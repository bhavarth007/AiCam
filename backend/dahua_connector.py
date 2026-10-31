from typing import Dict, Any
from backend.vendor_adapter import VendorCameraAdapter

class DahuaConnector:
    """
    Dahua & CP Plus DVR/NVR and IP Camera adapter.
    Constructs high-reliability RTSP streams and channel mappings.
    """
    @staticmethod
    def get_stream_urls(ip: str, port: int = 554, user: str = "admin", password: str = "", channel: int = 1) -> Dict[str, str]:
        main_url = VendorCameraAdapter.build_rtsp_url("dahua", ip, port, user, password, channel, "main")
        sub_url = VendorCameraAdapter.build_rtsp_url("dahua", ip, port, user, password, channel, "sub")
        return {
            "main_stream": main_url,
            "sub_stream": sub_url,
            "main_masked": VendorCameraAdapter.mask_credentials(main_url),
            "sub_masked": VendorCameraAdapter.mask_credentials(sub_url)
        }
