"""v3.10 — Per-pedestal daily LED on/off schedule.

One row per pedestal. The background `led_scheduler` ticks every minute and
fires `opta/cmd/led` when the current marina-local time matches `on_time` or
`off_time`. Operator can opt out per pedestal by setting `enabled=False`
(row stays so the configuration is preserved).

Days of week are stored as a comma-separated string of integers 0..6 where
0 = Monday and 6 = Sunday (matches Python `datetime.weekday()`).
Color is one of {green, blue, red, yellow} for v3.10 — `white` is deferred
until the Arduino firmware confirms support (see `docs/firmware_requirements.md`).
"""
from datetime import datetime
from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey, String, UniqueConstraint
from ..database import Base


class LedSchedule(Base):
    __tablename__ = "led_schedules"

    id            = Column(Integer, primary_key=True, index=True)
    pedestal_id   = Column(Integer, ForeignKey("pedestals.id"), nullable=False, index=True)
    enabled       = Column(Boolean, nullable=False, default=True)
    # HH:MM strings (24-hour). Validated by the API layer; stored verbatim
    # so the operator's chosen value round-trips unchanged.
    on_time       = Column(String(5), nullable=False)
    off_time      = Column(String(5), nullable=False)
    color         = Column(String(16), nullable=False, default="green")
    # Comma-separated weekday ints 0..6. Default = every day.
    days_of_week  = Column(String(32), nullable=False, default="0,1,2,3,4,5,6")
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("pedestal_id", name="uq_led_schedule_pedestal"),
    )
