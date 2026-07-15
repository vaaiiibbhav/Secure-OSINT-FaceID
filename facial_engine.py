"""
facial_engine.py
================
Isolated computer-vision layer for Secure-OSINT-FaceID.

This module owns everything that touches pixels and knows nothing about the web
server or the OSINT scraper. It exposes a single :class:`FacialEngine` that:

  * detects faces (MediaPipe Face Detection),
  * builds recognition embeddings (DeepFace / ArcFace, with a landmark fallback),
  * checks 3D liveness to reject printed-photo spoofing (MediaPipe Face Mesh),
  * persists a small "known faces" database to disk.

Everything here operates on in-memory ``numpy`` BGR image arrays (OpenCV's native
format). No camera capture, no windows, no HTTP — that lives in ``main.py``.

Dependencies: opencv-python, mediapipe, numpy, scikit-learn, deepface (optional).
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import mediapipe as mp
from sklearn.metrics.pairwise import cosine_similarity

# DeepFace is heavy (pulls TensorFlow) and downloads model weights on first use.
# Keep it optional so the engine still runs on a bare install using the
# MediaPipe-landmark embedding fallback.
try:
    from deepface import DeepFace

    _DEEPFACE_AVAILABLE = True
except Exception:  # pragma: no cover - depends on local install
    DeepFace = None
    _DEEPFACE_AVAILABLE = False


# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #
@dataclass
class FaceResult:
    """One recognized (or unrecognized) face in a frame."""

    name: str
    is_known: bool
    confidence: float
    bbox: tuple[int, int, int, int]  # (x, y, w, h)
    is_live: bool = True
    spoof: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bbox"] = list(self.bbox)
        return d


@dataclass
class KnownFace:
    """A stored identity: one embedding plus bookkeeping metadata."""

    name: str
    embedding: np.ndarray
    backend: str
    notes: str = ""
    added_date: str = field(default_factory=lambda: datetime.now().isoformat())
    total_detections: int = 0
    last_seen: Optional[str] = None

    def meta(self) -> dict:
        """JSON-friendly metadata (no raw embedding vector)."""
        return {
            "name": self.name,
            "backend": self.backend,
            "notes": self.notes,
            "added_date": self.added_date,
            "total_detections": self.total_detections,
            "last_seen": self.last_seen,
        }


class FacialEngine:
    """
    Detection + recognition + liveness over a small local identity database.

    Parameters
    ----------
    data_dir:
        Folder for the persisted database (``faces.pkl`` + ``faces_info.json``).
    backend:
        ``"deepface"`` (ArcFace embeddings, robust to pose/lighting) or
        ``"landmarks"`` (468 MediaPipe mesh points, no model download).
        Falls back to ``"landmarks"`` automatically if DeepFace is missing.
    model_name:
        DeepFace model when ``backend="deepface"``. ArcFace is a good default.
    """

    # Similarity thresholds are backend-specific because the embedding spaces
    # are completely different. ArcFace cosine similarity for a genuine match is
    # typically well above ~0.40; raw face-mesh geometry sits much higher because
    # all human faces are structurally similar, hence the strict 0.96.
    _DEFAULT_THRESHOLDS = {"deepface": 0.40, "landmarks": 0.96}

    def __init__(
        self,
        data_dir: str = "family_data",
        backend: str = "deepface",
        model_name: str = "ArcFace",
        recognition_threshold: Optional[float] = None,
        liveness_min_depth: float = 0.05,
    ):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        if backend == "deepface" and not _DEEPFACE_AVAILABLE:
            print("[FacialEngine] DeepFace unavailable -> falling back to 'landmarks' backend.")
            backend = "landmarks"
        self.backend = backend
        self.model_name = model_name
        self.recognition_threshold = (
            recognition_threshold
            if recognition_threshold is not None
            else self._DEFAULT_THRESHOLDS[backend]
        )
        self.liveness_min_depth = liveness_min_depth

        self.known_faces: list[KnownFace] = []

        # MediaPipe primitives. Face detection localizes; face mesh gives the
        # dense 3D landmarks used for liveness (and landmark-mode embeddings).
        mp_fd = mp.solutions.face_detection
        mp_fm = mp.solutions.face_mesh
        self._face_detection = mp_fd.FaceDetection(model_selection=1, min_detection_confidence=0.5)
        self._face_mesh = mp_fm.FaceMesh(
            static_image_mode=True,
            max_num_faces=5,
            refine_landmarks=True,
            min_detection_confidence=0.5,
        )

        self.load()

    # ------------------------------------------------------------------ #
    # Low-level vision helpers
    # ------------------------------------------------------------------ #
    def detect_faces(self, image: np.ndarray) -> list[dict]:
        """Return bounding boxes for every detected face: ``{bbox, confidence}``."""
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self._face_detection.process(rgb)

        faces: list[dict] = []
        if results.detections:
            h, w = image.shape[:2]
            for det in results.detections:
                box = det.location_data.relative_bounding_box
                x = max(0, int(box.xmin * w))
                y = max(0, int(box.ymin * h))
                bw = int(box.width * w)
                bh = int(box.height * h)
                faces.append({"bbox": (x, y, bw, bh), "confidence": float(det.score[0])})
        return faces

    def _mesh_landmarks(self, image: np.ndarray) -> list[np.ndarray]:
        """Return one flat (468*3,) landmark array per detected face."""
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self._face_mesh.process(rgb)

        out: list[np.ndarray] = []
        if results.multi_face_landmarks:
            for face in results.multi_face_landmarks:
                pts = np.array([[lm.x, lm.y, lm.z] for lm in face.landmark], dtype=np.float32)
                out.append(pts.flatten())
        return out

    @staticmethod
    def _crop(image: np.ndarray, bbox: tuple[int, int, int, int], pad: float = 0.2) -> np.ndarray:
        """Crop a padded face region, clamped to image bounds."""
        h, w = image.shape[:2]
        x, y, bw, bh = bbox
        px, py = int(bw * pad), int(bh * pad)
        x0, y0 = max(0, x - px), max(0, y - py)
        x1, y1 = min(w, x + bw + px), min(h, y + bh + py)
        return image[y0:y1, x0:x1]

    # ------------------------------------------------------------------ #
    # Embeddings
    # ------------------------------------------------------------------ #
    def embed(self, image: np.ndarray, bbox: Optional[tuple[int, int, int, int]] = None) -> Optional[np.ndarray]:
        """
        Produce a single normalized embedding for the (optionally cropped) face.

        Uses DeepFace when the backend allows it; otherwise derives a geometric
        embedding from the MediaPipe mesh. Returns ``None`` if no face is usable.
        """
        face_img = self._crop(image, bbox) if bbox is not None else image

        if self.backend == "deepface":
            try:
                reps = DeepFace.represent(
                    img_path=face_img,
                    model_name=self.model_name,
                    enforce_detection=False,
                    detector_backend="skip" if bbox is not None else "opencv",
                )
                if not reps:
                    return None
                vec = np.asarray(reps[0]["embedding"], dtype=np.float32)
                return self._l2(vec)
            except Exception as exc:  # pragma: no cover
                print(f"[FacialEngine] DeepFace embed failed: {exc}")
                return None

        # landmarks backend
        meshes = self._mesh_landmarks(face_img)
        if not meshes:
            return None
        return self._geometric_embedding(meshes[0])

    @staticmethod
    def _geometric_embedding(flat_landmarks: np.ndarray) -> np.ndarray:
        """Translation- and scale-invariant embedding from raw mesh points."""
        pts = flat_landmarks.reshape(-1, 3)
        pts = pts - pts.mean(axis=0)  # translation invariant
        return FacialEngine._l2(pts.flatten())

    @staticmethod
    def _l2(vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    # ------------------------------------------------------------------ #
    # Liveness
    # ------------------------------------------------------------------ #
    def check_liveness(self, image: np.ndarray) -> bool:
        """
        Cheap 3D anti-spoof: a real face has meaningful Z-depth variance across
        the mesh, a printed photo is (nearly) planar. Returns ``True`` if live.
        """
        meshes = self._mesh_landmarks(image)
        if not meshes:
            return False
        z = meshes[0].reshape(-1, 3)[:, 2]
        return bool(np.ptp(z) > self.liveness_min_depth)

    # ------------------------------------------------------------------ #
    # Recognition
    # ------------------------------------------------------------------ #
    def recognize(self, image: np.ndarray) -> list[FaceResult]:
        """
        Detect and identify every face in ``image``.

        Updates detection bookkeeping for matched identities and flags spoofed
        (non-live) matches instead of trusting them.
        """
        detections = self.detect_faces(image)
        results: list[FaceResult] = []

        for det in detections:
            bbox = det["bbox"]
            emb = self.embed(image, bbox)
            if emb is None:
                continue

            live = self.check_liveness(self._crop(image, bbox))

            if not self.known_faces:
                results.append(FaceResult("Unknown", False, 0.0, bbox, is_live=live))
                continue

            sims = [
                float(cosine_similarity(emb.reshape(1, -1), kf.embedding.reshape(1, -1))[0][0])
                for kf in self.known_faces
            ]
            best_idx = int(np.argmax(sims))
            best_sim = sims[best_idx]

            if best_sim >= self.recognition_threshold:
                kf = self.known_faces[best_idx]
                if live:
                    kf.total_detections += 1
                    kf.last_seen = datetime.now().isoformat()
                    results.append(FaceResult(kf.name, True, best_sim, bbox, is_live=True))
                else:
                    # Matched a known face geometry but failed liveness -> spoof.
                    results.append(
                        FaceResult(kf.name, False, best_sim, bbox, is_live=False, spoof=True)
                    )
            else:
                results.append(FaceResult("Unknown", False, best_sim, bbox, is_live=live))

        # Persist updated detection counters if anything matched.
        if any(r.is_known for r in results):
            self.save()
        return results

    # ------------------------------------------------------------------ #
    # Database management
    # ------------------------------------------------------------------ #
    def add_face(self, name: str, image: np.ndarray, notes: str = "") -> bool:
        """Enroll a new identity from an image. Uses the largest detected face."""
        detections = self.detect_faces(image)
        if not detections:
            print(f"[FacialEngine] No face detected while enrolling '{name}'.")
            return False

        largest = max(detections, key=lambda d: d["bbox"][2] * d["bbox"][3])
        emb = self.embed(image, largest["bbox"])
        if emb is None:
            print(f"[FacialEngine] Could not build an embedding for '{name}'.")
            return False

        self.known_faces.append(KnownFace(name=name, embedding=emb, backend=self.backend, notes=notes))
        self.save()
        print(f"[FacialEngine] Enrolled '{name}' ({len(self.known_faces)} total).")
        return True

    def remove_face(self, name: str) -> bool:
        """Remove every identity matching ``name`` (case-insensitive)."""
        before = len(self.known_faces)
        self.known_faces = [kf for kf in self.known_faces if kf.name.lower() != name.lower()]
        removed = before != len(self.known_faces)
        if removed:
            self.save()
            print(f"[FacialEngine] Removed '{name}'.")
        else:
            print(f"[FacialEngine] '{name}' not found.")
        return removed

    def list_faces(self) -> dict:
        """Summary of enrolled identities (safe to serialize / return over HTTP)."""
        return {
            "backend": self.backend,
            "threshold": self.recognition_threshold,
            "total": len(self.known_faces),
            "members": [kf.meta() for kf in self.known_faces],
        }

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def save(self) -> None:
        payload = {
            "backend": self.backend,
            "model_name": self.model_name,
            "threshold": self.recognition_threshold,
            "faces": [
                {
                    "name": kf.name,
                    "embedding": kf.embedding.tolist(),
                    "backend": kf.backend,
                    "notes": kf.notes,
                    "added_date": kf.added_date,
                    "total_detections": kf.total_detections,
                    "last_seen": kf.last_seen,
                }
                for kf in self.known_faces
            ],
        }
        with open(self.data_dir / "faces.pkl", "wb") as f:
            pickle.dump(payload, f)

        # Human-readable mirror (no embeddings) for dashboards / debugging.
        with open(self.data_dir / "faces_info.json", "w", encoding="utf-8") as f:
            json.dump(self.list_faces(), f, indent=2)

    def load(self) -> None:
        db = self.data_dir / "faces.pkl"
        if not db.exists():
            print("[FacialEngine] No existing database — starting fresh.")
            return
        try:
            with open(db, "rb") as f:
                payload = pickle.load(f)
            self.known_faces = [
                KnownFace(
                    name=item["name"],
                    embedding=np.asarray(item["embedding"], dtype=np.float32),
                    backend=item.get("backend", self.backend),
                    notes=item.get("notes", ""),
                    added_date=item.get("added_date", datetime.now().isoformat()),
                    total_detections=item.get("total_detections", 0),
                    last_seen=item.get("last_seen"),
                )
                for item in payload.get("faces", [])
            ]
            print(f"[FacialEngine] Loaded {len(self.known_faces)} identities.")
        except Exception as exc:  # pragma: no cover
            print(f"[FacialEngine] Failed to load database: {exc}")

    # ------------------------------------------------------------------ #
    # Visualization (optional convenience for debugging still frames)
    # ------------------------------------------------------------------ #
    @staticmethod
    def annotate(image: np.ndarray, results: list[FaceResult]) -> np.ndarray:
        """Draw corner-bracket boxes + labels. Returns a copy; never displays."""
        frame = image.copy()
        for r in results:
            x, y, w, h = r.bbox
            if r.spoof:
                color = (0, 0, 255)          # red: spoof
            elif r.is_known:
                color = (0, 255, 0)          # green: known
            else:
                color = (0, 165, 255)        # orange: unknown
            seg = int(w * 0.25)
            for (x0, y0, x1, y1) in [
                (x, y, x + seg, y), (x, y, x, y + seg),
                (x + w, y, x + w - seg, y), (x + w, y, x + w, y + seg),
                (x, y + h, x + seg, y + h), (x, y + h, x, y + h - seg),
                (x + w, y + h, x + w - seg, y + h), (x + w, y + h, x + w, y + h - seg),
            ]:
                cv2.line(frame, (x0, y0), (x1, y1), color, 2)
            label = f"{r.name} {r.confidence:.0%}" + (" SPOOF" if r.spoof else "")
            cv2.putText(frame, label, (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        return frame

    def close(self) -> None:
        self._face_detection.close()
        self._face_mesh.close()
