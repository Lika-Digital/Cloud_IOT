"""
Device auto-discovery for Cloud IoT NUC.

Three discovery methods:
  1. ONVIF WS-Discovery  — UDP multicast, finds D-Link DCS-TF2283AI-DL cameras
  2. Papouch TME scan    — HTTP /values.xml probe on local subnet
  3. mDNS scan           — Zeroconf _rtsp._tcp / _onvif._tcp (supplementary)

SNMP scan kept for backward compat but not used in main flow.
"""
import asyncio
import logging
import re
import socket
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_local_subnet() -> str:
    """
    Auto-detect the local /24 subnet (e.g. '192.168.1').
    Tries to find the LAN IP by connecting a UDP socket (no packet sent).
    Falls back to '192.168.1'.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ".".join(ip.split(".")[:3])
    except Exception:
        return "192.168.1"


# ─── ONVIF WS-Discovery ───────────────────────────────────────────────────────

_WSD_MULTICAST_IP   = "239.255.255.250"
_WSD_MULTICAST_PORT = 3702

_WSD_PROBE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"'
    ' xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"'
    ' xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
    "<e:Header>"
    "<w:MessageID>uuid:{msg_id}</w:MessageID>"
    "<w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>"
    "<w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>"
    "</e:Header>"
    "<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>"
    "</e:Envelope>"
)


def _extract_onvif_urls(xml_text: str) -> list[str]:
    """Pull XAddrs (device service URLs) from a WS-Discovery ProbeMatch response."""
    matches = re.findall(r"<[^>]*XAddrs[^>]*>([^<]+)</[^>]*XAddrs>", xml_text)
    urls = []
    for m in matches:
        for part in m.split():
            part = part.strip()
            if part.startswith("http"):
                urls.append(part)
    return urls


def _extract_ip_from_url(url: str) -> str:
    """Extract IP from http://192.168.1.x:port/path"""
    m = re.search(r"https?://([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", url)
    return m.group(1) if m else ""


async def scan_onvif(timeout: float = 3.0) -> list[dict]:
    """
    WS-Discovery UDP multicast probe on 239.255.255.250:3702.
    Returns [{ip, onvif_url, name}] for each responding ONVIF device.
    Compatible with D-Link DCS-TF2283AI-DL and any ONVIF camera.
    """
    results: list[dict] = []
    msg_id = str(uuid.uuid4())
    probe = _WSD_PROBE.format(msg_id=msg_id).encode("utf-8")

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
    sock.settimeout(0.1)

    seen_ips: set[str] = set()
    try:
        sock.sendto(probe, (_WSD_MULTICAST_IP, _WSD_MULTICAST_PORT))
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                data, addr = sock.recvfrom(4096)
                xml = data.decode("utf-8", errors="replace")
                urls = _extract_onvif_urls(xml)
                ip = addr[0]
                if ip in seen_ips:
                    continue
                seen_ips.add(ip)
                onvif_url = urls[0] if urls else f"http://{ip}/onvif/device_service"
                results.append({
                    "ip": ip,
                    "onvif_url": onvif_url,
                    "type": "camera_onvif",
                    "name": f"ONVIF Camera ({ip})",
                })
                logger.info(f"[ONVIF] Found device at {ip} → {onvif_url}")
            except socket.timeout:
                await asyncio.sleep(0.1)
            except Exception as exc:
                logger.debug(f"[ONVIF] recv error: {exc}")
                await asyncio.sleep(0.05)
    except Exception as exc:
        logger.warning(f"[ONVIF] scan error: {exc}")
    finally:
        sock.close()

    return results


# ─── Papouch TME temperature sensor ──────────────────────────────────────────

async def check_tme_sensor(ip: str, port: int = 80) -> Optional[dict]:
    """
    Probe a single IP for a Papouch TME temperature sensor via HTTP /values.xml.
    Returns {ip, port, temperature, unit} if found, None otherwise.
    The TME returns XML: <root><sns><sn0><v>23.5</v><u>C</u>...
    """
    try:
        import httpx
        url = f"http://{ip}:{port}/values.xml"
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and "xml" in resp.headers.get("content-type", "").lower():
                xml = resp.text
                # Papouch TME XML: <v>23.5</v><u>C</u>
                temp_match = re.search(r"<v>([\-0-9.]+)</v>", xml)
                unit_match = re.search(r"<u>([^<]+)</u>", xml)
                if temp_match:
                    return {
                        "ip": ip,
                        "port": port,
                        "protocol": "http",
                        "type": "temp_sensor_tme",
                        "name": f"Papouch TME ({ip})",
                        "temperature": float(temp_match.group(1)),
                        "unit": unit_match.group(1) if unit_match else "C",
                    }
            # Fallback: check root page for "Papouch" or "TME" in response
            url_root = f"http://{ip}:{port}/"
            resp2 = await client.get(url_root)
            if resp2.status_code == 200:
                body = resp2.text.lower()
                if "papouch" in body or "tme" in body or "thermometer" in body:
                    return {
                        "ip": ip,
                        "port": port,
                        "protocol": "http",
                        "type": "temp_sensor_tme",
                        "name": f"Papouch TME ({ip})",
                        "temperature": None,
                        "unit": "C",
                    }
    except Exception:
        pass
    return None


