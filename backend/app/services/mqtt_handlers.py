import json
import logging
import re
from datetime import datetime, timedelta

from ..database import SessionLocal
from ..services.session_service import session_service
from ..services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

# Tracks most-recent heartbeat per pedestal — read by _comm_loss_watchdog in main.py
last_heartbeat: dict[int, datetime] = {}

# Cached cabinetId from opta/status heartbeats — used as fallback when
# opta/sockets/… and opta/water/… payloads omit cabinetId.
_opta_cached_cabinet_id: str | None = None

# Topic patterns — legacy pedestal/... schema
SOCKET_STATUS_RE  = re.compile(r"pedestal/(\d+)/socket/(\d+)/status")
SOCKET_POWER_RE   = re.compile(r"pedestal/(\d+)/socket/(\d+)/power")
WATER_FLOW_RE     = re.compile(r"pedestal/(\d+)/water/flow")
HEARTBEAT_RE      = re.compile(r"pedestal/(\d+)/heartbeat")
SENSOR_TEMP_RE    = re.compile(r"pedestal/(\d+)/sensors/temperature")
SENSOR_MOIST_RE   = re.compile(r"pedestal/(\d+)/sensors/moisture")
DIAGNOSTICS_RE    = re.compile(r"pedestal/(\d+)/diagnostics/response")
SENSOR_REGISTER_RE = re.compile(r"pedestal/(\d+)/register")

# Topic patterns — marina cabinet firmware schema (real hardware)
MARINA_SOCKET_RE  = re.compile(r"marina/cabinet/([^/]+)/sockets/([^/]+)/state")
MARINA_WATER_RE   = re.compile(r"marina/cabinet/([^/]+)/water/([^/]+)/state")
MARINA_DOOR_RE    = re.compile(r"marina/cabinet/([^/]+)/door/state")
MARINA_STATUS_RE  = re.compile(r"marina/cabinet/([^/]+)/status")
MARINA_EVENTS_RE  = re.compile(r"marina/cabinet/([^/]+)/events")
MARINA_ACKS_RE    = re.compile(r"marina/cabinet/([^/]+)/acks")

# Topic patterns — opta firmware schema (cabinetId carried in JSON payload, not in topic)
OPTA_STATUS_RE       = re.compile(r"opta/status")
OPTA_SOCKET_RE       = re.compile(r"opta/sockets/([^/]+)/status")
OPTA_SOCKET_POWER_RE = re.compile(r"opta/sockets/([^/]+)/power")
OPTA_WATER_RE        = re.compile(r"opta/water/([^/]+)/status")
OPTA_DOOR_RE         = re.compile(r"opta/door/status")
OPTA_EVENTS_RE       = re.compile(r"opta/events")
OPTA_ACKS_RE         = re.compile(r"opta/acks")


def _hw_warn(source: str, message: str, details: str | None = None):
    try:
        from .error_log_service import log_warning
        log_warning("hw", source, message, details=details)
    except Exception:
        pass


def _hw_error(source: str, message: str, details: str | None = None):
    try:
        from .error_log_service import log_error
        log_error("hw", source, message, details=details)
    except Exception:
        pass


def _ensure_pedestal(db, pedestal_id: int):
    """
    Auto-create a Pedestal row the first time any MQTT message arrives for it.
    Called inside an open DB session — caller must commit.
    """
    from ..models.pedestal import Pedestal
    if not db.get(Pedestal, pedestal_id):
        db.add(Pedestal(
            id=pedestal_id,
            name=f"Pedestal {pedestal_id}",
            location="",
            data_mode="real",
            initialized=False,
            mobile_enabled=False,
        ))
        db.commit()
        logger.info("Auto-created Pedestal %d from first MQTT message", pedestal_id)


