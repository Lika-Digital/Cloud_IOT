"""Per-socket configuration.

Holds the `auto_activate` flag for each (pedestal_id, socket_id) pair so an
operator can opt individual sockets into the auto-activation flow introduced
in v3.5. Water valves are intentionally not represented — the feature is
electricity-only.

v3.8 adds breaker state + metadata columns. Metadata (breaker_type, breaker_rating,
breaker_poles, breaker_rcd, breaker_rcd_sensitivity) is populated exclusively from
incoming MQTT payloads on `opta/breakers/+/status` — the backend never assumes or
hardcodes values, and a missing key in a subsequent payload does not overwrite
previously-stored metadata. `breaker_trip_count` is cumulative forever.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from ..database import Base


class SocketConfig(Base):
    __tablename__ = "socket_configs"

    id            = Column(Integer, primary_key=True, index=True)
    pedestal_id   = Column(Integer, ForeignKey("pedestals.id"), nullable=False, index=True)
    socket_id     = Column(Integer, nullable=False)   # 1–4
    auto_activate = Column(Boolean, nullable=False, default=False)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # v3.8 — live breaker state, populated from opta/breakers/{socket_id}/status.
    breaker_state            = Column(String, nullable=True, default="unknown")
    breaker_last_trip_at     = Column(DateTime, nullable=True)
    breaker_trip_cause       = Column(String, nullable=True)
    breaker_trip_count       = Column(Integer, nullable=False, default=0)

    # v3.8 — breaker hardware metadata reported by Arduino at runtime. Never
    # hardcoded; missing keys in an update preserve the previous value.
    breaker_type             = Column(String, nullable=True)
    breaker_rating           = Column(String, nullable=True)
    breaker_poles            = Column(String, nullable=True)
    breaker_rcd              = Column(Boolean, nullable=True)
    breaker_rcd_sensitivity  = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("pedestal_id", "socket_id", name="uq_socket_config"),
    )
