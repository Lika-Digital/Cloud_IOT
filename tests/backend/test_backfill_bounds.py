"""
Regression guard for H-3: the startup backfill of session energy/water totals
must not adopt an out-of-bounds sensor reading as truth.

Scenario: a firmware glitch puts a single 99_999 kWh reading in the table.
Before the bounds fix, startup would write that as the session's energy_kwh.
After the fix, the reading is excluded from MAX() and the session stays at 0.
"""
from __future__ import annotations
import logging
import pytest

from app.database import _backfill_session_totals
from app.models.session import Session
from app.models.sensor_reading import SensorReading
from tests.backend.conftest import TestSession, test_engine


def _seed_session_and_reading(
    db,
    type_: str,
    reading_type: str,
    reading_value: float,
    energy_kwh: float | None = 0,
    water_liters: float | None = 0,
) -> int:
    s = Session(
        pedestal_id=1,
        socket_id=1,
        type=type_,
        status="completed",
        energy_kwh=energy_kwh,
        water_liters=water_liters,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    r = SensorReading(
        session_id=s.id,
        pedestal_id=1,
        socket_id=1,
        type=reading_type,
        value=reading_value,
        unit="kWh" if reading_type == "kwh_total" else "L",
    )
    db.add(r)
    db.commit()
    return s.id


@pytest.fixture
def clean_session_tables():
    """Clear sessions + sensor_readings so each test starts fresh."""
    db = TestSession()
    try:
        db.query(SensorReading).delete()
        db.query(Session).delete()
        db.commit()
        yield db
    finally:
        db.rollback()
        db.query(SensorReading).delete()
        db.query(Session).delete()
        db.commit()
        db.close()


def test_backfill_skips_out_of_bounds_electricity(clean_session_tables):
    """A 99_999 kWh reading must NOT be adopted — session stays at 0."""
    db = clean_session_tables
    sid = _seed_session_and_reading(db, "electricity", "kwh_total", 99_999.0)
    _backfill_session_totals(logging.getLogger("test"), db_engine=test_engine)
    db.expire_all()
    session = db.get(Session, sid)
    assert session.energy_kwh in (0, None), (
        f"Backfill adopted out-of-bounds reading 99_999 kWh; got {session.energy_kwh}"
    )


def test_backfill_skips_out_of_bounds_water(clean_session_tables):
    """A 999_999 L reading must NOT be adopted — session stays at 0."""
    db = clean_session_tables
    sid = _seed_session_and_reading(db, "water", "total_liters", 999_999.0)
    _backfill_session_totals(logging.getLogger("test"), db_engine=test_engine)
    db.expire_all()
    session = db.get(Session, sid)
    assert session.water_liters in (0, None), (
        f"Backfill adopted out-of-bounds reading 999_999 L; got {session.water_liters}"
    )


def test_backfill_accepts_normal_reading(clean_session_tables):
    """A plausible 12.5 kWh reading gets adopted."""
    db = clean_session_tables
    sid = _seed_session_and_reading(db, "electricity", "kwh_total", 12.5)
    _backfill_session_totals(logging.getLogger("test"), db_engine=test_engine)
    db.expire_all()
    session = db.get(Session, sid)
    assert session.energy_kwh == 12.5, (
        f"Backfill failed to adopt normal reading 12.5; got {session.energy_kwh}"
    )
