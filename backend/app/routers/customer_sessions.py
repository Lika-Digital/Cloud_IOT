"""Customer session management: start, list, stop."""
from datetime import datetime
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

PILOT_PLUGIN_WINDOW_SECONDS = 180  # 3-minute window for plug-in event


def _get_pilot_assignment(db: DBSession, customer: Customer):
    """Return active pilot assignment for this customer, or None."""
    if not customer.name:
        return None
    from ..models.pilot_assignment import PilotAssignment
    return db.query(PilotAssignment).filter(
        PilotAssignment.username == customer.name,
        PilotAssignment.active == True,  # noqa: E712
    ).first()


@router.get("/pedestal-status", response_model=list[PedestalStatusResponse])
def pedestal_status(
    db: DBSession = Depends(get_db),
    customer: Customer = Depends(require_customer),
):
    """Return pedestals with occupied sockets. Pilot-mode customers see only their assigned pedestal."""
    from ..models.pedestal import Pedestal

    assignment = _get_pilot_assignment(db, customer)

    pedestals = db.query(Pedestal).filter(Pedestal.mobile_enabled == True).order_by(Pedestal.id).all()  # noqa: E712

    # Pilot mode: restrict to the assigned pedestal only
    if assignment:
        pedestals = [p for p in pedestals if p.id == assignment.pedestal_id]

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
            assigned_socket_id=assignment.socket_id if assignment and p.id == assignment.pedestal_id else None,
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

    # Validate pedestal exists and is mobile-enabled
    from ..models.pedestal import Pedestal
    pedestal = db.query(Pedestal).filter(
        Pedestal.id == body.pedestal_id, Pedestal.mobile_enabled == True  # noqa: E712
    ).first()
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found or not available")

    # Pilot mode: enforce assignment + recent plug-in event
    assignment = _get_pilot_assignment(db, customer)
    if assignment:
        if body.pedestal_id != assignment.pedestal_id:
            raise HTTPException(status_code=403, detail="Pilot assignment: use pedestal %d" % assignment.pedestal_id)
        if body.type == "electricity" and body.socket_id != assignment.socket_id:
            raise HTTPException(status_code=403, detail="Pilot assignment: use socket %d" % assignment.socket_id)
        # Require physical plug-in within the last 3 minutes
        from ..models.pedestal_config import SocketState
        state = db.query(SocketState).filter(
            SocketState.pedestal_id == body.pedestal_id,
            SocketState.socket_id == assignment.socket_id,
            SocketState.connected == True,  # noqa: E712
        ).first()
        if state is None or (datetime.utcnow() - state.updated_at).total_seconds() > PILOT_PLUGIN_WINDOW_SECONDS:
            raise HTTPException(
                status_code=409,
                detail="Pilot mode: please plug in within 3 minutes before starting a session",
            )

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

    # Validate socket is physically connected (only blocks if Arduino explicitly reported disconnected)
    if body.type == "electricity":
        from ..models.pedestal_config import SocketState
        state = db.query(SocketState).filter(
            SocketState.pedestal_id == body.pedestal_id,
            SocketState.socket_id == body.socket_id,
        ).first()
        if state is not None and not state.connected:
            raise HTTPException(
                status_code=409,
                detail="Socket is not physically connected",
            )

    socket_id = body.socket_id if body.type == "electricity" else None

    # Check operator rejection: if operator has explicitly rejected this socket, block the customer
    if body.type == "electricity":
        from ..models.pedestal_config import SocketState as _SocketState
        _state = db.query(_SocketState).filter(
            _SocketState.pedestal_id == body.pedestal_id,
            _SocketState.socket_id == body.socket_id,
        ).first()
        if _state is not None and _state.operator_status == "rejected":
            raise HTTPException(
                status_code=409,
                detail="Operator has rejected this socket session. Please reconnect the device.",
            )

    # Check if session already active (operator pre-approved before mobile acted)
    existing = session_service.get_active_for_socket(db, body.pedestal_id, socket_id)
    if existing:
        if existing.status == "active":
            # Operator approved first — assign customer and return active session
            if existing.customer_id is None:
                existing.customer_id = customer.id
                db.commit()
                db.refresh(existing)
            from ..services.audit_service import log_transition
            log_transition(
                db, existing.id, body.pedestal_id, socket_id,
                "customer_claimed_active", "customer", actor_id=customer.id,
            )
            await ws_manager.broadcast({
                "event": "session_updated",
                "data": {
                    "session_id": existing.id,
                    "pedestal_id": existing.pedestal_id,
                    "socket_id": existing.socket_id,
                    "type": existing.type,
                    "status": "active",
                    "customer_id": customer.id,
                    "deny_reason": None,
                },
            })
            return existing
        raise HTTPException(status_code=409, detail="Socket already has an active or pending session")

    session = session_service.create_pending(
        db, body.pedestal_id, socket_id, body.type, customer_id=customer.id
    )

    # Auto-activate immediately — no operator approval required
    session_service.activate(db, session)

    # Clear socket pending flag now that a session is starting
    if body.type == "electricity":
        from ..models.pedestal_config import SocketState as _SocketState2
        _st = db.query(_SocketState2).filter(
            _SocketState2.pedestal_id == body.pedestal_id,
            _SocketState2.socket_id == body.socket_id,
        ).first()
        if _st:
            _st.operator_status = None
            _st.operator_status_at = None
            db.commit()

    from ..services.audit_service import log_transition as _log
    _log(db, session.id, body.pedestal_id, socket_id, "customer_approved", "customer", actor_id=customer.id)

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
    # v3.6 authority model — mobile app is monitoring only. Customer cannot
    # stop a session via API; physical unplug (firmware UserPluggedOut) is the
    # only customer-side stop mechanism. Operator stop stays in the controls
    # router under admin role. The handler body below is preserved for
    # reference but is unreachable.
    raise HTTPException(
        status_code=403,
        detail=(
            "Customer stop is disabled. Unplug the cable to end your session; "
            "only operators can stop sessions from the dashboard."
        ),
    )

    # ─── unreachable — kept for audit / future re-enable ─────────────────────
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
