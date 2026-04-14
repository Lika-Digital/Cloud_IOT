"""
Direct Device Control Endpoints — Verification Tests
=====================================================

Tests cover the new direct MQTT command endpoints added alongside the
Control Center UI: direct socket commands, direct water valve commands,
LED control, and pedestal reset.

Test IDs:
  TC-DC-01  Direct socket activate → MQTT published to opta/cmd/socket/Q{n}
  TC-DC-02  Direct socket stop → MQTT published to opta/cmd/socket/Q{n}
  TC-DC-03  (removed — maintenance not supported by Opta firmware)
  TC-DC-04  Invalid socket name → 400 error
  TC-DC-05  Direct water activate → MQTT published to opta/cmd/water/V{n}
  TC-DC-06  Direct water stop → MQTT published
  TC-DC-07  Invalid water valve name → 400 error
  TC-DC-08  LED on/off/blink → MQTT published to opta/cmd/led
  TC-DC-09  LED invalid color → 422 validation error
  TC-DC-10  LED invalid state → 422 validation error
  TC-DC-11  Pedestal reset → MQTT published to opta/cmd/reset
  TC-DC-12  All direct-control endpoints require admin auth
  TC-DC-13  MQTT handlers broadcast opta_socket_status WS event
  TC-DC-14  MQTT handlers broadcast opta_water_status WS event
  TC-DC-15  MQTT handlers broadcast opta_status WS event with seq/uptime
  TC-DC-16  MQTT handlers include pedestal_id in marina_ack broadcast
"""
import asyncio
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── shared test DBs (same files as conftest) ─────────────────────────────────
TEST_DB      = "sqlite:///./tests/test_pedestal.db"
TEST_USER_DB = "sqlite:///./tests/test_users.db"

_test_engine      = create_engine(TEST_DB,      connect_args={"check_same_thread": False}, poolclass=StaticPool)
_test_user_engine = create_engine(TEST_USER_DB, connect_args={"check_same_thread": False}, poolclass=StaticPool)
_TestSession      = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)
_TestUserSession  = sessionmaker(autocommit=False, autoflush=False, bind=_test_user_engine)


@pytest.fixture(scope="session", autouse=True)
def _dispose_dc_engines():
    yield
    _test_engine.dispose()
    _test_user_engine.dispose()


# ── MQTT simulation helper ────────────────────────────────────────────────────

def _simulate_mqtt(topic: str, payload: str) -> list[dict]:
    """Run handle_message and return all WS broadcasts captured."""
    broadcasts: list[dict] = []

    async def capture_broadcast(msg):
        broadcasts.append(msg)

    from app.services.mqtt_handlers import handle_message
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", side_effect=capture_broadcast),
    ):
        asyncio.run(handle_message(topic, payload))

    return broadcasts


# ─────────────────────────────────────────────────────────────────────────────
# TC-DC-01..04  Direct socket commands
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("action", ["activate", "stop"])
def test_direct_socket_cmd_publishes_mqtt(client, auth_headers, action):
    """TC-DC-01/02  POST socket cmd → MQTT published to opta/cmd/socket/Q{n}."""
    published: list[tuple] = []

    def mock_publish(topic, payload, qos=1):
        published.append((topic, json.loads(payload)))

    with patch("app.routers.controls.mqtt_service.publish", side_effect=mock_publish):
        r = client.post(
            f"/api/controls/pedestal/1/socket/Q1/cmd",
            json={"action": action},
            headers=auth_headers,
        )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "sent"
    assert data["socket"] == "Q1"
    assert data["action"] == action

    topics = [p[0] for p in published]
    # Should publish to opta topic (no cabinet_id → legacy topic used in test env)
    assert any("Q1" in t or "socket" in t for t in topics), f"No socket MQTT publish seen in {topics}"
    payloads = [p[1] for p in published]
    assert any(p.get("action") == action for p in payloads)


def test_direct_socket_invalid_name(client, auth_headers):
    """TC-DC-04  Invalid socket name → 400."""
    with patch("app.routers.controls.mqtt_service.publish"):
        r = client.post(
            "/api/controls/pedestal/1/socket/E1/cmd",
            json={"action": "activate"},
            headers=auth_headers,
        )
    assert r.status_code == 400
    assert "Q1" in r.json()["detail"]


