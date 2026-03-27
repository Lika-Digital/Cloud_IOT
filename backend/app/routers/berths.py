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
    # Camera info (from pedestal_config)
    camera_stream_url: Optional[str] = None
    camera_reachable: bool = False
    # Reference images
    reference_image_count: int = 0

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


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _berth_to_out(b: Berth, pedestal_cfg=None, ref_count: int = 0) -> BerthOut:
    return BerthOut(
        id=b.id,
        name=b.name,
        pedestal_id=b.pedestal_id,
        status=b.status,
        detected_status=b.detected_status,
        last_analyzed=b.last_analyzed.isoformat() if b.last_analyzed else None,
        occupied_bit=b.occupied_bit or 0,
        match_ok_bit=b.match_ok_bit or 0,
        state_code=b.state_code or 0,
        alarm=b.alarm or 0,
        match_score=b.match_score,
        analysis_error=b.analysis_error,
        camera_stream_url=pedestal_cfg.camera_stream_url if pedestal_cfg else None,
        camera_reachable=bool(pedestal_cfg.camera_reachable) if pedestal_cfg else False,
        reference_image_count=ref_count,
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
    from ..services.berth_analyzer import list_reference_images
    berths = user_db.query(Berth).order_by(Berth.id).all()
    cfg_map = _get_pedestal_cfg_map(db)
    return [
        _berth_to_out(b, cfg_map.get(b.pedestal_id), len(list_reference_images(b.id)))
        for b in berths
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
      1. Grab a live snapshot from the pedestal camera via ffmpeg.
      2. Detect ship presence using edge-density (Laplacian variance).
      3. Compare with uploaded reference images using histogram similarity.
      4. Persist result and broadcast via WebSocket.
    """
    from ..models.pedestal_config import PedestalConfig
    from ..services.berth_analyzer import (
        analyze_berth_now, list_reference_images,
    )
    from ..services.websocket_manager import ws_manager

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

    res = await analyze_berth_now(
        berth_id=berth_id,
        stream_url=cfg.camera_stream_url,
        camera_username=cfg.camera_username or "",
        camera_password=cfg.camera_password or "",
        # detect_conf_threshold repurposed as Laplacian variance threshold (default 300)
        detect_threshold=berth.detect_conf_threshold or 300.0,
        match_threshold=berth.match_threshold or 0.75,
    )

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
        detected_label = f"⚠ Unknown ship detected (score {b.match_score:.2f})"

    return {"ok": True, "detected_status": detected_label, **res}


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
