"""NFC provisioning + pending-session logic (v3.26).

All functions operate on the pedestal.db session (the caller supplies `db`).
Tag identifiers are firmware-facing strings: cabinet_id (e.g. "MAR_KRK_ORM_01")
and socket_id ("Q1".."Q4").

Design points (confirmed):
  * A physical NFC tag (`nfc_tag_id`) is globally unique — it can map to exactly
    one socket. Re-provisioning the same tag to a different socket is rejected.
  * A socket has at most one ACTIVE tag; provisioning a new tag for a socket
    deactivates the previous one (history is retained, is_active=False).
  * Pending sessions expire LAZILY after 5 minutes — no background task; callers
    use `get_live_pending` / `expire_if_past` which mark stale rows expired inline.
"""
import logging
from datetime import datetime, timedelta

from ..models.nfc_tag import NfcTag
from ..models.nfc_pending_session import NfcPendingSession
from ..time_utils import iso_z

logger = logging.getLogger(__name__)

PENDING_TTL_MINUTES = 5


class DuplicateNfcTagError(Exception):
    """Raised when an nfc_tag_id is already active on a different socket."""

    def __init__(self, cabinet_id: str, socket_id: str):
        self.cabinet_id = cabinet_id
        self.socket_id = socket_id
        super().__init__(
            f"NFC tag already provisioned to {cabinet_id} / {socket_id}"
        )


# ── Provisioning (admin) ──────────────────────────────────────────────────────

def get_active_tag_for_socket(db, cabinet_id: str, socket_id: str) -> NfcTag | None:
    return (
        db.query(NfcTag)
        .filter(
            NfcTag.cabinet_id == cabinet_id,
            NfcTag.socket_id == socket_id,
            NfcTag.is_active.is_(True),
        )
        .first()
    )


def get_active_tag_by_id(db, nfc_tag_id: str) -> NfcTag | None:
    return (
        db.query(NfcTag)
        .filter(NfcTag.nfc_tag_id == nfc_tag_id, NfcTag.is_active.is_(True))
        .first()
    )


def list_tags(db, cabinet_id: str) -> list[NfcTag]:
    """Active tags for a cabinet, ordered by socket id."""
    return (
        db.query(NfcTag)
        .filter(NfcTag.cabinet_id == cabinet_id, NfcTag.is_active.is_(True))
        .order_by(NfcTag.socket_id)
        .all()
    )


OUTLET_SOCKET = "socket"
OUTLET_VALVE = "valve"

# The outlet names each kind may legitimately carry, per the firmware capture. Deliberately NOT
# derived from the MQTT resolver's allowlists: those accept unverified marina/* spellings for
# inbound traffic, whereas a TAG we write ourselves has no such excuse and should only ever use
# what the hardware actually publishes — Q1..Q4 and V1/V2.
VALID_OUTLETS = {
    OUTLET_SOCKET: ("Q1", "Q2", "Q3", "Q4"),
    OUTLET_VALVE: ("V1", "V2"),
}


def outlet_type_for(outlet_name: str) -> str | None:
    """Which kind of outlet this name belongs to, or None if it belongs to neither.

    Used to CHECK a caller's stated type, never to replace it. The type is stored on the tag
    because names are ambiguous in general — both inbound vocabularies accept bare digits, so
    "1" cannot distinguish socket 1 from valve 1. This helper only catches a caller that says
    "valve" while naming Q3.
    """
    for kind, names in VALID_OUTLETS.items():
        if outlet_name in names:
            return kind
    return None


def session_type_for(outlet_type: str) -> str:
    """The session type an outlet kind produces.

    `/scan` used to hardcode "electricity". Deriving it from the tag is what makes a water tag
    open a WATER session rather than an electricity one on the same numeric socket.
    """
    return "water" if outlet_type == OUTLET_VALVE else "electricity"


