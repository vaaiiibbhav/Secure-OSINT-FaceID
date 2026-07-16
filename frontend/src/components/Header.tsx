import { useState } from "react";
import { ScanFace, User, Wifi, WifiOff } from "lucide-react";
import { DeveloperProfile } from "./DeveloperProfile";

interface HeaderProps {
  connected: boolean;
}

const NAV_TABS = [
  { id: "live", label: "Live Feed" },
  { id: "activity", label: "Activity & OSINT" },
  { id: "profiles", label: "Known Profiles" },
] as const;

export type TabId = (typeof NAV_TABS)[number]["id"];

interface HeaderNavProps extends HeaderProps {
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
}

export function Header({ connected, activeTab, onTabChange }: HeaderNavProps) {
  const [profileOpen, setProfileOpen] = useState(false);

  return (
    <>
      <header className="sticky top-4 z-40 mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-4 rounded-2xl border border-white/10 bg-surface-1/80 px-5 py-3.5 shadow-[0_8px_32px_rgba(0,0,0,0.45)] backdrop-blur-xl">
        <div className="flex items-center gap-3">
          <div className="rounded-lg border border-brand-500/30 bg-brand-500/15 p-2">
            <ScanFace className="text-brand-400" size={22} />
          </div>
          <div>
            <h1 className="text-base font-bold tracking-wide text-white sm:text-lg">
              SECURE<span className="text-brand-400">-OSINT-</span>FaceID
            </h1>
            <div className="flex items-center gap-1.5 font-mono text-[11px]">
              {connected ? (
                <>
                  <Wifi size={11} className="text-status-known" />
                  <span className="text-status-known/80">API CONNECTED</span>
                </>
              ) : (
                <>
                  <WifiOff size={11} className="text-status-spoof" />
                  <span className="text-status-spoof/80">API OFFLINE</span>
                </>
              )}
            </div>
          </div>
        </div>

        <nav className="flex items-center gap-1 rounded-xl border border-white/5 bg-black/20 p-1">
          {NAV_TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onTabChange(tab.id)}
              className={`rounded-lg px-3.5 py-2 text-xs font-semibold tracking-wide transition-all sm:text-sm ${
                activeTab === tab.id
                  ? "bg-brand-500/20 text-brand-300 shadow-inner"
                  : "text-white/50 hover:bg-white/5 hover:text-white/80"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        <button
          onClick={() => setProfileOpen(true)}
          className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs font-semibold text-white/70 transition hover:border-brand-500/30 hover:bg-white/10 hover:text-white"
        >
          <User size={15} className="text-brand-400" />
          <span className="hidden sm:inline">Developer</span>
        </button>
      </header>

      <DeveloperProfile open={profileOpen} onClose={() => setProfileOpen(false)} />
    </>
  );
}
