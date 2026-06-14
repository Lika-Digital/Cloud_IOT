"""v3.23 — Temperature range alarms for the Papouch TME sensor.

Covers:
  * temp_alarm.evaluate_temp_band — pure band logic incl. clearing hysteresis.
  * alarm_service — severity storage, in-place escalate (no duplicate), and
    resolve_alarm_type / has_active_alarm auto-clear.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.temp_alarm import (
    evaluate_temp_band, threshold_for,
    HIGH_WARN_C, HIGH_CRIT_C, LOW_WARN_C, LOW_CRIT_C,
)


# ── Band logic (pure) ────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (25.0,  (None, None)),
    (44.9,  (None, None)),
    (45.0,  ("warning", "high")),
    (59.9,  ("warning", "high")),
    (60.0,  ("critical", "high")),
    (75.0,  ("critical", "high")),
    (0.0,   ("warning", "low")),
    (-0.1,  ("warning", "low")),
    (-9.9,  ("warning", "low")),
    (-10.0, ("critical", "low")),
    (-20.0, ("critical", "low")),
])
def test_band_inactive(value, expected):
    assert evaluate_temp_band(value, currently_active=False) == expected


def test_hysteresis_holds_high_warning_near_boundary():
    # Active warning at 45 stays until comfortably below (45 - 1).
    assert evaluate_temp_band(44.5, currently_active=True) == ("warning", "high")
    assert evaluate_temp_band(43.9, currently_active=True) == (None, None)


def test_hysteresis_holds_low_warning_near_boundary():
    assert evaluate_temp_band(0.5, currently_active=True) == ("warning", "low")
    assert evaluate_temp_band(1.5, currently_active=True) == (None, None)


def test_hysteresis_escalation_to_critical():
    assert evaluate_temp_band(59.5, currently_active=True) == ("critical", "high")


def test_threshold_for():
    assert threshold_for("warning", "high") == HIGH_WARN_C == 45.0
    assert threshold_for("critical", "high") == HIGH_CRIT_C == 60.0
    assert threshold_for("warning", "low") == LOW_WARN_C == 0.0
    assert threshold_for("critical", "low") == LOW_CRIT_C == -10.0


# ── alarm_service severity / escalate / resolve (DB) ─────────────────────────

_engine = create_engine(
    "sqlite:///./tests/test_alarm.db",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
from app.database import Base  # noqa: E402
from app.models.active_alarm import ActiveAlarm as _AA  # noqa: E402,F401 — register table before create_all
Base.metadata.create_all(bind=_engine)
_TS = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture(scope="module", autouse=True)
def _dispose_engine():
    yield
    _engine.dispose()
    try:
        os.remove("tests/test_alarm.db")
    except OSError:
        pass


@pytest.fixture(autouse=True)
def _clean_alarms():
    from app.models.active_alarm import ActiveAlarm
    db = _TS()
    try:
        db.query(ActiveAlarm).delete()
        db.commit()
    finally:
        db.close()
    yield


def _count_triggered(pid: int) -> int:
    from app.models.active_alarm import ActiveAlarm
    db = _TS()
    try:
        return db.query(ActiveAlarm).filter_by(pedestal_id=pid, status="triggered").count()
    finally:
        db.close()


def test_trigger_alarm_stores_severity():
    with patch("app.services.alarm_service.SessionLocal", _TS):
        from app.services.alarm_service import trigger_alarm
        a = trigger_alarm("temperature", "sensor_auto", "warn", pedestal_id=10, severity="warning")
    assert a is not None
    assert a.severity == "warning"
    assert _count_triggered(10) == 1


def test_trigger_escalates_in_place_no_duplicate():
    from app.models.active_alarm import ActiveAlarm
    with patch("app.services.alarm_service.SessionLocal", _TS):
        from app.services.alarm_service import trigger_alarm
        a1 = trigger_alarm("temperature", "sensor_auto", "warn", pedestal_id=11, severity="warning")
        a2 = trigger_alarm("temperature", "sensor_auto", "crit", pedestal_id=11, severity="critical")
    assert a1.id == a2.id           # same row updated, not a new one
    assert _count_triggered(11) == 1
    db = _TS()
    try:
        assert db.get(ActiveAlarm, a1.id).severity == "critical"
    finally:
        db.close()


def test_resolve_alarm_type_clears_and_sets_resolved():
    from app.models.active_alarm import ActiveAlarm
    with patch("app.services.alarm_service.SessionLocal", _TS):
        from app.services.alarm_service import trigger_alarm, resolve_alarm_type, has_active_alarm
        trigger_alarm("temperature", "sensor_auto", "warn", pedestal_id=12, severity="warning")
        assert has_active_alarm("temperature", 12) is True
        n = resolve_alarm_type("temperature", 12)
        assert n == 1
        assert has_active_alarm("temperature", 12) is False
    db = _TS()
    try:
        row = db.query(ActiveAlarm).filter_by(pedestal_id=12).first()
        assert row.status == "resolved"
        assert row.resolved_at is not None
    finally:
        db.close()


def test_resolve_is_noop_when_nothing_active():
    with patch("app.services.alarm_service.SessionLocal", _TS):
        from app.services.alarm_service import resolve_alarm_type
        assert resolve_alarm_type("temperature", 999) == 0
