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
from datetime import datetime, timedelta

from ..models.nfc_tag import NfcTag
from ..models.nfc_pending_session import NfcPendingSession

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


def provision_tag(db, nfc_tag_id: str, cabinet_id: str, socket_id: str,
                  provisioned_by: str | None = None) -> NfcTag:
    """Map an NFC tag to a socket, replacing any previous active tag on that
    socket. Raises DuplicateNfcTagError if the tag is already active elsewhere."""
    nfc_tag_id = (nfc_tag_id or "").strip()
    if not nfc_tag_id:
        raise ValueError("nfc_tag_id is required")

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
        tag = existing
    else:
        tag = NfcTag(
            nfc_tag_id=nfc_tag_id,
            cabinet_id=cabinet_id,
            socket_id=socket_id,
            provisioned_at=now,
            provisioned_by=provisioned_by,
            is_active=True,
        )
        db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


def remove_tag(db, cabinet_id: str, socket_id: str) -> bool:
    """Deactivate the active tag for a socket. Returns True if one was cleared."""
    tag = get_active_tag_for_socket(db, cabinet_id, socket_id)
    if tag is None:
        return False
    tag.is_active = False
    db.commit()
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
    None when no BillingConfig row exists.
    """
    from ..models.pedestal_config import PedestalConfig
    from ..models.socket_config import SocketConfig

    cfg = db.query(PedestalConfig).filter(
        PedestalConfig.pedestal_id == session.pedestal_id
    ).first()
    cabinet_id = getattr(cfg, "opta_client_id", None) if cfg else None

    sc = None
    if session.socket_id is not None:
        sc = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == session.pedestal_id,
            SocketConfig.socket_id == session.socket_id,
        ).first()

    is_active = session.status == "active"
    # Energy: final value once the session is completed; live meter total while active.
    energy_kwh = session.energy_kwh
    if energy_kwh is None and sc is not None:
        energy_kwh = sc.meter_energy_kwh
    energy_kwh = round(energy_kwh, 4) if energy_kwh is not None else None

    power_kw_current = (sc.meter_power_kw if (is_active and sc is not None) else 0.0) or 0.0

    end = session.ended_at or datetime.utcnow()
    duration_minutes = round(max(0.0, (end - session.started_at).total_seconds()) / 60.0, 2)

    estimated_cost = None
    try:
        from ..auth.customer_models import BillingConfig
        billing = user_db.get(BillingConfig, 1)
        if billing is not None and energy_kwh is not None:
            estimated_cost = round(energy_kwh * (billing.kwh_price_eur or 0.0), 4)
    except Exception:
        estimated_cost = None

    return {
        "session_id": session.id,
        "cabinet_id": cabinet_id,
        "socket_id": f"Q{session.socket_id}" if session.socket_id is not None else None,
        "customer_id": session.nfc_user_id,
        "status": "active" if is_active else "ended",
        "activated_at": session.started_at.isoformat() if session.started_at else None,
        "duration_minutes": duration_minutes,
        "energy_kwh": energy_kwh,
        "power_kw_current": round(power_kw_current, 3),
        "estimated_cost": estimated_cost,
    }
