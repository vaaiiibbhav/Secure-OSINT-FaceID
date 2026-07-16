"""
main.py
=======
FastAPI application for Secure-OSINT-FaceID.

This is the orchestration layer. It owns the HTTP surface and wires together the
two isolated subsystems:

  * :class:`facial_engine.FacialEngine` — detection / recognition / liveness
  * :class:`scraper.OSINTScraper`       — headless public-web OSINT lookups

Run it with::

    uvicorn main:app --reload --port 8000

Then open the interactive docs at http://localhost:8000/docs
"""

from __future__ import annotations

import base64
import json
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from facial_engine import FacialEngine
from scraper import OSINTScraper

DATA_DIR = Path("family_data")
LOG_FILE = DATA_DIR / "logs" / "activity_log.json"
UNKNOWN_DIR = DATA_DIR / "unknown"

# The live-feed panel polls /detect frequently (roughly once a second), which
# would otherwise flood the activity log and re-queue the same visitor for
# OSINT review on every single frame. These cooldowns debounce that per
# "who" (a known member's name, or the single shared "unknown" bucket).
KNOWN_LOG_COOLDOWN_SECONDS = 15.0
UNKNOWN_OSINT_COOLDOWN_SECONDS = 20.0


# --------------------------------------------------------------------------- #
# Lightweight activity logger (kept here so the vision engine stays pure)
# --------------------------------------------------------------------------- #
class ActivityLogger:
    """Append-only JSON event log, capped to the most recent events."""

    def __init__(self, path: Path = LOG_FILE, cap: int = 1000):
        self.path = path
        self.cap = cap
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []
        if self.path.exists():
            try:
                self.events = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.events = []

    def log(
        self,
        event_type: str,
        name: str,
        is_known: bool,
        confidence: float,
        details: str = "",
        event_id: Optional[str] = None,
        osint_status: Optional[str] = None,
    ) -> dict:
        now = datetime.now()
        event = {
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "event_type": event_type,
            "name": name,
            "is_known": is_known,
            "confidence": round(float(confidence), 3),
            "details": details,
            "event_id": event_id,
            "osint_status": osint_status,
        }
        self.events.append(event)
        self.events = self.events[-self.cap :]
        self.path.write_text(json.dumps(self.events, indent=2), encoding="utf-8")
        return event

    def set_osint_status(self, event_id: str, status: str) -> None:
        """Patch a previously logged event's OSINT status, found by event_id."""
        for event in reversed(self.events):
            if event.get("event_id") == event_id:
                event["osint_status"] = status
                self.path.write_text(json.dumps(self.events, indent=2), encoding="utf-8")
                return

    def recent(self, count: int = 20) -> list[dict]:
        return self.events[-count:][::-1]


# --------------------------------------------------------------------------- #
# App state / lifecycle
# --------------------------------------------------------------------------- #
state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: build the heavy vision engine once and reuse it.
    state["engine"] = FacialEngine(data_dir=str(DATA_DIR))
    state["logger"] = ActivityLogger()
    state["cooldowns"] = {}  # "known:<name>" | "unknown" -> last-trigger unix ts
    state["osint_queue"] = {}  # event_id -> {status, timestamp, frame_path, results}
    UNKNOWN_DIR.mkdir(parents=True, exist_ok=True)
    print("[main] Secure-OSINT-FaceID API ready.")
    yield
    # Shutdown: release MediaPipe/OpenCV handles.
    state["engine"].close()
    print("[main] Shutdown complete.")


app = FastAPI(
    title="Secure-OSINT-FaceID",
    description="Face recognition + liveness with an isolated public-web OSINT layer.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to your frontend origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _read_image(upload: UploadFile) -> np.ndarray:
    """Decode an uploaded image into an OpenCV BGR array."""
    raw = await upload.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload.")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Could not decode image.")
    return img


def _decode_base64_image(data: str) -> tuple[np.ndarray, bytes]:
    """Decode a base64 (optionally ``data:image/...;base64,``-prefixed) frame."""
    if data.strip().lower().startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data, validate=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image data: {exc}") from exc
    if not raw:
        raise HTTPException(status_code=400, detail="Empty image data.")
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Could not decode image.")
    return img, raw


def engine() -> FacialEngine:
    return state["engine"]


def logger() -> ActivityLogger:
    return state["logger"]