async def scan_tme_sensors(subnet: str = "", timeout: float = 3.0) -> list[dict]:
    """
    Scan the local /24 subnet for Papouch TME temperature sensors.
    Probes http://<ip>/values.xml on each host.
    Returns [{ip, port, protocol, temperature, unit}].
    """
    if not subnet:
        subnet = get_local_subnet()

    # Probe all 254 hosts concurrently with a semaphore to avoid flooding
    sem = asyncio.Semaphore(50)

    async def _probe(i: int):
        ip = f"{subnet}.{i}"
        async with sem:
            return await check_tme_sensor(ip)

    tasks = [_probe(i) for i in range(1, 255)]
    raw = await asyncio.gather(*tasks, return_exceptions=True)
    results = [r for r in raw if isinstance(r, dict)]

    for r in results:
        logger.info(f"[TME] Found sensor at {r['ip']}: {r.get('temperature')}°{r.get('unit')}")
    return results


async def check_camera(
    url: str,
    username: str = "",
    password: str = "",
) -> bool:
    """
    HTTP HEAD to camera URL, return True if 2xx or 4xx (device reachable).
    """
    if not url:
        return False
    try:
        import httpx
        auth = (username, password) if username else None
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            resp = await client.head(url, auth=auth)
            return resp.status_code < 500
    except Exception:
        return False


# ─── Unified scan ─────────────────────────────────────────────────────────────

async def scan_all(subnet: str = "", timeout: float = 5.0) -> dict:
    """
    Run ONVIF WS-Discovery and TME subnet scan concurrently.
    Returns:
      {
        cameras:     [{ip, onvif_url, type, name}],
        temp_sensors: [{ip, port, protocol, type, name, temperature, unit}],
        subnet:      "192.168.1",
      }
    """
    if not subnet:
        subnet = get_local_subnet()

    logger.info(f"[Discovery] Starting full scan on subnet {subnet}.0/24 (timeout={timeout}s)")

    cameras_task      = asyncio.create_task(scan_onvif(timeout=min(timeout, 3.0)))
    temp_sensors_task = asyncio.create_task(scan_tme_sensors(subnet=subnet, timeout=timeout))

    cameras, temp_sensors = await asyncio.gather(cameras_task, temp_sensors_task)

    logger.info(f"[Discovery] Done — cameras: {len(cameras)}, temp sensors: {len(temp_sensors)}")
    return {
        "cameras": cameras,
        "temp_sensors": temp_sensors,
        "subnet": subnet,
    }


# ─── mDNS (kept for supplementary use) ───────────────────────────────────────

async def scan_mdns(timeout: float = 5.0) -> list[dict]:
    """
    Use zeroconf to find _rtsp._tcp.local., _http._tcp.local., _onvif._tcp.local. services.
    Returns [{name, address, port, type}].
    """
    try:
        from zeroconf import Zeroconf, ServiceBrowser
        from zeroconf._utils.ipaddress import address_to_string
    except ImportError:
        logger.warning("zeroconf not installed — mDNS scan unavailable.")
        return []

    results: list[dict] = []

    class _Listener:
        def add_service(self, zc: Zeroconf, type_: str, name: str):
            info = zc.get_service_info(type_, name)
            if info:
                try:
                    addr = address_to_string(info.addresses[0]) if info.addresses else "unknown"
                except Exception:
                    addr = "unknown"
                results.append({"name": name, "address": addr, "port": info.port, "type": type_})

        def remove_service(self, zc, type_, name): pass
        def update_service(self, zc, type_, name): pass

    service_types = ["_rtsp._tcp.local.", "_http._tcp.local.", "_onvif._tcp.local."]
    zc = Zeroconf()
    listener = _Listener()
    try:
        for st in service_types:
            ServiceBrowser(zc, st, listener)
        await asyncio.sleep(timeout)
    finally:
        zc.close()

    return results


# ─── SNMP (kept for backward compat) ─────────────────────────────────────────

async def scan_snmp(
    subnet: str,
    community: str = "public",
    timeout: float = 2.0,
) -> list[dict]:
    """Walk /24 subnet via SNMP GET sysDescr. Returns [{ip, sysDescr}]."""
    try:
        from pysnmp.hlapi.asyncio import (
            getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData,
            ObjectType, ObjectIdentity,
        )
    except ImportError:
        logger.warning("pysnmp not installed — SNMP scan unavailable.")
        return []

    base = subnet.strip()
    if "/" in base:
        base = base.split("/")[0]
        parts = base.rsplit(".", 1)[0]
    else:
        parts = base.rstrip(".0")

    results: list[dict] = []

    async def _get_one(ip: str):
        try:
            engine = SnmpEngine()
            iterator = getCmd(
                engine,
                CommunityData(community, mpModel=0),
                UdpTransportTarget((ip, 161), timeout=timeout, retries=0),
                ContextData(),
                ObjectType(ObjectIdentity("1.3.6.1.2.1.1.1.0")),
            )
            error_indication, error_status, _, var_binds = await iterator
            if not error_indication and not error_status:
                for _, val in var_binds:
                    results.append({"ip": ip, "sysDescr": str(val)})
        except Exception:
            pass

    tasks = [_get_one(f"{parts}.{i}") for i in range(1, 255)]
    await asyncio.gather(*tasks)
    return results
