"""Camera endpoints — live snapshot and MJPEG stream proxy."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..auth.dependencies import require_admin

router = APIRouter(prefix="/api/camera", tags=["camera"])


def _get_pedestal_cfg(db: DBSession, pedestal_id: int):
    """Return PedestalConfig for pedestal_id, or None."""
    from ..models.pedestal_config import PedestalConfig
    return db.query(PedestalConfig).filter(
        PedestalConfig.pedestal_id == pedestal_id
    ).first()


@router.get("/{pedestal_id}/snapshot")
async def camera_snapshot(
    pedestal_id: int,
    db: DBSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Grab a single JPEG frame from the pedestal's configured RTSP stream.
    Used by the berth live-view modal (polls every 2 s).
    Returns 404 if no camera is configured, 503 if camera is unreachable.
    """
    from ..services.berth_analyzer import grab_snapshot

    cfg = _get_pedestal_cfg(db, pedestal_id)
    if not cfg or not cfg.camera_stream_url:
        raise HTTPException(
            status_code=404,
            detail="No camera stream URL configured for this pedestal",
        )
    if not cfg.camera_reachable:
        raise HTTPException(
            status_code=503,
            detail="Camera is not currently reachable",
        )

    try:
        data = await grab_snapshot(
            cfg.camera_stream_url,
            cfg.camera_username or "",
            cfg.camera_password or "",
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Snapshot failed: {exc}")

    return Response(
        content=data,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{pedestal_id}/stream")
def camera_stream(
    pedestal_id: int,
    db: DBSession = Depends(get_db),
):
    """
    Proxy the IP camera MJPEG stream.
    Falls back to camera_fqdn if stream URL is not an HTTP MJPEG source.
    """
    from ..services.camera_service import stream_ip_camera

    cfg = _get_pedestal_cfg(db, pedestal_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="Pedestal not found")

    camera_ip = cfg.camera_fqdn or ""
    if not camera_ip and cfg.camera_stream_url:
        # Extract host from stream URL for MJPEG fallback
        import re
        m = re.search(r"://(?:[^:@]+:[^@]+@)?([^/:]+)", cfg.camera_stream_url)
        camera_ip = m.group(1) if m else ""

    # Final fallback: use camera_ip stored directly on the Pedestal record
    if not camera_ip:
        from ..models.pedestal import Pedestal
        pedestal = db.get(Pedestal, pedestal_id)
        camera_ip = (pedestal.camera_ip or "") if pedestal else ""

    if not camera_ip:
        raise HTTPException(status_code=400, detail="No camera IP configured for this pedestal")

    return StreamingResponse(
        stream_ip_camera(camera_ip),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
