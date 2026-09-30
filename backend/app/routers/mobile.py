"""Mobile QR-code + real-time monitoring endpoints (v3.6).

Customer scans the QR printed on a socket → mobile app opens this API with
the scanned `pedestal_id` / `socket_id`. The backend claims the existing
active session for that customer (if any) and returns a short-lived
`websocket_token` the app uses to subscribe to per-session telemetry on /ws.

Authority model (confirmed 2026-04-21):
  - Mobile app is monitoring only. No stop endpoint lives here.
  - Admin role overrides everything from the dashboard via existing controls.
  - Marina access control deliberately skipped — any authenticated customer
    can claim any socket's live data (prepaid walk-up model).
"""
from __future__ import annotations

import io
import logging
from datetime import datetime

import qrcode
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models.pedestal import Pedestal
from ..models.pedestal_config import PedestalConfig
from ..models.session import Session as SessionModel
from ..models.sensor_reading import SensorReading
from ..auth.customer_models import Customer
from ..auth.customer_dependencies import require_customer
from ..auth.dependencies import require_admin
from ..auth.tokens import create_websocket_token
from ..time_utils import now_iso, iso_z
# v3.43 — the outlet vocabulary is imported, not restated. A second copy of the outlet list
# is how the QR path came to disagree with the NFC path in the first place.
from ..services.nfc_service import (
    OUTLET_SOCKET, OUTLET_VALVE, VALID_OUTLETS,
    WaterTagBlockedByAppVersion, assert_valve_provisioning_allowed,
    outlet_type_for, session_type_for,
)


router = APIRouter(prefix="/api/mobile", tags=["mobile"])
logger = logging.getLogger(__name__)


QR_BASE_URL = "https://marina.lika.solutions/mobile/socket"

# v3.43 — QR ADDRESSES THE SAME SIX OUTLETS AS NFC.
#
# This was `{"Q1".."Q4"}` with the comment "water valves are out of scope for mobile
# monitoring per v3.6 spec". That was a real decision, but it predates the six-tag model,
# and it left a difference nobody can explain to a customer standing at a water outlet
# with no code on it: six outlets reachable by NFC, four by QR.
#
# A printed code on a water outlet is gated on the same app-version flag as an NFC water
# tag — see assert_valve_provisioning_allowed, and the reason at socket_qr_image.
_ALL_OUTLETS = tuple(n for names in VALID_OUTLETS.values() for n in names)

# How old a stored valve state may be and still be reported as current. Four heartbeat
# intervals (opta/status is 15 s), the same slack the comm-loss watchdog allows before it
# calls a cabinet silent. Past this, `_outlet_state_str` answers "unknown" rather than
# repeating the last thing the valve said before its cabinet stopped talking.
VALVE_STATE_MAX_AGE_S = 60


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _resolve_pedestal_db_id(db: DBSession, pedestal_id: str) -> int | None:
    """Accept either a numeric primary-key string or an `opta_client_id`
    (e.g. 'MAR_KRK_ORM_01'). Returns the integer DB id or None if not found.
    Mirrors `ext_pedestal_endpoints._resolve_pedestal` but operates on the
    caller's DB session so we stay inside one transaction."""
    if pedestal_id.isdigit():
        if db.get(Pedestal, int(pedestal_id)):
            return int(pedestal_id)
    cfg = db.query(PedestalConfig).filter(PedestalConfig.opta_client_id == pedestal_id).first()
    return cfg.pedestal_id if cfg else None


def _outlet_name_to_kind_and_id(outlet_name: str) -> tuple[str, int]:
    """Map Q1-Q4 / V1-V2 → (kind, 1-4). Raises 404 for anything else.

    Returns the KIND alongside the number because the numbers overlap: V1 and Q1 are both
    outlet 1, separated only by the session type. Every caller below needs both, and
    deciding the kind twice is how two halves of one request come to disagree.
    """
    kind = outlet_type_for(outlet_name)
    if kind is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Outlet not found on this pedestal",
        )
    return kind, int(outlet_name[1:])


