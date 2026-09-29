"""NFC tag provisioning (Socket Settings — NFC mode).

One row per NFC tag physically placed next to a socket on the pedestal housing.
The mapping is cabinet_id + socket_id (the firmware-facing string ids, e.g.
"MAR_KRK_ORM_01" / "Q1"), so this table lives in pedestal.db alongside the
socket/session hardware state that the MQTT handlers consult on plug-in.

Invariants enforced at the service layer (nfc_service):
  * `nfc_tag_id` is globally unique — a physical tag can only ever map to one
    socket. Provisioning a tag already owned by a different socket is rejected.
  * A socket has at most one ACTIVE tag — provisioning a new tag for a socket
    deactivates (is_active=False) the previous one rather than deleting history.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from ..database import Base


class NfcTag(Base):
    __tablename__ = "nfc_tags"

    id             = Column(Integer, primary_key=True, index=True)
    # Globally unique physical tag UID (string as read from the tag).
    nfc_tag_id     = Column(String, unique=True, nullable=False, index=True)
    # Firmware-facing identifiers (NOT the numeric pedestal_id).
    cabinet_id     = Column(String, nullable=False, index=True)
    socket_id      = Column(String, nullable=False)   # "Q1" | "Q2" | "Q3" | "Q4"

    provisioned_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    # Admin user email. Nullable in the schema for the rows that predate v3.43, but the
    # service layer now REFUSES to write a row without it — an unattributed mapping decides
    # which socket a customer's tap energises, and "who set this up" has to be answerable.
    provisioned_by = Column(String, nullable=True)
    is_active      = Column(Boolean, nullable=False, default=True)

    # v3.43 — removal audit trail. Deactivation kept the row but recorded neither who nor
    # when, so the only part of a tag's life that was traceable was its creation. For a
    # control that decides which socket a customer's tap energises, un-pointing it deserves
    # the same trail as pointing it.
    removed_at     = Column(DateTime, nullable=True)
    removed_by     = Column(String, nullable=True)
