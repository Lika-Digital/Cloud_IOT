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
from datetime import datetime
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
from ..services import erp_reconciliation, nfc_service
from ..services.nfc_service import (
    DuplicateNfcTagError,
    OUTLET_SOCKET,
    OUTLET_VALVE,
    VALID_OUTLETS,
    WaterTagBlockedByAppVersion,
    outlet_type_for,
    session_type_for,
)
from ..time_utils import iso_z

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/nfc", tags=["nfc"])

# v3.43 — SIX outlets, not four. A cabinet with 4 sockets and 2 water outlets carries six
# NFC tags, one per outlet, and water works exactly like electricity: the customer scans the
# tag on the outlet they are about to use and the session belongs to whoever scanned. The
# old `_VALID_SOCKETS = {Q1..Q4}` made the two water tags unprovisionable — 400 at the door.
#
# The vocabulary lives in nfc_service so there is one list, not a router copy that drifts.
_ALL_OUTLETS = tuple(n for names in VALID_OUTLETS.values() for n in names)
_OUTLETS_HELP = "outlet must be one of " + ", ".join(_ALL_OUTLETS)

# Same threshold the comm-loss watchdog uses (main.COMM_LOSS_TIMEOUT_SECONDS). Imported by
# value rather than from main to avoid a circular import; kept identical on purpose, because
# two different opinions about when a cabinet is dead is how the dashboard and the NFC path
# would come to disagree in front of a customer.
COMM_LOSS_TIMEOUT_S = 60


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_pedestal(db: DBSession, cabinet_id: str) -> Optional[PedestalConfig]:
    """Lookup PedestalConfig by opta_client_id. Does NOT auto-create."""
    return db.query(PedestalConfig).filter(
        PedestalConfig.opta_client_id == cabinet_id
    ).first()


def _outlet_kind_or_400(outlet_name: str) -> str:
    """The outlet kind for a name, or 400 if this hardware has no such outlet.

    Replaces the Q1..Q4 set check. Note it returns the KIND rather than a boolean: every
    caller downstream needs to know whether it is holding a socket or a valve, and deciding
    that twice is how the two halves come to disagree.
    """
    kind = outlet_type_for(outlet_name)
    if kind is None:
        raise HTTPException(
            status_code=400,
            detail=f"{_OUTLETS_HELP} (got {outlet_name})",
        )
    return kind


def _outlet_str_to_id(outlet_name: str, kind: str) -> int:
    """Outlet name → the numeric id sessions and configs are keyed by.

    Q3 → 3 and V2 → 2. The numbers overlap between the two kinds by design — a water
    session on V1 and an electricity session on Q1 are both socket_id=1, told apart by
    Session.type — so the kind must be supplied rather than sniffed from the name.
    """
    from ..services.mqtt_handlers import _socket_name_to_id, _water_name_to_id
    if kind == OUTLET_VALVE:
        return _water_name_to_id(outlet_name)
    return _socket_name_to_id(outlet_name)


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
    # "Q1".."Q4" for a socket, "V1"/"V2" for a valve. Still 2 characters on today's
    # hardware, but the field no longer pins it at exactly 2 — the outlet vocabulary is
    # validated against nfc_service.VALID_OUTLETS, which is the list that actually knows.
    socket_id: str = Field(..., min_length=2, max_length=8)
    nfc_tag_id: str = Field(..., min_length=1, max_length=256)
    # Which kind of outlet the caller believes this is. Defaults to "socket" so every
    # existing client keeps working unchanged; a water tag must state "valve" explicitly.
    # The service refuses a mismatch (valve + Q3) rather than correcting it.
    outlet_type: str = Field(OUTLET_SOCKET, pattern="^(socket|valve)$")


class NfcBulkItem(BaseModel):
    socket_id: str = Field(..., min_length=2, max_length=8)
    nfc_tag_id: str = Field(..., min_length=1, max_length=256)
    outlet_type: str = Field(OUTLET_SOCKET, pattern="^(socket|valve)$")


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

