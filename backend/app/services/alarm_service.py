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
from ..time_utils import iso_z

logger = logging.getLogger(__name__)


def trigger_alarm(
    alarm_type: str,
    source: str,
    message: str,
    pedestal_id: int | None = None,
    details: str | None = None,
    deduplicate: bool = True,
    severity: str | None = None,
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
                # v3.23 — escalate/de-escalate an already-active alarm in place
                # (e.g. temperature warning -> critical) instead of spawning a
                # duplicate. Re-broadcast only when something actually changed.
                changed = False
                if severity is not None and existing.severity != severity:
                    existing.severity = severity
                    changed = True
                if message and existing.message != message[:500]:
                    existing.message = message[:500]
                    changed = True
                if changed:
                    db.commit()
                    db.refresh(existing)
                    _broadcast(existing, "alarm_triggered")
                return existing

        alarm = ActiveAlarm(
            alarm_type=alarm_type,
            source=source,
            pedestal_id=pedestal_id,
            status="triggered",
            severity=severity,
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


def has_active_alarm(alarm_type: str, pedestal_id: int | None) -> bool:
    """v3.23 — True if a 'triggered' alarm of this type+pedestal exists.
    Used by the temperature poller to apply clearing hysteresis."""
    db = SessionLocal()
    try:
        return (
            db.query(ActiveAlarm)
            .filter(
                ActiveAlarm.alarm_type == alarm_type,
                ActiveAlarm.pedestal_id == pedestal_id,
                ActiveAlarm.status == "triggered",
            )
            .first()
            is not None
        )
    finally:
        db.close()


def resolve_alarm_type(alarm_type: str, pedestal_id: int | None) -> int:
    """v3.23 — auto-resolve every 'triggered' alarm of this type+pedestal
    (sets status='resolved', resolved_at=now) and broadcasts 'alarm_resolved'.
    Returns the number resolved. Used when a self-healing condition (e.g. the
    temperature returning to normal) clears."""
    db = SessionLocal()
    try:
        alarms = (
            db.query(ActiveAlarm)
            .filter(
                ActiveAlarm.alarm_type == alarm_type,
                ActiveAlarm.pedestal_id == pedestal_id,
                ActiveAlarm.status == "triggered",
            )
            .all()
        )
        if not alarms:
            return 0
        now = datetime.utcnow()
        for a in alarms:
            a.status = "resolved"
            a.resolved_at = now
        db.commit()
        for a in alarms:
            db.refresh(a)
            _broadcast(a, "alarm_resolved")
        return len(alarms)
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to resolve alarms ({alarm_type}, pedestal={pedestal_id}): {e}")
        return 0
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
                "severity": getattr(alarm, "severity", None),
                "message": alarm.message,
                "triggered_at": iso_z(alarm.triggered_at),
                "acknowledged_at": iso_z(alarm.acknowledged_at),
                "acknowledged_by": alarm.acknowledged_by,
                "resolved_at": iso_z(alarm.resolved_at) if getattr(alarm, "resolved_at", None) else None,
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
