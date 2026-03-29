"""Admin settings endpoints: SMTP, SNMP trap, network info, active pedestals, pilot assignments."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.user_database import get_user_db
from ..auth.dependencies import require_admin
from ..auth.models import User, SmtpConfig
from ..auth.schemas import SmtpConfigUpdate
from ..config import settings
from ..database import get_db

router = APIRouter(prefix="/api/admin/settings", tags=["admin-settings"])


@router.get("/smtp")
def get_smtp(
    _: User = Depends(require_admin),
    db: Session = Depends(get_user_db),
):
    """Return current SMTP config. Password is masked as '**' if set."""
    cfg = db.get(SmtpConfig, 1)

    if cfg and cfg.host:
        return {
            "host": cfg.host,
            "port": cfg.port,
            "tls": bool(cfg.tls),
            "username": cfg.username,
            "password": "**" if cfg.password else "",
            "from_email": cfg.from_email,
            "configured": True,
            "source": "db",
        }

    # Fallback: report .env values
    if settings.smtp_host:
        return {
            "host": settings.smtp_host,
            "port": settings.smtp_port,
            "tls": settings.smtp_tls,
            "username": settings.smtp_user,
            "password": "**" if settings.smtp_password else "",
            "from_email": settings.smtp_from,
            "configured": True,
            "source": "env",
        }

    return {
        "host": "",
        "port": 587,
        "tls": True,
        "username": "",
        "password": "",
        "from_email": "",
        "configured": False,
        "source": "none",
    }


@router.put("/smtp")
def update_smtp(
    body: SmtpConfigUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_user_db),
):
    """Save SMTP settings to the database (runtime, no restart required)."""
    cfg = db.get(SmtpConfig, 1)
    if not cfg:
        cfg = SmtpConfig(id=1)
        db.add(cfg)

    cfg.host = body.host.strip()
    cfg.port = body.port
    cfg.tls = 1 if body.tls else 0
    cfg.username = body.username.strip()
    # Keep existing password if client sends the masked placeholder "**"
    if body.password and body.password != "**":
        cfg.password = body.password
    elif not body.password:
        cfg.password = ""
    cfg.from_email = body.from_email.strip()
    cfg.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "SMTP settings saved"}


@router.get("/network-info")
def get_network_info(_: User = Depends(require_admin)):
    """Return auto-detected LAN IP of this machine (NUC or dev PC)."""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = "127.0.0.1"
    return {
        "lan_ip": ip,
        "mqtt_port": 1883,
        "snmp_trap_port": _get_snmp_config()["port"],
    }


class SnmpConfigUpdate(BaseModel):
    enabled:     bool   = True
    port:        int    = 1620
    community:   str    = "public"
    temp_oid:    str    = "1.3.6.1.4.1.18248.20.1.2.1.1.2.1"
    pedestal_id: int    = 1


def _get_snmp_config() -> dict:
    from ..services.snmp_trap_service import get_config
    return get_config()


@router.get("/snmp")
def get_snmp_config(_: User = Depends(require_admin)):
    """Return current SNMP trap receiver configuration."""
    return _get_snmp_config()


@router.put("/snmp")
def update_snmp_config(body: SnmpConfigUpdate, _: User = Depends(require_admin)):
    """Update SNMP trap receiver configuration at runtime (no restart needed)."""
    from ..services.snmp_trap_service import update_config
    updated = update_config(body.model_dump())
    return {"message": "SNMP config updated", "config": updated}


@router.get("/active-pedestals")
def get_active_pedestals(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return count and per-pedestal MQTT connection status."""
    from ..models.pedestal import Pedestal
    from ..models.pedestal_config import PedestalConfig

    pedestals = db.query(Pedestal).order_by(Pedestal.id).all()
    configs = {c.pedestal_id: c for c in db.query(PedestalConfig).all()}

    items = []
    for p in pedestals:
        cfg = configs.get(p.id)
        items.append({
            "id": p.id,
            "name": p.name,
            "connected": bool(cfg and cfg.opta_connected),
            "last_heartbeat": cfg.last_heartbeat.isoformat() if cfg and cfg.last_heartbeat else None,
        })

    return {
        "total": len(items),
        "connected": sum(1 for r in items if r["connected"]),
        "pedestals": items,
    }


class PilotAssignmentCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=120)
    pedestal_id: int
    socket_id: int = Field(..., ge=1, le=4)


@router.get("/pilot-assignments")
def list_pilot_assignments(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return all active pilot assignments."""
    from ..models.pilot_assignment import PilotAssignment
    return db.query(PilotAssignment).order_by(PilotAssignment.pedestal_id, PilotAssignment.socket_id).all()


@router.post("/pilot-assignments", status_code=201)
def create_pilot_assignment(
    body: PilotAssignmentCreate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a pilot assignment (one per pedestal/socket)."""
    from ..models.pilot_assignment import PilotAssignment
    existing = db.query(PilotAssignment).filter(
        PilotAssignment.pedestal_id == body.pedestal_id,
        PilotAssignment.socket_id == body.socket_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="That pedestal/socket already has a pilot assignment")
    a = PilotAssignment(
        username=body.username.strip(),
        pedestal_id=body.pedestal_id,
        socket_id=body.socket_id,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


@router.delete("/pilot-assignments/{assignment_id}", status_code=204)
def delete_pilot_assignment(
    assignment_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete a pilot assignment."""
    from ..models.pilot_assignment import PilotAssignment
    a = db.get(PilotAssignment, assignment_id)
    if not a:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(a)
    db.commit()


@router.post("/smtp/test")
def test_smtp(
    current_user: User = Depends(require_admin),
    _db: Session = Depends(get_user_db),
):
    """Send a test email to the currently logged-in admin's address."""
    from ..auth.email_service import send_test_email
    try:
        send_test_email(current_user.email)
        return {"message": f"Test email sent to {current_user.email}"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SMTP delivery failed: {exc}")
