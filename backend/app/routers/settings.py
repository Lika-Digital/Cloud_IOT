"""Admin settings endpoints: SMTP configuration."""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth.user_database import get_user_db
from ..auth.dependencies import require_admin
from ..auth.models import User, SmtpConfig
from ..auth.schemas import SmtpConfigUpdate
from ..config import settings

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
