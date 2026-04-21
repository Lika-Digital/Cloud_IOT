"""
Socket Plug State Machine — Verification Tests
==============================================

Coverage for the UserPluggedIn / UserPluggedOut flow and the unified
socket_state_changed WebSocket event.

State flow under test:
  idle     → UserPluggedIn            → pending
  pending  → activate cmd             → active
  active   → UserPluggedOut mid-session → stop cmd + session completed + idle
  active   → stop cmd                 → pending (plug still in) | idle (removed)
  pending  → UserPluggedOut           → idle
  idle     → activate cmd (no plug)   → HTTP 409 "Socket has no plug inserted"

Test IDs:
  TC-SP-01  UserPluggedIn → SocketState.connected=True + socket_state_changed=pending
  TC-SP-02  activate accepted when SocketState.connected=True
  TC-SP-03  activate rejected 409 "Socket has no plug inserted" when connected=False
  TC-SP-04  UserPluggedOut → connected=False + socket_state_changed=idle
  TC-SP-05  UserPluggedOut during active session → stop published + session completed + idle broadcast
  TC-SP-06  SessionEnded with plug still in → socket_state_changed=pending
  TC-SP-07  SessionEnded with plug removed  → socket_state_changed=idle
"""
from __future__ import annotations
import asyncio
import json
import pytest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_test_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False}, poolclass=StaticPool)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


@pytest.fixture(scope="module", autouse=True)
def _dispose_engine():
    yield
    _test_engine.dispose()


def _simulate_opta_event(event_type: str, outlet_id: str, resource: str = "POWER", totals: dict | None = None) -> list[dict]:
    """Inject an opta/events message and capture WS broadcasts."""
    broadcasts: list[dict] = []

    async def capture_broadcast(msg):
        broadcasts.append(msg)

    payload = {
        "eventType": event_type,
        "device": {
            "cabinetId": "TEST_CABINET",
            "outletId": outlet_id,
            "resource": resource,
            "berthId": "VEZ_A1",
        },
    }
    if totals is not None:
        payload["totals"] = totals

    from app.services.mqtt_handlers import handle_message
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", side_effect=capture_broadcast),
    ):
        asyncio.run(handle_message("opta/events", json.dumps(payload)))

    return broadcasts


def _events_of(broadcasts: list[dict], event_name: str) -> list[dict]:
    return [b for b in broadcasts if b.get("event") == event_name]


def _seed_connected(pedestal_id: int, socket_id: int, connected: bool) -> None:
    from app.models.pedestal_config import SocketState
    db = _TestSession()
    try:
        row = db.query(SocketState).filter_by(pedestal_id=pedestal_id, socket_id=socket_id).first()
        if row:
            row.connected = connected
        else:
            db.add(SocketState(pedestal_id=pedestal_id, socket_id=socket_id, connected=connected))
        db.commit()
    finally:
        db.close()


def _pedestal_id_for_cabinet(cabinet_id: str = "TEST_CABINET") -> int:
    """Return the numeric pedestal_id that the MQTT handler resolves cabinet_id to.
    The first event for an unknown cabinet auto-creates a Pedestal row, so
    tests that simulate events need the resulting id for seeding state rows."""
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(opta_client_id=cabinet_id).first()
        return cfg.pedestal_id if cfg else 0
    finally:
        db.close()


@pytest.fixture
def clean_state():
    """Clear sockets + sessions so each test starts from a blank state."""
    from app.models.pedestal_config import SocketState
    from app.models.session import Session
    db = _TestSession()
    try:
        db.query(SocketState).delete()
        db.query(Session).delete()
        db.commit()
        yield
    finally:
        db.close()


# ── TC-SP-01 ─────────────────────────────────────────────────────────────────

def test_user_plugged_in_sets_pending_and_broadcasts(clean_state):
    broadcasts = _simulate_opta_event("UserPluggedIn", "Q1")
    pid = _pedestal_id_for_cabinet()

    from app.models.pedestal_config import SocketState
    db = _TestSession()
    try:
        state = db.query(SocketState).filter_by(pedestal_id=pid, socket_id=1).first()
        assert state is not None and state.connected is True, "SocketState.connected should be True"
    finally:
        db.close()

    ssc = _events_of(broadcasts, "socket_state_changed")
    assert ssc, "socket_state_changed event not broadcast"
    assert ssc[-1]["data"]["state"] == "pending"
    assert ssc[-1]["data"]["socket_id"] == 1
    assert ssc[-1]["data"]["pedestal_id"] == pid


# ── TC-SP-02 ─────────────────────────────────────────────────────────────────

def test_activate_accepted_when_plug_inserted(client, auth_headers, clean_state):
    _seed_connected(1, 1, True)
    with patch("app.routers.controls.mqtt_service.publish"):
        r = client.post(
            "/api/controls/pedestal/1/socket/Q1/cmd",
            json={"action": "activate"},
            headers=auth_headers,
        )
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "activate"


# ── TC-SP-03 ─────────────────────────────────────────────────────────────────

