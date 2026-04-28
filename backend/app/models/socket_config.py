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
from sqlalchemy import Column, Integer, Boolean, DateTime, ForeignKey, Float, String, UniqueConstraint
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

    # v3.11 — meter hardware configuration reported by Arduino on
    # `opta/config/hardware`. Same no-overwrite-with-null rule as breaker
    # metadata: a missing key in a subsequent payload preserves the previous
    # value. `phases` is 1 (single-phase) or 3 (three-phase). The backend
    # never assumes meter type, phase count, or rated_amps — they are read
    # exclusively from this MQTT payload.
    meter_type               = Column(String, nullable=True)
    phases                   = Column(Integer, nullable=True)
    rated_amps               = Column(Float, nullable=True)
    modbus_address           = Column(Integer, nullable=True)
    hw_config_received_at    = Column(DateTime, nullable=True)

    # v3.11 — live meter readings populated from `opta/meters/{socket}/telemetry`.
    # Single-phase sockets: only the aggregate columns are populated.
    # Three-phase sockets: aggregate + per-phase columns are both populated.
    # `meter_load_pct` and `meter_load_status` are derived; the rest are
    # passthrough from the firmware's Modbus reading.
    meter_current_amps       = Column(Float, nullable=True)
    meter_voltage_v          = Column(Float, nullable=True)
    meter_power_kw           = Column(Float, nullable=True)
    meter_power_factor       = Column(Float, nullable=True)
    meter_energy_kwh         = Column(Float, nullable=True)
    meter_frequency_hz       = Column(Float, nullable=True)

    # 3-phase only.
    meter_current_l1         = Column(Float, nullable=True)
    meter_current_l2         = Column(Float, nullable=True)
    meter_current_l3         = Column(Float, nullable=True)
    meter_voltage_l1         = Column(Float, nullable=True)
    meter_voltage_l2         = Column(Float, nullable=True)
    meter_voltage_l3         = Column(Float, nullable=True)

    # Derived. `load_pct` for 3-phase is max(L1,L2,L3)/rated_amps*100 — the
    # bottleneck phase, not the sum (D2 design decision; spec was incorrect).
    meter_load_pct           = Column(Float, nullable=True)
    meter_load_status        = Column(String, nullable=False, default="unknown")
    meter_load_updated_at    = Column(DateTime, nullable=True)

    # Operator-configurable thresholds. The only meter-related values an
    # operator may set; everything else is read-only hardware data.
    load_warning_threshold_pct  = Column(Integer, nullable=False, default=60)
    load_critical_threshold_pct = Column(Integer, nullable=False, default=80)

    __table_args__ = (
        UniqueConstraint("pedestal_id", "socket_id", name="uq_socket_config"),
    )
