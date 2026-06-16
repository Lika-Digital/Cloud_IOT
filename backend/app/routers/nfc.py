"""NFC provisioning + ERP integration endpoints (v3.26).

Two audiences:
  * Operator/admin (JWT, require_admin): provision/remove/list NFC tags per socket.
  * ERP / myMarina (X-API-Key, require_erp_api_key): /scan pre-registration,
    /session read + remote stop.

Critical architecture notes (per spec):
  * /scan does NOT activate the socket. It only pre-registers intent. Activation
    happens when the Opta reports UserPluggedIn over MQTT (see mqtt_handlers).
  * The operator always retains highest-priority control: the existing operator
    stop flow is unchanged and works for NFC sessions identically.
"""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..auth.user_database import get_user_db
from ..auth.dependencies import require_admin
from ..auth.erp_api_key import require_erp_api_key
from ..auth.models import User
from ..models.session import Session
from ..models.pedestal_config import PedestalConfig
from ..services.session_service import session_service
from ..services import nfc_service
from ..services.nfc_service import DuplicateNfcTagError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nfc", tags=["nfc"])

_VALID_SOCKETS = {"Q1", "Q2", "Q3", "Q4"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_pedestal(db: DBSession, cabinet_id: str) -> Optional[PedestalConfig]:
    """Lookup PedestalConfig by opta_client_id. Does NOT auto-create."""
    return db.query(PedestalConfig).filter(
        PedestalConfig.opta_client_id == cabinet_id
    ).first()


def _socket_str_to_id(socket_id: str) -> int:
    from ..services.mqtt_handlers import _socket_name_to_id
    return _socket_name_to_id(socket_id)


def _socket_display_state(db: DBSession, pedestal_id: int, socket_id: int) -> str:
    from ..services.mqtt_handlers import _compute_socket_display_state
    return _compute_socket_display_state(db, pedestal_id, socket_id, raw_state="", hw_status="")


# ── Pydantic bodies ───────────────────────────────────────────────────────────

class NfcScanBody(BaseModel):
    nfc_tag_id: str = Field(..., min_length=1, max_length=256)
    user_id: str = Field(..., min_length=1, max_length=128)


class NfcProvisionBody(BaseModel):
    cabinet_id: str = Field(..., min_length=1)
    socket_id: str = Field(..., min_length=2, max_length=2)   # "Q1".."Q4"
    nfc_tag_id: str = Field(..., min_length=1, max_length=256)


class NfcBulkItem(BaseModel):
    socket_id: str = Field(..., min_length=2, max_length=2)
    nfc_tag_id: str = Field(..., min_length=1, max_length=256)


class NfcBulkBody(BaseModel):
    cabinet_id: str = Field(..., min_length=1)
    items: List[NfcBulkItem]


class NfcModeBody(BaseModel):
    mode: str = Field(..., pattern="^(qr|nfc)$")


# ── Provisioning mode (admin) ─────────────────────────────────────────────────

@router.get("/mode/{cabinet_id}")
def get_provisioning_mode(cabinet_id: str, db: DBSession = Depends(get_db),
                          _: User = Depends(require_admin)):
    cfg = _resolve_pedestal(db, cabinet_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Pedestal not found")
    return {"cabinet_id": cabinet_id, "provisioning_mode": cfg.provisioning_mode or "qr"}


@router.patch("/mode/{cabinet_id}")
def set_provisioning_mode(cabinet_id: str, body: NfcModeBody,
                          db: DBSession = Depends(get_db),
                          _: User = Depends(require_admin)):
    """Switch the cabinet's provisioning mode. Switching to NFC disables
    auto_activate on ALL the cabinet's sockets (explicit activation required);
    switching back to QR restores auto_activate=True on all of them."""
    cfg = _resolve_pedestal(db, cabinet_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Pedestal not found")

    cfg.provisioning_mode = body.mode
    auto = body.mode == "qr"   # qr → auto_activate True; nfc → False

    from ..models.socket_config import SocketConfig
    rows = db.query(SocketConfig).filter(
        SocketConfig.pedestal_id == cfg.pedestal_id
    ).all()
    for r in rows:
        r.auto_activate = auto
    db.commit()

    return {
        "cabinet_id": cabinet_id,
        "provisioning_mode": body.mode,
        "auto_activate": auto,
        "sockets_updated": len(rows),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Admin provisioning (JWT, require_admin)
# ══════════════════════════════════════════════════════════════════════════════

def _tag_out(tag) -> dict:
    return {
        "nfc_tag_id": tag.nfc_tag_id,
        "cabinet_id": tag.cabinet_id,
        "socket_id": tag.socket_id,
        "provisioned_at": tag.provisioned_at.isoformat() if tag.provisioned_at else None,
        "provisioned_by": tag.provisioned_by,
        "is_active": tag.is_active,
    }


@router.get("/tags/{cabinet_id}")
def list_nfc_tags(cabinet_id: str, db: DBSession = Depends(get_db),
                  _: User = Depends(require_admin)):
    """Active NFC tag mappings for a cabinet (summary of the configuration)."""
    return [_tag_out(t) for t in nfc_service.list_tags(db, cabinet_id)]


def _provision_one(db, cabinet_id: str, socket_id: str, nfc_tag_id: str, by: str):
    if socket_id not in _VALID_SOCKETS:
        raise HTTPException(status_code=400, detail="socket_id must be one of Q1..Q4")
    try:
        return nfc_service.provision_tag(db, nfc_tag_id, cabinet_id, socket_id, provisioned_by=by)
    except DuplicateNfcTagError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"NFC tag already provisioned to cabinet {e.cabinet_id} socket {e.socket_id}",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/tags")
def provision_nfc_tag(body: NfcProvisionBody, db: DBSession = Depends(get_db),
                      admin: User = Depends(require_admin)):
    """Provision (or replace) the NFC tag for one socket."""
    tag = _provision_one(db, body.cabinet_id, body.socket_id, body.nfc_tag_id, admin.email)
    return _tag_out(tag)


@router.post("/tags/bulk")
def provision_nfc_tags_bulk(body: NfcBulkBody, db: DBSession = Depends(get_db),
                            admin: User = Depends(require_admin)):
    """Save All — provision multiple sockets at once. Validated per item; a
    duplicate/invalid item aborts the whole batch (nothing committed past the
    failing item is left half-applied because each provision commits, so we
    pre-validate duplicates across the batch first)."""
    # Pre-validate: reject in-batch duplicate tag ids and bad socket ids.
    seen: dict[str, str] = {}
    for it in body.items:
        if it.socket_id not in _VALID_SOCKETS:
            raise HTTPException(status_code=400, detail=f"socket_id must be one of Q1..Q4 (got {it.socket_id})")
        if it.nfc_tag_id in seen and seen[it.nfc_tag_id] != it.socket_id:
            raise HTTPException(
                status_code=409,
                detail=f"NFC tag {it.nfc_tag_id} assigned to two sockets in the same request",
            )
        seen[it.nfc_tag_id] = it.socket_id
    out = []
    for it in body.items:
        out.append(_tag_out(_provision_one(db, body.cabinet_id, it.socket_id, it.nfc_tag_id, admin.email)))
    return {"cabinet_id": body.cabinet_id, "tags": out}


@router.delete("/tags/{cabinet_id}/{socket_id}")
def remove_nfc_tag(cabinet_id: str, socket_id: str, db: DBSession = Depends(get_db),
                   _: User = Depends(require_admin)):
    """Clear the NFC tag mapping for a socket (is_active=False)."""
    if socket_id not in _VALID_SOCKETS:
        raise HTTPException(status_code=400, detail="socket_id must be one of Q1..Q4")
    cleared = nfc_service.remove_tag(db, cabinet_id, socket_id)
    if not cleared:
        raise HTTPException(status_code=404, detail="No active NFC tag for this socket")
    return {"cabinet_id": cabinet_id, "socket_id": socket_id, "removed": True}


# ══════════════════════════════════════════════════════════════════════════════
# ERP integration (X-API-Key, require_erp_api_key)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/scan")
def nfc_scan(body: NfcScanBody, db: DBSession = Depends(get_db),
             _: str = Depends(require_erp_api_key)):
    """Pre-register a marina customer's intent to use a socket (NFC tag scanned
    in myMarina). Does NOT activate the socket — activation happens on plug-in."""
    tag = nfc_service.get_active_tag_by_id(db, body.nfc_tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="NFC tag not provisioned")

    cabinet_id, socket_id = tag.cabinet_id, tag.socket_id
    cfg = _resolve_pedestal(db, cabinet_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="NFC tag not provisioned")

    socket_int = _socket_str_to_id(socket_id)

    # Socket availability.
    if _socket_display_state(db, cfg.pedestal_id, socket_int) == "fault":
        raise HTTPException(status_code=503, detail="Socket unavailable")
    active = session_service.get_active_for_socket(db, cfg.pedestal_id, socket_int, session_type="electricity")
    if active is not None and active.status == "active":
        raise HTTPException(status_code=409, detail="Socket already in use")

    # A still-valid pending scan for this socket blocks a second one.
    live = nfc_service.get_live_pending(db, cabinet_id, socket_id)
    if live is not None:
        raise HTTPException(status_code=409, detail="Socket already in use")

    rec = nfc_service.create_pending(db, body.nfc_tag_id, body.user_id, cabinet_id, socket_id)
    logger.info("[NFC] scan pre-registered user=%s cabinet=%s socket=%s expires=%s",
                body.user_id, cabinet_id, socket_id, rec.expires_at.isoformat())

    return {
        "status": "pending",
        "message": "Please plug in your charger to activate the socket",
        "cabinet_id": cabinet_id,
        "socket_id": socket_id,
        "berth_id": getattr(cfg, "berth_ref", None),
        "expires_at": rec.expires_at.isoformat(),
    }


@router.get("/session/{session_id}")
def nfc_session_status(session_id: int, db: DBSession = Depends(get_db),
                       user_db: DBSession = Depends(get_user_db),
                       _: str = Depends(require_erp_api_key)):
    """Current session status + spending data for the ERP to poll."""
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return nfc_service.build_session_payload(db, user_db, session)


@router.post("/session/{session_id}/stop")
async def nfc_session_stop(session_id: int, db: DBSession = Depends(get_db),
                           user_db: DBSession = Depends(get_user_db),
                           _: str = Depends(require_erp_api_key)):
    """Remote stop from the ERP. Operator override is highest priority: if the
    session is already ended (e.g. operator stopped it), return 409 and never
    restart it. Otherwise stop via the SAME flow as operator stop."""
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "active":
        raise HTTPException(status_code=409, detail="Session already ended by operator")

    # Identical to operator stop: complete the row + publish stop to the Opta.
    session_service.complete(db, session)
    from .controls import _publish_session_control
    _publish_session_control(db, session, "stop")
    db.refresh(session)
    logger.info("[NFC] ERP stopped session %d", session_id)
    return nfc_service.build_session_payload(db, user_db, session)