def _cooldown_ready(key: str, window_seconds: float) -> bool:
    """True (and resets the clock) if `key` hasn't fired within `window_seconds`."""
    now = time.monotonic()
    last = state["cooldowns"].get(key, 0.0)
    if now - last < window_seconds:
        return False
    state["cooldowns"][key] = now
    return True


def _queue_for_osint_review(event_id: str, frame_bytes: bytes) -> None:
    """
    Background task: persist the triggering frame and mark it pending review.

    Deliberately does NOT run a reverse-image search automatically. An unknown
    visitor at the door hasn't consented to being searched across the public
    web, so that step requires an explicit operator action — see
    POST /osint/investigate/{event_id}. This task only makes the frame
    available for that decision.
    """
    frame_path = UNKNOWN_DIR / f"{event_id}.jpg"
    frame_path.write_bytes(frame_bytes)
    state["osint_queue"][event_id] = {
        "event_id": event_id,
        "status": "pending_review",
        "timestamp": datetime.now().isoformat(),
        "frame_path": str(frame_path),
        "results": None,
    }


def _public_queue_item(item: dict) -> dict:
    """Client-facing view of a queue entry -- omits the server filesystem path."""
    return {
        "event_id": item["event_id"],
        "status": item["status"],
        "timestamp": item["timestamp"],
        "results": item["results"],
        "frame_url": f"/osint/unknown/{item['event_id']}/photo",
    }


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class SearchRequest(BaseModel):
    query: str
    max_results: int = 10


class DetectRequest(BaseModel):
    image: str  # base64, optionally "data:image/jpeg;base64,..." prefixed


class ThresholdRequest(BaseModel):
    threshold: float


# --------------------------------------------------------------------------- #
# Health & metadata
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    eng = engine()
    return {
        "status": "ok",
        "backend": eng.backend,
        "known_faces": len(eng.known_faces),
        "threshold": eng.recognition_threshold,
    }


# --------------------------------------------------------------------------- #
# Recognition
# --------------------------------------------------------------------------- #
@app.post("/recognize")
async def recognize(file: UploadFile = File(...)):
    """Detect + identify every face in an uploaded image. Always logs."""
    img = await _read_image(file)
    results = engine().recognize(img)

    for r in results:
        event = "spoof_detected" if r.spoof else ("known" if r.is_known else "unknown")
        logger().log(event, r.name, r.is_known, r.confidence)

    return {"count": len(results), "faces": [r.to_dict() for r in results]}


@app.post("/detect")
async def detect(req: DetectRequest, background_tasks: BackgroundTasks):
    """
    Lightweight detection for the live-feed overlay.

    Accepts a base64-encoded JPEG frame so the browser can POST straight from a
    canvas capture. Meant to be polled at high frequency (the dashboard runs
    this at ~5 FPS), so unlike /recognize it does not log every single frame.
    Instead it debounces: a known face logs at most once per cooldown window,
    and an unknown *live* (non-spoofed) face schedules a background task that
    queues the frame for optional, operator-triggered OSINT review.
    """
    img, raw = _decode_base64_image(req.image)
    results = engine().recognize(img)

    for r in results:
        if r.spoof:
            if _cooldown_ready("spoof", KNOWN_LOG_COOLDOWN_SECONDS):
                logger().log("spoof_detected", r.name, False, r.confidence)
        elif r.is_known:
            if _cooldown_ready(f"known:{r.name}", KNOWN_LOG_COOLDOWN_SECONDS):
                logger().log("known", r.name, True, r.confidence)
        else:
            if r.is_live and _cooldown_ready("unknown", UNKNOWN_OSINT_COOLDOWN_SECONDS):
                event_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
                logger().log(
                    "unknown_detected",
                    r.name,
                    False,
                    r.confidence,
                    "Queued for OSINT review",
                    event_id=event_id,
                    osint_status="pending_review",
                )
                background_tasks.add_task(_queue_for_osint_review, event_id, raw)

    return {"count": len(results), "faces": [r.to_dict() for r in results]}


# --------------------------------------------------------------------------- #
# Identity database
# --------------------------------------------------------------------------- #
@app.get("/faces")
def list_faces():
    data = engine().list_faces()
    for member in data["members"]:
        has_photo = engine().latest_photo_path(member["name"]) is not None
        member["photo_url"] = f"/faces/{member['name']}/photo" if has_photo else None
    return data


