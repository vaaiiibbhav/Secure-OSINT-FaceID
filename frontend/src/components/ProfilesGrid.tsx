import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Users, UserPlus, Trash2, X, Upload, Loader2, AlertCircle } from "lucide-react";
import { api, ApiError, type FaceMember } from "../lib/api";
import { useEscapeKey } from "../hooks/useEscapeKey";

const POLL_INTERVAL_MS = 5000;

export function ProfilesGrid() {
  const [members, setMembers] = useState<FaceMember[]>([]);
  const [enrollOpen, setEnrollOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await api.listFaces();
      setMembers(res.members);
    } catch {
      // backend offline -- keep last known list
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [refresh]);

  const handleDelete = async (name: string) => {
    try {
      await api.removeFace(name);
      setMembers((prev) => prev.filter((m) => m.name !== name));
    } finally {
      setPendingDelete(null);
    }
  };

  return (
    <div className="rounded-2xl border border-white/10 bg-surface-1 p-4 shadow-xl">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-bold tracking-wide text-white">
          <Users size={16} className="text-brand-400" />
          KNOWN PROFILES <span className="text-white/30">({members.length})</span>
        </h2>
        <button
          onClick={() => setEnrollOpen(true)}
          className="flex items-center gap-1.5 rounded-lg bg-brand-500 px-3 py-1.5 text-xs font-semibold text-surface-0 transition hover:bg-brand-400"
        >
          <UserPlus size={13} />
          Enroll Face
        </button>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {members.map((member) => (
          <motion.div
            key={member.name}
            layout
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="group relative rounded-xl border border-white/10 bg-black/20 p-4"
          >
            <button
              onClick={() => setPendingDelete(member.name)}
              aria-label={`Remove ${member.name}`}
              className="absolute right-3 top-3 rounded-lg p-1 text-white/25 opacity-0 transition hover:bg-status-spoof/15 hover:text-status-spoof group-hover:opacity-100"
            >
              <Trash2 size={14} />
            </button>

            <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500/15 font-mono text-sm font-bold text-brand-300">
              {member.name.slice(0, 2).toUpperCase()}
            </div>
            <h3 className="truncate pr-6 text-sm font-bold text-white">{member.name}</h3>
            {member.notes && <p className="mt-0.5 truncate text-xs text-white/40">{member.notes}</p>}

            <dl className="mt-3 space-y-1 font-mono text-[11px] text-white/35">
              <div className="flex justify-between">
                <dt>Enrolled</dt>
                <dd>{member.added_date.slice(0, 10)}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Detections</dt>
                <dd>{member.total_detections}</dd>
              </div>
              <div className="flex justify-between">
                <dt>Last seen</dt>
                <dd>{member.last_seen ? member.last_seen.replace("T", " ").slice(0, 16) : "Never"}</dd>
              </div>
            </dl>
          </motion.div>
        ))}

        {members.length === 0 && (
          <div className="col-span-full rounded-xl border border-dashed border-white/10 py-12 text-center text-sm text-white/30">
            No identities enrolled yet. Add a family member to enable recognition.
          </div>
        )}
      </div>

      <EnrollModal
        open={enrollOpen}
        onClose={() => setEnrollOpen(false)}
        onEnrolled={() => {
          setEnrollOpen(false);
          refresh();
        }}
      />

      <ConfirmDeleteModal
        name={pendingDelete}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => pendingDelete && handleDelete(pendingDelete)}
      />
    </div>
  );
}

interface EnrollModalProps {
  open: boolean;
  onClose: () => void;
  onEnrolled: () => void;
}

function EnrollModal({ open, onClose, onEnrolled }: EnrollModalProps) {
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEscapeKey(open && !submitting, onClose);

  const reset = () => {
    setName("");
    setNotes("");
    setFile(null);
    setError(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !file) {
      setError("A name and a photo are both required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.enrollFace(name.trim(), notes.trim(), file);
      reset();
      onEnrolled();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Enrollment failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => !submitting && onClose()}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />

          <motion.form
            onSubmit={handleSubmit}
            role="dialog"
            aria-modal="true"
            aria-label="Enroll a new face"
            className="relative w-full max-w-sm rounded-2xl border border-white/10 bg-surface-1 p-6 shadow-2xl"
            initial={{ opacity: 0, scale: 0.92, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 8 }}
            transition={{ type: "spring", stiffness: 340, damping: 28 }}
          >
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-bold tracking-wide text-white">ENROLL NEW FACE</h3>
              <button
                type="button"
                onClick={onClose}
                disabled={submitting}
                className="rounded-full p-1 text-white/40 transition hover:text-white"
              >
                <X size={16} />
              </button>
            </div>

            <div className="flex flex-col gap-3">
              <label className="text-xs font-medium text-white/60">
                Name
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Vaibhav Verma"
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-brand-500/50"
                />
              </label>

              <label className="text-xs font-medium text-white/60">
                Notes <span className="text-white/30">(optional)</span>
                <input
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="e.g. dev, family"
                  className="mt-1 w-full rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-brand-500/50"
                />
              </label>

              <label className="text-xs font-medium text-white/60">
                Photo
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="mt-1 flex w-full items-center justify-center gap-2 rounded-lg border border-dashed border-white/15 bg-black/20 px-3 py-4 text-xs text-white/50 transition hover:border-brand-500/40 hover:text-white/80"
                >
                  <Upload size={14} />
                  {file ? file.name : "Choose a clear, front-facing photo"}
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </label>

              {error && (
                <p className="flex items-start gap-1.5 text-xs text-status-spoof">
                  <AlertCircle size={13} className="mt-0.5 shrink-0" />
                  {error}
                </p>
              )}

              <button
                type="submit"
                disabled={submitting}
                className="mt-1 flex items-center justify-center gap-2 rounded-lg bg-brand-500 py-2.5 text-sm font-semibold text-surface-0 transition hover:bg-brand-400 disabled:opacity-50"
              >
                {submitting ? (
                  <>
                    <Loader2 size={14} className="animate-spin" /> Enrolling…
                  </>
                ) : (
                  "Enroll"
                )}
              </button>
            </div>
          </motion.form>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

interface ConfirmDeleteModalProps {
  name: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}

function ConfirmDeleteModal({ name, onCancel, onConfirm }: ConfirmDeleteModalProps) {
  useEscapeKey(name !== null, onCancel);

  return (
    <AnimatePresence>
      {name && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={onCancel}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />
          <motion.div
            role="alertdialog"
            aria-modal="true"
            className="relative w-full max-w-xs rounded-2xl border border-white/10 bg-surface-1 p-5 text-center shadow-2xl"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
          >
            <p className="text-sm text-white/80">
              Remove <span className="font-bold text-white">{name}</span> from the identity database?
            </p>
            <div className="mt-4 flex gap-2">
              <button
                onClick={onCancel}
                className="flex-1 rounded-lg border border-white/10 py-2 text-xs font-semibold text-white/60 hover:bg-white/5"
              >
                Cancel
              </button>
              <button
                onClick={onConfirm}
                className="flex-1 rounded-lg bg-status-spoof/90 py-2 text-xs font-semibold text-white hover:bg-status-spoof"
              >
                Remove
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
