from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session as DBSession
from ..database import get_db
from ..models.session import Session
from ..schemas.session import SessionResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionResponse])
def list_sessions(
    pedestal_id: int | None = None,
    status: str | None = None,
    limit: int = Query(default=100, le=500),
    db: DBSession = Depends(get_db),
):
    q = db.query(Session)
    if pedestal_id:
        q = q.filter(Session.pedestal_id == pedestal_id)
    if status:
        q = q.filter(Session.status == status)
    return q.order_by(Session.started_at.desc()).limit(limit).all()


@router.get("/active", response_model=list[SessionResponse])
def active_sessions(pedestal_id: int | None = None, db: DBSession = Depends(get_db)):
    q = db.query(Session).filter(Session.status == "active")
    if pedestal_id:
        q = q.filter(Session.pedestal_id == pedestal_id)
    return q.all()


@router.get("/pending", response_model=list[SessionResponse])
def pending_sessions(pedestal_id: int | None = None, db: DBSession = Depends(get_db)):
    q = db.query(Session).filter(Session.status == "pending")
    if pedestal_id:
        q = q.filter(Session.pedestal_id == pedestal_id)
    return q.all()


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(session_id: int, db: DBSession = Depends(get_db)):
    from fastapi import HTTPException
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