def test_direct_socket_invalid_action(client, auth_headers):
    """Invalid action value → 422 validation error."""
    with patch("app.routers.controls.mqtt_service.publish"):
        r = client.post(
            "/api/controls/pedestal/1/socket/Q1/cmd",
            json={"action": "blast"},
            headers=auth_headers,
        )
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# TC-DC-05..07  Direct water valve commands
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("action", ["activate", "stop"])
def test_direct_water_cmd_publishes_mqtt(client, auth_headers, action):
    """TC-DC-05/06  POST water cmd → MQTT published to opta/cmd/water/V{n}."""
    published: list[tuple] = []

    def mock_publish(topic, payload, qos=1):
        published.append((topic, json.loads(payload)))

    with patch("app.routers.controls.mqtt_service.publish", side_effect=mock_publish):
        r = client.post(
            f"/api/controls/pedestal/1/water/V1/cmd",
            json={"action": action},
            headers=auth_headers,
        )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "sent"
    assert data["valve"] == "V1"
    assert data["action"] == action

    topics = [p[0] for p in published]
    assert any("V1" in t or "water" in t for t in topics), f"No water MQTT publish seen in {topics}"
    payloads = [p[1] for p in published]
    assert any(p.get("action") == action for p in payloads)


def test_direct_water_invalid_name(client, auth_headers):
    """TC-DC-07  Invalid valve name → 400."""
    with patch("app.routers.controls.mqtt_service.publish"):
        r = client.post(
            "/api/controls/pedestal/1/water/W1/cmd",
            json={"action": "activate"},
            headers=auth_headers,
        )
    assert r.status_code == 400
    assert "V1" in r.json()["detail"]


# ─────────────────────────────────────────────────────────────────────────────
# TC-DC-08..10  LED control
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("color,state", [
    ("green", "on"),
    ("red", "blink"),
    ("blue", "off"),
    ("yellow", "on"),
    ("off", "off"),
])
def test_led_control(client, auth_headers, color, state):
    """TC-DC-08  LED command published to opta/cmd/led with correct color+state."""
    published: list[tuple] = []

    def mock_publish(topic, payload, qos=1):
        published.append((topic, json.loads(payload)))

    with patch("app.routers.controls.mqtt_service.publish", side_effect=mock_publish):
        r = client.post(
            "/api/controls/pedestal/1/led",
            json={"color": color, "state": state},
            headers=auth_headers,
        )

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["color"] == color
    assert data["state"] == state

    payloads = [p[1] for p in published]
    assert any(p.get("color") == color and p.get("state") == state for p in payloads), \
        f"LED payload not found in {payloads}"


def test_led_invalid_color(client, auth_headers):
    """TC-DC-09  Invalid LED color → 422."""
    r = client.post(
        "/api/controls/pedestal/1/led",
        json={"color": "purple", "state": "on"},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_led_invalid_state(client, auth_headers):
    """TC-DC-10  Invalid LED state → 422."""
    r = client.post(
        "/api/controls/pedestal/1/led",
        json={"color": "green", "state": "strobe"},
        headers=auth_headers,
    )
    assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# TC-DC-11  Pedestal reset
# ─────────────────────────────────────────────────────────────────────────────

def test_pedestal_reset(client, auth_headers):
    """TC-DC-11  Reset command published to opta/cmd/reset or legacy topic."""
    published: list[tuple] = []

    def mock_publish(topic, payload, qos=1):
        published.append((topic, json.loads(payload)))

    with patch("app.routers.controls.mqtt_service.publish", side_effect=mock_publish):
        r = client.post("/api/controls/pedestal/1/reset", headers=auth_headers)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "reset_sent"
    topics = [p[0] for p in published]
    assert any("reset" in t for t in topics), f"No reset topic in {topics}"


# ─────────────────────────────────────────────────────────────────────────────
# TC-DC-12  Auth enforcement
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path,method,body", [
    ("/api/controls/pedestal/1/socket/Q1/cmd", "post", {"action": "activate"}),
    ("/api/controls/pedestal/1/water/V1/cmd",  "post", {"action": "stop"}),
    ("/api/controls/pedestal/1/led",            "post", {"color": "green", "state": "on"}),
    ("/api/controls/pedestal/1/reset",          "post", {}),
])
def test_direct_controls_require_auth(client, path, method, body):
    """TC-DC-12  All direct control endpoints reject unauthenticated requests."""
    resp = getattr(client, method)(path, json=body)
    assert resp.status_code in (401, 403), f"{path} returned {resp.status_code}"


