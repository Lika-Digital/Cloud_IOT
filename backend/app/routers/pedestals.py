from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession
from ..database import get_db
from ..models.pedestal import Pedestal
from ..schemas.pedestal import PedestalCreate, PedestalUpdate, PedestalResponse
from ..services.simulator_manager import simulator_manager
from ..config import settings

router = APIRouter(prefix="/api/pedestals", tags=["pedestals"])


@router.get("", response_model=list[PedestalResponse])
def list_pedestals(db: DBSession = Depends(get_db)):
    return db.query(Pedestal).all()


@router.post("", response_model=PedestalResponse, status_code=201)
def create_pedestal(body: PedestalCreate, db: DBSession = Depends(get_db)):
    pedestal = Pedestal(**body.model_dump())
    db.add(pedestal)
    db.commit()
    db.refresh(pedestal)
    return pedestal


@router.get("/{pedestal_id}", response_model=PedestalResponse)
def get_pedestal(pedestal_id: int, db: DBSession = Depends(get_db)):
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    return pedestal


@router.patch("/{pedestal_id}", response_model=PedestalResponse)
def update_pedestal(pedestal_id: int, body: PedestalUpdate, db: DBSession = Depends(get_db)):
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
):
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")

    if mode == "synthetic":
        pedestal.data_mode = "synthetic"
        simulator_manager.start(
            pedestal_id=pedestal_id,
            broker_host=settings.mqtt_broker_host,
            broker_port=settings.mqtt_broker_port,
        )
    else:
        pedestal.data_mode = "real"
        if ip_address:
            pedestal.ip_address = ip_address
        simulator_manager.stop()

    db.commit()
    db.refresh(pedestal)
    return pedestal


@router.get("/{pedestal_id}/simulator/status")
def simulator_status(pedestal_id: int):
    return {"running": simulator_manager.is_running}
