import threading
import numpy as np
from typing import Dict, Optional, List, Any
from backend.rtsp_connector import RTSPStreamWorker
from backend.camera_health_monitor import CameraHealthMonitor

class CameraRegistry:
    """
    In-memory registry and lifecycle manager for all camera workers.
    Ensures complete thread isolation:
    A failure or disconnect on one camera NEVER affects any other camera!
    """
    def __init__(self):
        self._workers: Dict[str, RTSPStreamWorker] = {}
        self._health_monitors: Dict[str, CameraHealthMonitor] = {}
        self.lock = threading.Lock()

    def register_camera(self, camera_id: str, stream_url: str) -> RTSPStreamWorker:
        """Creates and starts an isolated RTSP worker for a camera."""
        with self.lock:
            if camera_id in self._workers:
                self._workers[camera_id].stop()

            health = CameraHealthMonitor(camera_id)
            worker = RTSPStreamWorker(camera_id, stream_url, health)
            self._workers[camera_id] = worker
            self._health_monitors[camera_id] = health
            worker.start()
            return worker

    def unregister_camera(self, camera_id: str):
        with self.lock:
            if camera_id in self._workers:
                self._workers[camera_id].stop()
                del self._workers[camera_id]
            if camera_id in self._health_monitors:
                del self._health_monitors[camera_id]

    def get_worker(self, camera_id: str) -> Optional[RTSPStreamWorker]:
        with self.lock:
            return self._workers.get(camera_id)

    def get_frame(self, camera_id: str) -> Optional[np.ndarray]:
        with self.lock:
            worker = self._workers.get(camera_id)
        if worker:
            return worker.get_latest_frame()
        return None

    def get_health(self, camera_id: str) -> Dict[str, Any]:
        with self.lock:
            monitor = self._health_monitors.get(camera_id)
        if monitor:
            return monitor.get_stats()
        return {"camera_id": camera_id, "status": "offline", "fps": 0.0, "latency_ms": 0.0}

    def get_all_active_ids(self) -> List[str]:
        with self.lock:
            return list(self._workers.keys())

    def shutdown_all(self):
        with self.lock:
            for cid, w in self._workers.items():
                w.stop()
            self._workers.clear()
            self._health_monitors.clear()
