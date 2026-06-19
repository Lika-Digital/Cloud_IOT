import asyncio
import json
import logging
import re
import time
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
# published `opta/cmd/diagnostic` for this pedestal. SOCKET auto-activate
# refuses to fire within 60 s of that timestamp (prevents racing with the
# diagnostic pulse). Renamed in v3.9 for clarity vs. the valve trigger dict.
last_diagnostic_lockout_at: dict[int, datetime] = {}
# Back-compat alias — existing imports (e.g. routers/diagnostics.py) still
# reference `last_diagnostic_at`. Keeps the rename a non-breaking change.
last_diagnostic_at = last_diagnostic_lockout_at

# v3.9 — stamped when `opta/diagnostic` RESPONSE arrives. Used for telemetry
# and can be consumed by future flows that want to know when a pedestal was
# last successfully diagnosed. NOT a blocker — actual valve auto-open fires
# inline inside `_handle_opta_diagnostic` per-valve.
last_diagnostic_ok_at: dict[int, datetime] = {}

# v3.9 — Key: (pedestal_id, valve_id); Value: UTC datetime when the operator
# last manually stopped this valve. Post-diagnostic valve auto-open refuses
# to re-open within 10 minutes so that diagnostic does not become an
# accidental water-on button (D3).
last_valve_manual_stop_at: dict[tuple[int, int], datetime] = {}

# v3.28 (B5) — duplicate-activate dedup. Key: f"{pedestal_id}-{socket_id}";
# Value: time.monotonic() of the last AUTO-activate publish. A second
# UserPluggedIn racing within the window would otherwise publish a duplicate
# `activate` (seen in the field, two commands ~10 ms apart). In-memory only;
# the entry is cleared on SessionEnded so a genuine re-activation after a
# confirmed stop is never blocked. Does NOT cover operator manual activate
# (direct_socket_cmd publishes separately).
_last_activate_ts: dict[str, float] = {}
_ACTIVATE_DEDUP_WINDOW_S = 3.0

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
# v3.8 — per-socket breaker status; socket_id ("Q1"..."Q4") is in the topic path
# and authoritative. The payload may also carry `socketId` as a sanity check.
OPTA_BREAKER_RE      = re.compile(r"opta/breakers/([^/]+)/status")
# v3.11 — cabinet hardware configuration (one-shot per cabinet) + live per-socket
# meter telemetry every 5 s. Socket id ("Q1"..."Q4") is in the topic path on
# /meters/; on /config/hardware the cabinetId comes from the payload (one
# message describes every socket).
OPTA_HW_CONFIG_RE    = re.compile(r"opta/config/hardware")
OPTA_METER_RE        = re.compile(r"opta/meters/([^/]+)/telemetry")


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
            auto_activate=True,
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


def _auto_discover_valve_config(db, pedestal_id: int, valve_id: int) -> bool:
    """v3.9 — ValveConfig sibling of _auto_discover_socket_config.

    Mirrors the v3.7 auto-discovery pattern: on first contact with a water
    valve, create the config row with `auto_activate=True` (default-ON for
    valves, opposite of sockets). Never overwrites an existing row so
    operator toggles survive.
    """
    try:
        from ..models.valve_config import ValveConfig
        row = db.query(ValveConfig).filter(
            ValveConfig.pedestal_id == pedestal_id,
            ValveConfig.valve_id == valve_id,
        ).first()
        if row:
            return False
        db.add(ValveConfig(
            pedestal_id=pedestal_id,
            valve_id=valve_id,
            auto_activate=True,
        ))
        db.commit()
        logger.info("[Discovery] ValveConfig created pedestal=%d valve=%d", pedestal_id, valve_id)
        return True
    except Exception as e:
        logger.warning("[Discovery] valve config create failed (pedestal=%d valve=%d): %s",
                       pedestal_id, valve_id, e)
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


def _smart_mode_on(db, pedestal_id: int) -> bool:
    """v3.30 — True if the pedestal's firmware SmartMode is ON (NUC in control).

    When OFF the Opta runs standalone and the NUC is monitor + alarms only: it
    must NOT create/adopt sessions, auto-activate sockets, or auto-open valves.
    Used as the master gate for every NUC-initiated action.
    """
    from ..models.pedestal_config import PedestalConfig
    cfg = db.query(PedestalConfig).filter(
        PedestalConfig.pedestal_id == pedestal_id
    ).first()
    return bool(cfg and cfg.smart_mode)


