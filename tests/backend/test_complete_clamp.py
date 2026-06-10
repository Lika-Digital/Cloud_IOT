"""Regression guard for v3.14 over-bill clamp in session_service.complete().

A single corrupt telemetry packet (e.g. a 9999 kWh / 99999 L spike) must NOT
become the billed total. complete() clamps readings to the same sanity bounds
the startup backfill uses, then takes max() of the survivors.
"""
from __future__ import annotations

import pytest
from app.services.session_service import session_service
from app.models.session import Session
from app.models.sensor_reading import SensorReading
from app.database import _MAX_SANE_KWH_PER_SESSION, _MAX_SANE_LITERS_PER_SESSION
from tests.backend.conftest import TestSession


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


def test_electricity_spike_excluded_from_billing(db):
    sess = Session(pedestal_id=1, socket_id=1, type="electricity", status="active")
    db.add(sess); db.commit(); db.refresh(sess)
    _reading(db, sess.id, "kwh_total", 4.5, "kWh")          # legit
    _reading(db, sess.id, "kwh_total", 9999.0, "kWh")        # corrupt spike
    db.commit()

    session_service.complete(db, sess)
    assert sess.energy_kwh == 4.5  # spike clamped, not 9999


def test_water_spike_excluded_from_billing(db):
    sess = Session(pedestal_id=1, socket_id=None, type="water", status="active")
    db.add(sess); db.commit(); db.refresh(sess)
    _reading(db, sess.id, "total_liters", 120.0, "L")        # legit
    _reading(db, sess.id, "total_liters", _MAX_SANE_LITERS_PER_SESSION + 1, "L")  # spike
    db.commit()

    session_service.complete(db, sess)
    assert sess.water_liters == 120.0


def test_legitimate_high_value_still_billed(db):
    """A real total just under the bound is billed normally (no false clamp)."""
    sess = Session(pedestal_id=1, socket_id=1, type="electricity", status="active")
    db.add(sess); db.commit(); db.refresh(sess)
    legit = _MAX_SANE_KWH_PER_SESSION - 1
    _reading(db, sess.id, "kwh_total", legit, "kWh")
    db.commit()

    session_service.complete(db, sess)
    assert sess.energy_kwh == legit
