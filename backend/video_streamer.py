import os
import cv2
import time
import threading
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any, Generator
from backend.config import CAMERA_INDEX, UPLOADED_VIDEOS_DIR
from backend.face_engine import FaceRecognitionEngine
from backend.tracking_engine import GateTrackingEngine

class VideoStreamManager:
    def __init__(self, face_engine: FaceRecognitionEngine, tracking_engine: GateTrackingEngine):
        self.face_engine = face_engine
        self.tracking_engine = tracking_engine
        self.tracking_engine.face_engine = face_engine
        
        self.source_type = "webcam"  # "webcam", "file", "synthetic"
        self.source_path: Optional[str] = None
        self.cap: Optional[cv2.VideoCapture] = None
        
        self.running = False
        self.counting_active = True
        self.is_paused = False
        self.current_frame: Optional[np.ndarray] = None
        self.current_hud_frame: Optional[np.ndarray] = None
        self.current_detections = []
        
        self.fps = 0.0
        self.last_frame_time = time.time()
        self.lock = threading.Lock()
        
        # Background worker thread
        self.thread: Optional[threading.Thread] = None

    def start(self, source_type: str = "webcam", source_path: Optional[str] = None):
        """Starts or switches the video stream capture thread."""
        with self.lock:
            self.stop_stream()
            self.source_type = source_type
            self.source_path = source_path
            
            if source_type == "webcam":
                idx = int(source_path) if (source_path and source_path.isdigit()) else CAMERA_INDEX
                self.cap = cv2.VideoCapture(idx)
                # Check if opened, otherwise fallback to synthetic simulation
                if not self.cap.isOpened():
                    print(f"[VideoStream] Webcam index {idx} not available. Switching to realistic Gate Simulator.")
                    self.source_type = "synthetic"
                    self.cap = None
            elif source_type == "file" and source_path and os.path.exists(source_path):
                self.cap = cv2.VideoCapture(source_path)
                if not self.cap.isOpened():
                    print(f"[VideoStream] Could not open video file: {source_path}. Fallback to synthetic.")
                    self.source_type = "synthetic"
                    self.cap = None
            else:
                self.source_type = "synthetic"
                self.cap = None

            self.running = True
            self.thread = threading.Thread(target=self._capture_and_process_loop, daemon=True)
            self.thread.start()
            print(f"[VideoStream] Stream started with source: {self.source_type} ({self.source_path})")

    def stop_stream(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

    def start_counting(self):
        """Starts video playback and activates live AI line crossing counting."""
        with self.lock:
            self.counting_active = True
            self.is_paused = False
        print("[VideoStream] Live counting and video playback STARTED.")

    def stop_counting(self):
        """Pauses video playback and suspends live AI line crossing counting."""
        with self.lock:
            self.counting_active = False
            self.is_paused = True
        print("[VideoStream] Live counting and video playback STOPPED/PAUSED.")

    def toggle_counting(self) -> bool:
        """Toggles between start and stop states."""
        with self.lock:
            if self.counting_active and not self.is_paused:
                self.counting_active = False
                self.is_paused = True
            else:
                self.counting_active = True
                self.is_paused = False
            return self.counting_active and not self.is_paused

    def reset_counts(self):
        """Resets session counters to 0 and rewinds video if file source."""
        with self.lock:
            self.tracking_engine.count_in = 0
            self.tracking_engine.count_out = 0
            self.tracking_engine.count_unknown = 0
            self.tracking_engine.track_side.clear()
            self.tracking_engine.track_history.clear()
            self.tracking_engine.cooldown_locks.clear()
            self.tracking_engine.recent_events.clear()
            
            if self.cap and self.source_type == "file":
                try:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                except Exception:
                    pass
        print("[VideoStream] Session counts reset to 0. Video rewound to beginning.")

    def _generate_synthetic_gate_frame(self, frame_num: int) -> np.ndarray:
        """
        Generates a realistic textile mill gate scene with moving workers/staff
        when no physical webcam or video is connected, allowing complete end-to-end testing.
        """
        w, h = 960, 540
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        
        # Factory / Office gate background: Floor and Wall
        cv2.rectangle(frame, (0, 0), (w, int(h * 0.45)), (45, 52, 60), -1)  # Wall
        cv2.rectangle(frame, (0, int(h * 0.45)), (w, h), (85, 92, 105), -1)  # Floor tiles
        
        # Gate doorway frame
        cv2.rectangle(frame, (180, int(h * 0.15)), (w - 180, int(h * 0.95)), (110, 120, 135), 4)
        
        # Signboard above gate
        cv2.rectangle(frame, (280, int(h * 0.05)), (w - 280, int(h * 0.14)), (20, 30, 45), -1)
        cv2.putText(frame, "TEXTILE MILL - MAIN ENTRANCE GATE", (295, int(h * 0.11)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (230, 240, 255), 2)
        
        # Simulate walking people with cyclic motion
        # Person 1: Walking Inward (Crossing line around frame 100-180)
        t1 = (frame_num % 300) / 300.0
        p1_y = int(h * 0.20 + t1 * (h * 0.65))
        p1_x = int(w * 0.38 + np.sin(t1 * np.pi) * 20)
        
        # Person 2: Walking Outward (Exiting around frame 180-260)
        t2 = ((frame_num + 140) % 320) / 320.0
        p2_y = int(h * 0.85 - t2 * (h * 0.65))
        p2_x = int(w * 0.62 - np.sin(t2 * np.pi) * 15)

        # Draw Person 1 (Blue shirt / Worker)
        pw, ph = 70, 180
        # Head
        cv2.circle(frame, (p1_x, p1_y - 60), 22, (200, 180, 160), -1)
        # Hair
        cv2.ellipse(frame, (p1_x, p1_y - 70), (22, 14), 0, 180, 360, (25, 25, 25), -1)
        # Body
        cv2.rectangle(frame, (p1_x - 32, p1_y - 38), (p1_x + 32, p1_y + 45), (180, 90, 40), -1)
        # Legs
        cv2.rectangle(frame, (p1_x - 28, p1_y + 45), (p1_x - 6, p1_y + 115), (50, 50, 60), -1)
        cv2.rectangle(frame, (p1_x + 6, p1_y + 45), (p1_x + 28, p1_y + 115), (50, 50, 60), -1)
        
        # Draw Person 2 (Brown shirt / Staff)
        cv2.circle(frame, (p2_x, p2_y - 60), 22, (190, 175, 155), -1)
        cv2.ellipse(frame, (p2_x, p2_y - 70), (22, 14), 0, 180, 360, (30, 30, 30), -1)
        cv2.rectangle(frame, (p2_x - 30, p2_y - 38), (p2_x + 30, p2_y + 45), (50, 120, 180), -1)
        cv2.rectangle(frame, (p2_x - 26, p2_y + 45), (p2_x - 6, p2_y + 115), (60, 60, 70), -1)
        cv2.rectangle(frame, (p2_x + 6, p2_y + 45), (p2_x + 26, p2_y + 115), (60, 60, 70), -1)

        return frame

    def _capture_and_process_loop(self):
        """Main camera acquisition and AI inference loop."""
        frame_counter = 0
        skip_counter = 0

        while self.running:
            start_t = time.time()

            # If video playback is paused on a video file, hold the current frame
            if self.is_paused and self.source_type == "file" and self.current_frame is not None:
                hud_frame = self.tracking_engine.draw_hud_overlay(self.current_frame, self.current_detections, is_counting=False)
                with self.lock:
                    self.current_hud_frame = hud_frame
                time.sleep(0.04)
                continue

            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if not ret:
                    if self.source_type == "file":
                        # Loop video file continuously
                        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, frame = self.cap.read()
                    if not ret:
                        time.sleep(0.05)
                        continue
            else:
                # Generate synthetic test gate frame
                frame = self._generate_synthetic_gate_frame(frame_counter)

            frame_counter += 1
            h, w, _ = frame.shape

            # Run AI Inference every 2nd or 3rd frame for high FPS
            skip_counter += 1
            if skip_counter % 2 == 0 or len(self.current_detections) == 0:
                try:
                    # Run YOLO-pose detector
                    results = self.face_engine.pose_model.track(
                        source=frame,
                        persist=True,
                        verbose=False,
                        classes=[0]  # Person class only
                    )

                    detections = []
                    if len(results) > 0 and results[0].boxes is not None:
                        boxes = results[0].boxes.xyxy.cpu().numpy()
                        track_ids = results[0].boxes.id.cpu().numpy().astype(int) if results[0].boxes.id is not None else list(range(len(boxes)))
                        kpts = results[0].keypoints.data.cpu().numpy() if results[0].keypoints is not None else [None] * len(boxes)

                        for idx, box in enumerate(boxes):
                            tid = int(track_ids[idx])
                            kp = kpts[idx] if idx < len(kpts) else np.zeros((17, 3))
                            
                            cx = (box[0] + box[2]) / 2.0
                            cy = (box[1] + box[3]) / 2.0

                            # Recognize face
                            p_info = self.face_engine.process_person_detection(frame, box.tolist(), kp, capture_unknown=False)
                            p_info["track_id"] = tid
                            p_info["person_box"] = box.tolist()

                            # Line Crossing Gate Tracking (only when counting is active and unpaused!)
                            if self.counting_active and not self.is_paused:
                                self.tracking_engine.process_crossing(tid, cx, cy, w, h, p_info)

                            detections.append(p_info)

                    self.current_detections = detections
                except Exception as e:
                    print(f"[VideoStream] Inference error: {e}")

            # Draw AI HUD overlays with active counting flag
            is_active_counting = self.counting_active and not self.is_paused
            hud_frame = self.tracking_engine.draw_hud_overlay(frame, self.current_detections, is_counting=is_active_counting)

            # Calculate FPS
            dt = time.time() - start_t
            if dt > 0:
                cur_fps = 1.0 / dt
                self.fps = round(self.fps * 0.85 + cur_fps * 0.15, 1)

            with self.lock:
                self.current_frame = frame
                self.current_hud_frame = hud_frame

            # Target ~25-30 FPS
            sleep_needed = max(0.005, 0.033 - (time.time() - start_t))
            time.sleep(sleep_needed)

    def get_latest_jpeg(self) -> Optional[bytes]:
        """Encodes current HUD frame to JPEG for MJPEG browser stream."""
        with self.lock:
            if self.current_hud_frame is None:
                return None
            ret, jpeg = cv2.imencode('.jpg', self.current_hud_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ret:
                return jpeg.tobytes()
        return None

    def get_raw_snapshot_jpeg(self) -> Optional[bytes]:
        """Encodes clean current camera frame without HUD for staff registration."""
        with self.lock:
            if self.current_frame is None:
                return None
            ret, jpeg = cv2.imencode('.jpg', self.current_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            if ret:
                return jpeg.tobytes()
        return None

    def generate_mjpeg_stream(self) -> Generator[bytes, None, None]:
        """MJPEG generator for FastAPI StreamingResponse."""
        while self.running:
            jpeg_bytes = self.get_latest_jpeg()
            if jpeg_bytes is not None:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg_bytes + b'\r\n')
            time.sleep(0.035)
