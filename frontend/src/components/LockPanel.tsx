import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Lock, LockOpen, DoorOpen, ShieldAlert, SlidersHorizontal } from "lucide-react";
import { api, type FaceResult } from "../lib/api";
import { playAccessGrantedChime, playAlertTone } from "../lib/sound";

const UNLOCK_HOLD_MS = 5000;
const THRESHOLD_DEBOUNCE_MS = 400;
const DEFAULT_THRESHOLD = 0.65;

interface LockPanelProps {
  faces: FaceResult[];
}

export function LockPanel({ faces }: LockPanelProps) {
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD);
  const [savingThreshold, setSavingThreshold] = useState(false);
  const thresholdDebounce = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [unlocked, setUnlocked] = useState(false);
  const [grantedTo, setGrantedTo] = useState<string | null>(null);
  const [grantedConfidence, setGrantedConfidence] = useState<number | null>(null);
  const [unlockKey, setUnlockKey] = useState(0);
  const relockTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wasUnlockedRef = useRef(false);
  const wasAlertRef = useRef(false);

  // Load the door's real current threshold on mount rather than assuming the
  // default -- it may already have been changed (and persisted) in a prior
  // session.
  useEffect(() => {
    api
      .health()
      .then((h) => setThreshold(h.threshold))
      .catch(() => {
        // backend offline -- keep the client default until it's reachable
      });
  }, []);

  const handleThresholdChange = (value: number) => {
    setThreshold(value);
    if (thresholdDebounce.current) clearTimeout(thresholdDebounce.current);
    thresholdDebounce.current = setTimeout(() => {
      setSavingThreshold(true);
      api
        .updateThreshold(value)
        .catch(() => {
          // transient failure -- the slider still reflects intent locally
        })
        .finally(() => setSavingThreshold(false));
    }, THRESHOLD_DEBOUNCE_MS);
  };

  useEffect(() => () => {
    if (thresholdDebounce.current) clearTimeout(thresholdDebounce.current);
  }, []);

  // The backend's own `is_known` already reflects its current threshold, but
  // checking confidence >= threshold here too means a stricter slider change
  // takes visual effect immediately, without waiting on the next debounced
  // round-trip -- the client-side check can only ever be MORE conservative,
  // never grant access the backend wouldn't also currently agree with.
  const grantee = faces.find((f) => f.is_known && f.is_live && !f.spoof && f.confidence >= threshold);
  const alertActive = !unlocked && faces.some((f) => !f.is_known && f.is_live && !f.spoof);

  useEffect(() => {
    if (!grantee) return;

    if (!wasUnlockedRef.current) {
      playAccessGrantedChime();
    }
    wasUnlockedRef.current = true;

    // Intentionally re-arms on every qualifying poll tick, not just the first:
    // a known face still in frame should keep extending the unlock hold, so
    // this can't be reduced to a plain prop->state derivation computed at
    // render time.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setUnlocked(true);
    setGrantedTo(grantee.name);
    setGrantedConfidence(grantee.confidence);
    setUnlockKey((k) => k + 1);

    if (relockTimer.current) clearTimeout(relockTimer.current);
    relockTimer.current = setTimeout(() => {
      setUnlocked(false);
      setGrantedTo(null);
      setGrantedConfidence(null);
      wasUnlockedRef.current = false;
    }, UNLOCK_HOLD_MS);
  }, [grantee]);

  useEffect(() => () => {
    if (relockTimer.current) clearTimeout(relockTimer.current);
  }, []);

  useEffect(() => {
    if (alertActive && !wasAlertRef.current) {
      playAlertTone();
    }
    wasAlertRef.current = alertActive;
  }, [alertActive]);

  const visual = unlocked
    ? { label: "UNLOCKED", sub: `ACCESS GRANTED · ${(grantedTo ?? "").toUpperCase()}`, color: "known" as const, Icon: LockOpen }
    : alertActive
      ? { label: "ALERT", sub: "UNKNOWN VISITOR DETECTED", color: "spoof" as const, Icon: ShieldAlert }
      : { label: "LOCKED", sub: "AWAITING VERIFIED IDENTITY", color: "idle" as const, Icon: Lock };

  const colorClasses = {
    known: { ring: "text-status-known/40", bg: "bg-status-known/15 text-status-known", text: "text-status-known" },
    spoof: { ring: "text-status-spoof/40", bg: "bg-status-spoof/15 text-status-spoof", text: "text-status-spoof" },
    idle: { ring: "text-white/10", bg: "bg-white/5 text-white/40", text: "text-white/50" },
  }[visual.color];

  return (
    <div className="rounded-2xl border border-white/10 bg-surface-1 p-4 shadow-xl">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-bold tracking-wide text-white">
        <DoorOpen size={16} className="text-brand-400" />
        DOOR LOCK CONTROL
      </h2>

      <div className="relative overflow-hidden rounded-xl border border-white/10 bg-black/30 p-6">
        <AnimatePresence mode="wait">
          <motion.div
            key={unlocked ? `unlocked-${unlockKey}` : visual.label}
            initial={{ opacity: 0, scale: 0.85, rotate: unlocked ? -8 : 8 }}
            animate={{ opacity: 1, scale: 1, rotate: 0 }}
            exit={{ opacity: 0, scale: 0.9 }}
            transition={{ type: "spring", stiffness: 300, damping: 22 }}
            className="flex flex-col items-center gap-3 text-center"
          >
            <div className={`relative flex h-20 w-20 items-center justify-center rounded-full ${colorClasses.bg}`}>
              {visual.color !== "idle" && (
                <span className={`animate-pulse-ring absolute inset-0 rounded-full ${colorClasses.ring}`} />
              )}
              <visual.Icon size={32} />
            </div>

            <div>
              <p className={`text-lg font-extrabold tracking-widest ${colorClasses.text}`}>{visual.label}</p>
              <p className={`mt-0.5 font-mono text-xs ${visual.color === "idle" ? "text-white/40" : `${colorClasses.text}/70`}`}>
                {visual.sub}
              </p>
              {unlocked && grantedConfidence !== null && (
                <p className="mt-1 font-mono text-[11px] text-white/40">
                  match confidence {(grantedConfidence * 100).toFixed(1)}%
                </p>
              )}
            </div>
          </motion.div>
        </AnimatePresence>

        {unlocked && (
          <motion.div
            key={`bar-${unlockKey}`}
            className="absolute inset-x-0 bottom-0 h-0.5 bg-status-known"
            initial={{ scaleX: 1 }}
            animate={{ scaleX: 0 }}
            style={{ originX: 0 }}
            transition={{ duration: UNLOCK_HOLD_MS / 1000, ease: "linear" }}
          />
        )}
      </div>

      <div className="mt-4">
        <div className="mb-1.5 flex items-center justify-between text-xs font-semibold text-white/60">
          <span className="flex items-center gap-1.5">
            <SlidersHorizontal size={13} className="text-brand-400" />
            Accuracy Threshold
          </span>
          <span className="font-mono text-white/40">
            {(threshold * 100).toFixed(0)}%{savingThreshold ? " · saving…" : ""}
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={threshold}
          onChange={(e) => handleThresholdChange(Number(e.target.value))}
          className="w-full accent-cyan-400"
          aria-label="Face match accuracy threshold"
        />
        <p className="mt-1 text-[11px] text-white/30">
          Higher is stricter -- fewer false unlocks, but may reject valid matches in poor lighting.
        </p>
      </div>
    </div>
  );
}
