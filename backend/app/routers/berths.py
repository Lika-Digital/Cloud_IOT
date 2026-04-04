"""
Berth occupancy and reservation endpoints.

Public / customer routes:
  GET  /api/berths                               → list all berths (with camera status)
  GET  /api/berths/availability                  → check free berths for a date range
  POST /api/customer/berths/reserve              → create a reservation
  GET  /api/customer/berths/mine                 → customer's own reservations
  DELETE /api/customer/berths/reservations/{id}  → cancel a reservation

Admin routes:
  GET  /api/admin/berths/calendar/{berth_id}            → calendar entries for a berth
  POST /api/admin/berths/{id}/analyze                   → on-demand snapshot + ship detection
  PUT  /api/admin/berths/{id}/status                    → manually set berth status
  GET  /api/admin/berths/{id}/reference-images          → list reference images
  POST /api/admin/berths/{id}/reference-images          → upload reference images
  DELETE /api/admin/berths/{id}/reference-images/{fn}  → delete a reference image
"""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from ..auth.user_database import get_user_db
from ..auth.berth_models import Berth, BerthReservation
from ..auth.customer_models import Customer
from ..auth.dependencies import require_admin
from ..auth.customer_dependencies import require_customer
from ..database import get_db

router = APIRouter(tags=["berths"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class BerthOut(BaseModel):
    id: int
    name: str
    pedestal_id: Optional[int]
    berth_type: str = "transit"
    status: str
    detected_status: str
    last_analyzed: Optional[str]
    # ML pipeline outputs
    occupied_bit: int = 0
    match_ok_bit: int = 0
    state_code: int = 0       # 0=FREE  1=OCCUPIED_CORRECT  2=OCCUPIED_WRONG
    alarm: int = 0
    match_score: Optional[float] = None
    analysis_error: Optional[str] = None
    confidence: float = 0.0   # OpenVINO detection confidence (Section 6)
    # Camera info (from pedestal_config)
    camera_stream_url: Optional[str] = None
    camera_reachable: bool = False
    # Reference images
    reference_image_count: int = 0
    # Re-ID embedding (Section 7)
    sample_embedding_path: Optional[str] = None
    sample_updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class ReservationIn(BaseModel):
    berth_id: int
    check_in_date: str   # YYYY-MM-DD
    check_out_date: str  # YYYY-MM-DD
    notes: Optional[str] = Field(None, max_length=500)


class ReservationOut(BaseModel):
    id: int
    berth_id: int
    berth_name: str
    customer_id: int
    check_in_date: str
    check_out_date: str
    status: str
    notes: Optional[str]
    created_at: str

    class Config:
        from_attributes = True


class CalendarEntry(BaseModel):
    reservation_id: int
    customer_id: int
    check_in_date: str
    check_out_date: str
    status: str


class BerthStatusUpdate(BaseModel):
    status: str  # "free" | "occupied" | "reserved"


class BerthConfigUpdate(BaseModel):
    name: Optional[str] = None
    pedestal_id: Optional[int] = None
    berth_type: Optional[str] = None   # "transit" | "yearly"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _berth_to_out(b: Berth, pedestal_cfg=None, ref_count: int = 0) -> BerthOut:
    return BerthOut(
        id=b.id,
        name=b.name,
        pedestal_id=b.pedestal_id,
        berth_type=b.berth_type or "transit",
        status=b.status,
        detected_status=b.detected_status,
        last_analyzed=b.last_analyzed.isoformat() if b.last_analyzed else None,
        occupied_bit=b.occupied_bit or 0,
        match_ok_bit=b.match_ok_bit or 0,
        state_code=b.state_code or 0,
        alarm=b.alarm or 0,
        match_score=b.match_score,
        analysis_error=b.analysis_error,
        confidence=0.0,  # populated by analyze endpoint when available
        camera_stream_url=pedestal_cfg.camera_stream_url if pedestal_cfg else None,
        camera_reachable=bool(pedestal_cfg.camera_reachable) if pedestal_cfg else False,
        reference_image_count=ref_count,
        sample_embedding_path=getattr(b, "sample_embedding_path", None),
        sample_updated_at=(
            b.sample_updated_at.isoformat()
            if getattr(b, "sample_updated_at", None) else None
        ),
    )


def _reservation_to_out(r: BerthReservation, berth_name: str) -> ReservationOut:
    return ReservationOut(
        id=r.id,
        berth_id=r.berth_id,
        berth_name=berth_name,
        customer_id=r.customer_id,
        check_in_date=r.check_in_date.isoformat(),
        check_out_date=r.check_out_date.isoformat(),
        status=r.status,
        notes=r.notes,
        created_at=r.created_at.isoformat(),
    )


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except Exception:
        raise HTTPException(status_code=422, detail=f"Invalid date format: '{s}'. Use YYYY-MM-DD.")


def _get_pedestal_cfg_map(db: DBSession) -> dict:
    """Return {pedestal_id: PedestalConfig} map from pedestal.db."""
    from ..models.pedestal_config import PedestalConfig
    return {c.pedestal_id: c for c in db.query(PedestalConfig).all()}


# ─── Public routes ────────────────────────────────────────────────────────────

@router.get("/api/berths", response_model=List[BerthOut])
def list_berths(
    user_db: DBSession = Depends(get_user_db),
    db: DBSession = Depends(get_db),
):
    """
    Return berths synced to the registered pedestal list.
    - Auto-creates a berth for any pedestal that doesn't have one yet.
    - Returns only berths whose pedestal_id matches a real pedestal.
    - Berth count always equals pedestal count.
    """
    from ..services.berth_analyzer import list_reference_images
    from ..models.pedestal import Pedestal

    pedestals = db.query(Pedestal).order_by(Pedestal.id).all()
    pedestal_ids = {p.id for p in pedestals}

    # Auto-create missing berths (one per pedestal)
    existing_ped_ids = {b.pedestal_id for b in user_db.query(Berth).all() if b.pedestal_id}
    for ped in pedestals:
        if ped.id not in existing_ped_ids:
            user_db.add(Berth(
                name=f"Berth {ped.name}",
                pedestal_id=ped.id,
                berth_type="transit",
                status="free",
                detected_status="free",
            ))
    user_db.commit()

    # Return only berths tied to real pedestals, one per pedestal (first match)
    berths = user_db.query(Berth).order_by(Berth.id).all()
    seen_pedestals: set = set()
    filtered: list = []
    for b in berths:
        if b.pedestal_id in pedestal_ids and b.pedestal_id not in seen_pedestals:
            seen_pedestals.add(b.pedestal_id)
            filtered.append(b)

    cfg_map = _get_pedestal_cfg_map(db)
    return [
        _berth_to_out(b, cfg_map.get(b.pedestal_id), len(list_reference_images(b.id)))
        for b in filtered
    ]


@router.get("/api/berths/availability", response_model=List[BerthOut])
def get_availability(
    check_in: str,
    check_out: str,
    user_db: DBSession = Depends(get_user_db),
    db: DBSession = Depends(get_db),
):
    ci = _parse_date(check_in)
    co = _parse_date(check_out)
    if co <= ci:
        raise HTTPException(status_code=422, detail="check_out must be after check_in")

    from ..services.berth_analyzer import list_reference_images
    berths = user_db.query(Berth).order_by(Berth.id).all()
    cfg_map = _get_pedestal_cfg_map(db)
    free_berths = []
    for b in berths:
        conflicting = (
            user_db.query(BerthReservation)
            .filter(
                BerthReservation.berth_id == b.id,
                BerthReservation.status == "confirmed",
                BerthReservation.check_in_date < co,
                BerthReservation.check_out_date > ci,
            )
            .first()
        )
        if conflicting is None and b.detected_status != "occupied":
            free_berths.append(
                _berth_to_out(b, cfg_map.get(b.pedestal_id), len(list_reference_images(b.id)))
            )
    return free_berths


# ─── Customer routes ──────────────────────────────────────────────────────────

@router.post("/api/customer/berths/reserve", response_model=ReservationOut)
def reserve_berth(
    body: ReservationIn,
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    ci = _parse_date(body.check_in_date)
    co = _parse_date(body.check_out_date)
    if co <= ci:
        raise HTTPException(status_code=422, detail="check_out must be after check_in")
    if ci < date.today():
        raise HTTPException(status_code=422, detail="check_in must not be in the past")
    if (co - ci).days > 365:
        raise HTTPException(status_code=422, detail="Reservation duration cannot exceed 365 days")

    berth = user_db.get(Berth, body.berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")

    conflicting = (
        user_db.query(BerthReservation)
        .filter(
            BerthReservation.berth_id == body.berth_id,
            BerthReservation.status == "confirmed",
            BerthReservation.check_in_date < co,
            BerthReservation.check_out_date > ci,
        )
        .first()
    )
    if conflicting:
        raise HTTPException(status_code=409, detail="Berth is already reserved for those dates")

    reservation = BerthReservation(
        berth_id=body.berth_id,
        customer_id=customer.id,
        check_in_date=ci,
        check_out_date=co,
        notes=body.notes,
        status="confirmed",
    )
    user_db.add(reservation)

    if ci <= date.today() <= co:
        berth_row = user_db.get(Berth, body.berth_id)
        if berth_row:
            berth_row.status = "reserved"

    user_db.commit()
    user_db.refresh(reservation)
    return _reservation_to_out(reservation, berth.name)


@router.get("/api/customer/berths/mine", response_model=List[ReservationOut])
def get_my_reservations(
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    rows = (
        user_db.query(BerthReservation)
        .filter(BerthReservation.customer_id == customer.id)
        .order_by(BerthReservation.check_in_date.desc())
        .all()
    )
    berth_map = {b.id: b for b in user_db.query(Berth).all()}
    return [
        _reservation_to_out(r, berth_map[r.berth_id].name if r.berth_id in berth_map else "Unknown")
        for r in rows
    ]


@router.delete("/api/customer/berths/reservations/{reservation_id}")
def cancel_reservation(
    reservation_id: int,
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    res = user_db.get(BerthReservation, reservation_id)
    if not res or res.customer_id != customer.id:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if res.status == "cancelled":
        raise HTTPException(status_code=400, detail="Already cancelled")
    res.status = "cancelled"
    user_db.commit()
    return {"ok": True}


# ─── Admin routes ─────────────────────────────────────────────────────────────

@router.get("/api/admin/berths/calendar/{berth_id}", response_model=List[CalendarEntry])
def get_berth_calendar(
    berth_id: int,
    user_db: DBSession = Depends(get_user_db),
    _admin=Depends(require_admin),
):
    rows = (
        user_db.query(BerthReservation)
        .filter(BerthReservation.berth_id == berth_id)
        .order_by(BerthReservation.check_in_date)
        .all()
    )
    return [
        CalendarEntry(
            reservation_id=r.id,
            customer_id=r.customer_id,
            check_in_date=r.check_in_date.isoformat(),
            check_out_date=r.check_out_date.isoformat(),
            status=r.status,
        )
        for r in rows
    ]


@router.post("/api/admin/berths/{berth_id}/analyze")
async def trigger_analysis(
    berth_id: int,
    user_db: DBSession = Depends(get_user_db),
    db: DBSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    On-demand berth analysis:
      1. Get latest frame from frame buffer; fall back to live grab if none.
      2. Crop to detection zone if configured.
      3. Try YOLOv8n OpenVINO inference; fall back to Laplacian if unavailable.
      4. Compare with reference images using histogram similarity.
      5. Save training crop asynchronously.
      6. Persist result and broadcast via WebSocket.
    """
    import asyncio as _asyncio
    from ..models.pedestal_config import PedestalConfig
    from ..services.berth_analyzer import (
        analyze_berth_now, grab_snapshot, list_reference_images,
        detect_ship, compute_match_score,
    )
    from ..services.websocket_manager import ws_manager
    from ..services.frame_buffer import get_latest_frame
    from ..services.cv_services import yolo_detector
    from ..services.training_data import save_crop

    berth = user_db.get(Berth, berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")
    if not berth.pedestal_id:
        raise HTTPException(status_code=400, detail="Berth has no pedestal configured")

    cfg = db.query(PedestalConfig).filter(
        PedestalConfig.pedestal_id == berth.pedestal_id
    ).first()
    if not cfg or not cfg.camera_stream_url:
        raise HTTPException(
            status_code=400,
            detail="No camera stream URL configured for this pedestal. "
                   "Set it in Settings → Device Configuration.",
        )
    if not cfg.camera_reachable:
        raise HTTPException(
            status_code=503,
            detail="Camera is not reachable. Check network connection and camera settings.",
        )

    # 1. Get frame: try buffer first, fall back to live grab
    snapshot = get_latest_frame(berth.pedestal_id)
    if snapshot is None:
        snapshot = await grab_snapshot(
            cfg.camera_stream_url,
            username=cfg.camera_username or "",
            password=cfg.camera_password or "",
        )

    # 2. Crop to detection zone if configured
    crop = snapshot
    zone_rect = None
    if berth.use_detection_zone and all(
        v is not None for v in [berth.zone_x1, berth.zone_y1, berth.zone_x2, berth.zone_y2]
    ):
        try:
            from PIL import Image
            import io as _io
            img = Image.open(_io.BytesIO(snapshot)).convert("RGB")
            w, h = img.size
            x1 = int(berth.zone_x1 * w)
            y1 = int(berth.zone_y1 * h)
            x2 = int(berth.zone_x2 * w)
            y2 = int(berth.zone_y2 * h)
            cropped = img.crop((x1, y1, x2, y2))
            buf = _io.BytesIO()
            cropped.save(buf, format="JPEG", quality=90)
            crop = buf.getvalue()
            zone_rect = {
                "x1": berth.zone_x1, "y1": berth.zone_y1,
                "x2": berth.zone_x2, "y2": berth.zone_y2,
            }
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).warning("Berth %d zone crop failed: %s", berth_id, exc)
            crop = snapshot  # fall back to full frame

    # 3. Detection: try YOLOv8n OpenVINO first, fall back to Laplacian
    ov_result = yolo_detector.detect(crop, conf_threshold=berth.detect_conf_threshold or 0.3)
    confidence = 0.0
    if ov_result.get("occupied") is not None:
        # OpenVINO inference succeeded
        occupied = bool(ov_result["occupied"])
        confidence = float(ov_result.get("confidence", 0.0))
    else:
        # Fall back to existing Laplacian detection
        # detect_conf_threshold is re-purposed as Laplacian variance threshold (default 300)
        laplacian_threshold = berth.detect_conf_threshold or 300.0
        occupied = detect_ship(crop, threshold=laplacian_threshold)
        confidence = 0.0

    # 4. Run full analysis pipeline (handles match scoring)
    res = await analyze_berth_now(
        berth_id=berth_id,
        stream_url=cfg.camera_stream_url,
        camera_username=cfg.camera_username or "",
        camera_password=cfg.camera_password or "",
        detect_threshold=berth.detect_conf_threshold or 300.0,
        match_threshold=berth.match_threshold or 0.75,
    )
    # If we got a concrete OpenVINO result, override the occupied_bit from full analysis
    if ov_result.get("occupied") is not None:
        if not occupied:
            res = {
                "occupied_bit": 0, "match_ok_bit": 0,
                "state_code": 0, "alarm": 0, "match_score": None, "error": None,
            }
        # else keep the full analysis result (it also ran detect_ship but we trust OV)

    # Add confidence to result
    res["confidence"] = confidence

    # 5. Save training crop (fire-and-forget)
    try:
        result_label = "occupied" if res.get("occupied_bit") else "empty"
        camera_id = str(berth.pedestal_id or berth_id)
        _asyncio.create_task(
            _async_save_crop(berth_id, camera_id, crop, result_label, confidence, zone_rect or {})
        )
    except Exception:
        pass  # never block the response

    # Persist ML outputs
    b = user_db.get(Berth, berth_id)
    b.occupied_bit   = res.get("occupied_bit", 0)
    b.match_ok_bit   = res.get("match_ok_bit", 0)
    b.state_code     = res.get("state_code", 0)
    b.alarm          = res.get("alarm", 0)
    b.match_score    = res.get("match_score")
    b.analysis_error = res.get("error")
    b.last_analyzed  = datetime.utcnow()
    if b.status != "reserved":
        b.status = "occupied" if b.occupied_bit else "free"
        b.detected_status = b.status
    user_db.commit()
    user_db.refresh(b)

    # Broadcast
    ref_count = len(list_reference_images(berth_id))
    cfg2 = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == b.pedestal_id).first()
    await ws_manager.broadcast({
        "event": "berth_occupancy_updated",
        "data": {"berths": [_berth_to_out(b, cfg2, ref_count).model_dump()]},
    })

    # Human-readable status for the UI toast
    if b.occupied_bit == 0:
        detected_label = "Berth is empty"
    elif b.match_score is None:
        detected_label = "Ship detected (no reference images to compare)"
    elif b.match_ok_bit:
        detected_label = f"Correct ship detected (score {b.match_score:.2f})"
    else:
        detected_label = f"Unknown ship detected (score {b.match_score:.2f})"

    return {"ok": True, "detected_status": detected_label, **res}


async def _async_save_crop(berth_id: int, camera_id: str, crop_bytes: bytes,
                            result: str, confidence: float, rect: dict):
    """Fire-and-forget async wrapper for save_crop."""
    import asyncio as _asyncio
    try:
        from ..services.training_data import save_crop
        loop = _asyncio.get_event_loop()
        await loop.run_in_executor(
            None, save_crop, berth_id, camera_id, crop_bytes, result, confidence, rect
        )
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).debug("save_crop failed (non-critical): %s", exc)


@router.post("/api/admin/berths/{berth_id}/match")
async def match_ship(
    berth_id: int,
    user_db: DBSession = Depends(get_user_db),
    db: DBSession = Depends(get_db),
    _admin=Depends(require_admin),
):
    """
    Compare the current camera frame against the stored Re-ID embedding for this berth.
    Requires the berth to be occupied and a sample embedding to be saved.
    """
    import asyncio as _asyncio
    from ..models.pedestal_config import PedestalConfig
    from ..services.berth_analyzer import grab_snapshot
    from ..services.frame_buffer import get_latest_frame
    from ..services.cv_services import reid_matcher
    from ..services.training_data import TRAINING_DATA_DIR, save_crop

    berth = user_db.get(Berth, berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")
    if not berth.pedestal_id:
        raise HTTPException(status_code=400, detail="Berth has no pedestal configured")
    if not berth.occupied_bit:
        raise HTTPException(status_code=400, detail="Berth is not currently occupied")

    cfg = db.query(PedestalConfig).filter(
        PedestalConfig.pedestal_id == berth.pedestal_id
    ).first()
    if not cfg or not cfg.camera_stream_url:
        raise HTTPException(status_code=400, detail="No camera stream URL configured")
    if not cfg.camera_reachable:
        raise HTTPException(status_code=503, detail="Camera is not reachable")

    # Get frame
    snapshot = get_latest_frame(berth.pedestal_id)
    if snapshot is None:
        snapshot = await grab_snapshot(
            cfg.camera_stream_url,
            username=cfg.camera_username or "",
            password=cfg.camera_password or "",
        )

    # Crop to detection zone
    crop = snapshot
    if berth.use_detection_zone and all(
        v is not None for v in [berth.zone_x1, berth.zone_y1, berth.zone_x2, berth.zone_y2]
    ):
        try:
            from PIL import Image
            import io as _io
            img = Image.open(_io.BytesIO(snapshot)).convert("RGB")
            w, h = img.size
            cropped = img.crop((
                int(berth.zone_x1 * w), int(berth.zone_y1 * h),
                int(berth.zone_x2 * w), int(berth.zone_y2 * h),
            ))
            buf = _io.BytesIO()
            cropped.save(buf, format="JPEG", quality=90)
            crop = buf.getvalue()
        except Exception:
            crop = snapshot

    if not reid_matcher.available:
        raise HTTPException(
            status_code=503,
            detail="Re-ID model not available on this server. "
                   "Run setup_openvino_models.py on the NUC first.",
        )

    # Load stored embedding
    storage_dir = getattr(berth, "sample_embedding_path", None)
    # sample_embedding_path holds the full .npy file path; derive storage_dir from it
    import os as _os
    if storage_dir and _os.path.isfile(storage_dir):
        npy_dir = _os.path.dirname(storage_dir)
    else:
        npy_dir = _os.path.join(TRAINING_DATA_DIR, "embeddings")

    stored_emb = reid_matcher.load_embedding(berth_id, npy_dir)
    if stored_emb is None:
        raise HTTPException(
            status_code=400,
            detail="No sample embedding stored for this berth. "
                   "Upload a sample image via POST /api/admin/berths/{id}/sample-embedding first.",
        )

    # Extract current embedding
    current_emb = reid_matcher.extract_embedding(crop)
    if current_emb is None:
        raise HTTPException(status_code=500, detail="Failed to extract embedding from current frame")

    match_score = reid_matcher.cosine_similarity(current_emb, stored_emb)

    # Save training crop
    try:
        camera_id = str(berth.pedestal_id or berth_id)
        _asyncio.create_task(
            _async_save_crop(berth_id, camera_id, crop, "match", match_score, {})
        )
    except Exception:
        pass

    return {
        "match_score": round(float(match_score), 4),
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.post("/api/admin/berths/{berth_id}/sample-embedding")
async def upload_sample_embedding(
    berth_id: int,
    file: UploadFile = File(...),
    user_db: DBSession = Depends(get_user_db),
    _admin=Depends(require_admin),
):
    """
    Upload a sample image and extract + save its Re-ID embedding for this berth.
    Used as the reference for future ship identity matching.
    """
    import os as _os
    from ..services.cv_services import reid_matcher
    from ..services.training_data import TRAINING_DATA_DIR

    berth = user_db.get(Berth, berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")

    if not reid_matcher.available:
        raise HTTPException(
            status_code=503,
            detail="Re-ID model not available on this server. "
                   "Run setup_openvino_models.py on the NUC first.",
        )

    img_data = await file.read()
    if not img_data:
        raise HTTPException(status_code=422, detail="Uploaded file is empty")

    embedding = reid_matcher.extract_embedding(img_data)
    if embedding is None:
        raise HTTPException(status_code=500, detail="Failed to extract Re-ID embedding from image")

    storage_dir = _os.path.join(TRAINING_DATA_DIR, "embeddings")
    saved_path = reid_matcher.save_embedding(berth_id, embedding, storage_dir)
    if saved_path is None:
        raise HTTPException(status_code=500, detail="Failed to save embedding to disk")

    # Persist path and update timestamp in DB
    berth.sample_embedding_path = saved_path
    berth.sample_updated_at = datetime.utcnow()
    user_db.commit()

    return {
        "ok": True,
        "berth_id": berth_id,
        "embedding_dim": int(embedding.shape[0]),
        "path": saved_path,
    }


@router.put("/api/admin/berths/{berth_id}/config")
def update_berth_config(
    berth_id: int,
    body: BerthConfigUpdate,
    user_db: DBSession = Depends(get_user_db),
    _admin=Depends(require_admin),
):
    """Update berth name, pedestal assignment, and berth type (transit/yearly)."""
    berth = user_db.get(Berth, berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")
    if body.name is not None:
        berth.name = body.name.strip()
    if body.pedestal_id is not None:
        berth.pedestal_id = body.pedestal_id if body.pedestal_id > 0 else None
    if body.berth_type is not None:
        if body.berth_type not in ("transit", "yearly"):
            raise HTTPException(status_code=422, detail="berth_type must be 'transit' or 'yearly'")
        berth.berth_type = body.berth_type
    user_db.commit()
    return {"ok": True}


@router.post("/api/admin/berths")
def create_berth(
    body: BerthConfigUpdate,
    user_db: DBSession = Depends(get_user_db),
    _admin=Depends(require_admin),
):
    """Create a new berth."""
    berth = Berth(
        name=(body.name or "New Berth").strip(),
        pedestal_id=body.pedestal_id if body.pedestal_id and body.pedestal_id > 0 else None,
        berth_type=body.berth_type or "transit",
        status="free",
        detected_status="free",
    )
    user_db.add(berth)
    user_db.commit()
    user_db.refresh(berth)
    return {"ok": True, "id": berth.id}


@router.delete("/api/admin/berths/{berth_id}")
def delete_berth(
    berth_id: int,
    user_db: DBSession = Depends(get_user_db),
    _admin=Depends(require_admin),
):
    """Delete a berth and its reservations."""
    berth = user_db.get(Berth, berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")
    user_db.query(BerthReservation).filter(BerthReservation.berth_id == berth_id).delete()
    user_db.delete(berth)
    user_db.commit()
    return {"ok": True}


@router.put("/api/admin/berths/{berth_id}/status")
def set_berth_status(
    berth_id: int,
    body: BerthStatusUpdate,
    user_db: DBSession = Depends(get_user_db),
    _admin=Depends(require_admin),
):
    valid = {"free", "occupied", "reserved"}
    if body.status not in valid:
        raise HTTPException(status_code=422, detail=f"status must be one of {valid}")
    berth = user_db.get(Berth, berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")
    berth.status = body.status
    user_db.commit()
    return {"ok": True}


# ─── Reference images (admin) ─────────────────────────────────────────────────

@router.get("/api/admin/berths/{berth_id}/reference-images")
def get_reference_images(
    berth_id: int,
    user_db: DBSession = Depends(get_user_db),
    _admin=Depends(require_admin),
):
    from ..services.berth_analyzer import list_reference_images
    berth = user_db.get(Berth, berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")
    return {"images": list_reference_images(berth_id)}


@router.post("/api/admin/berths/{berth_id}/reference-images")
async def upload_reference_images(
    berth_id: int,
    files: List[UploadFile] = File(...),
    user_db: DBSession = Depends(get_user_db),
    _admin=Depends(require_admin),
):
    from ..services.berth_analyzer import save_reference_image
    berth = user_db.get(Berth, berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")
    if not files:
        raise HTTPException(status_code=422, detail="No files provided")

    saved = []
    for f in files:
        data = await f.read()
        if not data:
            continue
        name = save_reference_image(berth_id, f.filename or "upload.jpg", data)
        saved.append(name)

    return {"saved": saved, "count": len(saved)}


@router.delete("/api/admin/berths/{berth_id}/reference-images/{filename}")
def delete_reference_image_endpoint(
    berth_id: int,
    filename: str,
    user_db: DBSession = Depends(get_user_db),
    _admin=Depends(require_admin),
):
    from ..services.berth_analyzer import delete_reference_image
    berth = user_db.get(Berth, berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")
    ok = delete_reference_image(berth_id, filename)
    if not ok:
        raise HTTPException(status_code=404, detail="Image not found")
    return {"ok": True}
