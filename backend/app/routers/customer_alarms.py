"""Customer-triggered alarms: fire and unauthorised entry."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..auth.customer_dependencies import require_customer
from ..auth.customer_models import Customer
from ..services.alarm_service import trigger_alarm
from ..services.error_log_service import log_error

router = APIRouter(prefix="/api/customer/alarms", tags=["customer-alarms"])

_ALLOWED = frozenset({"fire", "unauthorized_entry"})


class TriggerAlarmRequest(BaseModel):
    alarm_type: str   # 'fire' | 'unauthorized_entry'
    pedestal_id: int


class TriggerAlarmResponse(BaseModel):
    alarm_id: int
    alarm_type: str
    status: str
    message: str


@router.post("/trigger", response_model=TriggerAlarmResponse)
def trigger_customer_alarm(
    body: TriggerAlarmRequest,
    customer: Customer = Depends(require_customer),
):
    if body.alarm_type not in _ALLOWED:
        raise HTTPException(
            status_code=400,
            detail=f"alarm_type must be one of: {sorted(_ALLOWED)}",
        )

    label = body.alarm_type.replace("_", " ").title()
    msg = (
        f"{label} reported by {customer.name or customer.email} "
        f"(id={customer.id}) at pedestal {body.pedestal_id}"
    )
    detail_str = f"customer_id={customer.id}, email={customer.email}"

    alarm = trigger_alarm(
        alarm_type=body.alarm_type,
        source="customer_mobile",
        message=msg,
        pedestal_id=body.pedestal_id,
        details=detail_str,
        deduplicate=False,   # every customer trigger is a separate alarm event
    )
    if alarm is None:
        raise HTTPException(status_code=500, detail="Failed to create alarm")

    # Mirror to error_log so it also appears in the System Health log view
    log_error("alarm", "customer_mobile", msg, details=detail_str)

    return TriggerAlarmResponse(
        alarm_id=alarm.id,
        alarm_type=alarm.alarm_type,
        status=alarm.status,
        message=alarm.message,
    )