def _coerce_bool(value):
    """Coerce a firmware-reported flag to a real bool for Boolean DB columns.

    The Opta sends RCD presence as the strings "yes"/"no" (also seen: "true"/
    "false", "1"/"0"). SQLAlchemy/SQLite reject a raw string for a Boolean
    column ("Not a boolean value: 'no'"), so normalise here. Passes None and
    real bools through unchanged; returns None for unrecognised values so an
    unknown flag stays NULL rather than crashing.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in ("yes", "true", "1", "on"):
        return True
    if s in ("no", "false", "0", "off"):
        return False
    return None


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
        elif m := OPTA_BREAKER_RE.match(topic):
            await _handle_opta_breaker_status(m.group(1), payload)
        elif OPTA_HW_CONFIG_RE.match(topic):
            await _handle_opta_hardware_config(payload)
        elif m := OPTA_METER_RE.match(topic):
            await _handle_opta_meter_telemetry(m.group(1), payload)
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

        # v3.30 — standalone defensive clear. In Smart Mode OFF the dashboard is
        # read-only, so a socket the firmware reports `idle` with no session must
        # not linger as `awaiting_activation`/`pending` (that marker only makes
        # sense for the NUC-driven Activate flow). Without this, a marker set
        # while Smart Mode was ON survives the periodic idle poll forever. Gated
        # on smart_mode=False so the sticky-pending behaviour is untouched while
        # the NUC is in control.
        if (
            raw_state == "idle"
            and data.get("session") is None
            and state_row.operator_status in ("pending", "awaiting_activation")
        ):
            from ..models.pedestal_config import PedestalConfig
            _cfg = db.query(PedestalConfig).filter(
                PedestalConfig.pedestal_id == pedestal_id
            ).first()
            if _cfg is not None and not _cfg.smart_mode:
                state_row.operator_status = None
                state_row.operator_status_at = None
        db.commit()

        # v3.18 — adopt a session the hardware is already running. If the Opta
        # reports the socket ACTIVE but we have no open session (e.g. the Opta
        # ran standalone and the NUC just (re)connected), materialize one so the
        # live session is TRACKED rather than torn down by a later event.
        # v3.30 — only when SmartMode is ON. In standalone the NUC is monitor-
        # only and must not create NUC sessions (that produced the spurious
        # "unattributed" sessions while the Opta owned everything).
        if raw_state == "active" and _smart_mode_on(db, pedestal_id):
            from .session_service import session_service as _ss
            if _ss.get_active_for_socket(db, pedestal_id, socket_id, session_type="electricity") is None:
                _adopted = _ss.create_pending(db, pedestal_id, socket_id, "electricity")
                _ss.activate(db, _adopted)
                logger.info("[Adopt] pedestal=%d socket=%d adopted live session %d",
                            pedestal_id, socket_id, _adopted.id)
                await ws_manager.broadcast({
                    "event": "session_created",
                    "data": {
                        "session_id": _adopted.id, "pedestal_id": pedestal_id,
                        "socket_id": socket_id, "type": "electricity", "status": "active",
                        "started_at": _adopted.started_at.isoformat(),
                        "customer_id": None, "customer_name": None, "adopted": True,
                    },
                })

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

        # B2 (v3.21) — resolve the unified display state (fault precedence) while
        # the db session is still open; broadcast it after the session closes.
        display_state = _compute_socket_display_state(
            db, pedestal_id, socket_id,
            raw_state=raw_state, hw_status=data.get("hw_status", ""),
        )
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

    # B2 (v3.21) — emit the unified socket_state_changed so the dashboard badge
    # (socketComputedStates, single source of truth) respects fault precedence:
    # fault > active > pending > idle. Display only — session state is untouched.
    await _broadcast_socket_state(pedestal_id, socket_id, display_state, "POWER")


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

    valve_id = _water_name_to_id(water_name)
    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
        # v3.9 — idempotent ValveConfig auto-discovery on first sight.
        if pedestal_id is not None:
            _auto_discover_valve_config(db, pedestal_id, valve_id)
    finally:
        db.close()

    if pedestal_id is None:
        logger.warning("[Marina] Could not resolve cabinet '%s' to pedestal_id", cabinet_id)
        return

    logger.debug("[Marina] cabinet=%s water=%s total_l=%.3f session_l=%.3f", cabinet_id, water_name, total_l, session_l)

    # v3.18 — adopt a live water session on (re)connect (same as electricity).
    # v3.30 — SmartMode-gated: in standalone the NUC must not create sessions
    # (this was the source of the "unattributed" valve badge while OFF).
    if data.get("state") == "active":
        adb = SessionLocal()
        try:
            from .session_service import session_service as _ss
            if not _smart_mode_on(adb, pedestal_id):
                pass
            elif _ss.get_active_for_socket(adb, pedestal_id, valve_id, session_type="water") is None:
                _adopted = _ss.create_pending(adb, pedestal_id, valve_id, "water")
                _ss.activate(adb, _adopted)
                logger.info("[Adopt] pedestal=%d valve=%d adopted live water session %d",
                            pedestal_id, valve_id, _adopted.id)
                await ws_manager.broadcast({
                    "event": "session_created",
                    "data": {
                        "session_id": _adopted.id, "pedestal_id": pedestal_id,
                        "socket_id": valve_id, "type": "water", "status": "active",
                        "started_at": _adopted.started_at.isoformat(),
                        "customer_id": None, "customer_name": None, "adopted": True,
                    },
                })
        finally:
            adb.close()

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

    smart_mode_val = None
    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
        if pedestal_id is not None:
            from ..models.pedestal_config import PedestalConfig
            cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pedestal_id).first()
            # v3.28 — update SmartMode ONLY when the firmware includes the field;
            # an absent `smartMode` must not clobber the stored value.
            if cfg is not None and "smartMode" in data:
                new_sm = bool(data["smartMode"])
                if cfg.smart_mode != new_sm:
                    cfg.smart_mode = new_sm
                    db.commit()
            smart_mode_val = bool(cfg.smart_mode) if cfg is not None else None
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
            "smart_mode": smart_mode_val,
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
        elif event_type == "BreakerTripped":
            # v3.8 — breaker trip event. Logs to breaker_events, stops any active
            # power session on that socket with end_reason="breaker_trip", and
            # broadcasts a breaker_alarm WS event for persistent dashboard UI.
            await _handle_event_breaker_tripped(db, pedestal_id, outlet_id, data)
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


# v3.32 — a socket is "delivering power" when the live meter shows real draw.
# Small thresholds so standby/measurement noise does not flicker the badge.
_METER_ACTIVE_KW = 0.05       # >= 50 W
_METER_ACTIVE_AMPS = 0.30     # >= 0.3 A on any phase


def _socket_delivering_power(cfg) -> bool:
    """True when the live meter shows real current/power above a small
    threshold. Handles single- and three-phase configs (the Opta reports the
    meter in BOTH Smart Mode ON and OFF)."""
    if cfg is None:
        return False
    pwr = getattr(cfg, "meter_power_kw", None)
    if pwr is not None and pwr >= _METER_ACTIVE_KW:
        return True
    for field in ("meter_current_amps", "meter_current_l1", "meter_current_l2", "meter_current_l3"):
        c = getattr(cfg, field, None)
        if c is not None and c >= _METER_ACTIVE_AMPS:
            return True
    return False


def _compute_socket_display_state(
    db, pedestal_id: int, socket_id: int, *, raw_state: str = "", hw_status: str = "",
) -> str:
    """B2 (v3.21) — unified socket display state with fault precedence.

    Precedence: fault > active(session or live meter) > pending > idle. A
    hardware fault or a tripped breaker always wins. v3.32 — a socket that is
    physically delivering power (live meter above threshold) is shown active
    even with no NUC session, so a standalone (Smart Mode OFF) socket passing
    power shows active instead of idle. Display only — sessions are untouched.

    Fault signals (D5): the live message reports `fault`, OR the persisted
    `SocketConfig.breaker_state == "tripped"`, OR `SocketState.connected is
    False` (set whenever the firmware reports a non-active/idle state).
    """
    if hw_status == "fault" or raw_state == "fault":
        return "fault"

    from ..models.socket_config import SocketConfig
    from ..models.pedestal_config import SocketState

    cfg = db.query(SocketConfig).filter(
        SocketConfig.pedestal_id == pedestal_id,
        SocketConfig.socket_id == socket_id,
    ).first()
    if cfg is not None and cfg.breaker_state == "tripped":
        return "fault"

    ss = db.query(SocketState).filter(
        SocketState.pedestal_id == pedestal_id,
        SocketState.socket_id == socket_id,
    ).first()
    if ss is not None and ss.connected is False:
        return "fault"

    # v3.32 — live meter shows real draw → active, regardless of session
    # bookkeeping (covers Smart Mode OFF / standalone sockets passing power).
    if _socket_delivering_power(cfg):
        return "active"

    from .session_service import session_service as _ss
    active = _ss.get_active_for_socket(db, pedestal_id, socket_id, session_type="electricity")
    if active is not None:
        return "active" if getattr(active, "status", None) == "active" else "pending"
    # No session, but a plug is physically inserted awaiting operator action.
    # Modern Opta UserPluggedIn flow sets "awaiting_activation"; the legacy
    # connect-string flow sets "pending". Either keeps the socket shown as
    # pending so the operator can still activate it.
    if ss is not None and ss.operator_status in ("pending", "awaiting_activation"):
        return "pending"
    return "idle"


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


async def reconcile_pedestal_standalone(pedestal_id: int) -> None:
    """v3.30 — Smart Mode OFF reconciliation.

    When a cabinet drops to standalone (firmware controls power directly; the
    dashboard is read-only for that pedestal), the NUC must not keep showing
    actionable "pending" badges left over from the Smart Mode session/plug-in
    flow. Clear any stale per-socket `operator_status` markers
    (awaiting_activation/pending) and deny any electricity session still stuck in
    `pending` (created but never activated), then re-broadcast the resolved
    display state so the dashboard falls back to idle/fault.

    Active sessions are left untouched — an adopted live session stays tracked.
    Fault precedence is preserved: a tripped breaker / hardware fault still wins,
    so a faulted socket keeps showing `fault`, not `idle`.
    """
    from ..models.pedestal_config import SocketState
    from ..models.session import Session as _S

    changed_sockets: set[int] = set()
    states: dict[int, str] = {}
    db = SessionLocal()
    try:
        for ss in db.query(SocketState).filter(
            SocketState.pedestal_id == pedestal_id
        ).all():
            if ss.operator_status in ("pending", "awaiting_activation"):
                ss.operator_status = None
                ss.operator_status_at = None
                changed_sockets.add(ss.socket_id)
        # Tear down sessions never activated; leave live `active` sessions alone.
        for s in db.query(_S).filter(
            _S.pedestal_id == pedestal_id,
            _S.type == "electricity",
            _S.status == "pending",
        ).all():
            session_service.deny(db, s, reason="Smart Mode disabled")  # commits
            if s.socket_id is not None:
                changed_sockets.add(s.socket_id)
        db.commit()

        for sid in changed_sockets:
            states[sid] = _compute_socket_display_state(db, pedestal_id, sid)
    finally:
        db.close()

    for sid, st in states.items():
        await _broadcast_socket_state(pedestal_id, sid, st, resource="POWER")
    if states:
        logger.info("[Standalone] pedestal=%d reconciled sockets %s on Smart Mode OFF",
                    pedestal_id, sorted(states.keys()))


# ── v3.32 — standalone usage recording ───────────────────────────────────────
# When Smart Mode is OFF the Opta runs the sockets standalone and emits no
# control session, but it DOES report the meter. This watchdog turns sustained
# consumption into a usage session (origin="standalone", customer blank) so it
# shows in Usage History, and integrates energy from power x time because the
# firmware reports energyKwh=0. When Smart Mode is ON the control flow owns
# sessions, so any lingering standalone session is completed and handed back.
_STANDALONE_USAGE_STOP_GRACE_S = 120     # complete after this long below threshold
_STANDALONE_TICK_S = 30
_standalone_usage_last: dict = {}        # (pid, sid) -> (datetime, power_kw)
_standalone_usage_low_since: dict = {}   # (pid, sid) -> datetime first below threshold

# v3.32 — per-socket power×time energy integration state for the LIVE meter
# handler: (pid, sid) -> (last_sample_time, last_power_kw, session_id).
_meter_energy_last: dict = {}


def _integrate_session_energy(db, pedestal_id: int, socket_id: int, power_kw, now=None) -> None:
    """Accumulate energy_kwh on the active electricity session from power × time.

    Called on every meter tick (~5 s). Because the Opta's cumulative `energyKwh`
    register reads 0, this trapezoidal integral is the real source of energy for
    ANY active session (operator / customer / NFC OR standalone). dt is the gap
    between received samples, clamped to ignore restarts; resets per session id.
    """
    now = now or datetime.utcnow()
    from .session_service import session_service as _ss
    active = _ss.get_active_for_socket(db, pedestal_id, socket_id, session_type="electricity")
    key = (pedestal_id, socket_id)
    if active is None:
        _meter_energy_last.pop(key, None)
        return
    p = float(power_kw or 0.0)
    last = _meter_energy_last.get(key)
    if last is not None and last[2] == active.id:
        dt_s = (now - last[0]).total_seconds()
        if 0 < dt_s <= 60:
            avg_kw = (last[1] + p) / 2.0
            active.energy_kwh = (active.energy_kwh or 0.0) + avg_kw * (dt_s / 3600.0)
    _meter_energy_last[key] = (now, p, active.id)


async def _standalone_usage_tick(now: datetime) -> None:
    """One pass over every electricity socket: open/integrate/close standalone
    usage sessions based on the live meter and the pedestal's Smart Mode."""
    from ..models.socket_config import SocketConfig
    from ..models.pedestal_config import PedestalConfig
    from ..models.session import Session as _Session
    from .session_service import session_service as _ss

    broadcasts: list[tuple] = []
    db = SessionLocal()
    try:
        smart_off = {
            c.pedestal_id for c in db.query(PedestalConfig).all() if not c.smart_mode
        }
        for sc in db.query(SocketConfig).all():
            pid, sid = sc.pedestal_id, sc.socket_id
            key = (pid, sid)
            open_sess = _ss.get_active_for_socket(db, pid, sid, session_type="electricity")
            standalone_open = open_sess if (
                open_sess is not None and getattr(open_sess, "origin", None) == "standalone"
            ) else None

            if pid not in smart_off:
                # Smart Mode ON — hand control back: complete any standalone session.
                if standalone_open is not None:
                    _ss.complete(db, standalone_open)
                    _standalone_usage_last.pop(key, None)
                    _standalone_usage_low_since.pop(key, None)
                    broadcasts.append(("session_completed", standalone_open, pid, sid))
                continue

            if _socket_delivering_power(sc):
                _standalone_usage_low_since.pop(key, None)
                if open_sess is None:
                    s = _Session(
                        pedestal_id=pid, socket_id=sid, type="electricity",
                        status="active", started_at=now, energy_kwh=0.0,
                        customer_id=None, origin="standalone",
                    )
                    db.add(s)
                    db.flush()
                    broadcasts.append(("session_created", s, pid, sid))
                # Energy is integrated by the live meter handler (every ~5 s) for
                # whatever session is active — including this standalone one — so
                # the watchdog only opens/closes; it never touches energy_kwh.
            else:
                if standalone_open is not None:
                    first_low = _standalone_usage_low_since.setdefault(key, now)
                    if (now - first_low).total_seconds() >= _STANDALONE_USAGE_STOP_GRACE_S:
                        _ss.complete(db, standalone_open)
                        _standalone_usage_last.pop(key, None)
                        _standalone_usage_low_since.pop(key, None)
                        broadcasts.append(("session_completed", standalone_open, pid, sid))
        db.commit()
        for evt, sess, pid, sid in broadcasts:
            db.refresh(sess)
    finally:
        db.close()

    for evt, sess, pid, sid in broadcasts:
        await ws_manager.broadcast({
            "event": evt,
            "data": {
                "session_id": sess.id, "pedestal_id": pid, "socket_id": sid,
                "type": "electricity",
                "status": sess.status,
                "energy_kwh": sess.energy_kwh,
                "customer_id": None, "customer_name": None,
                "origin": "standalone",
                "started_at": sess.started_at.isoformat() if sess.started_at else None,
                "timestamp": datetime.utcnow().isoformat(),
            },
        })


