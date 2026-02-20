from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session as DBSession
from ..database import get_db
from ..models.session import Session
from ..services.prediction_service import prediction_service

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.post("/train")
def train_model(pedestal_id: int | None = None, db: DBSession = Depends(get_db)):
    q = db.query(Session).filter(Session.status == "completed")
    if pedestal_id:
        q = q.filter(Session.pedestal_id == pedestal_id)
    sessions = q.all()
    result = prediction_service.train(sessions)
    result["total_sessions"] = len(sessions)
    return result


@router.get("/electricity")
def predict_electricity(
    duration_minutes: float = Query(..., gt=0, description="Expected duration in minutes"),
):
    result = prediction_service.predict_electricity(duration_minutes)
    if result is None:
        raise HTTPException(
            status_code=400,
            detail="Electricity model not trained. Need at least 5 completed electricity sessions. Call POST /train first.",
        )
    return result


@router.get("/water")
def predict_water(
    duration_minutes: float = Query(..., gt=0, description="Expected duration in minutes"),
):
    result = prediction_service.predict_water(duration_minutes)
    if result is None:
        raise HTTPException(
            status_code=400,
            detail="Water model not trained. Need at least 5 completed water sessions. Call POST /train first.",
        )
    return result


@router.get("/status")
def prediction_status():
    return {
        "electricity_model_ready": prediction_service.electricity_ready,
        "water_model_ready": prediction_service.water_ready,
    }
