import time
import threading
from typing import Dict, Any, Optional

class CameraHealthMonitor:
    """
    Monitors camera operational health metrics:
    - Real-time FPS (moving average)
    - Latency (ms)
    - Frame counts (received / dropped)
    - Connection state (connected, reconnecting, disconnected, error)
    - Last error description
    - Uptime and last frame timestamp
    """
    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self.status = "disconnected"
        self.fps = 0.0
        self.latency_ms = 0.0
        self.total_frames_received = 0
        self.total_frames_dropped = 0
        self.reconnect_count = 0
        self.last_frame_time = 0.0
        self.connection_start_time = 0.0
        self.last_error = ""
        self.lock = threading.Lock()

    def record_frame(self, latency_ms: float = 0.0):
        with self.lock:
            now = time.time()
            if self.last_frame_time > 0:
                dt = now - self.last_frame_time
                if dt > 0:
                    current_fps = 1.0 / dt
                    self.fps = round(self.fps * 0.85 + current_fps * 0.15, 1)
            else:
                self.connection_start_time = now

            self.last_frame_time = now
            self.total_frames_received += 1
            self.latency_ms = round(latency_ms, 1) if latency_ms > 0 else 15.0
            self.status = "connected"
            self.last_error = ""

    def record_dropped_frame(self):
        with self.lock:
            self.total_frames_dropped += 1

    def record_reconnect_attempt(self, error_msg: str = ""):
        with self.lock:
            self.status = "reconnecting"
            self.reconnect_count += 1
            self.fps = 0.0
            if error_msg:
                self.last_error = error_msg

    def record_disconnection(self, error_msg: str = ""):
        with self.lock:
            self.status = "disconnected"
            self.fps = 0.0
            if error_msg:
                self.last_error = error_msg

    def record_error(self, error_msg: str):
        with self.lock:
            self.status = "error"
            self.last_error = error_msg
            self.fps = 0.0

    def get_stats(self) -> Dict[str, Any]:
        with self.lock:
            now = time.time()
            # If no frame received for > 3.5 seconds while supposedly connected, mark as reconnecting
            if self.status == "connected" and self.last_frame_time > 0 and (now - self.last_frame_time > 3.5):
                self.status = "reconnecting"
                self.fps = 0.0

            uptime_sec = round(now - self.connection_start_time, 1) if (self.status == "connected" and self.connection_start_time > 0) else 0.0

            return {
                "camera_id": self.camera_id,
                "status": self.status,
                "fps": self.fps,
                "latency_ms": self.latency_ms,
                "received_frames": self.total_frames_received,
                "dropped_frames": self.total_frames_dropped,
                "reconnect_count": self.reconnect_count,
                "uptime_seconds": uptime_sec,
                "last_error": self.last_error,
                "is_healthy": (self.status == "connected" and self.fps >= 5.0)
            }
