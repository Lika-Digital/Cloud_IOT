"""
Mock berth occupancy analyzer.

In production this would pull an RTSP frame and run RT-DETR object detection.
For the pilot we use a filename-based heuristic:
  - video_source contains "full" (case-insensitive)  → occupied
  - video_source contains "empty" (case-insensitive) → free
  - no video_source                                  → free (Transit / reserved berths)

The analyzer runs every 30 s as an asyncio background task.
It only updates berths that are NOT currently reserved — reserved berths
keep status="reserved" regardless of what the camera sees.
"""
import asyncio
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)


def _detect_from_filename(video_source: str | None) -> str:
    """Return 'occupied' or 'free' based on the video filename heuristic."""
    if not video_source:
        return "free"
    lower = video_source.lower()
    if "full" in lower:
        return "occupied"
    if "empty" in lower or "free" in lower:
        return "free"
    return "free"


def _is_berth_reserved_today(berth_id: int) -> bool:
    """Check whether a berth has an active reservation covering today."""
    from ..auth.user_database import UserSessionLocal
    from ..auth.berth_models import BerthReservation

    today = date.today()
    db = UserSessionLocal()
    try:
        res = (
            db.query(BerthReservation)
            .filter(
                BerthReservation.berth_id == berth_id,
                BerthReservation.status == "confirmed",
                BerthReservation.check_in_date <= today,
                BerthReservation.check_out_date >= today,
            )
            .first()
        )
        return res is not None
    finally:
        db.close()


async def run_berth_analysis():
    """
    Background task: analyze all berths every 30 s and broadcast results via WebSocket.
    """
    from ..auth.user_database import UserSessionLocal
    from ..auth.berth_models import Berth
    from ..services.websocket_manager import ws_manager

    while True:
        await asyncio.sleep(30)
        try:
            db = UserSessionLocal()
            try:
                berths = db.query(Berth).all()
                updates = []

                for berth in berths:
                    detected = _detect_from_filename(berth.video_source)
                    berth.detected_status = detected
                    berth.last_analyzed = datetime.utcnow()

                    # Don't override a reserved berth's status
                    if berth.status != "reserved":
                        berth.status = detected

                    db.commit()
                    db.refresh(berth)

                    updates.append({
                        "id": berth.id,
                        "name": berth.name,
                        "status": berth.status,
                        "detected_status": berth.detected_status,
                        "pedestal_id": berth.pedestal_id,
                        "video_source": berth.video_source,
                        "last_analyzed": berth.last_analyzed.isoformat() if berth.last_analyzed else None,
                    })

                await ws_manager.broadcast({
                    "event": "berth_occupancy_updated",
                    "data": {"berths": updates},
                })
                logger.debug("Berth analysis complete: %s berths updated", len(updates))
            finally:
                db.close()
        except Exception as e:
            logger.warning("Berth analysis error: %s", e)
