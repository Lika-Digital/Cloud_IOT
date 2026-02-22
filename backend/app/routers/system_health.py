"""System Health API — error logs, stats, cleanup."""
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from ..auth.dependencies import require_admin
from ..auth.models import User
from ..services.error_log_service import get_logs, get_summary, clear_all_logs, purge_old_logs
from ..services.mqtt_client import mqtt_service
from ..services.simulator_manager import simulator_manager

router = APIRouter(prefix="/api/system", tags=["system-health"])


class ErrorLogResponse(BaseModel):
    id: int
    level: str
    category: str
    source: str
    message: str
    details: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class HealthSummaryResponse(BaseModel):
    total_7d: int
    errors_7d: int
    warnings_7d: int
    system_errors: int
    hw_errors: int
    hw_warnings: int
    last_24h_total: int
    last_24h_errors: int
    mqtt_connected: bool
    simulator_running: bool


@router.get("/health", response_model=HealthSummaryResponse)
def health_summary(_: User = Depends(require_admin)):
    summary = get_summary()
    return HealthSummaryResponse(
        **summary,
        mqtt_connected=mqtt_service.is_connected,
        simulator_running=simulator_manager.is_running,
    )


@router.get("/logs", response_model=list[ErrorLogResponse])
def get_error_logs(
    category: Optional[str] = Query(default=None, description="system | hw"),
    level: Optional[str] = Query(default=None, description="error | warning | info"),
    hours: int = Query(default=168, ge=1, le=168, description="Look-back window (max 168 = 7 days)"),
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
    """Manually trigger purge of logs older than 7 days."""
    purge_old_logs()
    return {"message": "Purge complete"}
