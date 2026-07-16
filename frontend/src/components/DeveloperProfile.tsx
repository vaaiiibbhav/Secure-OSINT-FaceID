import { AnimatePresence, motion } from "framer-motion";
import { X, ArrowUpRight, ScanFace } from "lucide-react";
import { developer } from "../lib/developer";
import { useEscapeKey } from "../hooks/useEscapeKey";

interface DeveloperProfileProps {
  open: boolean;
  onClose: () => void;
}

export function DeveloperProfile({ open, onClose }: DeveloperProfileProps) {
  useEscapeKey(open, onClose);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <motion.div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={onClose}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />

          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label="Developer profile"
            className="relative w-full max-w-sm overflow-hidden rounded-2xl border border-white/10 bg-surface-1 shadow-2xl"
            initial={{ opacity: 0, scale: 0.92, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 8 }}
            transition={{ type: "spring", stiffness: 340, damping: 28 }}
          >
            <div className="relative h-24 bg-gradient-to-br from-brand-500/30 via-surface-2 to-surface-1">
              <div className="absolute -bottom-10 left-6 flex h-20 w-20 items-center justify-center rounded-2xl border-4 border-surface-1 bg-gradient-to-br from-brand-400 to-brand-500 text-2xl font-bold tracking-wide text-surface-0 shadow-lg">
                {developer.initials}
              </div>
              <button
                onClick={onClose}
                aria-label="Close"
                className="absolute right-3 top-3 rounded-full bg-black/30 p-1.5 text-white/70 transition hover:bg-black/50 hover:text-white"
              >
                <X size={16} />
              </button>
            </div>

            <div className="px-6 pb-6 pt-14">
              <div className="mb-1 flex items-center gap-2 text-xs font-mono uppercase tracking-widest text-brand-400">
                <ScanFace size={14} />
                Developer Profile
              </div>
              <h2 className="text-xl font-bold text-white">{developer.name}</h2>
              <p className="mt-1 text-sm leading-relaxed text-white/50">{developer.role}</p>

              <div className="mt-5 flex flex-col gap-2">
                {developer.links.map(({ label, href, icon: Icon }) => (
                  <a
                    key={label}
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-white/80 transition hover:border-brand-500/40 hover:bg-white/10 hover:text-white"
                  >
                    <span className="flex items-center gap-3">
                      <Icon size={17} className="text-brand-400" />
                      {label}
                    </span>
                    <ArrowUpRight
                      size={15}
                      className="text-white/30 transition group-hover:translate-x-0.5 group-hover:-translate-y-0.5 group-hover:text-brand-400"
                    />
                  </a>
                ))}
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
