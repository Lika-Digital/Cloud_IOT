"""Customer session management: start, list, stop."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession
from ..database import get_db
from ..auth.user_database import get_user_db
from ..auth.customer_models import Customer
from ..auth.customer_dependencies import require_customer
from ..services.session_service import session_service
from ..services.mqtt_client import mqtt_service
from ..services.websocket_manager import ws_manager
from ..services.invoice_service import create_invoice_for_session
from ..schemas.session import SessionResponse
from ..schemas.customer import StartSessionRequest, PedestalStatusResponse
from ..models.session import Session

router = APIRouter(prefix="/api/customer/sessions", tags=["customer-sessions"])


@router.get("/pedestal-status", response_model=list[PedestalStatusResponse])
def pedestal_status(
    db: DBSession = Depends(get_db),
    customer: Customer = Depends(require_customer),
):
    """Return all pedestals with their currently occupied sockets."""
    from ..models.pedestal import Pedestal
    pedestals = db.query(Pedestal).filter(Pedestal.mobile_enabled == True).order_by(Pedestal.id).all()  # noqa: E712
    result = []
    for p in pedestals:
        active = (
            db.query(Session)
            .filter(Session.pedestal_id == p.id, Session.status.in_(["pending", "active"]))
            .all()
        )
        occupied_sockets = [s.socket_id for s in active if s.socket_id is not None]
        water_occupied = any(s for s in active if s.type == "water")
        result.append(PedestalStatusResponse(
            id=p.id,
            name=p.name,
            location=p.location,
            occupied_sockets=occupied_sockets,
            water_occupied=water_occupied,
        ))
    return result


@router.post("/start", response_model=SessionResponse)
async def start_session(
    body: StartSessionRequest,
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    if body.type not in ("electricity", "water"):
        raise HTTPException(status_code=422, detail="type must be 'electricity' or 'water'")
    if body.type == "electricity":
        if body.socket_id is None:
            raise HTTPException(status_code=422, detail="socket_id required for electricity")
        if body.socket_id not in (1, 2, 3, 4):
            raise HTTPException(status_code=422, detail="socket_id must be 1, 2, 3, or 4")

    # One active/pending session per customer at a time
    customer_busy = (
        db.query(Session)
        .filter(Session.customer_id == customer.id, Session.status.in_(["pending", "active"]))
        .first()
    )
    if customer_busy:
        raise HTTPException(
            status_code=409,
            detail="You already have an active or pending session. Stop it before starting a new one.",
        )

    # Check socket not already in use
    socket_id = body.socket_id if body.type == "electricity" else None
    existing = session_service.get_active_for_socket(db, body.pedestal_id, socket_id)
    if existing:
        raise HTTPException(status_code=409, detail="Socket already has an active or pending session")

    session = session_service.create_pending(
        db, body.pedestal_id, socket_id, body.type, customer_id=customer.id
    )

    # Auto-activate immediately — no operator approval required
    session_service.activate(db, session)
    control_topic = (
        f"pedestal/{session.pedestal_id}/socket/{session.socket_id}/control"
        if session.type == "electricity"
        else f"pedestal/{session.pedestal_id}/water/control"
    )
    mqtt_service.publish(control_topic, "allow")

    await ws_manager.broadcast({
        "event": "session_created",
        "data": {
            "session_id": session.id,
            "pedestal_id": session.pedestal_id,
            "socket_id": session.socket_id,
            "type": session.type,
            "status": "active",
            "started_at": session.started_at.isoformat(),
            "customer_id": customer.id,
            "customer_name": customer.name,
        },
    })
    return session


@router.get("/mine", response_model=list[SessionResponse])
def my_sessions(
    db: DBSession = Depends(get_db),
    customer: Customer = Depends(require_customer),
):
    return db.query(Session).filter(Session.customer_id == customer.id).order_by(Session.started_at.desc()).all()


@router.post("/{session_id}/stop", response_model=SessionResponse)
async def stop_my_session(
    session_id: int,
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    session = db.get(Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.customer_id != customer.id:
        raise HTTPException(status_code=403, detail="Not your session")
    if session.status != "active":
        raise HTTPException(status_code=400, detail=f"Session is {session.status}, expected active")

    session_service.complete(db, session)

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

    # Best-effort — session is already completed; don't abort on invoice failure
    try:
        await create_invoice_for_session(db, user_db, session)
    except Exception as e:
        try:
            from ..services.error_log_service import log_error
            log_error(
                "system", "customer_sessions",
                f"Invoice creation failed for session {session.id}: {e}",
                exc=e,
            )
        except Exception:
            pass

    return session
