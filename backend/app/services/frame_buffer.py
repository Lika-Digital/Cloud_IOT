"""
Frame Buffer Service — rolling 10-second JPEG snapshot per camera.

Maintains a module-level dict mapping pedestal_id → latest JPEG bytes.
A background coroutine `run_frame_buffer()` refreshes each camera every 10 s.

All opencv/numpy imports are inside try/except so the module imports cleanly
on 32-bit dev machines where those wheels may not be available.
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Singleton buffer: pedestal_id → latest JPEG bytes (or None)
_buffer: dict[int, Optional[bytes]] = {}


def get_latest_frame(pedestal_id: int) -> Optional[bytes]:
    """Return the latest buffered JPEG bytes for a pedestal, or None if unavailable."""
    return _buffer.get(pedestal_id)


async def run_frame_buffer():
    """
    Background coroutine: every 10 seconds, grab a fresh snapshot from every
    pedestal camera that is currently marked reachable, and store it in _buffer.

    Errors are logged but never crash the loop.
    """
    logger.info("Frame buffer service started — polling interval 10 s")

    while True:
        await asyncio.sleep(10)
        try:
            await _refresh_all_frames()
        except Exception as exc:
            logger.warning("Frame buffer: unexpected error in refresh loop: %s", exc)


async def _refresh_all_frames():
    """Query all reachable cameras and update the buffer."""
    # Import database inside function to avoid circular import issues at module load time
    from ..database import SessionLocal
    from ..models.pedestal_config import PedestalConfig

    db = SessionLocal()
    try:
        configs = db.query(PedestalConfig).filter(
            PedestalConfig.camera_reachable == 1,
            PedestalConfig.camera_stream_url.isnot(None),
            PedestalConfig.camera_stream_url != "",
        ).all()
    finally:
        db.close()

    if not configs:
        return

    # Fire all snapshots concurrently, bounded by a per-camera timeout
    tasks = [
        asyncio.create_task(_fetch_and_store(cfg.pedestal_id, cfg.camera_stream_url,
                                              cfg.camera_username or "", cfg.camera_password or ""))
        for cfg in configs
    ]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _fetch_and_store(pedestal_id: int, stream_url: str,
                            username: str, password: str):
    """Grab one snapshot and store in _buffer.  Never raises."""
    try:
        from .berth_analyzer import grab_snapshot
        jpeg_bytes = await grab_snapshot(stream_url, username=username, password=password)
        _buffer[pedestal_id] = jpeg_bytes
        logger.debug("Frame buffer: updated pedestal %d (%d bytes)", pedestal_id, len(jpeg_bytes))
    except Exception as exc:
        # Log but do NOT store None — keep the previous frame if any
        logger.warning("Frame buffer: snapshot failed for pedestal %d: %s", pedestal_id, exc)
