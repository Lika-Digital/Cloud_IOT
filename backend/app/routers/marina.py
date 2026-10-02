"""v3.44 — CORE for the marina Monitoring & Control profile.

`GET /api/marina/berths` is the whole L1 dashboard in one call, plus websocket deltas for live
figures. The frontend renders what it is given and computes no status.

SHAPE: ELECTRICITY IS PER BERTH, WATER IS PER PEDESTAL
------------------------------------------------------
Settled with the Krk layout, 2026-10-01: one pedestal covers 4 berths for electricity, one
socket each; **water serves a maximum of 2 users at a time via the 2 valves**, and the valves
are not piped to specific berths.

So `berths[].power` exists and `berths[].water` does not. Water is `pedestals[].water_outlets`
— two entries, each showing whoever's session is on it. A per-berth water line would invent a
relationship the plumbing does not have: it would read "Water OFF" on a berth whose occupant is
using the valve at the far end of the cabinet.

NO CUSTOMER NAMES, ANYWHERE
---------------------------
Decided 2026-10-01. The berth number and the vessel photo identify the boat, and staff standing
on the pontoon can see it. A name on a wall-mounted dashboard is a privacy exposure with no
operational payoff. `nfc_user_id` is likewise absent — it is an ERP identifier, not something
marina staff need. There is no field to omit later; there is no field.
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..auth.user_database import get_user_db
from ..auth.dependencies import require_admin, require_any_role
from ..auth.models import User
from ..models.berth_assignment import BerthAssignment
from ..models.pedestal_config import PedestalConfig, SocketState
from ..models.session import Session
from ..models.socket_config import SocketConfig
from ..models.valve_config import ValveConfig
from ..services import marina_status as ms
from ..services.marina_status import BerthFacts
from ..time_utils import iso_z

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/marina", tags=["marina"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _heartbeat_age(pedestal_id: int) -> float | None:
    """Seconds since this cabinet was last heard from, from the IN-MEMORY map.

    Never from `PedestalConfig.opta_connected` or a stored `last_heartbeat`: a retained
    `opta/status` replays to every new subscriber, so a cabinet dead for weeks looks healthy
    in the database after a restart.
    """
    from ..services.mqtt_handlers import last_heartbeat
    return ms.heartbeat_age(last_heartbeat.get(pedestal_id))


def _berths_for(user_db: DBSession, pedestal_id: int) -> list:
    from ..auth.berth_models import Berth
    return (
        user_db.query(Berth)
        .filter(Berth.pedestal_id == pedestal_id)
        .order_by(Berth.berth_number.is_(None), Berth.berth_number, Berth.id)
        .all()
    )


def _active_session(db: DBSession, pedestal_id: int, outlet_id: int, session_type: str):
    """The active session on one outlet, of one kind.

    The type filter is not optional: V1 and Q1 are both `socket_id=1`, so an unfiltered lookup
    reports the wrong outlet's session (`docs/architecture.md §2`).
    """
    return (
        db.query(Session)
        .filter(
            Session.pedestal_id == pedestal_id,
            Session.socket_id == outlet_id,
            Session.type == session_type,
            Session.status == "active",
        )
        .first()
    )


def _power_block(db: DBSession, pedestal_id: int, socket_id: Optional[int],
                 *, controllable: bool) -> dict:
    """One berth's electricity facility.

    `available` means "a control may be rendered". False renders a sentence and NO control
    element in the DOM — not a disabled button. Two distinct reasons produce False, and the
    caller tells them apart with `unavailable_reason`, because "this berth has no socket" and
    "this pedestal is switching for itself" are different sentences.
    """
    if socket_id is None:
        return {
            "outlet": None, "on": False, "state": "unknown",
            "watts": None, "unit": "W",
            "available": False, "unavailable_reason": "no_socket",
        }

    cfg = (
        db.query(SocketConfig)
        .filter(SocketConfig.pedestal_id == pedestal_id, SocketConfig.socket_id == socket_id)
        .first()
    )
    state_row = (
        db.query(SocketState)
        .filter(SocketState.pedestal_id == pedestal_id, SocketState.socket_id == socket_id)
        .first()
    )
    active = _active_session(db, pedestal_id, socket_id, "electricity")

    if active is not None:
        state = "active"
    elif state_row is not None and state_row.connected:
        state = "pending"
    else:
        state = "idle"

    # Live power only while a session runs. A leftover figure on an idle socket reads as
    # "something is drawing here", which is the opposite of true.
    watts = None
    if active is not None and cfg is not None and cfg.meter_power_kw is not None:
        watts = round(cfg.meter_power_kw * 1000.0)

    return {
        "outlet": f"Q{socket_id}",
        "on": active is not None,
        "state": state,
        "watts": watts,
        "unit": "W",
        "available": controllable,
        "unavailable_reason": None if controllable else "standalone",
    }


def _water_outlets(db: DBSession, pedestal_id: int, *, controllable: bool) -> list[dict]:
    """The cabinet's water outlets — a pool, not a per-berth facility.

    Each entry reports its own state from `valve_configs`, which the MQTT handler persists
    from `opta/water/V{n}/status`. `unknown` when missing or older than 60 s: a stored state
    is only as good as its age, and reporting the last thing a valve said before its cabinet
    went quiet would tell a customer the outlet is free.

    There is deliberately no `pending`. That state means "physically connected, awaiting
    activation" and comes from the socket's plug-in detection; the firmware has no valve
    analogue, so it does not exist rather than being unread.
    """
    rows = (
        db.query(ValveConfig)
        .filter(ValveConfig.pedestal_id == pedestal_id)
        .order_by(ValveConfig.valve_id)
        .all()
    )
    out: list[dict] = []
    for r in rows:
        active = _active_session(db, pedestal_id, r.valve_id, "water")
        if active is not None:
            state = "active"
        elif ms.outlet_state_is_stale(r.state_updated_at) or not r.last_state:
            state = "unknown"
        else:
            state = r.last_state

        out.append({
            "outlet": f"V{r.valve_id}",
            "on": active is not None,
            "state": state,
            "litres_per_min": None,          # live, arrives over the websocket
            "unit": "L/min",
            "rated_liters_per_min": r.rated_liters_per_min,
            "in_use": active is not None,
            "available": controllable,
            "unavailable_reason": None if controllable else "standalone",
        })
    return out


def _guard_block(pedestal_id: int) -> dict:
    """Guard, mapped to the four words the marina sees.

    `UNAVAILABLE` must never render as "Guard off". Off is a decision someone made;
    unavailable is a fault. The whole liveness design exists to keep those apart, and
    collapsing them here would throw it away at the last step.
    """
    try:
        from ..services.guard_state import current_guard_state   # type: ignore
        raw = current_guard_state(pedestal_id)
    except Exception:
        # No guard wiring for this pedestal yet. "unavailable", never "off".
        return {"state": "unavailable", "sentence": "Guard unavailable", "scope": "pedestal"}

    s = (raw or {}).get("state", "UNAVAILABLE")
    limited = bool((raw or {}).get("limited_visibility"))

    if s in ("ARMED", "ALARM", "RECORDING", "ARMING"):
        if limited:
            return {"state": "paused", "sentence": "Guard paused — too dark to see",
                    "scope": "pedestal"}
        return {"state": "on", "sentence": "Guard on", "scope": "pedestal"}
    if s == "OFF":
        return {"state": "off", "sentence": "Guard off", "scope": "pedestal"}
    if s in ("SUSPENDED_CPU", "NO_DISK"):
        reason = "the pedestal is busy" if s == "SUSPENDED_CPU" else "there is no space to record"
        return {"state": "paused", "sentence": f"Guard paused — {reason}", "scope": "pedestal"}
    return {"state": "unavailable", "sentence": "Guard unavailable", "scope": "pedestal"}


def _berth_payload(db: DBSession, berth, assignment, *, facts_base: BerthFacts,
                   controllable: bool) -> dict:
    socket_id = assignment.socket_id if assignment is not None else None

    cfg = None
    if socket_id is not None:
        cfg = (
            db.query(SocketConfig)
            .filter(SocketConfig.pedestal_id == berth.pedestal_id,
                    SocketConfig.socket_id == socket_id)
            .first()
        )

    match_configured = bool(getattr(berth, "reference_image", None))
    facts = BerthFacts(
        heartbeat_age_s=facts_base.heartbeat_age_s,
        smart_mode=facts_base.smart_mode,
        outlet_state_unknown=False,
        moisture_alarm=facts_base.moisture_alarm,
        temperature_alarm=facts_base.temperature_alarm,
        auto_stop_pending_ack=bool(cfg is not None and cfg.auto_stop_pending_ack),
        breaker_tripped=facts_base.breaker_tripped,
        guard_alarm_unreviewed=facts_base.guard_alarm_unreviewed,
        consumption_unmeasured=_has_unmeasured_session(db, berth.pedestal_id, socket_id),
        vessel_mismatch=(getattr(berth, "state_code", 0) == 2),
        vessel_match_configured=match_configured,
    )

    payload = {
        "berth_id": berth.id,
        "berth_number": berth.berth_number,
        "power": _power_block(db, berth.pedestal_id, socket_id, controllable=controllable),
        "occupied": bool(getattr(berth, "occupied_bit", 0)),
        # Distinguished from `occupied` so the UI can render "we do not know" rather than
        # "empty". Zero and unknown are different values (engineering note 8).
        "occupied_known": getattr(berth, "last_analyzed", None) is not None,
        "vessel_matches": bool(getattr(berth, "match_ok_bit", 0)) if match_configured else None,
        "vessel_match_configured": match_configured,
        "alarm_count": facts_base.alarm_count if hasattr(facts_base, "alarm_count") else 0,
    }
    payload.update(ms.as_payload(ms.reduce(facts)))
    return payload


def _has_unmeasured_session(db: DBSession, pedestal_id: int,
                            socket_id: Optional[int]) -> bool:
    """A completed session at this berth whose consumption could not be measured.

    `consumption_source == "unknown"` means the register could not be read at one end or the
    other. We report the figure and the ERP bills it, so an unknown leaves the ERP nothing to
    charge — and without this nobody on our side would know it happened.
    """
    if socket_id is None:
        return False
    row = (
        db.query(Session)
        .filter(
            Session.pedestal_id == pedestal_id,
            Session.socket_id == socket_id,
            Session.type == "electricity",
            Session.status == "completed",
            Session.consumption_source == "unknown",
        )
        .order_by(Session.id.desc())
        .first()
    )
    return row is not None


# ── CORE ──────────────────────────────────────────────────────────────────────

@router.get("/berths")
def marina_berths(db: DBSession = Depends(get_db),
                  user_db: DBSession = Depends(get_user_db),
                  _: User = Depends(require_any_role)):
    """The L1 dashboard in one call.

    `require_any_role` — this is operations. Marina staff answering "what is wrong at berth 3"
    is exactly the audience, and every other read in the system is gated the same way.
    """
    from ..models.active_alarm import ActiveAlarm

    pedestals = db.query(PedestalConfig).order_by(PedestalConfig.pedestal_id).all()
    out = []

    for cfg in pedestals:
        pid = cfg.pedestal_id
        age = _heartbeat_age(pid)
        reachable = age is not None and age <= ms.COMM_LOSS_TIMEOUT_S
        smart = bool(cfg.smart_mode)
        # Controls render only when the NUC can actually act. Both halves matter: an
        # unreachable cabinet cannot be commanded, and in non-smart mode the Opta is
        # switching for itself.
        controllable = reachable and smart

        # Unresolved only. An alarm with `resolved_at` set has returned to normal on its
        # own and is history, not a condition.
        alarms = (
            db.query(ActiveAlarm)
            .filter(ActiveAlarm.pedestal_id == pid, ActiveAlarm.resolved_at.is_(None))
            .all()
        )
        alarm_types = {a.alarm_type for a in alarms}
        # "Unreviewed" means nobody has acknowledged it yet. Presence alone would keep the row
        # shouting after a human had already looked.
        unreviewed_types = {a.alarm_type for a in alarms if a.status == "triggered"}

        facts_base = BerthFacts(
            heartbeat_age_s=age,
            smart_mode=smart,
            moisture_alarm=any("moisture" in t or "leak" in t for t in alarm_types),
            temperature_alarm=any("temp" in t for t in alarm_types),
            breaker_tripped=any("breaker" in t for t in alarm_types),
            guard_alarm_unreviewed=any(
                "guard" in t or "unauthorized" in t for t in unreviewed_types
            ),
        )
        facts_base.alarm_count = len(alarms)   # type: ignore[attr-defined]

        assignments = {
            a.berth_id: a
            for a in db.query(BerthAssignment)
            .filter(BerthAssignment.pedestal_id == pid).all()
        }

        berths = [
            _berth_payload(db, b, assignments.get(b.id),
                           facts_base=facts_base, controllable=controllable)
            for b in _berths_for(user_db, pid)
        ]

        out.append({
            "pedestal_id": pid,
            "cabinet_id": cfg.opta_client_id,
            "dock": cfg.dock_id,
            "reachable": reachable,
            "smart_mode": smart,
            "berths": berths,
            # Pedestal-level, not per berth: the valves are a pool of two, not piped to
            # specific berths. See the module docstring.
            "water_outlets": _water_outlets(db, pid, controllable=controllable),
            "light": {
                "on": bool(getattr(cfg, "led_on", False)),
                "scope": "pedestal",
                "available": controllable,
                "unavailable_reason": None if controllable else "standalone",
            },
            "guard": _guard_block(pid),
            "alarm_count": len(alarms),
        })

    return {"pedestals": out}


@router.get("/berths/{berth_id}")
def marina_berth_detail(berth_id: int,
                        db: DBSession = Depends(get_db),
                        user_db: DBSession = Depends(get_user_db),
                        _: User = Depends(require_any_role)):
    """One berth, with the detail L1 deliberately leaves out.

    Adds the socket's own facts from `opta/config/hardware` — rating and phase count, which
    differ per socket on real hardware (Q1 is three-phase 32 A; Q3/Q4 are 16 A) — and the
    month-to-date figures WITH their provenance.
    """
    from ..auth.berth_models import Berth
    from ..models.active_alarm import ActiveAlarm

    berth = user_db.get(Berth, berth_id)
    if berth is None or berth.pedestal_id is None:
        raise HTTPException(status_code=404, detail="Berth not found")

    pid = berth.pedestal_id
    cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
    if cfg is None:
        raise HTTPException(status_code=404, detail="Berth not found")

    age = _heartbeat_age(pid)
    reachable = age is not None and age <= ms.COMM_LOSS_TIMEOUT_S
    smart = bool(cfg.smart_mode)
    controllable = reachable and smart

    assignment = (
        db.query(BerthAssignment)
        .filter(BerthAssignment.pedestal_id == pid, BerthAssignment.berth_id == berth_id)
        .first()
    )

    alarms = (
        db.query(ActiveAlarm)
        .filter(ActiveAlarm.pedestal_id == pid, ActiveAlarm.resolved_at.is_(None))
        .all()
    )
    alarm_types = {a.alarm_type for a in alarms}
    unreviewed_types = {a.alarm_type for a in alarms if a.status == "triggered"}
    facts_base = BerthFacts(
        heartbeat_age_s=age, smart_mode=smart,
        moisture_alarm=any("moisture" in t or "leak" in t for t in alarm_types),
        temperature_alarm=any("temp" in t for t in alarm_types),
        breaker_tripped=any("breaker" in t for t in alarm_types),
        guard_alarm_unreviewed=any(
            "guard" in t or "unauthorized" in t for t in unreviewed_types
        ),
    )
    facts_base.alarm_count = len(alarms)   # type: ignore[attr-defined]

    payload = _berth_payload(db, berth, assignment,
                             facts_base=facts_base, controllable=controllable)

    socket_id = assignment.socket_id if assignment is not None else None
    sc = None
    if socket_id is not None:
        sc = (
            db.query(SocketConfig)
            .filter(SocketConfig.pedestal_id == pid, SocketConfig.socket_id == socket_id)
            .first()
        )

    payload["outlet_spec"] = {
        "outlet": f"Q{socket_id}" if socket_id is not None else None,
        # From the cabinet's own enumeration, never a constant. Null means the cabinet has
        # not published its hardware config — which is different from "16 A".
        "rated_amps": getattr(sc, "rated_amps", None),
        "phases": getattr(sc, "phases", None),
        "meter_type": getattr(sc, "meter_type", None),
    }
    payload["consumption"] = _consumption_summary(db, pid, socket_id)
    payload["reference_image"] = getattr(berth, "reference_image", None)
    payload["cabinet_id"] = cfg.opta_client_id
    payload["pedestal_id"] = pid
    # Per pedestal, not per berth: one camera per cabinet, so the event list is the
    # cabinet's. Saying so prevents attributing a stranger at berth 1 to berth 3.
    payload["guard"] = _guard_block(pid)
    payload["guard_scope_note"] = (
        "Guard covers the whole pedestal, so these events may come from any berth it serves."
    )
    return payload


def _consumption_summary(db: DBSession, pedestal_id: int,
                         socket_id: Optional[int]) -> dict:
    """Month-to-date electricity for one berth, with its provenance.

    Summed from COMPLETED sessions, and the provenance travels with the number. A figure shown
    without it is how the old power-integration workaround survived three months unnoticed.

    `kwh` is None — not 0.0 — when any contributing session is unmeasurable. The sum of a
    partial set is not the total, and reporting it as one is a silent under-report.
    """
    if socket_id is None:
        return {"kwh": None, "source": None, "note": "This berth has no electricity socket."}

    start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = (
        db.query(Session)
        .filter(
            Session.pedestal_id == pedestal_id,
            Session.socket_id == socket_id,
            Session.type == "electricity",
            Session.status == "completed",
            Session.started_at >= start,
        )
        .all()
    )
    if not rows:
        return {"kwh": 0.0, "source": "register", "note": "No sessions this month."}

    sources = {getattr(r, "consumption_source", None) for r in rows}
    if "unknown" in sources or any(r.energy_kwh is None for r in rows):
        return {
            "kwh": None, "source": "unknown",
            "note": "Not measured — at least one session could not be read.",
        }
    total = round(sum(r.energy_kwh or 0.0 for r in rows), 3)
    if "integrated_legacy" in sources:
        return {"kwh": total, "source": "integrated_legacy",
                "note": "Estimated — the meter was unavailable for part of this month."}
    return {"kwh": total, "source": "register", "note": "Meter reading."}


@router.get("/alarms")
def marina_alarms(db: DBSession = Depends(get_db),
                  _: User = Depends(require_any_role)):
    """Cross-pedestal alarm list, in plain sentences.

    A NEW marina-scoped endpoint rather than the admin one re-gated: re-gating would leak
    admin diagnostic detail into this profile by default, and the next field added to the
    admin payload would appear on a marina screen without anyone deciding so.
    """
    from ..models.active_alarm import ActiveAlarm

    rows = (
        db.query(ActiveAlarm)
        .order_by(ActiveAlarm.resolved_at.is_(None).desc(), ActiveAlarm.triggered_at.desc())
        .limit(200)
        .all()
    )
    cabinets = {
        c.pedestal_id: c.opta_client_id
        for c in db.query(PedestalConfig).all()
    }

    out = []
    for a in rows:
        code = _alarm_code_for(a.alarm_type)
        sentence = ms.SENTENCES.get(code, ms.UNRECOGNISED)
        out.append({
            "alarm_id": a.id,
            "pedestal_id": a.pedestal_id,
            "cabinet_id": cabinets.get(a.pedestal_id),
            "status_code": sentence.code,
            # Plain words only. An error code on this screen is the thing the audit called out.
            "sentence": sentence.text or "Something needs checking",
            "severity": getattr(a, "severity", None),
            "raised_at": iso_z(a.triggered_at),
            "resolved_at": iso_z(a.resolved_at) if a.resolved_at else None,
            "active": a.resolved_at is None,
        })
    return {"alarms": out}


def _alarm_code_for(alarm_type: str) -> str:
    """Map a stored alarm type onto the sentence table.

    An unrecognised type falls through to UNRECOGNISED rather than being echoed to the screen.
    Echoing it would put `meter_power_implausible` in front of marina staff.
    """
    t = (alarm_type or "").lower()
    if "moisture" in t or "leak" in t:
        return "water_leak"
    if "temp" in t:
        return "too_hot"
    if "breaker" in t:
        return "breaker_tripped"
    if "overload" in t or "auto_stop" in t:
        return "auto_off_overload"
    if "guard" in t or "person" in t:
        return "guard_unreviewed"
    if "meter" in t or "measure" in t:
        return "measurement_missing"
    return "unrecognised"


# ── Berth assignments (admin — installation) ──────────────────────────────────

@router.get("/berth-assignments/{pedestal_id}")
def get_berth_assignments(pedestal_id: int,
                          db: DBSession = Depends(get_db),
                          _: User = Depends(require_any_role)):
    """Current mapping, for the wizard to pre-fill. Readable by any operator."""
    rows = (
        db.query(BerthAssignment)
        .filter(BerthAssignment.pedestal_id == pedestal_id)
        .order_by(BerthAssignment.socket_id)
        .all()
    )
    return {
        "pedestal_id": pedestal_id,
        "assignments": [
            {
                "berth_id": r.berth_id,
                "socket_id": r.socket_id,
                "assigned_at": iso_z(r.assigned_at),
                "assigned_by": r.assigned_by,
            }
            for r in rows
        ],
    }


@router.put("/berth-assignments/{pedestal_id}")
def put_berth_assignments(pedestal_id: int, body: dict,
                          db: DBSession = Depends(get_db),
                          admin: User = Depends(require_admin)):
    """Replace the mapping for one pedestal. ADMIN ONLY — this is an installation act.

    After one of these, a customer's consumption lands against a different berth. Same tier as
    NFC provisioning and for the same reason, and `assigned_by` records who did it.

    Replace-whole rather than patch-per-row: the invariant being maintained is "these berths,
    these sockets, no socket twice", and that is a property of the SET. A per-row patch can
    pass each individual check and still leave two berths on one socket between two calls.
    """
    from ..services.marina_service import replace_berth_assignments, BerthAssignmentError

    items = body.get("assignments")
    if not isinstance(items, list):
        raise HTTPException(status_code=422, detail="assignments must be a list")
    try:
        saved = replace_berth_assignments(db, pedestal_id, items, assigned_by=admin.email)
    except BerthAssignmentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("[Marina] berth assignments for pedestal=%s replaced by %s (%d rows)",
                pedestal_id, admin.email, len(saved))
    return {"pedestal_id": pedestal_id, "assignments": saved}
