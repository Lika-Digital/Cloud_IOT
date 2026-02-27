"""
Optional auto-discovery services.
Both zeroconf and pysnmp are optional imports — if not installed the functions
return empty lists / False with a warning log instead of crashing.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def scan_mdns(timeout: float = 5.0) -> list[dict]:
    """
    Use zeroconf to find _rtsp._tcp.local. and _http._tcp.local. services.
    Returns [{name, address, port, type}].
    """
    try:
        from zeroconf import Zeroconf, ServiceBrowser
        from zeroconf._utils.ipaddress import address_to_string
    except ImportError:
        logger.warning("zeroconf not installed — mDNS scan unavailable. Run: pip install zeroconf")
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
                results.append({
                    "name": name,
                    "address": addr,
                    "port": info.port,
                    "type": type_,
                })

        def remove_service(self, zc, type_, name):
            pass

        def update_service(self, zc, type_, name):
            pass

    service_types = ["_rtsp._tcp.local.", "_http._tcp.local.", "_onvif._tcp.local."]
    zc = Zeroconf()
    browsers = []
    listener = _Listener()
    try:
        for st in service_types:
            browsers.append(ServiceBrowser(zc, st, listener))
        await asyncio.sleep(timeout)
    finally:
        zc.close()

    return results


async def scan_snmp(
    subnet: str,
    community: str = "public",
    timeout: float = 2.0,
) -> list[dict]:
    """
    Walk a /24 subnet, SNMP GET sysDescr OID 1.3.6.1.2.1.1.1.0.
    Returns [{ip, sysDescr}].
    """
    try:
        from pysnmp.hlapi.asyncio import (
            getCmd, SnmpEngine, CommunityData, UdpTransportTarget, ContextData,
            ObjectType, ObjectIdentity,
        )
    except ImportError:
        logger.warning("pysnmp not installed — SNMP scan unavailable. Run: pip install pysnmp")
        return []

    # Parse the subnet (accept "192.168.1" or "192.168.1.0/24" or "192.168.1.x")
    base = subnet.strip()
    if "/" in base:
        base = base.split("/")[0]       # e.g. 192.168.1.0
        parts = base.rsplit(".", 1)[0]  # e.g. 192.168.1
    else:
        parts = base.rstrip(".0")       # strip trailing .0 or single digit

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
            # 2xx or 4xx (auth required) both mean the device is reachable
            return resp.status_code < 500
    except Exception:
        return False
