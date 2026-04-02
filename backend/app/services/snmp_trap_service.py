"""
SNMP Trap Receiver — Cloud IoT NUC
────────────────────────────────────────────────────────────────────────────
Listens for incoming UDP SNMP v1/v2c traps from IP temperature sensors
(e.g. Papouch TME, generic SNMP-capable thermometers).

When a trap is received the service extracts OID→value pairs using a
minimal BER/ASN.1 decoder (no pysnmp dependency at runtime), then maps
a configured temperature OID to the standard temperature handler so the
reading is stored and broadcast to the dashboard exactly like a MQTT
temperature message.

Default port: 1620  (use 162 on Linux with root / CAP_NET_BIND_SERVICE)
Default community: "public"
Default temp OID: Papouch TME  1.3.6.1.4.1.18248.20.1.2.1.1.2.1
"""
import asyncio
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Runtime config (updated via settings API) ─────────────────────────────────

_config: dict = {
    "enabled":    True,
    "port":       int(os.environ.get("SNMP_TRAP_PORT", "1620")),
    "community":  os.environ.get("SNMP_COMMUNITY", "public"),
    "temp_oid":   os.environ.get("SNMP_TEMP_OID", "1.3.6.1.4.1.18248.20.1.2.1.1.2.1"),
    "pedestal_id": int(os.environ.get("SNMP_PEDESTAL_ID", "1")),
}

_transport: asyncio.BaseTransport | None = None


def get_config() -> dict:
    return dict(_config)


def update_config(updates: dict) -> dict:
    _config.update(updates)
    logger.info("[SNMP] Config updated: %s", updates)
    return dict(_config)


# ── Minimal BER/ASN.1 decoder ─────────────────────────────────────────────────

def _read_length(buf: bytes, pos: int) -> tuple[int, int]:
    b = buf[pos]; pos += 1
    if not (b & 0x80):
        return b, pos
    n = b & 0x7F
    length = 0
    for _ in range(n):
        length = (length << 8) | buf[pos]; pos += 1
    return length, pos


