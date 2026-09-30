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
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Float, ForeignKey, UniqueConstraint,
)
from ..database import Base


class ValveConfig(Base):
    __tablename__ = "valve_configs"

    id            = Column(Integer, primary_key=True, index=True)
    pedestal_id   = Column(Integer, ForeignKey("pedestals.id"), nullable=False, index=True)
    valve_id      = Column(Integer, nullable=False)   # 1 (V1) or 2 (V2)
    # Default True per v3.9 design decision — hardware is normally-closed.
    auto_activate = Column(Boolean, nullable=False, default=True)

    # v3.43 — from opta/config/hardware, which enumerates the cabinet's own valves
    # (V1 and V2, both 20 L/min on MAR_KRK_ORM_01). The cabinet tells us what it has;
    # provisioning reads this rather than assuming a fixed outlet list.
    rated_liters_per_min = Column(Float, nullable=True)

    # v3.43 — the valve's cumulative water register (`total_l` from
    # opta/water/V{n}/status), mirroring socket_configs.meter_energy_kwh for electricity. This
    # is what we forward to ERP as cumulative-per-outlet, and the source of a session's litres
    # (end minus start) rather than any figure we derive.
    meter_total_l    = Column(Float, nullable=True)
    meter_updated_at = Column(DateTime, nullable=True)

    # v3.43 — the valve's LAST REPORTED STATE, persisted.
    #
    # `opta/water/V{n}/status` has always carried `state` ("idle"/"active") and `hw_status`
    # ("off"/...) — the real payload is
    #     {"id":"V1","state":"idle","hw_status":"off","ts":…,"total_l":…,"session_l":…}
    # — but the handler broadcast them over the websocket and kept nothing. So any caller that
    # was not listening at that moment had no way to ask what a valve was doing, and
    # `socket_states` (which is keyed by number alone) would have answered with the ELECTRICITY
    # socket of the same number.
    #
    # This is the valve counterpart of `socket_states`, put on ValveConfig rather than in a new
    # table because the row already exists per (pedestal, valve) and the socket equivalent's
    # extra columns — operator approval — have no valve analogue.
    #
    # `state_updated_at` is not decoration: a stored state is only as good as its age. A valve
    # whose cabinet went silent three days ago must not report "idle" as though it were current
    # (docs/engineering_notes.md, rule 1).
    last_state       = Column(String, nullable=True)
    last_hw_status   = Column(String, nullable=True)
    state_updated_at = Column(DateTime, nullable=True)

    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("pedestal_id", "valve_id", name="uq_valve_config"),
    )
