"""NFC provisioning + ERP integration endpoints (v3.26, access model revised v3.43).

Two audiences:
  * **Admin (JWT, require_admin): provisioning.** Writing, re-assigning or deleting a tag, and
    switching a cabinet's provisioning mode, are INSTALLATION acts — after one, a customer's
    tap energises a different socket. They are admin only. Until v3.43 this docstring said
    `require_admin` while the code used `require_control`, so marina staff could re-point a
    physical tag; three places read as admin-only while behaving otherwise, which is how it
    stayed invisible. Reads stay open to any operator: answering "why did my tap not work?"
    is operations, not configuration.
  * ERP / myMarina (X-API-Key, require_erp_api_key): /scan pre-registration,
    /session read + remote stop. See the object-authorisation note further down — a valid key
    is not a claim to a particular record.

Critical architecture notes (per spec):
  * /scan does NOT activate the socket. It only pre-registers intent. Activation
    happens when the Opta reports UserPluggedIn over MQTT (see mqtt_handlers).
  * The operator always retains highest-priority control: the existing operator
    stop flow is unchanged and works for NFC sessions identically.
"""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from ..config import settings
from ..database import get_db
from ..auth.user_database import get_user_db
from ..auth.customer_dependencies import optional_customer
from ..auth.dependencies import require_admin, require_any_role
from ..auth.erp_api_key import require_erp_api_key
from ..auth.models import User
from ..models.session import Session
from ..models.pedestal_config import PedestalConfig
from ..services.session_service import session_service
from ..services import nfc_service
from ..services.nfc_service import DuplicateNfcTagError
from ..time_utils import iso_z

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
                          _: User = Depends(require_any_role)):
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
        "provisioned_at": iso_z(tag.provisioned_at),
        "provisioned_by": tag.provisioned_by,
        "is_active": tag.is_active,
    }


@router.get("/tags/{cabinet_id}")
def list_nfc_tags(cabinet_id: str, db: DBSession = Depends(get_db),
                  _: User = Depends(require_any_role)):
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
#
# OBJECT-LEVEL AUTHORISATION (v3.43)
# ----------------------------------
# These routes serve two callers: the ERP server-to-server, and the mobile app. Until v3.43
# they checked only that the X-API-Key was valid and then acted on whatever record id or
# `user_id` the request named. Authentication answers "who is this"; it never answers "may
# this caller touch this record", and the gap between those two questions is what these
# helpers close.
#
# It matters more than an ordinary IDOR because of what the records ARE. In MODE 2
# (nfc_direct_client_mode, no ERP) our session rows are the billing record — there is no
# second system holding the truth. Reading or stopping someone else's session there is
# tampering with a financial record, not merely seeing data you should not. In MODE 1 a forged
# identifier corrupts ERP reconciliation instead, and silently, because the two systems only
# compare totals.
#
# The principal was already available: the app's axios interceptor attaches
# `Authorization: Bearer <customer JWT>` to every request (mobile/src/api/client.ts:19-20),
# and the backend was discarding it in favour of the request body.


def _customer_identities(customer) -> set[str]:
    """Every string that legitimately identifies this customer in `nfc_user_id`.

    The app sends `profile.email || String(profile.id)`
    (`mobile/app/(app)/scan.tsx:42`), so both forms appear in stored rows and both must be
    accepted — otherwise the fix would lock customers out of their own sessions depending on
    which app version wrote the row.
    """
    out = {str(customer.id)}
    if getattr(customer, "email", None):
        out.add(customer.email)
        out.add(customer.email.lower())
    return out


def _owns(session, customer) -> bool:
    """Whether this customer owns this session.

    `customer_id` is the real foreign key and is checked first; `nfc_user_id` is the external
    string the app or ERP supplied, and is the only link for sessions created through the NFC
    path before an owner was claimed.
    """
    if session.customer_id is not None and session.customer_id == customer.id:
        return True
    if session.nfc_user_id:
        return session.nfc_user_id in _customer_identities(customer)
    return False


def _require_session_access(session, customer) -> None:
    """Gate a single session record.

    404, not 403, on a mismatch: a distinct "forbidden" would confirm that the session exists,
    which is all an enumeration needs. The caller who legitimately owns nothing and the caller
    probing someone else's id get the same answer.

    When there is no customer principal the caller is the ERP machine key. In MODE 1 that is a
    server acting on its own records and is allowed; in MODE 2 it is refused before reaching
    here, by `_require_direct_client_principal`.
    """
    if customer is None:
        return
    if not _owns(session, customer):
        raise HTTPException(status_code=404, detail="Session not found")


def _require_direct_client_principal(customer) -> None:
    """In MODE 2 a customer token is mandatory on the session endpoints.

    Without this the object checks above are bypassable by simply omitting the Bearer header:
    the caller falls back to being "the ERP", and the ERP key is compiled into the mobile app
    bundle (EXPO_PUBLIC_ERP_API_KEY), so it must be assumed known. A check that an attacker
    opts out of by sending fewer headers is not a check.

    MODE 1 deliberately still accepts the bare key, because there the caller really is ERP's
    server. Closing the app-shaped hole there means the app must stop holding the key at all —
    a separate change, and the key rotated with it.
    """
    if settings.nfc_direct_client_mode and customer is None:
        raise HTTPException(
            status_code=401,
            detail="This marina runs without an ERP, so a customer sign-in is required "
                   "for session data.",
        )


