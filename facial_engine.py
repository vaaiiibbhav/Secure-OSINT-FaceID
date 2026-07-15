"""
facial_engine.py
================
Isolated computer-vision layer for Secure-OSINT-FaceID.

This module owns everything that touches pixels and knows nothing about the web
server or the OSINT scraper. It exposes a single :class:`FacialEngine` that:

  * detects faces + extracts 3D landmarks (MediaPipe **Tasks** FaceLandmarker),
  * builds recognition embeddings (DeepFace / ArcFace, with a landmark fallback),
  * checks 3D liveness to reject printed-photo spoofing,
  * persists a small "known faces" database to disk.

Everything here operates on in-memory ``numpy`` BGR image arrays (OpenCV's native
format). No camera capture, no windows, no HTTP — that lives in ``main.py``.

MediaPipe API note
------------------
MediaPipe 0.10.x removed the legacy ``mp.solutions.*`` API (and there is no
``mediapipe.python.solutions`` package either). This module uses the current
**Tasks** API: :class:`mediapipe.tasks.python.vision.FaceLandmarker`, which is a
single model that yields both the face region and the dense 3D landmark mesh.
The ``.task`` model bundle is downloaded on first use and cached under ``models/``.

Dependencies: opencv-python, mediapipe>=0.10, numpy, scikit-learn,
deepface (optional but recommended; requires ``tf-keras`` alongside TensorFlow).
"""

from __future__ import annotations

import json
import pickle
import sys
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# DeepFace and MediaPipe emit emoji-laden log lines (e.g. "🔗 downloading ...").
# Windows consoles default to cp1252 and raise UnicodeEncodeError on those
# characters, which -- because DeepFace wraps *any* exception during weight
# download as a generic failure -- silently breaks model loading. Force UTF-8 on
# the standard streams so third-party (and our own) logging can never crash the
# vision pipeline. Must run before importing DeepFace.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:  # pragma: no cover - non-reconfigurable stream
        pass

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core.base_options import BaseOptions
from sklearn.metrics.pairwise import cosine_similarity

# DeepFace is heavy (pulls TensorFlow) and downloads model weights on first use.
# Keep it optional so the engine still runs on a bare install using the
# MediaPipe-landmark embedding fallback -- but make any import failure LOUD so we
# never silently degrade recognition quality without the operator noticing.
_DEEPFACE_AVAILABLE = False
_DEEPFACE_IMPORT_ERROR: Optional[str] = None
try:
    from deepface import DeepFace

    _DEEPFACE_AVAILABLE = True
except Exception as _exc:  # pragma: no cover - depends on local install
    DeepFace = None
    _DEEPFACE_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"
    print(
        "[FacialEngine] WARNING: DeepFace failed to import -- ArcFace recognition "
        f"is unavailable and the engine will use the weaker 'landmarks' backend.\n"
        f"              Reason: {_DEEPFACE_IMPORT_ERROR}\n"
        "              Fix: `pip install tf-keras` (TensorFlow 2.16+ defaults to "
        "Keras 3, which DeepFace/retinaface cannot use directly)."
    )


