import cv2
import time
import numpy as np
from typing import Dict, Any, List, Optional, Generator
from backend.camera_registry import CameraRegistry
from backend.vendor_adapter import VendorCameraAdapter
from backend.onvif_connector import ONVIFDiscovery
from backend.rtsp_connector import test_rtsp_connection
from backend.database import (
    get_connection, get_all_cameras, get_camera_by_id,
    add_camera, update_camera, delete_camera, update_camera_status
)

class UniversalCameraManager:
    """
    Universal Camera Manager for AiCam Commercial Platform.
    Manages multi-brand CCTV discovery, credential security, connection testing,
    isolated background capture pipelines, and multi-camera stream dispatching.
    """
    def __init__(self):
        self.registry = CameraRegistry()
        self._init_active_cameras_from_db()

    def _init_active_cameras_from_db(self):
        """Initializes and connects active cameras saved in database."""
        try:
            cameras = get_all_cameras()
            for cam in cameras:
                if cam.get("is_active"):
                    cid = cam["camera_id"]
                    url = cam.get("sub_rtsp_url") or cam.get("main_rtsp_url")
                    if url:
                        print(f"[CameraManager] Initializing camera: {cam['name']} ({cid})")
                        self.registry.register_camera(cid, url)
        except Exception as e:
            print(f"[CameraManager] Error loading initial cameras: {e}")

    def discover_network_cameras(self) -> List[Dict[str, Any]]:
        """Scans local network for ONVIF IP cameras and NVRs."""
        return ONVIFDiscovery.discover_devices(timeout_s=2.0)

    def test_camera_connection(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Tests stream connectivity without storing."""
        brand = config.get("brand", "generic_rtsp")
        ip = config.get("ip_address", "").strip()
        port = int(config.get("port") or 554)
        user = config.get("username", "admin").strip()
        pwd = config.get("password", "").strip()
        channel = int(config.get("channel") or 1)
        quality = config.get("stream_quality", "sub")
        custom_path = config.get("rtsp_path")

        url = VendorCameraAdapter.build_rtsp_url(
            brand=brand, ip_address=ip, port=port, username=user, password=pwd,
            channel=channel, stream_quality=quality, custom_path=custom_path
        )
        test_res = test_rtsp_connection(url, timeout_s=3.5)
        test_res["constructed_url_masked"] = VendorCameraAdapter.mask_credentials(url)
        return test_res

    def add_new_camera(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validates, builds vendor stream paths, saves camera to DB and starts isolated worker."""
        brand = config.get("brand", "generic_rtsp")
        ip = config.get("ip_address", "127.0.0.1").strip()
        port = int(config.get("port") or 554)
        user = config.get("username", "admin").strip()
        pwd = config.get("password", "").strip()
        channel = int(config.get("channel") or 1)
        name = config.get("name") or f"Camera {ip}"
        assigned_module = config.get("assigned_module", "attendance")

        # Build main & sub URLs
        main_url = VendorCameraAdapter.build_rtsp_url(brand, ip, port, user, pwd, channel, "main", config.get("rtsp_path"))
        sub_url = VendorCameraAdapter.build_rtsp_url(brand, ip, port, user, pwd, channel, "sub", config.get("rtsp_path"))

        cam_data = {
            "name": name,
            "brand": brand,
            "connection_type": config.get("connection_type", "rtsp"),
            "ip_address": ip,
            "port": port,
            "username": user,
            "password": pwd,
            "channel": channel,
            "rtsp_path": config.get("rtsp_path", ""),
            "stream_quality": config.get("stream_quality", "sub"),
            "main_rtsp_url": main_url,
            "sub_rtsp_url": sub_url,
            "assigned_module": assigned_module,
            "geometry_config": config.get("geometry_config", "{}")
        }

        cid = add_camera(cam_data)
        # Register and start worker immediately
        chosen_stream = sub_url if config.get("stream_quality", "sub") == "sub" else main_url
        self.registry.register_camera(cid, chosen_stream)

        return {"status": "success", "camera_id": cid, "message": f"Camera '{name}' successfully registered and connected."}

    def get_camera_frame(self, camera_id: str) -> Optional[np.ndarray]:
        """Retrieves active real-time frame for requested camera."""
        return self.registry.get_frame(camera_id)

    def generate_mjpeg_stream(self, camera_id: str) -> Generator[bytes, None, None]:
        """Generates continuous MJPEG multipart stream for a specific camera view."""
        while True:
            frame = self.registry.get_frame(camera_id)
            if frame is None:
                # Standby frame
                standby = np.zeros((360, 640, 3), dtype=np.uint8)
                standby[:] = (15, 23, 42)
                cv2.putText(standby, f"Camera [{camera_id}] Connecting...", (40, 180),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (148, 163, 184), 2)
                ret, jpeg = cv2.imencode(".jpg", standby, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
            else:
                ret, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])

            if ret:
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")

            time.sleep(0.04) # ~25 FPS

    def get_all_camera_cards(self) -> List[Dict[str, Any]]:
        """Returns all registered cameras with real-time health stats and masked credentials."""
        cams = get_all_cameras()
        cards = []
        for c in cams:
            cid = c["camera_id"]
            health = self.registry.get_health(cid)
            cards.append({
                **c,
                "health": health,
                "fps": health.get("fps", 0.0),
                "status": health.get("status", c.get("status", "disconnected")),
                "main_rtsp_url_masked": VendorCameraAdapter.mask_credentials(c.get("main_rtsp_url") or ""),
                "sub_rtsp_url_masked": VendorCameraAdapter.mask_credentials(c.get("sub_rtsp_url") or "")
            })
        return cards