def _cabinet_to_pedestal_id(db, cabinet_id: str) -> int | None:
    """
    Resolve a marina cabinet string ID (e.g. 'MAR_KRK_ORM_01') to a numeric pedestal_id.
    Looks up PedestalConfig.opta_client_id; auto-creates the Pedestal + PedestalConfig
    on first contact so a new cabinet becomes visible in the dashboard immediately.
    """
    from ..models.pedestal_config import PedestalConfig
    from ..models.pedestal import Pedestal

    cfg = db.query(PedestalConfig).filter(
        PedestalConfig.opta_client_id == cabinet_id
    ).first()
    if cfg:
        return cfg.pedestal_id

    # Auto-create: find the next free pedestal id
    existing_ids = [p.id for p in db.query(Pedestal).all()]
    new_id = max(existing_ids, default=0) + 1

    db.add(Pedestal(
        id=new_id,
        name=cabinet_id,
        location="",
        data_mode="real",
        initialized=False,
        mobile_enabled=False,
    ))
    db.flush()

    new_cfg = PedestalConfig(
        pedestal_id=new_id,
        opta_client_id=cabinet_id,
        opta_connected=0,
    )
    db.add(new_cfg)
    db.commit()
    logger.info("Auto-created Pedestal %d for marina cabinet '%s'", new_id, cabinet_id)
    return new_id