async def run_standalone_usage_watchdog() -> None:
    """Lifespan task — ticks every 30 s."""
    while True:
        await asyncio.sleep(_STANDALONE_TICK_S)
        try:
            await _standalone_usage_tick(datetime.utcnow())
        except Exception as e:
            logger.warning("[StandaloneUsage] tick failed: %s", e)


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

    # v3.25 — persist "plug inserted, awaiting manual activation" so the pending
    # display survives the periodic idle status poll (keeps the Control Center
    # Activate button enabled until the operator acts or the plug is removed).
    # We use a DISTINCT marker ("awaiting_activation") rather than "pending" so
    # the 15s pending auto-reject sweep — which targets the legacy customer
    # approval flow keyed on operator_status == "pending" — does NOT cancel it.
    if not is_water and not (active and active.status == "active"):
        from ..models.pedestal_config import SocketState
        ss = db.query(SocketState).filter(
            SocketState.pedestal_id == pedestal_id,
            SocketState.socket_id == socket_id,
        ).first()
        if ss is not None and ss.operator_status not in ("pending", "awaiting_activation"):
            ss.operator_status = "awaiting_activation"
            ss.operator_status_at = datetime.utcnow()
            db.commit()

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

        # v3.26 — NFC: a valid (non-expired) pending scan authorizes a one-shot
        # activation on plug-in, regardless of auto_activate. The ERP user is
        # attached to the resulting session in _handle_event_outlet_activated.
        from . import nfc_service as _nfc
        from ..models.pedestal_config import PedestalConfig as _PC
        _pc = db.query(_PC).filter(_PC.pedestal_id == pedestal_id).first()
        cabinet_id = getattr(_pc, "opta_client_id", None) if _pc else None
        live = _nfc.get_live_pending(db, cabinet_id, outlet_id) if cabinet_id else None

        if live is not None:
            live.status = "activated"
            db.commit()
            logger.info("[NFC] UserPluggedIn matched pending (user=%s, %s/%s) — one-shot activate",
                        live.user_id, cabinet_id, outlet_id)
            asyncio.create_task(_maybe_auto_activate(pedestal_id, socket_id, outlet_id))
        elif cfg and cfg.auto_activate:
            asyncio.create_task(_maybe_auto_activate(pedestal_id, socket_id, outlet_id))
        else:
            # NFC mode (auto_activate False) with no valid pending scan: do not
            # activate. Socket stays idle until a valid NFC scan + plug-in.
            logger.info("[NFC] UserPluggedIn on %s/%s — no valid NFC pending and "
                        "auto_activate off; activation blocked", cabinet_id, outlet_id)


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

    # 0. v3.30 — SmartMode must be ON. In standalone the Opta owns control and
    #    ignores NUC commands; the NUC must not auto-activate.
    if not _smart_mode_on(db, pedestal_id):
        return "smart mode off"

    # 1. Door state is NO LONGER a blocking precondition (v3.18). An open or
    #    unknown door only raises a WARNING at activation time (see
    #    _maybe_auto_activate) — sockets must work with the door open (common
    #    during testing/operation); breakers guard against electrical faults.

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

    # 5. No diagnostic running (socket lockout window).
    last_diag = last_diagnostic_lockout_at.get(pedestal_id)
    if last_diag and (datetime.utcnow() - last_diag).total_seconds() < _DIAGNOSTIC_LOCKOUT_S:
        return "diagnostic in progress"

    # 6. v3.30 — an overload alarm no longer blocks auto-activation (alarm-only;
    # the NUC never withholds control). The previous auto_stop_pending_ack guard
    # was removed to match approve_socket / direct_socket_cmd.

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
        door_state = getattr(cfg, "door_state", "unknown") if cfg else "unknown"
    finally:
        db.close()

    # v3.18 — door is non-blocking; warn but proceed if it's open/unknown.
    if door_state != "closed":
        _hw_warn(
            f"pedestal_{pedestal_id}",
            f"Auto-activating socket {socket_id} with cabinet door {door_state.upper()} "
            f"— proceeding (door is non-blocking).",
        )

    # v3.28 (B5) — duplicate-activate dedup. If an auto-activate was already
    # published for this socket within the window, skip this one (absorbs the
    # two-UserPluggedIn race). The entry is cleared on SessionEnded so a genuine
    # re-activation after a confirmed stop is never blocked.
    _akey = f"{pedestal_id}-{socket_id}"
    _now = time.monotonic()
    _prev = _last_activate_ts.get(_akey)
    if _prev is not None and (_now - _prev) < _ACTIVATE_DEDUP_WINDOW_S:
        logger.warning(
            "[AutoActivate] pedestal=%d socket=%d SKIPPED: duplicate activate within %.1fs (race)",
            pedestal_id, socket_id, _ACTIVATE_DEDUP_WINDOW_S)
        _log_auto_activation(pedestal_id, socket_id, "skipped", reason="duplicate activate (dedup)")
        return
    _last_activate_ts[_akey] = _now

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


