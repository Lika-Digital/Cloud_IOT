"""
External API — direct pedestal endpoints for berth occupancy and camera.

These routes are registered in main.py BEFORE the gateway catch-all
(ANY /api/ext/{path:path}), so FastAPI resolves them first.

Each endpoint:
  1. Validates the same external API JWT as the gateway.
  2. Checks the per-endpoint enable toggle (allowed_endpoints in ExternalApiConfig).
  3. Checks feature availability (camera configured/reachable, berths defined).
  4. Returns 503 for disabled or unavailable features; 401/403 for auth failures.

Routes:
  GET /api/ext/pedestals/{pedestal_id}/berths/occupancy
  GET /api/ext/pedestals/{pedestal_id}/camera/frame
  GET /api/ext/pedestals/{pedestal_id}/camera/stream
"""
import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from ..config import settings
from ..database import SessionLocal
from ..auth.user_database import UserSessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ext-pedestal"])

# ── Catalog IDs for toggle checks ─────────────────────────────────────────────

_EP_BERTHS_OCC = "berths.occupancy_ext"
_EP_CAM_FRAME  = "camera.frame_ext"
_EP_CAM_STREAM = "camera.stream_ext"
_EP_PUSH_IMAGE = "berths.push_image_ext"   # v3.16 — ERP pushes a match image


# ── Auth + config helpers ─────────────────────────────────────────────────────

def _check_ext_auth(request: Request):
    """
    Validate external API Bearer JWT (same logic as gateway router).
    Returns (payload_dict, None) on success or (None, error_JSONResponse) on failure.
    Checks gateway active flag; per-endpoint toggle is checked separately.
    """
    import hmac
    import jwt as pyjwt
    from ..models.external_api import ExternalApiConfig

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None, JSONResponse(
            {"detail": "Missing Authorization header"}, status_code=401
        )

    token = auth[7:].strip()
    try:
        payload = pyjwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except pyjwt.ExpiredSignatureError:
        return None, JSONResponse(
            {"detail": "Invalid or expired API key"}, status_code=401
        )
    except pyjwt.InvalidTokenError:
        return None, JSONResponse(
            {"detail": "Invalid or expired API key"}, status_code=401
        )

    role = payload.get("role")
    if role not in {"external_api", "api_client"}:
        return None, JSONResponse(
            {"detail": "Invalid or expired API key"}, status_code=401
        )

    db = SessionLocal()
    try:
        cfg = db.get(ExternalApiConfig, 1)
    finally:
        db.close()

    if cfg is None:
        return None, JSONResponse(
            {"detail": "External API not configured"}, status_code=403
        )
    if not cfg.active:
        return None, JSONResponse(
            {"error": "Feature not available", "reason": "Not enabled"}, status_code=503
        )
    if role == "external_api":
        if not hmac.compare_digest(cfg.api_key or "", token):
            return None, JSONResponse(
                {"detail": "Invalid API key"}, status_code=403
            )

    return payload, None


def _endpoint_enabled(endpoint_id: str) -> bool:
    """Return True if the endpoint ID is in the allowed_endpoints list."""
    from ..models.external_api import ExternalApiConfig

    db = SessionLocal()
    try:
        cfg = db.get(ExternalApiConfig, 1)
        if not cfg:
            return False
        allowed = json.loads(cfg.allowed_endpoints or "[]")
        return any(e["id"] == endpoint_id for e in allowed)
    finally:
        db.close()


def _resolve_pedestal(pedestal_id: str):
    """
    Resolve pedestal_id string to (db_int_id, display_id).
    Accepts numeric primary-key string or opta_client_id (e.g. "MAR_KRK_ORM_01").
    Returns (None, None) if not found.
    """
    from ..models.pedestal import Pedestal
    from ..models.pedestal_config import PedestalConfig

    db = SessionLocal()
    try:
        if pedestal_id.isdigit():
            p = db.get(Pedestal, int(pedestal_id))
            if p:
                cfg = db.query(PedestalConfig).filter(
                    PedestalConfig.pedestal_id == p.id
                ).first()
                display = (cfg.opta_client_id if cfg and cfg.opta_client_id else str(p.id))
                return p.id, display
        # Try lookup by opta_client_id
        cfg = db.query(PedestalConfig).filter(
            PedestalConfig.opta_client_id == pedestal_id
        ).first()
        if cfg:
            return cfg.pedestal_id, pedestal_id
        return None, None
    finally:
        db.close()


