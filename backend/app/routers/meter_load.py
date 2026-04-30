"""v3.11 — internal admin endpoints for socket meter load monitoring.

Five endpoints (plus two alarm-actions per D9):

  GET    /api/pedestals/{pid}/sockets/{sid}/load        — single socket live data
  GET    /api/pedestals/{pid}/load                       — all sockets on pedestal
  PATCH  /api/pedestals/{pid}/sockets/{sid}/load/thresholds
  GET    /api/pedestals/{pid}/load/alarms                — open alarms only
  GET    /api/pedestals/{pid}/sockets/{sid}/load/history — last 50 events
  POST   /api/pedestals/{pid}/load/alarms/{alarm_id}/acknowledge
  POST   /api/pedestals/{pid}/load/alarms/{alarm_id}/resolve

Helpers `serialize_load_state`, `serialize_alarm`, `_get_socket_or_404` are
re-exported to `ext_meter_load_endpoints.py` for the ERP-facing version.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from ..auth.dependencies import require_admin, require_any_role
from ..auth.models import User
from ..database import get_db
from ..models.meter_load_alarm import MeterLoadAlarm
from ..models.pedestal import Pedestal
from ..models.socket_config import SocketConfig
from ..services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pedestals", tags=["meter-load"])


# ── Pydantic ────────────────────────────────────────────────────────────────

class ThresholdsBody(BaseModel):
    warning_threshold_pct: int = Field(..., ge=1, le=99)
    critical_threshold_pct: int = Field(..., ge=1, le=99)


# ── Shared helpers (re-imported by ext_meter_load_endpoints.py) ─────────────

def _get_pedestal_or_404(db: DBSession, pedestal_id: int) -> Pedestal:
    p = db.get(Pedestal, pedestal_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    return p


def _get_socket_or_404(db: DBSession, pedestal_id: int, socket_id: int) -> SocketConfig:
    cfg = db.query(SocketConfig).filter(
        SocketConfig.pedestal_id == pedestal_id,
        SocketConfig.socket_id == socket_id,
    ).first()
    if cfg is None:
        raise HTTPException(status_code=404, detail="Socket not found on this pedestal")
    return cfg


def serialize_load_state(cfg: SocketConfig) -> dict:
    """Render every meter-related field of a SocketConfig row. Per-phase
    fields are only included for 3-phase meters so the JSON shape matches
    what the firmware reported (D2)."""
    base: dict = {
        "pedestal_id": cfg.pedestal_id,
        "socket_id": cfg.socket_id,
        "meter_type": cfg.meter_type,
        "phases": cfg.phases,
        "rated_amps": cfg.rated_amps,
        "modbus_address": cfg.modbus_address,
        "hw_config_received_at": cfg.hw_config_received_at.isoformat() if cfg.hw_config_received_at else None,
        "current_amps": cfg.meter_current_amps,
        "voltage_v": cfg.meter_voltage_v,
        "power_kw": cfg.meter_power_kw,
        "power_factor": cfg.meter_power_factor,
        "energy_kwh": cfg.meter_energy_kwh,
        "frequency_hz": cfg.meter_frequency_hz,
        "load_pct": cfg.meter_load_pct,
        "load_status": cfg.meter_load_status or "unknown",
        "meter_load_updated_at": cfg.meter_load_updated_at.isoformat() if cfg.meter_load_updated_at else None,
        "warning_threshold_pct": cfg.load_warning_threshold_pct,
        "critical_threshold_pct": cfg.load_critical_threshold_pct,
    }
    if cfg.phases == 3:
        base.update({
            "current_l1": cfg.meter_current_l1,
            "current_l2": cfg.meter_current_l2,
            "current_l3": cfg.meter_current_l3,
            "voltage_l1": cfg.meter_voltage_l1,
            "voltage_l2": cfg.meter_voltage_l2,
            "voltage_l3": cfg.meter_voltage_l3,
        })
    return base


def serialize_alarm(a: MeterLoadAlarm) -> dict:
    return {
        "id": a.id,
        "pedestal_id": a.pedestal_id,
        "socket_id": a.socket_id,
        "alarm_type": a.alarm_type,
        "current_amps": a.current_amps,
        "rated_amps": a.rated_amps,
        "load_pct": a.load_pct,
        "phases": a.phases,
        "meter_type": a.meter_type,
        "triggered_at": a.triggered_at.isoformat() if a.triggered_at else None,
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
        "resolved_by": a.resolved_by,
        "acknowledged": bool(a.acknowledged),
        "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
        "acknowledged_by": a.acknowledged_by,
    }


# ── Routes ──────────────────────────────────────────────────────────────────

@router.get("/{pedestal_id}/sockets/{socket_id}/load")
def get_socket_load(
    pedestal_id: int,
    socket_id: int,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    """Live meter readings + load status for a single socket. Admin & monitor."""
    _get_pedestal_or_404(db, pedestal_id)
    cfg = _get_socket_or_404(db, pedestal_id, socket_id)
    return serialize_load_state(cfg)


@router.get("/{pedestal_id}/load")
def get_pedestal_load(
    pedestal_id: int,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    """Live load + meter readings for every socket on the pedestal."""
    _get_pedestal_or_404(db, pedestal_id)
    rows = db.query(SocketConfig).filter(
        SocketConfig.pedestal_id == pedestal_id,
    ).order_by(SocketConfig.socket_id).all()
    return {
        "pedestal_id": pedestal_id,
        "sockets": [serialize_load_state(r) for r in rows],
    }


@router.patch("/{pedestal_id}/sockets/{socket_id}/load/thresholds")
def patch_thresholds(
    pedestal_id: int,
    socket_id: int,
    body: ThresholdsBody,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Operator-set warning/critical thresholds. Admin only.

    Validation: 1 ≤ warning < critical ≤ 99 (Pydantic enforces the range;
    we enforce ordering here so a 400 with a clear message comes back).
    """
    if body.warning_threshold_pct >= body.critical_threshold_pct:
        raise HTTPException(
            status_code=400,
            detail="warning_threshold_pct must be strictly less than critical_threshold_pct",
        )
    _get_pedestal_or_404(db, pedestal_id)
    cfg = _get_socket_or_404(db, pedestal_id, socket_id)
    cfg.load_warning_threshold_pct = body.warning_threshold_pct
    cfg.load_critical_threshold_pct = body.critical_threshold_pct
    db.commit()
    db.refresh(cfg)
    return serialize_load_state(cfg)


