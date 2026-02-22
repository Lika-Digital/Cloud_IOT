"""System Health API — error logs, alarms, cybersecurity, stats, cleanup."""
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from ..auth.dependencies import require_admin
from ..auth.models import User
from ..services.error_log_service import get_logs, get_summary, clear_all_logs, purge_old_logs
from ..services.alarm_service import get_active_alarms, get_active_alarm_count
from ..services.mqtt_client import mqtt_service
from ..services.simulator_manager import simulator_manager

router = APIRouter(prefix="/api/system", tags=["system-health"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class ErrorLogResponse(BaseModel):
    id: int
    level: str
    category: str     # system | hw | security | alarm
    source: str
    message: str
    details: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AlarmSummary(BaseModel):
    active_count: int
    fire_active: int
    temperature_active: int
    moisture_active: int
    unauthorized_entry_active: int
    comm_loss_active: int
    operational_failure_active: int
    security_active: int


class SecuritySummary(BaseModel):
    events_24h: int
    events_7d: int
    brute_force_7d: int
    unauthorized_access_7d: int


class HealthSummaryResponse(BaseModel):
    # Existing error-log stats
    total_7d: int
    errors_7d: int
    warnings_7d: int
    system_errors: int
    hw_errors: int
    hw_warnings: int
    last_24h_total: int
    last_24h_errors: int
    # Infrastructure
    mqtt_connected: bool
    simulator_running: bool
    # New
    alarm_summary: AlarmSummary
    security_summary: SecuritySummary


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthSummaryResponse)
def health_summary(_: User = Depends(require_admin)):
    summary = get_summary()

    # Alarm breakdown
    active = get_active_alarms()
    def _count(t: str) -> int:
        return sum(1 for a in active if a.alarm_type == t)

    alarm_sum = AlarmSummary(
        active_count=len(active),
        fire_active=_count("fire"),
        temperature_active=_count("temperature"),
        moisture_active=_count("moisture"),
        unauthorized_entry_active=_count("unauthorized_entry"),
        comm_loss_active=_count("comm_loss"),
        operational_failure_active=_count("operational_failure"),
        security_active=_count("security"),
    )

    # Security event counts from error_log (category='security')
    sec_logs_24h = get_logs(limit=1000, category="security", since_hours=24)
    sec_logs_7d  = get_logs(limit=5000, category="security", since_hours=168)

    sec_sum = SecuritySummary(
        events_24h=len(sec_logs_24h),
        events_7d=len(sec_logs_7d),
        brute_force_7d=sum(1 for e in sec_logs_7d if "brute" in e.message.lower()),
        unauthorized_access_7d=sum(1 for e in sec_logs_7d if "403" in e.message or "unauthoris" in e.message.lower()),
    )

    return HealthSummaryResponse(
        **summary,
        mqtt_connected=mqtt_service.is_connected,
        simulator_running=simulator_manager.is_running,
        alarm_summary=alarm_sum,
        security_summary=sec_sum,
    )


@router.get("/logs", response_model=list[ErrorLogResponse])
def get_error_logs(
    category: Optional[str] = Query(default=None, description="system | hw | security | alarm"),
    level: Optional[str] = Query(default=None, description="error | warning | info"),
    hours: int = Query(default=168, ge=1, le=168),
    limit: int = Query(default=500, ge=1, le=1000),
    _: User = Depends(require_admin),
):
    return get_logs(limit=limit, category=category, level=level, since_hours=hours)


@router.delete("/logs")
def clear_logs(_: User = Depends(require_admin)):
    count = clear_all_logs()
    return {"deleted": count, "message": f"Cleared {count} log entries"}


@router.post("/logs/purge")
def manual_purge(_: User = Depends(require_admin)):
    purge_old_logs()
    return {"message": "Purge complete"}
