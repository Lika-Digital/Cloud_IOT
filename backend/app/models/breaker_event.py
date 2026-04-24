"""v3.8 — breaker trip / reset audit log.

Every breaker state transition of interest (trip detected from firmware, operator
or ERP reset attempt, successful reset, failed reset, manual open) lands in
`breaker_events` so the audit trail is independent of the live `SocketConfig`
snapshot. The raw MQTT payload is preserved as JSON text for debugging.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, Float, DateTime, ForeignKey, String, Text, Index
from ..database import Base


class BreakerEvent(Base):
    __tablename__ = "breaker_events"

    id                    = Column(Integer, primary_key=True, index=True)
    pedestal_id           = Column(Integer, ForeignKey("pedestals.id"), nullable=False, index=True)
    socket_id             = Column(Integer, nullable=False)

    # tripped | reset_attempted | reset_success | reset_failed | manually_opened
    event_type            = Column(String(32), nullable=False)

    timestamp             = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    trip_cause            = Column(String(32), nullable=True)
    current_at_trip       = Column(Float, nullable=True)

    # Operator username for admin-initiated resets; `"erp-service"` for ERP-initiated.
    reset_initiated_by    = Column(String(64), nullable=True)

    # Full payload for forensic replay. Stored as JSON-encoded text (SQLite TEXT).
    raw_payload           = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_breaker_events_ped_socket_ts", "pedestal_id", "socket_id", "timestamp"),
    )