def provision_tag(db, nfc_tag_id: str, cabinet_id: str, socket_id: str,
                  provisioned_by: str | None = None,
                  outlet_type: str = OUTLET_SOCKET) -> NfcTag:
    """Map an NFC tag to a socket, replacing any previous active tag on that
    socket. Raises DuplicateNfcTagError if the tag is already active elsewhere.

    `provisioned_by` is REQUIRED from v3.43. The column stays nullable for rows written before
    then, but a new unattributed mapping is refused: this decides which socket a customer's tap
    energises, and every path that creates one must be able to answer who did it. It is a
    ValueError rather than a silent default because a caller that has no actor has a bug, and
    writing "(unknown)" would hide it.
    """
    nfc_tag_id = (nfc_tag_id or "").strip()
    if not nfc_tag_id:
        raise ValueError("nfc_tag_id is required")
    if outlet_type not in VALID_OUTLETS:
        raise ValueError(
            f"outlet_type must be one of {sorted(VALID_OUTLETS)}, got {outlet_type!r}"
        )
    implied = outlet_type_for(socket_id)
    if implied is None:
        raise ValueError(
            f"{socket_id!r} is not an outlet this hardware has. Expected one of "
            f"{list(VALID_OUTLETS[outlet_type])} for a {outlet_type}."
        )
    if implied != outlet_type:
        # Refused rather than silently corrected: a caller that says "valve" while naming Q3
        # has a bug, and choosing one of the two for them would hide which one.
        raise ValueError(
            f"{socket_id!r} is a {implied}, but outlet_type says {outlet_type!r}. A water tag "
            f"must never be provisioned against an electricity socket, or the reverse."
        )
    if not (provisioned_by or "").strip():
        raise ValueError(
            "provisioned_by is required — an NFC mapping must be attributable to the admin "
            "who created it"
        )

    # Reject the same physical tag mapped to a DIFFERENT socket.
    existing = get_active_tag_by_id(db, nfc_tag_id)
    if existing is not None and not (
        existing.cabinet_id == cabinet_id and existing.socket_id == socket_id
    ):
        raise DuplicateNfcTagError(existing.cabinet_id, existing.socket_id)

    # Deactivate whatever tag currently owns this socket (different tag id).
    for old in (
        db.query(NfcTag).filter(
            NfcTag.cabinet_id == cabinet_id,
            NfcTag.socket_id == socket_id,
            NfcTag.is_active.is_(True),
        ).all()
    ):
        if old.nfc_tag_id != nfc_tag_id:
            old.is_active = False

    now = datetime.utcnow()
    if existing is not None:
        # Same tag re-provisioned to the same socket — refresh metadata.
        existing.is_active = True
        existing.provisioned_at = now
        existing.provisioned_by = provisioned_by
        existing.outlet_type = outlet_type
        tag = existing
    else:
        tag = NfcTag(
            nfc_tag_id=nfc_tag_id,
            cabinet_id=cabinet_id,
            socket_id=socket_id,
            provisioned_at=now,
            provisioned_by=provisioned_by,
            outlet_type=outlet_type,
            is_active=True,
        )
        db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def remove_tag(db, cabinet_id: str, socket_id: str,
               removed_by: str | None = None) -> bool:
    """Deactivate the active tag for a socket. Returns True if one was cleared.

    `removed_by` is recorded alongside the time (v3.43). The row already survived removal, so
    the history was there — but nothing said who un-pointed the tag or when, which made the
    one destructive act in a tag's life the only untraceable one.
    """
    tag = get_active_tag_for_socket(db, cabinet_id, socket_id)
    if tag is None:
        return False
    tag.is_active = False
    tag.removed_at = datetime.utcnow()
    tag.removed_by = removed_by
    db.commit()
    logger.info("[NFC] tag %s removed from cabinet=%s socket=%s by %s",
                tag.nfc_tag_id, cabinet_id, socket_id, removed_by or "(unattributed)")
    return True


# ── Pending sessions (lazy expiry) ────────────────────────────────────────────

def expire_if_past(db, record: NfcPendingSession) -> bool:
    """If a pending record is past expiry, mark it expired. Returns True if the
    record is (now) expired and must be treated as absent."""
    if record.status != "pending":
        return record.status == "expired"
    if record.expires_at <= datetime.utcnow():
        record.status = "expired"
        db.commit()
        return True
    return False


def get_live_pending(db, cabinet_id: str, socket_id: str) -> NfcPendingSession | None:
    """Return the most recent still-valid (pending, non-expired) record for a
    socket, lazily expiring any stale pending rows for that socket."""
    rows = (
        db.query(NfcPendingSession)
        .filter(
            NfcPendingSession.cabinet_id == cabinet_id,
            NfcPendingSession.socket_id == socket_id,
            NfcPendingSession.status == "pending",
        )
        .order_by(NfcPendingSession.created_at.desc())
        .all()
    )
    live = None
    for r in rows:
        if expire_if_past(db, r):
            continue
        if live is None:
            live = r  # newest valid one
    return live


