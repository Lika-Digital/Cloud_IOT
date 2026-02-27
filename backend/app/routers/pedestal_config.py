"""
Admin endpoints for per-pedestal extended configuration, sensor management,
auto-discovery (mDNS / SNMP), and health status.
"""
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..auth.dependencies import require_admin
from ..models.pedestal_config import PedestalConfig, PedestalSensor
from ..models.pedestal import Pedestal

router = APIRouter(tags=["pedestal-config"])
logger = logging.getLogger(__name__)


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class PedestalConfigUpdate(BaseModel):
    site_id: Optional[str] = None
    dock_id: Optional[str] = None
    berth_ref: Optional[str] = None
    pedestal_uid: Optional[str] = None
    pedestal_model: Optional[str] = None
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    opta_client_id: Optional[str] = None
    camera_stream_url: Optional[str] = None
    camera_fqdn: Optional[str] = None
    camera_username: Optional[str] = None
    camera_password: Optional[str] = None
    sensor_config_mode: Optional[str] = None   # "auto" | "manual"


class SensorCreate(BaseModel):
    sensor_name: str
    sensor_type: str
    mqtt_topic: str
    unit: Optional[str] = None
    min_alarm: Optional[float] = None
    max_alarm: Optional[float] = None
    is_active: bool = True


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_or_create_config(db: Session, pedestal_id: int) -> PedestalConfig:
    """Return existing PedestalConfig or create an empty one."""
    cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pedestal_id).first()
    if cfg is None:
        cfg = PedestalConfig(pedestal_id=pedestal_id, updated_at=datetime.utcnow())
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _config_to_dict(cfg: PedestalConfig) -> dict:
    return {
        "id": cfg.id,
        "pedestal_id": cfg.pedestal_id,
        "site_id": cfg.site_id,
        "dock_id": cfg.dock_id,
        "berth_ref": cfg.berth_ref,
        "pedestal_uid": cfg.pedestal_uid,
        "pedestal_model": cfg.pedestal_model,
        "mqtt_username": cfg.mqtt_username,
        "mqtt_password": cfg.mqtt_password,
        "opta_client_id": cfg.opta_client_id,
        "camera_stream_url": cfg.camera_stream_url,
        "camera_fqdn": cfg.camera_fqdn,
        "camera_username": cfg.camera_username,
        "camera_password": cfg.camera_password,
        "sensor_config_mode": cfg.sensor_config_mode,
        "mdns_discovered": json.loads(cfg.mdns_discovered) if cfg.mdns_discovered else [],
        "snmp_discovered": json.loads(cfg.snmp_discovered) if cfg.snmp_discovered else [],
        "opta_connected": bool(cfg.opta_connected),
        "last_heartbeat": cfg.last_heartbeat.isoformat() if cfg.last_heartbeat else None,
        "camera_reachable": bool(cfg.camera_reachable),
        "last_camera_check": cfg.last_camera_check.isoformat() if cfg.last_camera_check else None,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


def _sensor_to_dict(s: PedestalSensor) -> dict:
    return {
        "id": s.id,
        "pedestal_id": s.pedestal_id,
        "sensor_name": s.sensor_name,
        "sensor_type": s.sensor_type,
        "mqtt_topic": s.mqtt_topic,
        "unit": s.unit,
        "min_alarm": s.min_alarm,
        "max_alarm": s.max_alarm,
        "is_active": s.is_active,
        "source": s.source,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/api/admin/pedestal/{pedestal_id}/config")
def get_config(
    pedestal_id: int,
    db: Session = Depends(get_db),
    _user = Depends(require_admin),
):
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    cfg = _get_or_create_config(db, pedestal_id)
    sensors = db.query(PedestalSensor).filter(PedestalSensor.pedestal_id == pedestal_id).all()
    result = _config_to_dict(cfg)
    result["sensors"] = [_sensor_to_dict(s) for s in sensors]
    return result


@router.put("/api/admin/pedestal/{pedestal_id}/config")
def update_config(
    pedestal_id: int,
    body: PedestalConfigUpdate,
    db: Session = Depends(get_db),
    _user = Depends(require_admin),
):
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    cfg = _get_or_create_config(db, pedestal_id)

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(cfg, field, value)
    cfg.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(cfg)
    return _config_to_dict(cfg)


@router.get("/api/admin/pedestal/{pedestal_id}/sensors")
def get_sensors(
    pedestal_id: int,
    db: Session = Depends(get_db),
    _user = Depends(require_admin),
):
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    sensors = db.query(PedestalSensor).filter(PedestalSensor.pedestal_id == pedestal_id).all()
    return [_sensor_to_dict(s) for s in sensors]


@router.post("/api/admin/pedestal/{pedestal_id}/sensors")
def add_sensor(
    pedestal_id: int,
    body: SensorCreate,
    db: Session = Depends(get_db),
    _user = Depends(require_admin),
):
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    sensor = PedestalSensor(
        pedestal_id=pedestal_id,
        sensor_name=body.sensor_name,
        sensor_type=body.sensor_type,
        mqtt_topic=body.mqtt_topic,
        unit=body.unit,
        min_alarm=body.min_alarm,
        max_alarm=body.max_alarm,
        is_active=body.is_active,
        source="manual",
        created_at=datetime.utcnow(),
    )
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return _sensor_to_dict(sensor)


@router.delete("/api/admin/pedestal/sensors/{sensor_id}")
def delete_sensor(
    sensor_id: int,
    db: Session = Depends(get_db),
    _user = Depends(require_admin),
):
    sensor = db.get(PedestalSensor, sensor_id)
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")
    db.delete(sensor)
    db.commit()
    return {"ok": True}


@router.post("/api/admin/pedestal/{pedestal_id}/discover/mdns")
async def discover_mdns(
    pedestal_id: int,
    db: Session = Depends(get_db),
    _user = Depends(require_admin),
):
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    from ..services.discovery import scan_mdns
    found = await scan_mdns(timeout=5.0)
    cfg = _get_or_create_config(db, pedestal_id)
    cfg.mdns_discovered = json.dumps(found)
    cfg.updated_at = datetime.utcnow()
    db.commit()
    return {"discovered": found}


@router.post("/api/admin/pedestal/{pedestal_id}/discover/snmp")
async def discover_snmp(
    pedestal_id: int,
    subnet: str = "192.168.1",
    db: Session = Depends(get_db),
    _user = Depends(require_admin),
):
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    from ..services.discovery import scan_snmp
    found = await scan_snmp(subnet=subnet)
    cfg = _get_or_create_config(db, pedestal_id)
    cfg.snmp_discovered = json.dumps(found)
    cfg.updated_at = datetime.utcnow()
    db.commit()
    return {"discovered": found}


@router.get("/api/pedestals/health")
def get_health(
    db: Session = Depends(get_db),
):
    """Public endpoint — returns health status for all pedestals."""
    configs = db.query(PedestalConfig).all()
    result = {}
    for cfg in configs:
        result[cfg.pedestal_id] = {
            "opta_connected": bool(cfg.opta_connected),
            "last_heartbeat": cfg.last_heartbeat.isoformat() if cfg.last_heartbeat else None,
            "camera_reachable": bool(cfg.camera_reachable),
            "last_camera_check": cfg.last_camera_check.isoformat() if cfg.last_camera_check else None,
        }
    return result
