import re
import socket
import uuid
import xml.etree.ElementTree as ET
from typing import List, Dict, Any

class ONVIFDiscovery:
    """
    ONVIF WS-Discovery engine.
    Scans local area network for ONVIF-compliant CCTV cameras and DVR/NVRs.
    """
    WS_DISCOVERY_PROBE = """<?xml version="1.0" encoding="utf-8"?>
    <Envelope xmlns:tds="http://www.onvif.org/ver10/device/wsdl"
              xmlns="http://www.w3.org/2003/05/soap-envelope">
      <Header>
        <wsa:MessageID xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">uuid:{msg_id}</wsa:MessageID>
        <wsa:To xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
        <wsa:Action xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
      </Header>
      <Body>
        <Probe xmlns="http://schemas.xmlsoap.org/ws/2005/04/discovery">
          <Types>tds:Device</Types>
        </Probe>
      </Body>
    </Envelope>"""

    @classmethod
    def discover_devices(cls, timeout_s: float = 2.0) -> List[Dict[str, Any]]:
        """
        Sends WS-Discovery multicast UDP packet to 239.255.255.250:3702 and parses replies.
        """
        devices = []
        seen_ips = set()
        msg_id = str(uuid.uuid4())
        probe_xml = cls.WS_DISCOVERY_PROBE.format(msg_id=msg_id).encode("utf-8")

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout_s)

        try:
            sock.sendto(probe_xml, ("239.255.255.250", 3702))
            
            while True:
                try:
                    data, addr = sock.recvfrom(65535)
                    ip = addr[0]
                    if ip in seen_ips:
                        continue
                    seen_ips.add(ip)

                    xml_str = data.decode("utf-8", errors="ignore")
                    
                    # Extract hardware/brand if present in scopes
                    brand = "Generic ONVIF"
                    if "hikvision" in xml_str.lower():
                        brand = "Hikvision"
                    elif "dahua" in xml_str.lower():
                        brand = "Dahua"
                    elif "uniview" in xml_str.lower() or "unv" in xml_str.lower():
                        brand = "Uniview"
                    elif "cpplus" in xml_str.lower() or "cp plus" in xml_str.lower():
                        brand = "CP Plus"

                    devices.append({
                        "ip_address": ip,
                        "brand": brand,
                        "connection_type": "onvif",
                        "port": 80,
                        "onvif_service_url": f"http://{ip}:80/onvif/device_service",
                        "discovered_at": addr[0]
                    })
                except socket.timeout:
                    break
                except Exception:
                    break
        except Exception as e:
            print(f"[ONVIFDiscovery] Discovery scan error: {e}")
        finally:
            sock.close()

        return devices
