"""v3.11 — Live socket meter load alarms.

One row per *threshold crossing*. Rows stay in the table forever — `resolved_at`
distinguishes open from closed alarms:

- `resolved_at IS NULL` ⇒ alarm is currently active (visible on the System
  Health badge + alarm card).
- `resolved_at IS NOT NULL` ⇒ historical record. `resolved_by` is the operator
  email (manual resolve), `"auto-resolve"` (load returned to normal),
  `"auto-upgrade"` (warning superseded by critical), or `"auto-downgrade"`
  (critical superseded by warning).

`acknowledged` is a separate flag from `resolved_at`: an acknowledged-but-
not-resolved alarm stays visible (dimmed) on the dashboard, and stops counting
toward the navigation badge. The `phases` and `meter_type` columns are copied
from the SocketConfig snapshot at trigger-time so the audit row is self-
contained even if the meter is later swapped for a different model.
"""
from datetime import datetime
from sqlalchemy import Column, Integer, Boolean, DateTime, Float, ForeignKey, String, Index
from ..database import Base


class MeterLoadAlarm(Base):
    __tablename__ = "meter_load_alarms"

    id            = Column(Integer, primary_key=True, index=True)
    pedestal_id   = Column(Integer, ForeignKey("pedestals.id"), nullable=False, index=True)
    socket_id     = Column(Integer, nullable=False)
    # "warning" | "critical"
    alarm_type    = Column(String(16), nullable=False)

    # Snapshot of the live meter reading + hardware config that triggered.
    current_amps  = Column(Float, nullable=False)
    rated_amps    = Column(Float, nullable=False)
    load_pct      = Column(Float, nullable=False)
    phases        = Column(Integer, nullable=False)
    meter_type    = Column(String, nullable=True)

    triggered_at  = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    resolved_at   = Column(DateTime, nullable=True, index=True)
    # operator email | "auto-resolve" | "auto-upgrade" | "auto-downgrade"
    resolved_by   = Column(String(64), nullable=True)

    acknowledged       = Column(Boolean, nullable=False, default=False)
    acknowledged_at    = Column(DateTime, nullable=True)
    acknowledged_by    = Column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_meter_load_alarms_open", "pedestal_id", "socket_id", "resolved_at"),
    )
