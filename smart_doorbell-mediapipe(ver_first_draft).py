"""
SMART DOORBELL SYSTEM - MEDIAPIPE VERSION
Privacy-First Family Recognition System

Installation:
    !pip install mediapipe opencv-python numpy pillow scikit-learn

Features:
    - Face detection and recognition using MediaPipe
    - Privacy-respecting (no data collection on strangers)
    - Local storage only
    - Activity logging
    - Smart home integration ready

Author: Privacy-First AI Systems
"""

import cv2
import mediapipe as mp
import numpy as np
import pickle
import os
import json
import sys
import queue
import threading
import pyttsx3

# Force UTF-8 encoding for Windows terminals to support emojis
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from datetime import datetime
from pathlib import Path
from sklearn.metrics.pairwise import cosine_similarity
from flask import Flask, jsonify, request
from flask_cors import CORS

# Global doorbell instance for API remote control
doorbell_instance = None

# --- FLASK API SERVER (Serves data to React Frontend) ---
app_api = Flask(__name__)
CORS(app_api)

@app_api.route('/api/scan', methods=['POST'])
def trigger_scan():
    global doorbell_instance
    if doorbell_instance:
        if not doorbell_instance.camera:
            doorbell_instance.start_camera()
        
        # Trigger doorbell ring check on the background thread!
        try:
            doorbell_instance.process_doorbell_ring()
            return jsonify({"status": "Scan completed!"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    
    return jsonify({"error": "Doorbell system not initialized"}), 503


@app_api.route('/api/logs')
def get_logs():
    try:
        log_file = Path('family_data/logs/activity_log.json')
        if log_file.exists():
            with open(log_file, 'r') as f:
                return jsonify(json.load(f))
        return jsonify([])
    except Exception as e:
        return jsonify({'error': str(e)})

@app_api.route('/api/family')
def get_family():
    try:
        info_file = Path('family_data/family_info.json')
        if info_file.exists():
            with open(info_file, 'r') as f:
                return jsonify(json.load(f))
        return jsonify({'total_members': 0, 'members': []})
    except Exception as e:
        return jsonify({'error': str(e)})

def run_flask_api():
    # Hide flask startup messages for a cleaner console
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app_api.run(host='0.0.0.0', port=5000, use_reloader=False)
# --------------------------------------------------------

class VoiceAssistant:
    """Non-blocking TTS for Smart Doorbell"""
    def __init__(self):
        self.q = queue.Queue()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        try:
            import pythoncom
            pythoncom.CoInitialize() # FIX: Resolves Windows background thread COM error!
        except ImportError:
            pass
            
        engine = pyttsx3.init()
        engine.setProperty('rate', 160)
        while True:
            text = self.q.get()
            if text is None: break
            engine.say(text)
            engine.runAndWait()
            self.q.task_done()

    def speak(self, text):
        if self.q.qsize() < 2:
            self.q.put(text)


class MediaPipeFaceRecognition:
    """
    Face recognition system using MediaPipe Face Mesh
    Extracts 468 3D facial landmarks as features
    """
    
    def __init__(self, data_dir='family_data', recognition_threshold=0.92):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        
        self.known_embeddings = []
        self.known_names = []
        self.known_metadata = []
        self.recognition_threshold = recognition_threshold
        
        # Initialize MediaPipe Face Detection and Face Mesh
        self.mp_face_detection = mp.solutions.face_detection
        self.mp_face_mesh = mp.solutions.face_mesh
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_drawing_styles = mp.solutions.drawing_styles
        
        # Face detection for initial face localization
        self.face_detection = self.mp_face_detection.FaceDetection(
            model_selection=1,  # 1 for full range (0-5m)
            min_detection_confidence=0.5
        )
        
        # Face mesh for detailed landmark extraction
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=2,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        
        self.load_family_database()
        
    def extract_face_landmarks(self, image):
        """
        Extract facial landmarks using MediaPipe Face Mesh
        Returns normalized landmark coordinates
        """
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb_image)
        
        landmarks_list = []
        if results.multi_face_landmarks:
            for face_landmarks in results.multi_face_landmarks:
                # Extract all 468 landmarks (x, y, z coordinates)
                landmarks = []
                for landmark in face_landmarks.landmark:
                    landmarks.extend([landmark.x, landmark.y, landmark.z])
                landmarks_list.append(np.array(landmarks))
        
        return landmarks_list
    
    def detect_faces(self, image):
        """
        Detect faces in image and return bounding boxes
        """
        rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        results = self.face_detection.process(rgb_image)
        
        faces = []
        if results.detections:
            h, w, _ = image.shape
            for detection in results.detections:
                bbox = detection.location_data.relative_bounding_box
                x = int(bbox.xmin * w)
                y = int(bbox.ymin * h)
                width = int(bbox.width * w)
                height = int(bbox.height * h)
                confidence = detection.score[0]
                faces.append({
                    'bbox': (x, y, width, height),
                    'confidence': confidence
                })
        
        return faces
    
    def create_face_embedding(self, landmarks):
        """
        Create normalized embedding from landmarks
        Translation and scale invariant for maximum accuracy.
        """
        # Translation invariant (center around centroid)
        pts = landmarks.reshape(-1, 3)
        pts = pts - np.mean(pts, axis=0)
        
        # Scale invariant (normalize)
        embedding = pts.flatten()
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
            
        return embedding
    
    def add_family_member(self, name, image_path, notes=""):
        """
        Add a new family member to the database
        """
        if not os.path.exists(image_path):
            print(f"✗ Error: Image file not found: {image_path}")
            return False
        
        image = cv2.imread(image_path)
        if image is None:
            print(f"✗ Error: Could not read image: {image_path}")
            return False
        
        # Extract landmarks
        landmarks_list = self.extract_face_landmarks(image)
        
        if len(landmarks_list) == 0:
            print(f"✗ Error: No face detected in image for {name}")
            return False
        
        if len(landmarks_list) > 1:
            print(f"⚠ Warning: Multiple faces detected. Using the first face.")
        
        # Create embedding from first detected face
        embedding = self.create_face_embedding(landmarks_list[0])
        
        # Store family member data
        self.known_embeddings.append(embedding)
        self.known_names.append(name)
        self.known_metadata.append({
            'name': name,
            'added_date': datetime.now().isoformat(),
            'notes': notes,
            'total_detections': 0,
            'last_seen': None
        })
        
        self.save_family_database()
        print(f"✓ Successfully added {name} to family database")
        return True
    
    def remove_family_member(self, name):
        """Remove a family member from the database"""
        if name in self.known_names:
            idx = self.known_names.index(name)
            del self.known_embeddings[idx]
            del self.known_names[idx]
            del self.known_metadata[idx]
            self.save_family_database()
            print(f"✓ Removed {name} from family database")
            return True
        else:
            print(f"✗ {name} not found in database")
            return False
    
    def recognize_faces(self, image):
        """
        Recognize all faces in the image
        Returns: list of (is_family, name, confidence, bbox)
        """
        # First detect faces
        detected_faces = self.detect_faces(image)
        
        if not detected_faces:
            return []
        
        # Extract landmarks for all detected faces
        landmarks_list = self.extract_face_landmarks(image)
        
        if not landmarks_list:
            return []
        
        results = []
        for i, (face_info, landmarks) in enumerate(zip(detected_faces, landmarks_list)):
            embedding = self.create_face_embedding(landmarks)
            
            if len(self.known_embeddings) == 0:
                results.append({
                    'is_family': False,
                    'name': 'Unknown Person',
                    'confidence': 0.0,
                    'bbox': face_info['bbox']
                })
                continue
            
            # Compare with all known family members
            similarities = []
            for known_embedding in self.known_embeddings:
                similarity = cosine_similarity(
                    embedding.reshape(1, -1),
                    known_embedding.reshape(1, -1)
                )[0][0]
                similarities.append(similarity)
            
            best_match_idx = np.argmax(similarities)
            best_similarity = similarities[best_match_idx]
            
            # Enforce stricter minimum threshold due to high baseline structural similarity of 3D face meshes
            dynamic_min_threshold = max(self.recognition_threshold, 0.96)
            
            if best_similarity >= dynamic_min_threshold:
                name = self.known_names[best_match_idx]
                
                # Basic 3D Liveness Detection: Check Z-depth variance to prevent photo spoofing
                z_coords = landmarks.reshape(-1, 3)[:, 2]
                depth_variance = np.ptp(z_coords) # Peak to peak (max - min) Z depth
                is_live = bool(depth_variance > 0.05) # Realistic 3D face has variance
                
                if not is_live:
                    name = f"SPOOF DETECTED ({name})"
                    
                # Update detection count
                self.known_metadata[best_match_idx]['total_detections'] += 1
                self.known_metadata[best_match_idx]['last_seen'] = datetime.now().isoformat()
                results.append({
                    'is_family': True and is_live,
                    'name': name,
                    'confidence': float(best_similarity),
                    'bbox': face_info['bbox'],
                    'liveness': is_live
                })
            else:
                results.append({
                    'is_family': False,
                    'name': 'Unknown Person',
                    'confidence': float(best_similarity),
                    'bbox': face_info['bbox'],
                    'liveness': True
                })
        
        return results
    
    def save_family_database(self):
        """Save family database to disk"""
        data = {
            'embeddings': [emb.tolist() for emb in self.known_embeddings],
            'names': self.known_names,
            'metadata': self.known_metadata,
            'threshold': self.recognition_threshold
        }
        
        # Save as pickle for embeddings
        with open(self.data_dir / 'family_database.pkl', 'wb') as f:
            pickle.dump(data, f)
        
        # Also save metadata as JSON for easy viewing
        metadata_readable = {
            'total_members': len(self.known_names),
            'members': self.known_metadata,
            'threshold': self.recognition_threshold
        }
        with open(self.data_dir / 'family_info.json', 'w') as f:
            json.dump(metadata_readable, f, indent=2)
        
        print(f"💾 Database saved ({len(self.known_names)} family members)")
    
    def load_family_database(self):
        """Load family database from disk"""
        db_path = self.data_dir / 'family_database.pkl'
        if db_path.exists():
            with open(db_path, 'rb') as f:
                data = pickle.load(f)
                self.known_embeddings = [np.array(emb) for emb in data['embeddings']]
                self.known_names = data['names']
                self.known_metadata = data['metadata']
                if 'threshold' in data:
                    self.recognition_threshold = data['threshold']
            print(f"✓ Loaded {len(self.known_names)} family members from database")
        else:
            print("ℹ No existing database found. Starting fresh.")
    
    def get_family_stats(self):
        """Get statistics about family members"""
        stats = {
            'total_members': len(self.known_names),
            'members': []
        }
        
        for i, name in enumerate(self.known_names):
            member_info = self.known_metadata[i].copy()
            stats['members'].append(member_info)
        
        return stats
    
    def cleanup(self):
        """Release MediaPipe resources"""
        self.face_detection.close()
        self.face_mesh.close()


class ActivityLogger:
    """Logs all doorbell activity with privacy protection"""
    
    def __init__(self, log_dir='family_data/logs'):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / 'activity_log.txt'
        self.json_log = self.log_dir / 'activity_log.json'
        self.events = []
        self.load_logs()
    
    def log_event(self, event_type, is_family, name, confidence, details=""):
        """Log a detection event"""
        timestamp = datetime.now()
        
        event = {
            'timestamp': timestamp.isoformat(),
            'date': timestamp.strftime('%Y-%m-%d'),
            'time': timestamp.strftime('%H:%M:%S'),
            'event_type': event_type,
            'is_family': is_family,
            'name': name,
            'confidence': round(confidence, 3),
            'details': details
        }
        
        self.events.append(event)
        
        # Write to text log
        status = "FAMILY" if is_family else "UNKNOWN"
        log_line = f"[{event['date']} {event['time']}] {status}: {name} (conf: {confidence:.2f}) - {details}\n"
        
        with open(self.log_file, 'a') as f:
            f.write(log_line)
        
        # Save JSON log
        self.save_json_log()
        
        return event
    
    def save_json_log(self):
        """Save events to JSON file"""
        with open(self.json_log, 'w') as f:
            json.dump(self.events[-1000:], f, indent=2)  # Keep last 1000 events
    
    def load_logs(self):
        """Load existing logs"""
        if self.json_log.exists():
            with open(self.json_log, 'r') as f:
                self.events = json.load(f)
    
    def get_recent_events(self, count=10):
        """Get recent events"""
        return self.events[-count:][::-1]
    
    def get_stats(self):
        """Get activity statistics"""
        if not self.events:
            return {
                'total_events': 0,
                'family_visits': 0,
                'unknown_visits': 0,
                'most_frequent_visitor': None
            }
        
        family_events = [e for e in self.events if e['is_family']]
        unknown_events = [e for e in self.events if not e['is_family']]
        
        # Count visits by person
        from collections import Counter
        visitor_counts = Counter([e['name'] for e in family_events])
        most_frequent = visitor_counts.most_common(1)
        
        return {
            'total_events': len(self.events),
            'family_visits': len(family_events),
            'unknown_visits': len(unknown_events),
            'most_frequent_visitor': most_frequent[0] if most_frequent else None
        }


class SmartDoorbellSystem:
    """
    Complete smart doorbell system with MediaPipe recognition
    """
    
    def __init__(self, data_dir='family_data'):
        self.recognition = MediaPipeFaceRecognition(data_dir)
        self.logger = ActivityLogger()
        self.camera = None
        self.frame_skip = 3  # Process every 3rd frame for performance
        self.frame_count = 0
        self.voice = VoiceAssistant()
        self.voice.speak("Smart Doorbell Online.")

        
    def start_camera(self, camera_id=0):
        """Initialize camera"""
        self.camera = cv2.VideoCapture(camera_id)
        if not self.camera.isOpened():
            raise Exception("❌ Could not open camera")
        
        # Set camera properties for better performance and far distance accuracy
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self.camera.set(cv2.CAP_PROP_FPS, 30)
        
        print("✓ Camera initialized successfully")
    
    def capture_frame(self):
        """Capture a single frame from camera"""
        if self.camera is None:
            raise Exception("Camera not initialized")
        
        ret, frame = self.camera.read()
        if not ret:
            return None
        return frame
    
    def process_doorbell_ring(self):
        """Process a doorbell ring event"""
        print("\n" + "="*60)
        print("🔔 DOORBELL PRESSED - PROCESSING...")
        print("="*60)
        
        frame = self.capture_frame()
        if frame is None:
            print("❌ Failed to capture image")
            return
        
        # Recognize faces
        results = self.recognition.recognize_faces(frame)
        
        if not results:
            print("ℹ No faces detected")
            self.logger.log_event('doorbell_ring', False, 'No Face', 0.0, 'No face detected')
            self.send_notification("Doorbell pressed - No face detected")
            return
        
        # Process each detected face
        for result in results:
            is_family = result['is_family']
            name = result['name']
            confidence = result['confidence']
            bbox = result['bbox']
            
            # Log the event
            self.logger.log_event('doorbell_ring', is_family, name, confidence)
            
            # Handle based on recognition
            if is_family:
                print(f"\n✓ FAMILY MEMBER RECOGNIZED: {name}")
                print(f"  Confidence: {confidence:.2%}")
                print(f"  🔓 Unlocking door...")
                print(f"  💡 Turning on lights...")
                self.unlock_door()
                self.control_smart_home(name, 'arrival')
                self.send_notification(f"Welcome home, {name}!", is_family=True)
                self.voice.speak(f"Welcome home, {name.split()[0]}")
            else:
                print(f"\n⚠ UNKNOWN VISITOR DETECTED")
                if "SPOOF" in name:
                    print(f"  🛑 3D LIVENESS CHECK FAILED. PRINTED PHOTO DETECTED!")
                    self.voice.speak("Spoofing attempt detected. Security alerted.")
                else:
                    print(f"  Match confidence: {confidence:.2%} (below threshold)")
                    self.voice.speak("Unknown visitor detected at the door.")
                print(f"  📱 Sending alert to homeowner...")
                self.send_notification("Unknown visitor at door", is_family=False)
                # DO NOT collect data, search online, or store visitor images
            
            # Draw detection on frame
            frame = self.draw_detection(frame, result)
        
        # Display result
        cv2.imshow('Detection Result', frame)
        cv2.waitKey(3000)  # Show for 3 seconds
        cv2.destroyWindow('Detection Result')
        
        print("="*60)
    
    def draw_detection(self, frame, result):
        """Draw sci-fi bounding box and label on frame"""
        bbox = result['bbox']
        x, y, w, h = bbox
        is_family = result['is_family']
        name = result['name']
        confidence = result['confidence']
        liveness = result.get('liveness', True)
        
        # Choose color based on recognition and liveness
        if not liveness:
            color = (0, 0, 255) # Red for spoofing
        else:
            color = (0, 255, 0) if is_family else (0, 165, 255)  # Green family, Orange unknown
            
        # Draw futuristic brackets instead of full rectangle
        thick = 2
        l = int(w * 0.25)
        cv2.line(frame, (x, y), (x + l, y), color, thick)
        cv2.line(frame, (x, y), (x, y + l), color, thick)
        cv2.line(frame, (x+w, y), (x+w - l, y), color, thick)
        cv2.line(frame, (x+w, y), (x+w, y + l), color, thick)
        cv2.line(frame, (x, y+h), (x + l, y+h), color, thick)
        cv2.line(frame, (x, y+h), (x, y+h - l), color, thick)
        cv2.line(frame, (x+w, y+h), (x+w - l, y+h), color, thick)
        cv2.line(frame, (x+w, y+h), (x+w, y+h - l), color, thick)

        # Draw label background
        label = f"{name} ({confidence:.0%})"
        (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(frame, (x, y - label_h - 10), (x + label_w + 10, y), color, -1)
        
        # Draw label text
        cv2.putText(frame, label, (x + 5, y - 5),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0) if color != (0, 0, 255) else (255,255,255), 2)
        
        return frame
    
    def unlock_door(self):
        """
        Integrate with smart lock
        Examples: August, Yale, Schlage, Kwikset
        """
        # Placeholder for smart lock integration
        # Add your smart lock API here:
        # - August Smart Lock API
        # - Yale Access API
        # - Z-Wave/Zigbee controller
        pass
    
    def control_smart_home(self, person_name, event_type):
        """
        Control smart home devices based on person and event
        """
        # Placeholder for smart home integration
        # Examples:
        # - Turn on lights (Philips Hue, LIFX)
        # - Adjust thermostat (Nest, Ecobee)
        # - Play welcome message (Sonos, Google Home)
        # - Open garage (MyQ)
        pass
    
    def send_notification(self, message, is_family=False):
        """
        Send notification to homeowner
        """
        print(f"📱 Notification: {message}")
        
        # Integration options:
        # 1. Email via SMTP
        # 2. SMS via Twilio
        # 3. Push notification via Firebase Cloud Messaging
        # 4. Smart home hub notification (Home Assistant, SmartThings)
        # 5. Telegram/Discord bot
        # 6. IFTTT webhook
        pass
    
    def add_family_member_from_camera(self, name, notes=""):
        """Capture photo from camera and add family member"""
        print(f"\n📸 Capturing photo for {name}...")
        print("Position yourself in front of the camera")
        print("Press SPACE to capture, ESC to cancel")
        
        if self.camera is None:
            self.start_camera()
        
        while True:
            frame = self.capture_frame()
            if frame is None:
                continue
            
            # Detect faces to help positioning
            faces = self.recognition.detect_faces(frame)
            display_frame = frame.copy()
            
            for face in faces:
                x, y, w, h = face['bbox']
                cv2.rectangle(display_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.putText(display_frame, "Press SPACE to capture", (x, y - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            
            cv2.imshow('Capture Family Member', display_frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == 32:  # SPACE
                temp_path = f"temp_{name.replace(' ', '_')}.jpg"
                cv2.imwrite(temp_path, frame)
                success = self.recognition.add_family_member(name, temp_path, notes)
                os.remove(temp_path)
                cv2.destroyWindow('Capture Family Member')
                return success
            elif key == 27:  # ESC
                cv2.destroyWindow('Capture Family Member')
                return False
    
    def show_live_feed(self):
        """Show live camera feed with real-time recognition"""
        print("\n📹 Starting live feed...")
        print("Press 'q' to quit, 's' to scan")
        
        if self.camera is None:
            self.start_camera()
        
        current_results = []
        
        while True:
            frame = self.capture_frame()
            if frame is None:
                continue
            
            self.frame_count += 1
            
            # Process every Nth frame for performance
            if self.frame_count % self.frame_skip == 0:
                current_results = self.recognition.recognize_faces(frame)
                
            for result in current_results:
                frame = self.draw_detection(frame, result)
            
            # Add instructions
            cv2.putText(frame, "Press 's' to scan | 'q' to quit",
                       (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            cv2.imshow('Doorbell Live Feed', frame)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('s'):
                self.process_doorbell_ring()
        
        cv2.destroyWindow('Doorbell Live Feed')
    
    def display_stats(self):
        """Display system statistics"""
        print("\n" + "="*60)
        print("📊 SYSTEM STATISTICS")
        print("="*60)
        
        # Family member stats
        family_stats = self.recognition.get_family_stats()
        print(f"\n👥 Family Members: {family_stats['total_members']}")
        for member in family_stats['members']:
            print(f"   • {member['name']}")
            print(f"     Added: {member['added_date'][:10]}")
            print(f"     Detections: {member['total_detections']}")
            if member['last_seen']:
                print(f"     Last seen: {member['last_seen'][:19]}")
        
        # Activity stats
        activity_stats = self.logger.get_stats()
        print(f"\n📈 Activity Statistics:")
        print(f"   Total events: {activity_stats['total_events']}")
        print(f"   Family visits: {activity_stats['family_visits']}")
        print(f"   Unknown visits: {activity_stats['unknown_visits']}")
        if activity_stats['most_frequent_visitor']:
            name, count = activity_stats['most_frequent_visitor']
            print(f"   Most frequent: {name} ({count} visits)")
        
        # Recent events
        print(f"\n📋 Recent Events:")
        recent = self.logger.get_recent_events(5)
        for event in recent:
            status = "✓" if event['is_family'] else "⚠"
            print(f"   {status} [{event['time']}] {event['name']} ({event['confidence']:.0%})")
        
        print("="*60)
    
    def cleanup(self):
        """Release all resources"""
        if self.camera:
            self.camera.release()
        cv2.destroyAllWindows()
        self.recognition.cleanup()
        print("\n✓ System shutdown complete")


def print_menu():
    """Display main menu"""
    print("\n" + "="*60)
    print("SMART DOORBELL SYSTEM - MAIN MENU")
    print("="*60)
    print("1. 📹 Live Camera Feed (with real-time recognition)")
    print("2. 🔔 Simulate Doorbell Ring")
    print("3. 👥 Manage Family Members")
    print("4. 📊 View Statistics")
    print("5. 📋 View Activity Log")
    print("6. ⚙️  System Settings")
    print("7. ❌ Exit")
    print("="*60)


def manage_family_menu(doorbell_instance):
    """Family management submenu"""
    while True:
        print("\n" + "-"*60)
        print("FAMILY MEMBER MANAGEMENT")
        print("-"*60)
        print("1. Add family member from file")
        print("2. Add family member from camera")
        print("3. Remove family member")
        print("4. List all family members")
        print("5. Back to main menu")
        print("-"*60)
        
        choice = input("\nEnter choice (1-5): ").strip()
        
        if choice == '1':
            name = input("Enter name: ").strip()
            image_path = input("Enter image path: ").strip()
            notes = input("Enter notes (optional): ").strip()
            doorbell_instance.recognition.add_family_member(name, image_path, notes)
        
        elif choice == '2':
            name = input("Enter name: ").strip()
            notes = input("Enter notes (optional): ").strip()
            doorbell_instance.add_family_member_from_camera(name, notes)
        
        elif choice == '3':
            name = input("Enter name to remove: ").strip()
            confirm = input(f"Are you sure you want to remove {name}? (yes/no): ").lower()
            if confirm == 'yes':
                doorbell_instance.recognition.remove_family_member(name)
        
        elif choice == '4':
            stats = doorbell_instance.recognition.get_family_stats()
            print(f"\n👥 Registered Family Members ({stats['total_members']}):")
            for member in stats['members']:
                print(f"\n• {member['name']}")
                print(f"  Added: {member['added_date'][:10]}")
                print(f"  Total detections: {member['total_detections']}")
                if member['notes']:
                    print(f"  Notes: {member['notes']}")
        
        elif choice == '5':
            break


def main():
    """Main application"""
    print("\n" + "="*60)
    print("🏠 SMART DOORBELL SYSTEM")
    print("Privacy-First Family Recognition with MediaPipe")
    print("="*60)
    
    global doorbell_instance
    doorbell_instance = SmartDoorbellSystem()
    
    # Start the Flask API server cleanly in background for the React Dashboard
    print("🚀 Starting Web API for React Dashboard on http://localhost:5000...")
    threading.Thread(target=run_flask_api, daemon=True).start()
    
    # Check if family members exist
    stats = doorbell_instance.recognition.get_family_stats()
    if stats['total_members'] == 0:
        print("\n⚠ No family members registered")
        setup = input("Would you like to add family members now? (y/n): ").lower()
        if setup == 'y':
            manage_family_menu(doorbell_instance)
    else:
        print(f"\n✓ System loaded with {stats['total_members']} family members")
    
    # Main loop
    try:
        while True:
            print_menu()
            choice = input("\nEnter choice (1-7): ").strip()
            
            if choice == '1':
                doorbell_instance.show_live_feed()
            
            elif choice == '2':
                if not doorbell_instance.camera:
                    doorbell_instance.start_camera()
                doorbell_instance.process_doorbell_ring()
            
            elif choice == '3':
                manage_family_menu(doorbell_instance)
            
            elif choice == '4':
                doorbell_instance.display_stats()
            
            elif choice == '5':
                recent = doorbell_instance.logger.get_recent_events(20)
                print("\n📋 Recent Activity (last 20 events):")
                print("-"*60)
                for event in recent:
                    status = "✓ FAMILY" if event['is_family'] else "⚠ UNKNOWN"
                    print(f"[{event['date']} {event['time']}] {status}: {event['name']} ({event['confidence']:.0%})")
                print("-"*60)
            
            elif choice == '6':
                print("\n⚙️  System Settings:")
                print(f"Current recognition threshold: {doorbell_instance.recognition.recognition_threshold:.2%}")
                new_threshold = input("Enter new threshold (0.00-1.00) or press Enter to keep current: ").strip()
                if new_threshold:
                    try:
                        threshold = float(new_threshold)
                        if 0 <= threshold <= 1:
                            doorbell_instance.recognition.recognition_threshold = threshold
                            doorbell_instance.recognition.save_family_database()
                            print(f"✓ Threshold updated to {threshold:.2%}")
                        else:
                            print("✗ Invalid threshold. Must be between 0 and 1.")
                    except ValueError:
                        print("✗ Invalid input")
            
            elif choice == '7':
                print("\n👋 Shutting down system...")
                break
            
            else:
                print("❌ Invalid choice. Please try again.")
    
    except KeyboardInterrupt:
        print("\n\n⚠ System interrupted by user")
    
    finally:
        doorbell_instance.cleanup()
        print("Goodbye! 👋\n")


if __name__ == "__main__":
    main()