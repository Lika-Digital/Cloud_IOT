"""v3.9 — Per-valve configuration (mirrors the v3.5 SocketConfig for electricity).

Holds the `auto_activate` flag for each (pedestal_id, valve_id) pair so an
operator can opt individual valves OUT of the post-diagnostic auto-open flow.

The default is **True** (opposite of SocketConfig): the hardware valve is
normally closed, so auto-open means only a commanded open; the flow meter
provides immediate visibility if anything unexpected happens. If the operator
flips auto_activate to False on a particular valve, post-diagnostic auto-open
skips that valve and the operator must open it manually via the Control Center.

valve_id = 1 for V1, 2 for V2.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint
from ..database import Base


class ValveConfig(Base):
    __tablename__ = "valve_configs"

    id            = Column(Integer, primary_key=True, index=True)
    pedestal_id   = Column(Integer, ForeignKey("pedestals.id"), nullable=False, index=True)
    valve_id      = Column(Integer, nullable=False)   # 1 (V1) or 2 (V2)
    # Default True per v3.9 design decision — hardware is normally-closed.
    auto_activate = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("pedestal_id", "valve_id", name="uq_valve_config"),
    )