def _socket_name_to_id(name: str) -> int:
    """E1→1, E2→2, E3→3, E4→4; Q1→1, Q2→2, Q3→3, Q4→4; fallback: strip non-digits."""
    mapping = {"E1": 1, "E2": 2, "E3": 3, "E4": 4,
               "Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}
    if name in mapping:
        return mapping[name]
    digits = re.sub(r"\D", "", name)
    return int(digits) if digits else 1


def _water_name_to_id(name: str) -> int:
    """V1→1, V2→2; fallback: strip non-digits."""
    mapping = {"V1": 1, "V2": 2}
    if name in mapping:
        return mapping[name]
    digits = re.sub(r"\D", "", name)
    return int(digits) if digits else 1


async def handle_message(topic: str, payload: str):
    try:
        # ── Opta firmware (cabinetId in payload) ─────────────────────────────
        if OPTA_STATUS_RE.match(topic):
            await _handle_opta_status(payload)
        elif m := OPTA_SOCKET_RE.match(topic):
            await _handle_opta_socket(m.group(1), payload)
        elif m := OPTA_SOCKET_POWER_RE.match(topic):
            await _handle_opta_socket_power(m.group(1), payload)
        elif m := OPTA_WATER_RE.match(topic):
            await _handle_opta_water(m.group(1), payload)
        elif OPTA_DOOR_RE.match(topic):
            await _handle_opta_door(payload)
        elif OPTA_EVENTS_RE.match(topic):
            await _handle_opta_events(payload)
        elif OPTA_ACKS_RE.match(topic):
            await _handle_opta_acks(payload)
        # ── Marina cabinet firmware (real hardware) ──────────────────────────
        elif m := MARINA_SOCKET_RE.match(topic):
            await _handle_marina_socket(m.group(1), m.group(2), payload)
        elif m := MARINA_WATER_RE.match(topic):
            await _handle_marina_water(m.group(1), m.group(2), payload)
        elif m := MARINA_DOOR_RE.match(topic):
            await _handle_marina_door(m.group(1), payload)
        elif m := MARINA_STATUS_RE.match(topic):
            await _handle_marina_status(m.group(1), payload)
        elif m := MARINA_EVENTS_RE.match(topic):
            await _handle_marina_events(m.group(1), payload)
        elif m := MARINA_ACKS_RE.match(topic):
            await _handle_marina_acks(m.group(1), payload)
        # ── Legacy pedestal/... schema ───────────────────────────────────────
        elif m := SOCKET_STATUS_RE.match(topic):
            await _handle_socket_status(int(m.group(1)), int(m.group(2)), payload)
        elif m := SOCKET_POWER_RE.match(topic):
            await _handle_socket_power(int(m.group(1)), int(m.group(2)), payload)
        elif m := WATER_FLOW_RE.match(topic):
            await _handle_water_flow(int(m.group(1)), payload)
        elif m := HEARTBEAT_RE.match(topic):
            await _handle_heartbeat(int(m.group(1)), payload)
        elif m := SENSOR_TEMP_RE.match(topic):
            await _handle_temperature(int(m.group(1)), payload)
        elif m := SENSOR_MOIST_RE.match(topic):
            await _handle_moisture(int(m.group(1)), payload)
        elif m := DIAGNOSTICS_RE.match(topic):
            await _handle_diagnostics(int(m.group(1)), payload)
        elif m := SENSOR_REGISTER_RE.match(topic):
            await _handle_auto_register(int(m.group(1)), payload)
    except Exception as e:
        logger.error(f"Error handling MQTT message on {topic}: {e}")
        _hw_error("mqtt_handlers", f"Unhandled error on topic {topic}: {e}")


async def _handle_marina_socket(cabinet_id: str, socket_name: str, payload: str):
    """
    marina/cabinet/{cabinetId}/sockets/{socketName}/state
    Payload: {"id":"PWR-1","state":"idle"|"active","ts":...,"session":...}
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.warning("[Marina] Bad socket payload from cabinet %s socket %s: %s", cabinet_id, socket_name, e)
        return

    raw_state = data.get("state", "")
    # Map firmware states → legacy schema expected by _handle_socket_status
    status = "connected" if raw_state == "active" else "disconnected"
    socket_id = _socket_name_to_id(socket_name)

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
    finally:
        db.close()

    if pedestal_id is None:
        logger.warning("[Marina] Could not resolve cabinet '%s' to pedestal_id", cabinet_id)
        return

    logger.debug("[Marina] cabinet=%s socket=%s(%d) state=%s→%s", cabinet_id, socket_name, socket_id, raw_state, status)
    await _handle_socket_status(pedestal_id, socket_id, status)
    # Rich broadcast for Control Center UI
    await ws_manager.broadcast({
        "event": "opta_socket_status",
        "data": {
            "pedestal_id": pedestal_id,
            "socket_name": socket_name,
            "state": raw_state,
            "hw_status": data.get("hw_status", ""),
            "session": data.get("session"),
            "ts": data.get("ts"),
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


async def _handle_marina_water(cabinet_id: str, water_name: str, payload: str):
    """
    marina/cabinet/{cabinetId}/water/{waterName}/state
    Payload: {"id":"WTR-1","state":"idle","ts":...,"total_l":1.0,"session_l":0,"session":null}
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.warning("[Marina] Bad water payload from cabinet %s: %s", cabinet_id, e)
        return

    total_l = float(data.get("total_l", 0))
    session_l = float(data.get("session_l", 0))
    # Convert to legacy water format: lpm=session flow rate (session_l as proxy), total_liters
    lpm = session_l  # firmware doesn't send L/min, use session_l as-is
    legacy_payload = json.dumps({"lpm": lpm, "total_liters": total_l})

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
    finally:
        db.close()

    if pedestal_id is None:
        logger.warning("[Marina] Could not resolve cabinet '%s' to pedestal_id", cabinet_id)
        return

    logger.debug("[Marina] cabinet=%s water=%s total_l=%.3f session_l=%.3f", cabinet_id, water_name, total_l, session_l)
    await _handle_water_flow(pedestal_id, legacy_payload)
    # Rich broadcast for Control Center UI
    await ws_manager.broadcast({
        "event": "opta_water_status",
        "data": {
            "pedestal_id": pedestal_id,
            "valve_name": water_name,
            "state": data.get("state", "idle"),
            "hw_status": data.get("hw_status", ""),
            "total_l": total_l,
            "session_l": session_l,
            "ts": data.get("ts"),
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


async def _handle_marina_door(cabinet_id: str, payload: str):
    """
    marina/cabinet/{cabinetId}/door/state
    Payload: {"cabinetId":"...","door":"open"|"closed","ts":"..."}
    Broadcast door state for dashboard; no legacy mapping.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.warning("[Marina] Bad door payload from cabinet %s: %s", cabinet_id, e)
        return

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
    finally:
        db.close()

    door_state = data.get("door", "unknown")
    logger.info("[Marina] cabinet=%s door=%s", cabinet_id, door_state)

    await ws_manager.broadcast({
        "event": "marina_door",
        "data": {
            "pedestal_id": pedestal_id,
            "cabinet_id": cabinet_id,
            "door": door_state,
            "timestamp": data.get("ts", datetime.utcnow().isoformat()),
        },
    })

    if door_state == "open":
        _hw_warn(f"cabinet_{cabinet_id}", f"Cabinet door OPEN on {cabinet_id}")


async def _handle_marina_status(cabinet_id: str, payload: str):
    """
    marina/cabinet/{cabinetId}/status
    Payload: {"cabinetId":"...","seq":34,"uptime_ms":512397,"door":"closed"}
    Maps to heartbeat handler so the pedestal shows as connected.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.warning("[Marina] Bad status payload from cabinet %s: %s", cabinet_id, e)
        return

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
    finally:
        db.close()

    if pedestal_id is None:
        logger.warning("[Marina] Could not resolve cabinet '%s' to pedestal_id", cabinet_id)
        return

    # Build a legacy heartbeat payload
    legacy_payload = json.dumps({
        "online": True,
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_ms": data.get("uptime_ms", 0),
        "seq": data.get("seq", 0),
    })
    logger.debug("[Marina] cabinet=%s status seq=%s → heartbeat pedestal=%d", cabinet_id, data.get("seq"), pedestal_id)
    await _handle_heartbeat(pedestal_id, legacy_payload)
    # Also broadcast raw opta status details for Control Center UI
    await ws_manager.broadcast({
        "event": "opta_status",
        "data": {
            "pedestal_id": pedestal_id,
            "cabinet_id": cabinet_id,
            "seq": data.get("seq", 0),
            "uptime_ms": data.get("uptime_ms", 0),
            "door": data.get("door"),
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


async def _handle_marina_events(cabinet_id: str, payload: str):
    """
    marina/cabinet/{cabinetId}/events
    Generic event log from firmware — broadcast to dashboard for visibility.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = {"raw": payload}

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
    finally:
        db.close()

    logger.info("[Marina] Event from cabinet %s: %s", cabinet_id, payload[:200])
    await ws_manager.broadcast({
        "event": "marina_event",
        "data": {
            "pedestal_id": pedestal_id,
            "cabinet_id": cabinet_id,
            "payload": data,
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


async def _handle_marina_acks(cabinet_id: str, payload: str):
    """
    marina/cabinet/{cabinetId}/acks
    Command acknowledgements from firmware — log and broadcast.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = {"raw": payload}

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
    finally:
        db.close()
    logger.debug("[Marina] Ack from cabinet %s: %s", cabinet_id, payload[:200])
    await ws_manager.broadcast({
        "event": "marina_ack",
        "data": {
            "pedestal_id": pedestal_id,
            "cabinet_id": cabinet_id,
            "payload": data,
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


# ── Opta firmware handlers ────────────────────────────────────────────────────
# The opta schema sends cabinetId inside the JSON payload instead of the topic path.
# We extract it and delegate to the equivalent _handle_marina_* function.

def _opta_cabinet_id(payload: str, topic_hint: str) -> str | None:
    """Parse cabinetId from opta JSON payload.

    Checks (in order):
      1. Top-level ``cabinetId`` field (opta/status, opta/door/status)
      2. Nested ``device.cabinetId`` (opta/events)
      3. Module-level ``_opta_cached_cabinet_id`` (populated by opta/status heartbeats)

    Returns None and logs a warning only if all three fail.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.warning("[Opta] Cannot parse payload on %s: %s", topic_hint, e)
        return _opta_cached_cabinet_id  # best-effort fallback

    cid = data.get("cabinetId", "") or ""
    if not cid:
        device = data.get("device")
        if isinstance(device, dict):
            cid = device.get("cabinetId", "") or ""
    if not cid:
        cid = _opta_cached_cabinet_id
    if not cid:
        logger.warning("[Opta] No cabinetId in payload on %s and no cached value", topic_hint)
        return None
    return cid


async def _handle_opta_status(payload: str):
    """opta/status — cabinet heartbeat (same as marina status but cabinetId in payload)."""
    global _opta_cached_cabinet_id
    cabinet_id = _opta_cabinet_id(payload, "opta/status")
    if cabinet_id:
        _opta_cached_cabinet_id = cabinet_id
        await _handle_marina_status(cabinet_id, payload)


async def _handle_opta_socket(socket_name: str, payload: str):
    """
    opta/sockets/{socketName}/status
    Payload: {"cabinetId":"...", "id":"Q1", "state":"idle"|"active", "ts":...}
    """
    cabinet_id = _opta_cabinet_id(payload, f"opta/sockets/{socket_name}/status")
    if cabinet_id:
        await _handle_marina_socket(cabinet_id, socket_name, payload)


async def _handle_opta_socket_power(socket_name: str, payload: str):
    """
    opta/sockets/{socketName}/power
    Payload: {"id":"Q1", "watts":N, "kwh_total":N, "ts":...}
    cabinetId may be absent — resolved via _opta_cabinet_id fallback.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.warning("[Opta] Bad power payload on %s: %s", socket_name, e)
        return

    cabinet_id = _opta_cabinet_id(payload, f"opta/sockets/{socket_name}/power")
    if not cabinet_id:
        return

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
    finally:
        db.close()

    if pedestal_id is None:
        logger.warning("[Opta] Could not resolve cabinet '%s' to pedestal_id", cabinet_id)
        return

    socket_id = _socket_name_to_id(socket_name)
    # Reuse legacy handler with just the fields it needs
    power_payload = json.dumps({
        "watts": data.get("watts", 0),
        "kwh_total": data.get("kwh_total", 0),
    })
    logger.debug("[Opta] cabinet=%s socket=%s(%d) power", cabinet_id, socket_name, socket_id)
    await _handle_socket_power(pedestal_id, socket_id, power_payload)


async def _handle_opta_water(water_name: str, payload: str):
    """
    opta/water/{waterName}/status
    Payload: {"id":"V1", "state":"idle", "ts":..., "total_l":N, "session_l":N}
    cabinetId may be absent — resolved via _opta_cabinet_id fallback.
    """
    cabinet_id = _opta_cabinet_id(payload, f"opta/water/{water_name}/status")
    if not cabinet_id:
        return

    await _handle_marina_water(cabinet_id, water_name, payload)


async def _handle_opta_door(payload: str):
    """
    opta/door/status
    Payload: {"cabinetId":"...", "door":"open"|"closed", "ts":"..."}
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.warning("[Opta] Bad door payload: %s", e)
        return

    cabinet_id = data.get("cabinetId", "")
    if not cabinet_id:
        logger.warning("[Opta] Missing cabinetId in door payload: %s", payload[:200])
        return

    await _handle_marina_door(cabinet_id, payload)


async def _handle_opta_events(payload: str):
    """
    opta/events
    Payload: {"cabinetId":"...", ...}
    """
    cabinet_id = _opta_cabinet_id(payload, "opta/events")
    if cabinet_id:
        await _handle_marina_events(cabinet_id, payload)


async def _handle_opta_acks(payload: str):
    """
    opta/acks
    Payload: {"cabinetId":"...", "cmd":"...", "status":"ok"|"err", ...}
    """
    cabinet_id = _opta_cabinet_id(payload, "opta/acks")
    if cabinet_id:
        await _handle_marina_acks(cabinet_id, payload)


async def _handle_socket_status(pedestal_id: int, socket_id: int, payload: str):
    status = payload.strip().strip('"')
    db = SessionLocal()
    try:
        # Persist physical connection state so the session API can validate it
        if status in ("connected", "disconnected"):
            from ..models.pedestal_config import SocketState
            _ensure_pedestal(db, pedestal_id)
            state = db.query(SocketState).filter(
                SocketState.pedestal_id == pedestal_id,
                SocketState.socket_id == socket_id,
            ).first()
            now = datetime.utcnow()
            if state:
                state.connected = (status == "connected")
                state.updated_at = now
            else:
                state = SocketState(
                    pedestal_id=pedestal_id,
                    socket_id=socket_id,
                    connected=(status == "connected"),
                )
                db.add(state)
            # Update operator_status alongside physical state
            if status == "connected":
                state.operator_status = "pending"
                state.operator_status_at = now
            elif status == "disconnected":
                state.operator_status = None
                state.operator_status_at = None
            db.commit()

        if status == "connected":
            from .audit_service import log_transition
            log_transition(db, None, pedestal_id, socket_id, "socket_connected", "system")
            await ws_manager.broadcast({
                "event": "socket_pending",
                "data": {"pedestal_id": pedestal_id, "socket_id": socket_id},
            })

        if status == "disconnected":
            session = session_service.get_active_for_socket(db, pedestal_id, socket_id)
            if session and session.status == "active":
                session_service.complete(db, session)
                await ws_manager.broadcast({
                    "event": "session_completed",
                    "data": {
                        "session_id": session.id,
                        "pedestal_id": pedestal_id,
                        "socket_id": socket_id,
                        "energy_kwh": session.energy_kwh,
                        "customer_id": session.customer_id,
                    },
                })
                if session.customer_id:
                    from ..auth.user_database import UserSessionLocal
                    from ..services.invoice_service import create_invoice_for_session
                    user_db = UserSessionLocal()
                    try:
                        await create_invoice_for_session(db, user_db, session)
                    except Exception as e:
                        _hw_error(
                            f"pedestal_{pedestal_id}",
                            f"Invoice creation failed for session {session.id} on disconnect: {e}",
                        )
                    finally:
                        user_db.close()
        elif status not in ("connected", "disconnected"):
            _hw_warn(
                f"pedestal_{pedestal_id}",
                f"Unknown socket status '{status}' on socket {socket_id}",
            )
    finally:
        db.close()


async def _handle_socket_power(pedestal_id: int, socket_id: int, payload: str):
    try:
        data = json.loads(payload)
        watts = float(data["watts"])
        kwh_total = float(data["kwh_total"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Invalid power payload: {payload} — {e}")
        _hw_warn(
            f"pedestal_{pedestal_id}",
            f"Invalid power payload on socket {socket_id}: {e}",
            details=payload[:200],
        )
        return

    db = SessionLocal()
    try:
        session = session_service.get_active_for_socket(db, pedestal_id, socket_id)
        session_id = session.id if session and session.status == "active" else None
        customer_id = session.customer_id if session else None

        session_service.add_reading(db, session_id, pedestal_id, socket_id, "power_watts", watts, "W")
        session_service.add_reading(db, session_id, pedestal_id, socket_id, "kwh_total", kwh_total, "kWh")

        await ws_manager.broadcast({
            "event": "power_reading",
            "data": {
                "pedestal_id": pedestal_id,
                "socket_id": socket_id,
                "session_id": session_id,
                "watts": watts,
                "kwh_total": kwh_total,
                "timestamp": datetime.utcnow().isoformat(),
                "customer_id": customer_id,
            },
        })
    finally:
        db.close()


async def _handle_water_flow(pedestal_id: int, payload: str):
    try:
        data = json.loads(payload)
        lpm = float(data["lpm"])
        total_liters = float(data["total_liters"])
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Invalid water payload: {payload} — {e}")
        _hw_warn(
            f"pedestal_{pedestal_id}",
            f"Invalid water flow payload: {e}",
            details=payload[:200],
        )
        return

    db = SessionLocal()
    try:
        session = session_service.get_active_for_socket(db, pedestal_id, None)
        session_id = session.id if session and session.status == "active" else None
        customer_id = session.customer_id if session else None

        session_service.add_reading(db, session_id, pedestal_id, None, "water_lpm", lpm, "L/min")
        session_service.add_reading(db, session_id, pedestal_id, None, "total_liters", total_liters, "L")

        await ws_manager.broadcast({
            "event": "water_reading",
            "data": {
                "pedestal_id": pedestal_id,
                "session_id": session_id,
                "lpm": lpm,
                "total_liters": total_liters,
                "timestamp": datetime.utcnow().isoformat(),
                "customer_id": customer_id,
            },
        })
    finally:
        db.close()


async def _handle_heartbeat(pedestal_id: int, payload: str):
    try:
        data = json.loads(payload)
        now = datetime.utcnow()
        last_heartbeat[pedestal_id] = now  # update for comm-loss watchdog

        # Persist heartbeat timestamp + mark OPTA connected in DB
        try:
            from ..models.pedestal_config import PedestalConfig
            db = SessionLocal()
            try:
                _ensure_pedestal(db, pedestal_id)
                cfg = db.query(PedestalConfig).filter(
                    PedestalConfig.pedestal_id == pedestal_id
                ).first()
                if cfg is None:
                    cfg = PedestalConfig(
                        pedestal_id=pedestal_id,
                        opta_connected=1,
                        last_heartbeat=now,
                        updated_at=now,
                    )
                    db.add(cfg)
                else:
                    cfg.opta_connected = 1
                    cfg.last_heartbeat = now
                    cfg.updated_at = now
                db.commit()
            finally:
                db.close()
        except Exception as db_err:
            logger.warning(f"Heartbeat DB update failed for pedestal {pedestal_id}: {db_err}")

        await ws_manager.broadcast({
            "event": "heartbeat",
            "data": {
                "pedestal_id": pedestal_id,
                "online": data.get("online", True),
                "timestamp": data.get("timestamp", now.isoformat()),
            },
        })
        await ws_manager.broadcast({
            "event": "pedestal_health_updated",
            "data": {
                "pedestal_id": pedestal_id,
                "opta_connected": True,
                "last_heartbeat": now.isoformat(),
            },
        })
    except Exception as e:
        logger.warning(f"Invalid heartbeat payload: {e}")
        _hw_warn(f"pedestal_{pedestal_id}", f"Invalid heartbeat payload: {e}", details=payload[:200])


async def _handle_auto_register(pedestal_id: int, payload: str):
    """Auto-upsert sensor into pedestal_sensors when device publishes pedestal/{id}/register."""
    try:
        data = json.loads(payload)
        sensor_name = data.get("sensor_name", "").strip()
        sensor_type = data.get("sensor_type", "").strip()
        mqtt_topic  = data.get("mqtt_topic", "").strip()
        unit        = data.get("unit", "")

        if not sensor_name or not mqtt_topic:
            logger.warning(f"Auto-register: missing sensor_name or mqtt_topic from pedestal {pedestal_id}")
            return

        from ..models.pedestal_config import PedestalSensor
        db = SessionLocal()
        try:
            _ensure_pedestal(db, pedestal_id)
            existing = db.query(PedestalSensor).filter(
                PedestalSensor.pedestal_id == pedestal_id,
                PedestalSensor.mqtt_topic == mqtt_topic,
            ).first()
            if existing:
                existing.sensor_name = sensor_name
                existing.sensor_type = sensor_type
                existing.unit = unit
                existing.source = "auto_mqtt"
            else:
                db.add(PedestalSensor(
                    pedestal_id=pedestal_id,
                    sensor_name=sensor_name,
                    sensor_type=sensor_type,
                    mqtt_topic=mqtt_topic,
                    unit=unit,
                    source="auto_mqtt",
                    created_at=datetime.utcnow(),
                ))
            db.commit()
            logger.info(f"Auto-registered sensor '{sensor_name}' for pedestal {pedestal_id}")
        finally:
            db.close()
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Auto-register parse error on pedestal {pedestal_id}: {e}")


async def _handle_temperature(pedestal_id: int, payload: str):
    try:
        data = json.loads(payload)
        value = float(data["value"])
        alarm = value > 50.0

        db = SessionLocal()
        try:
            session_service.add_reading(db, None, pedestal_id, None, "temperature", value, "°C")
        finally:
            db.close()

        if alarm:
            _hw_warn(
                f"pedestal_{pedestal_id}",
                f"Temperature ALARM: {round(value, 1)}°C (threshold 50°C)",
            )
            try:
                from .alarm_service import trigger_alarm
                trigger_alarm(
                    alarm_type="temperature",
                    source="sensor_auto",
                    message=f"Pedestal {pedestal_id}: temperature {round(value, 1)}°C exceeds 50°C threshold",
                    pedestal_id=pedestal_id,
                    deduplicate=True,
                )
            except Exception:
                pass

        await ws_manager.broadcast({
            "event": "temperature_reading",
            "data": {
                "pedestal_id": pedestal_id,
                "value": round(value, 1),
                "alarm": alarm,
                "timestamp": datetime.utcnow().isoformat(),
            },
        })
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Invalid temperature payload: {payload} — {e}")
        _hw_warn(f"pedestal_{pedestal_id}", f"Invalid temperature payload: {e}", details=payload[:200])


async def _handle_moisture(pedestal_id: int, payload: str):
    try:
        data = json.loads(payload)
        value = float(data["value"])
        alarm = value > 90.0

        db = SessionLocal()
        try:
            session_service.add_reading(db, None, pedestal_id, None, "moisture", value, "%")
        finally:
            db.close()

        if alarm:
            _hw_warn(
                f"pedestal_{pedestal_id}",
                f"Moisture ALARM: {round(value, 1)}% (threshold 90%)",
            )
            try:
                from .alarm_service import trigger_alarm
                trigger_alarm(
                    alarm_type="moisture",
                    source="sensor_auto",
                    message=f"Pedestal {pedestal_id}: moisture {round(value, 1)}% exceeds 90% threshold",
                    pedestal_id=pedestal_id,
                    deduplicate=True,
                )
            except Exception:
                pass

        await ws_manager.broadcast({
            "event": "moisture_reading",
            "data": {
                "pedestal_id": pedestal_id,
                "value": round(value, 1),
                "alarm": alarm,
                "timestamp": datetime.utcnow().isoformat(),
            },
        })
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning(f"Invalid moisture payload: {payload} — {e}")
        _hw_warn(f"pedestal_{pedestal_id}", f"Invalid moisture payload: {e}", details=payload[:200])


async def _handle_diagnostics(pedestal_id: int, payload: str):
    try:
        from ..services.diagnostics_manager import diagnostics_manager
        data = json.loads(payload)
        diagnostics_manager.complete_request(pedestal_id, data)

        # Log any failed sensors as HW errors and raise operational alarm
        failed = [k for k, v in data.items() if v != "ok"]
        if failed:
            _hw_error(
                f"pedestal_{pedestal_id}",
                f"Diagnostics: {len(failed)} sensor(s) failed — {', '.join(failed)}",
                details=json.dumps(data),
            )
            try:
                from .alarm_service import trigger_alarm
                trigger_alarm(
                    alarm_type="operational_failure",
                    source="sensor_auto",
                    message=f"Pedestal {pedestal_id}: diagnostics failure — {', '.join(failed)}",
                    pedestal_id=pedestal_id,
                    details=json.dumps(data),
                    deduplicate=True,
                )
            except Exception:
                pass

        await ws_manager.broadcast({
            "event": "diagnostics_result",
            "data": {"pedestal_id": pedestal_id, "results": data},
        })
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Invalid diagnostics response: {payload} — {e}")
        _hw_error(f"pedestal_{pedestal_id}", f"Diagnostics response parse error: {e}", details=payload[:200])


async def auto_reject_stale_socket_pending(
    db,
    cutoff: datetime,
    mqtt_publish,
    ws_broadcast,
    timeout_seconds: int,
) -> list:
    """
    Find SocketStates with operator_status='pending' older than cutoff and auto-reject them.
    Called by the background watchdog in main.py; also directly callable from tests.
    Returns list of rejected SocketState rows.
    """
    from ..models.pedestal_config import SocketState
    from .audit_service import log_transition

    stale = (
        db.query(SocketState)
        .filter(
            SocketState.operator_status == "pending",
            SocketState.operator_status_at < cutoff,
        )
        .all()
    )
    rejected = []
    for s in stale:
        try:
            s.operator_status = "rejected"
            s.operator_status_at = datetime.utcnow()
            db.commit()

            reason = f"Auto-rejected: no response within {timeout_seconds}s"

            # Publish to marina + opta topics if this pedestal is a marina cabinet
            from ..models.pedestal_config import PedestalConfig as _PC
            cfg = db.query(_PC).filter(_PC.pedestal_id == s.pedestal_id).first()
            cabinet_id = getattr(cfg, "opta_client_id", None) if cfg else None
            if cabinet_id:
                mqtt_publish(
                    f"marina/cabinet/{cabinet_id}/cmd/socket/E{s.socket_id}",
                    json.dumps({"cmd": "disable"}),
                )
                mqtt_publish(
                    f"opta/cmd/socket/Q{s.socket_id}",
                    json.dumps({"cabinetId": cabinet_id, "cmd": "disable"}),
                )
            else:
                mqtt_publish(
                    f"pedestal/{s.pedestal_id}/socket/{s.socket_id}/command",
                    json.dumps({"cmd": "rejected", "reason": reason}),
                )
            log_transition(db, None, s.pedestal_id, s.socket_id, "auto_rejected", "system", reason=reason)
            await ws_broadcast({
                "event": "socket_rejected",
                "data": {"pedestal_id": s.pedestal_id, "socket_id": s.socket_id},
            })
            rejected.append(s)
        except Exception as exc:
            logger.warning(
                "Auto-reject failed for pedestal %s socket %s: %s",
                s.pedestal_id, s.socket_id, exc,
            )
    return rejected
