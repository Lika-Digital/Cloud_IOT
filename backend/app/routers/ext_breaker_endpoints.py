"""v3.8 — External API: breaker monitoring and remote reset for ERP.

Direct FastAPI routes registered in `main.py` BEFORE the `/api/ext/{path:path}`
gateway catch-all so path-specific handlers win. Auth + per-endpoint toggle
mirror `ext_pedestal_endpoints.py` exactly for consistency.

Routes:
  GET  /api/ext/pedestals/{pedestal_id}/breakers
  GET  /api/ext/pedestals/{pedestal_id}/sockets/{socket_id}/breaker
  POST /api/ext/pedestals/{pedestal_id}/sockets/{socket_id}/breaker/reset
  GET  /api/ext/pedestals/{pedestal_id}/breaker/history
  GET  /api/ext/marinas/{marina_id}/breaker/alarms

Every ERP-triggered reset writes `reset_initiated_by='erp-service'` into the
breaker_events audit table so operator vs ERP resets are distinguishable.
"""
from __future__ import annotations

import hmac
import json
import logging

import jwt as pyjwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..config import settings
from ..database import SessionLocal
from ..models.breaker_event import BreakerEvent
from ..models.external_api import ExternalApiConfig
from ..models.pedestal import Pedestal
from ..models.pedestal_config import PedestalConfig
from ..models.socket_config import SocketConfig
from .breakers import (
    broadcast_resetting,
    perform_breaker_reset,
    serialize_breaker_status,
    serialize_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ext-breakers"])

# Catalog IDs — must match api_catalog.py entries for the toggle check.
_EP_LIST    = "breakers.pedestal_list_ext"
_EP_SOCKET  = "breakers.socket_get_ext"
_EP_RESET   = "breakers.socket_reset_ext"
_EP_HISTORY = "breakers.pedestal_history_ext"
_EP_MARINA  = "breakers.marina_alarms_ext"


# ── Auth + toggle helpers (copied from ext_pedestal_endpoints for parity) ────

def _check_ext_auth(request: Request):
    """Validate Bearer JWT, gateway active flag, and HMAC against stored api_key.
    Returns (payload, None) on success or (None, JSONResponse) on failure.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, JSONResponse({"detail": "Missing Authorization header"}, status_code=401)

    token = auth[7:].strip()
    try:
        payload = pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
        return None, JSONResponse({"detail": "Invalid or expired API key"}, status_code=401)

    role = payload.get("role")
    if role not in {"external_api", "api_client"}:
        return None, JSONResponse({"detail": "Invalid or expired API key"}, status_code=401)

    db = SessionLocal()
    try:
        cfg = db.get(ExternalApiConfig, 1)
    finally:
        db.close()

    if cfg is None:
        return None, JSONResponse({"detail": "External API not configured"}, status_code=403)
    if not cfg.active:
        return None, JSONResponse({"error": "Feature not available", "reason": "Not enabled"}, status_code=503)
    if role == "external_api":
        if not hmac.compare_digest(cfg.api_key or "", token):
            return None, JSONResponse({"detail": "Invalid API key"}, status_code=403)

    return payload, None


def _endpoint_enabled(endpoint_id: str) -> bool:
    db = SessionLocal()
    try:
        cfg = db.get(ExternalApiConfig, 1)
        if not cfg:
            return False
        allowed = json.loads(cfg.allowed_endpoints or "[]")
        return any(e.get("id") == endpoint_id for e in allowed)
    finally:
        db.close()


def _feature_not_available() -> JSONResponse:
    return JSONResponse(
        {"error": "Feature not available", "reason": "Not enabled"}, status_code=503
    )


# ── 1. List all breakers on a pedestal ───────────────────────────────────────

@router.get("/api/ext/pedestals/{pedestal_id}/breakers")
async def ext_breakers_list(pedestal_id: int, request: Request):
    _, err = _check_ext_auth(request)
    if err:
        return err
    if not _endpoint_enabled(_EP_LIST):
        return _feature_not_available()

    db = SessionLocal()
    try:
        if db.get(Pedestal, pedestal_id) is None:
            return JSONResponse({"detail": "Pedestal not found"}, status_code=404)
        rows = db.query(SocketConfig).filter(SocketConfig.pedestal_id == pedestal_id).order_by(SocketConfig.socket_id).all()
        sockets = []
        for cfg in rows:
            item = {"socket_id": cfg.socket_id}
            item.update(serialize_breaker_status(cfg))
            sockets.append(item)
        return JSONResponse({"pedestal_id": pedestal_id, "sockets": sockets})
    finally:
        db.close()


# ── 2. Single-socket breaker + last 5 events ─────────────────────────────────

@router.get("/api/ext/pedestals/{pedestal_id}/sockets/{socket_id}/breaker")
async def ext_breaker_socket_get(pedestal_id: int, socket_id: int, request: Request):
    _, err = _check_ext_auth(request)
    if err:
        return err
    if not _endpoint_enabled(_EP_SOCKET):
        return _feature_not_available()

    db = SessionLocal()
    try:
        if db.get(Pedestal, pedestal_id) is None:
            return JSONResponse({"detail": "Pedestal not found"}, status_code=404)
        cfg = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == pedestal_id,
            SocketConfig.socket_id == socket_id,
        ).first()
        events = (
            db.query(BreakerEvent)
            .filter(
                BreakerEvent.pedestal_id == pedestal_id,
                BreakerEvent.socket_id == socket_id,
            )
            .order_by(BreakerEvent.timestamp.desc())
            .limit(5)
            .all()
        )
        body = {"pedestal_id": pedestal_id, "socket_id": socket_id}
        body.update(serialize_breaker_status(cfg))
        body["recent_events"] = [serialize_event(e) for e in events]
        return JSONResponse(body)
    finally:
        db.close()


# ── 3. POST reset (ERP) ──────────────────────────────────────────────────────

@router.post("/api/ext/pedestals/{pedestal_id}/sockets/{socket_id}/breaker/reset")
async def ext_breaker_reset(pedestal_id: int, socket_id: int, request: Request):
    _, err = _check_ext_auth(request)
    if err:
        return err
    if not _endpoint_enabled(_EP_RESET):
        return _feature_not_available()

    db = SessionLocal()
    try:
        try:
            perform_breaker_reset(db, pedestal_id, socket_id, initiated_by="erp-service")
        except Exception as e:
            # perform_breaker_reset raises HTTPException(404) or (409). Convert.
            from fastapi import HTTPException
            if isinstance(e, HTTPException):
                return JSONResponse({"detail": e.detail}, status_code=e.status_code)
            raise
    finally:
        db.close()

    await broadcast_resetting(pedestal_id, socket_id)
    return JSONResponse({
        "status": "reset_command_sent",
        "socket_id": socket_id,
        "initiated_by": "erp-service",
    })


# ── 4. Pedestal-level breaker history (last 50) ──────────────────────────────

@router.get("/api/ext/pedestals/{pedestal_id}/breaker/history")
async def ext_breaker_history(pedestal_id: int, request: Request):
    _, err = _check_ext_auth(request)
    if err:
        return err
    if not _endpoint_enabled(_EP_HISTORY):
        return _feature_not_available()

    db = SessionLocal()
    try:
        if db.get(Pedestal, pedestal_id) is None:
            return JSONResponse({"detail": "Pedestal not found"}, status_code=404)
        rows = (
            db.query(BreakerEvent)
            .filter(BreakerEvent.pedestal_id == pedestal_id)
            .order_by(BreakerEvent.timestamp.desc())
            .limit(50)
            .all()
        )
        return JSONResponse({"pedestal_id": pedestal_id, "events": [serialize_event(e) for e in rows]})
    finally:
        db.close()


# ── 5. Marina-wide active alarms ─────────────────────────────────────────────

@router.get("/api/ext/marinas/{marina_id}/breaker/alarms")
async def ext_breaker_marina_alarms(marina_id: str, request: Request):
    """Return every socket currently in `tripped` or `resetting` state across
    all pedestals whose cabinet id matches `MAR_{marina_id}_...`.

    marina_id is the middle segment of the Opta cabinet id convention
    (e.g. "KRK" for MAR_KRK_ORM_01). Match is prefix-anchored — two marinas
    sharing a leading substring will not alias.
    """
    _, err = _check_ext_auth(request)
    if err:
        return err
    if not _endpoint_enabled(_EP_MARINA):
        return _feature_not_available()

    # Escape SQL-LIKE wildcards in marina_id; we then own the wildcard.
    safe = marina_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"MAR_{safe}_%"

    db = SessionLocal()
    try:
        cfg_rows = db.query(PedestalConfig).filter(
            PedestalConfig.opta_client_id.like(pattern, escape="\\")
        ).all()
        pedestal_ids = [cfg.pedestal_id for cfg in cfg_rows]
        if not pedestal_ids:
            return JSONResponse({"marina_id": marina_id, "alarms": []})

        sockets = (
            db.query(SocketConfig)
            .filter(
                SocketConfig.pedestal_id.in_(pedestal_ids),
                SocketConfig.breaker_state.in_(("tripped", "resetting")),
            )
            .order_by(SocketConfig.pedestal_id, SocketConfig.socket_id)
            .all()
        )
        alarms = [
            {
                "pedestal_id": s.pedestal_id,
                "socket_id": s.socket_id,
                "breaker_state": s.breaker_state,
                "breaker_trip_cause": s.breaker_trip_cause,
                "breaker_last_trip_at": s.breaker_last_trip_at.isoformat() if s.breaker_last_trip_at else None,
                "breaker_trip_count": s.breaker_trip_count or 0,
            }
            for s in sockets
        ]
        return JSONResponse({"marina_id": marina_id, "alarms": alarms})
    finally:
        db.close()
