/**
 * Self-contained UI sound cues via the Web Audio API -- no audio assets to
 * host or license. Every call is wrapped defensively: sound is a nice-to-have,
 * never something that should throw and break a detection/lock state update.
 */

interface WindowWithWebkitAudio extends Window {
  webkitAudioContext?: typeof AudioContext;
}

let audioCtx: AudioContext | null = null;

function getContext(): AudioContext {
  if (!audioCtx) {
    const w = window as WindowWithWebkitAudio;
    const Ctor = window.AudioContext ?? w.webkitAudioContext;
    if (!Ctor) throw new Error("Web Audio API unavailable");
    audioCtx = new Ctor();
  }
  if (audioCtx.state === "suspended") {
    void audioCtx.resume();
  }
  return audioCtx;
}

function tone(
  ctx: AudioContext,
  freq: number,
  startOffset: number,
  duration: number,
  type: OscillatorType = "sine",
  gainPeak = 0.15,
): void {
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  const start = ctx.currentTime + startOffset;
  gain.gain.setValueAtTime(0, start);
  gain.gain.linearRampToValueAtTime(gainPeak, start + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  osc.connect(gain).connect(ctx.destination);
  osc.start(start);
  osc.stop(start + duration + 0.05);
}

/** Call from a user gesture (e.g. "Start Live Feed") to satisfy autoplay policy. */
export function primeAudio(): void {
  try {
    getContext();
  } catch {
    // Web Audio unavailable -- sound cues simply won't play.
  }
}

/** Bright ascending chime for a granted, verified-identity door unlock. */
export function playAccessGrantedChime(): void {
  try {
    const ctx = getContext();
    tone(ctx, 660, 0, 0.14);
    tone(ctx, 880, 0.12, 0.18);
    tone(ctx, 1320, 0.26, 0.3);
  } catch {
    // ignore
  }
}

/** Short double buzz for an unknown-visitor alert. */
export function playAlertTone(): void {
  try {
    const ctx = getContext();
    tone(ctx, 220, 0, 0.16, "sawtooth", 0.12);
    tone(ctx, 180, 0.18, 0.2, "sawtooth", 0.12);
  } catch {
    // ignore
  }
}
