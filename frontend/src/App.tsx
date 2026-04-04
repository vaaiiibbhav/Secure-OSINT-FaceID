import React, { useState, useEffect } from 'react';
import { Camera, Users, Bell, Shield, AlertTriangle, CheckCircle, Server, Activity, ScanFace } from 'lucide-react';

const API_BASE = 'http://localhost:5000/api';

const App = () => {
  const [familyData, setFamilyData] = useState({ total_members: 0, members: [] });
  const [currentView, setCurrentView] = useState('home');
  const [detectionLog, setDetectionLog] = useState([]);
  const [serverStatus, setServerStatus] = useState('Connecting...');
  const [isScanning, setIsScanning] = useState(false);

  // Poll the Python API every 2 seconds for live data
  useEffect(() => {
    const fetchApi = async () => {
      try {
        const [logsRes, familyRes] = await Promise.all([
          fetch(`${API_BASE}/logs`),
          fetch(`${API_BASE}/family`)
        ]);
        
        if (logsRes.ok && familyRes.ok) {
          const logs = await logsRes.json();
          const family = await familyRes.json();
          setDetectionLog(Array.isArray(logs) ? logs.reverse() : []);
          setFamilyData(family.error ? { total_members: 0, members: [] } : family);
          setServerStatus('Connected to AI Core');
        } else {
          setServerStatus('AI Server Offline');
        }
      } catch (e) {
        setServerStatus('AI Server Offline');
      }
    };

    fetchApi();
    const interval = setInterval(fetchApi, 2000);
    return () => clearInterval(interval);
  }, []);

  const triggerScan = async () => {
    setIsScanning(true);
    try {
      await fetch(`${API_BASE}/scan`, { method: 'POST' });
    } catch (e) {
      console.error(e);
    }
    setTimeout(() => setIsScanning(false), 3000); // UI visual timeout
  };

  const FamilyManagement = () => (
    <div className="space-y-6 animate-fade-in">
      <h2 className="text-2xl font-bold text-white flex items-center gap-2">
        <Users className="text-cyan-400" />
        Registered Identities ({familyData?.total_members || 0})
      </h2>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {(familyData?.members || []).map((member, idx) => (
          <div key={idx} className="bg-white/5 backdrop-blur-md border border-white/10 rounded-xl p-5 hover:bg-white/10 transition-all shadow-[0_0_15px_rgba(0,255,255,0.05)]">
            <h3 className="font-bold text-xl text-cyan-50">{member.name}</h3>
            <div className="text-sm text-cyan-200/60 space-y-1 mt-3 font-mono">
              <p>ENROLLED: {member.added_date?.split('T')[0]}</p>
              <p>DETECTIONS: {member.total_detections}</p>
              <p>LAST RECORD: {member.last_seen ? member.last_seen.replace('T', ' ').slice(0, 19) : 'Never'}</p>
            </div>
          </div>
        ))}
      </div>

      {(!familyData?.members || familyData.members.length === 0) && (
        <div className="text-center py-10 text-cyan-500/50 border border-dashed border-cyan-500/20 rounded-xl font-mono">
          NO IDENTITIES FOUND IN DATABASE.
        </div>
      )}
    </div>
  );

  const DetectionLog = () => (
    <div className="space-y-6 animate-fade-in">
      <h2 className="text-2xl font-bold text-white flex items-center gap-2">
        <Activity className="text-cyan-400" />
        System Event Log
      </h2>

      <div className="space-y-4">
        {detectionLog.map((log, idx) => {
          const isFamily = log.is_family;
          const isSpoof = log.name.includes("SPOOF");
          
          let bgColor = isFamily ? 'bg-cyan-900/20 border-cyan-500/30 shadow-[0_0_15px_rgba(34,211,238,0.1)]' : 'bg-orange-900/20 border-orange-500/30 shadow-[0_0_15px_rgba(249,115,22,0.1)]';
          let textColor = isFamily ? 'text-cyan-400' : 'text-orange-400';
          let iconColor = isFamily ? 'text-cyan-400' : 'text-orange-400';
          let Icon = isFamily ? CheckCircle : Shield;

          if (isSpoof || log.details === 'No face detected') {
             bgColor = 'bg-red-900/20 border-red-500/30 shadow-[0_0_15px_rgba(239,68,68,0.2)]';
             textColor = 'text-red-400';
             iconColor = 'text-red-400';
             Icon = AlertTriangle;
          }

          return (
            <div key={idx} className={`border rounded-xl p-5 backdrop-blur-md transition-all ${bgColor}`}>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-3">
                  <Icon className={iconColor} size={24} />
                  <span className={`font-bold tracking-wider ${textColor}`}>{log.name.toUpperCase()}</span>
                  {log.confidence > 0 && <span className="text-xs px-2 py-1 rounded bg-black/40 text-gray-300 font-mono">CONF: {(log.confidence*100).toFixed(1)}%</span>}
                </div>
                <span className="text-xs text-gray-400 font-mono tracking-widest bg-black/30 px-3 py-1 rounded-full">
                  {log.date} // {log.time}
                </span>
              </div>
              <p className="text-sm text-gray-300 ml-9 opacity-80">{isFamily ? 'AUTH: SUCCESS. Door Mechanism Triggered.' : 'AUTH: FAILED. Unknown Entity Logged.'}</p>
            </div>
          );
        })}
      </div>

      {detectionLog.length === 0 && (
        <div className="text-center py-10 text-gray-500 font-mono border border-white/5 rounded-xl">
          System operational. Awaiting external triggers.
        </div>
      )}
    </div>
  );

  const SystemInfo = () => (
    <div className="space-y-6 animate-fade-in">
      <h2 className="text-2xl font-bold text-white">Neural Architecture</h2>
      
      <div className="bg-gradient-to-br from-cyan-900/40 to-blue-900/40 border border-cyan-500/20 text-cyan-50 rounded-xl p-8 backdrop-blur-xl relative overflow-hidden">
        <div className="absolute top-0 right-0 p-32 bg-cyan-500/10 blur-[100px] rounded-full"></div>
        <h3 className="text-2xl font-bold mb-3 tracking-tight">OSINT Privacy Core</h3>
        <p className="opacity-80 leading-relaxed max-w-2xl">
          Engineered to perform mathematically invariant local biometric analysis. Utilizes MediaPipe 3D topographical mesh scaling combined with zero-day liveness tracking (depth-variance check).
        </p>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div className="bg-black/40 backdrop-blur-md border border-green-500/20 rounded-xl p-6 relative overflow-hidden">
          <div className="absolute -top-10 -right-10 w-32 h-32 bg-green-500/10 blur-[50px]"></div>
          <h3 className="font-bold text-lg mb-4 flex items-center gap-2 text-green-400">
            <Shield size={20} /> Defense Protocols
          </h3>
          <ul className="space-y-3 text-gray-300 text-sm font-mono">
             <li className="flex items-center gap-2"><div className="w-1.5 h-1.5 rounded-full bg-green-500"></div> Depth Variance Anti-Spoofing</li>
             <li className="flex items-center gap-2"><div className="w-1.5 h-1.5 rounded-full bg-green-500"></div> Sub-Second Verification</li>
             <li className="flex items-center gap-2"><div className="w-1.5 h-1.5 rounded-full bg-green-500"></div> Zero Cloud Dependency</li>
          </ul>
        </div>
        <div className="bg-black/40 backdrop-blur-md border border-red-500/20 rounded-xl p-6 relative overflow-hidden">
          <div className="absolute -bottom-10 -left-10 w-32 h-32 bg-red-500/10 blur-[50px]"></div>
           <h3 className="font-bold text-lg mb-4 flex items-center gap-2 text-red-400">
            <AlertTriangle size={20} /> Data Restrictions
          </h3>
          <ul className="space-y-3 text-gray-300 text-sm font-mono">
             <li className="flex items-center gap-2"><div className="w-1.5 h-1.5 rounded-full bg-red-500"></div> Ephemeral Processing</li>
             <li className="flex items-center gap-2"><div className="w-1.5 h-1.5 rounded-full bg-red-500"></div> Cache Flushing Active</li>
             <li className="flex items-center gap-2"><div className="w-1.5 h-1.5 rounded-full bg-red-500"></div> Photo Replay Blacklisted</li>
          </ul>
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-[#050505] text-white font-sans p-6 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-blue-900/10 via-[#050505] to-[#050505]">
      
      {/* Floating Header */}
      <div className="max-w-5xl mx-auto">
        <div className="bg-white/5 backdrop-blur-2xl rounded-2xl border border-white/10 p-5 mb-8 sticky top-6 z-50 flex items-center justify-between shadow-[0_8px_32px_rgba(0,0,0,0.5)]">
          <div className="flex items-center gap-4 pl-2">
            <div className="p-2 bg-cyan-500/20 rounded-lg border border-cyan-500/30">
              <Camera className="text-cyan-400" size={28} />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-wider text-white">DOORBELL<span className="text-cyan-400">.OS</span></h1>
              <div className="flex items-center gap-2 text-xs font-mono mt-1">
                <div className={`w-2 h-2 rounded-full animate-pulse ${serverStatus.includes('Connected') ? 'bg-green-400' : 'bg-red-500'}`}></div>
                <span className={serverStatus.includes('Connected') ? 'text-green-400/80' : 'text-red-400/80'}>{serverStatus.toUpperCase()}</span>
              </div>
            </div>
          </div>
          
          <div className="flex items-center gap-4 pr-2">
            <button 
              onClick={triggerScan}
              disabled={isScanning || !serverStatus.includes('Connected')}
              className={`relative group overflow-hidden px-6 py-3 rounded-xl font-bold tracking-widest transition-all duration-300 ${
                isScanning ? 'bg-cyan-900 text-cyan-500 border border-cyan-500/50 cursor-not-allowed' : 
                !serverStatus.includes('Connected') ? 'bg-white/5 text-gray-500 border border-white/10 cursor-not-allowed' :
                'bg-cyan-500 text-black hover:bg-cyan-400 hover:shadow-[0_0_25px_rgba(34,211,238,0.5)] border border-transparent'
              }`}
            >
              <div className="flex items-center gap-2">
                <ScanFace size={20} className={isScanning ? 'animate-pulse' : ''} />
                {isScanning ? 'SCANNING...' : 'FORCE SCAN'}
              </div>
            </button>
          </div>
        </div>

        {/* Content Layout */}
        <div className="flex gap-8">
          {/* Futuristic Sidebar Menu */}
          <div className="w-48 shrink-0 flex flex-col gap-2">
            {['home', 'family', 'log'].map((view, i) => (
              <button 
                key={view} 
                onClick={() => setCurrentView(view)} 
                className={`text-left px-5 py-4 rounded-xl font-mono text-sm tracking-widest transition-all duration-300 ${
                  currentView === view 
                    ? 'bg-gradient-to-r from-cyan-500/20 to-transparent text-cyan-300 border-l-2 border-cyan-400' 
                    : 'text-gray-500 hover:text-gray-300 hover:bg-white/5 border-l-2 border-transparent'
                }`}
              >
                0{i+1}. {view.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Main Content Area */}
          <div className="flex-1 min-h-[600px] mb-20">
            {currentView === 'home' && <SystemInfo />}
            {currentView === 'family' && <FamilyManagement />}
            {currentView === 'log' && <DetectionLog />}
          </div>
        </div>
      </div>
    </div>
  );
};

export default App;
