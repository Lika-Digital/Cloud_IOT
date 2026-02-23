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
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from ..auth.user_database import get_user_db
from ..auth.berth_models import Berth, BerthReservation
from ..auth.customer_models import Customer
from ..auth.dependencies import require_admin
from ..routers.customer_auth import require_customer

router = APIRouter(tags=["berths"])


# ─── Schemas ──────────────────────────────────────────────────────────────────

class BerthOut(BaseModel):
    id: int
    name: str
    pedestal_id: Optional[int]
    status: str
    detected_status: str
    video_source: Optional[str]
    last_analyzed: Optional[str]

    class Config:
        from_attributes = True


class ReservationIn(BaseModel):
    berth_id: int
    check_in_date: str   # YYYY-MM-DD
    check_out_date: str  # YYYY-MM-DD
    notes: Optional[str] = None


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
        last_analyzed=b.last_analyzed.isoformat() if b.last_analyzed else None,
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
    result = []
    for r in rows:
        b = user_db.get(Berth, r.berth_id)
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
    from ..services.berth_analyzer import _detect_from_filename
    from ..services.websocket_manager import ws_manager

    berth = user_db.get(Berth, berth_id)
    if not berth:
        raise HTTPException(status_code=404, detail="Berth not found")

    detected = _detect_from_filename(berth.video_source)
    berth.detected_status = detected
    berth.last_analyzed = datetime.utcnow()
    if berth.status != "reserved":
        berth.status = detected
    user_db.commit()
    user_db.refresh(berth)

    await ws_manager.broadcast({
        "event": "berth_occupancy_updated",
        "data": {
            "berths": [{
                "id": berth.id,
                "name": berth.name,
                "status": berth.status,
                "detected_status": berth.detected_status,
                "pedestal_id": berth.pedestal_id,
                "video_source": berth.video_source,
                "last_analyzed": berth.last_analyzed.isoformat(),
            }]
        },
    })
    return {"ok": True, "detected_status": detected}


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
