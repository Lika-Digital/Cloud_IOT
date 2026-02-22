"""
Central error logging service.

Usage anywhere in the codebase:
    from ..services.error_log_service import log_error, log_warning, log_info

All calls are synchronous and safe to call from both sync and async contexts.
Errors are stored in pedestal.db (error_logs table) and broadcast via WebSocket.
Records older than 7 days are automatically purged on startup and hourly.
"""
import logging
import traceback
from datetime import datetime, timedelta

from ..database import SessionLocal
from ..models.error_log import ErrorLog

logger = logging.getLogger(__name__)

RETENTION_DAYS = 7


# ─── Public API ──────────────────────────────────────────────────────────────

def log_error(
    category: str,   # 'system' | 'hw'
    source: str,
    message: str,
    details: str | None = None,
    exc: Exception | None = None,
) -> ErrorLog | None:
    """Log an ERROR-level event. Pass exc to capture traceback automatically."""
    if exc and details is None:
        details = traceback.format_exc()
    return _write("error", category, source, message, details)


def log_warning(
    category: str,
    source: str,
    message: str,
    details: str | None = None,
) -> ErrorLog | None:
    return _write("warning", category, source, message, details)


def log_info(
    category: str,
    source: str,
    message: str,
    details: str | None = None,
) -> ErrorLog | None:
    return _write("info", category, source, message, details)


# ─── Cleanup ─────────────────────────────────────────────────────────────────

def purge_old_logs():
    """Delete logs older than RETENTION_DAYS. Called on startup and hourly."""
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    db = SessionLocal()
    try:
        deleted = db.query(ErrorLog).filter(ErrorLog.created_at < cutoff).delete()
        db.commit()
        if deleted:
            logger.info(f"Purged {deleted} error log entries older than {RETENTION_DAYS} days")
    except Exception as e:
        logger.error(f"Failed to purge old error logs: {e}")
    finally:
        db.close()


def get_logs(
    limit: int = 500,
    category: str | None = None,
    level: str | None = None,
    since_hours: int = 168,  # 7 days
) -> list[ErrorLog]:
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    db = SessionLocal()
    try:
        q = db.query(ErrorLog).filter(ErrorLog.created_at >= cutoff)
        if category:
            q = q.filter(ErrorLog.category == category)
        if level:
            q = q.filter(ErrorLog.level == level)
        return q.order_by(ErrorLog.created_at.desc()).limit(limit).all()
    finally:
        db.close()


def get_summary() -> dict:
    """Returns counts for the last 24h and 7d for the health dashboard."""
    now = datetime.utcnow()
    db = SessionLocal()
    try:
        def _count(since: datetime, category: str | None = None, level: str | None = None) -> int:
            q = db.query(ErrorLog).filter(ErrorLog.created_at >= since)
            if category:
                q = q.filter(ErrorLog.category == category)
            if level:
                q = q.filter(ErrorLog.level == level)
            return q.count()

        last_24h = now - timedelta(hours=24)
        last_7d  = now - timedelta(days=7)

        return {
            "total_7d":       _count(last_7d),
            "errors_7d":      _count(last_7d,  level="error"),
            "warnings_7d":    _count(last_7d,  level="warning"),
            "system_errors":  _count(last_7d,  category="system", level="error"),
            "hw_errors":      _count(last_7d,  category="hw",     level="error"),
            "hw_warnings":    _count(last_7d,  category="hw",     level="warning"),
            "last_24h_total": _count(last_24h),
            "last_24h_errors":_count(last_24h, level="error"),
        }
    finally:
        db.close()


def clear_all_logs():
    db = SessionLocal()
    try:
        count = db.query(ErrorLog).delete()
        db.commit()
        return count
    finally:
        db.close()


# ─── Internal ────────────────────────────────────────────────────────────────

def _write(
    level: str,
    category: str,
    source: str,
    message: str,
    details: str | None,
) -> ErrorLog | None:
    # Also emit to Python logger so it still appears in the terminal
    log_fn = {"error": logger.error, "warning": logger.warning}.get(level, logger.info)
    log_fn(f"[{category.upper()}] {source}: {message}")

    db = SessionLocal()
    try:
        entry = ErrorLog(
            level=level,
            category=category,
            source=source[:100],
            message=message[:500],
            details=details,
            created_at=datetime.utcnow(),
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)

        # Broadcast via WebSocket (non-blocking, fire-and-forget)
        _broadcast_async(entry)

        return entry
    except Exception as e:
        logger.error(f"Failed to write error log: {e}")
        return None
    finally:
        db.close()


def _broadcast_async(entry: ErrorLog):
    """Push the log entry to all WebSocket clients in a non-blocking way."""
    import asyncio
    try:
        from .websocket_manager import ws_manager
        payload = {
            "event": "error_logged",
            "data": {
                "id": entry.id,
                "level": entry.level,
                "category": entry.category,
                "source": entry.source,
                "message": entry.message,
                "created_at": entry.created_at.isoformat(),
            },
        }
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        if loop and loop.is_running():
            loop.create_task(ws_manager.broadcast(payload))
        else:
            # Called from a sync thread (e.g. MQTT callback)
            try:
                loop = asyncio._get_running_loop()  # may be None
            except Exception:
                loop = None
            if loop:
                asyncio.run_coroutine_threadsafe(ws_manager.broadcast(payload), loop)
    except Exception:
        pass  # Never let broadcasting crash the caller