# Official MediaPipe model bundle for the Face Landmarker task.
_FACE_LANDMARKER_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
_MODELS_DIR = Path(__file__).resolve().parent / "models"


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
        ``"landmarks"`` (MediaPipe mesh geometry, no model download).
        Falls back to ``"landmarks"`` automatically if DeepFace is missing.
    model_name:
        DeepFace model when ``backend="deepface"``. ArcFace is a good default.
    max_faces:
        Maximum number of faces the landmarker will return per frame.
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
        liveness_min_depth: float = 0.02,
        max_faces: int = 5,
        model_path: Optional[str] = None,
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

        # MediaPipe Tasks FaceLandmarker: one model gives both the face region
        # (derived from the landmark hull) and the dense 3D mesh used for
        # liveness and, in landmark mode, the recognition embedding.
        resolved_model = Path(model_path) if model_path else self._ensure_model()
        options = vision.FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(resolved_model)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=max_faces,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
            min_tracking_confidence=0.5,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

        self.load()

    # ------------------------------------------------------------------ #
    # Model management
    # ------------------------------------------------------------------ #
    @staticmethod
    def _ensure_model() -> Path:
        """Return the local FaceLandmarker model path, downloading it if absent."""
        _MODELS_DIR.mkdir(parents=True, exist_ok=True)
        dst = _MODELS_DIR / "face_landmarker.task"
        if not dst.exists():
            print(f"[FacialEngine] Downloading FaceLandmarker model -> {dst} ...")
            urllib.request.urlretrieve(_FACE_LANDMARKER_URL, dst)
            print(f"[FacialEngine] Model ready ({dst.stat().st_size} bytes).")
        return dst

    # ------------------------------------------------------------------ #
    # Core inference (single landmarker pass shared by detect/mesh/recognize)
    # ------------------------------------------------------------------ #
    def _analyze(self, image: np.ndarray) -> list[dict]:
        """
        Run the landmarker once and return one entry per detected face:
        ``{"bbox": (x, y, w, h), "landmarks": np.ndarray(shape=(N*3,))}``.
        """
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        result = self._landmarker.detect(mp_image)

        h, w = image.shape[:2]
        faces: list[dict] = []
        if not result.face_landmarks:
            return faces

        for landmarks in result.face_landmarks:
            xs = np.fromiter((lm.x for lm in landmarks), dtype=np.float32)
            ys = np.fromiter((lm.y for lm in landmarks), dtype=np.float32)
            flat = np.array([[lm.x, lm.y, lm.z] for lm in landmarks], dtype=np.float32).flatten()

            x0 = max(0, int(xs.min() * w))
            y0 = max(0, int(ys.min() * h))
            x1 = min(w, int(xs.max() * w))
            y1 = min(h, int(ys.max() * h))
            faces.append({"bbox": (x0, y0, x1 - x0, y1 - y0), "landmarks": flat})
        return faces

    # ------------------------------------------------------------------ #
    # Low-level vision helpers (public API preserved)
    # ------------------------------------------------------------------ #
    def detect_faces(self, image: np.ndarray) -> list[dict]:
        """Return bounding boxes for every detected face: ``{bbox, confidence}``."""
        return [{"bbox": f["bbox"], "confidence": 1.0} for f in self._analyze(image)]

    def _mesh_landmarks(self, image: np.ndarray) -> list[np.ndarray]:
        """Return one flat ``(N*3,)`` landmark array per detected face."""
        return [f["landmarks"] for f in self._analyze(image)]

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
    def embed(
        self,
        image: np.ndarray,
        bbox: Optional[tuple[int, int, int, int]] = None,
        landmarks: Optional[np.ndarray] = None,
    ) -> Optional[np.ndarray]:
        """
        Produce a single normalized embedding for the (optionally cropped) face.

        Uses DeepFace when the backend allows it; otherwise derives a geometric
        embedding from the MediaPipe mesh. ``landmarks`` may be supplied to reuse
        an existing landmarker pass. Returns ``None`` if no face is usable.
        """
        if self.backend == "deepface":
            face_img = self._crop(image, bbox) if bbox is not None else image
            try:
                reps = DeepFace.represent(
                    img_path=face_img,
                    model_name=self.model_name,
                    enforce_detection=False,
                    detector_backend="skip",
                )
                if not reps:
                    return None
                vec = np.asarray(reps[0]["embedding"], dtype=np.float32)
                return self._l2(vec)
            except Exception as exc:  # pragma: no cover
                print(f"[FacialEngine] DeepFace embed failed: {exc}")
                return None

        # landmarks backend
        if landmarks is None:
            face_img = self._crop(image, bbox) if bbox is not None else image
            meshes = self._mesh_landmarks(face_img)
            if not meshes:
                return None
            landmarks = meshes[0]
        return self._geometric_embedding(landmarks)

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
    @staticmethod
    def _depth_variance(flat_landmarks: np.ndarray) -> float:
        z = flat_landmarks.reshape(-1, 3)[:, 2]
        return float(np.ptp(z))

    def check_liveness(self, image: np.ndarray) -> bool:
        """
        Cheap 3D anti-spoof: a real face has meaningful Z-depth variance across
        the mesh, a printed photo is (nearly) planar. Returns ``True`` if live.
        """
        meshes = self._mesh_landmarks(image)
        if not meshes:
            return False
        return self._depth_variance(meshes[0]) > self.liveness_min_depth

    # ------------------------------------------------------------------ #
    # Recognition
    # ------------------------------------------------------------------ #
    def recognize(self, image: np.ndarray) -> list[FaceResult]:
        """
        Detect and identify every face in ``image``.

        Runs the landmarker once, then for each face builds an embedding, checks
        liveness from the same landmark set, and matches against the database.
        Spoofed (non-live) matches are flagged instead of being trusted.
        """
        faces = self._analyze(image)
        results: list[FaceResult] = []

        for face in faces:
            bbox = face["bbox"]
            lm = face["landmarks"]
            emb = self.embed(image, bbox=bbox, landmarks=lm)
            if emb is None:
                continue

            live = self._depth_variance(lm) > self.liveness_min_depth

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
        faces = self._analyze(image)
        if not faces:
            print(f"[FacialEngine] No face detected while enrolling '{name}'.")
            return False

        largest = max(faces, key=lambda f: f["bbox"][2] * f["bbox"][3])
        emb = self.embed(image, bbox=largest["bbox"], landmarks=largest["landmarks"])
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
        self._landmarker.close()
