from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession
from ..database import get_db
from ..auth.user_database import get_user_db
from ..auth.dependencies import require_any_role
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from ..auth.identity_redaction import redact, sees_identity
from ..auth.models import User
from ..auth.customer_models import Customer
from ..models.session import Session
from ..schemas.session import SessionResponse

# 2026-10-12, block 1 (rule 13): identity on the ROUTER, so a route added here later cannot be
# left open. Every route below answered anyone — including this list, which carries customer
# fields — and an anonymous GET reached the SQL query.
router = APIRouter(prefix="/api/sessions", tags=["sessions"],
                   dependencies=[Depends(require_any_role)])


def _enrich(sessions: list[Session], user_db: DBSession) -> list[SessionResponse]:
    """
    Populate customer_name on SessionResponse objects by joining Customer records.
    GAP-FE-BE: customer_name is consumed by the frontend but absent from the ORM model.
    This helper performs a bulk lookup to avoid N+1 queries.
    """
    # Collect unique customer IDs that are non-null
    cids = {s.customer_id for s in sessions if s.customer_id is not None}
    name_map: dict[int, str | None] = {}
    if cids:
        customers = user_db.query(Customer).filter(Customer.id.in_(cids)).all()
        name_map = {c.id: c.name for c in customers}

    results = []
    for s in sessions:
        resp = SessionResponse.model_validate(s)
        resp.customer_name = name_map.get(s.customer_id) if s.customer_id else None
        results.append(resp)
    return results


def _for(user: User, payload):
    """2026-10-12, part B: customer identity only for an admin. Everyone else gets the same
    rows without customer_id / customer_name / nfc_user_id / erp_ref — removed, not nulled."""
    if sees_identity(user.role):
        return payload
    return JSONResponse(redact(jsonable_encoder(payload)))


@router.get("", response_model=list[SessionResponse])
def list_sessions(
    pedestal_id: int | None = None,
    status: str | None = None,
    limit: int = Query(default=100, le=500),
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    user: User = Depends(require_any_role),
):
    q = db.query(Session)
    if pedestal_id:
        q = q.filter(Session.pedestal_id == pedestal_id)
    if status:
        q = q.filter(Session.status == status)
    sessions = q.order_by(Session.started_at.desc()).limit(limit).all()
    return _for(user, _enrich(sessions, user_db))


@router.get("/active", response_model=list[SessionResponse])
def active_sessions(
    pedestal_id: int | None = None,
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    user: User = Depends(require_any_role),
):
    q = db.query(Session).filter(Session.status == "active")
    if pedestal_id:
        q = q.filter(Session.pedestal_id == pedestal_id)
    return _for(user, _enrich(q.all(), user_db))


@router.get("/pending", response_model=list[SessionResponse])
def pending_sessions(
    pedestal_id: int | None = None,
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    user: User = Depends(require_any_role),
):
    q = db.query(Session).filter(Session.status == "pending")
    if pedestal_id:
        q = q.filter(Session.pedestal_id == pedestal_id)
    return _for(user, _enrich(q.all(), user_db))


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: int,
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    user: User = Depends(require_any_role),
):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _for(user, _enrich([session], user_db)[0])
