"""v3.11 — External API: load monitoring for ERP.

Direct FastAPI routes registered in `main.py` BEFORE the
`/api/ext/{path:path}` gateway catch-all. Auth + per-endpoint enable toggle
mirror `ext_pedestal_endpoints.py` (v3.3) and `ext_breaker_endpoints.py`
(v3.8) — same `_check_ext_auth` + `_endpoint_enabled` flow.

Routes:
  GET /api/ext/pedestals/{pedestal_id}/load
  GET /api/ext/pedestals/{pedestal_id}/sockets/{socket_id}/load
  GET /api/ext/marinas/{marina_id}/load/alarms
  GET /api/ext/pedestals/{pedestal_id}/load/alarms
  GET /api/ext/pedestals/{pedestal_id}/sockets/{socket_id}/load/history
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
from ..models.external_api import ExternalApiConfig
from ..models.meter_load_alarm import MeterLoadAlarm
from ..models.pedestal import Pedestal
from ..models.pedestal_config import PedestalConfig
from ..models.socket_config import SocketConfig
from .meter_load import serialize_alarm, serialize_load_state

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ext-meter-load"])

_EP_PEDESTAL_LOAD = "load.pedestal_get_ext"
_EP_SOCKET_LOAD   = "load.socket_get_ext"
_EP_MARINA_ALARMS = "load.marina_alarms_ext"
_EP_PED_ALARMS    = "load.pedestal_alarms_ext"
_EP_HISTORY       = "load.socket_history_ext"


# ── Auth + toggle helpers (copied 1:1 from ext_breaker_endpoints) ──────────

def _check_ext_auth(request: Request):
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
        {"error": "Feature not available", "reason": "Not enabled"}, status_code=503,
    )


# ── 1. Pedestal-wide load ───────────────────────────────────────────────────

@router.get("/api/ext/pedestals/{pedestal_id}/load")
async def ext_pedestal_load(pedestal_id: int, request: Request):
    _, err = _check_ext_auth(request)
    if err:
        return err
    if not _endpoint_enabled(_EP_PEDESTAL_LOAD):
        return _feature_not_available()

    db = SessionLocal()
    try:
        if db.get(Pedestal, pedestal_id) is None:
            return JSONResponse({"detail": "Pedestal not found"}, status_code=404)
        rows = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == pedestal_id,
        ).order_by(SocketConfig.socket_id).all()
        return JSONResponse({
            "pedestal_id": pedestal_id,
            "sockets": [serialize_load_state(r) for r in rows],
        })
    finally:
        db.close()


# ── 2. Single-socket load ───────────────────────────────────────────────────

@router.get("/api/ext/pedestals/{pedestal_id}/sockets/{socket_id}/load")
async def ext_socket_load(pedestal_id: int, socket_id: int, request: Request):
    _, err = _check_ext_auth(request)
    if err:
        return err
    if not _endpoint_enabled(_EP_SOCKET_LOAD):
        return _feature_not_available()

    db = SessionLocal()
    try:
        if db.get(Pedestal, pedestal_id) is None:
            return JSONResponse({"detail": "Pedestal not found"}, status_code=404)
        cfg = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == pedestal_id,
            SocketConfig.socket_id == socket_id,
        ).first()
        if cfg is None:
            return JSONResponse({"detail": "Socket not found on this pedestal"}, status_code=404)
        return JSONResponse(serialize_load_state(cfg))
    finally:
        db.close()


# ── 3. Marina-wide active alarms ────────────────────────────────────────────

@router.get("/api/ext/marinas/{marina_id}/load/alarms")
async def ext_marina_load_alarms(marina_id: str, request: Request):
    """Active alarms (warning OR critical, unresolved) across every pedestal
    whose cabinet id matches `MAR_{marina_id}_...`. Mirrors v3.8 breaker
    marina aggregator."""
    _, err = _check_ext_auth(request)
    if err:
        return err
    if not _endpoint_enabled(_EP_MARINA_ALARMS):
        return _feature_not_available()

    safe = marina_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"MAR_{safe}_%"

    db = SessionLocal()
    try:
        cfg_rows = db.query(PedestalConfig).filter(
            PedestalConfig.opta_client_id.like(pattern, escape="\\")
        ).all()
        pedestal_ids = [c.pedestal_id for c in cfg_rows]
        if not pedestal_ids:
            return JSONResponse({"marina_id": marina_id, "alarms": []})

        rows = (
            db.query(MeterLoadAlarm)
            .filter(
                MeterLoadAlarm.pedestal_id.in_(pedestal_ids),
                MeterLoadAlarm.resolved_at.is_(None),
            )
            .order_by(MeterLoadAlarm.triggered_at.desc())
            .all()
        )
        return JSONResponse({
            "marina_id": marina_id,
            "alarms": [serialize_alarm(a) for a in rows],
        })
    finally:
        db.close()


# ── 4. Pedestal-wide active alarms ──────────────────────────────────────────

@router.get("/api/ext/pedestals/{pedestal_id}/load/alarms")
async def ext_pedestal_load_alarms(pedestal_id: int, request: Request):
    _, err = _check_ext_auth(request)
    if err:
        return err
    if not _endpoint_enabled(_EP_PED_ALARMS):
        return _feature_not_available()

    db = SessionLocal()
    try:
        if db.get(Pedestal, pedestal_id) is None:
            return JSONResponse({"detail": "Pedestal not found"}, status_code=404)
        rows = (
            db.query(MeterLoadAlarm)
            .filter(
                MeterLoadAlarm.pedestal_id == pedestal_id,
                MeterLoadAlarm.resolved_at.is_(None),
            )
            .order_by(MeterLoadAlarm.triggered_at.desc())
            .all()
        )
        return JSONResponse({
            "pedestal_id": pedestal_id,
            "alarms": [serialize_alarm(a) for a in rows],
        })
    finally:
        db.close()


# ── 5. Socket alarm history (last 50) ───────────────────────────────────────

@router.get("/api/ext/pedestals/{pedestal_id}/sockets/{socket_id}/load/history")
async def ext_socket_load_history(pedestal_id: int, socket_id: int, request: Request):
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
            db.query(MeterLoadAlarm)
            .filter(
                MeterLoadAlarm.pedestal_id == pedestal_id,
                MeterLoadAlarm.socket_id == socket_id,
            )
            .order_by(MeterLoadAlarm.triggered_at.desc())
            .limit(50)
            .all()
        )
        return JSONResponse({
            "pedestal_id": pedestal_id,
            "socket_id": socket_id,
            "events": [serialize_alarm(a) for a in rows],
        })
    finally:
        db.close()
