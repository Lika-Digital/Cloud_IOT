from typing import Optional
import asyncio
import json
import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from ..database import get_db
from ..auth.user_database import get_user_db
from ..auth.customer_models import Customer
from ..models.session import Session
from ..models.pedestal_config import SocketState
from ..schemas.session import SessionResponse
from ..services.session_service import session_service
from ..services.mqtt_client import mqtt_service
from ..services.websocket_manager import ws_manager
from ..services.invoice_service import create_invoice_for_session
from ..services.audit_service import log_transition
from ..auth.dependencies import require_admin
from ..auth.models import User

logger = logging.getLogger(__name__)


async def _send_expo_push(push_token: str, title: str, body: str, data: dict):
    """Fire-and-forget Expo push notification. Never raises."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                "https://exp.host/--/api/v2/push/send",
                json={"to": push_token, "title": title, "body": body, "data": data},
            )
    except Exception as e:
        logger.warning(f"Push notification failed: {e}")

router = APIRouter(prefix="/api/controls", tags=["controls"])


class DenyBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


def _get_session_or_404(session_id: int, db: DBSession) -> Session:
    s = db.get(Session, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s


def _control_topic(session: Session) -> str:
    if session.type == "electricity":
        return f"pedestal/{session.pedestal_id}/socket/{session.socket_id}/control"
    return f"pedestal/{session.pedestal_id}/water/control"


@router.post("/{session_id}/allow", response_model=SessionResponse)
async def allow_session(
    session_id: int,
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    session = _get_session_or_404(session_id, db)
    if session.status != "pending":
        raise HTTPException(status_code=400, detail=f"Session is {session.status}, expected pending")

    session_service.activate(db, session)
    mqtt_service.publish(_control_topic(session), "allow")

    await ws_manager.broadcast({
        "event": "session_updated",
        "data": {
            "session_id": session.id,
            "pedestal_id": session.pedestal_id,
            "socket_id": session.socket_id,
            "type": session.type,
            "status": "active",
            "customer_id": session.customer_id,
            "deny_reason": None,
        },
    })

    # Fire-and-forget push notification
    if session.customer_id:
        customer = user_db.get(Customer, session.customer_id)
        if customer and getattr(customer, "push_token", None):
            asyncio.create_task(_send_expo_push(
                customer.push_token,
                title="Session Approved",
                body=f"Your {session.type} session on Pedestal {session.pedestal_id} has been approved.",
                data={"session_id": session.id},
            ))

    return session


@router.post("/{session_id}/deny", response_model=SessionResponse)
async def deny_session(
    session_id: int,
    body: DenyBody = DenyBody(),
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    session = _get_session_or_404(session_id, db)
    if session.status != "pending":
        raise HTTPException(status_code=400, detail=f"Session is {session.status}, expected pending")

    session_service.deny(db, session, reason=body.reason)
    mqtt_service.publish(_control_topic(session), "deny")

    await ws_manager.broadcast({
        "event": "session_updated",
        "data": {
            "session_id": session.id,
            "pedestal_id": session.pedestal_id,
            "socket_id": session.socket_id,
            "type": session.type,
            "status": "denied",
            "customer_id": session.customer_id,
            "deny_reason": session.deny_reason,
        },
    })

    # Fire-and-forget push notification
    if session.customer_id:
        customer = user_db.get(Customer, session.customer_id)
        if customer and getattr(customer, "push_token", None):
            reason_text = session.deny_reason or "No reason provided."
            asyncio.create_task(_send_expo_push(
                customer.push_token,
                title="Session Denied",
                body=f"Your {session.type} session was denied. Reason: {reason_text}",
                data={"session_id": session.id},
            ))

    return session


@router.post("/{session_id}/stop", response_model=SessionResponse)
async def stop_session(
    session_id: int,
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    _: User = Depends(require_admin),
):
    session = _get_session_or_404(session_id, db)
    if session.status != "active":
        raise HTTPException(status_code=400, detail=f"Session is {session.status}, expected active")

    session_service.complete(db, session)
    mqtt_service.publish(_control_topic(session), "stop")

    await ws_manager.broadcast({
        "event": "session_completed",
        "data": {
            "session_id": session.id,
            "pedestal_id": session.pedestal_id,
            "socket_id": session.socket_id,
            "type": session.type,
            "status": "completed",
            "energy_kwh": session.energy_kwh,
            "water_liters": session.water_liters,
            "customer_id": session.customer_id,
            "stopped_by": "operator",
        },
    })

    # Push notification — inform customer session was stopped by operator
    if session.customer_id:
        customer = user_db.get(Customer, session.customer_id)
        if customer and getattr(customer, "push_token", None):
            asyncio.create_task(_send_expo_push(
                customer.push_token,
                title="Session Stopped by Operator",
                body=f"Your {session.type} session on Pedestal {session.pedestal_id} was manually stopped by the marina operator.",
                data={"session_id": session.id, "stopped_by": "operator"},
            ))

    # Invoice creation is best-effort — session is already completed; don't abort on failure
    try:
        await create_invoice_for_session(db, user_db, session)
    except Exception as e:
        try:
            from ..services.error_log_service import log_error
            log_error(
                "system", "controls",
                f"Invoice creation failed for session {session.id} (session still completed): {e}",
                exc=e,
            )
        except Exception:
            pass

    return session


# ── Socket-level operator approval (before any session exists) ────────────────

def _get_socket_state_or_400(db: DBSession, pedestal_id: int, socket_id: int) -> SocketState:
    state = db.query(SocketState).filter(
        SocketState.pedestal_id == pedestal_id,
        SocketState.socket_id == socket_id,
    ).first()
    if not state or state.operator_status != "pending":
        raise HTTPException(status_code=400, detail="Socket is not in pending approval state")
    return state


@router.post("/sockets/{pedestal_id}/{socket_id}/approve", response_model=SessionResponse)
async def approve_socket(
    pedestal_id: int,
    socket_id: int,
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    current_user: User = Depends(require_admin),
):
    """
    Operator approves a socket that is in pending state (MQTT connected event fired).
    Creates and activates a session, clears the pending flag, publishes MQTT approved command.
    """
    state = _get_socket_state_or_400(db, pedestal_id, socket_id)

    existing = session_service.get_active_for_socket(db, pedestal_id, socket_id)
    if existing and existing.status == "active":
        raise HTTPException(status_code=409, detail="Socket already has an active session")

    session = session_service.create_pending(db, pedestal_id, socket_id, "electricity")
    session_service.activate(db, session)

    state.operator_status = None
    state.operator_status_at = None
    db.commit()
    db.refresh(session)

    mqtt_service.publish(
        f"pedestal/{pedestal_id}/socket/{socket_id}/command",
        json.dumps({"cmd": "approved"}),
    )
    log_transition(
        db, session.id, pedestal_id, socket_id,
        "operator_approved", "operator", actor_id=current_user.id,
    )

    await ws_manager.broadcast({
        "event": "session_created",
        "data": {
            "session_id": session.id,
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "type": "electricity",
            "status": "active",
            "started_at": session.started_at.isoformat(),
            "customer_id": None,
            "customer_name": None,
        },
    })
    return session


class RejectSocketBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


@router.post("/sockets/{pedestal_id}/{socket_id}/reject")
async def reject_socket(
    pedestal_id: int,
    socket_id: int,
    body: RejectSocketBody = RejectSocketBody(),
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    current_user: User = Depends(require_admin),
):
    """
    Operator rejects a socket in pending state.
    Publishes MQTT rejection command, marks socket as rejected, notifies dashboard.
    """
    state = _get_socket_state_or_400(db, pedestal_id, socket_id)

    reason = body.reason or "Operator denied"
    state.operator_status = "rejected"
    state.operator_status_at = datetime.utcnow()
    db.commit()

    mqtt_service.publish(
        f"pedestal/{pedestal_id}/socket/{socket_id}/command",
        json.dumps({"cmd": "rejected", "reason": reason}),
    )
    log_transition(
        db, None, pedestal_id, socket_id,
        "operator_rejected", "operator", actor_id=current_user.id, reason=reason,
    )

    await ws_manager.broadcast({
        "event": "socket_rejected",
        "data": {"pedestal_id": pedestal_id, "socket_id": socket_id},
    })
    return {"status": "rejected", "pedestal_id": pedestal_id, "socket_id": socket_id}
