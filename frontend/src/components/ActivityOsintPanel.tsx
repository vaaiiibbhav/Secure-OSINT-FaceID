import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  CheckCircle2,
  ShieldAlert,
  ShieldQuestion,
  UserPlus,
  Search,
  Loader2,
  ExternalLink,
  Info,
} from "lucide-react";
import { API_BASE, api, type ActivityEvent, type OSINTQueueItem } from "../lib/api";

const POLL_INTERVAL_MS = 3000;

function eventVisual(event: ActivityEvent) {
  switch (event.event_type) {
    case "known":
      return { Icon: CheckCircle2, color: "text-status-known", bg: "bg-status-known/10 border-status-known/20" };
    case "spoof_detected":
      return { Icon: ShieldAlert, color: "text-status-spoof", bg: "bg-status-spoof/10 border-status-spoof/20" };
    case "enroll":
      return { Icon: UserPlus, color: "text-brand-400", bg: "bg-brand-500/10 border-brand-500/20" };
    default:
      return {
        Icon: ShieldQuestion,
        color: "text-status-unknown",
        bg: "bg-status-unknown/10 border-status-unknown/20",
      };
  }
}

const OSINT_STATUS_STYLES: Record<string, { text: string; cls: string }> = {
  pending_review: { text: "PENDING REVIEW", cls: "text-status-pending bg-status-pending/10" },
  completed: { text: "COMPLETED", cls: "text-status-known bg-status-known/10" },
  failed: { text: "FAILED", cls: "text-status-spoof bg-status-spoof/10" },
};

