"""v3.35 — energy interval ledger. FROZEN since 2026-10-10 16:12:59 UTC; nothing is billed from it.

PROVENANCE — READ BEFORE USING ANY ROW
--------------------------------------
Every row in this table is INTEGRAL-DERIVED: backend power x time, never a meter register.
The ledger froze at 2026-10-10 16:12:59 UTC, before the register path wrote a single row,
so the boundary is the whole table. There is deliberately no ``consumption_source`` column
here and no migration labelling these rows — this paragraph IS the label. A report covering a
period before that timestamp must say its interval figures are integrated estimates.

It was described as "the billing source of truth". It is not: the ERP owns invoicing, and
on the pilot cabinet this data exists only for our own analysis.

Each row is one 15-minute (configurable) checkpoint of an electricity session's
consumption, written by the interval logger and on session completion. When this was
built the Opta's cumulative ``energyKwh`` register read 0, so the energy here came from
the backend's power x time integration accumulated on ``sessions.energy_kwh``;
each interval row stores the DELTA since the previous checkpoint.

Attribution is copied off the active session so billing can aggregate without a
join back to sessions:
  - ``origin``: "customer" | "nfc" | "operator" | "berth-marina"
      ("berth-marina" = Smart Mode OFF standalone draw, no customer)
  - ``customer_id`` / ``nfc_user_id``: set for attributed sessions, else NULL
  - ``berth_ref``: the pedestal's berth reference (Option A) — the berth-config
      label for standalone per-socket daily billing.

Daily billing history is computed by aggregating these rows per (date, socket)
on read — there is no separate daily table to drift out of sync.
"""
from datetime import datetime

from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class EnergyInterval(Base):
    __tablename__ = "energy_intervals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pedestal_id: Mapped[int] = mapped_column(Integer, ForeignKey("pedestals.id"), nullable=False)
    socket_id: Mapped[int] = mapped_column(Integer, nullable=False)   # 1-4 (electricity only)
    session_id: Mapped[int] = mapped_column(Integer, nullable=True)   # active session during the window

    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="operator")
    customer_id: Mapped[int] = mapped_column(Integer, nullable=True)
    nfc_user_id: Mapped[str] = mapped_column(String(128), nullable=True)
    berth_ref: Mapped[str] = mapped_column(String(128), nullable=True)

    interval_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    interval_end: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    kwh: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_power_kw: Mapped[float] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_energy_interval_socket_time", "pedestal_id", "socket_id", "interval_start"),
        Index("ix_energy_interval_customer_time", "customer_id", "interval_start"),
        Index("ix_energy_interval_session", "session_id"),
    )