def _socket_name_to_id(socket_id_str: str) -> int:
    """Electricity-only helper kept for the callers that are genuinely socket-specific."""
    kind, num = _outlet_name_to_kind_and_id(socket_id_str)
    if kind != OUTLET_SOCKET:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Socket not found on this pedestal",
        )
    return num


def _live_metrics(db: DBSession, session: SessionModel) -> dict:
    """Duration plus the live figures for whichever kind of session this is.

    v3.43 — a water session reaches this now, and the electricity keys are no longer
    filled in for one. `kwh_total` and `power_watts` are simply never written for a water
    session, so the old `next(..., 0.0)` defaults returned a confident 0.0000 kWh / 0 kW
    for a tank being filled. Those keys are None for water — not 0.0, which reads as a
    measurement of nothing rather than the absence of that quantity.

    Both key sets are always present so a client never has to branch on their existence,
    only on their value.
    """
    readings = (
        db.query(SensorReading)
        .filter(SensorReading.session_id == session.id)
        .order_by(SensorReading.timestamp.desc())
        .limit(10)
        .all()
    )
    duration_s = int((datetime.utcnow() - session.started_at).total_seconds()) if session.started_at else 0
    is_water = getattr(session, "type", None) == "water"

    def latest(kind: str):
        return next((r.value for r in readings if r.type == kind), None)

    if is_water:
        liters = latest("total_liters")
        lpm = latest("water_lpm")
        return {
            "duration_seconds": duration_s,
            "energy_kwh": None,
            "power_kw": None,
            "water_liters": round(float(liters), 3) if liters is not None else 0.0,
            "flow_lpm": round(float(lpm), 2) if lpm is not None else 0.0,
        }

    # Session-cumulative kWh — firmware sends monotonic values that reset per
    # session, so the most recent reading of type kwh_total is authoritative.
    latest_kwh = latest("kwh_total")
    latest_power_w = latest("power_watts")
    return {
        "duration_seconds": duration_s,
        "energy_kwh": round(float(latest_kwh), 4) if latest_kwh is not None else 0.0,
        "power_kw": round(float(latest_power_w) / 1000.0, 3) if latest_power_w is not None else 0.0,
        "water_liters": None,
        "flow_lpm": None,
    }


def _active_session_for(db: DBSession, pedestal_db_id: int, outlet_id: int,
                        session_type: str = "electricity") -> SessionModel | None:
    """The active session on one outlet, of one kind.

    The type filter is not optional. V1 and Q1 are both `socket_id=1`, so without it a QR
    scan at a water outlet would return the electricity session on socket 1 — and
    `qr_claim` would offer to claim it, putting a neighbour's charge under this customer.
    """
    return (
        db.query(SessionModel)
        .filter(
            SessionModel.pedestal_id == pedestal_db_id,
            SessionModel.socket_id == outlet_id,
            SessionModel.type == session_type,
            SessionModel.status == "active",
        )
        .first()
    )


