import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Camera, CameraOff, ShieldAlert, ShieldCheck, ShieldQuestion, Radio } from "lucide-react";
import { api, type FaceResult } from "../lib/api";

const POLL_INTERVAL_MS = 900;
const JPEG_QUALITY = 0.82;

type CameraState = "idle" | "requesting" | "active" | "denied" | "unavailable" | "error";

interface LiveCameraFeedProps {
  onFaces: (faces: FaceResult[]) => void;
}

function statusFor(face: FaceResult) {
  if (face.spoof) {
    return { color: "border-status-spoof text-status-spoof", label: "SPOOF DETECTED", Icon: ShieldAlert };
  }
  if (face.is_known) {
    return { color: "border-status-known text-status-known", label: "LIVENESS OK", Icon: ShieldCheck };
  }
  return { color: "border-status-unknown text-status-unknown", label: face.is_live ? "UNVERIFIED" : "NO LIVENESS", Icon: ShieldQuestion };
}

export function LiveCameraFeed({ onFaces }: LiveCameraFeedProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const captureCanvasRef = useRef<HTMLCanvasElement>(document.createElement("canvas"));
  const streamRef = useRef<MediaStream | null>(null);
  const inFlightRef = useRef(false);

  const [cameraState, setCameraState] = useState<CameraState>("idle");
  const [nativeSize, setNativeSize] = useState<{ w: number; h: number } | null>(null);
  const [displaySize, setDisplaySize] = useState({ w: 0, h: 0 });
  const [faces, setFaces] = useState<FaceResult[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const startCamera = useCallback(async () => {
    setCameraState("requesting");
    setErrorMsg(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraState("unavailable");
      setErrorMsg("This browser does not expose camera access (getUserMedia unavailable).");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setCameraState("active");
    } catch (err) {
      const name = err instanceof DOMException ? err.name : "Error";
      if (name === "NotAllowedError" || name === "PermissionDeniedError") {
        setCameraState("denied");
        setErrorMsg("Camera permission was denied. Allow camera access and retry.");
      } else if (name === "NotFoundError") {
        setCameraState("unavailable");
        setErrorMsg("No camera device was found on this machine.");
      } else {
        setCameraState("error");
        setErrorMsg(err instanceof Error ? err.message : "Unknown camera error.");
      }
    }
  }, []);

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setCameraState("idle");
    setFaces([]);
  }, []);

  useEffect(() => () => stopCamera(), [stopCamera]);

  // Lock the display container to the camera's native aspect ratio once known,
  // so overlay coordinates map back from the captured frame with a single
  // uniform scale factor -- no cropping/offset math for object-fit: cover.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const onLoadedMeta = () => {
      setNativeSize({ w: video.videoWidth, h: video.videoHeight });
    };
    video.addEventListener("loadedmetadata", onLoadedMeta);
    return () => video.removeEventListener("loadedmetadata", onLoadedMeta);
  }, [cameraState]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      setDisplaySize({ w: width, h: height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Poll /detect with captured frames while the camera is active.
  useEffect(() => {
    if (cameraState !== "active") return;

    const interval = setInterval(async () => {
      const video = videoRef.current;
      if (!video || video.readyState < 2 || inFlightRef.current) return;
      if (!video.videoWidth || !video.videoHeight) return;

      inFlightRef.current = true;
      try {
        const canvas = captureCanvasRef.current;
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

        const blob: Blob | null = await new Promise((resolve) =>
          canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY),
        );
        if (!blob) return;

        const res = await api.detect(blob);
        setFaces(res.faces);
        onFaces(res.faces);
      } catch {
        // Transient network/backend hiccup -- keep the last overlay, try again next tick.
      } finally {
        inFlightRef.current = false;
      }
    }, POLL_INTERVAL_MS);

    return () => clearInterval(interval);
  }, [cameraState, onFaces]);

  const scale = nativeSize && displaySize.w ? displaySize.w / nativeSize.w : 1;

  return (
    <div className="rounded-2xl border border-white/10 bg-surface-1 p-4 shadow-xl">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-bold tracking-wide text-white">
          <Camera size={16} className="text-brand-400" />
          LIVE CAMERA FEED
        </h2>
        {cameraState === "active" && (
          <span className="flex items-center gap-1.5 rounded-full bg-status-spoof/10 px-2.5 py-1 text-[11px] font-mono text-status-spoof">
            <Radio size={11} className="animate-pulse" />
            REC
          </span>
        )}
      </div>

      <div
        ref={containerRef}
        className="relative w-full overflow-hidden rounded-xl border border-white/10 bg-black"
        style={{ aspectRatio: nativeSize ? `${nativeSize.w} / ${nativeSize.h}` : "16 / 9" }}
      >
        <video
          ref={videoRef}
          muted
          playsInline
          className={`h-full w-full object-cover ${cameraState === "active" ? "opacity-100" : "opacity-0"}`}
        />

        {cameraState === "active" && (
          <div className="pointer-events-none absolute inset-0 overflow-hidden">
            <div className="animate-scan-line absolute inset-x-0 h-px bg-gradient-to-r from-transparent via-brand-400/60 to-transparent" />
          </div>
        )}

        <AnimatePresence>
          {faces.map((face, idx) => {
            const [x, y, w, h] = face.bbox;
            const status = statusFor(face);
            return (
              <motion.div
                key={idx}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ duration: 0.15 }}
                className={`absolute rounded-md border-2 ${status.color}`}
                style={{
                  left: x * scale,
                  top: y * scale,
                  width: w * scale,
                  height: h * scale,
                }}
              >
                <div
                  className={`absolute -top-6 left-0 flex items-center gap-1 whitespace-nowrap rounded-t-md bg-black/80 px-1.5 py-0.5 text-[10px] font-mono font-semibold ${status.color}`}
                >
                  <status.Icon size={10} />
                  {face.name} · {(face.confidence * 100).toFixed(0)}%
                </div>
                <div
                  className={`absolute -bottom-5 left-0 whitespace-nowrap rounded-b-md bg-black/80 px-1.5 py-0.5 text-[9px] font-mono tracking-wide ${status.color}`}
                >
                  {status.label}
                </div>
              </motion.div>
            );
          })}
        </AnimatePresence>

        {cameraState !== "active" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
            <CameraOff size={32} className="text-white/25" />
            <p className="max-w-xs text-sm text-white/50">
              {cameraState === "requesting" && "Requesting camera access…"}
              {cameraState === "idle" && "Camera is off. Start the feed to begin live face verification."}
              {(cameraState === "denied" || cameraState === "unavailable" || cameraState === "error") &&
                (errorMsg ?? "Camera unavailable.")}
            </p>
          </div>
        )}
      </div>

      <div className="mt-3 flex gap-2">
        {cameraState === "active" ? (
          <button
            onClick={stopCamera}
            className="flex-1 rounded-xl border border-status-spoof/30 bg-status-spoof/10 py-2.5 text-sm font-semibold text-status-spoof transition hover:bg-status-spoof/20"
          >
            Stop Feed
          </button>
        ) : (
          <button
            onClick={startCamera}
            disabled={cameraState === "requesting"}
            className="flex-1 rounded-xl bg-brand-500 py-2.5 text-sm font-semibold text-surface-0 transition hover:bg-brand-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {cameraState === "requesting" ? "Requesting…" : "Start Live Feed"}
          </button>
        )}
      </div>
    </div>
  );
}
