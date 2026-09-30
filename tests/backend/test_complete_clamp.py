"""
Corrupt telemetry must never become the billed total (v3.14, rewritten for v3.43).
=================================================================================

The original guard: a single corrupt packet (9999 kWh, 99999 L) must not be billed, so
`complete()` clamped readings to sanity bounds and took `max()` of the survivors.

**v3.43 makes that guarantee structural instead of defensive.** The billed figure is now
`end - start` of the meter's own cumulative register, so a corrupt *reading* cannot reach it at
all — readings only feed the comparison figure. These tests are rewritten to assert the stronger
property rather than adjusted to keep passing: the spike is not clamped out of the billed total,
it was never eligible for it.

The sanity ceiling still exists, applied to the register delta itself — and there it REJECTS
rather than clamps, because a register delta of 9999 kWh is a meter fault, not a large session,
and quietly substituting a smaller number would hide it.

  TC-CLAMP-01  an electricity spike reading cannot influence the billed figure
  TC-CLAMP-02  a water spike reading cannot influence the billed figure
  TC-CLAMP-03  a legitimate high register delta is still billed in full
  TC-CLAMP-04  an absurd register DELTA is rejected, not clamped — and never zero
"""
from __future__ import annotations

import pytest

from app.database import _MAX_SANE_KWH_PER_SESSION, _MAX_SANE_LITERS_PER_SESSION
from app.models.pedestal_config import PedestalConfig  # noqa: F401 (table registration)
from app.models.sensor_reading import SensorReading
from app.models.session import Session
from app.models.socket_config import SocketConfig
from app.models.valve_config import ValveConfig
from app.services import meter_register as mr
from app.services.session_service import session_service
from tests.backend.conftest import TestSession

REG_BASE = 250.0
LITRE_BASE = 40.0


@pytest.fixture
def db():
    s = TestSession()
    s.query(SensorReading).delete()
    s.query(Session).delete()
    s.commit()
    yield s
    s.query(SensorReading).delete()
    s.query(Session).delete()
    s.commit()
    s.close()


def _reading(db, sid, rtype, value, unit):
    db.add(SensorReading(session_id=sid, pedestal_id=1, socket_id=1,
                         type=rtype, value=value, unit=unit))


def _set_socket_register(db, socket_id: int, value: float) -> None:
    cfg = db.query(SocketConfig).filter(
        SocketConfig.pedestal_id == 1, SocketConfig.socket_id == socket_id).first()
    if cfg is None:
        cfg = SocketConfig(pedestal_id=1, socket_id=socket_id)
        db.add(cfg)
    cfg.meter_energy_kwh = value
    db.commit()


def _set_valve_register(db, valve_id: int, value: float) -> None:
    cfg = db.query(ValveConfig).filter(
        ValveConfig.pedestal_id == 1, ValveConfig.valve_id == valve_id).first()
    if cfg is None:
        cfg = ValveConfig(pedestal_id=1, valve_id=valve_id)
        db.add(cfg)
    cfg.meter_total_l = value
    db.commit()


def _electricity_session(db, *, consumed: float, socket_id: int = 1) -> Session:
    sess = Session(pedestal_id=1, socket_id=socket_id, type="electricity", status="active",
                   meter_energy_start_kwh=REG_BASE)
    db.add(sess); db.commit(); db.refresh(sess)
    _set_socket_register(db, socket_id, REG_BASE + consumed)
    return sess


# ═══ TC-CLAMP-01 ══════════════════════════════════════════════════════════════

def test_tc_clamp_01_electricity_spike_cannot_reach_the_billed_figure(db):
    """A 9999 kWh packet is not clamped out of the total — it was never in it.

    The billed figure is the register delta. The spike lands only in the comparison figure,
    where its job is to be noticed rather than to be billed.
    """
    sess = _electricity_session(db, consumed=4.5)
    _reading(db, sess.id, "kwh_total", 4.5, "kWh")
    _reading(db, sess.id, "kwh_total", 9999.0, "kWh")
    db.commit()

    session_service.complete(db, sess)

    assert sess.energy_kwh == pytest.approx(4.5), \
        f"billed {sess.energy_kwh}; the register said 4.5 and nothing else may override it"
    assert sess.consumption_source == mr.SOURCE_REGISTER
    assert sess.meter_energy_start_kwh == REG_BASE and \
        sess.meter_energy_end_kwh == pytest.approx(REG_BASE + 4.5), \
        "both register endpoints must be stored, so a queried charge can be reconstructed"


# ═══ TC-CLAMP-02 ══════════════════════════════════════════════════════════════

def test_tc_clamp_02_water_spike_cannot_reach_the_billed_figure(db):
    """Same for water: litres come from total_l deltas, not from readings."""
    sess = Session(pedestal_id=1, socket_id=1, type="water", status="active",
                   meter_water_start_l=LITRE_BASE)
    db.add(sess); db.commit(); db.refresh(sess)
    _set_valve_register(db, 1, LITRE_BASE + 120.0)

    _reading(db, sess.id, "total_liters", 120.0, "L")
    _reading(db, sess.id, "total_liters", _MAX_SANE_LITERS_PER_SESSION + 1, "L")
    db.commit()

    session_service.complete(db, sess)

    assert sess.water_liters == pytest.approx(120.0)
    assert sess.consumption_source == mr.SOURCE_REGISTER
    # The spike is clamped out of the COMPARISON figure, which is where readings now live.
    assert sess.water_liters_firmware == pytest.approx(120.0), \
        "the corrupt reading must not survive even into the comparison figure"


# ═══ TC-CLAMP-03 ══════════════════════════════════════════════════════════════

def test_tc_clamp_03_a_legitimate_high_delta_is_billed_in_full(db):
    """No false rejection just below the ceiling — a long real session must still bill."""
    legit = _MAX_SANE_KWH_PER_SESSION - 1
    sess = _electricity_session(db, consumed=legit)

    session_service.complete(db, sess)

    assert sess.energy_kwh == pytest.approx(legit)
    assert sess.consumption_source == mr.SOURCE_REGISTER


# ═══ TC-CLAMP-04 ══════════════════════════════════════════════════════════════

def test_tc_clamp_04_an_absurd_delta_is_rejected_never_clamped_or_zeroed(db):
    """A register delta past the ceiling is a meter fault, and is refused.

    Clamping it to the ceiling would bill a fabricated number; zeroing it would claim the
    customer used nothing. Both hide a broken meter, so the figure is UNKNOWN and an alarm is
    raised for a human.
    """
    sess = _electricity_session(db, consumed=_MAX_SANE_KWH_PER_SESSION + 500)

    session_service.complete(db, sess)

    assert sess.energy_kwh is None, (
        f"got {sess.energy_kwh}: an impossible delta must not be billed at all. Neither the "
        f"ceiling nor 0.0 is an honest substitute for a reading we do not believe."
    )
    assert sess.consumption_source == mr.SOURCE_UNKNOWN
