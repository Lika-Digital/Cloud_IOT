"""Camera endpoints — stream and YOLO detections."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models.pedestal import Pedestal
from ..services.camera_service import get_video_detections, stream_ip_camera

router = APIRouter(prefix="/api/camera", tags=["camera"])


@router.get("/{pedestal_id}/detections")
def camera_detections(pedestal_id: int, db: DBSession = Depends(get_db)):
    """
    Return YOLOv8 ship detection data for the demo video (synthetic mode)
    or a note that real-time detections aren't pre-processed (real mode).

    Response: list of {time_s, detections: [{label, confidence, x1, y1, x2, y2}]}
    """
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")

    detections = get_video_detections(pedestal_id)
    return {"pedestal_id": pedestal_id, "mode": "mock_or_yolo", "frames": detections}


@router.get("/{pedestal_id}/stream")
def camera_stream(pedestal_id: int, db: DBSession = Depends(get_db)):
    """
    Proxy the real IP camera MJPEG stream.
    Only usable in 'real' mode with a camera_ip configured.
    """
    pedestal = db.get(Pedestal, pedestal_id)
    if not pedestal:
        raise HTTPException(status_code=404, detail="Pedestal not found")

    if not pedestal.camera_ip:
        raise HTTPException(status_code=400, detail="No camera IP configured for this pedestal")

    return StreamingResponse(
        stream_ip_camera(pedestal.camera_ip),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