@router.get("/outlets/{cabinet_id}")
def list_cabinet_outlets(cabinet_id: str, db: DBSession = Depends(get_db),
                         _: User = Depends(require_any_role)):
    """The outlets this cabinet actually has, for the provisioning UI to render.

    v3.43. The UI used to render a fixed four rows, `['Q1','Q2','Q3','Q4']`, which was wrong
    twice over: it omitted the two water outlets entirely, and it asserted four identical
    sockets when `opta/config/hardware` says Q1 is three-phase 32 A and Q3/Q4 are 16 A.

    The cabinet enumerates itself. This reads what it reported (persisted by
    `_handle_opta_hardware_config`) rather than assuming.

    `reported` says whether this is the cabinet's own account of itself or our fallback. It
    matters: a cabinet that has never published its hardware config is a different situation
    from one with no water outlets, and a UI that renders both as four rows cannot tell an
    admin which it is looking at. The fallback list is the canonical six — printed tags exist
    on the housing whether or not the cabinet has spoken since the last restart — but it is
    labelled as a fallback so the UI can say so.
    """
    from ..models.socket_config import SocketConfig
    from ..models.valve_config import ValveConfig

    cfg = _resolve_pedestal(db, cabinet_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail="Pedestal not found")

    socket_rows = db.query(SocketConfig).filter(
        SocketConfig.pedestal_id == cfg.pedestal_id
    ).order_by(SocketConfig.socket_id).all()
    valve_rows = db.query(ValveConfig).filter(
        ValveConfig.pedestal_id == cfg.pedestal_id
    ).order_by(ValveConfig.valve_id).all()

    # "Reported" means the cabinet told us, not that a row exists — socket_configs rows are
    # created by several other paths, so their presence proves nothing about hardware config.
    reported = any(getattr(r, "hw_config_received_at", None) for r in socket_rows)

    outlets: list[dict] = []
    if reported:
        for r in socket_rows:
            outlets.append({
                "outlet_name": f"Q{r.socket_id}",
                "outlet_type": OUTLET_SOCKET,
                "session_type": session_type_for(OUTLET_SOCKET),
                "meter_type": r.meter_type,
                "phases": r.phases,
                "rated_amps": r.rated_amps,
                "rated_liters_per_min": None,
            })
        for r in valve_rows:
            outlets.append({
                "outlet_name": f"V{r.valve_id}",
                "outlet_type": OUTLET_VALVE,
                "session_type": session_type_for(OUTLET_VALVE),
                "meter_type": None,
                "phases": None,
                "rated_amps": None,
                "rated_liters_per_min": r.rated_liters_per_min,
            })
    else:
        for kind, names in VALID_OUTLETS.items():
            for name in names:
                outlets.append({
                    "outlet_name": name,
                    "outlet_type": kind,
                    "session_type": session_type_for(kind),
                    "meter_type": None,
                    "phases": None,
                    "rated_amps": None,
                    "rated_liters_per_min": None,
                })

    tags = {t.socket_id: t for t in nfc_service.list_tags(db, cabinet_id)}
    for o in outlets:
        tag = tags.get(o["outlet_name"])
        o["nfc_tag_id"] = tag.nfc_tag_id if tag else None

    return {
        "cabinet_id": cabinet_id,
        "reported": reported,
        "outlets": outlets,
    }


def _tag_out(tag) -> dict:
    return {
        "nfc_tag_id": tag.nfc_tag_id,
        "cabinet_id": tag.cabinet_id,
        "socket_id": tag.socket_id,
        # v3.43 — "socket" or "valve". The UI cannot infer it from the name: both inbound
        # vocabularies accept bare digits, so "1" is genuinely ambiguous.
        "outlet_type": tag.outlet_type or OUTLET_SOCKET,
        "session_type": session_type_for(tag.outlet_type or OUTLET_SOCKET),
        "provisioned_at": iso_z(tag.provisioned_at),
        "provisioned_by": tag.provisioned_by,
        "is_active": tag.is_active,
        # v3.43 — surfaced so the trail is readable without a DB query. Null for an active tag
        # and for rows removed before the columns existed.
        "removed_at": iso_z(tag.removed_at) if tag.removed_at else None,
        "removed_by": tag.removed_by,
    }


@router.get("/tags/{cabinet_id}")
def list_nfc_tags(cabinet_id: str, db: DBSession = Depends(get_db),
                  _: User = Depends(require_any_role)):
    """Active NFC tag mappings for a cabinet (summary of the configuration)."""
    return [_tag_out(t) for t in nfc_service.list_tags(db, cabinet_id)]


