from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from ..database import get_db
from ..models.session import Session
from ..schemas.session import SessionResponse
from ..services.session_service import session_service
from ..services.mqtt_client import mqtt_service
from ..services.websocket_manager import ws_manager
from ..auth.dependencies import require_admin
from ..auth.models import User
import asyncio

router = APIRouter(prefix="/api/controls", tags=["controls"])


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
async def allow_session(session_id: int, db: DBSession = Depends(get_db), _: User = Depends(require_admin)):
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
        },
    })
    return session


@router.post("/{session_id}/deny", response_model=SessionResponse)
async def deny_session(session_id: int, db: DBSession = Depends(get_db), _: User = Depends(require_admin)):
    session = _get_session_or_404(session_id, db)
    if session.status != "pending":
        raise HTTPException(status_code=400, detail=f"Session is {session.status}, expected pending")

    session_service.deny(db, session)
    mqtt_service.publish(_control_topic(session), "deny")

    await ws_manager.broadcast({
        "event": "session_updated",
        "data": {
            "session_id": session.id,
            "pedestal_id": session.pedestal_id,
            "socket_id": session.socket_id,
            "type": session.type,
            "status": "denied",
        },
    })
    return session


@router.post("/{session_id}/stop", response_model=SessionResponse)
async def stop_session(session_id: int, db: DBSession = Depends(get_db), _: User = Depends(require_admin)):
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
        },
    })
    return session