# ── v3.9 — Post-diagnostic valve auto-open + zero-flow watchdog ──────────────

_VALVE_MANUAL_STOP_COOLDOWN_S = 600   # D3: 10 minutes after a manual stop
_VALVE_FLOW_WATCHDOG_S = 30           # User-requested zero-flow check delay


async def _maybe_auto_open_valve(pedestal_id: int, valve_id: int, cabinet_id: str | None) -> None:
    """Post-diagnostic auto-open for a single valve (v3.9).

    Triggered by `_handle_opta_diagnostic` when the diagnostic response arrives
    and reports that this valve's sensor is ok.

    Guards (in order, first failure logs + returns):
      0. SmartMode is ON (v3.30 — standalone NUC never auto-opens).
      1. ValveConfig.auto_activate is True for this (pedestal, valve).
      2. No active water session on this valve.
      3. Operator has not manually stopped this valve in the last 10 minutes.
      4. Pedestal has a cabinet_id configured (else MQTT publish is impossible).

    On success: publishes `opta/cmd/water/V{n}` activate and spawns a 30 s
    zero-flow watchdog. The unattributed customer_id=NULL session is created
    by the existing `_handle_event_outlet_activated` flow when firmware emits
    `OutletActivated` in response to this activate command.
    """
    db = SessionLocal()
    try:
        from ..models.valve_config import ValveConfig
        from ..models.session import Session as SessionModel

        # 0. v3.30 — SmartMode master gate.
        if not _smart_mode_on(db, pedestal_id):
            logger.info("[ValveAutoOpen] pedestal=%d valve=%d SKIPPED: smart mode off",
                        pedestal_id, valve_id)
            return

        cfg = db.query(ValveConfig).filter(
            ValveConfig.pedestal_id == pedestal_id,
            ValveConfig.valve_id == valve_id,
        ).first()
        if not cfg or not cfg.auto_activate:
            logger.info("[ValveAutoOpen] pedestal=%d valve=%d SKIPPED: auto_activate=False",
                        pedestal_id, valve_id)
            return

        existing = db.query(SessionModel).filter(
            SessionModel.pedestal_id == pedestal_id,
            SessionModel.socket_id == valve_id,
            SessionModel.type == "water",
            SessionModel.status.in_(["pending", "active"]),
        ).first()
        if existing:
            logger.info("[ValveAutoOpen] pedestal=%d valve=%d SKIPPED: active session %d",
                        pedestal_id, valve_id, existing.id)
            return
    finally:
        db.close()

    last_stop = last_valve_manual_stop_at.get((pedestal_id, valve_id))
    if last_stop and (datetime.utcnow() - last_stop).total_seconds() < _VALVE_MANUAL_STOP_COOLDOWN_S:
        elapsed = int((datetime.utcnow() - last_stop).total_seconds())
        logger.info("[ValveAutoOpen] pedestal=%d valve=%d SKIPPED: manual stop %ds ago (cooldown %ds)",
                    pedestal_id, valve_id, elapsed, _VALVE_MANUAL_STOP_COOLDOWN_S)
        return

    if not cabinet_id:
        logger.warning("[ValveAutoOpen] pedestal=%d valve=%d SKIPPED: no cabinet_id",
                       pedestal_id, valve_id)
        return

    # Publish activate. Same shape as operator-initiated activation.
    from .mqtt_client import mqtt_service
    msg_id = str(int(datetime.utcnow().timestamp() * 1000))
    mqtt_service.publish(
        f"opta/cmd/water/V{valve_id}",
        json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": "activate"}),
    )
    logger.info("[ValveAutoOpen] pedestal=%d valve=%d ACTIVATE published to cabinet=%s (msg_id=%s)",
                pedestal_id, valve_id, cabinet_id, msg_id)

    # Fire-and-forget 30-second zero-flow check.
    asyncio.create_task(_check_valve_flow_after_30s(pedestal_id, valve_id))


async def _check_valve_flow_after_30s(pedestal_id: int, valve_id: int) -> None:
    """Zero-flow safety watchdog (v3.9 informational guard).

    30 seconds after an auto-open publishes, check the most recent `lpm`
    SensorReading for this valve. If flow is 0, broadcast a
    `valve_flow_warning` event so the operator sees a dashboard banner.
    Informational only — does not close the valve.
    """
    await asyncio.sleep(_VALVE_FLOW_WATCHDOG_S)

    db = SessionLocal()
    try:
        from ..models.sensor_reading import SensorReading
        from datetime import timedelta as _td
        cutoff = datetime.utcnow() - _td(seconds=_VALVE_FLOW_WATCHDOG_S + 5)
        recent = (
            db.query(SensorReading)
            .filter(
                SensorReading.pedestal_id == pedestal_id,
                SensorReading.socket_id == valve_id,
                SensorReading.type == "lpm",
                SensorReading.timestamp >= cutoff,
            )
            .order_by(SensorReading.timestamp.desc())
            .first()
        )
        latest_flow = float(recent.value) if recent is not None else 0.0
    finally:
        db.close()

    if latest_flow > 0:
        logger.info("[ValveWatchdog] pedestal=%d valve=%d flow=%.3f lpm — healthy",
                    pedestal_id, valve_id, latest_flow)
        return

    message = f"Auto-activated valve V{valve_id} reports zero flow — possible disconnected hose"
    logger.warning("[ValveWatchdog] pedestal=%d valve=%d %s", pedestal_id, valve_id, message)
    try:
        from .error_log_service import log_warning
        log_warning("hw", f"pedestal_{pedestal_id}", message)
    except Exception:
        pass

    await ws_manager.broadcast({
        "event": "valve_flow_warning",
        "data": {
            "pedestal_id": pedestal_id,
            "valve_id": valve_id,
            "reason": "zero_flow_after_auto_open",
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


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

        # v3.26 — ERP webhook: session ended via unplug (de-duped vs SessionEnded).
        if not is_water:
            from . import erp_webhook
            if erp_webhook.mark_ended(active.id):
                _pl = erp_webhook.build(db, active, "session_ended")
                if _pl is not None:
                    asyncio.create_task(erp_webhook.post_erp_event(_pl))

    _set_socket_connected(db, pedestal_id, socket_id, False)
    # v3.25 — plug removed: clear any plug-in pending marker so the socket
    # returns to idle (not stuck "awaiting activation").
    if not is_water:
        from ..models.pedestal_config import SocketState as _SS
        ss_row = db.query(_SS).filter(
            _SS.pedestal_id == pedestal_id, _SS.socket_id == socket_id,
        ).first()
        if ss_row is not None:
            ss_row.operator_status = None
            ss_row.operator_status_at = None
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

    # v3.25 — clear the plug-in pending marker now that a live session exists.
    if not is_water:
        from ..models.pedestal_config import SocketState as _SS
        ss_row = db.query(_SS).filter(
            _SS.pedestal_id == pedestal_id, _SS.socket_id == socket_id,
        ).first()
        if ss_row is not None and ss_row.operator_status is not None:
            ss_row.operator_status = None
            ss_row.operator_status_at = None
            db.commit()

    # v3.26 — NFC: attach the ERP user if this activation was authorized by a
    # recent NFC scan (marked "activated" on UserPluggedIn for this socket).
    # The recency window bounds staleness so a later operator manual-activate
    # does not inherit an old scan's user.
    nfc_user_id = None
    if not is_water:
        from datetime import timedelta
        from ..models.pedestal_config import PedestalConfig as _PC
        from ..models.nfc_pending_session import NfcPendingSession as _NPS
        _pc = db.query(_PC).filter(_PC.pedestal_id == pedestal_id).first()
        cabinet_id = getattr(_pc, "opta_client_id", None) if _pc else None
        if cabinet_id:
            cutoff = datetime.utcnow() - timedelta(minutes=10)
            rec = (db.query(_NPS)
                   .filter(_NPS.cabinet_id == cabinet_id,
                           _NPS.socket_id == outlet_id,
                           _NPS.status == "activated",
                           _NPS.created_at >= cutoff)
                   .order_by(_NPS.created_at.desc())
                   .first())
            if rec is not None:
                session.nfc_user_id = rec.user_id
                nfc_user_id = rec.user_id
                db.commit()
                logger.info("[NFC] attached user=%s to session %d", rec.user_id, session.id)

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
            "nfc_user_id": nfc_user_id,
        },
    })
    await _broadcast_socket_state(pedestal_id, socket_id, "active", resource=resource)

    # v3.26 — ERP webhook: socket activated.
    if not is_water:
        from . import erp_webhook
        _pl = erp_webhook.build(db, session, "session_activated")
        if _pl is not None:
            asyncio.create_task(erp_webhook.post_erp_event(_pl))


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

            # v3.26 — ERP webhook: throttled (~60 s) live telemetry.
            from . import erp_webhook
            if erp_webhook.should_send_telemetry(session_id):
                _pl = erp_webhook.build(db, session, "telemetry")
                if _pl is not None:
                    asyncio.create_task(erp_webhook.post_erp_event(_pl))


