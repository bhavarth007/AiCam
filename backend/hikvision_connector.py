import requests
from typing import Dict, Any, List
from backend.vendor_adapter import VendorCameraAdapter

class HikvisionConnector:
    """
    Hikvision DVR/NVR and IP Camera adapter.
    Supports channel probing, ISAPI device info, and RTSP stream path generation.
    """
    @staticmethod
    def get_stream_urls(ip: str, port: int = 554, user: str = "admin", password: str = "", channel: int = 1) -> Dict[str, str]:
        main_url = VendorCameraAdapter.build_rtsp_url("hikvision", ip, port, user, password, channel, "main")
        sub_url = VendorCameraAdapter.build_rtsp_url("hikvision", ip, port, user, password, channel, "sub")
        return {
            "main_stream": main_url,
            "sub_stream": sub_url,
            "main_masked": VendorCameraAdapter.mask_credentials(main_url),
            "sub_masked": VendorCameraAdapter.mask_credentials(sub_url)
        }

    @staticmethod
    def probe_device_info(ip: str, http_port: int = 80, user: str = "admin", password: str = "", timeout: float = 2.0) -> Dict[str, Any]:
        """
        Queries Hikvision ISAPI /ISAPI/System/deviceInfo to retrieve model, serial, and firmware.
        """
        url = f"http://{ip}:{http_port}/ISAPI/System/deviceInfo"
        try:
            res = requests.get(url, auth=requests.auth.HTTPDigestAuth(user, password), timeout=timeout)
            if res.status_code == 200:
                return {"online": True, "auth_type": "digest", "raw_xml": res.text[:300]}
        except Exception:
            pass
        return {"online": False}