@app.get("/faces/{name}/photo")
def face_photo(name: str):
    path = engine().latest_photo_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"No photo on file for '{name}'.")
    return FileResponse(path)


async def _enroll(name: str, notes: str, file: UploadFile) -> dict:
    img = await _read_image(file)
    if not engine().add_face(name, img, notes):
        raise HTTPException(status_code=422, detail="No usable face found in the image.")
    logger().log("enroll", name, True, 1.0, notes)
    return {"status": "enrolled", "name": name}


@app.post("/enroll")
async def enroll_face(name: str = Form(...), notes: str = Form(""), file: UploadFile = File(...)):
    """Enroll a new identity -- from a webcam capture or an uploaded photo."""
    return await _enroll(name, notes, file)


@app.post("/faces")
async def enroll_face_legacy(name: str = Form(...), notes: str = Form(""), file: UploadFile = File(...)):
    """Alias of POST /enroll (kept for backward compatibility)."""
    return await _enroll(name, notes, file)


@app.delete("/faces/{name}")
def delete_face(name: str):
    if not engine().remove_face(name):
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")
    return {"status": "removed", "name": name}


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
@app.put("/settings/threshold")
def update_threshold(req: ThresholdRequest):
    """Adjust the door-unlock matching strictness at runtime -- no restart needed."""
    if not 0.0 <= req.threshold <= 1.0:
        raise HTTPException(status_code=422, detail="threshold must be between 0.0 and 1.0.")
    engine().recognition_threshold = req.threshold
    engine().save()
    return {"threshold": engine().recognition_threshold}


# --------------------------------------------------------------------------- #
# OSINT
# --------------------------------------------------------------------------- #
@app.post("/osint/search")
def osint_search(req: SearchRequest):
    """Run a public web search for a name/handle/keyword pivot."""
    with OSINTScraper() as osint:
        hits = osint.web_search(req.query, max_results=req.max_results)
    return {"query": req.query, "count": len(hits), "results": [h.to_dict() for h in hits]}


@app.get("/osint/queue")
def osint_queue():
    """Unknown-visitor frames queued by /detect, newest first -- the visitor gallery."""
    items = sorted(state["osint_queue"].values(), key=lambda e: e["timestamp"], reverse=True)
    return {"count": len(items), "items": [_public_queue_item(i) for i in items]}


@app.get("/osint/unknown/{event_id}/photo")
def unknown_photo(event_id: str):
    entry = state["osint_queue"].get(event_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No queued event '{event_id}'.")
    return FileResponse(entry["frame_path"])


@app.post("/osint/investigate/{event_id}")
def osint_investigate(event_id: str):
    """
    Explicitly run a reverse-image lookup for a queued unknown-visitor frame.

    This is the one step in the pipeline that actually searches the public web
    for a stranger's face, so it never fires automatically — the operator must
    trigger it per event after reviewing the frame.
    """
    entry = state["osint_queue"].get(event_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No queued event '{event_id}'.")

    try:
        with OSINTScraper() as osint:
            hits = osint.reverse_image_search(entry["frame_path"])
        entry["results"] = [h.to_dict() for h in hits]
        entry["status"] = "completed"
        logger().set_osint_status(event_id, "completed")
    except Exception as exc:
        entry["status"] = "failed"
        entry["results"] = []
        logger().set_osint_status(event_id, "failed")
        raise HTTPException(status_code=502, detail=f"OSINT lookup failed: {exc}") from exc

    return _public_queue_item(entry)


@app.post("/osint/reverse-image")
async def osint_reverse_image(file: UploadFile = File(...), max_results: int = Form(10)):
    """
    Reverse-image lookup for an uploaded photo.

    Intended for images you own or are authorized to investigate. Results are
    best-effort — reverse-image surfaces frequently block headless automation.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload.")

    suffix = Path(file.filename or "upload.jpg").suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        with OSINTScraper() as osint:
            hits = osint.reverse_image_search(tmp_path, max_results=max_results)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {"count": len(hits), "results": [h.to_dict() for h in hits]}


# --------------------------------------------------------------------------- #
# Activity log
# --------------------------------------------------------------------------- #
@app.get("/logs")
def logs(count: int = 20):
    return {"events": logger().recent(count)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
