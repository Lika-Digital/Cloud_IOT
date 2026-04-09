"""Admin endpoints for the External API Gateway configurator.

All routes require admin role.
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from ..auth.dependencies import require_admin
from ..auth.models import User
from ..config import settings
from ..database import get_db
from ..models.external_api import ExternalApiConfig
from ..services.api_catalog import ENDPOINT_CATALOG, EVENT_CATALOG

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/ext-api", tags=["ext-api-admin"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class EndpointEntry(BaseModel):
    id: str
    mode: str  # "monitor" | "bidirectional"


class UpdateConfigRequest(BaseModel):
    allowed_endpoints: list[EndpointEntry]
    webhook_url: str | None = None
    allowed_events: list[str] = []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_config(db: DBSession) -> ExternalApiConfig:
    cfg = db.get(ExternalApiConfig, 1)
    if cfg is None:
        cfg = ExternalApiConfig(
            id=1,
            allowed_endpoints="[]",
            allowed_events="[]",
            active=0,
            verified=0,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _config_to_dict(cfg: ExternalApiConfig) -> dict:
    return {
        "id":                   cfg.id,
        "api_key":              ("***" if cfg.api_key else None),
        "allowed_endpoints":    json.loads(cfg.allowed_endpoints or "[]"),
        "webhook_url":          cfg.webhook_url,
        "allowed_events":       json.loads(cfg.allowed_events or "[]"),
        "active":               bool(cfg.active),
        "verified":             bool(cfg.verified),
        "last_verified_at":     cfg.last_verified_at.isoformat() if cfg.last_verified_at else None,
        "verification_results": json.loads(cfg.verification_results or "null"),
        "created_at":           cfg.created_at.isoformat() if cfg.created_at else None,
        "updated_at":           cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


def _make_external_api_jwt() -> str:
    """Generate a 10-year JWT for external API access."""
    expires = datetime.now(timezone.utc) + timedelta(days=3650)
    payload = {
        "sub":  "external_api",
        "role": "external_api",
        "exp":  expires,
        "iat":  datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _make_internal_admin_jwt() -> str | None:
    """Generate a short-lived (5 min) admin JWT for internal proxy calls."""
    from ..auth.user_database import UserSessionLocal
    from ..auth.models import User as UserModel
    db = UserSessionLocal()
    try:
        admin = db.query(UserModel).filter(
            UserModel.role == "admin",
            UserModel.is_active == True,  # noqa: E712
        ).first()
        if not admin:
            return None
        expires = datetime.now(timezone.utc) + timedelta(minutes=5)
        payload = {
            "sub":   str(admin.id),
            "email": admin.email,
            "role":  "admin",
            "exp":   expires,
        }
        return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
    finally:
        db.close()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/catalog")
def get_catalog(_: User = Depends(require_admin)):
    """Return the full endpoint and event catalogs."""
    return {"endpoints": ENDPOINT_CATALOG, "events": EVENT_CATALOG}


@router.get("/config")
def get_config(
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return current config (or empty defaults if not yet created)."""
    cfg = db.get(ExternalApiConfig, 1)
    if cfg is None:
        return {
            "id":                   None,
            "api_key":              None,
            "allowed_endpoints":    [],
            "webhook_url":          None,
            "allowed_events":       [],
            "active":               False,
            "verified":             False,
            "last_verified_at":     None,
            "verification_results": None,
            "created_at":           None,
            "updated_at":           None,
        }
    return _config_to_dict(cfg)