@router.post("/scan")
def nfc_scan(body: NfcScanBody, db: DBSession = Depends(get_db),
             customer=Depends(optional_customer),
             _: str = Depends(require_erp_api_key)):
    """Pre-register a marina customer's intent to use a socket (NFC tag scanned
    in myMarina). Does NOT activate the socket — activation happens on plug-in.

    `body.user_id` is NOT trusted when a customer token is present. It becomes
    `sessions.nfc_user_id`, which is what ERP reconciles billing against in MODE 1 and what
    attributes the charge itself in MODE 2 — so a value the caller simply asserts is a way to
    make someone else pay. Identity comes from the authenticated principal; a body value that
    disagrees is refused rather than quietly corrected, because a disagreement means either a
    client bug or an attempt, and both are worth surfacing.
    """
    _require_direct_client_principal(customer)

    user_id = body.user_id
    if customer is not None:
        allowed = _customer_identities(customer)
        if user_id not in allowed:
            logger.warning(
                "[NFC] scan REFUSED: customer id=%s presented user_id=%r which is not theirs",
                customer.id, user_id,
            )
            raise HTTPException(
                status_code=403,
                detail="user_id does not match the signed-in customer",
            )
        # Normalise to the authenticated identity rather than the supplied spelling, so
        # attribution is stable regardless of what the client sent.
        user_id = customer.email or str(customer.id)

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

    rec = nfc_service.create_pending(db, body.nfc_tag_id, user_id, cabinet_id, socket_id)
    # Log the resolved mapping and the authenticated principal, so an attribution dispute is
    # answerable from the journal rather than by inference.
    logger.info("[NFC] scan pre-registered user=%s (principal=%s) cabinet=%s socket=%s "
                "tag=%s expires=%s",
                user_id, f"customer:{customer.id}" if customer else "erp-api-key",
                cabinet_id, socket_id, body.nfc_tag_id, iso_z(rec.expires_at))

    return {
        "status": "pending",
        "message": "Please plug in your charger to activate the socket",
        "cabinet_id": cabinet_id,
        "socket_id": socket_id,
        "berth_id": getattr(cfg, "berth_ref", None),
        "expires_at": iso_z(rec.expires_at),
    }


@router.get("/session/{session_id}")
def nfc_session_status(session_id: int, db: DBSession = Depends(get_db),
                       user_db: DBSession = Depends(get_user_db),
                       customer=Depends(optional_customer),
                       _: str = Depends(require_erp_api_key)):
    """Current session status + spending data for the ERP to poll.

    A customer may read only their own session. The payload carries energy, duration and
    estimated cost, and in MODE 2 that is the billing record itself.
    """
    _require_direct_client_principal(customer)
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _require_session_access(session, customer)
    return nfc_service.build_session_payload(db, user_db, session)


@router.get("/sessions/by-user/{user_id}")
def nfc_sessions_by_user(
    user_id: str,
    status: Optional[str] = Query(None, pattern="^(active|ended)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: DBSession = Depends(get_db),
    user_db: DBSession = Depends(get_user_db),
    customer=Depends(optional_customer),
    _: str = Depends(require_erp_api_key),
):
    """All sessions (active + historical) for one ERP user_id, newest first.

    Lets the ERP reconcile its own records against our DB by *its own* user id —
    the `nfc_user_id` we stored from POST /api/nfc/scan. Each entry uses the same
    spending payload as GET /api/nfc/session/{id} (session_id, energy_kwh,
    duration_minutes, estimated_cost, status, …). Optional `status` narrows to
    active or ended; `limit` caps the result (default 100, max 500).

    A customer may list only their own sessions. 403 rather than 404 here, and deliberately:
    the `user_id` in the path was supplied by the caller, so refusing it plainly leaks nothing
    they did not already type, and a silent empty list would read as "you have no sessions"
    when the truth is "that is not you".
    """
    _require_direct_client_principal(customer)
    if customer is not None and user_id not in _customer_identities(customer):
        raise HTTPException(
            status_code=403, detail="You may only list your own sessions",
        )
    q = db.query(Session).filter(Session.nfc_user_id == user_id)
    if status == "active":
        q = q.filter(Session.status == "active")
    elif status == "ended":
        q = q.filter(Session.status != "active")
    rows = q.order_by(Session.started_at.desc()).limit(limit).all()
    return {
        "user_id": user_id,
        "count": len(rows),
        "sessions": [nfc_service.build_session_payload(db, user_db, s) for s in rows],
    }


@router.post("/session/{session_id}/stop")
async def nfc_session_stop(session_id: int, db: DBSession = Depends(get_db),
                           user_db: DBSession = Depends(get_user_db),
                           customer=Depends(optional_customer),
                           _: str = Depends(require_erp_api_key)):
    """Remote stop from the ERP. Operator override is highest priority: if the
    session is already ended (e.g. operator stopped it), return 409 and never
    restart it. Otherwise stop via the SAME flow as operator stop.

    A customer may stop only their own session. This is the check with a physical consequence:
    without it, any holder of the machine key could cut power to another berth mid-charge.
    Ownership is verified BEFORE the already-ended check, so a probe cannot learn the state of
    a session it does not own.
    """
    _require_direct_client_principal(customer)
    session = db.get(Session, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    _require_session_access(session, customer)
    if session.status != "active":
        raise HTTPException(status_code=409, detail="Session already ended by operator")

    # Identical to operator stop: complete the row + publish stop to the Opta.
    session_service.complete(db, session)
    from .controls import _publish_session_control
    _publish_session_control(db, session, "stop")
    db.refresh(session)
    logger.info("[NFC] ERP stopped session %d", session_id)
    return nfc_service.build_session_payload(db, user_db, session)
