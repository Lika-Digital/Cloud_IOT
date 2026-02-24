from typing import Optional
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from ..database import get_db
from ..auth.user_database import get_user_db
from ..auth.customer_models import Customer
from ..models.session import Session
from ..schemas.session import SessionResponse
from ..services.session_service import session_service
from ..services.mqtt_client import mqtt_service
from ..services.websocket_manager import ws_manager
from ..services.invoice_service import create_invoice_for_session
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
        },
    })

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