@router.put("/config")
def update_config(
    body: UpdateConfigRequest,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Upsert endpoint/event/webhook config. Resets verified=False on any change."""
    from ..services.webhook_service import invalidate_cache

    cfg = _get_or_create_config(db)
    cfg.allowed_endpoints    = json.dumps([e.model_dump() for e in body.allowed_endpoints])
    cfg.webhook_url          = body.webhook_url
    cfg.allowed_events       = json.dumps(body.allowed_events)
    cfg.verified             = 0
    cfg.active               = 0   # require re-activation after config change
    cfg.updated_at           = datetime.utcnow()
    db.commit()
    db.refresh(cfg)
    invalidate_cache()
    return _config_to_dict(cfg)


@router.post("/config/rotate-key")
def rotate_key(
    db: DBSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Generate a new external API JWT and store it. Returns the new key."""
    cfg = _get_or_create_config(db)
    new_key = _make_external_api_jwt()
    cfg.api_key    = new_key
    cfg.updated_at = datetime.utcnow()
    db.commit()
    from ..services.webhook_service import invalidate_cache
    from ..services.error_log_service import log_warning
    invalidate_cache()
    try:
        log_warning("security", "ext_api/rotate-key",
                    f"External API key rotated by {admin.email}",
                    details="Previous key invalidated — update all integrations")
    except Exception:
        pass
    return {"api_key": new_key}


@router.post("/config/verify")
async def verify_config(
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Live-test each non-parameterised GET endpoint in the allowed list.
    Sets verified=True if at least one GET passes and none fail outright.
    Returns detailed results per endpoint.
    """
    import httpx

    cfg = db.get(ExternalApiConfig, 1)
    if not cfg:
        raise HTTPException(status_code=404, detail="No config found — save a config first")

    allowed_ids = {e["id"] for e in json.loads(cfg.allowed_endpoints or "[]")}
    if not allowed_ids:
        raise HTTPException(status_code=400, detail="No endpoints enabled — select at least one")

    internal_token = _make_internal_admin_jwt()
    if not internal_token:
        raise HTTPException(status_code=500, detail="Could not generate internal admin token — ensure an admin user exists")

    base_url = f"http://127.0.0.1:{settings.app_port}"
    results = []
    any_pass = False
    any_fail = False

    async with httpx.AsyncClient(timeout=8.0) as client:
        for ep in ENDPOINT_CATALOG:
            if ep["id"] not in allowed_ids:
                continue

            has_param = "{id}" in ep["path"]
            if ep["method"] != "GET":
                results.append({
                    "endpoint_id": ep["id"],
                    "path":        ep["path"],
                    "status_code": None,
                    "ok":          None,
                    "note":        "Skipped — control endpoint (POST)",
                })
                continue

            if has_param:
                results.append({
                    "endpoint_id": ep["id"],
                    "path":        ep["path"],
                    "status_code": None,
                    "ok":          None,
                    "note":        "Skipped — parameterised path",
                })
                continue

            # Testable GET without path param
            url = f"{base_url}{ep['path']}"
            try:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {internal_token}"},
                )
                ok = resp.status_code < 400
                if ok:
                    any_pass = True
                else:
                    any_fail = True
                results.append({
                    "endpoint_id": ep["id"],
                    "path":        ep["path"],
                    "status_code": resp.status_code,
                    "ok":          ok,
                    "note":        "Pass" if ok else f"HTTP {resp.status_code}",
                })
            except Exception as e:
                any_fail = True
                results.append({
                    "endpoint_id": ep["id"],
                    "path":        ep["path"],
                    "status_code": None,
                    "ok":          False,
                    "note":        f"Connection error: {e}",
                })

    verified = any_pass and not any_fail
    cfg.verified             = 1 if verified else 0
    cfg.last_verified_at     = datetime.utcnow()
    cfg.verification_results = json.dumps(results)
    cfg.updated_at           = datetime.utcnow()
    db.commit()

    return {
        "verified": verified,
        "results":  results,
    }


@router.post("/config/activate")
def activate_config(
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Activate the gateway."""
    from ..services.webhook_service import invalidate_cache

    cfg = _get_or_create_config(db)
    cfg.active     = 1
    cfg.updated_at = datetime.utcnow()
    db.commit()
    invalidate_cache()
    return {"active": True}


@router.post("/config/deactivate")
def deactivate_config(
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Deactivate the gateway."""
    from ..services.webhook_service import invalidate_cache

    cfg = db.get(ExternalApiConfig, 1)
    if not cfg:
        raise HTTPException(status_code=404, detail="No config found")

    cfg.active     = 0
    cfg.updated_at = datetime.utcnow()
    db.commit()
    invalidate_cache()
    return {"active": False}
