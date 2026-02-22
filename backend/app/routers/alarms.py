"""Operator alarm management: list active, acknowledge, history."""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..auth.dependencies import require_admin
from ..auth.models import User
from ..services.alarm_service import get_active_alarms, acknowledge_alarm, get_alarm_history

router = APIRouter(prefix="/api/alarms", tags=["alarms"])


class AlarmResponse(BaseModel):
    id: int
    alarm_type: str
    source: str
    pedestal_id: Optional[int] = None
    status: str
    message: str
    details: Optional[str] = None
    triggered_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None

    model_config = {"from_attributes": True}


@router.get("/active", response_model=list[AlarmResponse])
def list_active_alarms(_: User = Depends(require_admin)):
    return get_active_alarms()


@router.post("/{alarm_id}/acknowledge", response_model=AlarmResponse)
def ack_alarm(alarm_id: int, current_user: User = Depends(require_admin)):
    alarm = acknowledge_alarm(alarm_id, operator_email=current_user.email)
    if alarm is None:
        raise HTTPException(status_code=404, detail="Alarm not found or already acknowledged")
    return alarm


@router.get("/history", response_model=list[AlarmResponse])
def alarm_history(
    hours: int = 168,
    limit: int = 200,
    _: User = Depends(require_admin),
):
    return get_alarm_history(limit=limit, since_hours=hours)
