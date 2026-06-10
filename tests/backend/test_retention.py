"""Tests for the v3.13 telemetry/operational-log retention purge.

Verifies that retention_service.purge_old_data():
  - deletes telemetry/operational rows older than the cutoff,
  - keeps recent rows,
  - never prunes readings tied to a still-open (pending/active) session,
  - only prunes RESOLVED meter-load alarms and ACKNOWLEDGED active alarms,
  - never touches business/legal records (sessions are preserved).

The service opens its own SessionLocal(), so we patch it to the test DB
(same pattern as test_breaker_monitoring.py patching mqtt_handlers.SessionLocal).
"""
from __future__ import annotations
from datetime import datetime, timedelta

import pytest
from unittest.mock import patch

from app.services import retention_service
from app.models.sensor_reading import SensorReading
from app.models.session import Session
from app.models.auto_activation_log import AutoActivationLog
from app.models.meter_load_alarm import MeterLoadAlarm
from app.models.active_alarm import ActiveAlarm
from tests.backend.conftest import TestSession

OLD = datetime.utcnow() - timedelta(days=10)   # older than the 7-day cutoff
NEW = datetime.utcnow() - timedelta(days=1)     # within retention

_TABLES = (SensorReading, AutoActivationLog, MeterLoadAlarm, ActiveAlarm, Session)


@pytest.fixture
def clean_tables():
    """Start each test from a clean slate on the tables under test."""
    db = TestSession()
    for model in _TABLES:
        db.query(model).delete()
    db.commit()
    yield db
    for model in _TABLES:
        db.query(model).delete()
    db.commit()
    db.close()


def _seed(db):
    """Seed a known mix of old/new rows. Returns (completed_sid, active_sid)."""
    completed = Session(pedestal_id=1, socket_id=1, type="electricity",
                        status="completed", started_at=OLD, ended_at=OLD)
    active = Session(pedestal_id=1, socket_id=2, type="electricity",
                     status="active", started_at=OLD)
    db.add_all([completed, active])
    db.commit()
    db.refresh(completed)
    db.refresh(active)

    db.add_all([
        # old reading on a completed session -> PRUNE
        SensorReading(session_id=completed.id, pedestal_id=1, socket_id=1,
                      type="kwh_total", value=1.0, unit="kWh", timestamp=OLD),
        # recent reading on a completed session -> KEEP
        SensorReading(session_id=completed.id, pedestal_id=1, socket_id=1,
                      type="kwh_total", value=2.0, unit="kWh", timestamp=NEW),
        # old reading on a still-ACTIVE session -> KEEP (open-session guard)
        SensorReading(session_id=active.id, pedestal_id=1, socket_id=2,
                      type="kwh_total", value=3.0, unit="kWh", timestamp=OLD),
        # old unattached reading (no session) -> PRUNE
        SensorReading(session_id=None, pedestal_id=1, socket_id=3,
                      type="power_watts", value=0.0, unit="W", timestamp=OLD),
    ])

    db.add_all([
        AutoActivationLog(pedestal_id=1, socket_id=1, timestamp=OLD, result="skipped", reason="old"),
        AutoActivationLog(pedestal_id=1, socket_id=1, timestamp=NEW, result="success"),
    ])

    db.add_all([
        # resolved + old -> PRUNE
        MeterLoadAlarm(pedestal_id=1, socket_id=1, alarm_type="warning", current_amps=10,
                       rated_amps=16, load_pct=62, phases=1, triggered_at=OLD, resolved_at=OLD),
        # open (unresolved) + old -> KEEP
        MeterLoadAlarm(pedestal_id=1, socket_id=2, alarm_type="critical", current_amps=15,
                       rated_amps=16, load_pct=94, phases=1, triggered_at=OLD, resolved_at=None),
        # resolved but recent -> KEEP
        MeterLoadAlarm(pedestal_id=1, socket_id=3, alarm_type="warning", current_amps=10,
                       rated_amps=16, load_pct=62, phases=1, triggered_at=NEW, resolved_at=NEW),
    ])

    db.add_all([
        # acknowledged + old -> PRUNE
        ActiveAlarm(alarm_type="temperature", source="sensor_auto", status="acknowledged",
                    message="hot", triggered_at=OLD),
        # triggered (still open) + old -> KEEP
        ActiveAlarm(alarm_type="moisture", source="sensor_auto", status="triggered",
                    message="wet", triggered_at=OLD),
        # acknowledged but recent -> KEEP
        ActiveAlarm(alarm_type="comm_loss", source="sensor_auto", status="acknowledged",
                    message="lost", triggered_at=NEW),
    ])
    db.commit()
    return completed.id, active.id


def test_purge_deletes_old_telemetry_keeps_recent_open_and_business(clean_tables):
    db = clean_tables
    completed_id, active_id = _seed(db)

    with patch.object(retention_service, "SessionLocal", TestSession):
        counts = retention_service.purge_old_data(retention_days=7)

    db.expire_all()

    # sensor_readings: old-completed + old-unattached pruned (2); recent + active-old kept (2)
    assert counts["sensor_readings"] == 2
    remaining = db.query(SensorReading).all()
    assert len(remaining) == 2
    assert all(r.timestamp == NEW or r.session_id == active_id for r in remaining)
    # the active session's old reading survived the cutoff
    assert db.query(SensorReading).filter_by(session_id=active_id).count() == 1

    # auto_activation_log: old pruned, recent kept
    assert counts["auto_activation_log"] == 1
    assert db.query(AutoActivationLog).count() == 1

    # meter_load_alarms: only resolved+old pruned (1); open-old and resolved-recent kept (2)
    assert counts["meter_load_alarms"] == 1
    assert db.query(MeterLoadAlarm).count() == 2
    assert db.query(MeterLoadAlarm).filter(MeterLoadAlarm.resolved_at.is_(None)).count() == 1

    # active_alarms: only acknowledged+old pruned (1); triggered-old and ack-recent kept (2)
    assert counts["active_alarms"] == 1
    assert db.query(ActiveAlarm).count() == 2
    assert db.query(ActiveAlarm).filter_by(status="triggered").count() == 1

    # business records: both sessions still present (never auto-deleted)
    assert db.query(Session).count() == 2
    assert db.query(Session).filter_by(id=completed_id).count() == 1


def test_purge_noop_when_everything_recent(clean_tables):
    db = clean_tables
    db.add(SensorReading(session_id=None, pedestal_id=1, socket_id=1,
                         type="power_watts", value=5.0, unit="W", timestamp=NEW))
    db.commit()

    with patch.object(retention_service, "SessionLocal", TestSession):
        counts = retention_service.purge_old_data(retention_days=7)

    assert sum(counts.values()) == 0
    assert db.query(SensorReading).count() == 1