async def _handle_event_session_ended(db, pedestal_id: int, outlet_id: str, resource: str, data: dict):
    """SessionEnded — complete the DB session; store final totals from firmware."""
    is_water = resource == "WATER"
    socket_id = _water_name_to_id(outlet_id) if is_water else _socket_name_to_id(outlet_id)
    session_type = "water" if is_water else "electricity"

    # v3.28 (B5) — clear the activate-dedup entry so a legitimate re-activation
    # after this confirmed stop is never blocked by the dedup window.
    _last_activate_ts.pop(f"{pedestal_id}-{socket_id}", None)

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

    # v3.26 — ERP webhook: session ended (any cause). De-duped across end paths.
    if not is_water:
        from . import erp_webhook
        if erp_webhook.mark_ended(session.id):
            _pl = erp_webhook.build(db, session, "session_ended")
            if _pl is not None:
                asyncio.create_task(erp_webhook.post_erp_event(_pl))

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

    cmd_topic = data.get("cmd_topic") or data.get("cmdTopic") or ""
    status = data.get("status")
    led_event = None

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
        # v3.27 — confirm LED state from the ACK on opta/cmd/led. The intended
        # on/off was persisted when the command was sent; the ACK flips it to
        # confirmed (status ok) or clears the pending flag (status not ok).
        if pedestal_id is not None and cmd_topic.endswith("cmd/led"):
            from ..models.pedestal_config import PedestalConfig
            cfg = db.query(PedestalConfig).filter(
                PedestalConfig.pedestal_id == pedestal_id
            ).first()
            if cfg is not None:
                cfg.led_pending = False
                ok = status == "ok"
                if ok:
                    cfg.led_confirmed_at = datetime.utcnow()
                db.commit()
                led_event = {
                    "pedestal_id": pedestal_id,
                    "cabinet_id": cabinet_id,
                    "on": bool(cfg.led_on),
                    "state": "on" if cfg.led_on else "off",
                    "confirmed": ok,
                    "source": "ack",
                    "timestamp": datetime.utcnow().isoformat(),
                }
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
    if led_event is not None:
        await ws_manager.broadcast({"event": "led_changed", "data": led_event})


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


