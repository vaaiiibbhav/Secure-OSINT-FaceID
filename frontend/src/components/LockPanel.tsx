import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Lock, LockOpen, DoorOpen } from "lucide-react";
import type { FaceResult } from "../lib/api";

const UNLOCK_HOLD_MS = 5000;

interface LockPanelProps {
  faces: FaceResult[];
}

export function LockPanel({ faces }: LockPanelProps) {
  const [unlocked, setUnlocked] = useState(false);
  const [grantedTo, setGrantedTo] = useState<string | null>(null);
  const [unlockKey, setUnlockKey] = useState(0);
  const relockTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const grantee = faces.find((f) => f.is_known && f.is_live && !f.spoof);
    if (!grantee) return;

    // Intentionally re-arms on every qualifying poll tick, not just the first:
    // a known face still in frame should keep extending the unlock hold, so
    // this can't be reduced to a plain prop->state derivation computed at
    // render time.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setUnlocked(true);
    setGrantedTo(grantee.name);
    setUnlockKey((k) => k + 1);

    if (relockTimer.current) clearTimeout(relockTimer.current);
    relockTimer.current = setTimeout(() => {
      setUnlocked(false);
      setGrantedTo(null);
    }, UNLOCK_HOLD_MS);
  }, [faces]);

  useEffect(() => () => {
    if (relockTimer.current) clearTimeout(relockTimer.current);
  }, []);

  return (
    <div className="rounded-2xl border border-white/10 bg-surface-1 p-4 shadow-xl">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-bold tracking-wide text-white">
        <DoorOpen size={16} className="text-brand-400" />
        DOOR LOCK CONTROL
      </h2>

      <div className="relative overflow-hidden rounded-xl border border-white/10 bg-black/30 p-6">
        <AnimatePresence mode="wait">
          <motion.div
            key={unlocked ? `unlocked-${unlockKey}` : "locked"}
            initial={{ opacity: 0, scale: 0.85, rotate: unlocked ? -8 : 8 }}
            animate={{ opacity: 1, scale: 1, rotate: 0 }}
            exit={{ opacity: 0, scale: 0.9 }}
            transition={{ type: "spring", stiffness: 300, damping: 22 }}
            className="flex flex-col items-center gap-3 text-center"
          >
            <div
              className={`relative flex h-20 w-20 items-center justify-center rounded-full ${
                unlocked ? "bg-status-known/15 text-status-known" : "bg-status-spoof/15 text-status-spoof"
              }`}
            >
              <span
                className={`animate-pulse-ring absolute inset-0 rounded-full ${
                  unlocked ? "text-status-known/40" : "text-status-spoof/30"
                }`}
              />
              {unlocked ? <LockOpen size={32} /> : <Lock size={32} />}
            </div>

            <div>
              <p
                className={`text-lg font-extrabold tracking-widest ${
                  unlocked ? "text-status-known" : "text-status-spoof"
                }`}
              >
                {unlocked ? "UNLOCKED" : "LOCKED"}
              </p>
              {unlocked && grantedTo && (
                <p className="mt-0.5 font-mono text-xs text-status-known/70">
                  ACCESS GRANTED · {grantedTo.toUpperCase()}
                </p>
              )}
              {!unlocked && <p className="mt-0.5 font-mono text-xs text-white/40">AWAITING VERIFIED IDENTITY</p>}
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
    </div>
  );
}
