# Secure-OSINT-FaceID

**Privacy-First OSINT Smart Doorbell** — a local-first face recognition doorbell with a human-gated OSINT layer for unknown visitors, built on FastAPI, MediaPipe, DeepFace, and a React/Vite dashboard.

Built by **[Vaibhav Verma](https://vaaiiibbhav.vercel.app/)** — [Portfolio](https://vaaiiibbhav.vercel.app/) · [GitHub](https://github.com/vaaiiibbhav) · [LinkedIn](https://www.linkedin.com/in/vaibhav-verma-905a1b270/)

---

## What it does

Point a webcam at your door. The system detects faces, checks liveness to reject printed-photo spoofing, and matches against a locally-enrolled family database:

- **Known + live face, above your threshold** → door unlocks, green "ACCESS GRANTED" state.
- **Unknown face** → red alert, the visitor is logged and their photo is queued for review — *not* automatically searched. An operator has to explicitly click "Investigate" before any public-web lookup runs, because a stranger at the door hasn't consented to a reverse-image search.

Everything — embeddings, photos, activity logs — stays on disk under `family_data/`. Nothing is sent anywhere unless you deliberately trigger an OSINT lookup on a specific visitor.

## Key features

- **5 FPS real-time webcam streaming** — the dashboard captures canvas frames and posts base64 JPEGs to `/detect` roughly every 200ms for a responsive live overlay (bounding boxes, liveness/spoof indicators).
- **MediaPipe face detection & landmarks** — the current Tasks API (`FaceLandmarker`), yielding both the face region and a dense 3D mesh in one pass.
- **DeepFace (ArcFace) vector matching** — robust recognition embeddings, with an automatic fallback to a geometric MediaPipe-landmark embedding if DeepFace isn't installed.
- **3D liveness / anti-spoof** — rejects flat printed photos using Z-depth variance across the mesh.
- **Instant face enrollment** — capture a frame from the webcam or upload a photo, enroll a name, and the recognition index updates immediately — no server restart.
- **Dynamic accuracy threshold** — a live slider (default `0.65`) tunes match strictness for unlocking, applied instantly via `PUT /settings/threshold`.
- **Background Selenium OSINT lookup** — headless, rate-limited, and strictly human-gated: unknown visitors are queued automatically, but the reverse-image search only runs on an explicit per-event "Investigate" action.
- **Activity & audit dashboard** — timestamped log of every event (name, known/unknown status, confidence, OSINT status) plus a photo gallery of queued unknown visitors.

## Architecture

```
facial_engine.py   Isolated vision layer: detection, embeddings, liveness, the local face database.
scraper.py         Headless Selenium OSINT layer: public web search + reverse-image lookup.
main.py            FastAPI orchestration: HTTP endpoints, activity log, OSINT queue.
frontend/          React + Vite + Tailwind dashboard (live feed, lock panel, audit, enrollment).
family_data/       Local storage: face embeddings, enrolled photos, unknown-visitor queue, logs.
```

`facial_engine.py` and `scraper.py` know nothing about each other or about HTTP — `main.py` is the only place that wires them together.

## Quick start

Requires **Python 3.11** and **Node 18+**.

### 1. Backend (FastAPI, port 8000)

```bash
python -m venv venv
venv\Scripts\activate        # Windows; use `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt

uvicorn main:app --reload --port 8000
```

The first run downloads the MediaPipe face landmark model into `models/` and, if DeepFace is installed, its ArcFace weights on first use. API docs are available at `http://localhost:8000/docs`.

### 2. Frontend (Vite dashboard, port 5173)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` with both servers running.

## Privacy & ethics

This project is built around one hard rule: **no automatic identification of non-consenting people.** Known family members are recognized locally because they consented to enrollment. Unknown visitors are logged and their photo is held for review, but the OSINT reverse-image step never fires on its own — it requires an explicit, per-visitor operator action. If you deploy something like this in the real world, pair it with visible camera signage and check your local recording/biometric-data laws.
