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


router = APIRouter(prefix="/api/mobile", tags=["mobile"])
logger = logging.getLogger(__name__)


QR_BASE_URL = "https://marina.lika.solutions/mobile/socket"

# Valid socket_id strings accepted by the QR endpoints. Q1–Q4 are the only
# physical electricity outlets in the current firmware; water valves are
# out of scope for mobile monitoring per v3.6 spec.
_VALID_SOCKETS = {"Q1", "Q2", "Q3", "Q4"}


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


def _socket_name_to_id(socket_id_str: str) -> int:
    """Map Q1-Q4 → 1-4. Raises 404 for anything else."""
    if socket_id_str not in _VALID_SOCKETS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Socket not found on this pedestal",
        )
    return int(socket_id_str.replace("Q", ""))


def _live_metrics(db: DBSession, session: SessionModel) -> dict:
    """Compute duration / latest kWh / latest power for a session from its
    SensorReading rows. Returns zeros when no readings are present yet."""
    readings = (
        db.query(SensorReading)
        .filter(SensorReading.session_id == session.id)
        .order_by(SensorReading.timestamp.desc())
        .limit(10)
        .all()
    )
    # Session-cumulative kWh — firmware sends monotonic values that reset per
    # session, so the most recent reading of type kwh_total is authoritative.
    latest_kwh = next((r.value for r in readings if r.type == "kwh_total"), 0.0)
    latest_power_w = next((r.value for r in readings if r.type == "power_watts"), 0.0)
    duration_s = int((datetime.utcnow() - session.started_at).total_seconds()) if session.started_at else 0
    return {
        "duration_seconds": duration_s,
        "energy_kwh": round(float(latest_kwh), 4),
        "power_kw": round(float(latest_power_w) / 1000.0, 3),
    }


def _active_session_for(db: DBSession, pedestal_db_id: int, socket_id: int) -> SessionModel | None:
    return (
        db.query(SessionModel)
        .filter(
            SessionModel.pedestal_id == pedestal_db_id,
            SessionModel.socket_id == socket_id,
            SessionModel.type == "electricity",
            SessionModel.status == "active",
        )
        .first()
    )


def _socket_state_str(db: DBSession, pedestal_db_id: int, socket_id: int) -> str:
    """Compute a simple idle|pending|active string for the mobile UI.

    Mirrors the logic the frontend Control Center uses but from the backend
    side so mobile clients do not need to subscribe to multiple WS events to
    know what to render on the landing screen.
    """
    if _active_session_for(db, pedestal_db_id, socket_id):
        return "active"
    from ..models.pedestal_config import SocketState
    row = (
        db.query(SocketState)
        .filter(SocketState.pedestal_id == pedestal_db_id, SocketState.socket_id == socket_id)
        .first()
    )
    if row and row.connected:
        return "pending"
    return "idle"


# ─── Request / response shapes ───────────────────────────────────────────────

class QrClaimBody(BaseModel):
    pedestal_id: str = Field(..., description="opta_client_id string or numeric id")
    socket_id: str = Field(..., description="Q1–Q4")


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

    socket_int_id = _socket_name_to_id(body.socket_id)

    # Step 4 (marina access control) intentionally skipped per v3.6 decision —
    # any authenticated customer may monitor any socket. See docs/mobile_api.md.

    active = _active_session_for(db, pedestal_db_id, socket_int_id)
    socket_state = _socket_state_str(db, pedestal_db_id, socket_int_id)

    if active is None:
        # No session yet. Mobile shows the "No session view" — user plugs in,
        # auto-activation fires (if configured) or manual Activate button is
        # shown while auto-activate is off.
        return {
            "status": "no_session",
            "pedestal_id": body.pedestal_id,
            "socket_id": body.socket_id,
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
        "socket_state": socket_state,
        "session_started_at": active.started_at.isoformat() if active.started_at else None,
        "duration_seconds": metrics["duration_seconds"],
        "energy_kwh": metrics["energy_kwh"],
        "power_kw": metrics["power_kw"],
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
    return {
        "session_id": session.id,
        "socket_state": _socket_state_str(db, session.pedestal_id, session.socket_id or 0),
        "duration_seconds": metrics["duration_seconds"],
        "energy_kwh": metrics["energy_kwh"],
        "power_kw": metrics["power_kw"],
        "last_updated_at": datetime.utcnow().isoformat(),
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
    if socket_id not in _VALID_SOCKETS:
        raise HTTPException(status_code=404, detail="Socket not found on this pedestal")

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