def _provision_one(db, cabinet_id: str, socket_id: str, nfc_tag_id: str, by: str,
                   outlet_type: str = OUTLET_SOCKET):
    _outlet_kind_or_400(socket_id)
    try:
        return nfc_service.provision_tag(db, nfc_tag_id, cabinet_id, socket_id,
                                         provisioned_by=by, outlet_type=outlet_type)
    except WaterTagBlockedByAppVersion as e:
        # 409, not 400: the request is well-formed and will be valid once the app ships.
        # 400 would read as "you typed something wrong" and invite a retry.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
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
    tag = _provision_one(db, body.cabinet_id, body.socket_id, body.nfc_tag_id, admin.email,
                         outlet_type=body.outlet_type)
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
        _outlet_kind_or_400(it.socket_id)
        if it.outlet_type == OUTLET_VALVE:
            # In the PRE-PASS, not the write loop. Each provision commits individually,
            # so discovering this mid-loop would leave the electricity tags before it
            # applied and the ones after it not — a half-provisioned cabinet.
            try:
                nfc_service.assert_valve_provisioning_allowed()
            except WaterTagBlockedByAppVersion as e:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        if it.nfc_tag_id in seen and seen[it.nfc_tag_id] != it.socket_id:
            raise HTTPException(
                status_code=409,
                detail=f"NFC tag {it.nfc_tag_id} assigned to two sockets in the same request",
            )
        seen[it.nfc_tag_id] = it.socket_id
    out = []
    for it in body.items:
        out.append(_tag_out(_provision_one(db, body.cabinet_id, it.socket_id, it.nfc_tag_id,
                                           admin.email, outlet_type=it.outlet_type)))
    return {"cabinet_id": body.cabinet_id, "tags": out}


@router.delete("/tags/{cabinet_id}/{socket_id}")
def remove_nfc_tag(cabinet_id: str, socket_id: str, db: DBSession = Depends(get_db),
                   admin: User = Depends(require_admin)):
    """Clear the NFC tag mapping for a socket (is_active=False).

    The actor is recorded from v3.43 — the dependency was `_: User` before, discarding the one
    piece of information the audit trail was missing.
    """
    _outlet_kind_or_400(socket_id)
    cleared = nfc_service.remove_tag(db, cabinet_id, socket_id, removed_by=admin.email)
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


