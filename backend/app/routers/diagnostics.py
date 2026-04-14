"""
Pedestal diagnostics endpoint.

POST /api/pedestals/{id}/diagnostics/run
  → Publishes MQTT diagnostic request
  → Waits up to 12s for pedestal response
  → Returns per-sensor pass/fail + overall status
  → Marks pedestal.initialized=True if all sensors pass
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models.pedestal import Pedestal
from ..services.diagnostics_manager import diagnostics_manager, EXPECTED_SENSORS
from ..services.mqtt_client import mqtt_service
from ..auth.dependencies import require_admin
from ..auth.models import User

router = APIRouter(prefix="/api/pedestals", tags=["diagnostics"])
logger = logging.getLogger(__name__)


@router.post("/{pedestal_id}/diagnostics/run")
async def run_diagnostics(pedestal_id: int, db: DBSession = Depends(get_db), _: User = Depends(require_admin)):
    """
    Send a diagnostics request to the pedestal via MQTT and wait for its response.

    Response schema:
    {
      "pedestal_id": int,
      "sensors": {
          "socket_1": "ok"|"fail"|"missing",
          "socket_2": ...,
          "socket_3": ...,
          "socket_4": ...,
          "water":       ...,
          "temperature": ...,
          "moisture":    ...,
          "camera":      ...
      },
      "all_ok": bool,
      "initialized": bool,
      "error": str | null
    }
    """
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")

    # ── Marina cabinet / Opta: send MQTT diagnostic request ─────────────────────
    from ..models.pedestal_config import PedestalConfig, SocketState
    cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pedestal_id).first()
    if cfg and getattr(cfg, "opta_client_id", None):
        cabinet_id = cfg.opta_client_id

        # Send diagnostic request to Opta via MQTT
        mqtt_service.publish(
            "opta/cmd/diagnostic",
            json.dumps({"cabinetId": cabinet_id, "request": "all"}),
        )
        logger.info(f"Diagnostics request sent to Opta cabinet {cabinet_id} (pedestal {pedestal_id})")

        # Wait for response on opta/diagnostic topic
        raw = await diagnostics_manager.wait_for_result(pedestal_id, timeout=12.0)

        if raw is not None:
            # Opta responded — use its result
            sensors = {s: raw.get(s, "missing") for s in EXPECTED_SENSORS}
            all_ok = all(v == "ok" for v in sensors.values())
        else:
            # Opta didn't respond — fall back to DB-derived state
            logger.warning(f"No diagnostic response from Opta {cabinet_id} — falling back to DB state")
            connected = bool(cfg.opta_connected)
            socket_states = {
                ss.socket_id: ss.connected
                for ss in db.query(SocketState).filter(SocketState.pedestal_id == pedestal_id).all()
            }
            sensors = {}
            for i in range(1, 5):
                if i in socket_states:
                    sensors[f"socket_{i}"] = "ok" if socket_states[i] else "fail"
                else:
                    sensors[f"socket_{i}"] = "ok" if connected else "missing"
            sensors["water"]       = "ok" if connected else "missing"
            sensors["temperature"] = "ok" if connected else "missing"
            sensors["moisture"]    = "ok" if connected else "missing"
            sensors["camera"]      = "missing"
            all_ok = connected

        if all_ok and not pedestal.initialized:
            pedestal.initialized = True
            db.commit()
            db.refresh(pedestal)
            logger.info(f"Marina cabinet {cabinet_id} (pedestal {pedestal_id}) marked as initialized")

        return {
            "pedestal_id": pedestal_id,
            "sensors": sensors,
            "all_ok": all_ok,
            "initialized": pedestal.initialized,
            "error": None if raw is not None else f"No response from Opta {cabinet_id} — showing cached state.",
        }

    # ── Legacy pedestal: MQTT diagnostics request/response ────────────────────
    mqtt_service.publish(
        f"pedestal/{pedestal_id}/diagnostics/request",
        json.dumps({"request": "all"}),
    )
    logger.info(f"Diagnostics request sent to pedestal {pedestal_id}")

    # Wait for response
    raw = await diagnostics_manager.wait_for_result(pedestal_id, timeout=12.0)

    if raw is None:
        return {
            "pedestal_id": pedestal_id,
            "sensors": {s: "missing" for s in EXPECTED_SENSORS},
            "all_ok": False,
            "initialized": pedestal.initialized,
            "error": "No response from pedestal — check that it is powered on and connected to the MQTT broker.",
        }

    # Normalise: fill in any missing sensors as "missing"
    sensors = {s: raw.get(s, "missing") for s in EXPECTED_SENSORS}
    all_ok = all(v == "ok" for v in sensors.values())

    # Persist initialization status
    if all_ok and not pedestal.initialized:
        pedestal.initialized = True
        db.commit()
        db.refresh(pedestal)
        logger.info(f"Pedestal {pedestal_id} marked as initialized")

    return {
        "pedestal_id": pedestal_id,
        "sensors": sensors,
        "all_ok": all_ok,
        "initialized": pedestal.initialized,
        "error": None,
    }


@router.post("/{pedestal_id}/diagnostics/reset")
def reset_initialization(pedestal_id: int, db: DBSession = Depends(get_db), _: User = Depends(require_admin)):
    """Mark a pedestal as not initialized (e.g. after hardware change)."""
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    pedestal.initialized = False
    db.commit()
    db.refresh(pedestal)
    return {"pedestal_id": pedestal_id, "initialized": False}
