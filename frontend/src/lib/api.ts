/**
 * Typed client for the Secure-OSINT-FaceID FastAPI backend.
 * Backend source: ../../../main.py, facial_engine.py, scraper.py
 */

export const API_BASE = "http://localhost:8000";

export interface FaceResult {
  name: string;
  is_known: boolean;
  confidence: number;
  bbox: [number, number, number, number]; // x, y, w, h
  is_live: boolean;
  spoof: boolean;
}

export interface DetectResponse {
  count: number;
  faces: FaceResult[];
}

export interface FaceMember {
  name: string;
  backend: string;
  notes: string;
  added_date: string;
  total_detections: number;
  last_seen: string | null;
  photo_url: string | null;
}

export interface FacesResponse {
  backend: string;
  threshold: number;
  total: number;
  members: FaceMember[];
}

export interface ActivityEvent {
  timestamp: string;
  date: string;
  time: string;
  event_type: string;
  name: string;
  is_known: boolean;
  confidence: number;
  details: string;
  event_id: string | null;
  osint_status: string | null;
}

export interface LogsResponse {
  events: ActivityEvent[];
}

export interface OSINTHit {
  title: string;
  url: string;
  snippet: string;
  source: string;
}

export interface OSINTQueueItem {
  event_id: string;
  status: "pending_review" | "completed" | "failed";
  timestamp: string;
  frame_url: string;
  results: OSINTHit[] | null;
}

export interface OSINTQueueResponse {
  count: number;
  items: OSINTQueueItem[];
}

export interface HealthResponse {
  status: string;
  backend: string;
  known_faces: number;
  threshold: number;
}

class ApiError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response wasn't JSON; keep statusText
    }
    throw new ApiError(detail, res.status);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health(): Promise<HealthResponse> {
    return fetch(`${API_BASE}/health`).then((r) => handle(r));
  },

  /**
   * High-frequency polling endpoint for the live-feed overlay. Debounced
   * server-side. Takes a base64-encoded JPEG frame (data-URL prefix optional).
   */
  detect(base64Image: string): Promise<DetectResponse> {
    return fetch(`${API_BASE}/detect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: base64Image }),
    }).then((r) => handle(r));
  },

  /** Full detect + always-logged recognition, used for explicit "verify" actions. */
  recognize(blob: Blob): Promise<DetectResponse> {
    const form = new FormData();
    form.append("file", blob, "frame.jpg");
    return fetch(`${API_BASE}/recognize`, { method: "POST", body: form }).then((r) => handle(r));
  },

  listFaces(): Promise<FacesResponse> {
    return fetch(`${API_BASE}/faces`).then((r) => handle(r));
  },

  enrollFace(name: string, notes: string, file: File | Blob): Promise<{ status: string; name: string }> {
    const form = new FormData();
    form.append("name", name);
    form.append("notes", notes);
    form.append("file", file, "enroll.jpg");
    return fetch(`${API_BASE}/enroll`, { method: "POST", body: form }).then((r) => handle(r));
  },

  removeFace(name: string): Promise<{ status: string; name: string }> {
    return fetch(`${API_BASE}/faces/${encodeURIComponent(name)}`, { method: "DELETE" }).then((r) => handle(r));
  },

  /** Runtime door-unlock matching strictness (0-1). No server restart needed. */
  updateThreshold(threshold: number): Promise<{ threshold: number }> {
    return fetch(`${API_BASE}/settings/threshold`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ threshold }),
    }).then((r) => handle(r));
  },

  logs(count = 20): Promise<LogsResponse> {
    return fetch(`${API_BASE}/logs?count=${count}`).then((r) => handle(r));
  },

  osintQueue(): Promise<OSINTQueueResponse> {
    return fetch(`${API_BASE}/osint/queue`).then((r) => handle(r));
  },

  /** Explicit, operator-triggered reverse-image lookup for one queued visitor frame. */
  osintInvestigate(eventId: string): Promise<OSINTQueueItem> {
    return fetch(`${API_BASE}/osint/investigate/${encodeURIComponent(eventId)}`, { method: "POST" }).then((r) =>
      handle(r),
    );
  },

  osintSearch(query: string, maxResults = 10): Promise<{ query: string; count: number; results: OSINTHit[] }> {
    return fetch(`${API_BASE}/osint/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, max_results: maxResults }),
    }).then((r) => handle(r));
  },
};

export { ApiError };
