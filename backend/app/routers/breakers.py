"""v3.8 — internal breaker monitoring + remote reset endpoints.

Exposes admin-only reset and admin-or-monitor status/history reads. The ERP
counterpart lives in `routers/ext_breaker_endpoints.py` and reuses the same
publish helper + event-log conventions so audit rows are consistent regardless
of who triggered the reset.

Shared helper `publish_breaker_reset` is imported by the ERP router so both
call sites emit the identical MQTT topic + JSON shape.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session as DBSession

from ..auth.dependencies import require_admin, require_any_role
from ..auth.models import User
from ..database import get_db
from ..models.breaker_event import BreakerEvent
from ..models.pedestal import Pedestal
from ..models.pedestal_config import PedestalConfig
from ..models.socket_config import SocketConfig
from ..services.mqtt_client import mqtt_service
from ..services.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pedestals", tags=["breakers"])


# ── shared helpers (used by this router + ext_breaker_endpoints.py) ──────────

def get_cabinet_id(db: DBSession, pedestal_id: int) -> str | None:
    """Resolve pedestal → marina cabinet string id ('MAR_KRK_ORM_01'). None for
    legacy pedestals without a PedestalConfig row."""
    cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pedestal_id).first()
    return getattr(cfg, "opta_client_id", None) if cfg else None


def publish_breaker_reset(cabinet_id: str, socket_id: int) -> None:
    """Publish the reset command to `opta/cmd/breaker/Q{n}`. Idempotent — Opta
    acks on `opta/acks`; final breaker state arrives via `opta/breakers/Q{n}/status`.
    """
    msg_id = f"breaker-reset-{int(datetime.utcnow().timestamp() * 1000)}"
    mqtt_service.publish(
        f"opta/cmd/breaker/Q{socket_id}",
        json.dumps({"msgId": msg_id, "cabinetId": cabinet_id, "action": "reset"}),
    )


def serialize_breaker_status(cfg: SocketConfig | None) -> dict:
    """Shape returned by GET endpoints. Reused by ERP router."""
    if cfg is None:
        return {
            "breaker_state": "unknown",
            "breaker_last_trip_at": None,
            "breaker_trip_cause": None,
            "breaker_trip_count": 0,
            "breaker_type": None,
            "breaker_rating": None,
            "breaker_poles": None,
            "breaker_rcd": None,
            "breaker_rcd_sensitivity": None,
        }
    return {
        "breaker_state": cfg.breaker_state or "unknown",
        "breaker_last_trip_at": cfg.breaker_last_trip_at.isoformat() if cfg.breaker_last_trip_at else None,
        "breaker_trip_cause": cfg.breaker_trip_cause,
        "breaker_trip_count": cfg.breaker_trip_count or 0,
        "breaker_type": cfg.breaker_type,
        "breaker_rating": cfg.breaker_rating,
        "breaker_poles": cfg.breaker_poles,
        "breaker_rcd": cfg.breaker_rcd,
        "breaker_rcd_sensitivity": cfg.breaker_rcd_sensitivity,
    }


def serialize_event(e: BreakerEvent) -> dict:
    return {
        "id": e.id,
        "pedestal_id": e.pedestal_id,
        "socket_id": e.socket_id,
        "event_type": e.event_type,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "trip_cause": e.trip_cause,
        "current_at_trip": e.current_at_trip,
        "reset_initiated_by": e.reset_initiated_by,
    }


def perform_breaker_reset(
    db: DBSession,
    pedestal_id: int,
    socket_id: int,
    initiated_by: str,
) -> dict:
    """Core reset flow shared by admin + ERP endpoints.

    Raises HTTPException(404) if pedestal/socket not found.
    Raises HTTPException(409) if breaker_state != 'tripped'.
    On success: flips state to 'resetting', appends breaker_events row, publishes
    MQTT, broadcasts `breaker_state_changed`, returns a status dict.
    """
    if db.get(Pedestal, pedestal_id) is None:
        raise HTTPException(status_code=404, detail="Pedestal not found")

    cfg = db.query(SocketConfig).filter(
        SocketConfig.pedestal_id == pedestal_id,
        SocketConfig.socket_id == socket_id,
    ).first()
    if cfg is None:
        raise HTTPException(status_code=404, detail="Socket not found")
    if cfg.breaker_state != "tripped":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Breaker is not in tripped state",
        )

    cabinet_id = get_cabinet_id(db, pedestal_id)
    if not cabinet_id:
        raise HTTPException(status_code=409, detail="Pedestal has no cabinet id configured")

    cfg.breaker_state = "resetting"
    db.add(BreakerEvent(
        pedestal_id=pedestal_id,
        socket_id=socket_id,
        event_type="reset_attempted",
        timestamp=datetime.utcnow(),
        reset_initiated_by=initiated_by,
    ))
    db.commit()

    publish_breaker_reset(cabinet_id, socket_id)

    return {
        "pedestal_id": pedestal_id,
        "socket_id": socket_id,
        "initiated_by": initiated_by,
    }


async def broadcast_resetting(pedestal_id: int, socket_id: int) -> None:
    """Broadcast the synchronous state flip. Called after `perform_breaker_reset`
    returns — outside the DB session so WS publish never holds the connection."""
    await ws_manager.broadcast({
        "event": "breaker_state_changed",
        "data": {
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "breaker_state": "resetting",
            "trip_cause": None,
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


# ── admin + monitor routes ───────────────────────────────────────────────────

@router.post("/{pedestal_id}/sockets/{socket_id}/breaker/reset")
async def reset_breaker(
    pedestal_id: int,
    socket_id: int,
    db: DBSession = Depends(get_db),
    user: User = Depends(require_admin),
):
    """Operator-triggered remote reset. Returns 409 when state != tripped."""
    result = perform_breaker_reset(db, pedestal_id, socket_id, initiated_by=user.email)
    await broadcast_resetting(pedestal_id, socket_id)
    return {
        "status": "reset_command_sent",
        "socket_id": socket_id,
        "initiated_by": result["initiated_by"],
    }


@router.get("/{pedestal_id}/sockets/{socket_id}/breaker/status")
def get_socket_breaker_status(
    pedestal_id: int,
    socket_id: int,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    cfg = db.query(SocketConfig).filter(
        SocketConfig.pedestal_id == pedestal_id,
        SocketConfig.socket_id == socket_id,
    ).first()
    if cfg is None and db.get(Pedestal, pedestal_id) is None:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    body = {"pedestal_id": pedestal_id, "socket_id": socket_id}
    body.update(serialize_breaker_status(cfg))
    return body


@router.get("/{pedestal_id}/sockets/{socket_id}/breaker/history")
def get_socket_breaker_history(
    pedestal_id: int,
    socket_id: int,
    limit: int = Query(default=10, ge=1, le=200),
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    """Per-spec D6 — used by the history modal in the Control Center.
    Default limit 10, capped at 200 so operators can never accidentally pull
    unbounded history from the UI.
    """
    rows = (
        db.query(BreakerEvent)
        .filter(
            BreakerEvent.pedestal_id == pedestal_id,
            BreakerEvent.socket_id == socket_id,
        )
        .order_by(BreakerEvent.timestamp.desc())
        .limit(limit)
        .all()
    )
    return {"pedestal_id": pedestal_id, "socket_id": socket_id, "events": [serialize_event(e) for e in rows]}


@router.get("/{pedestal_id}/breaker/history")
def get_pedestal_breaker_history(
    pedestal_id: int,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    """Last 50 events across every socket on the pedestal (per spec)."""
    rows = (
        db.query(BreakerEvent)
        .filter(BreakerEvent.pedestal_id == pedestal_id)
        .order_by(BreakerEvent.timestamp.desc())
        .limit(50)
        .all()
    )
    return {"pedestal_id": pedestal_id, "events": [serialize_event(e) for e in rows]}
