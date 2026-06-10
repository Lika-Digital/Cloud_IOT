"""Disk-space guard (v3.13).

A cheap, cached free-space check so the high-frequency write paths (telemetry)
can refuse to store when the disk is nearly full — surfacing a clear alarm and
pointing the operator at the clear-cache action — instead of crashing on ENOSPC
or silently dropping data.

`shutil.disk_usage` is cached for CHECK_INTERVAL_S so we never syscall per
insert. Fails OPEN: if the disk cannot be measured, writes are allowed (we never
block on a measurement error).
"""
import logging
import shutil
import time

logger = logging.getLogger(__name__)

# Refuse new buffered writes when free space drops below this many bytes.
MIN_FREE_BYTES = 500 * 1024 * 1024     # 500 MB
CHECK_INTERVAL_S = 30                    # cache disk_usage this long
_LOG_THROTTLE_S = 300                    # at most one "storage full" log / 5 min
PATH = "/"                               # NUC root; overridable in tests

_cache = {"at": 0.0, "free": None, "total": None}
_last_log = 0.0


def disk_status() -> dict:
    """Cached {free, total, free_pct, low_space}; refreshes on CHECK_INTERVAL_S."""
    if _cache["free"] is None or (time.monotonic() - _cache["at"]) > CHECK_INTERVAL_S:
        try:
            u = shutil.disk_usage(PATH)
            _cache.update(at=time.monotonic(), free=u.free, total=u.total)
        except Exception as e:
            logger.warning("disk_guard: disk_usage(%s) failed: %s", PATH, e)
            # Fail open — if we cannot measure, do not block writes.
            return {"free": None, "total": None, "free_pct": None, "low_space": False}
    free, total = _cache["free"], _cache["total"]
    free_pct = (free / total * 100) if total else None
    return {
        "free": free,
        "total": total,
        "free_pct": free_pct,
        "low_space": free is not None and free < MIN_FREE_BYTES,
    }


def has_free_space() -> bool:
    """True if there is room to keep buffering data (or measurement failed)."""
    return not disk_status()["low_space"]


def note_storage_full(log_fn) -> bool:
    """Throttled notifier: calls log_fn(message) at most once per _LOG_THROTTLE_S.

    Returns True when it actually logged this time (so the caller knows a fresh
    alarm was raised rather than a suppressed repeat).
    """
    global _last_log
    now = time.monotonic()
    if _last_log and (now - _last_log) < _LOG_THROTTLE_S:
        return False
    _last_log = now
    log_fn(
        "Storage nearly full — new telemetry is being dropped to protect the "
        "disk. Free space or clear cached data (System Health → Clear cached data)."
    )
    return True


def invalidate():
    """Force the next status check to re-read the disk (e.g. after a clear)."""
    _cache["at"] = 0.0
    _cache["free"] = None
    global _last_log
    _last_log = 0.0