def test_activate_rejected_when_no_plug(client, auth_headers, clean_state):
    _seed_connected(1, 1, False)
    with patch("app.routers.controls.mqtt_service.publish") as pub:
        r = client.post(
            "/api/controls/pedestal/1/socket/Q1/cmd",
            json={"action": "activate"},
            headers=auth_headers,
        )
    assert r.status_code == 409, r.text
    assert "plug" in r.json()["detail"].lower()
    assert pub.call_count == 0, "Must not publish MQTT when plug is missing"


def test_activate_rejected_when_socket_state_missing(client, auth_headers, clean_state):
    # No SocketState row at all → treat as not inserted.
    with patch("app.routers.controls.mqtt_service.publish") as pub:
        r = client.post(
            "/api/controls/pedestal/1/socket/Q2/cmd",
            json={"action": "activate"},
            headers=auth_headers,
        )
    assert r.status_code == 409
    assert pub.call_count == 0


# ── TC-SP-04 ─────────────────────────────────────────────────────────────────

def test_user_plugged_out_sets_idle_and_broadcasts(clean_state):
    # Plug in first so the cabinet is auto-registered and SocketState exists.
    _simulate_opta_event("UserPluggedIn", "Q1")
    pid = _pedestal_id_for_cabinet()

    broadcasts = _simulate_opta_event("UserPluggedOut", "Q1")

    from app.models.pedestal_config import SocketState
    db = _TestSession()
    try:
        state = db.query(SocketState).filter_by(pedestal_id=pid, socket_id=1).first()
        assert state is not None and state.connected is False
    finally:
        db.close()

    ssc = _events_of(broadcasts, "socket_state_changed")
    assert ssc and ssc[-1]["data"]["state"] == "idle"


# ── TC-SP-05 ─────────────────────────────────────────────────────────────────

def test_user_plugged_out_during_active_session_stops_and_completes(clean_state):
    # Arrange: plug in, activate → session exists, connected=True
    _simulate_opta_event("UserPluggedIn", "Q1")
    _simulate_opta_event("OutletActivated", "Q1")
    pid = _pedestal_id_for_cabinet()

    from app.models.session import Session
    db = _TestSession()
    try:
        active = db.query(Session).filter_by(pedestal_id=pid, socket_id=1, type="electricity", status="active").first()
        assert active is not None, "Setup failed — expected active session"
        active_session_id = active.id
    finally:
        db.close()

    # Capture MQTT publishes during UserPluggedOut.
    # `mqtt_service` is imported lazily inside the handler, so patch the
    # canonical singleton on the mqtt_client module.
    published: list[tuple] = []
    with patch("app.services.mqtt_client.mqtt_service.publish", side_effect=lambda t, p, qos=1: published.append((t, json.loads(p)))):
        broadcasts = _simulate_opta_event("UserPluggedOut", "Q1")

    # The stop command must have been published.
    topics = [t for (t, _p) in published]
    assert any("opta/cmd/socket/Q1" in t for t in topics), f"Expected stop publish to opta/cmd/socket/Q1, got {topics}"
    payloads = [p for (_t, p) in published]
    assert any(pl.get("action") == "stop" for pl in payloads)

    # Session must be completed.
    db = _TestSession()
    try:
        s = db.query(Session).filter_by(id=active_session_id).first()
        assert s.status == "completed"
    finally:
        db.close()

    # State broadcast must be idle.
    ssc = _events_of(broadcasts, "socket_state_changed")
    assert ssc and ssc[-1]["data"]["state"] == "idle"


# ── TC-SP-06 ─────────────────────────────────────────────────────────────────

def test_session_ended_with_plug_still_in_broadcasts_pending(clean_state):
    _simulate_opta_event("UserPluggedIn", "Q1")
    _simulate_opta_event("OutletActivated", "Q1")
    # Plug stays in, firmware finishes the session on its own.
    broadcasts = _simulate_opta_event("SessionEnded", "Q1", totals={"energyKwh": 0.042, "durationMinutes": 1})

    ssc = _events_of(broadcasts, "socket_state_changed")
    assert ssc, "No socket_state_changed emitted after SessionEnded"
    assert ssc[-1]["data"]["state"] == "pending", (
        f"Plug still in after SessionEnded must leave state=pending, got {ssc[-1]['data']['state']}"
    )


# ── TC-SP-07 ─────────────────────────────────────────────────────────────────

def test_session_ended_with_plug_removed_broadcasts_idle(clean_state):
    _simulate_opta_event("UserPluggedIn", "Q1")
    _simulate_opta_event("OutletActivated", "Q1")
    pid = _pedestal_id_for_cabinet()
    # Plug is removed BEFORE the firmware emits SessionEnded.
    _seed_connected(pid, 1, False)
    broadcasts = _simulate_opta_event("SessionEnded", "Q1", totals={"energyKwh": 0.01, "durationMinutes": 0})

    ssc = _events_of(broadcasts, "socket_state_changed")
    assert ssc and ssc[-1]["data"]["state"] == "idle"