def _outlet_state_str(db: DBSession, pedestal_db_id: int, outlet_id: int,
                      kind: str = OUTLET_SOCKET) -> str:
    """A simple idle|pending|active|unknown string for the mobile UI.

    Mirrors the logic the frontend Control Center uses but from the backend
    side so mobile clients do not need to subscribe to multiple WS events to
    know what to render on the landing screen.

    v3.43 — a valve reads its OWN state, never the socket table.

    `socket_states` is keyed by number alone, so consulting it for a valve returned the
    electricity socket of the same number: "cable detected" on a tap, or "idle" while water
    ran. The valve's real state comes from `opta/water/V{n}/status`, which carries `state` and
    `hw_status` and is now persisted on `valve_configs`.

    Two valve-specific answers:

      * **"unknown"** when the stored state is missing or STALE. A stored value is only as
        good as its age; a valve whose cabinet went silent three days ago must not report
        "idle" as if it were current (rule 1 — a predicate a replay can satisfy is not a
        liveness check). Clients render it as "—".
      * **no "pending"**. Pending means "physically connected, awaiting activation", and that
        comes from the socket's plug-in detection. The firmware has no valve analogue — there
        is no "hose connected" signal — so the state genuinely does not exist rather than
        being unread.
    """
    session_type = session_type_for(kind)
    if _active_session_for(db, pedestal_db_id, outlet_id, session_type):
        return "active"
    if kind == OUTLET_VALVE:
        from ..models.valve_config import ValveConfig
        vc = (
            db.query(ValveConfig)
            .filter(ValveConfig.pedestal_id == pedestal_db_id,
                    ValveConfig.valve_id == outlet_id)
            .first()
        )
        if vc is None or not vc.last_state or vc.state_updated_at is None:
            return "unknown"
        age_s = (datetime.utcnow() - vc.state_updated_at).total_seconds()
        if age_s > VALVE_STATE_MAX_AGE_S:
            return "unknown"
        # The firmware's own vocabulary, passed through rather than re-mapped. "active" is
        # already handled above from our session rows; anything else it reports is its word.
        return vc.last_state
    from ..models.pedestal_config import SocketState
    row = (
        db.query(SocketState)
        .filter(SocketState.pedestal_id == pedestal_db_id, SocketState.socket_id == outlet_id)
        .first()
    )
    if row and row.connected:
        return "pending"
    return "idle"


def _socket_state_str(db: DBSession, pedestal_db_id: int, socket_id: int) -> str:
    """Back-compatible electricity-only wrapper."""
    return _outlet_state_str(db, pedestal_db_id, socket_id, OUTLET_SOCKET)


# ─── Request / response shapes ───────────────────────────────────────────────

class QrClaimBody(BaseModel):
    pedestal_id: str = Field(..., description="opta_client_id string or numeric id")
    # The outlet printed on the code. v3.43: V1/V2 are accepted alongside Q1-Q4, so a
    # water outlet can carry a printed code like every other outlet.
    socket_id: str = Field(..., description="Q1-Q4 (electricity) or V1-V2 (water)")


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/qr/claim")
def qr_claim(
    body: QrClaimBody,
    db: DBSession = Depends(get_db),
    customer: Customer = Depends(require_customer),
):
    """Primary QR scan entry point. Returns the session view the mobile app
    should render (claimed / already_owner / read_only / no_session) plus a
    1h `websocket_token` for per-session live telemetry."""

    pedestal_db_id = _resolve_pedestal_db_id(db, body.pedestal_id)
    if pedestal_db_id is None:
        raise HTTPException(status_code=404, detail="Pedestal not found")

    outlet_kind, outlet_int_id = _outlet_name_to_kind_and_id(body.socket_id)
    session_type = session_type_for(outlet_kind)
    # Kept under the old name for the response and the log lines, which have always used it.
    socket_int_id = outlet_int_id

    # Step 4 (marina access control) intentionally skipped per v3.6 decision —
    # any authenticated customer may monitor any socket. See docs/mobile_api.md.

    active = _active_session_for(db, pedestal_db_id, outlet_int_id, session_type)
    socket_state = _outlet_state_str(db, pedestal_db_id, outlet_int_id, outlet_kind)

    if active is None:
        # No session yet. Mobile shows the "No session view" — user plugs in,
        # auto-activation fires (if configured) or manual Activate button is
        # shown while auto-activate is off.
        return {
            "status": "no_session",
            "pedestal_id": body.pedestal_id,
            "socket_id": body.socket_id,
            "outlet_type": outlet_kind,
            "session_type": session_type,
            "socket_state": socket_state,
        }

    # Session exists — decide ownership branch.
    if active.customer_id is None:
        # Unowned auto-activated session → claim it for this customer.
        active.customer_id = customer.id
        active.owner_claimed_at = datetime.utcnow()
        db.commit()
        db.refresh(active)
        logger.info(
            "[QRClaim] session %d claimed by customer %d (pedestal=%s socket=%s)",
            active.id, customer.id, body.pedestal_id, body.socket_id,
        )
        claim_status = "claimed"
        is_owner = True
    elif active.customer_id == customer.id:
        claim_status = "already_owner"
        is_owner = True
    else:
        claim_status = "read_only"
        is_owner = False

    metrics = _live_metrics(db, active)
    ws_token = create_websocket_token(active.id, customer.id)

    return {
        "status": claim_status,
        "session_id": active.id,
        "pedestal_id": body.pedestal_id,
        "socket_id": body.socket_id,
        "outlet_type": outlet_kind,
        "session_type": session_type,
        "socket_state": socket_state,
        "session_started_at": iso_z(active.started_at),
        "duration_seconds": metrics["duration_seconds"],
        # Exactly one pair carries figures; the other is null. Never 0.0 for a quantity
        # this outlet does not measure.
        "energy_kwh": metrics["energy_kwh"],
        "power_kw": metrics["power_kw"],
        "water_liters": metrics["water_liters"],
        "flow_lpm": metrics["flow_lpm"],
        "is_owner": is_owner,
        "websocket_token": ws_token,
    }


