"""
Storage Monitor — tracks disk usage of the training_data directory.

Background task `run_storage_monitor()` runs every 5 minutes and broadcasts
a WebSocket alarm when usage exceeds STORAGE_ALARM_THRESHOLD (80%).

Public API:
    get_training_storage_status() -> dict
    run_storage_monitor()         -> coroutine (background task)
    alarm_active                  -> bool (module-level state)
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

STORAGE_ALARM_THRESHOLD: float = 0.80   # 80 %
_CHECK_INTERVAL_SECONDS: int   = 300    # 5 minutes

# Module-level alarm state (updated by background task)
_alarm_active: bool = False


def get_training_storage_status() -> dict:
    """
    Return current training-data storage status.

    Returns:
        {
            "size_gb":      float,   # bytes actually used
            "max_gb":       float,   # configured cap
            "percent_used": float,   # 0.0 – 1.0
            "alarm_active": bool,
        }
    """
    from .training_data import TRAINING_DATA_DIR, TRAINING_DATA_MAX_GB

    total_bytes = 0
    if os.path.isdir(TRAINING_DATA_DIR):
        for dirpath, _dirs, files in os.walk(TRAINING_DATA_DIR):
            for fname in files:
                try:
                    total_bytes += os.path.getsize(os.path.join(dirpath, fname))
                except OSError:
                    pass

    max_bytes = TRAINING_DATA_MAX_GB * 1024 ** 3
    size_gb   = total_bytes / (1024 ** 3)
    percent   = total_bytes / max_bytes if max_bytes > 0 else 0.0

    return {
        "size_gb":      round(size_gb, 4),
        "max_gb":       TRAINING_DATA_MAX_GB,
        "percent_used": round(percent, 4),
        "alarm_active": _alarm_active,
    }


async def run_storage_monitor():
    """
    Background coroutine: check training-data storage every 5 minutes.
    Broadcasts via WebSocket when alarm state changes.
    """
    global _alarm_active

    logger.info("Storage monitor started — checking every %d s", _CHECK_INTERVAL_SECONDS)

    while True:
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
        try:
            status = get_training_storage_status()
            new_alarm = status["percent_used"] >= STORAGE_ALARM_THRESHOLD

            if new_alarm != _alarm_active:
                _alarm_active = new_alarm
                try:
                    from .websocket_manager import ws_manager
                    await ws_manager.broadcast({
                        "event": "training_storage_alarm",
                        "data": {
                            "alarm":        _alarm_active,
                            "percent_used": status["percent_used"],
                            "size_gb":      status["size_gb"],
                            "max_gb":       status["max_gb"],
                        },
                    })
                    logger.info(
                        "Storage monitor: alarm=%s (%.1f%% of %.1f GB used)",
                        _alarm_active,
                        status["percent_used"] * 100,
                        status["max_gb"],
                    )
                except Exception as exc:
                    logger.warning("Storage monitor: broadcast error: %s", exc)
        except Exception as exc:
            logger.warning("Storage monitor: check error: %s", exc)