function QueueStatusBadge({ status }: { status: OSINTQueueItem["status"] }) {
  const cfg = OSINT_STATUS_STYLES[status];
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-mono font-semibold ${cfg.cls}`}>{cfg.text}</span>;
}

export function ActivityOsintPanel() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [queue, setQueue] = useState<OSINTQueueItem[]>([]);
  const [investigating, setInvestigating] = useState<Set<string>>(new Set());
  const [investigateErrors, setInvestigateErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const [logsRes, queueRes] = await Promise.all([api.logs(25), api.osintQueue()]);
        if (cancelled) return;
        setEvents(logsRes.events);
        setQueue(queueRes.items);
      } catch {
        // backend offline -- keep last known state, retry next tick
      }
    };
    poll();
    const interval = setInterval(poll, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const investigate = async (eventId: string) => {
    setInvestigating((prev) => new Set(prev).add(eventId));
    setInvestigateErrors((prev) => ({ ...prev, [eventId]: "" }));
    try {
      const result = await api.osintInvestigate(eventId);
      setQueue((prev) => prev.map((item) => (item.event_id === eventId ? result : item)));
    } catch (err) {
      setInvestigateErrors((prev) => ({
        ...prev,
        [eventId]: err instanceof Error ? err.message : "Lookup failed.",
      }));
    } finally {
      setInvestigating((prev) => {
        const next = new Set(prev);
        next.delete(eventId);
        return next;
      });
    }
  };

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {/* Activity feed */}
      <div className="rounded-2xl border border-white/10 bg-surface-1 p-4 shadow-xl">
        <h2 className="mb-3 flex items-center gap-2 text-sm font-bold tracking-wide text-white">
          <Activity size={16} className="text-brand-400" />
          RECENT ACTIVITY
        </h2>

        <div className="flex max-h-[28rem] flex-col gap-2 overflow-y-auto pr-1">
          {events.map((event, idx) => {
            const { Icon, color, bg } = eventVisual(event);
            return (
              <motion.div
                key={`${event.timestamp}-${idx}`}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.15 }}
                className={`flex items-start gap-3 rounded-xl border px-3 py-2.5 ${bg}`}
              >
                <Icon size={16} className={`mt-0.5 shrink-0 ${color}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className={`truncate text-sm font-semibold ${color}`}>{event.name}</span>
                    <span className="shrink-0 font-mono text-[10px] text-white/35">{event.time}</span>
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[11px] text-white/40">
                    <span className="uppercase tracking-wide">{event.event_type.replace("_", " ")}</span>
                    {event.confidence > 0 && (
                      <span className="rounded bg-black/30 px-1.5 py-0.5 font-mono">
                        {(event.confidence * 100).toFixed(1)}%
                      </span>
                    )}
                    {event.osint_status && (
                      <span
                        className={`rounded px-1.5 py-0.5 font-mono ${
                          OSINT_STATUS_STYLES[event.osint_status]?.cls ?? "bg-black/30 text-white/40"
                        }`}
                      >
                        OSINT: {(OSINT_STATUS_STYLES[event.osint_status]?.text ?? event.osint_status.toUpperCase())}
                      </span>
                    )}
                  </div>
                </div>
              </motion.div>
            );
          })}

          {events.length === 0 && (
            <div className="rounded-xl border border-dashed border-white/10 py-10 text-center text-xs text-white/30">
              No activity recorded yet.
            </div>
          )}
        </div>
      </div>

      {/* Unknown visitor gallery + OSINT review queue */}
      <div className="rounded-2xl border border-white/10 bg-surface-1 p-4 shadow-xl">
        <h2 className="mb-1 flex items-center gap-2 text-sm font-bold tracking-wide text-white">
          <Search size={16} className="text-brand-400" />
          UNKNOWN VISITOR GALLERY
        </h2>
        <p className="mb-3 flex items-start gap-1.5 text-[11px] leading-relaxed text-white/35">
          <Info size={12} className="mt-0.5 shrink-0" />
          Unknown visitors are queued automatically for review. Public web lookups only run when you explicitly
          investigate one.
        </p>

        <div className="grid max-h-[28rem] grid-cols-1 gap-3 overflow-y-auto pr-1 sm:grid-cols-2">
          {queue.map((item) => (
            <div key={item.event_id} className="overflow-hidden rounded-xl border border-white/10 bg-black/20">
              <img
                src={`${API_BASE}${item.frame_url}`}
                alt={`Unknown visitor at ${item.timestamp}`}
                className="aspect-video w-full object-cover"
              />
              <div className="p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[11px] text-white/50">
                    {item.timestamp.replace("T", " ").slice(0, 19)}
                  </span>
                  <QueueStatusBadge status={item.status} />
                </div>

                {item.status === "pending_review" && (
                  <button
                    onClick={() => investigate(item.event_id)}
                    disabled={investigating.has(item.event_id)}
                    className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg bg-brand-500/15 py-1.5 text-xs font-semibold text-brand-300 transition hover:bg-brand-500/25 disabled:opacity-50"
                  >
                    {investigating.has(item.event_id) ? (
                      <>
                        <Loader2 size={12} className="animate-spin" /> Searching…
                      </>
                    ) : (
                      <>
                        <Search size={12} /> Investigate
                      </>
                    )}
                  </button>
                )}

                {investigateErrors[item.event_id] && (
                  <p className="mt-2 text-[11px] text-status-spoof">{investigateErrors[item.event_id]}</p>
                )}

                {item.status === "completed" && (
                  <div className="mt-2 flex flex-col gap-1.5">
                    {item.results && item.results.length > 0 ? (
                      item.results.slice(0, 5).map((hit, i) => (
                        <a
                          key={i}
                          href={hit.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-1.5 truncate rounded-lg bg-white/5 px-2.5 py-1.5 text-[11px] text-white/60 transition hover:bg-white/10 hover:text-white"
                        >
                          <ExternalLink size={11} className="shrink-0 text-brand-400" />
                          <span className="truncate">{hit.title}</span>
                        </a>
                      ))
                    ) : (
                      <p className="text-[11px] text-white/35">No public matches found.</p>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}

          {queue.length === 0 && (
            <div className="col-span-full rounded-xl border border-dashed border-white/10 py-10 text-center text-xs text-white/30">
              No unknown visitors queued.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
