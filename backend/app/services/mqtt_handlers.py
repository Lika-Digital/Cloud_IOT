import asyncio
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

# ── Auto-activation precondition inputs (v3.5) ───────────────────────────────
# Module-level dicts are fine for process-local state — the backend is a
# single uvicorn worker and all callers run inside the same event loop.
# A DB column was explicitly rejected for these two (see implementation_status
# v3.5 design decisions).
#
# Key: (pedestal_id, socket_id); Value: most-recent UTC datetime we saw the
# firmware report `state="fault"` for that outlet. Cleared when state goes
# back to anything non-fault.
socket_fault_state: dict[tuple[int, int], datetime] = {}
#
# Key: pedestal_id; Value: UTC datetime when the diagnostics router last
# published `opta/cmd/diagnostic` for this pedestal. Auto-activate refuses
# to fire within 60 s of that timestamp.
last_diagnostic_at: dict[int, datetime] = {}

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
OPTA_DIAGNOSTIC_RE   = re.compile(r"opta/diagnostic")


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

    v3.7 — on first creation: prettify the display name, stamp first_seen_at and
    status="online", and schedule a `pedestal_registered is_new=True` broadcast
    + per-socket QR PNG generation so the operator sees the new cabinet in real
    time and printable QR labels are ready immediately.
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

    # Prettify the display name on first creation only — operators can still
    # rename later via the settings page and the new name sticks.
    pretty_name = cabinet_id.replace("_", " ")
    now = datetime.utcnow()

    db.add(Pedestal(
        id=new_id,
        name=pretty_name,
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
        first_seen_at=now,
        status="online",
    )
    db.add(new_cfg)
    db.commit()
    logger.info("Auto-created Pedestal %d for marina cabinet '%s'", new_id, cabinet_id)

    # Fire-and-forget: announce the new pedestal + pre-generate QR PNGs for
    # the four electricity sockets so the dashboard "QR Codes" section can
    # load them instantly. Wrapped so a QR-gen failure never crashes MQTT.
    try:
        asyncio.create_task(_announce_new_pedestal(new_id, cabinet_id, pretty_name))
    except Exception as e:
        logger.warning("[Discovery] could not schedule announce for %s: %s", cabinet_id, e)

    return new_id


# ── Auto-discovery broadcasts (v3.7) ─────────────────────────────────────────
#
# `pedestal_registered` fires once on first contact with `is_new=True` and
# again on every subsequent opta/status heartbeat with `is_new=False`,
# throttled to one event per pedestal per 60 seconds so reconnect storms
# cannot drown the operator dashboard.

_PEDESTAL_REGISTERED_THROTTLE_S = 60.0
_pedestal_registered_last_at: dict[int, datetime] = {}


async def _announce_new_pedestal(pedestal_id: int, cabinet_id: str, name: str) -> None:
    """Broadcast `pedestal_registered is_new=True` + generate printable QR PNGs."""
    _pedestal_registered_last_at[pedestal_id] = datetime.utcnow()
    try:
        from .qr_service import generate_all_qr_for_pedestal
        generate_all_qr_for_pedestal(cabinet_id, ["Q1", "Q2", "Q3", "Q4"])
    except Exception as e:
        logger.warning("[Discovery] QR pre-generation failed for %s: %s", cabinet_id, e)
    await ws_manager.broadcast({
        "event": "pedestal_registered",
        "data": {
            "pedestal_id": pedestal_id,
            "cabinet_id": cabinet_id,
            "name": name,
            "is_new": True,
            "socket_ids": ["Q1", "Q2", "Q3", "Q4"],
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


async def _announce_pedestal_heartbeat(pedestal_id: int, cabinet_id: str, name: str) -> None:
    """Throttled `pedestal_registered is_new=False`. Swallows the heartbeat if
    we broadcast within the last 60 seconds."""
    last = _pedestal_registered_last_at.get(pedestal_id)
    now = datetime.utcnow()
    if last and (now - last).total_seconds() < _PEDESTAL_REGISTERED_THROTTLE_S:
        return
    _pedestal_registered_last_at[pedestal_id] = now
    await ws_manager.broadcast({
        "event": "pedestal_registered",
        "data": {
            "pedestal_id": pedestal_id,
            "cabinet_id": cabinet_id,
            "name": name,
            "is_new": False,
            "socket_ids": ["Q1", "Q2", "Q3", "Q4"],
            "timestamp": now.isoformat(),
        },
    })


def _auto_discover_socket_config(db, pedestal_id: int, socket_id: int) -> bool:
    """Idempotently create a SocketConfig row for (pedestal_id, socket_id).
    Returns True if a new row was inserted, False if one already existed.
    Safe for MQTT handler context — catches and logs every exception."""
    try:
        from ..models.socket_config import SocketConfig
        row = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == pedestal_id,
            SocketConfig.socket_id == socket_id,
        ).first()
        if row:
            return False
        db.add(SocketConfig(
            pedestal_id=pedestal_id,
            socket_id=socket_id,
            auto_activate=False,
        ))
        db.commit()
        logger.info("[Discovery] SocketConfig created pedestal=%d socket=%d", pedestal_id, socket_id)
        return True
    except Exception as e:
        logger.warning("[Discovery] socket config create failed (pedestal=%d socket=%d): %s",
                       pedestal_id, socket_id, e)
        try:
            db.rollback()
        except Exception:
            pass
        return False


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
        elif OPTA_DIAGNOSTIC_RE.match(topic):
            await _handle_opta_diagnostic(payload)
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
    socket_id = _socket_name_to_id(socket_name)

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
        if pedestal_id is None:
            logger.warning("[Marina] Could not resolve cabinet '%s' to pedestal_id", cabinet_id)
            return

        # Update SocketState connected flag (informational) without triggering
        # the legacy pending approval flow. Sessions are managed by OutletActivated
        # events and Control Center commands, not by socket status changes.
        from ..models.pedestal_config import SocketState
        _ensure_pedestal(db, pedestal_id)
        now = datetime.utcnow()
        is_connected = raw_state in ("active", "idle")  # anything not fault/blocked
        state_row = db.query(SocketState).filter(
            SocketState.pedestal_id == pedestal_id,
            SocketState.socket_id == socket_id,
        ).first()
        if state_row:
            state_row.connected = is_connected
            state_row.updated_at = now
        else:
            state_row = SocketState(pedestal_id=pedestal_id, socket_id=socket_id, connected=is_connected)
            db.add(state_row)
        db.commit()

        # v3.7 — auto-discovery side-effect: ensure a SocketConfig exists for
        # this socket and render its printable QR PNG on first sight. Both
        # steps are idempotent; both catch+log all exceptions so MQTT flow
        # continues even if the filesystem or DB hiccups.
        newly_created = _auto_discover_socket_config(db, pedestal_id, socket_id)
        if newly_created:
            try:
                from .qr_service import generate_socket_qr
                generate_socket_qr(cabinet_id, socket_name)
            except Exception as e:
                logger.warning("[Discovery] QR gen for socket %s on %s failed: %s",
                               socket_name, cabinet_id, e)
    finally:
        db.close()

    # Track fault state for the auto-activate precondition (v3.5). A pedestal
    # with ANY socket reported as `fault` is ineligible until the firmware
    # clears it.
    fault_key = (pedestal_id, socket_id)
    if raw_state == "fault":
        socket_fault_state[fault_key] = datetime.utcnow()
    else:
        socket_fault_state.pop(fault_key, None)

    logger.debug("[Marina] cabinet=%s socket=%s(%d) state=%s", cabinet_id, socket_name, socket_id, raw_state)
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

    door_state = data.get("door", "unknown")
    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
        # Persist door state so the auto-activate precondition check has a
        # source of truth independent of live WebSocket subscribers.
        if pedestal_id is not None and door_state in ("open", "closed"):
            from ..models.pedestal_config import PedestalConfig
            cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pedestal_id).first()
            if cfg and getattr(cfg, "door_state", None) != door_state:
                cfg.door_state = door_state
                db.commit()
    finally:
        db.close()

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
    Processes structured firmware events and broadcasts to dashboard.

    Handled eventTypes:
      OutletActivated  — create + activate a DB session
      TelemetryUpdate  — store power/water sensor readings
      SessionEnded     — complete the DB session with final totals
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = {"raw": payload}

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
        if pedestal_id is None:
            logger.warning("[Marina] Could not resolve cabinet '%s' for event", cabinet_id)
            return

        event_type = data.get("eventType", "")
        device = data.get("device", {})
        outlet_id = device.get("outletId", "")  # Q1-Q4 or V1-V2
        resource = device.get("resource", "")    # POWER or WATER

        if event_type == "OutletActivated":
            await _handle_event_outlet_activated(db, pedestal_id, outlet_id, resource, data)
        elif event_type == "TelemetryUpdate":
            await _handle_event_telemetry_update(db, pedestal_id, outlet_id, resource, data)
        elif event_type == "SessionEnded":
            await _handle_event_session_ended(db, pedestal_id, outlet_id, resource, data)
        elif event_type == "UserPluggedIn":
            await _handle_event_user_plugged_in(db, pedestal_id, outlet_id, resource, data)
        elif event_type == "UserPluggedOut":
            await _handle_event_user_plugged_out(db, pedestal_id, outlet_id, resource, data)
        elif event_type == "AlarmRaised":
            alarm = data.get("alarm", {})
            code = alarm.get("code", "UNKNOWN")
            severity = alarm.get("severity", "MEDIUM")
            _hw_error(
                f"pedestal_{pedestal_id}",
                f"Opta alarm: {code} (severity={severity})",
                details=json.dumps(data),
            )
            logger.warning("[Event] AlarmRaised pedestal=%d code=%s severity=%s", pedestal_id, code, severity)
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


async def _broadcast_socket_state(pedestal_id: int, socket_id: int, new_state: str, resource: str = "POWER"):
    """Single-point emitter for socket_state_changed. Keeps the WebSocket event
    shape consistent across every call site (UserPluggedIn/Out, OutletActivated,
    SessionEnded). `new_state` is one of idle|pending|active|fault.

    v3.6 — also fans out to any mobile client subscribed to the currently
    active session for this (pedestal, socket) pair so its screen refreshes
    without a global reconnect.
    """
    # Look up an active session so we can target the mobile subscriber.
    db = SessionLocal()
    try:
        from ..models.session import Session as _S
        active = (
            db.query(_S)
            .filter(_S.pedestal_id == pedestal_id,
                    _S.socket_id == socket_id,
                    _S.type == "electricity",
                    _S.status == "active")
            .first()
        )
        session_id_for_subs = active.id if active else None
    finally:
        db.close()

    if session_id_for_subs is not None:
        await ws_manager.broadcast_to_session(session_id_for_subs, {
            "event": "socket_state_changed",
            "data": {
                "pedestal_id": pedestal_id,
                "socket_id": socket_id,
                "session_id": session_id_for_subs,
                "state": new_state,
                "resource": resource,
                "timestamp": datetime.utcnow().isoformat(),
            },
        })

    await ws_manager.broadcast({
        "event": "socket_state_changed",
        "data": {
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "state": new_state,
            "resource": resource,
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


def _set_socket_connected(db, pedestal_id: int, socket_id: int, connected: bool) -> None:
    """Upsert SocketState.connected. Caller is responsible for committing."""
    from ..models.pedestal_config import SocketState
    now = datetime.utcnow()
    state = db.query(SocketState).filter(
        SocketState.pedestal_id == pedestal_id,
        SocketState.socket_id == socket_id,
    ).first()
    if state:
        state.connected = connected
        state.updated_at = now
    else:
        state = SocketState(
            pedestal_id=pedestal_id,
            socket_id=socket_id,
            connected=connected,
        )
        db.add(state)


async def _handle_event_user_plugged_in(db, pedestal_id: int, outlet_id: str, resource: str, data: dict):
    """UserPluggedIn — marks socket as physically connected and moves the
    computed socket state to `pending` when no session is running. A session
    already in flight keeps `active` — plug re-assertions during a session
    must not flip the operator-visible state.

    If the operator has enabled `SocketConfig.auto_activate` for this socket
    we additionally kick off `_maybe_auto_activate` — a fire-and-forget task
    that runs the 5 preconditions, waits 2 s, re-checks the socket state,
    and publishes the activate command if everything still looks right.
    """
    is_water = resource == "WATER"
    socket_id = _water_name_to_id(outlet_id) if is_water else _socket_name_to_id(outlet_id)

    _ensure_pedestal(db, pedestal_id)
    _set_socket_connected(db, pedestal_id, socket_id, True)
    db.commit()

    session_type = "water" if is_water else "electricity"
    active = session_service.get_active_for_socket(db, pedestal_id, socket_id, session_type=session_type)
    computed = "active" if (active and active.status == "active") else "pending"

    berth_id = data.get("device", {}).get("berthId", "")
    logger.info("[Event] UserPluggedIn %s (berth=%s, socket=%d) — state=%s", outlet_id, berth_id, socket_id, computed)

    # Back-compat event (consumed by the pendingSockets store).
    await ws_manager.broadcast({
        "event": "user_plugged_in",
        "data": {
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "outlet_id": outlet_id,
            "berth_id": berth_id,
            "resource": resource,
        },
    })
    await _broadcast_socket_state(pedestal_id, socket_id, computed, resource=resource)

    # Auto-activation is electricity-only (spec v3.5). We always invoke
    # `_maybe_auto_activate` when the operator has enabled it, even when the
    # socket is already in an active session — the precondition check surfaces
    # the "socket already active" skip reason in the broadcast + log so the
    # operator sees an audit trail instead of silence.
    if not is_water:
        from ..models.socket_config import SocketConfig
        cfg = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == pedestal_id,
            SocketConfig.socket_id == socket_id,
        ).first()
        if cfg and cfg.auto_activate:
            asyncio.create_task(_maybe_auto_activate(pedestal_id, socket_id, outlet_id))


# ── Auto-activation implementation (v3.5) ────────────────────────────────────

_HEARTBEAT_MAX_AGE_S = 300
_DIAGNOSTIC_LOCKOUT_S = 60
_AUTO_ACTIVATE_DELAY_S = 2.0


def _log_auto_activation(pedestal_id: int, socket_id: int, result: str,
                         reason: str | None = None, session_id: int | None = None) -> None:
    """Append a row to auto_activation_log. Uses its own Session so the caller
    does not have to manage DB scope across the 2-second sleep window."""
    from ..models.auto_activation_log import AutoActivationLog
    db = SessionLocal()
    try:
        db.add(AutoActivationLog(
            pedestal_id=pedestal_id,
            socket_id=socket_id,
            timestamp=datetime.utcnow(),
            result=result,
            reason=reason,
            session_id=session_id,
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("Failed to record auto_activation_log row: %s", e)
    finally:
        db.close()


async def _broadcast_auto_activate_skipped(pedestal_id: int, socket_id: int, reason: str) -> None:
    await ws_manager.broadcast({
        "event": "socket_auto_activate_skipped",
        "data": {
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


def _auto_activate_precondition_check(db, pedestal_id: int, socket_id: int) -> str | None:
    """Return None if all checks pass, otherwise the skip reason string.

    Check order matches the spec so the reason the operator sees is the
    first failure, not an arbitrary one.
    """
    from ..models.pedestal_config import PedestalConfig
    from ..models.session import Session as SessionModel

    # 1. Door closed (unknown ≡ open per design decision).
    cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pedestal_id).first()
    door = getattr(cfg, "door_state", "unknown") if cfg else "unknown"
    if door != "closed":
        if door == "unknown":
            return "door state unknown"
        return "door open"

    # 2. No active faults anywhere on this pedestal.
    for (pid, _sid), _ts in socket_fault_state.items():
        if pid == pedestal_id:
            return "active fault on pedestal"

    # 3. Heartbeat recent.
    last = last_heartbeat.get(pedestal_id)
    if last is None or (datetime.utcnow() - last).total_seconds() > _HEARTBEAT_MAX_AGE_S:
        return "pedestal heartbeat timeout"

    # 4. Socket not already active.
    existing = db.query(SessionModel).filter(
        SessionModel.pedestal_id == pedestal_id,
        SessionModel.socket_id == socket_id,
        SessionModel.type == "electricity",
        SessionModel.status == "active",
    ).first()
    if existing:
        return "socket already active"

    # 5. No diagnostic running.
    last_diag = last_diagnostic_at.get(pedestal_id)
    if last_diag and (datetime.utcnow() - last_diag).total_seconds() < _DIAGNOSTIC_LOCKOUT_S:
        return "diagnostic in progress"

    return None


async def _maybe_auto_activate(pedestal_id: int, socket_id: int, outlet_id: str) -> None:
    """Fire-and-forget coroutine kicked off by _handle_event_user_plugged_in
    when SocketConfig.auto_activate is True.

    Runs the 5 precondition checks, waits 2 seconds (firmware stabilisation
    window per spec), re-checks the socket is still `pending`, then publishes
    the activate command. Every outcome is persisted to auto_activation_log.
    """
    from ..models.pedestal_config import PedestalConfig, SocketState
    # Precondition pass 1 — fail fast before the sleep so the operator gets
    # a skip reason without waiting 2 seconds.
    db = SessionLocal()
    try:
        reason = _auto_activate_precondition_check(db, pedestal_id, socket_id)
    finally:
        db.close()

    if reason:
        logger.info("[AutoActivate] pedestal=%d socket=%d SKIPPED (pre-sleep): %s",
                    pedestal_id, socket_id, reason)
        _log_auto_activation(pedestal_id, socket_id, "skipped", reason=reason)
        await _broadcast_auto_activate_skipped(pedestal_id, socket_id, reason)
        return

    # 2-second firmware stabilisation delay.
    await asyncio.sleep(_AUTO_ACTIVATE_DELAY_S)

    # Re-check everything after the sleep. During those 2 s the operator
    # could have manually activated, the plug could have been yanked, the
    # door could have opened, etc.
    db = SessionLocal()
    try:
        # Abort if the socket is no longer connected (plug yanked) or is
        # already active (operator beat us to it / race with OutletActivated).
        sock_state = db.query(SocketState).filter(
            SocketState.pedestal_id == pedestal_id,
            SocketState.socket_id == socket_id,
        ).first()
        if not sock_state or not sock_state.connected:
            logger.info("[AutoActivate] pedestal=%d socket=%d SKIPPED: plug no longer inserted", pedestal_id, socket_id)
            _log_auto_activation(pedestal_id, socket_id, "skipped", reason="plug no longer inserted")
            await _broadcast_auto_activate_skipped(pedestal_id, socket_id, "plug no longer inserted")
            return

        reason = _auto_activate_precondition_check(db, pedestal_id, socket_id)
        if reason:
            logger.info("[AutoActivate] pedestal=%d socket=%d SKIPPED (post-sleep): %s",
                        pedestal_id, socket_id, reason)
            _log_auto_activation(pedestal_id, socket_id, "skipped", reason=reason)
            await _broadcast_auto_activate_skipped(pedestal_id, socket_id, reason)
            return

        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pedestal_id).first()
        cabinet_id = getattr(cfg, "opta_client_id", None) if cfg else None
    finally:
        db.close()

    # Publish. Format matches direct_socket_cmd so the firmware sees an
    # identical command shape whether it came from the operator or auto.
    from .mqtt_client import mqtt_service
    msg_id = str(int(datetime.utcnow().timestamp() * 1000))
    if cabinet_id:
        mqtt_service.publish(
            f"opta/cmd/socket/{outlet_id}",
            json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": "activate"}),
        )
    else:
        mqtt_service.publish(
            f"pedestal/{pedestal_id}/socket/{outlet_id}/command",
            json.dumps({"msgId": msg_id, "action": "activate"}),
        )
    logger.info("[AutoActivate] pedestal=%d socket=%d published activate (msg_id=%s)",
                pedestal_id, socket_id, msg_id)
    # Session id isn't known yet — OutletActivated will create it shortly.
    _log_auto_activation(pedestal_id, socket_id, "success")


async def _handle_event_user_plugged_out(db, pedestal_id: int, outlet_id: str, resource: str, data: dict):
    """UserPluggedOut — plug was physically removed.

    If a session is currently active we stop it (publish stop command to Opta,
    complete the DB row) before marking the socket idle. If no session is
    active we just flip connected=False and broadcast idle.
    """
    is_water = resource == "WATER"
    socket_id = _water_name_to_id(outlet_id) if is_water else _socket_name_to_id(outlet_id)
    session_type = "water" if is_water else "electricity"

    _ensure_pedestal(db, pedestal_id)

    active = session_service.get_active_for_socket(db, pedestal_id, socket_id, session_type=session_type)
    if active and active.status == "active":
        # Tell the firmware to stop, then complete the DB session. The Opta
        # SessionEnded that normally follows is idempotent (handler logs +
        # re-sets socket state, we will already be idle).
        from ..models.pedestal_config import PedestalConfig
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pedestal_id).first()
        cabinet_id = getattr(cfg, "opta_client_id", None) if cfg else None
        if cabinet_id:
            from .mqtt_client import mqtt_service
            cmd_topic = (
                f"opta/cmd/water/{outlet_id}" if is_water
                else f"opta/cmd/socket/{outlet_id}"
            )
            msg_id = str(int(datetime.utcnow().timestamp() * 1000))
            mqtt_service.publish(
                cmd_topic,
                json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": "stop"}),
            )
        session_service.complete(db, active)
        await ws_manager.broadcast({
            "event": "session_completed",
            "data": {
                "session_id": active.id,
                "pedestal_id": pedestal_id,
                "socket_id": socket_id,
                "energy_kwh": active.energy_kwh,
                "water_liters": active.water_liters,
                "customer_id": active.customer_id,
            },
        })
        logger.info("[Event] UserPluggedOut %s — stopped active session %d", outlet_id, active.id)

    _set_socket_connected(db, pedestal_id, socket_id, False)
    db.commit()

    logger.info("[Event] UserPluggedOut %s (socket=%d) — state=idle", outlet_id, socket_id)
    await _broadcast_socket_state(pedestal_id, socket_id, "idle", resource=resource)


async def _handle_event_outlet_activated(db, pedestal_id: int, outlet_id: str, resource: str, data: dict):
    """OutletActivated — create + activate a session if none exists for this outlet.

    Both water valves (V1, V2) and electricity sockets (Q1–Q4) use their numeric
    id so V1 and V2 can run independent sessions. If firmware retries the event
    on ack loss, create_pending catches the DB-level UNIQUE violation and
    returns the existing session instead of inserting a duplicate.
    """
    is_water = resource == "WATER"
    socket_id = _water_name_to_id(outlet_id) if is_water else _socket_name_to_id(outlet_id)
    session_type = "water" if is_water else "electricity"

    existing = session_service.get_active_for_socket(db, pedestal_id, socket_id, session_type=session_type)
    if existing:
        logger.debug("[Event] OutletActivated %s — session %d already exists", outlet_id, existing.id)
        return

    _ensure_pedestal(db, pedestal_id)
    session = session_service.create_pending(db, pedestal_id, socket_id, session_type)
    # If another thread won the race and create_pending returned the existing
    # row, activate() is still safe (idempotent on 'active' status).
    session_service.activate(db, session)
    logger.info("[Event] OutletActivated %s → session %d (type=%s, socket_id=%s)",
                outlet_id, session.id, session_type, socket_id)

    await ws_manager.broadcast({
        "event": "session_created",
        "data": {
            "session_id": session.id,
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "type": session_type,
            "status": "active",
            "started_at": session.started_at.isoformat(),
            "customer_id": None,
            "customer_name": None,
        },
    })
    await _broadcast_socket_state(pedestal_id, socket_id, "active", resource=resource)


async def _handle_event_telemetry_update(db, pedestal_id: int, outlet_id: str, resource: str, data: dict):
    """TelemetryUpdate — store power/water readings as SensorReading records."""
    is_water = resource == "WATER"
    socket_id = _water_name_to_id(outlet_id) if is_water else _socket_name_to_id(outlet_id)
    session_type = "water" if is_water else "electricity"

    session = session_service.get_active_for_socket(db, pedestal_id, socket_id, session_type=session_type)
    session_id = session.id if session and session.status == "active" else None

    metrics = data.get("metrics", {})
    duration_min = metrics.get("durationMinutes", 0)

    if is_water:
        total_l = float(metrics.get("volumeLTotal", 0))
        if total_l > 0 or session_id:
            session_service.add_reading(db, session_id, pedestal_id, socket_id, "total_liters", total_l, "L")
        logger.info("[Telemetry] %s WATER total_l=%.3f duration=%dmin session=%s", outlet_id, total_l, duration_min, session_id)
    else:
        kwh_total = float(metrics.get("energyKwhTotal", 0))
        power_kw = float(metrics.get("powerKw", 0))
        watts = power_kw * 1000

        session_service.add_reading(db, session_id, pedestal_id, socket_id, "kwh_total", kwh_total, "kWh")
        session_service.add_reading(db, session_id, pedestal_id, socket_id, "power_watts", watts, "W")
        logger.info("[Telemetry] %s POWER kwh=%.4f watts=%.1f duration=%dmin session=%s", outlet_id, kwh_total, watts, duration_min, session_id)

        # Warn if session has been active >2min with zero energy — possible metering issue
        if session_id and duration_min >= 2 and kwh_total == 0.0 and watts == 0.0:
            _hw_warn(
                f"pedestal_{pedestal_id}",
                f"Zero energy reading on {outlet_id} after {duration_min}min — check metering hardware",
            )
            logger.warning("[Telemetry] ZERO ENERGY WARNING: %s session=%s duration=%dmin — metering may not be functioning", outlet_id, session_id, duration_min)

        await ws_manager.broadcast({
            "event": "power_reading",
            "data": {
                "pedestal_id": pedestal_id,
                "socket_id": socket_id,
                "session_id": session_id,
                "watts": watts,
                "kwh_total": kwh_total,
                "timestamp": datetime.utcnow().isoformat(),
            },
        })

        # v3.6 — per-session mobile telemetry push. Only subscribers of this
        # session's WebSocket channel receive it, so the mobile user sees
        # their own live kWh/kW data without the whole operator broadcast
        # firehose.
        if session_id is not None:
            started_at = session.started_at if session else None
            duration_seconds = int((datetime.utcnow() - started_at).total_seconds()) if started_at else 0
            await ws_manager.broadcast_to_session(session_id, {
                "event": "session_telemetry",
                "data": {
                    "session_id": session_id,
                    "pedestal_id": pedestal_id,
                    "socket_id": socket_id,
                    "duration_seconds": duration_seconds,
                    "energy_kwh": kwh_total,
                    "power_kw": round(power_kw, 3),
                    "timestamp": datetime.utcnow().isoformat(),
                },
            })


async def _handle_event_session_ended(db, pedestal_id: int, outlet_id: str, resource: str, data: dict):
    """SessionEnded — complete the DB session; store final totals from firmware."""
    is_water = resource == "WATER"
    socket_id = _water_name_to_id(outlet_id) if is_water else _socket_name_to_id(outlet_id)
    session_type = "water" if is_water else "electricity"

    session = session_service.get_active_for_socket(db, pedestal_id, socket_id, session_type=session_type)
    if not session:
        logger.warning("[Event] SessionEnded %s but no active session found (pedestal=%d)", outlet_id, pedestal_id)
        return

    # Store final totals from firmware before completing
    totals = data.get("totals", {})
    if is_water:
        final_liters = float(totals.get("volumeL", 0))
        if final_liters > 0:
            session_service.add_reading(db, session.id, pedestal_id, socket_id, "total_liters", final_liters, "L")
    else:
        final_kwh = float(totals.get("energyKwh", 0))
        session_service.add_reading(db, session.id, pedestal_id, socket_id, "kwh_total", final_kwh, "kWh")

    session_service.complete(db, session)
    logger.info("[Event] SessionEnded %s → completed session %d", outlet_id, session.id)

    await ws_manager.broadcast({
        "event": "session_completed",
        "data": {
            "session_id": session.id,
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "energy_kwh": session.energy_kwh,
            "water_liters": session.water_liters,
            "customer_id": session.customer_id,
        },
    })

    # v3.6 — push a session_ended event to the mobile subscriber and close
    # their channel cleanly. The subscriber has no further use for this
    # session after it completes.
    await ws_manager.broadcast_to_session(session.id, {
        "event": "session_ended",
        "data": {
            "session_id": session.id,
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "energy_kwh": session.energy_kwh,
            "water_liters": session.water_liters,
            "ended_at": session.ended_at.isoformat() if session.ended_at else datetime.utcnow().isoformat(),
        },
    }, close_after=True)

    # Socket state after SessionEnded:
    #   cable still inserted (SocketState.connected=True) → 'pending'
    #   cable removed                                      → 'idle'
    from ..models.pedestal_config import SocketState
    sock_state = db.query(SocketState).filter(
        SocketState.pedestal_id == pedestal_id,
        SocketState.socket_id == socket_id,
    ).first()
    still_connected = bool(sock_state and sock_state.connected)
    await _broadcast_socket_state(
        pedestal_id, socket_id, "pending" if still_connected else "idle", resource=resource,
    )


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
    """opta/status — cabinet heartbeat (same as marina status but cabinetId in payload).

    When seq=0 (Opta just restarted), publish a time sync immediately.
    """
    global _opta_cached_cabinet_id
    cabinet_id = _opta_cabinet_id(payload, "opta/status")
    if cabinet_id:
        _opta_cached_cabinet_id = cabinet_id
        await _handle_marina_status(cabinet_id, payload)

        # Detect Opta restart and send time sync
        try:
            data = json.loads(payload)
            if data.get("seq") == 0:
                _publish_time_sync()
        except (json.JSONDecodeError, Exception):
            pass

        # v3.7 — heartbeat-side `pedestal_registered is_new=False` broadcast.
        # `_cabinet_to_pedestal_id` already handled first-contact creation +
        # the `is_new=True` announce; here we just nudge connected dashboards
        # that this pedestal is alive, throttled to once per 60 s.
        try:
            db = SessionLocal()
            try:
                pid = _cabinet_to_pedestal_id(db, cabinet_id)
                if pid is not None:
                    from ..models.pedestal import Pedestal
                    from ..models.pedestal_config import PedestalConfig as _PC
                    p = db.get(Pedestal, pid)
                    cfg = db.query(_PC).filter(_PC.pedestal_id == pid).first()
                    if cfg and cfg.status != "online":
                        cfg.status = "online"
                        db.commit()
                    await _announce_pedestal_heartbeat(pid, cabinet_id, p.name if p else cabinet_id)
            finally:
                db.close()
        except Exception as e:
            logger.warning("[Discovery] heartbeat announce failed for %s: %s", cabinet_id, e)


def _publish_time_sync():
    """Publish current UTC time to opta/cmd/time for Opta RTC sync."""
    from .mqtt_client import mqtt_service
    now = datetime.utcnow()
    epoch = int(now.timestamp())
    payload = json.dumps({
        "msgId": f"timesync-{int(now.timestamp() * 1000)}",
        "action": "sync",
        "epoch": epoch,
        "iso": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    mqtt_service.publish("opta/cmd/time", payload)
    logger.info("Time sync → opta/cmd/time: epoch=%d iso=%s", epoch, now.strftime("%Y-%m-%dT%H:%M:%SZ"))


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


async def _handle_opta_diagnostic(payload: str):
    """
    opta/diagnostic
    Diagnostic response from Opta. Route to diagnostics_manager so the
    waiting API endpoint receives the result.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.warning("[Opta] Bad diagnostic payload: %s", e)
        return

    cabinet_id = data.get("cabinetId", "") or _opta_cached_cabinet_id
    if not cabinet_id:
        logger.warning("[Opta] No cabinetId in diagnostic response")
        return

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
    finally:
        db.close()

    if pedestal_id is None:
        return

    # Map Opta diagnostic response to expected sensor format.
    # Opta sends: {"power":[{"id":"Q1","state":"idle","hw":"off"},...], "water":[...]}
    # Backend expects: {"socket_1":"ok"|"fail"|"missing", "water":"ok", ...}
    from .diagnostics_manager import diagnostics_manager

    sensors = {}
    power_arr = data.get("power", [])
    for item in power_arr:
        idx = _socket_name_to_id(item.get("id", "Q1"))
        hw = item.get("hw", "off")
        state = item.get("state", "idle")
        if hw == "fault" or state == "fault":
            sensors[f"socket_{idx}"] = "fail"
        else:
            sensors[f"socket_{idx}"] = "ok"

    water_arr = data.get("water", [])
    water_ok = all(w.get("hw", "off") != "fault" for w in water_arr) if water_arr else False
    sensors["water"] = "ok" if water_ok else ("fail" if water_arr else "missing")

    # Opta doesn't have separate temp/moisture/camera sensors
    sensors["temperature"] = "ok" if data.get("mqtt") == "connected" else "missing"
    sensors["moisture"] = "ok" if data.get("mqtt") == "connected" else "missing"
    sensors["camera"] = "missing"

    # Also pass the full raw response for rich display
    sensors["_raw"] = data

    diagnostics_manager.complete_request(pedestal_id, sensors)
    logger.info("[Opta] Diagnostic response for cabinet %s (pedestal %d): power=%s water=%s time=%s",
                cabinet_id, pedestal_id,
                [f"{p['id']}:{p.get('hw','?')}" for p in power_arr],
                [f"{w['id']}:{w.get('hw','?')}" for w in water_arr],
                data.get("time", "?"))


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
