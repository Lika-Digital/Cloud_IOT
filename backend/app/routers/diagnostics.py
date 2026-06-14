"""
Pedestal diagnostics endpoint.

POST /api/pedestals/{id}/diagnostics/run
  → Publishes MQTT diagnostic request
  → Waits up to 12s for pedestal response
  → Returns per-sensor pass/fail + overall status
  → Marks pedestal.initialized=True if all sensors respond (status known)
"""
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models.pedestal import Pedestal
from ..services.diagnostics_manager import diagnostics_manager, EXPECTED_SENSORS, LEGACY_SENSORS
from ..services.mqtt_client import mqtt_service
from ..auth.dependencies import require_admin
from ..auth.models import User

router = APIRouter(prefix="/api/pedestals", tags=["diagnostics"])
logger = logging.getLogger(__name__)


async def _await_diag_event(event: asyncio.Event, timeout: float = 12.0) -> None:
    """Awaitable seam around asyncio.wait_for so tests can stub the wait without
    touching the global event loop. Raises asyncio.TimeoutError on timeout."""
    await asyncio.wait_for(event.wait(), timeout=timeout)


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
          "moisture":    ...
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

        # Register the waiter BEFORE publishing to avoid race condition
        # (Opta can respond within milliseconds)
        event = asyncio.Event()
        diagnostics_manager._events[pedestal_id] = event

        # Stamp the diagnostic-in-progress window so auto-activation knows to
        # skip for the next 60 seconds (v3.5 precondition check).
        from datetime import datetime as _dt
        from ..services.mqtt_handlers import last_diagnostic_at
        last_diagnostic_at[pedestal_id] = _dt.utcnow()

        # Send diagnostic request to Opta via MQTT
        mqtt_service.publish(
            "opta/cmd/diagnostic",
            json.dumps({"cabinetId": cabinet_id, "request": "all"}),
        )
        logger.info(f"Diagnostics request sent to Opta cabinet {cabinet_id} (pedestal {pedestal_id})")

        # Wait for response on opta/diagnostic topic
        try:
            await _await_diag_event(event, 12.0)
            raw = diagnostics_manager._results.get(pedestal_id)
        except asyncio.TimeoutError:
            logger.warning(f"Diagnostics timeout for Opta {cabinet_id} (pedestal {pedestal_id})")
            raw = None
        finally:
            diagnostics_manager._events.pop(pedestal_id, None)
            diagnostics_manager._results.pop(pedestal_id, None)

        if raw is not None:
            # Opta responded — use its mapped result
            sensors = {s: raw.get(s, "missing") for s in EXPECTED_SENSORS}
            # B3b (v3.21) — only sensors the cabinet actually reports (not "missing")
            # count toward the verdict; phantom/absent sensors (temperature, moisture,
            # camera on an Opta cabinet) neither pass nor block initialization.
            present = {k: v for k, v in sensors.items() if v != "missing"}
            all_ok = bool(present) and all(v == "ok" for v in present.values())

            if all_ok and not pedestal.initialized:
                pedestal.initialized = True
                db.commit()
                db.refresh(pedestal)
                logger.info(f"Marina cabinet {cabinet_id} (pedestal {pedestal_id}) marked as initialized")

            return {
                "pedestal_id": pedestal_id,
                "sensors": sensors,
                "all_ok": all_ok,
                "status": "ok" if all_ok else "fault",
                "initialized": pedestal.initialized,
                "error": None,
            }

        # B3 (v3.21) — no fresh diagnostic response within the timeout window.
        # Report honestly: never synthesize an OK from the cached opta_connected
        # flag. The result must reflect what the device actually reported.
        logger.warning(f"No diagnostic response from Opta {cabinet_id} within timeout window")
        return {
            "pedestal_id": pedestal_id,
            "sensors": {s: "missing" for s in EXPECTED_SENSORS},
            "all_ok": False,
            "status": "unknown",
            "initialized": pedestal.initialized,
            "error": "No diagnostic response received from device",
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
            "sensors": {s: "missing" for s in LEGACY_SENSORS},
            "all_ok": False,
            "status": "unknown",
            "initialized": pedestal.initialized,
            "error": "No response from pedestal — check that it is powered on and connected to the MQTT broker.",
        }

    # Normalise: fill in any missing sensors as "missing" (no camera for legacy pedestals)
    sensors = {s: raw.get(s, "missing") for s in LEGACY_SENSORS}
    # Initialized = all sensors responded (status known), regardless of ok/fail
    all_ok = all(v != "missing" for v in sensors.values())

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
        "status": "ok" if all_ok else "fault",
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
