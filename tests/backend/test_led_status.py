"""ACK-confirmed LED status (v3.27).

POST /led marks the intended state PENDING (on a real cabinet); the firmware ACK
on opta/cmd/led flips it to confirmed. Single-colour LED → only on/off matters.
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, AsyncMock

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

CAB = "TST_LED_CAB"


@pytest.fixture(scope="module")
def led_pid(client, auth_headers):
    r = client.post("/api/pedestals/", json={
        "name": "LED Pedestal", "location": "Dock", "data_mode": "real",
    }, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    from app.models.pedestal_config import PedestalConfig
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid); db.add(cfg)
        cfg.opta_client_id = CAB
        db.commit()
    finally:
        db.close()
    return pid


def _led_row(pid):
    from app.models.pedestal_config import PedestalConfig
    db = _S()
    try:
        return db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
    finally:
        db.close()


def test_led_command_marks_pending(client, auth_headers, led_pid):
    with patch("app.services.mqtt_client.mqtt_service.publish"):
        r = client.post(f"/api/controls/pedestal/{led_pid}/led", headers=auth_headers,
                        json={"color": "green", "state": "on"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["on"] is True and body["pending"] is True   # cabinet → awaits ACK
    g = client.get(f"/api/controls/pedestal/{led_pid}/led", headers=auth_headers).json()
    assert g["on"] is True and g["pending"] is True and g["confirmed_at"] is None


def test_led_ack_confirms_state(client, auth_headers, led_pid):
    # Send the command (sets pending), then simulate the firmware ACK.
    with patch("app.services.mqtt_client.mqtt_service.publish"):
        client.post(f"/api/controls/pedestal/{led_pid}/led", headers=auth_headers,
                    json={"color": "green", "state": "on"})

    from app.services.mqtt_handlers import _handle_marina_acks
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _S),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
    ):
        asyncio.run(_handle_marina_acks(CAB, '{"cmd_topic":"opta/cmd/led","status":"ok","ts":1}'))

    row = _led_row(led_pid)
    assert row.led_pending is False
    assert row.led_confirmed_at is not None
    assert row.led_on is True

    g = client.get(f"/api/controls/pedestal/{led_pid}/led", headers=auth_headers).json()
    assert g["on"] is True and g["pending"] is False and g["confirmed_at"] is not None


def test_led_off_command_then_ack(client, auth_headers, led_pid):
    with patch("app.services.mqtt_client.mqtt_service.publish"):
        client.post(f"/api/controls/pedestal/{led_pid}/led", headers=auth_headers,
                    json={"color": "off", "state": "off"})
    from app.services.mqtt_handlers import _handle_marina_acks
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _S),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
    ):
        asyncio.run(_handle_marina_acks(CAB, '{"cmd_topic":"opta/cmd/led","status":"ok"}'))
    row = _led_row(led_pid)
    assert row.led_on is False and row.led_pending is False


def test_led_ack_failure_clears_pending_without_confirm(client, auth_headers, led_pid):
    with patch("app.services.mqtt_client.mqtt_service.publish"):
        client.post(f"/api/controls/pedestal/{led_pid}/led", headers=auth_headers,
                    json={"color": "green", "state": "on"})
    # Wipe confirmed timestamp to detect that a failed ACK does NOT re-stamp it.
    from app.models.pedestal_config import PedestalConfig
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == led_pid).first()
        cfg.led_confirmed_at = None
        db.commit()
    finally:
        db.close()
    from app.services.mqtt_handlers import _handle_marina_acks
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _S),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
    ):
        asyncio.run(_handle_marina_acks(CAB, '{"cmd_topic":"opta/cmd/led","status":"error"}'))
    row = _led_row(led_pid)
    assert row.led_pending is False and row.led_confirmed_at is None
