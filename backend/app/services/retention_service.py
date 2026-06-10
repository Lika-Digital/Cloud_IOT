"""Telemetry & operational-log retention (v3.13).

Deletes high-volume *buffer* data older than RETENTION_DAYS so the SQLite
database — and the NUC disk — stay bounded. Mirrors
``error_log_service.purge_old_logs()``: run once on startup and hourly.

Scope is **telemetry + operational logs ONLY**. Business / legal / forensic
records are NEVER touched here:

    PRUNED (>7 days):                 KEPT FOREVER:
      sensor_readings*                  sessions      (billing totals)
      auto_activation_log               invoices      (financial record)
      meter_load_alarms (resolved)      contracts     (legal record)
      active_alarms (acknowledged)      customers     (account/PII)
                                        chat_messages (communication record)
                                        breaker_events (forensic trail)
                                        error_logs    (own 7-day purge)

    * sensor_readings tied to a still-open (pending/active) session are never
      pruned, so an in-progress session's data is safe across the cutoff.

Pruning raw sensor_readings is billing/analytics/history-safe because session
energy_kwh / water_liters totals are persisted on the ``sessions`` row (and
snapshotted onto the ``invoices`` row) at completion — every downstream
consumer reads those persisted totals, not the raw readings.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import or_

from ..database import SessionLocal
from ..models.sensor_reading import SensorReading
from ..models.session import Session
from ..models.auto_activation_log import AutoActivationLog
from ..models.meter_load_alarm import MeterLoadAlarm
from ..models.active_alarm import ActiveAlarm

logger = logging.getLogger(__name__)

RETENTION_DAYS = 7


def purge_old_data(retention_days: int = RETENTION_DAYS) -> dict:
    """Delete telemetry / operational rows older than ``retention_days``.

    Returns a dict of ``{table: rows_deleted}``. Never raises — a failure is
    logged and an all-zero (or partial) count is returned so the scheduler
    loop keeps running.
    """
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    counts = {
        "sensor_readings": 0,
        "auto_activation_log": 0,
        "meter_load_alarms": 0,
        "active_alarms": 0,
    }
    db = SessionLocal()
    try:
        # Guard: never prune readings that belong to a session still open
        # (pending/active) — its totals are not finalised yet.
        open_ids = [
            row[0] for row in db.query(Session.id)
            .filter(Session.status.in_(("pending", "active"))).all()
        ]

        sr_q = db.query(SensorReading).filter(SensorReading.timestamp < cutoff)
        if open_ids:
            # notin_() alone would skip NULL session_id rows (SQL NULL logic),
            # so explicitly include unattached readings.
            sr_q = sr_q.filter(or_(
                SensorReading.session_id.is_(None),
                SensorReading.session_id.notin_(open_ids),
            ))
        counts["sensor_readings"] = sr_q.delete(synchronize_session=False)

        counts["auto_activation_log"] = (
            db.query(AutoActivationLog)
            .filter(AutoActivationLog.timestamp < cutoff)
            .delete(synchronize_session=False)
        )

        # Only resolved (historical) load alarms; open alarms stay visible.
        counts["meter_load_alarms"] = (
            db.query(MeterLoadAlarm)
            .filter(
                MeterLoadAlarm.triggered_at < cutoff,
                MeterLoadAlarm.resolved_at.isnot(None),
            )
            .delete(synchronize_session=False)
        )

        # Only acknowledged (historical) alarms; 'triggered' ones stay open.
        counts["active_alarms"] = (
            db.query(ActiveAlarm)
            .filter(
                ActiveAlarm.triggered_at < cutoff,
                ActiveAlarm.status == "acknowledged",
            )
            .delete(synchronize_session=False)
        )

        db.commit()
        total = sum(counts.values())
        if total:
            logger.info(
                "Retention purge: deleted %d rows older than %d days (%s)",
                total, retention_days,
                ", ".join(f"{k}={v}" for k, v in counts.items() if v),
            )
        return counts
    except Exception as e:
        db.rollback()
        logger.error("Retention purge failed: %s", e)
        return counts
    finally:
        db.close()


def clear_telemetry_buffer(db=None) -> int:
    """Emergency on-demand clear of the telemetry buffer (sensor_readings).

    Deletes ALL sensor_readings regardless of age, EXCEPT rows belonging to a
    still-open (pending/active) session (so an in-progress session's billing
    total is preserved). Returns rows deleted. Used by the admin
    ``POST /api/system/cache/clear`` action to free disk space immediately.

    Pass ``db`` to reuse a request-scoped session (testable); otherwise opens
    its own.
    """
    own = db is None
    if own:
        db = SessionLocal()
    try:
        open_ids = [
            row[0] for row in db.query(Session.id)
            .filter(Session.status.in_(("pending", "active"))).all()
        ]
        q = db.query(SensorReading)
        if open_ids:
            q = q.filter(or_(
                SensorReading.session_id.is_(None),
                SensorReading.session_id.notin_(open_ids),
            ))
        deleted = q.delete(synchronize_session=False)
        db.commit()
        logger.info("Telemetry buffer cleared: %d sensor_readings deleted", deleted)
        return deleted
    except Exception as e:
        db.rollback()
        logger.error("clear_telemetry_buffer failed: %s", e)
        return 0
    finally:
        if own:
            db.close()