def _require_pedestal_can_act(cfg: PedestalConfig) -> None:
    """Refuse a scan the NUC cannot actually honour, and say why in words a customer can use.

    Both checks were absent before v3.43 (`grep smart_mode nfc.py` and `grep opta_connected`
    each returned nothing), so `/scan` answered *"pending — please plug in your charger"* in
    situations where nothing could follow. That is worse than an error: the customer plugs in,
    waits, nothing happens, and blames the system instead of retrying. This cabinet was silent
    for 19 days in September, so it has almost certainly already happened.

    The messages are written for someone standing on a pontoon with a cable in their hand.
    They name the thing that is wrong and the action that helps, because a generic failure
    leaves them with neither.

    **Liveness comes from the in-memory heartbeat, never from the database.**
    `mqtt_handlers.last_heartbeat` is populated only by live traffic — retained replays are
    dropped outright (v3.40) — and it resets on backend restart, so "absent" honestly means
    "we have not heard from this cabinet since we started". `PedestalConfig.last_heartbeat`
    and `opta_connected` persist, so they are last-known state and would report a cabinet that
    died weeks ago as reachable. A predicate a retained replay can satisfy is not a liveness
    check: see `docs/engineering_notes.md`.
    """
    from ..services.mqtt_handlers import last_heartbeat

    # Liveness first. If the cabinet is not answering we cannot trust our stored view of its
    # smart mode either, so "not responding" is the more truthful of the two answers.
    last_hb = last_heartbeat.get(cfg.pedestal_id)
    if last_hb is None or (datetime.utcnow() - last_hb).total_seconds() > COMM_LOSS_TIMEOUT_S:
        logger.warning(
            "[NFC] scan refused: pedestal=%s not responding (last live heartbeat %s)",
            cfg.pedestal_id, last_hb.isoformat() if last_hb else "never since restart",
        )
        raise HTTPException(
            status_code=503,
            detail="This pedestal is not responding, so the socket cannot be switched on. "
                   "Please contact the marina office.",
        )

    if not cfg.smart_mode:
        logger.warning("[NFC] scan refused: pedestal=%s has smart mode OFF", cfg.pedestal_id)
        raise HTTPException(
            status_code=409,
            detail="This pedestal is running on its own and cannot be switched on remotely. "
                   "Please ask the marina office to start your socket.",
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
        # Still a 404, and still no fallback to a default socket — but worded for the person
        # reading it. "NFC tag not provisioned" told a customer nothing they could act on.
        raise HTTPException(
            status_code=404,
            detail="This tag is not registered to a socket. Please contact the marina office "
                   "to have it registered.",
        )

    cabinet_id, socket_id = tag.cabinet_id, tag.socket_id
    cfg = _resolve_pedestal(db, cabinet_id)
    if cfg is None:
        # DISTINCT from "unknown tag" (v3.43). The tag IS provisioned — to a cabinet this
        # system has no record of. That is our provisioning error, not the customer's unknown
        # token, and sharing the 404 made a configuration fault indistinguishable from a
        # stranger's tag. 500 because it is a server-side inconsistency, not a bad request.
        logger.error("[NFC] tag %s is provisioned to cabinet %s, which has no pedestal row",
                     body.nfc_tag_id, cabinet_id)
        raise HTTPException(
            status_code=500,
            detail="This tag is registered to a pedestal the system does not recognise. "
                   "Please contact the marina office.",
        )

    # Can the NUC act at all? Smart mode and liveness, neither of which was checked before.
    _require_pedestal_can_act(cfg)

    # v3.43 — WHAT KIND of outlet this tag is on, taken from the tag rather than assumed.
    # This endpoint hardcoded session_type="electricity", so a water tag opened an
    # ELECTRICITY session against socket N — and the litres it later drew were billed as
    # kWh on an outlet the customer never touched. Rows written before the column exists
    # default to "socket", which is what they all were.
    outlet_type = tag.outlet_type or OUTLET_SOCKET
    session_type = session_type_for(outlet_type)
    is_valve = outlet_type == OUTLET_VALVE
    outlet_word = "water outlet" if is_valve else "socket"

    outlet_int = _outlet_str_to_id(socket_id, outlet_type)
    # Kept for the electricity path and for the response, which has always used this name.
    socket_int = outlet_int

    # Outlet availability. The fault check applies to electricity only.
    #
    # Not because a valve has no state — it does: `opta/water/V{n}/status` carries
    # `state` and `hw_status`, and v3.43 persists both on `valve_configs`. The reason is
    # narrower and specific to WHEN a valve fault becomes observable.
    #
    # The firmware has a valve `STATE_FAULT`, but it reports it REACTIVELY: an attempt to
    # open a faulted valve answers on `opta/acks` with
    # `{"status":"error","reason":"outlet_fault"}` (docs/firmware_requirements.md, v3.9).
    # It does not appear in the status topic, and no capture has ever shown a `state` or
    # `hw_status` value other than `idle`/`off`.
    #
    # `/scan` runs BEFORE any open command, so at this moment there is genuinely nothing
    # to read. A check here would test for a string we invented, pass always, and be
    # indistinguishable from a check that works — the failure mode worth naming. The
    # fault surfaces where it actually can: the ACK handler, on activation.
    #
    # Passing a valve through `_socket_display_state` would be worse: that reads
    # socket-keyed tables, so V1 would be judged on socket 1's hardware.
    if not is_valve and _socket_display_state(db, cfg.pedestal_id, outlet_int) == "fault":
        raise HTTPException(
            status_code=503,
            detail="This socket has a fault and cannot be used. Please contact the marina "
                   "office, or try another socket.",
        )
    # Filtered by session_type, so a water session on V1 no longer blocks an electricity
    # session on Q1 — they are different outlets that happen to share the number 1.
    active = session_service.get_active_for_socket(db, cfg.pedestal_id, outlet_int,
                                                  session_type=session_type)
    if active is not None and active.status == "active":
        raise HTTPException(
            status_code=409,
            detail=f"This {outlet_word} is already in use. Please use another {outlet_word}.",
        )

    # A still-valid pending scan for this socket blocks a second one. DISTINCT from
    # "already in use" (v3.43): sharing that message meant ERP — and the customer — could not
    # tell "someone is charging here" from "someone tapped 30 seconds ago", which are minutes
    # apart in what you should do about them.
    live = nfc_service.get_live_pending(db, cabinet_id, socket_id)
    if live is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Someone else tapped this {outlet_word} a moment ago and it is being "
                   f"held for them until {iso_z(live.expires_at)}. Please wait, or use "
                   f"another {outlet_word}.",
        )

    rec = nfc_service.create_pending(db, body.nfc_tag_id, user_id, cabinet_id, socket_id)
    # Log the resolved mapping and the authenticated principal, so an attribution dispute is
    # answerable from the journal rather than by inference.
    logger.info("[NFC] scan pre-registered user=%s (principal=%s) cabinet=%s outlet=%s "
                "type=%s tag=%s expires=%s",
                user_id, f"customer:{customer.id}" if customer else "erp-api-key",
                cabinet_id, socket_id, session_type, body.nfc_tag_id, iso_z(rec.expires_at))

    return {
        "status": "pending",
        "message": ("Please open your tap to activate the water outlet" if is_valve
                    else "Please plug in your charger to activate the socket"),
        "cabinet_id": cabinet_id,
        "socket_id": socket_id,
        # v3.43 — so ERP and the app can tell an electricity scan from a water one without
        # parsing the outlet name. Additive: existing fields are unchanged.
        "outlet_type": outlet_type,
        "session_type": session_type,
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
    # v3.43 — a machine caller reading this IS reconciliation; a customer reading their own
    # charge is not. Stamping both would silence the divergence detector every time someone
    # opened the app.
    if customer is None:
        erp_reconciliation.mark_reconciled(db, [session])
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
    # This endpoint exists so ERP can reconcile, so a machine read of it is the reconciliation
    # event itself — the strongest signal we get that the integration is alive.
    if customer is None:
        erp_reconciliation.mark_reconciled(db, rows)
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


# ══════════════════════════════════════════════════════════════════════════════
# ERP reconciliation visibility (admin)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/reconciliation")
def erp_reconciliation_status(db: DBSession = Depends(get_db),
                              _: User = Depends(require_any_role)):
    """Has ERP actually been reconciling, and what is waiting? (v3.43)

    Before this, our records could drift from ERP's silently — each side kept its own totals
    and nothing asserted they agreed. Divergence you can see is a problem; **silence is a
    problem you cannot see**, which is why the per-pedestal state matters more than the list.

    Three states, and only one of them is a fault:

      `reconciling`          ERP read something inside the window. Healthy.
      `silent_with_backlog`  Finished sessions are waiting AND ERP has not read in the window.
                             The integration has stopped and the marina is billing nothing.
      `idle`                 Nothing waiting. A quiet marina, not a broken one.

    Open to any operator deliberately: "is our billing reaching the ERP?" is an operational
    question the marina should be able to answer without an admin, and it exposes no
    configuration.
    """
    states = erp_reconciliation.status_by_pedestal(db)
    return {
        "mode": "direct" if settings.nfc_direct_client_mode else "erp",
        "silence_threshold_days": settings.erp_reconciliation_silence_days,
        # In MODE 2 there is no ERP, so none of this is meaningful. Said explicitly rather than
        # returning empty lists that read as "all healthy".
        "applicable": not settings.nfc_direct_client_mode,
        "pedestals": [s.as_dict() for s in states],
        "needs_attention": [s.as_dict() for s in states
                            if s.state == erp_reconciliation.STATE_SILENT_WITH_BACKLOG],
    }


@router.get("/reconciliation/divergence")
def erp_divergence(limit: int = Query(default=200, ge=1, le=1000),
                   db: DBSession = Depends(get_db),
                   _: User = Depends(require_any_role)):
    """Finished ERP sessions never acknowledged, OLDEST FIRST.

    Oldest first because the oldest unreconciled charge is the one most likely to be disputed
    or written off, and a newest-first list buries exactly the row that needs attention.
    """
    rows = erp_reconciliation.divergent_sessions(db, limit=limit)
    return {"count": len(rows), "sessions": rows}