def create_pending(db, nfc_tag_id: str, user_id: str, cabinet_id: str,
                   socket_id: str) -> NfcPendingSession:
    """Create a 5-minute pending NFC session record."""
    now = datetime.utcnow()
    rec = NfcPendingSession(
        nfc_tag_id=nfc_tag_id,
        user_id=user_id,
        cabinet_id=cabinet_id,
        socket_id=socket_id,
        created_at=now,
        expires_at=now + timedelta(minutes=PENDING_TTL_MINUTES),
        status="pending",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


# ── Session data payload (shared by GET /api/nfc/session and the ERP webhook) ──

def build_session_payload(db, user_db, session) -> dict:
    """Build the ERP-facing session view used by GET /api/nfc/session/{id} and
    the ERP webhook. `db` = pedestal.db session, `user_db` = users.db session.

    estimated_cost uses the global BillingConfig.kwh_price_eur (energy_kwh * price);
    None when no BillingConfig row exists, and None for a water session (see below).

    v3.43 — WATER SESSIONS REACH THIS FUNCTION NOW, and it assumed electricity throughout.
    Since a water session on V1 and an electricity session on Q1 are both `socket_id=1`,
    every socket-keyed lookup here silently returned the WRONG OUTLET'S figures for a
    water session: the outlet was reported as "Q1", and `energy_kwh` fell back to socket 1's
    cumulative electricity register. ERP would have received a plausible kWh number for a
    session that drew litres, attributed to an outlet the customer never touched.

    It was unreachable before only because water tags could not be provisioned. Enabling
    the six-tag model is what made it reachable, which is why it is fixed in the same
    change rather than left as a follow-up.
    """
    from ..models.pedestal_config import PedestalConfig
    from ..models.socket_config import SocketConfig
    from ..models.valve_config import ValveConfig

    cfg = db.query(PedestalConfig).filter(
        PedestalConfig.pedestal_id == session.pedestal_id
    ).first()
    cabinet_id = getattr(cfg, "opta_client_id", None) if cfg else None

    is_water = getattr(session, "type", None) == "water"

    sc = vc = None
    if session.socket_id is not None:
        if is_water:
            vc = db.query(ValveConfig).filter(
                ValveConfig.pedestal_id == session.pedestal_id,
                ValveConfig.valve_id == session.socket_id,
            ).first()
        else:
            sc = db.query(SocketConfig).filter(
                SocketConfig.pedestal_id == session.pedestal_id,
                SocketConfig.socket_id == session.socket_id,
            ).first()

    is_active = session.status == "active"

    # Energy and litres are reported in their own fields and never substituted for one
    # another. A water session has energy_kwh = None, not 0.0 — the same distinction the
    # register work drew: zero means measured zero, and this outlet measures no kWh at all.
    energy_kwh = None if is_water else session.energy_kwh
    if not is_water and energy_kwh is None and sc is not None:
        # Live register total while the session runs; the session field once it completes.
        energy_kwh = sc.meter_energy_kwh
    energy_kwh = round(energy_kwh, 4) if energy_kwh is not None else None

    water_liters = getattr(session, "water_liters", None) if is_water else None
    if is_water and water_liters is None and vc is not None:
        water_liters = vc.meter_total_l
    water_liters = round(water_liters, 3) if water_liters is not None else None

    power_kw_current = (sc.meter_power_kw if (is_active and sc is not None) else 0.0) or 0.0

    end = session.ended_at or datetime.utcnow()
    duration_minutes = round(max(0.0, (end - session.started_at).total_seconds()) / 60.0, 2)

    # Priced from the kWh tariff, so it applies to electricity only. A water session gets
    # None rather than a euro figure derived from the wrong tariff — and in MODE 1 ERP
    # prices everything anyway; this field is an estimate for display, never the invoice.
    estimated_cost = None
    try:
        from ..auth.customer_models import BillingConfig
        billing = user_db.get(BillingConfig, 1)
        if billing is not None and energy_kwh is not None:
            estimated_cost = round(energy_kwh * (billing.kwh_price_eur or 0.0), 4)
    except Exception:
        estimated_cost = None

    # The outlet name follows the session TYPE. The numbers overlap between the two kinds
    # (V1 and Q1 are both 1), so the prefix is the only thing that says which outlet this
    # is — and ERP reconciles on this string.
    outlet_prefix = "V" if is_water else "Q"

    return {
        "session_id": session.id,
        "cabinet_id": cabinet_id,
        "socket_id": (f"{outlet_prefix}{session.socket_id}"
                      if session.socket_id is not None else None),
        # v3.43, additive: which kind of outlet, so ERP does not have to parse the name.
        "session_type": "water" if is_water else "electricity",
        "customer_id": session.nfc_user_id,
        "status": "active" if is_active else "ended",
        "activated_at": iso_z(session.started_at),
        "duration_minutes": duration_minutes,
        # Exactly one of these carries a figure. The other is None — NOT 0.0, which would
        # read as "measured nothing" for a quantity this outlet does not measure.
        "energy_kwh": energy_kwh,
        "water_liters": water_liters,
        "power_kw_current": round(power_kw_current, 3),
        "estimated_cost": estimated_cost,
    }