async def _handle_opta_breaker_status(socket_name: str, payload: str):
    """v3.8 — opta/breakers/{socket_id}/status.

    Updates `SocketConfig` breaker state + metadata, stamps
    `breaker_last_trip_at` and increments `breaker_trip_count` on fresh trips,
    and broadcasts `breaker_state_changed` to all dashboards.

    Metadata rule: only write fields that are PRESENT in the payload. A missing
    key leaves the previously-stored value alone — D4 in v3.8 design decisions.
    `socket_id` is taken from the topic path; payload `socketId` is used as a
    sanity check and logged as warning if it disagrees.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.warning("[Breaker] Bad status payload on %s: %s", socket_name, e)
        return

    cabinet_id = _opta_cabinet_id(payload, f"opta/breakers/{socket_name}/status")
    if not cabinet_id:
        return

    # Sanity check — log if payload disagrees with topic path. Real Opta firmware
    # sends `outletId`; older/marina payloads send `socketId`. Accept either.
    payload_socket = data.get("outletId") or data.get("socketId")
    if payload_socket and payload_socket != socket_name:
        logger.warning(
            "[Breaker] payload outletId/socketId=%s disagrees with topic socket_name=%s — trusting topic",
            payload_socket, socket_name,
        )

    # Real firmware sends `state`; legacy payloads send `breakerState`. Accept both.
    breaker_state = data.get("state") or data.get("breakerState") or "unknown"
    trip_cause    = data.get("tripCause") or data.get("cause")  # None when closed.
    socket_id     = _socket_name_to_id(socket_name)

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
        if pedestal_id is None:
            logger.warning("[Breaker] Could not resolve cabinet '%s' for breaker status", cabinet_id)
            return

        _ensure_pedestal(db, pedestal_id)

        from ..models.socket_config import SocketConfig
        cfg = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == pedestal_id,
            SocketConfig.socket_id == socket_id,
        ).first()
        if cfg is None:
            # Mirror the v3.7 auto-discovery pattern: create the row with defaults.
            cfg = SocketConfig(
                pedestal_id=pedestal_id,
                socket_id=socket_id,
                auto_activate=True,
            )
            db.add(cfg)
            db.flush()

        previous_state = cfg.breaker_state
        cfg.breaker_state = breaker_state
        cfg.breaker_trip_cause = trip_cause

        # Increment count + stamp timestamp on the transition INTO tripped.
        if breaker_state == "tripped" and previous_state != "tripped":
            cfg.breaker_last_trip_at = datetime.utcnow()
            cfg.breaker_trip_count = (cfg.breaker_trip_count or 0) + 1

        # Metadata merge — D4: only write keys that are PRESENT in this payload.
        # `in data` check handles explicit `null` values (treated as written) and
        # absent keys (treated as no-change). This preserves history across
        # firmware messages that omit the metadata block.
        # Real firmware sends `type`; legacy sends `breakerType`. Accept either.
        if "type" in data or "breakerType" in data:
            cfg.breaker_type = data.get("type", data.get("breakerType"))
        if "rating" in data:
            cfg.breaker_rating = data["rating"]
        if "poles" in data:
            cfg.breaker_poles = data["poles"]
        if "rcd" in data:
            # Firmware sends "yes"/"no" strings; column is Boolean. Coerce.
            cfg.breaker_rcd = _coerce_bool(data["rcd"])
        if "rcdSensitivity" in data:
            cfg.breaker_rcd_sensitivity = data["rcdSensitivity"]

        db.commit()
    finally:
        db.close()

    await ws_manager.broadcast({
        "event": "breaker_state_changed",
        "data": {
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "breaker_state": breaker_state,
            "trip_cause": trip_cause,
            "breaker_type": data.get("type", data.get("breakerType")),
            "breaker_rating": data.get("rating"),
            "breaker_poles": data.get("poles"),
            "breaker_rcd": _coerce_bool(data.get("rcd")),
            "breaker_rcd_sensitivity": data.get("rcdSensitivity"),
            "timestamp": datetime.utcnow().isoformat(),
        },
    })

    logger.info(
        "[Breaker] cabinet=%s socket=%s(%d) state=%s cause=%s",
        cabinet_id, socket_name, socket_id, breaker_state, trip_cause,
    )


async def _handle_event_breaker_tripped(
    db, pedestal_id: int, outlet_id: str, data: dict,
):
    """v3.8 — process a `BreakerTripped` event on opta/events.

    Steps:
      1. Resolve socket_id from outlet_id ("Q1" → 1).
      2. Append a `breaker_events` row with event_type="tripped".
      3. Broadcast `breaker_alarm` WS event for the dashboard banner + Notification.

    v3.30 — the NUC NO LONGER stops the session on a breaker trip. A tripped
    breaker has already physically cut the socket; the NUC's job is to REPORT
    (audit row + alarm), not to act. The session is left as-is so the operator
    decides; fault precedence already shows the socket as faulted on the UI.
    """
    from ..models.breaker_event import BreakerEvent

    socket_id  = _socket_name_to_id(outlet_id) if outlet_id else 0
    breaker    = data.get("breaker", {}) or {}
    trip_cause = breaker.get("tripCause")
    current_at_trip_raw = breaker.get("currentAtTrip")
    try:
        current_at_trip = float(current_at_trip_raw) if current_at_trip_raw is not None else None
    except (TypeError, ValueError):
        current_at_trip = None
    occurred_at_str = data.get("occurredAt")

    # 1. Audit log row.
    evt = BreakerEvent(
        pedestal_id=pedestal_id,
        socket_id=socket_id,
        event_type="tripped",
        timestamp=datetime.utcnow(),
        trip_cause=trip_cause,
        current_at_trip=current_at_trip,
        reset_initiated_by=None,
        raw_payload=json.dumps(data),
    )
    db.add(evt)
    db.commit()

    # 2. Persistent dashboard alarm — survives page navigation via Zustand +
    # sessionStorage ack on the frontend. Admin clients also get a Browser
    # Notification (useWebSocket handler).
    await ws_manager.broadcast({
        "event": "breaker_alarm",
        "data": {
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "trip_cause": trip_cause,
            "current_at_trip": current_at_trip,
            "severity": "HIGH",
            "occurred_at": occurred_at_str,
            "timestamp": datetime.utcnow().isoformat(),
        },
    })

    _hw_error(
        f"pedestal_{pedestal_id}",
        f"Breaker tripped on socket Q{socket_id} (cause={trip_cause})",
        details=json.dumps(data),
    )
    logger.warning(
        "[Breaker] TRIPPED pedestal=%d socket=%d cause=%s current=%s",
        pedestal_id, socket_id, trip_cause, current_at_trip,
    )


# ── v3.11 — Hardware config + live meter telemetry ──────────────────────────

# Hysteresis to avoid threshold-edge alarm chatter (D3). Only resolve a
# warning/critical alarm when load drops this many percentage points BELOW
# the threshold value.
_LOAD_HYSTERESIS_PCT = 2.0


def _classify_load(pct: float, prev_status: str, warn: int, crit: int) -> str:
    """Bucket a load percentage into normal | warning | critical with
    hysteresis on the resolve direction. Going UP into a state crosses the
    bare threshold; coming DOWN out of it requires `threshold - hysteresis`."""
    crit_in = float(crit)
    warn_in = float(warn)
    crit_out = crit_in - _LOAD_HYSTERESIS_PCT
    warn_out = warn_in - _LOAD_HYSTERESIS_PCT

    if prev_status == "critical":
        if pct >= crit_out:
            return "critical"
        if pct >= warn_out:
            return "warning"
        return "normal"
    if prev_status == "warning":
        if pct >= crit_in:
            return "critical"
        if pct >= warn_out:
            return "warning"
        return "normal"
    # prev_status in ("normal", "unknown") — bare upward thresholds.
    if pct >= crit_in:
        return "critical"
    if pct >= warn_in:
        return "warning"
    return "normal"


def _recover_truncated_hwconfig(payload: str) -> tuple[dict, int] | None:
    """B1 (v3.21) — best-effort recovery of a truncated opta/config/hardware payload.

    The Opta firmware (>=2.4.0, still present in 2.5.0) truncates this message at
    ~502 bytes, severing the trailing `valves` array. The `sockets` array always
    appears before `valves` and is complete within the limit, so we extract and
    parse only the `sockets` array (plus cabinetId / firmwareVersion from the
    intact prefix).

    Returns (recovered_dict, bytes_dropped) on success, or None if even the
    `sockets` array cannot be recovered. `bytes_dropped` is the length of the
    received-but-unusable tail after the sockets array (the truncated `valves`
    portion). Never raises.
    """
    try:
        key = payload.find('"sockets"')
        if key == -1:
            return None
        open_idx = payload.find('[', key)
        if open_idx == -1:
            return None

        # Bracket-match the sockets array, ignoring brackets inside JSON strings.
        depth = 0
        in_str = False
        escaped = False
        end_idx = -1
        for i in range(open_idx, len(payload)):
            ch = payload[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end_idx = i
                    break

        if end_idx == -1:
            return None  # sockets array itself is truncated — unrecoverable

        sockets = json.loads(payload[open_idx:end_idx + 1])
        if not isinstance(sockets, list):
            return None

        # Recover identity fields from the intact prefix (best-effort).
        data: dict = {"sockets": sockets}
        m_cab = re.search(r'"cabinetId"\s*:\s*"([^"]*)"', payload[:open_idx])
        if m_cab:
            data["cabinetId"] = m_cab.group(1)
        m_fw = re.search(r'"firmwareVersion"\s*:\s*"([^"]*)"', payload[:open_idx])
        if m_fw:
            data["firmwareVersion"] = m_fw.group(1)

        bytes_dropped = len(payload) - (end_idx + 1)
        return data, bytes_dropped
    except Exception:
        return None


async def _handle_opta_hardware_config(payload: str) -> None:
    """v3.11 — opta/config/hardware

    One-shot per cabinet: lists meter type, phases, ratedAmps, modbusAddress
    per socket plus a `valves` array we currently stash but do not yet use
    (placeholder for a future feature). Same `no-overwrite-with-null` rule
    as v3.8 breaker metadata — a missing key in a subsequent message
    preserves the previous value (D12).
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        # B1 (v3.21) — tolerant recovery for the firmware's 502-byte truncation.
        recovered = _recover_truncated_hwconfig(payload)
        if recovered is None:
            logger.warning(
                "[HwConfig] Bad payload (unrecoverable — sockets array not parseable): %s", e
            )
            return
        data, bytes_dropped = recovered
        logger.warning(
            "[HwConfig] Truncated payload recovered — parsed %d socket(s); valves data NOT "
            "recovered. Received %d bytes, dropped %d truncated byte(s) after the sockets array "
            "(Opta MQTT publish buffer too small). Underlying JSON error: %s",
            len(data.get("sockets", [])), len(payload), bytes_dropped, e,
        )

    cabinet_id = data.get("cabinetId", "") or _opta_cached_cabinet_id
    if not cabinet_id:
        logger.warning("[HwConfig] Missing cabinetId; ignoring")
        return

    sockets = data.get("sockets") or []
    if not isinstance(sockets, list):
        logger.warning("[HwConfig] sockets field is not a list; ignoring")
        return

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
        if pedestal_id is None:
            logger.warning("[HwConfig] could not resolve cabinet %s", cabinet_id)
            return

        from ..models.socket_config import SocketConfig
        applied_sockets: list[dict] = []

        for entry in sockets:
            if not isinstance(entry, dict):
                continue
            sock_name = entry.get("socketId")
            if not sock_name:
                continue
            try:
                socket_id = _socket_name_to_id(sock_name)
            except Exception:
                continue

            cfg = db.query(SocketConfig).filter(
                SocketConfig.pedestal_id == pedestal_id,
                SocketConfig.socket_id == socket_id,
            ).first()
            if cfg is None:
                cfg = SocketConfig(
                    pedestal_id=pedestal_id,
                    socket_id=socket_id,
                    auto_activate=True,
                )
                db.add(cfg)
                db.flush()

            # No-overwrite-with-null rule (D12). A field appearing as `null`
            # in the payload IS treated as a write — it's an explicit "the
            # firmware says this is unknown now". Only an *absent* key is
            # preserved.
            if "meterType" in entry:
                cfg.meter_type = entry["meterType"]
            if "phases" in entry:
                cfg.phases = entry["phases"]
            if "ratedAmps" in entry:
                try:
                    cfg.rated_amps = float(entry["ratedAmps"]) if entry["ratedAmps"] is not None else None
                except (TypeError, ValueError):
                    pass
            if "modbusAddress" in entry:
                cfg.modbus_address = entry["modbusAddress"]

            cfg.hw_config_received_at = datetime.utcnow()

            applied_sockets.append({
                "socket_id": socket_id,
                "socket_name": sock_name,
                "meter_type": cfg.meter_type,
                "phases": cfg.phases,
                "rated_amps": cfg.rated_amps,
                "modbus_address": cfg.modbus_address,
                "hw_config_received_at": cfg.hw_config_received_at.isoformat(),
            })

        db.commit()
    finally:
        db.close()

    logger.info(
        "[HwConfig] cabinet=%s pedestal=%d sockets=%d firmware=%s",
        cabinet_id, pedestal_id, len(applied_sockets), data.get("firmwareVersion", "?"),
    )

    await ws_manager.broadcast({
        "event": "hardware_config_updated",
        "data": {
            "pedestal_id": pedestal_id,
            "cabinet_id": cabinet_id,
            "firmware_version": data.get("firmwareVersion"),
            "sockets": applied_sockets,
            "valves": data.get("valves", []),
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


def _sanity_clamp_power_kw(
    reported_kw, *, voltage, current, power_factor, is_three_phase: bool, socket_name: str,
):
    """B4 (v3.21) — sanity-clamp the firmware's reported powerKw for DISPLAY/audit.

    Computes expected kW from V and I (D3: power factor is applied only for the
    three-phase formula, not single-phase). If the reported value exceeds the
    computed value by more than 50x, logs a warning with both figures and
    returns the computed value as the operational figure; otherwise returns the
    reported value unchanged. When voltage or current is zero/missing the check
    is skipped and the reported value is returned as-is.

    Operational decisions are unaffected: overload uses current (amps) and
    billing uses energy_kwh — this only corrects the displayed instantaneous
    power and provides a clamped/raw audit pair.
    """
    if reported_kw is None:
        return None
    try:
        v = float(voltage) if voltage is not None else 0.0
        i = float(current) if current is not None else 0.0
        rep = float(reported_kw)
    except (TypeError, ValueError):
        return reported_kw

    if v == 0.0 or i == 0.0:
        return reported_kw  # cannot compute an expected value — trust firmware

    if is_three_phase:
        try:
            pf = float(power_factor) if power_factor not in (None, "") else 0.0
        except (TypeError, ValueError):
            pf = 0.0
        computed = v * i * pf * 0.001
    else:
        computed = v * i * 0.001

    if computed > 0.0 and rep > computed * 50.0:
        logger.warning(
            "[Meter] %s powerKw sanity clamp fired: reported=%.3f kW computed=%.3f kW "
            "(>50x) — using computed value for display/audit (raw value preserved)",
            socket_name, rep, computed,
        )
        return computed
    return reported_kw


async def _handle_opta_meter_telemetry(socket_name: str, payload: str) -> None:
    """v3.11 — opta/meters/{socketId}/telemetry (every 5 s).

    Parses single- or three-phase payload generically based on which fields
    are present (D5). Stores live values; computes load_pct using the
    bottleneck-phase formula for 3-phase sockets (D2, electrically correct).
    Manages the alarm state machine (D4) with 2 % hysteresis on resolve (D3).
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        logger.warning("[Meter] bad telemetry on %s: %s", socket_name, e)
        return

    cabinet_id = data.get("cabinetId", "") or _opta_cached_cabinet_id
    if not cabinet_id:
        return

    try:
        socket_id = _socket_name_to_id(socket_name)
    except Exception:
        return

    # Detect phasing from which fields are present (no hardcoded socket id).
    is_three_phase = "currentAmpsTotal" in data
    is_single_phase = "currentAmps" in data and not is_three_phase
    if not is_three_phase and not is_single_phase:
        logger.warning("[Meter] %s payload has neither currentAmps nor currentAmpsTotal; skipping",
                       socket_name)
        return

    db = SessionLocal()
    try:
        pedestal_id = _cabinet_to_pedestal_id(db, cabinet_id)
        if pedestal_id is None:
            return

        from ..models.socket_config import SocketConfig
        from ..models.meter_load_alarm import MeterLoadAlarm

        cfg = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == pedestal_id,
            SocketConfig.socket_id == socket_id,
        ).first()
        if cfg is None:
            cfg = SocketConfig(pedestal_id=pedestal_id, socket_id=socket_id, auto_activate=True)
            db.add(cfg)
            db.flush()

        # Always store the raw live readings (D5). B4 (v3.21): also store the raw
        # reported power in meter_power_kw_raw and a sanity-clamped operational
        # value in meter_power_kw (display/audit pair).
        if is_single_phase:
            v_single   = data.get("voltageV")
            i_single   = data.get("currentAmps")
            reported_kw = data.get("powerKw")
            cfg.meter_current_amps  = i_single
            cfg.meter_voltage_v     = v_single
            cfg.meter_power_factor  = data.get("powerFactor")
            cfg.meter_energy_kwh    = data.get("energyKwh")
            cfg.meter_frequency_hz  = data.get("frequency")
            cfg.meter_power_kw_raw  = reported_kw
            cfg.meter_power_kw = _sanity_clamp_power_kw(
                reported_kw, voltage=v_single, current=i_single, power_factor=None,
                is_three_phase=False, socket_name=socket_name,
            )
        else:
            i_total     = data.get("currentAmpsTotal")
            pf_3ph      = data.get("powerFactor")
            reported_kw = data.get("powerKwTotal")
            cfg.meter_current_amps  = i_total
            cfg.meter_current_l1    = data.get("currentAmpsL1")
            cfg.meter_current_l2    = data.get("currentAmpsL2")
            cfg.meter_current_l3    = data.get("currentAmpsL3")
            cfg.meter_voltage_l1    = data.get("voltageL1")
            cfg.meter_voltage_l2    = data.get("voltageL2")
            cfg.meter_voltage_l3    = data.get("voltageL3")
            cfg.meter_power_factor  = pf_3ph
            cfg.meter_energy_kwh    = data.get("energyKwh")
            cfg.meter_frequency_hz  = data.get("frequency")
            # `meter_voltage_v` aggregate stays null for 3-phase rows.
            # D3 — three-phase expected power uses (vL1+vL2+vL3)/3 × I_total × PF.
            _vs = [x for x in (data.get("voltageL1"), data.get("voltageL2"),
                               data.get("voltageL3")) if x is not None]
            _avg_v = None
            if _vs:
                try:
                    _avg_v = sum(float(x) for x in _vs) / 3.0
                except (TypeError, ValueError):
                    _avg_v = None
            cfg.meter_power_kw_raw  = reported_kw
            cfg.meter_power_kw = _sanity_clamp_power_kw(
                reported_kw, voltage=_avg_v, current=i_total, power_factor=pf_3ph,
                is_three_phase=True, socket_name=socket_name,
            )
        cfg.meter_load_updated_at = datetime.utcnow()

        # Load calculation requires rated_amps from hardware config (D5).
        rated = cfg.rated_amps
        if rated is None or rated <= 0:
            cfg.meter_load_status = "unknown"
            cfg.meter_load_pct = None
            db.commit()
            logger.warning(
                "[Meter] telemetry received for %s but no hardware config available — skipping load calculation",
                socket_name,
            )
            await ws_manager.broadcast({
                "event": "meter_telemetry_received",
                "data": {
                    "pedestal_id": pedestal_id,
                    "socket_id": socket_id,
                    "phases": cfg.phases,
                    "load_status": "unknown",
                    "current_amps": cfg.meter_current_amps,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            })
            return

        # D2 — bottleneck phase for 3-phase, simple ratio for 1-phase.
        if is_three_phase:
            phase_currents = [
                v for v in (cfg.meter_current_l1, cfg.meter_current_l2, cfg.meter_current_l3)
                if v is not None
            ]
            current_for_load = max(phase_currents) if phase_currents else (cfg.meter_current_amps or 0.0)
        else:
            current_for_load = cfg.meter_current_amps or 0.0

        load_pct = (float(current_for_load) / float(rated)) * 100.0
        cfg.meter_load_pct = load_pct

        prev_status = cfg.meter_load_status or "unknown"
        warn = int(cfg.load_warning_threshold_pct or 60)
        crit = int(cfg.load_critical_threshold_pct or 80)

        # Common state used by every branch below.
        broadcasts: list[dict] = []
        auto_stop_session_id: int | None = None
        snapshot_meter_type = cfg.meter_type
        snapshot_phases = cfg.phases or (3 if is_three_phase else 1)
        snapshot_rated = float(rated)

        # v3.12 — Auto-stop is terminal (D1). Once the latch is set, status
        # stays `auto_stop` and the existing state machine is bypassed until
        # an admin acknowledges via the dedicated endpoint. We still update
        # the live readings (already done above) and emit the per-tick
        # telemetry broadcast at the bottom of the function so the dashboard
        # sees current load_pct even while suspended.
        # v3.32 — overload (>=90%) is a NON-terminal alarm state. Previously it
        # latched terminally ("auto_stop" stayed until an operator ack), which
        # left the dashboard showing "AUTO-STOP — overload protection" long
        # after the load had dropped (e.g. a socket at 10% still flagged). It
        # now raises an alarm on the way UP and auto-resolves on the way DOWN,
        # exactly like warning/critical. The NUC still never shuts the socket
        # down (v3.30 — alarm-only); the Opta/breaker owns protection.
        if load_pct >= 90.0:
            new_status = "auto_stop"
            cfg.meter_load_status = "auto_stop"
            if prev_status != "auto_stop":
                # Transition INTO overload — raise one alarm + set the
                # "needs ack" flag; supersede any open warning/critical rows.
                cfg.auto_stop_pending_ack = True
                now = datetime.utcnow()
                for r in db.query(MeterLoadAlarm).filter(
                    MeterLoadAlarm.pedestal_id == pedestal_id,
                    MeterLoadAlarm.socket_id == socket_id,
                    MeterLoadAlarm.resolved_at.is_(None),
                    MeterLoadAlarm.alarm_type.in_(["warning", "critical"]),
                ).all():
                    r.resolved_at = now
                    r.resolved_by = "overload-supersedes"
                db.add(MeterLoadAlarm(
                    pedestal_id=pedestal_id,
                    socket_id=socket_id,
                    alarm_type="auto_stop",
                    current_amps=float(current_for_load),
                    rated_amps=snapshot_rated,
                    load_pct=load_pct,
                    phases=snapshot_phases,
                    meter_type=snapshot_meter_type,
                    triggered_at=datetime.utcnow(),
                ))
                broadcasts.append({"event": "meter_load_auto_stop"})
                logger.warning(
                    "[Overload] pedestal=%d socket=%s current=%.2fA rated=%.2fA load_pct=%.1f%%",
                    pedestal_id, socket_name,
                    float(current_for_load), snapshot_rated, load_pct,
                )
            # else: still in overload — keep status, do not re-fire the alarm.

        else:
            # 60/80% state machine. v3.32 — also handles DESCENT from overload:
            # treat a prior "auto_stop" like "critical" so hysteresis behaves,
            # clear the latch, and resolve the open overload alarm.
            effective_prev = "critical" if prev_status == "auto_stop" else prev_status
            new_status = _classify_load(load_pct, effective_prev, warn, crit)
            cfg.meter_load_status = new_status

            def _resolve_open(reason: str) -> int:
                """Close every open MeterLoadAlarm row for this (pedestal,socket).
                Returns the number resolved."""
                now = datetime.utcnow()
                opens = db.query(MeterLoadAlarm).filter(
                    MeterLoadAlarm.pedestal_id == pedestal_id,
                    MeterLoadAlarm.socket_id == socket_id,
                    MeterLoadAlarm.resolved_at.is_(None),
                ).all()
                for r in opens:
                    r.resolved_at = now
                    r.resolved_by = reason
                return len(opens)

            def _open_row(level: str) -> MeterLoadAlarm:
                row = MeterLoadAlarm(
                    pedestal_id=pedestal_id,
                    socket_id=socket_id,
                    alarm_type=level,
                    current_amps=float(current_for_load),
                    rated_amps=snapshot_rated,
                    load_pct=load_pct,
                    phases=snapshot_phases,
                    meter_type=snapshot_meter_type,
                    triggered_at=datetime.utcnow(),
                )
                db.add(row)
                return row

            # v3.32 — descent from overload: clear the latch, resolve the open
            # overload alarm, and open the alarm matching the now-current load.
            if prev_status == "auto_stop":
                cfg.auto_stop_pending_ack = False
                _resolve_open("overload-cleared")
                if new_status == "critical":
                    _open_row("critical")
                    broadcasts.append({"event": "meter_load_critical"})
                elif new_status == "warning":
                    _open_row("warning")
                    broadcasts.append({"event": "meter_load_warning"})
                else:
                    broadcasts.append({"event": "meter_load_resolved"})

            # State-machine matrix (uses effective_prev so a descent from
            # overload is handled above, not here).
            elif effective_prev != new_status:
                if new_status == "warning" and effective_prev in ("normal", "unknown"):
                    _open_row("warning")
                    broadcasts.append({"event": "meter_load_warning"})
                elif new_status == "critical" and effective_prev in ("normal", "unknown"):
                    _open_row("critical")
                    broadcasts.append({"event": "meter_load_critical"})
                elif new_status == "critical" and effective_prev == "warning":
                    _resolve_open("auto-upgrade")
                    _open_row("critical")
                    broadcasts.append({"event": "meter_load_critical"})
                elif new_status == "warning" and effective_prev == "critical":
                    _resolve_open("auto-downgrade")
                    _open_row("warning")
                    broadcasts.append({"event": "meter_load_warning"})
                elif new_status == "normal":
                    resolved = _resolve_open("auto-resolve")
                    if resolved:
                        broadcasts.append({"event": "meter_load_resolved"})

        # v3.32 — integrate session energy from power × time on every meter tick.
        _integrate_session_energy(db, pedestal_id, socket_id, cfg.meter_power_kw)

        db.commit()
    finally:
        db.close()

    # Build common WS payload.
    payload_data = {
        "pedestal_id": pedestal_id,
        "socket_id": socket_id,
        "current_amps": float(current_for_load),
        "rated_amps": float(rated),
        "load_pct": load_pct,
        "phases": snapshot_phases,
        "meter_type": snapshot_meter_type,
        "load_status": new_status,
        "timestamp": datetime.utcnow().isoformat(),
    }
    if is_three_phase:
        payload_data["current_l1"] = data.get("currentAmpsL1")
        payload_data["current_l2"] = data.get("currentAmpsL2")
        payload_data["current_l3"] = data.get("currentAmpsL3")

    for b in broadcasts:
        evt = b["event"]
        # session_completed has its own pre-built data dict — broadcast as-is.
        if evt == "session_completed":
            await ws_manager.broadcast(b)
            continue
        if evt == "meter_load_critical":
            payload_data["severity"] = "CRITICAL"
        elif evt == "meter_load_warning":
            payload_data["severity"] = "WARNING"
        elif evt == "meter_load_auto_stop":
            # v3.30 — overload alarm severity. session_id is None: the NUC no
            # longer ends a session on overload (alarm-only), so there is no
            # ended-session to deep-link to.
            payload_data["severity"] = "AUTO_STOP"
            payload_data["session_id"] = auto_stop_session_id
        await ws_manager.broadcast({"event": evt, "data": dict(payload_data)})

    # Always emit a low-volume telemetry tick so the dashboard sees live load_pct.
    await ws_manager.broadcast({
        "event": "meter_telemetry_received",
        "data": payload_data,
    })

    if broadcasts:
        logger.info(
            "[Meter] pedestal=%d socket=%d load_pct=%.1f%% prev=%s new=%s rated=%.1fA",
            pedestal_id, socket_id, load_pct, prev_status, new_status, rated,
        )


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

    # v3.9 — expose per-valve water sensor status so post-diagnostic auto-open
    # can fire selectively on only the valves that passed.
    per_valve_ok: dict[int, bool] = {}
    for w in water_arr:
        vid = _water_name_to_id(w.get("id", ""))
        ok = (w.get("hw", "off") != "fault")
        sensors[f"water_v{vid}"] = "ok" if ok else "fail"
        per_valve_ok[vid] = ok

    # B3b (v3.21) — Opta cabinets have NO temperature/moisture/camera sensors.
    # Report them as "missing" (not present) instead of fabricating an "ok" from
    # MQTT connectivity, which made non-existent sensors show green in the UI.
    sensors["temperature"] = "missing"
    sensors["moisture"] = "missing"
    sensors["camera"] = "missing"

    # Also pass the full raw response for rich display
    sensors["_raw"] = data

    diagnostics_manager.complete_request(pedestal_id, sensors)
    logger.info("[Opta] Diagnostic response for cabinet %s (pedestal %d): power=%s water=%s time=%s",
                cabinet_id, pedestal_id,
                [f"{p['id']}:{p.get('hw','?')}" for p in power_arr],
                [f"{w['id']}:{w.get('hw','?')}" for w in water_arr],
                data.get("time", "?"))

    # v3.28 — plug-state sync. The firmware reports `plugged` per socket in the
    # diagnostic response. Mark a plugged-but-idle electricity socket as
    # `awaiting_activation` so the dashboard Activate button enables even WITHOUT
    # a fresh UserPluggedIn event (e.g. a cable already inserted when Smart Mode
    # was turned on). `awaiting_activation` is exempt from the 15 s pending
    # auto-reject sweep (which targets only legacy "pending").
    for item in power_arr:
        if "plugged" not in item:
            continue   # older firmware without the field → don't touch state
        sid = _socket_name_to_id(item.get("id", "Q1"))
        plugged = bool(item.get("plugged"))
        db = SessionLocal()
        try:
            from ..models.pedestal_config import SocketState
            ss = db.query(SocketState).filter(
                SocketState.pedestal_id == pedestal_id, SocketState.socket_id == sid,
            ).first()
            if ss is None:
                # The cabinet is clearly online (it just answered a diagnostic).
                ss = SocketState(pedestal_id=pedestal_id, socket_id=sid, connected=True)
                db.add(ss)
            active = session_service.get_active_for_socket(
                db, pedestal_id, sid, session_type="electricity")
            has_active = active is not None and active.status == "active"
            if plugged and not has_active:
                if ss.operator_status not in ("pending", "awaiting_activation"):
                    ss.operator_status = "awaiting_activation"
                    ss.operator_status_at = datetime.utcnow()
            elif not plugged and ss.operator_status == "awaiting_activation":
                ss.operator_status = None
                ss.operator_status_at = None
            db.commit()
            display = _compute_socket_display_state(
                db, pedestal_id, sid, raw_state="", hw_status="")
        finally:
            db.close()
        await _broadcast_socket_state(pedestal_id, sid, display, resource="POWER")

    # v3.9 — stamp the last-diagnostic-response timestamp and fire post-diag
    # valve auto-open for each valve that reported ok. Each task is
    # self-contained (own DB session) and runs the full precondition set —
    # auto_activate flag, no-active-session, and 10-min manual-stop cooldown.
    last_diagnostic_ok_at[pedestal_id] = datetime.utcnow()
    for vid, ok in per_valve_ok.items():
        if ok:
            asyncio.create_task(_maybe_auto_open_valve(pedestal_id, vid, cabinet_id))


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