@router.get("/{pedestal_id}/load/alarms")
def get_pedestal_alarms(
    pedestal_id: int,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    """Open (unresolved) alarms only, newest first. Admin & monitor."""
    _get_pedestal_or_404(db, pedestal_id)
    rows = (
        db.query(MeterLoadAlarm)
        .filter(
            MeterLoadAlarm.pedestal_id == pedestal_id,
            MeterLoadAlarm.resolved_at.is_(None),
        )
        .order_by(MeterLoadAlarm.triggered_at.desc())
        .all()
    )
    return {"pedestal_id": pedestal_id, "alarms": [serialize_alarm(a) for a in rows]}


@router.get("/{pedestal_id}/sockets/{socket_id}/load/history")
def get_socket_history(
    pedestal_id: int,
    socket_id: int,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    """Last 50 alarm events for a socket (open + resolved), newest first."""
    _get_pedestal_or_404(db, pedestal_id)
    rows = (
        db.query(MeterLoadAlarm)
        .filter(
            MeterLoadAlarm.pedestal_id == pedestal_id,
            MeterLoadAlarm.socket_id == socket_id,
        )
        .order_by(MeterLoadAlarm.triggered_at.desc())
        .limit(50)
        .all()
    )
    return {
        "pedestal_id": pedestal_id,
        "socket_id": socket_id,
        "events": [serialize_alarm(a) for a in rows],
    }


# ── Acknowledge / Resolve (D9) ──────────────────────────────────────────────

@router.post("/{pedestal_id}/load/alarms/{alarm_id}/acknowledge")
def acknowledge_alarm(
    pedestal_id: int,
    alarm_id: int,
    db: DBSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Flip `acknowledged=True`. Alarm stays open and visible (dimmed); badge
    no longer counts it. Admin only."""
    _get_pedestal_or_404(db, pedestal_id)
    a = db.get(MeterLoadAlarm, alarm_id)
    if a is None or a.pedestal_id != pedestal_id:
        raise HTTPException(status_code=404, detail="Alarm not found on this pedestal")
    if a.acknowledged:
        return serialize_alarm(a)
    a.acknowledged = True
    a.acknowledged_at = datetime.utcnow()
    a.acknowledged_by = user.email
    db.commit()
    db.refresh(a)
    return serialize_alarm(a)


@router.post("/{pedestal_id}/load/alarms/{alarm_id}/resolve")
def resolve_alarm(
    pedestal_id: int,
    alarm_id: int,
    db: DBSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Manual close. Sets `resolved_at = utcnow()`, `resolved_by = admin email`.
    Distinct from auto-resolve (which uses `resolved_by="auto-resolve"`). Admin only."""
    _get_pedestal_or_404(db, pedestal_id)
    a = db.get(MeterLoadAlarm, alarm_id)
    if a is None or a.pedestal_id != pedestal_id:
        raise HTTPException(status_code=404, detail="Alarm not found on this pedestal")
    if a.resolved_at is not None:
        return serialize_alarm(a)
    a.resolved_at = datetime.utcnow()
    a.resolved_by = user.email
    db.commit()
    db.refresh(a)
    return serialize_alarm(a)


# ── v3.12 — Auto-stop overload alarm acknowledgment ─────────────────────────

def _post_ack_load_status(cfg: SocketConfig) -> str:
    """Reclassify the socket's load_status after the auto-stop latch clears.
    Matches `_classify_load` in mqtt_handlers but uses prev_status="unknown"
    so the operator's ack is a clean restart — no hysteresis carryover."""
    pct = cfg.meter_load_pct
    if pct is None:
        return "unknown"
    warn = int(cfg.load_warning_threshold_pct or 60)
    crit = int(cfg.load_critical_threshold_pct or 80)
    # Defer to the canonical classifier so any future tweak stays in one place.
    from ..services.mqtt_handlers import _classify_load
    return _classify_load(float(pct), "unknown", warn, crit)


def perform_auto_stop_acknowledge(
    db: DBSession,
    pedestal_id: int,
    socket_id: int,
    actor_label: str,
) -> tuple[SocketConfig, MeterLoadAlarm | None, str]:
    """Atomic ack used by both the internal admin endpoint and the ERP
    twin (Step 5). Clears the latch on SocketConfig AND closes the latest
    open auto_stop alarm row in a single transaction. Returns the row
    triple (cfg, alarm, new_load_status) for the caller to broadcast +
    serialize. Raises HTTPException(404) when the socket or open alarm
    does not exist."""
    cfg = _get_socket_or_404(db, pedestal_id, socket_id)

    if not getattr(cfg, "auto_stop_pending_ack", False):
        raise HTTPException(
            status_code=409,
            detail="No auto-stop alarm is pending acknowledgment for this socket.",
        )

    # Find the most recent open auto-stop alarm for this socket (D4).
    alarm = (
        db.query(MeterLoadAlarm)
        .filter(
            MeterLoadAlarm.pedestal_id == pedestal_id,
            MeterLoadAlarm.socket_id == socket_id,
            MeterLoadAlarm.alarm_type == "auto_stop",
            MeterLoadAlarm.resolved_at.is_(None),
            MeterLoadAlarm.acknowledged.is_(False),
        )
        .order_by(MeterLoadAlarm.id.desc())
        .first()
    )

    now = datetime.utcnow()
    if alarm is not None:
        alarm.acknowledged = True
        alarm.acknowledged_at = now
        alarm.acknowledged_by = actor_label

    new_status = _post_ack_load_status(cfg)
    cfg.auto_stop_pending_ack = False
    cfg.meter_load_status = new_status

    db.commit()
    if alarm is not None:
        db.refresh(alarm)
    db.refresh(cfg)
    return cfg, alarm, new_status


@router.post("/{pedestal_id}/sockets/{socket_id}/load/auto-stop/acknowledge")
async def acknowledge_auto_stop(
    pedestal_id: int,
    socket_id: int,
    db: DBSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """v3.12 — operator acknowledges a 90% auto-stop alarm.

    Atomic in one transaction (D5):
      1. Clear `SocketConfig.auto_stop_pending_ack`
      2. Mark the latest open auto-stop alarm row acknowledged with the
         admin's email as `acknowledged_by`
      3. Reset `meter_load_status` to whatever the live load justifies
         (the latch was the only thing forcing it to `auto_stop`)

    Then broadcasts `meter_load_auto_stop_acknowledged` so the dashboard
    can clear its banner without waiting for the next telemetry tick.
    """
    _get_pedestal_or_404(db, pedestal_id)
    cfg, alarm, new_status = perform_auto_stop_acknowledge(
        db, pedestal_id, socket_id, actor_label=user.email,
    )

    await ws_manager.broadcast({
        "event": "meter_load_auto_stop_acknowledged",
        "data": {
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "alarm_id": alarm.id if alarm is not None else None,
            "acknowledged_by": user.email,
            "acknowledged_at": (alarm.acknowledged_at.isoformat()
                                 if alarm is not None and alarm.acknowledged_at else None),
            "load_status": new_status,
            "timestamp": datetime.utcnow().isoformat(),
        },
    })

    return {"status": "acknowledged", "socket_id": socket_id}
