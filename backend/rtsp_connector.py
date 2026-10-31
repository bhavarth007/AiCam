import os
import cv2
import time
import queue
import threading
import numpy as np
from typing import Optional, Dict, Any, Callable
from backend.camera_health_monitor import CameraHealthMonitor

def test_rtsp_connection(url: str, timeout_s: float = 3.0) -> Dict[str, Any]:
    """
    Safely tests connection to an RTSP, HTTP, or local camera source with a strict timeout.
    Returns: {"success": bool, "message": str, "resolution": (w, h), "fps": float}
    """
    if not url:
        return {"success": False, "message": "Camera URL cannot be empty."}

    # Set OpenCV environment variables for low-latency network probe
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|analyzeduration;1000000|probesize;1000000"

    result = {"success": False, "message": "Connection timed out.", "resolution": [0, 0], "fps": 0.0}
    finished = threading.Event()

    def _worker():
        nonlocal result
        try:
            # Handle local webcam index
            if url.isdigit():
                cap = cv2.VideoCapture(int(url))
            else:
                cap = cv2.VideoCapture(url)

            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None and frame.size > 0:
                    h, w = frame.shape[:2]
                    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
                    result["success"] = True
                    result["message"] = f"Camera connected successfully ({w}x{h} @ {fps:.1f} FPS)."
                    result["resolution"] = [w, h]
                    result["fps"] = round(fps, 1)
                else:
                    result["message"] = "Connected to stream, but failed to read initial video frame."
                cap.release()
            else:
                result["message"] = "Could not open camera stream. Check IP, Port, Username and Password."
        except Exception as e:
            result["message"] = f"Connection error: {str(e)}"
        finally:
            finished.set()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    finished.wait(timeout=timeout_s)

    if not finished.is_set():
        return {"success": False, "message": f"Connection timed out after {timeout_s}s. Verify camera network and firewall."}

    return result


class RTSPStreamWorker:
    """
    High-Reliability Video Capture Worker:
    - Runs in an isolated background thread.
    - Constant zero-latency frame flushing (drops stale frames so AI always gets the real-time frame).
    - Auto-reconnection with exponential backoff on dropped network packets.
    - Zero server blocking.
    """
    def __init__(self, camera_id: str, stream_url: str, health_monitor: Optional[CameraHealthMonitor] = None):
        self.camera_id = camera_id
        self.stream_url = stream_url
        self.health = health_monitor or CameraHealthMonitor(camera_id)

        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

        self.current_frame: Optional[np.ndarray] = None
        self.frame_width = 960
        self.frame_height = 540

        # Max reconnect backoff
        self.min_backoff_sec = 1.0
        self.max_backoff_sec = 10.0

    def start(self):
        with self.lock:
            if self.running:
                return
            self.running = True
            self.thread = threading.Thread(target=self._capture_loop, name=f"cam-worker-{self.camera_id}", daemon=True)
            self.thread.start()

    def stop(self):
        with self.lock:
            self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.5)
        self.health.record_disconnection("Worker stopped by user.")

    def get_latest_frame(self) -> Optional[np.ndarray]:
        """Returns the most recent real-time frame (thread-safe, non-blocking)."""
        with self.lock:
            if self.current_frame is not None:
                return self.current_frame.copy()
        return None

    def _capture_loop(self):
        backoff = self.min_backoff_sec

        while self.running:
            # 1. Establish connection
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay"
            cap = None
            try:
                if self.stream_url.isdigit():
                    cap = cv2.VideoCapture(int(self.stream_url))
                else:
                    cap = cv2.VideoCapture(self.stream_url)

                if not cap.isOpened():
                    self.health.record_reconnect_attempt(f"Failed to open camera: {self.stream_url}")
                    time.sleep(backoff)
                    backoff = min(self.max_backoff_sec, backoff * 1.5)
                    continue

                # Connection successful: reset backoff
                backoff = self.min_backoff_sec
                self.health.record_frame()

                consecutive_failures = 0

                # 2. Continuous frame reading loop
                while self.running and cap.isOpened():
                    t_start = time.time()
                    ret = cap.grab()
                    if not ret:
                        consecutive_failures += 1
                        self.health.record_dropped_frame()
                        if consecutive_failures > 30: # ~1 sec of continuous failure
                            self.health.record_reconnect_attempt("Dropped stream packets. Reconnecting...")
                            break
                        time.sleep(0.01)
                        continue

                    consecutive_failures = 0
                    ret, frame = cap.retrieve()
                    if ret and frame is not None and frame.size > 0:
                        lat_ms = (time.time() - t_start) * 1000.0
                        self.health.record_frame(lat_ms)

                        h, w = frame.shape[:2]
                        with self.lock:
                            self.current_frame = frame
                            self.frame_width = w
                            self.frame_height = h
                    else:
                        self.health.record_dropped_frame()

                    # Prevent CPU burning while retaining real-time rate (up to 30 FPS)
                    time.sleep(0.005)

            except Exception as e:
                self.health.record_reconnect_attempt(f"Capture worker error: {str(e)}")
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

            if self.running:
                time.sleep(backoff)
                backoff = min(self.max_backoff_sec, backoff * 1.5)
