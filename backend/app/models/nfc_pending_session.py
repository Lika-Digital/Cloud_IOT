"""NFC pending session — pre-registration of user intent before plug-in.

Created by POST /api/nfc/scan when a marina customer scans an NFC tag in the
myMarina ERP app. It records that `user_id` intends to use `cabinet_id`/`socket_id`,
valid for 5 minutes. Activation does NOT happen here — when the Opta later reports
`UserPluggedIn` for that cabinet+socket, the MQTT handler looks up a non-expired
`pending` record, authorizes a one-shot activate, attaches the ERP user to the
resulting session, and marks the record `activated`.

Expiry is LAZY (no background task): `expires_at` is checked at the moment a new
/api/nfc/scan or a UserPluggedIn event arrives for the same socket; a record past
its expiry is marked `expired` then and treated as if absent.

Lives in pedestal.db so the MQTT handlers (pedestal.db session) can consult it
inline during plug-in handling.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Index
from ..database import Base


class NfcPendingSession(Base):
    __tablename__ = "nfc_pending_sessions"

    id          = Column(Integer, primary_key=True, index=True)
    nfc_tag_id  = Column(String, nullable=False, index=True)
    user_id     = Column(String, nullable=False)     # ERP / myMarina customer id (string)
    cabinet_id  = Column(String, nullable=False)
    socket_id   = Column(String, nullable=False)     # "Q1" | "Q2" | "Q3" | "Q4"

    created_at  = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at  = Column(DateTime, nullable=False)
    # "pending" | "activated" | "expired"
    status      = Column(String, nullable=False, default="pending", index=True)

    __table_args__ = (
        # Fast lookup of the live pending record per socket during plug-in.
        Index("ix_nfc_pending_socket", "cabinet_id", "socket_id", "status"),
    )
