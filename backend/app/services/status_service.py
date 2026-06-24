"""System status snapshot files (v3.16) — MQTT broker + connected devices.

Writes two JSON files for offline/SSH troubleshooting AND backs the
/api/system/{mqtt-status,devices-status} endpoints (shared pure builders, so
file and endpoint never diverge).

  backend/data/status/mqtt_status.json     — broker connection state
  backend/data/status/devices_status.json  — per-pedestal device liveness
"""
import json
import logging
import os
from datetime import datetime, date

from ..database import SessionLocal
from ..auth.user_database import DATA_DIR
from ..time_utils import iso_z

logger = logging.getLogger(__name__)
STATUS_DIR = DATA_DIR / "status"


def _safe(v):
    if isinstance(v, datetime):
        return iso_z(v)  # explicit-UTC marker so clients convert to local correctly
    if isinstance(v, date):
        return v.isoformat()  # date-only: no timezone designator
    return v


def build_mqtt_status() -> dict:
    from .mqtt_client import mqtt_service
    try:
        s = mqtt_service.status()
    except Exception as e:  # never let the snapshot crash
        s = {"connected": False, "error": str(e)}
    return {"schema_version": 1, "generated_at": datetime.utcnow().isoformat() + "Z", **s}


def build_devices_status() -> dict:
    from ..models.pedestal_config import PedestalConfig, SocketState
    db = SessionLocal()
    pedestals = []
    try:
        by_ped: dict = {}
        for st in db.query(SocketState).all():
            by_ped.setdefault(st.pedestal_id, []).append({
                "socket_id": st.socket_id,
                "connected": bool(getattr(st, "connected", False)),
                "operator_status": getattr(st, "operator_status", None),
                "updated_at": _safe(getattr(st, "updated_at", None)),
            })
        for c in db.query(PedestalConfig).all():
            pedestals.append({
                "pedestal_id": c.pedestal_id,
                "cabinet_id": getattr(c, "opta_client_id", None),
                "cabinet": {
                    "connected": bool(getattr(c, "opta_connected", 0)),
                    "status": getattr(c, "status", None),
                    "last_heartbeat": _safe(getattr(c, "last_heartbeat", None)),
                    "door_state": getattr(c, "door_state", None),
                    "first_seen_at": _safe(getattr(c, "first_seen_at", None)),
                },
                "camera": {
                    "reachable": bool(getattr(c, "camera_reachable", 0)),
                    "last_check": _safe(getattr(c, "last_camera_check", None)),
                },
                "temp_sensor": {
                    "reachable": bool(getattr(c, "temp_sensor_reachable", 0)),
                    "last_check": _safe(getattr(c, "last_temp_sensor_check", None)),
                },
                "sockets": sorted(by_ped.get(c.pedestal_id, []), key=lambda s: s["socket_id"] or 0),
            })
    finally:
        db.close()
    return {"schema_version": 1, "generated_at": datetime.utcnow().isoformat() + "Z",
            "pedestals": pedestals}


def _atomic_write(path, data):
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def write_status_files() -> dict:
    mqtt = build_mqtt_status()
    devices = build_devices_status()
    try:
        _atomic_write(STATUS_DIR / "mqtt_status.json", mqtt)
        _atomic_write(STATUS_DIR / "devices_status.json", devices)
    except Exception as e:
        logger.warning("status snapshot write failed: %s", e)
    return {"mqtt": mqtt, "devices": devices}
