import re
from typing import Dict, Any, Tuple, Optional

class VendorCameraAdapter:
    """
    Universal Camera Vendor URL and protocol builder.
    Constructs accurate RTSP URLs and API paths for all major CCTV DVR/NVRs:
    - Hikvision
    - Dahua
    - CP Plus
    - Uniview
    - Generic RTSP
    - ONVIF
    - USB Webcams
    """

    @staticmethod
    def build_rtsp_url(
        brand: str,
        ip_address: str,
        port: int = 554,
        username: str = "admin",
        password: str = "",
        channel: int = 1,
        stream_quality: str = "sub",
        custom_path: Optional[str] = None
    ) -> str:
        """
        Builds the exact RTSP streaming URL for the requested brand and channel.
        """
        brand = (brand or "generic_rtsp").lower().strip()
        stream_quality = (stream_quality or "sub").lower().strip()
        channel = max(1, int(channel or 1))
        port = int(port or 554)
        ip = (ip_address or "").strip()

        # Direct camera index or existing full URL
        if brand == "webcam" or ip in ("0", "1", "2", "3", "4"):
            return ip
        if ip.startswith(("rtsp://", "http://", "https://")):
            return ip

        # Format credentials
        creds = f"{username}:{password}@" if username else ""

        # Custom path overrides vendor presets
        if custom_path and custom_path.strip():
            path = custom_path.strip().lstrip("/")
            return f"rtsp://{creds}{ip}:{port}/{path}"

        if brand in ("hikvision", "hik_connect"):
            # Hikvision RTSP format:
            # Channel 1: 101 (Main Stream), 102 (Sub Stream)
            # Channel 2: 201 (Main Stream), 202 (Sub Stream)
            subtype = "01" if stream_quality == "main" else "02"
            chan_code = f"{channel}{subtype}"
            return f"rtsp://{creds}{ip}:{port}/Streaming/Channels/{chan_code}"

        elif brand in ("dahua", "dahua_nvr"):
            # Dahua RTSP format:
            # subtype=0 (Main Stream), subtype=1 (Sub Stream)
            subtype = 0 if stream_quality == "main" else 1
            return f"rtsp://{creds}{ip}:{port}/cam/realmonitor?channel={channel}&subtype={subtype}"

        elif brand in ("cpplus", "cp_plus"):
            # CP Plus commonly uses Dahua OEM streaming syntax
            subtype = 0 if stream_quality == "main" else 1
            return f"rtsp://{creds}{ip}:{port}/cam/realmonitor?channel={channel}&subtype={subtype}"

        elif brand in ("uniview", "unv"):
            # Uniview RTSP format:
            # s0 (Main Stream), s1 (Sub Stream)
            stream_code = "s0" if stream_quality == "main" else "s1"
            return f"rtsp://{creds}{ip}:{port}/unicast/c{channel}/{stream_code}/live"

        else:
            # Generic RTSP default
            path = "h264Preview_01_main" if stream_quality == "main" else "h264Preview_01_sub"
            return f"rtsp://{creds}{ip}:{port}/{path}"

    @staticmethod
    def mask_credentials(url: str) -> str:
        """
        Masks password in RTSP / HTTP URL for safe display in UI, API responses and logs.
        E.g. rtsp://admin:myPass123@192.168.1.130:554/ch1 -> rtsp://admin:*****@192.168.1.130:554/ch1
        """
        if not url:
            return ""
        # Match rtsp://username:password@
        pattern = r"(rtsp://[^:]+:)([^@]+)(@)"
        return re.sub(pattern, r"\1*****\3", url)

    @staticmethod
    def parse_rtsp_components(url: str) -> Dict[str, Any]:
        """
        Extracts components from an RTSP URL.
        """
        if not url or not url.startswith("rtsp://"):
            return {"valid": False, "raw": url}

        # rtsp://[user[:pass]@]host[:port][/path]
        regex = r"^rtsp://(?:(?P<user>[^:]+)(?::(?P<pass>[^@]*))?@)?(?P<host>[^:/]+)(?::(?P<port>\d+))?(?P<path>/.*)?$"
        match = re.match(regex, url)
        if match:
            d = match.groupdict()
            return {
                "valid": True,
                "username": d.get("user") or "",
                "password": d.get("pass") or "",
                "host": d.get("host") or "",
                "port": int(d.get("port") or 554),
                "path": d.get("path") or "",
                "masked": VendorCameraAdapter.mask_credentials(url)
            }
        return {"valid": False, "raw": url}