# ── 1. Berth occupancy ────────────────────────────────────────────────────────

@router.get("/api/ext/pedestals/{pedestal_id}/berths/occupancy")
async def ext_berths_occupancy(pedestal_id: str, request: Request):
    """
    Return current occupancy status for all berths under the given pedestal.

    pedestal_id: numeric DB id or opta_client_id string (e.g. MAR_KRK_ORM_01)

    Response:
      200 { pedestal_id, berths: [{berth_id, berth_name, occupied, ...}] }
      200 { pedestal_id, berths: [], message: "No berth definitions..." }
      503 { error, reason } — disabled or feature unavailable
    """
    _, err = _check_ext_auth(request)
    if err:
        return err

    if not _endpoint_enabled(_EP_BERTHS_OCC):
        return JSONResponse(
            {"error": "Feature not available", "reason": "Not enabled"},
            status_code=503,
        )

    db_id, display_id = _resolve_pedestal(pedestal_id)
    if db_id is None:
        return JSONResponse({"detail": "Pedestal not found"}, status_code=404)

    from ..auth.berth_models import Berth

    user_db = UserSessionLocal()
    try:
        berths = user_db.query(Berth).filter(Berth.pedestal_id == db_id).all()
    finally:
        user_db.close()

    if not berths:
        return JSONResponse({
            "pedestal_id": display_id,
            "berths": [],
            "message": "No berth definitions found for this pedestal",
        }, status_code=200)

    berth_list = []
    for b in berths:
        if b.last_analyzed is None:
            berth_list.append({
                "berth_id": b.id,
                "berth_name": b.name,
                "occupied": None,
                "note": "No analysis performed yet",
            })
        else:
            berth_list.append({
                "berth_id": b.id,
                "berth_name": b.name,
                "occupied": bool(b.occupied_bit),
                "last_analyzed": b.last_analyzed.isoformat(),
            })

    return JSONResponse({"pedestal_id": display_id, "berths": berth_list})


# ── 1b. ERP pushes a reference image for a berth (v3.16) ──────────────────────

@router.post("/api/ext/pedestals/{pedestal_id}/berths/{berth_id}/reference-image")
async def ext_push_berth_image(pedestal_id: str, berth_id: int, request: Request):
    """ERP pushes an image (raw bytes) to MATCH against an EXISTING berth/sector.

    Sectors are created only on the NUC — this endpoint targets a berth_id that
    must already exist under the pedestal; it never creates one. The image is
    stored as a reference image for that berth and used by the histogram match
    during analysis.

      200 { ok, berth_id, stored }
      404 pedestal/berth not found · 422 empty body · 503 disabled
    """
    _, err = _check_ext_auth(request)
    if err:
        return err
    if not _endpoint_enabled(_EP_PUSH_IMAGE):
        return JSONResponse({"error": "Feature not available", "reason": "Not enabled"}, status_code=503)

    db_id, _display = _resolve_pedestal(pedestal_id)
    if db_id is None:
        return JSONResponse({"detail": "Pedestal not found"}, status_code=404)

    from ..auth.berth_models import Berth
    user_db = UserSessionLocal()
    try:
        berth = user_db.query(Berth).filter(
            Berth.id == berth_id, Berth.pedestal_id == db_id
        ).first()
    finally:
        user_db.close()
    if berth is None:
        return JSONResponse({"detail": "Berth not found for this pedestal"}, status_code=404)

    data = await request.body()
    if not data:
        return JSONResponse({"detail": "Empty image body"}, status_code=422)

    from datetime import datetime
    from ..services.berth_analyzer import save_reference_image
    fname = f"erp_{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.jpg"
    try:
        save_reference_image(berth_id, fname, data)
    except Exception as e:
        return JSONResponse({"detail": f"Failed to store image: {e}"}, status_code=500)
    return JSONResponse({"ok": True, "berth_id": berth_id, "stored": fname})