def _decode_oid(data: bytes) -> str:
    if not data:
        return ""
    parts = [data[0] // 40, data[0] % 40]
    acc = 0
    for b in data[1:]:
        acc = (acc << 7) | (b & 0x7F)
        if not (b & 0x80):
            parts.append(acc); acc = 0
    return ".".join(map(str, parts))


def _decode_value(tag: int, data: bytes) -> object:
    # INTEGER, Counter32, Gauge32, TimeTicks, Counter64
    if tag in (0x02, 0x41, 0x42, 0x43, 0x47):
        v = int.from_bytes(data, "big")
        if data and (data[0] & 0x80):
            v -= 1 << (8 * len(data))
        return v
    # OCTET STRING, Opaque — temperature sensors often encode value as ASCII "23.5"
    if tag in (0x04, 0x44):
        try:
            return float(data.decode("ascii").strip().rstrip("\x00"))
        except Exception:
            pass
        try:
            return data.decode("utf-8", errors="replace")
        except Exception:
            return data.hex()
    if tag == 0x06:
        return _decode_oid(data)
    if tag == 0x05:
        return None
    return data.hex()


def _extract_varbinds(buf: bytes) -> list[tuple[str, object]]:
    """
    Walk BER data and extract (oid_string, value) pairs from VarBind sequences.
    Handles SNMP v1 and v2c message structures at any nesting depth.
    """
    results: list[tuple[str, object]] = []

    def _walk(data: bytes, depth: int = 0):
        if depth > 8:
            return
        pos = 0
        while pos < len(data):
            if pos >= len(data):
                break
            try:
                tag = data[pos]; pos += 1
                length, pos = _read_length(data, pos)
                val = data[pos: pos + length]
                pos += length
            except (IndexError, Exception):
                break

            # Constructed: SEQUENCE (0x30) or context-specific (0xA0–0xAF)
            if tag == 0x30 or (0xA0 <= tag <= 0xAF):
                # Check if this is a VarBind: SEQUENCE { OID, value }
                if val and val[0] == 0x06:
                    try:
                        oid_tag = val[0]; inner_pos = 1
                        oid_len, inner_pos = _read_length(val, inner_pos)
                        oid_bytes = val[inner_pos: inner_pos + oid_len]
                        inner_pos += oid_len
                        if inner_pos < len(val):
                            val_tag = val[inner_pos]; inner_pos += 1
                            val_len, inner_pos = _read_length(val, inner_pos)
                            val_bytes = val[inner_pos: inner_pos + val_len]
                            end_pos   = inner_pos + val_len
                            # Only treat as a VarBind if there are no leftover bytes —
                            # SNMPv1 Trap-PDU starts with enterprise OID + more fields
                            # which would leave trailing bytes and must be walked instead
                            if end_pos >= len(val):
                                oid_str = _decode_oid(oid_bytes)
                                pval    = _decode_value(val_tag, val_bytes)
                                results.append((oid_str, pval))
                                continue
                    except Exception:
                        pass
                _walk(val, depth + 1)

    _walk(buf)
    return results


# ── Asyncio UDP protocol ───────────────────────────────────────────────────────

class _SnmpTrapProtocol(asyncio.DatagramProtocol):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def datagram_received(self, data: bytes, addr: tuple):
        host, port = addr
        logger.debug("[SNMP] Trap from %s:%s  (%d bytes)", host, port, len(data))
        try:
            varbinds = _extract_varbinds(data)
            asyncio.run_coroutine_threadsafe(
                _process_varbinds(varbinds, host),
                self._loop,
            )
        except Exception as exc:
            logger.warning("[SNMP] Parse error from %s: %s", host, exc)

    def error_received(self, exc: Exception):
        logger.warning("[SNMP] Transport error: %s", exc)

    def connection_lost(self, exc):
        logger.info("[SNMP] Trap listener closed")


async def _process_varbinds(varbinds: list[tuple[str, object]], sender_ip: str):
    temp_oid    = _config["temp_oid"]
    pedestal_id = _config["pedestal_id"]

    for oid, value in varbinds:
        # Match on full OID or suffix (sensor may send shorter/longer OID)
        if oid == temp_oid or oid.endswith(temp_oid) or temp_oid.endswith(oid):
            try:
                temp_val = float(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                logger.warning("[SNMP] Non-numeric temp value from %s: %r", sender_ip, value)
                continue

            logger.info("[SNMP] Temperature %.1f°C from %s (OID %s)", temp_val, sender_ip, oid)

            # Re-use the MQTT temperature handler — same logic, storage, alarm, broadcast
            import json
            from .mqtt_handlers import handle_message
            payload = json.dumps({"value": round(temp_val, 2)})
            await handle_message(f"pedestal/{pedestal_id}/sensors/temperature", payload)
            return

    if varbinds:
        logger.info("[SNMP] Trap from %s — no matching temp OID (watching: %s). VarBinds: %s",
                    sender_ip, temp_oid, [(o, v) for o, v in varbinds[:5]])


# ── Service start / stop ──────────────────────────────────────────────────────

async def start(loop: asyncio.AbstractEventLoop):
    global _transport
    if not _config["enabled"]:
        logger.info("[SNMP] Trap receiver disabled (SNMP_TRAP_PORT=0 or enabled=False)")
        return

    port = _config["port"]
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _SnmpTrapProtocol(loop),
            local_addr=("0.0.0.0", port),
        )
        _transport = transport
        logger.info("[SNMP] Trap receiver listening on UDP 0.0.0.0:%d", port)
        logger.info("[SNMP] Watching OID: %s  →  pedestal %d",
                    _config["temp_oid"], _config["pedestal_id"])
    except PermissionError:
        logger.warning(
            "[SNMP] Cannot bind UDP port %d (permission denied). "
            "On Linux use port 1620+ or: sudo setcap 'cap_net_bind_service=+ep' $(which python3)",
            port,
        )
    except Exception as exc:
        logger.error("[SNMP] Failed to start trap receiver: %s", exc)


def stop():
    global _transport
    if _transport:
        _transport.close()
        _transport = None
        logger.info("[SNMP] Trap receiver stopped")
