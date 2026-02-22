from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession
from ..database import get_db
from ..models.pedestal import Pedestal
from ..models.session import Session as SessionModel
from ..schemas.pedestal import PedestalCreate, PedestalUpdate, PedestalResponse
from ..services.simulator_manager import simulator_manager
from ..config import settings
from ..auth.dependencies import require_admin, require_any_role
from ..auth.models import User

router = APIRouter(prefix="/api/pedestals", tags=["pedestals"])


@router.get("", response_model=list[PedestalResponse])
def list_pedestals(db: DBSession = Depends(get_db)):
    return db.query(Pedestal).order_by(Pedestal.id).all()


@router.post("", response_model=PedestalResponse, status_code=201)
def create_pedestal(body: PedestalCreate, db: DBSession = Depends(get_db), _: User = Depends(require_admin)):
    pedestal = Pedestal(**body.model_dump())
    db.add(pedestal)
    db.commit()
    db.refresh(pedestal)
    return pedestal


@router.post("/configure", response_model=list[PedestalResponse])
def configure_pedestals(
    count: int = Query(..., ge=1, le=20, description="Number of pedestals to monitor"),
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Create or remove pedestals to match the requested count."""
    existing = db.query(Pedestal).order_by(Pedestal.id).all()
    existing_count = len(existing)

    if count > existing_count:
        for i in range(existing_count + 1, count + 1):
            p = Pedestal(
                name=f"Pedestal {i}",
                location=f"Marina Berth {chr(64 + i)}",
                data_mode="synthetic",
            )
            db.add(p)
        db.commit()
    elif count < existing_count:
        to_remove = existing[count:]
        # Block removal if any pedestal still has active or pending sessions
        for p in to_remove:
            busy = (
                db.query(SessionModel)
                .filter(
                    SessionModel.pedestal_id == p.id,
                    SessionModel.status.in_(["active", "pending"]),
                )
                .count()
            )
            if busy:
                raise HTTPException(
                    status_code=400,
                    detail=f"Pedestal '{p.name}' has active or pending sessions. Stop them first.",
                )
        for p in to_remove:
            db.delete(p)
        db.commit()

    # Restart simulator if running with updated pedestal list
    if simulator_manager.is_running:
        all_pedestals = db.query(Pedestal).order_by(Pedestal.id).all()
        pedestal_ids = [p.id for p in all_pedestals]
        simulator_manager.stop()
        simulator_manager.start(
            pedestal_ids=pedestal_ids,
            broker_host=settings.mqtt_broker_host,
            broker_port=settings.mqtt_broker_port,
        )

    return db.query(Pedestal).order_by(Pedestal.id).all()


@router.get("/{pedestal_id}", response_model=PedestalResponse)
def get_pedestal(pedestal_id: int, db: DBSession = Depends(get_db)):
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    return pedestal


@router.patch("/{pedestal_id}", response_model=PedestalResponse)
def update_pedestal(pedestal_id: int, body: PedestalUpdate, db: DBSession = Depends(get_db), _: User = Depends(require_admin)):
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(pedestal, field, value)
    db.commit()
    db.refresh(pedestal)
    return pedestal


@router.patch("/{pedestal_id}/mode", response_model=PedestalResponse)
def set_mode(
    pedestal_id: int,
    mode: str = Query(..., pattern="^(synthetic|real)$"),
    ip_address: str | None = None,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")

    if mode == "synthetic":
        pedestal.data_mode = "synthetic"
        pedestal.initialized = False  # reset — real pedestal check no longer valid
        all_pedestals = db.query(Pedestal).order_by(Pedestal.id).all()
        pedestal_ids = [p.id for p in all_pedestals]
        simulator_manager.start(
            pedestal_ids=pedestal_ids,
            broker_host=settings.mqtt_broker_host,
            broker_port=settings.mqtt_broker_port,
        )
    else:
        pedestal.data_mode = "real"
        pedestal.initialized = False  # must re-run diagnostics after connecting
        if ip_address:
            pedestal.ip_address = ip_address
        simulator_manager.stop()

    db.commit()
    db.refresh(pedestal)
    return pedestal


@router.get("/{pedestal_id}/simulator/status")
def simulator_status(pedestal_id: int):
    return {"running": simulator_manager.is_running}
