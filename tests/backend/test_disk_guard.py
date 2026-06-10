"""Tests for the v3.13 disk-space write guard + clear-cache action.

Covers:
  - disk_guard.has_free_space() flips on the MIN_FREE_BYTES threshold,
  - session_service.add_reading() refuses to store (returns None) when the disk
    is nearly full, instead of inserting,
  - the admin GET /api/system/cache and POST /api/system/cache/clear endpoints.
"""
from __future__ import annotations
from collections import namedtuple

import pytest
from unittest.mock import patch

from app.services import disk_guard
from app.services.session_service import session_service
from app.models.sensor_reading import SensorReading
from tests.backend.conftest import TestSession

_Usage = namedtuple("Usage", "total used free")


@pytest.fixture(autouse=True)
def reset_disk_cache():
    disk_guard.invalidate()
    yield
    disk_guard.invalidate()


@pytest.fixture
def clean_readings():
    db = TestSession()
    db.query(SensorReading).delete()
    db.commit()
    yield db
    db.query(SensorReading).delete()
    db.commit()
    db.close()


def _usage(free_mb):
    total = 10 * 1024 * 1024 * 1024  # 10 GB
    free = free_mb * 1024 * 1024
    return _Usage(total=total, used=total - free, free=free)


def test_has_free_space_true_when_plenty(monkeypatch):
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda p: _usage(2000))  # 2 GB free
    disk_guard.invalidate()
    assert disk_guard.has_free_space() is True
    assert disk_guard.disk_status()["low_space"] is False


def test_has_free_space_false_below_threshold(monkeypatch):
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", lambda p: _usage(100))  # 100 MB < 500 MB
    disk_guard.invalidate()
    assert disk_guard.has_free_space() is False
    assert disk_guard.disk_status()["low_space"] is True


def test_disk_measure_failure_fails_open(monkeypatch):
    def boom(p):
        raise OSError("cannot stat")
    monkeypatch.setattr(disk_guard.shutil, "disk_usage", boom)
    disk_guard.invalidate()
    # If we cannot measure the disk we must NOT block writes.
    assert disk_guard.has_free_space() is True


def test_add_reading_skips_when_disk_full(clean_readings):
    db = clean_readings
    with (
        patch("app.services.disk_guard.has_free_space", return_value=False),
        patch("app.services.disk_guard.note_storage_full") as note,
    ):
        result = session_service.add_reading(db, None, 1, 1, "power_watts", 5.0, "W")
    assert result is None
    assert db.query(SensorReading).count() == 0
    note.assert_called_once()


def test_add_reading_stores_when_disk_ok(clean_readings):
    db = clean_readings
    with patch("app.services.disk_guard.has_free_space", return_value=True):
        result = session_service.add_reading(db, None, 1, 1, "power_watts", 5.0, "W")
    assert result is not None
    assert db.query(SensorReading).count() == 1


def test_cache_status_endpoint(client, auth_headers):
    r = client.get("/api/system/cache", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "sensor_readings" in body
    assert "low_space" in body
    assert "disk_free_mb" in body


def test_clear_cache_endpoint(client, auth_headers, clean_readings):
    db = clean_readings
    db.add_all([
        SensorReading(session_id=None, pedestal_id=1, socket_id=1,
                      type="power_watts", value=1.0, unit="W"),
        SensorReading(session_id=None, pedestal_id=1, socket_id=2,
                      type="power_watts", value=2.0, unit="W"),
    ])
    db.commit()
    assert db.query(SensorReading).count() == 2

    r = client.post("/api/system/cache/clear", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["deleted"] == 2

    db.expire_all()
    assert db.query(SensorReading).count() == 0


def test_clear_cache_requires_admin(client):
    r = client.post("/api/system/cache/clear")
    assert r.status_code in (401, 403)