# ─────────────────────────────────────────────────────────────────────────────
# TC-DC-13  MQTT handler broadcasts opta_socket_status
# ─────────────────────────────────────────────────────────────────────────────

def test_opta_socket_status_broadcast():
    """TC-DC-13  opta/sockets/Q1/status → opta_socket_status WS event broadcast."""
    cabinet_id = "TEST_CABINET_DC"
    payload = json.dumps({
        "cabinetId": cabinet_id,
        "id": "Q1",
        "state": "active",
        "hw_status": "on",
        "session": {"customerId": "CUST1"},
        "ts": 123456,
    })

    broadcasts = _simulate_mqtt("opta/sockets/Q1/status", payload)

    # Find the opta_socket_status broadcast
    socket_events = [b for b in broadcasts if b.get("event") == "opta_socket_status"]
    assert socket_events, f"opta_socket_status not in broadcasts: {[b.get('event') for b in broadcasts]}"

    data = socket_events[0]["data"]
    assert data["socket_name"] == "Q1"
    assert data["state"] == "active"
    assert data["hw_status"] == "on"
    assert "timestamp" in data


# ─────────────────────────────────────────────────────────────────────────────
# TC-DC-14  MQTT handler broadcasts opta_water_status
# ─────────────────────────────────────────────────────────────────────────────

def test_opta_water_status_broadcast():
    """TC-DC-14  opta/water/V1/status → opta_water_status WS event broadcast."""
    cabinet_id = "TEST_CABINET_DC"
    payload = json.dumps({
        "cabinetId": cabinet_id,
        "id": "V1",
        "state": "active",
        "hw_status": "on",
        "total_l": 12.5,
        "session_l": 3.2,
        "ts": 123456,
    })

    broadcasts = _simulate_mqtt("opta/water/V1/status", payload)

    water_events = [b for b in broadcasts if b.get("event") == "opta_water_status"]
    assert water_events, f"opta_water_status not in broadcasts: {[b.get('event') for b in broadcasts]}"

    data = water_events[0]["data"]
    assert data["valve_name"] == "V1"
    assert data["state"] == "active"
    assert data["total_l"] == 12.5
    assert data["session_l"] == 3.2


# ─────────────────────────────────────────────────────────────────────────────
# TC-DC-15  MQTT handler broadcasts opta_status with seq/uptime
# ─────────────────────────────────────────────────────────────────────────────

def test_opta_status_broadcast():
    """TC-DC-15  opta/status → opta_status WS event with seq, uptime_ms, door."""
    cabinet_id = "TEST_CABINET_DC"
    payload = json.dumps({
        "cabinetId": cabinet_id,
        "seq": 42,
        "uptime_ms": 300000,
        "door": "closed",
    })

    broadcasts = _simulate_mqtt("opta/status", payload)

    status_events = [b for b in broadcasts if b.get("event") == "opta_status"]
    assert status_events, f"opta_status not in broadcasts: {[b.get('event') for b in broadcasts]}"

    data = status_events[0]["data"]
    assert data["seq"] == 42
    assert data["uptime_ms"] == 300000
    assert data["door"] == "closed"
    assert data["cabinet_id"] == cabinet_id


# ─────────────────────────────────────────────────────────────────────────────
# TC-DC-16  marina_ack broadcast includes pedestal_id
# ─────────────────────────────────────────────────────────────────────────────

def test_marina_ack_includes_pedestal_id():
    """TC-DC-16  opta/acks → marina_ack WS event includes pedestal_id field."""
    cabinet_id = "TEST_CABINET_DC"
    payload = json.dumps({
        "cabinetId": cabinet_id,
        "cmd_topic": "opta/cmd/socket/Q1",
        "status": "ok",
        "ts": 123456,
    })

    broadcasts = _simulate_mqtt("opta/acks", payload)

    ack_events = [b for b in broadcasts if b.get("event") == "marina_ack"]
    assert ack_events, f"marina_ack not in broadcasts: {[b.get('event') for b in broadcasts]}"

    data = ack_events[0]["data"]
    assert "pedestal_id" in data, "pedestal_id missing from marina_ack broadcast"
    assert data["cabinet_id"] == cabinet_id
