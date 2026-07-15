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

import json
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from facial_engine import FacialEngine
from scraper import OSINTScraper

DATA_DIR = Path("family_data")
LOG_FILE = DATA_DIR / "logs" / "activity_log.json"


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

    def log(self, event_type: str, name: str, is_known: bool, confidence: float, details: str = "") -> dict:
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
        }
        self.events.append(event)
        self.events = self.events[-self.cap :]
        self.path.write_text(json.dumps(self.events, indent=2), encoding="utf-8")
        return event

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


def engine() -> FacialEngine:
    return state["engine"]


def logger() -> ActivityLogger:
    return state["logger"]


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class SearchRequest(BaseModel):
    query: str
    max_results: int = 10


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
    """Detect + identify every face in an uploaded image."""
    img = await _read_image(file)
    results = engine().recognize(img)

    for r in results:
        event = "spoof_detected" if r.spoof else ("known" if r.is_known else "unknown")
        logger().log(event, r.name, r.is_known, r.confidence)

    return {"count": len(results), "faces": [r.to_dict() for r in results]}


# --------------------------------------------------------------------------- #
# Identity database
# --------------------------------------------------------------------------- #
@app.get("/faces")
def list_faces():
    return engine().list_faces()


@app.post("/faces")
async def enroll_face(name: str = Form(...), notes: str = Form(""), file: UploadFile = File(...)):
    """Enroll a new identity from an uploaded photo."""
    img = await _read_image(file)
    if not engine().add_face(name, img, notes):
        raise HTTPException(status_code=422, detail="No usable face found in the image.")
    logger().log("enroll", name, True, 1.0, notes)
    return {"status": "enrolled", "name": name}


@app.delete("/faces/{name}")
def delete_face(name: str):
    if not engine().remove_face(name):
        raise HTTPException(status_code=404, detail=f"'{name}' not found.")
    return {"status": "removed", "name": name}


# --------------------------------------------------------------------------- #
# OSINT
# --------------------------------------------------------------------------- #
@app.post("/osint/search")
def osint_search(req: SearchRequest):
    """Run a public web search for a name/handle/keyword pivot."""
    with OSINTScraper() as osint:
        hits = osint.web_search(req.query, max_results=req.max_results)
    return {"query": req.query, "count": len(hits), "results": [h.to_dict() for h in hits]}


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
