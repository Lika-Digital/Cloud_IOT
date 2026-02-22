"""
Alarm lifecycle service.

Public API:
    trigger_alarm(alarm_type, source, message, pedestal_id, details, deduplicate)
        -> ActiveAlarm | None
    acknowledge_alarm(alarm_id, operator_email) -> ActiveAlarm | None
    get_active_alarms()           -> list[ActiveAlarm]
    get_alarm_history(limit, since_hours) -> list[ActiveAlarm]
    get_active_alarm_count()      -> int

Deduplication (default on):
    If an alarm of the same type + pedestal_id is already 'triggered',
    a new record is NOT created to prevent sensor-spam when readings
    arrive every second. Set deduplicate=False to override (e.g. security events).
"""
import asyncio
import logging
from datetime import datetime, timedelta

from ..database import SessionLocal
from ..models.active_alarm import ActiveAlarm

logger = logging.getLogger(__name__)


def trigger_alarm(
    alarm_type: str,
    source: str,
    message: str,
    pedestal_id: int | None = None,
    details: str | None = None,
    deduplicate: bool = True,
) -> ActiveAlarm | None:
    db = SessionLocal()
    try:
        if deduplicate:
            existing = (
                db.query(ActiveAlarm)
                .filter(
                    ActiveAlarm.alarm_type == alarm_type,
                    ActiveAlarm.pedestal_id == pedestal_id,
                    ActiveAlarm.status == "triggered",
                )
                .first()
            )
            if existing:
                return existing  # already active, don't create duplicate

        alarm = ActiveAlarm(
            alarm_type=alarm_type,
            source=source,
            pedestal_id=pedestal_id,
            status="triggered",
            message=message[:500],
            details=details,
            triggered_at=datetime.utcnow(),
        )
        db.add(alarm)
        db.commit()
        db.refresh(alarm)
        _broadcast(alarm, "alarm_triggered")
        return alarm
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to trigger alarm ({alarm_type}): {e}")
        return None
    finally:
        db.close()


def acknowledge_alarm(alarm_id: int, operator_email: str) -> ActiveAlarm | None:
    db = SessionLocal()
    try:
        alarm = db.get(ActiveAlarm, alarm_id)
        if not alarm or alarm.status != "triggered":
            return None
        alarm.status = "acknowledged"
        alarm.acknowledged_at = datetime.utcnow()
        alarm.acknowledged_by = operator_email
        db.commit()
        db.refresh(alarm)
        _broadcast(alarm, "alarm_acknowledged")
        return alarm
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to acknowledge alarm {alarm_id}: {e}")
        return None
    finally:
        db.close()


def get_active_alarms() -> list[ActiveAlarm]:
    db = SessionLocal()
    try:
        return (
            db.query(ActiveAlarm)
            .filter(ActiveAlarm.status == "triggered")
            .order_by(ActiveAlarm.triggered_at.desc())
            .all()
        )
    finally:
        db.close()


def get_alarm_history(limit: int = 200, since_hours: int = 168) -> list[ActiveAlarm]:
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    db = SessionLocal()
    try:
        return (
            db.query(ActiveAlarm)
            .filter(ActiveAlarm.triggered_at >= cutoff)
            .order_by(ActiveAlarm.triggered_at.desc())
            .limit(limit)
            .all()
        )
    finally:
        db.close()


def get_active_alarm_count() -> int:
    db = SessionLocal()
    try:
        return db.query(ActiveAlarm).filter(ActiveAlarm.status == "triggered").count()
    finally:
        db.close()


# ─── Internal ─────────────────────────────────────────────────────────────────

def _broadcast(alarm: ActiveAlarm, event: str):
    """Async-safe, fire-and-forget WS broadcast. Never raises."""
    try:
        from .websocket_manager import ws_manager
        payload = {
            "event": event,
            "data": {
                "id": alarm.id,
                "alarm_type": alarm.alarm_type,
                "source": alarm.source,
                "pedestal_id": alarm.pedestal_id,
                "status": alarm.status,
                "message": alarm.message,
                "triggered_at": alarm.triggered_at.isoformat(),
                "acknowledged_at": alarm.acknowledged_at.isoformat() if alarm.acknowledged_at else None,
                "acknowledged_by": alarm.acknowledged_by,
            },
        }
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        if loop and loop.is_running():
            loop.create_task(ws_manager.broadcast(payload))
        else:
            try:
                loop = asyncio._get_running_loop()  # type: ignore[attr-defined]
            except Exception:
                loop = None
            if loop:
                asyncio.run_coroutine_threadsafe(ws_manager.broadcast(payload), loop)
    except Exception:
        pass
