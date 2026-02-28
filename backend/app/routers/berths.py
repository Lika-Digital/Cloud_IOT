"""
Berth occupancy and reservation endpoints.

Public / customer routes:
  GET  /api/berths                        → list all berths (status)
  GET  /api/berths/availability           → check free berths for a date range
  POST /api/customer/berths/reserve       → create a reservation
  GET  /api/customer/berths/mine          → customer's own reservations
  DELETE /api/customer/berths/reservations/{id}  → cancel a reservation

Admin routes:
  GET  /api/admin/berths/calendar/{berth_id}  → calendar entries for a berth
  POST /api/admin/berths/{id}/analyze         → trigger manual analysis
  PUT  /api/admin/berths/{id}/status          → manually set berth status
"""
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from ..auth.user_database import get_user_db
from ..auth.berth_models import Berth, BerthReservation
from ..auth.customer_models import Customer
from ..auth.dependencies import require_admin
from ..auth.customer_dependencies import require_customer

router = APIRouter(tags=["berths"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class BerthOut(BaseModel):
    id: int
    name: str
    pedestal_id: Optional[int]
    status: str
    detected_status: str
    video_source: Optional[str]
    background_image: Optional[str] = None
    last_analyzed: Optional[str]
    # ML pipeline outputs
    occupied_bit: int = 0
    match_ok_bit: int = 0
    state_code: int = 0       # 0=FREE 1=OCCUPIED_CORRECT 2=OCCUPIED_WRONG
    alarm: int = 0
    match_score: Optional[float] = None
    analysis_error: Optional[str] = None
    # Zone-based detection config
    use_detection_zone: int = 1
    zone_x1: float = 0.20
    zone_y1: float = 0.20
    zone_x2: float = 0.80
    zone_y2: float = 0.80

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

def _berth_to_out(b: Berth) -> BerthOut:
    return BerthOut(
        id=b.id,
        name=b.name,
        pedestal_id=b.pedestal_id,
        status=b.status,
        detected_status=b.detected_status,
        video_source=b.video_source,
        background_image=b.background_image,
        last_analyzed=b.last_analyzed.isoformat() if b.last_analyzed else None,
        occupied_bit=b.occupied_bit or 0,
        match_ok_bit=b.match_ok_bit or 0,
        state_code=b.state_code or 0,
        alarm=b.alarm or 0,
        match_score=b.match_score,
        analysis_error=b.analysis_error,
        use_detection_zone=b.use_detection_zone or 0,
        zone_x1=b.zone_x1 if b.zone_x1 is not None else 0.20,
        zone_y1=b.zone_y1 if b.zone_y1 is not None else 0.20,
        zone_x2=b.zone_x2 if b.zone_x2 is not None else 0.80,
        zone_y2=b.zone_y2 if b.zone_y2 is not None else 0.80,
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


def _dates_overlap(ci1: date, co1: date, ci2: date, co2: date) -> bool:
    """True if [ci1, co1) overlaps [ci2, co2)."""
    return ci1 < co2 and ci2 < co1


# ─── Public routes ────────────────────────────────────────────────────────────

@router.get("/api/berths", response_model=List[BerthOut])
def list_berths(user_db: DBSession = Depends(get_user_db)):
    berths = user_db.query(Berth).order_by(Berth.id).all()
    return [_berth_to_out(b) for b in berths]


@router.get("/api/berths/availability", response_model=List[BerthOut])
def get_availability(
    check_in: str,
    check_out: str,
    user_db: DBSession = Depends(get_user_db),
):
    ci = _parse_date(check_in)
    co = _parse_date(check_out)
    if co <= ci:
        raise HTTPException(status_code=422, detail="check_out must be after check_in")

    berths = user_db.query(Berth).order_by(Berth.id).all()
    free_berths = []
    for b in berths:
        # Check for any overlapping confirmed reservation
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
            free_berths.append(_berth_to_out(b))
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

    # Conflict check
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

    # Mark berth as reserved if check-in is today or earlier
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
    # Batch-load all berths to avoid N+1 queries
    berth_map = {b.id: b for b in user_db.query(Berth).all()}
    result = []
    for r in rows:
        b = berth_map.get(r.berth_id)
        result.append(_reservation_to_out(r, b.name if b else "Unknown"))
    return result


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
    _admin=Depends(require_admin),
):
    """Trigger an immediate ML analysis for a single berth via the ML Worker."""
    import httpx
    from ..services.berth_analyzer import ML_WORKER_URL, ML_TIMEOUT_SECONDS
    from ..services.websocket_manager import ws_manager

    berth = user_db.get(Berth, berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")

    payload = {
        "video_source":          berth.video_source,
        "reference_image":       berth.reference_image,
        "background_image":      berth.background_image,
        "detect_conf_threshold": berth.detect_conf_threshold or 0.30,
        "match_threshold":       berth.match_threshold or 0.50,
        "use_detection_zone":    bool(berth.use_detection_zone),
        "zone_x1":               berth.zone_x1 if berth.zone_x1 is not None else 0.20,
        "zone_y1":               berth.zone_y1 if berth.zone_y1 is not None else 0.20,
        "zone_x2":               berth.zone_x2 if berth.zone_x2 is not None else 0.80,
        "zone_y2":               berth.zone_y2 if berth.zone_y2 is not None else 0.80,
    }

    res: dict = {}
    try:
        async with httpx.AsyncClient(timeout=ML_TIMEOUT_SECONDS) as client:
            r = await client.post(f"{ML_WORKER_URL}/analyze/berth", json=payload)
            r.raise_for_status()
            res = r.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ML Worker error: {exc}")

    # Persist
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

    await ws_manager.broadcast({
        "event": "berth_occupancy_updated",
        "data": {"berths": [_berth_to_out(b).model_dump()]},
    })
    return res


@router.post("/api/admin/berths/{berth_id}/capture-background")
async def capture_background(
    berth_id: int,
    user_db: DBSession = Depends(get_user_db),
    _admin=Depends(require_admin),
):
    """
    Extract a middle frame from the berth's video source and save it as the
    background reference image used by the ML pre-screening step.
    Sets berth.background_image in the DB automatically.
    """
    import httpx
    from ..services.berth_analyzer import ML_WORKER_URL, ML_TIMEOUT_SECONDS

    berth = user_db.get(Berth, berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")
    if not berth.video_source:
        raise HTTPException(status_code=400, detail="Berth has no video source configured")

    output_name = f"bg_berth_{berth_id}.jpg"
    try:
        async with httpx.AsyncClient(timeout=ML_TIMEOUT_SECONDS) as client:
            r = await client.post(
                f"{ML_WORKER_URL}/capture/background",
                json={"video_source": berth.video_source, "output_name": output_name},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ML Worker error: {exc}")

    berth.background_image = output_name
    user_db.commit()
    return {"background_image": output_name, "width": data.get("width"), "height": data.get("height")}


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
