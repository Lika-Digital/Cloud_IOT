"""
Berth occupancy analyzer — calls the ML Worker microservice.

Architecture:
  32-bit FastAPI backend (this file)
      → HTTP POST http://ml_worker:8001/analyze/berth
      ← { occupied_bit, match_ok_bit, state_code, alarm, match_score, error }

The ML Worker (Docker, 64-bit Python) runs RT-DETR + DINOv2 via onnxruntime.

State codes:
  0 = FREE
  1 = OCCUPIED_CORRECT   (vessel detected, matches contracted ship)
  2 = OCCUPIED_WRONG     (vessel detected, ship does NOT match) → alarm = 1

Pilot expectations (with ONNX models loaded):
  "Berth Full.mp4"  + "Full_Berth.jpg" → state_code=2, alarm=1
  "Berth empty.mp4"                    → state_code=0, alarm=0
  (no video)                           → state_code=0, alarm=0

If the ML Worker is unreachable (not yet started, models missing, etc.),
the analyzer logs a warning and skips the DB/WS update for that cycle.
"""
import asyncio
import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

# URL of the ML Worker container (resolvable inside docker-compose network
# OR via localhost when running the worker with docker run -p 8001:8001)
ML_WORKER_URL = "http://localhost:8001"

# Per-request timeout for the ML worker (model inference can be slow on CPU)
ML_TIMEOUT_SECONDS = 60


async def _call_worker(payload: dict) -> dict:
    """POST to the ML Worker and return the parsed JSON response."""
    async with httpx.AsyncClient(timeout=ML_TIMEOUT_SECONDS) as client:
        resp = await client.post(f"{ML_WORKER_URL}/analyze/berth", json=payload)
        resp.raise_for_status()
        return resp.json()


async def run_berth_analysis():
    """
    Background asyncio task: analyze all berths every 30 s via the ML Worker.
    Updates DB status and broadcasts berth_occupancy_updated via WebSocket.
    """
    from ..auth.user_database import UserSessionLocal
    from ..auth.berth_models import Berth
    from ..services.websocket_manager import ws_manager

    logger.info("Berth analysis task started (interval=30 s, ML worker=%s)", ML_WORKER_URL)

    while True:
        await asyncio.sleep(30)
        try:
            db = UserSessionLocal()
            try:
                berths = db.query(Berth).all()
                updates = []

                for berth in berths:
                    payload = {
                        "video_source":           berth.video_source,
                        "reference_image":        berth.reference_image,
                        "background_image":       berth.background_image,
                        "detect_conf_threshold":  berth.detect_conf_threshold or 0.30,
                        "match_threshold":        berth.match_threshold or 0.50,
                        "use_detection_zone":     bool(berth.use_detection_zone),
                        "zone_x1":                berth.zone_x1 if berth.zone_x1 is not None else 0.20,
                        "zone_y1":                berth.zone_y1 if berth.zone_y1 is not None else 0.20,
                        "zone_x2":                berth.zone_x2 if berth.zone_x2 is not None else 0.80,
                        "zone_y2":                berth.zone_y2 if berth.zone_y2 is not None else 0.80,
                    }

                    try:
                        res = await _call_worker(payload)
                    except httpx.ConnectError:
                        logger.warning(
                            "ML Worker unreachable at %s — skipping this analysis cycle", ML_WORKER_URL
                        )
                        break   # Skip remaining berths too; try again next cycle
                    except Exception as exc:
                        logger.warning("ML Worker call failed for berth %d: %s", berth.id, exc)
                        res = {
                            "occupied_bit": 0, "match_ok_bit": 0,
                            "state_code": 0, "alarm": 0,
                            "match_score": None, "detection_score": None,
                            "error": str(exc),
                        }

                    # ── Persist ML outputs to DB ───────────────────────────
                    # Re-fetch in this session to avoid detached-instance issues
                    b = db.get(Berth, berth.id)
                    if b is None:
                        continue

                    b.occupied_bit    = res.get("occupied_bit", 0)
                    b.match_ok_bit    = res.get("match_ok_bit", 0)
                    b.state_code      = res.get("state_code",  0)
                    b.alarm           = res.get("alarm",       0)
                    b.match_score     = res.get("match_score")
                    b.analysis_error  = res.get("error")
                    b.last_analyzed   = datetime.utcnow()

                    # Update visible status (never override manually set "reserved")
                    if b.status != "reserved":
                        if b.occupied_bit == 1:
                            b.status = "occupied"
                            b.detected_status = "occupied"
                        else:
                            b.status = "free"
                            b.detected_status = "free"

                    db.commit()
                    db.refresh(b)

                    updates.append({
                        "id":               b.id,
                        "name":             b.name,
                        "status":           b.status,
                        "detected_status":  b.detected_status,
                        "pedestal_id":      b.pedestal_id,
                        "video_source":     b.video_source,
                        "last_analyzed":    b.last_analyzed.isoformat() if b.last_analyzed else None,
                        # ML pipeline outputs
                        "occupied_bit":     b.occupied_bit,
                        "match_ok_bit":     b.match_ok_bit,
                        "state_code":       b.state_code,
                        "alarm":            b.alarm,
                        "match_score":      b.match_score,
                        "analysis_error":   b.analysis_error,
                    })

                if updates:
                    await ws_manager.broadcast({
                        "event": "berth_occupancy_updated",
                        "data": {"berths": updates},
                    })
                    alarms = [u["name"] for u in updates if u["alarm"]]
                    logger.info(
                        "Berth analysis: %d berths updated — alarms: %s",
                        len(updates), alarms if alarms else "none",
                    )

            finally:
                db.close()

        except Exception as exc:
            logger.warning("Berth analysis cycle error: %s", exc)
