"""Tests for v3.16 status snapshot files (status_service)."""
from __future__ import annotations

from unittest.mock import patch

from app.services import status_service
from app.models.pedestal_config import PedestalConfig
from tests.backend.conftest import TestSession


def test_build_mqtt_status_shape():
    s = status_service.build_mqtt_status()
    assert "connected" in s
    assert s["schema_version"] == 1
    assert isinstance(s["subscribed_topics"], list) and s["subscribed_topics"]
    assert "broker_host" in s and "connect_count" in s


def test_build_devices_status_lists_pedestal():
    db = TestSession()
    db.query(PedestalConfig).delete()
    db.add(PedestalConfig(pedestal_id=1, opta_client_id="MAR_TEST",
                          status="online", opta_connected=1))
    db.commit(); db.close()
    try:
        with patch.object(status_service, "SessionLocal", TestSession):
            out = status_service.build_devices_status()
    finally:
        db = TestSession(); db.query(PedestalConfig).delete(); db.commit(); db.close()

    ped = next(p for p in out["pedestals"] if p["pedestal_id"] == 1)
    assert ped["cabinet_id"] == "MAR_TEST"
    assert ped["cabinet"]["connected"] is True
    assert "camera" in ped and "sockets" in ped


def test_write_status_files(tmp_path):
    with patch.object(status_service, "SessionLocal", TestSession), \
         patch.object(status_service, "STATUS_DIR", tmp_path / "status"):
        status_service.write_status_files()
    assert (tmp_path / "status" / "mqtt_status.json").exists()
    assert (tmp_path / "status" / "devices_status.json").exists()
