"""
Admin endpoints for per-pedestal extended configuration, sensor management,
auto-discovery (mDNS / SNMP), and health status.
"""
import json
import logging
import urllib.parse
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..auth.dependencies import require_admin
from ..auth.user_database import UserSessionLocal
from ..models.pedestal_config import PedestalConfig, PedestalSensor
from ..models.pedestal import Pedestal

router = APIRouter(tags=["pedestal-config"])
logger = logging.getLogger(__name__)


# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class PedestalConfigUpdate(BaseModel):
    # Pedestal display identity (stored on Pedestal row, not PedestalConfig)
    pedestal_name: Optional[str] = None
    pedestal_location: Optional[str] = None
    # Config fields
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
    temp_sensor_ip: Optional[str] = None
    temp_sensor_port: Optional[int] = None
    temp_sensor_protocol: Optional[str] = None  # "http" | "modbus_tcp"


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


def _config_to_dict(cfg: PedestalConfig, pedestal=None) -> dict:
    return {
        "id": cfg.id,
        "pedestal_id": cfg.pedestal_id,
        "pedestal_name": pedestal.name if pedestal else None,
        "pedestal_location": pedestal.location if pedestal else None,
        "site_id": cfg.site_id,
        "dock_id": cfg.dock_id,
        "berth_ref": cfg.berth_ref,
        "pedestal_uid": cfg.pedestal_uid,
        "pedestal_model": cfg.pedestal_model,
        "mqtt_username": cfg.mqtt_username,
        "mqtt_password": "***" if cfg.mqtt_password else None,
        "opta_client_id": cfg.opta_client_id,
        "camera_stream_url": cfg.camera_stream_url,
        "camera_fqdn": cfg.camera_fqdn,
        "camera_username": cfg.camera_username,
        "camera_password": "***" if cfg.camera_password else None,
        "sensor_config_mode": cfg.sensor_config_mode,
        "mdns_discovered": json.loads(cfg.mdns_discovered) if cfg.mdns_discovered else [],
        "snmp_discovered": json.loads(cfg.snmp_discovered) if cfg.snmp_discovered else [],
        "temp_sensor_ip": cfg.temp_sensor_ip,
        "temp_sensor_port": cfg.temp_sensor_port,
        "temp_sensor_protocol": cfg.temp_sensor_protocol,
        "opta_connected": bool(cfg.opta_connected),
        "last_heartbeat": cfg.last_heartbeat.isoformat() if cfg.last_heartbeat else None,
        "camera_reachable": bool(cfg.camera_reachable),
        "last_camera_check": cfg.last_camera_check.isoformat() if cfg.last_camera_check else None,
        "temp_sensor_reachable": bool(cfg.temp_sensor_reachable),
        "last_temp_sensor_check": cfg.last_temp_sensor_check.isoformat() if cfg.last_temp_sensor_check else None,
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
    result = _config_to_dict(cfg, pedestal)
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

    updated_fields = body.model_dump(exclude_none=True)
    # Never store the sentinel mask value — skip if UI echoed it back
    for secret_field in ("mqtt_password", "camera_password"):
        if updated_fields.get(secret_field) == "***":
            updated_fields.pop(secret_field)

    # pedestal_name / pedestal_location go to the Pedestal row, not PedestalConfig
    if "pedestal_name" in updated_fields:
        pedestal.name = updated_fields.pop("pedestal_name")
    if "pedestal_location" in updated_fields:
        pedestal.location = updated_fields.pop("pedestal_location")

    for field, value in updated_fields.items():
        setattr(cfg, field, value)
    cfg.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(cfg)
    db.refresh(pedestal)

    # Auto-inject credentials into camera_stream_url whenever URL or credentials change
    if any(f in updated_fields for f in ("camera_stream_url", "camera_username", "camera_password", "camera_fqdn")):
        url = cfg.camera_stream_url or ""
        username = cfg.camera_username or ""
        password = cfg.camera_password or ""
        if url and (username or password):
            try:
                parsed = urllib.parse.urlparse(url)
                # Strip existing credentials from netloc
                host = parsed.hostname or ""
                if parsed.port:
                    host = f"{host}:{parsed.port}"
                creds = urllib.parse.quote(username, safe="") + ":" + urllib.parse.quote(password, safe="")
                netloc = f"{creds}@{host}"
                injected = urllib.parse.urlunparse(
                    (parsed.scheme or "rtsp", netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
                )
                cfg.camera_stream_url = injected
                db.commit()
                db.refresh(cfg)
            except Exception:
                pass

    # Audit log — list which config keys changed (no values for secrets)
    try:
        from ..services.error_log_service import log_warning
        safe_fields = [
            f for f in updated_fields
            if f not in ("mqtt_password", "camera_password")
        ]
        secret_fields = [
            f for f in updated_fields
            if f in ("mqtt_password", "camera_password")
        ]
        detail_parts = []
        if safe_fields:
            detail_parts.append("fields=" + ",".join(safe_fields))
        if secret_fields:
            detail_parts.append("credentials_updated=" + ",".join(secret_fields))
        log_warning(
            "system", f"pedestal_config/pedestal_{pedestal_id}",
            f"Pedestal {pedestal_id} configuration updated",
            details="; ".join(detail_parts) if detail_parts else None,
        )
    except Exception:
        pass

    return _config_to_dict(cfg, pedestal)


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


@router.post("/api/admin/discovery/scan")
async def scan_all_devices(
    subnet: str = "",
    _user = Depends(require_admin),
):
    """
    Run full network scan: ONVIF WS-Discovery (cameras) + HTTP subnet scan (TME sensors).
    Returns {cameras: [...], temp_sensors: [...], subnet: "..."}.
    Subnet is auto-detected from NUC's network interface if not provided.
    """
    from ..services.discovery import scan_all
    result = await scan_all(subnet=subnet, timeout=5.0)
    return result


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
    _user = Depends(require_admin),
):
    """Returns hardware health status for all pedestals (admin only).

    Each pedestal entry also includes ext_berths_occupancy, ext_camera_frame,
    and ext_camera_stream status (enabled + availability) for the API Gateway UI.
    """
    from ..models.external_api import ExternalApiConfig
    from ..auth.berth_models import Berth as BerthModel

    configs = db.query(PedestalConfig).all()
    result = {}
    for cfg in configs:
        result[cfg.pedestal_id] = {
            "opta_connected": bool(cfg.opta_connected),
            "opta_client_id": cfg.opta_client_id,  # v3.7 — needed by QR UI
            "last_heartbeat": cfg.last_heartbeat.isoformat() if cfg.last_heartbeat else None,
            "camera_reachable": bool(cfg.camera_reachable),
            "last_camera_check": cfg.last_camera_check.isoformat() if cfg.last_camera_check else None,
            "temp_sensor_reachable": bool(cfg.temp_sensor_reachable),
            "last_temp_sensor_check": cfg.last_temp_sensor_check.isoformat() if cfg.last_temp_sensor_check else None,
        }

    # Ext endpoint enable status (global — same value across all pedestals)
    ext_cfg = db.get(ExternalApiConfig, 1)
    allowed_eps = json.loads(ext_cfg.allowed_endpoints or "[]") if ext_cfg else []
    enabled_ids = {e["id"] for e in allowed_eps}
    berths_enabled     = "berths.occupancy_ext" in enabled_ids
    cam_frame_enabled  = "camera.frame_ext"     in enabled_ids
    cam_stream_enabled = "camera.stream_ext"    in enabled_ids

    # Berth count per pedestal (user DB)
    user_db = UserSessionLocal()
    try:
        pedestal_berth_counts: dict[int, int] = {}
        for b in user_db.query(BerthModel).filter(BerthModel.pedestal_id.isnot(None)).all():
            pedestal_berth_counts[b.pedestal_id] = (
                pedestal_berth_counts.get(b.pedestal_id, 0) + 1
            )
    finally:
        user_db.close()

    for cfg in configs:
        has_berths    = pedestal_berth_counts.get(cfg.pedestal_id, 0) > 0
        has_camera    = bool(cfg.camera_stream_url)
        cam_reachable = bool(cfg.camera_reachable)

        result[cfg.pedestal_id]["ext_berths_occupancy"] = {
            "enabled":   berths_enabled,
            "available": has_berths,
            "reason": (
                None if (berths_enabled and has_berths) else
                "Not enabled" if not berths_enabled else
                "No berth definitions found"
            ),
        }
        result[cfg.pedestal_id]["ext_camera_frame"] = {
            "enabled":   cam_frame_enabled,
            "available": has_camera and cam_reachable,
            "reason": (
                None if (cam_frame_enabled and has_camera and cam_reachable) else
                "Not enabled" if not cam_frame_enabled else
                "No camera configured" if not has_camera else
                "Camera unreachable"
            ),
        }
        result[cfg.pedestal_id]["ext_camera_stream"] = {
            "enabled":   cam_stream_enabled,
            "available": has_camera,
            "reason": (
                None if (cam_stream_enabled and has_camera) else
                "Not enabled" if not cam_stream_enabled else
                "No camera configured"
            ),
        }

    return result


# ─── Per-socket auto-activation config (v3.5) ────────────────────────────────

class SocketConfigUpdate(BaseModel):
    auto_activate: bool


@router.get("/api/pedestals/{pedestal_id}/sockets/config")
def list_socket_configs(pedestal_id: int, db: Session = Depends(get_db)):
    """Return the auto-activate setting for all 4 electricity sockets on a pedestal.

    Sockets that have never been configured yet are returned as
    `{socket_id, auto_activate: false}` — matches the model default.
    """
    if not db.get(Pedestal, pedestal_id):
        raise HTTPException(status_code=404, detail="Pedestal not found")

    from ..models.socket_config import SocketConfig
    rows = db.query(SocketConfig).filter(SocketConfig.pedestal_id == pedestal_id).all()
    by_socket = {r.socket_id: r for r in rows}
    return [
        {
            "socket_id": sid,
            "auto_activate": bool(by_socket[sid].auto_activate) if sid in by_socket else False,
        }
        for sid in (1, 2, 3, 4)
    ]


@router.patch("/api/pedestals/{pedestal_id}/sockets/{socket_id}/config")
def update_socket_config(
    pedestal_id: int,
    socket_id: int,
    body: SocketConfigUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    """Update the auto-activate flag for a single socket. Admin only.

    Takes effect immediately — the next UserPluggedIn event for this socket
    reads the new value directly from SocketConfig.
    """
    if socket_id not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="socket_id must be in 1..4")
    if not db.get(Pedestal, pedestal_id):
        raise HTTPException(status_code=404, detail="Pedestal not found")

    from ..models.socket_config import SocketConfig
    cfg = db.query(SocketConfig).filter(
        SocketConfig.pedestal_id == pedestal_id,
        SocketConfig.socket_id == socket_id,
    ).first()
    if cfg:
        cfg.auto_activate = body.auto_activate
    else:
        cfg = SocketConfig(
            pedestal_id=pedestal_id,
            socket_id=socket_id,
            auto_activate=body.auto_activate,
        )
        db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return {"socket_id": socket_id, "auto_activate": bool(cfg.auto_activate)}


@router.get("/api/pedestals/{pedestal_id}/sockets/{socket_id}/auto-activate-log")
def get_auto_activate_log(pedestal_id: int, socket_id: int, db: Session = Depends(get_db)):
    """Return the last 20 auto-activation attempts for this socket, newest first."""
    if socket_id not in (1, 2, 3, 4):
        raise HTTPException(status_code=400, detail="socket_id must be in 1..4")
    if not db.get(Pedestal, pedestal_id):
        raise HTTPException(status_code=404, detail="Pedestal not found")

    from ..models.auto_activation_log import AutoActivationLog
    rows = (
        db.query(AutoActivationLog)
        .filter(
            AutoActivationLog.pedestal_id == pedestal_id,
            AutoActivationLog.socket_id == socket_id,
        )
        .order_by(AutoActivationLog.timestamp.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat(),
            "result": r.result,
            "reason": r.reason,
            "session_id": r.session_id,
        }
        for r in rows
    ]
