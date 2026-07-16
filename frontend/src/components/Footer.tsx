import { developer } from "../lib/developer";

export function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer className="mx-auto mt-10 flex w-full max-w-6xl flex-col items-center justify-between gap-3 border-t border-white/5 px-2 py-6 text-xs text-white/40 sm:flex-row">
      <p className="font-mono">
        © {year} Secure-OSINT-FaceID — Privacy-first, local-first face recognition.
      </p>
      <div className="flex items-center gap-4">
        <span className="text-white/30">Built by {developer.name}</span>
        <div className="flex items-center gap-3">
          {developer.links.map(({ label, href, icon: Icon }) => (
            <a
              key={label}
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              aria-label={label}
              title={label}
              className="text-white/40 transition hover:text-brand-400"
            >
              <Icon size={15} />
            </a>
          ))}
        </div>
      </div>
    </footer>
  );
}