@router.get("/sessions/{session_id}/live")
def session_live(
    session_id: int,
    db: DBSession = Depends(get_db),
    customer: Customer = Depends(require_customer),
):
    """Polling fallback for mobile clients that can't maintain a WebSocket.

    The customer must own the session (matching `customer_id`); if they don't,
    return 403 — mobile clients are monitoring only and we don't leak live
    data across customers.
    """
    session = db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.customer_id != customer.id:
        raise HTTPException(status_code=403, detail="You are not the owner of this session")

    metrics = _live_metrics(db, session)
    # v3.43 — the outlet kind comes from the session, not assumed. `_socket_state_str` reads
    # `socket_states`, which is keyed by number alone, so for a water session it was returning
    # the plug-in state of the ELECTRICITY socket with the same number: "cable detected" on a
    # tap, or "idle" while water ran.
    outlet_kind = OUTLET_VALVE if getattr(session, "type", None) == "water" else OUTLET_SOCKET
    return {
        "session_id": session.id,
        "socket_state": _outlet_state_str(db, session.pedestal_id, session.socket_id or 0,
                                          outlet_kind),
        "session_type": "water" if outlet_kind == OUTLET_VALVE else "electricity",
        "duration_seconds": metrics["duration_seconds"],
        "energy_kwh": metrics["energy_kwh"],
        "power_kw": metrics["power_kw"],
        "water_liters": metrics["water_liters"],
        "flow_lpm": metrics["flow_lpm"],
        "last_updated_at": now_iso(),
    }


@router.get("/socket/{pedestal_id}/{socket_id}/qr", responses={200: {"content": {"image/png": {}}}})
def socket_qr_image(
    pedestal_id: str,
    socket_id: str,
    db: DBSession = Depends(get_db),
    _: object = Depends(require_admin),
):
    """Generate and return a PNG QR code pointing at the mobile landing URL.

    Admin-only — operators download QR codes to print on physical socket
    labels. The QR URL format is static and matches what the mobile app
    expects at `/mobile/socket/{pedestal_id}/{socket_id}`.
    """
    if _resolve_pedestal_db_id(db, pedestal_id) is None:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    kind, _num = _outlet_name_to_kind_and_id(socket_id)
    if kind == OUTLET_VALVE:
        # Same app-version gate as an NFC water tag, and for a stronger reason: a printed
        # sticker outlives the deploy that produced it. Generating one now for a site whose
        # app cannot read a water outlet puts a permanent artefact on the pontoon.
        try:
            assert_valve_provisioning_allowed()
        except WaterTagBlockedByAppVersion as e:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))

    url = f"{QR_BASE_URL}/{pedestal_id}/{socket_id}"
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={
            "Content-Disposition": f'inline; filename="{pedestal_id}_{socket_id}_qr.png"',
            "X-QR-URL": url,
            "Cache-Control": "public, max-age=86400",
        },
    )
