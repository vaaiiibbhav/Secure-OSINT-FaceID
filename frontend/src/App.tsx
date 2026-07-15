import { useCallback, useEffect, useState } from "react";
import { Header, type TabId } from "./components/Header";
import { Footer } from "./components/Footer";
import { LiveCameraFeed } from "./components/LiveCameraFeed";
import { LockPanel } from "./components/LockPanel";
import { ActivityOsintPanel } from "./components/ActivityOsintPanel";
import { ProfilesGrid } from "./components/ProfilesGrid";
import { api, type FaceResult } from "./lib/api";

const HEALTH_POLL_MS = 5000;

function App() {
  const [activeTab, setActiveTab] = useState<TabId>("live");
  const [connected, setConnected] = useState(false);
  const [latestFaces, setLatestFaces] = useState<FaceResult[]>([]);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        await api.health();
        if (!cancelled) setConnected(true);
      } catch {
        if (!cancelled) setConnected(false);
      }
    };
    check();
    const interval = setInterval(check, HEALTH_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const handleFaces = useCallback((faces: FaceResult[]) => {
    setLatestFaces(faces);
  }, []);

  return (
    <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_rgba(6,182,212,0.08),_transparent_55%)] bg-surface-0 px-4 py-6 text-white">
      <Header connected={connected} activeTab={activeTab} onTabChange={setActiveTab} />

      <main className="mx-auto mt-8 w-full max-w-6xl">
        {activeTab === "live" && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
            <LiveCameraFeed onFaces={handleFaces} />
            <LockPanel faces={latestFaces} />
          </div>
        )}

        {activeTab === "activity" && <ActivityOsintPanel />}

        {activeTab === "profiles" && <ProfilesGrid />}
      </main>

      <Footer />
    </div>
  );
}

export default App;