# ── 2. Camera frame ───────────────────────────────────────────────────────────

@router.get("/api/ext/pedestals/{pedestal_id}/camera/frame")
async def ext_camera_frame(pedestal_id: str, request: Request):
    """
    Grab a single live JPEG frame from the pedestal camera RTSP stream
    and return it with Content-Type: image/jpeg.

    Returns 503 if camera not configured, not reachable, or frame capture fails.
    """
    _, err = _check_ext_auth(request)
    if err:
        return err

    if not _endpoint_enabled(_EP_CAM_FRAME):
        return JSONResponse(
            {"error": "Feature not available", "reason": "Not enabled"},
            status_code=503,
        )

    db_id, _ = _resolve_pedestal(pedestal_id)
    if db_id is None:
        return JSONResponse({"detail": "Pedestal not found"}, status_code=404)

    from ..models.pedestal_config import PedestalConfig

    db = SessionLocal()
    try:
        cfg = db.query(PedestalConfig).filter(
            PedestalConfig.pedestal_id == db_id
        ).first()
    finally:
        db.close()

    if not cfg or not cfg.camera_stream_url:
        return JSONResponse(
            {"error": "Camera stream unavailable",
             "reason": "Stream unreachable or not configured"},
            status_code=503,
        )

    if not cfg.camera_reachable:
        return JSONResponse(
            {"error": "Camera stream unavailable",
             "reason": "Stream unreachable or not configured"},
            status_code=503,
        )

    try:
        # Import from module so patch("app.services.berth_analyzer.grab_snapshot") works
        from ..services.berth_analyzer import grab_snapshot
        frame_bytes = await grab_snapshot(
            cfg.camera_stream_url,
            username=cfg.camera_username or "",
            password=cfg.camera_password or "",
        )
    except Exception:
        return JSONResponse(
            {"error": "Camera stream unavailable",
             "reason": "Failed to capture valid frame"},
            status_code=503,
        )

    if not frame_bytes:
        return JSONResponse(
            {"error": "Camera stream unavailable",
             "reason": "Failed to capture valid frame"},
            status_code=503,
        )

    return Response(
        content=frame_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


# ── 3. Camera stream URL ──────────────────────────────────────────────────────

@router.get("/api/ext/pedestals/{pedestal_id}/camera/stream")
async def ext_camera_stream(pedestal_id: str, request: Request):
    """
    Return the RTSP stream URL for the pedestal camera plus current reachability.
    Does not proxy the stream — ERP client connects directly.

    Response:
      200 { pedestal_id, stream_url, reachable, last_checked }
      503 { error, reason } — not configured or disabled
    """
    _, err = _check_ext_auth(request)
    if err:
        return err

    if not _endpoint_enabled(_EP_CAM_STREAM):
        return JSONResponse(
            {"error": "Feature not available", "reason": "Not enabled"},
            status_code=503,
        )

    db_id, display_id = _resolve_pedestal(pedestal_id)
    if db_id is None:
        return JSONResponse({"detail": "Pedestal not found"}, status_code=404)

    from ..models.pedestal_config import PedestalConfig

    db = SessionLocal()
    try:
        cfg = db.query(PedestalConfig).filter(
            PedestalConfig.pedestal_id == db_id
        ).first()
    finally:
        db.close()

    if not cfg or not cfg.camera_stream_url:
        return JSONResponse(
            {"error": "Camera stream unavailable",
             "reason": "No camera configured for this pedestal"},
            status_code=503,
        )

    return JSONResponse({
        "pedestal_id": display_id,
        "stream_url": cfg.camera_stream_url,
        "reachable": bool(cfg.camera_reachable),
        "last_checked": (
            cfg.last_camera_check.isoformat() if cfg.last_camera_check else None
        ),
    })
