import React, { useState, useRef, useEffect } from 'react';
import { Camera, Users, Bell, Shield, AlertCircle, CheckCircle, Upload, Trash2 } from 'lucide-react';

const SmartDoorbellSystem = () => {
  const [familyMembers, setFamilyMembers] = useState([]);
  const [currentView, setCurrentView] = useState('home');
  const [detectionLog, setDetectionLog] = useState([]);
  const [isProcessing, setIsProcessing] = useState(false);
  const videoRef = useRef(null);
  const [stream, setStream] = useState(null);

  // Simulate adding a family member
  const addFamilyMember = (name, imageData) => {
    const newMember = {
      id: Date.now(),
      name,
      imageData,
      addedDate: new Date().toISOString(),
      detections: 0
    };
    setFamilyMembers([...familyMembers, newMember]);
  };

  const removeFamilyMember = (id) => {
    setFamilyMembers(familyMembers.filter(m => m.id !== id));
  };

  // Simulate doorbell detection
  const simulateDetection = (isFamilyMember) => {
    const detection = {
      id: Date.now(),
      timestamp: new Date().toISOString(),
      type: isFamilyMember ? 'family' : 'unknown',
      name: isFamilyMember ? familyMembers[Math.floor(Math.random() * familyMembers.length)]?.name : 'Unknown Person',
      action: isFamilyMember ? 'Door unlocked automatically' : 'Notification sent to owner'
    };
    setDetectionLog([detection, ...detectionLog.slice(0, 9)]);
  };

  const startCamera = async () => {
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({ 
        video: { facingMode: 'user' } 
      });
      if (videoRef.current) {
        videoRef.current.srcObject = mediaStream;
      }
      setStream(mediaStream);
    } catch (err) {
      console.error("Error accessing camera:", err);
    }
  };

  const stopCamera = () => {
    if (stream) {
      stream.getTracks().forEach(track => track.stop());
      setStream(null);
    }
  };

  useEffect(() => {
    return () => stopCamera();
  }, []);

  const FamilyManagement = () => (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold text-gray-800 flex items-center gap-2">
        <Users className="text-blue-600" />
        Family Members
      </h2>
      
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
        <div className="flex gap-2 items-start">
          <Shield className="text-blue-600 flex-shrink-0 mt-1" size={20} />
          <div className="text-sm text-blue-800">
            <strong>Privacy First:</strong> All face data is stored locally. No images leave your device. Only authorized family members are recognized.
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {familyMembers.map(member => (
          <div key={member.id} className="bg-white border rounded-lg p-4 shadow-sm">
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold text-lg">{member.name}</h3>
              <button
                onClick={() => removeFamilyMember(member.id)}
                className="text-red-500 hover:text-red-700"
              >
                <Trash2 size={18} />
              </button>
            </div>
            <div className="text-sm text-gray-600 space-y-1">
              <p>Added: {new Date(member.addedDate).toLocaleDateString()}</p>
              <p>Detections: {member.detections}</p>
            </div>
          </div>
        ))}
      </div>

      {familyMembers.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          No family members registered yet. Add family members to enable recognition.
        </div>
      )}

      <button
        onClick={() => {
          const name = prompt("Enter family member name:");
          if (name) addFamilyMember(name, "simulated_data");
        }}
        className="w-full bg-blue-600 text-white py-3 rounded-lg hover:bg-blue-700 flex items-center justify-center gap-2"
      >
        <Upload size={20} />
        Add Family Member
      </button>
    </div>
  );

  const DetectionLog = () => (
    <div className="space-y-4">
      <h2 className="text-2xl font-bold text-gray-800 flex items-center gap-2">
        <Bell className="text-blue-600" />
        Detection Log
      </h2>

      <div className="space-y-2">
        {detectionLog.map(log => (
          <div key={log.id} className={`border rounded-lg p-4 ${
            log.type === 'family' ? 'bg-green-50 border-green-200' : 'bg-yellow-50 border-yellow-200'
          }`}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                {log.type === 'family' ? (
                  <CheckCircle className="text-green-600" size={20} />
                ) : (
                  <AlertCircle className="text-yellow-600" size={20} />
                )}
                <span className="font-semibold">{log.name}</span>
              </div>
              <span className="text-sm text-gray-600">
                {new Date(log.timestamp).toLocaleTimeString()}
              </span>
            </div>
            <p className="text-sm text-gray-700">{log.action}</p>
          </div>
        ))}
      </div>

      {detectionLog.length === 0 && (
        <div className="text-center py-8 text-gray-500">
          No detections yet. Simulate a detection to see how the system works.
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={() => simulateDetection(true)}
          className="flex-1 bg-green-600 text-white py-3 rounded-lg hover:bg-green-700"
          disabled={familyMembers.length === 0}
        >
          Simulate Family Member
        </button>
        <button
          onClick={() => simulateDetection(false)}
          className="flex-1 bg-yellow-600 text-white py-3 rounded-lg hover:bg-yellow-700"
        >
          Simulate Unknown Person
        </button>
      </div>
    </div>
  );

  const SystemInfo = () => (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-gray-800">System Overview</h2>
      
      <div className="bg-gradient-to-r from-blue-500 to-blue-600 text-white rounded-lg p-6">
        <h3 className="text-xl font-bold mb-2">Privacy-Respecting Recognition</h3>
        <p>This system only identifies pre-registered family members. Unknown visitors are simply logged as "unknown" with no data collection.</p>
      </div>

      <div className="space-y-4">
        <div className="border rounded-lg p-4">
          <h3 className="font-bold text-lg mb-2 flex items-center gap-2">
            <CheckCircle className="text-green-600" />
            What This System Does
          </h3>
          <ul className="space-y-2 text-gray-700">
            <li>✓ Recognizes registered family members</li>
            <li>✓ Sends notifications for unknown visitors</li>
            <li>✓ Keeps all data local (no cloud processing)</li>
            <li>✓ Provides activity logs</li>
            <li>✓ Enables automatic door unlock for family</li>
          </ul>
        </div>

        <div className="border rounded-lg p-4">
          <h3 className="font-bold text-lg mb-2 flex items-center gap-2">
            <AlertCircle className="text-red-600" />
            What This System Does NOT Do
          </h3>
          <ul className="space-y-2 text-gray-700">
            <li>✗ Does not collect data on strangers</li>
            <li>✗ Does not search social media</li>
            <li>✗ Does not perform background checks</li>
            <li>✗ Does not store images of unknown people</li>
            <li>✗ Does not violate privacy laws</li>
          </ul>
        </div>

        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <h3 className="font-bold mb-2">Legal Requirements</h3>
          <p className="text-sm text-gray-700">
            When deploying such a system, ensure you:
          </p>
          <ul className="text-sm text-gray-700 mt-2 space-y-1">
            <li>• Post visible signage about camera surveillance</li>
            <li>• Comply with local privacy and recording laws</li>
            <li>• Obtain consent from all family members</li>
            <li>• Securely store all biometric data</li>
            <li>• Provide data deletion options</li>
          </ul>
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="max-w-4xl mx-auto">
        <div className="bg-white rounded-lg shadow-lg p-6 mb-6">
          <div className="flex items-center gap-3 mb-6">
            <Camera className="text-blue-600" size={32} />
            <h1 className="text-3xl font-bold text-gray-800">Smart Doorbell System</h1>
          </div>

          <div className="flex gap-2 mb-6 border-b">
            <button
              onClick={() => setCurrentView('home')}
              className={`px-4 py-2 font-medium ${
                currentView === 'home'
                  ? 'text-blue-600 border-b-2 border-blue-600'
                  : 'text-gray-600'
              }`}
            >
              Overview
            </button>
            <button
              onClick={() => setCurrentView('family')}
              className={`px-4 py-2 font-medium ${
                currentView === 'family'
                  ? 'text-blue-600 border-b-2 border-blue-600'
                  : 'text-gray-600'
              }`}
            >
              Family Members
            </button>
            <button
              onClick={() => setCurrentView('log')}
              className={`px-4 py-2 font-medium ${
                currentView === 'log'
                  ? 'text-blue-600 border-b-2 border-blue-600'
                  : 'text-gray-600'
              }`}
            >
              Detection Log
            </button>
          </div>

          <div>
            {currentView === 'home' && <SystemInfo />}
            {currentView === 'family' && <FamilyManagement />}
            {currentView === 'log' && <DetectionLog />}
          </div>
        </div>
      </div>
    </div>
  );
};

export default SmartDoorbellSystem;