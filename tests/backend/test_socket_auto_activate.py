"""
Socket Auto-Activation — Verification Tests (v3.5)
===================================================

Covers the per-socket `auto_activate` flag and the 5-step precondition check
that gates `_maybe_auto_activate`. Reuses the same MQTT event simulator
pattern as tests/backend/test_socket_plug_state_machine.py.

Happy path:
  TC-AA-01  Default auto_activate is False for every socket on GET.
  TC-AA-02  PATCH updates auto_activate; admin only (non-admin → 403).
  TC-AA-03  auto_activate=False + UserPluggedIn → NO activate publish.
  TC-AA-04  auto_activate=True + all preconditions ok → activate publish after ~2s, success row.

Skip paths (each must: NOT publish + broadcast socket_auto_activate_skipped +
log a skipped row with the right reason):
  TC-AA-05  door=open
  TC-AA-06  active fault exists for any socket on the pedestal
  TC-AA-07  heartbeat stale (>300s)
  TC-AA-08  socket already has an active session
  TC-AA-09  diagnostic fired within the last 60s

Observability:
  TC-AA-10  GET auto-activate-log returns at most 20 rows, newest-first.
  TC-AA-11  `socket_auto_activate_skipped` WS payload shape.
"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime, timedelta
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


# ── Test helpers ─────────────────────────────────────────────────────────────

def _pedestal_id_for_cabinet(cabinet_id: str = "TEST_CABINET_AA") -> int:
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(opta_client_id=cabinet_id).first()
        return cfg.pedestal_id if cfg else 0
    finally:
        db.close()


def _set_door(pid: int, door: str) -> None:
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(pedestal_id=pid).first()
        if cfg:
            cfg.door_state = door
            db.commit()
    finally:
        db.close()


def _set_auto_activate(pid: int, sid: int, value: bool) -> None:
    from app.models.socket_config import SocketConfig
    db = _TestSession()
    try:
        row = db.query(SocketConfig).filter_by(pedestal_id=pid, socket_id=sid).first()
        if row:
            row.auto_activate = value
        else:
            db.add(SocketConfig(pedestal_id=pid, socket_id=sid, auto_activate=value))
        db.commit()
    finally:
        db.close()


def _refresh_heartbeat(pid: int) -> None:
    from app.services.mqtt_handlers import last_heartbeat
    last_heartbeat[pid] = datetime.utcnow()


@pytest.fixture
def clean_state():
    """Reset the tables that auto-activate interacts with.

    The simulator-driven tests share `_test_engine` with the plug-state-machine
    suite — clearing on entry keeps test order independent.
    """
    from app.models.pedestal_config import SocketState
    from app.models.session import Session as SessionModel
    from app.models.socket_config import SocketConfig
    from app.models.auto_activation_log import AutoActivationLog
    from app.services.mqtt_handlers import socket_fault_state, last_heartbeat, last_diagnostic_at
    db = _TestSession()
    try:
        db.query(SessionModel).delete()
        db.query(SocketState).delete()
        db.query(SocketConfig).delete()
        db.query(AutoActivationLog).delete()
        db.commit()
    finally:
        db.close()
    socket_fault_state.clear()
    last_heartbeat.clear()
    last_diagnostic_at.clear()
    yield


async def _fire_user_plugged_in_capture(cabinet_id: str = "TEST_CABINET_AA", outlet: str = "Q1"):
    """Invoke the real mqtt_handlers event dispatcher with a UserPluggedIn
    payload and capture every WS broadcast + MQTT publish that happens
    inside the coroutine tree (including the 2-second delayed path)."""
    broadcasts: list[dict] = []
    publishes: list[tuple] = []

    async def capture_broadcast(msg):
        broadcasts.append(msg)

    def capture_publish(topic, payload, qos=1):
        publishes.append((topic, json.loads(payload)))

    payload = {
        "eventType": "UserPluggedIn",
        "device": {
            "cabinetId": cabinet_id,
            "outletId": outlet,
            "resource": "POWER",
            "berthId": "VEZ_A1",
        },
    }

    from app.services.mqtt_handlers import handle_message
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", side_effect=capture_broadcast),
        # `mqtt_service` is imported lazily inside _maybe_auto_activate so we
        # patch the canonical singleton on the mqtt_client module.
        patch("app.services.mqtt_client.mqtt_service.publish", side_effect=capture_publish),
    ):
        await handle_message("opta/events", json.dumps(payload))
        # Let the fire-and-forget _maybe_auto_activate task complete, including
        # the 2-second stabilisation sleep. Cap at 3s so a hung task still fails
        # this test rather than hanging forever.
        for _ in range(30):
            await asyncio.sleep(0.1)
            if any(b.get("event") in ("socket_auto_activate_skipped",) for b in broadcasts):
                break
            if any("opta/cmd/socket/" in t for (t, _p) in publishes):
                break

    return broadcasts, publishes


def _events_of(broadcasts: list[dict], event: str) -> list[dict]:
    return [b for b in broadcasts if b.get("event") == event]


# ═════════════════════════════════════════════════════════════════════════════
# Happy path / API surface
# ═════════════════════════════════════════════════════════════════════════════

def test_default_auto_activate_is_false(client, auth_headers, clean_state):
    """TC-AA-01"""
    # Create the pedestal indirectly via a plug event so the config rows exist.
    asyncio.run(_fire_user_plugged_in_capture(outlet="Q1"))
    pid = _pedestal_id_for_cabinet()
    r = client.get(f"/api/pedestals/{pid}/sockets/config", headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 4
    assert all(row["auto_activate"] is False for row in rows)
    assert sorted(row["socket_id"] for row in rows) == [1, 2, 3, 4]


def test_patch_updates_and_requires_admin(client, auth_headers, cust_headers, clean_state):
    """TC-AA-02"""
    asyncio.run(_fire_user_plugged_in_capture(outlet="Q1"))
    pid = _pedestal_id_for_cabinet()

    # Non-admin (customer token) — 403 forbidden.
    r = client.patch(
        f"/api/pedestals/{pid}/sockets/2/config",
        json={"auto_activate": True},
        headers=cust_headers,
    )
    assert r.status_code in (401, 403)

    # Admin — 200, and the new value is returned and persisted.
    r = client.patch(
        f"/api/pedestals/{pid}/sockets/2/config",
        json={"auto_activate": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"socket_id": 2, "auto_activate": True}

    r = client.get(f"/api/pedestals/{pid}/sockets/config", headers=auth_headers)
    sock2 = next(row for row in r.json() if row["socket_id"] == 2)
    assert sock2["auto_activate"] is True


# ═════════════════════════════════════════════════════════════════════════════
# Behavioural tests — the 5 precondition checks + happy path
# ═════════════════════════════════════════════════════════════════════════════

def test_auto_activate_false_does_nothing(clean_state):
    """TC-AA-03 — auto_activate=False + UserPluggedIn => pending only, no publish."""
    broadcasts, publishes = asyncio.run(_fire_user_plugged_in_capture(outlet="Q1"))
    # No activate published.
    activates = [(t, p) for (t, p) in publishes if p.get("action") == "activate"]
    assert not activates, f"Unexpected activate published: {activates}"
    # pending state still broadcast.
    ssc = _events_of(broadcasts, "socket_state_changed")
    assert ssc and ssc[-1]["data"]["state"] == "pending"


def test_auto_activate_true_publishes_after_delay(clean_state):
    """TC-AA-04 — all preconditions ok → activate published."""
    # Seed: create pedestal row and set all preconditions to "OK".
    asyncio.run(_fire_user_plugged_in_capture(outlet="Q1"))   # registers cabinet
    pid = _pedestal_id_for_cabinet()
    _set_auto_activate(pid, 1, True)
    _set_door(pid, "closed")
    _refresh_heartbeat(pid)

    broadcasts, publishes = asyncio.run(_fire_user_plugged_in_capture(outlet="Q1"))

    activates = [(t, p) for (t, p) in publishes if p.get("action") == "activate"]
    assert activates, f"Expected an activate publish; captured {publishes}"
    assert "opta/cmd/socket/Q1" in activates[0][0]

    # A success row must have been written to auto_activation_log.
    from app.models.auto_activation_log import AutoActivationLog
    db = _TestSession()
    try:
        rows = db.query(AutoActivationLog).filter_by(
            pedestal_id=pid, socket_id=1, result="success",
        ).all()
        assert len(rows) == 1
    finally:
        db.close()


@pytest.mark.parametrize("scenario,reason_substring,setup", [
    # TC-AA-05 door open
    ("door_open",
     "door open",
     lambda pid: _set_door(pid, "open")),
    # TC-AA-06 active fault on any socket
    ("fault_on_pedestal",
     "active fault",
     lambda pid: __import__("app.services.mqtt_handlers", fromlist=["socket_fault_state"]).socket_fault_state.update({(pid, 2): datetime.utcnow()})),
    # TC-AA-07 heartbeat stale
    ("heartbeat_stale",
     "heartbeat timeout",
     lambda pid: __import__("app.services.mqtt_handlers", fromlist=["last_heartbeat"]).last_heartbeat.__setitem__(pid, datetime.utcnow() - timedelta(seconds=400))),
    # TC-AA-09 diagnostic recently fired
    ("diagnostic_running",
     "diagnostic in progress",
     lambda pid: __import__("app.services.mqtt_handlers", fromlist=["last_diagnostic_at"]).last_diagnostic_at.__setitem__(pid, datetime.utcnow())),
])
def test_auto_activate_skip_paths(scenario, reason_substring, setup, clean_state):
    """TC-AA-05, TC-AA-06, TC-AA-07, TC-AA-09 — precondition fails → skip."""
    # Arrange: seed pedestal, set auto-activate on for Q1, set door closed +
    # heartbeat fresh so only the targeted scenario's precondition is violated.
    asyncio.run(_fire_user_plugged_in_capture(outlet="Q1"))
    pid = _pedestal_id_for_cabinet()
    _set_auto_activate(pid, 1, True)
    _set_door(pid, "closed")
    _refresh_heartbeat(pid)
    # Apply the scenario-specific override AFTER the defaults.
    setup(pid)

    broadcasts, publishes = asyncio.run(_fire_user_plugged_in_capture(outlet="Q1"))

    # No activate must have been published.
    activates = [(t, p) for (t, p) in publishes if p.get("action") == "activate"]
    assert not activates, f"[{scenario}] activate leaked through: {activates}"

    # socket_auto_activate_skipped broadcast with the expected reason.
    skipped = _events_of(broadcasts, "socket_auto_activate_skipped")
    assert skipped, f"[{scenario}] no socket_auto_activate_skipped broadcast; got {[b.get('event') for b in broadcasts]}"
    assert reason_substring in skipped[-1]["data"]["reason"].lower()
    assert skipped[-1]["data"]["socket_id"] == 1
    assert skipped[-1]["data"]["pedestal_id"] == pid
    assert "timestamp" in skipped[-1]["data"]


def test_auto_activate_skip_when_already_active(clean_state):
    """TC-AA-08 — an existing active session makes auto-activate a no-op."""
    # Register pedestal via a plug event, then seed an active session on Q1.
    asyncio.run(_fire_user_plugged_in_capture(outlet="Q1"))
    pid = _pedestal_id_for_cabinet()
    _set_auto_activate(pid, 1, True)
    _set_door(pid, "closed")
    _refresh_heartbeat(pid)

    from app.models.session import Session as SessionModel
    db = _TestSession()
    try:
        db.add(SessionModel(
            pedestal_id=pid, socket_id=1, type="electricity",
            status="active", energy_kwh=0,
        ))
        db.commit()
    finally:
        db.close()

    broadcasts, publishes = asyncio.run(_fire_user_plugged_in_capture(outlet="Q1"))

    activates = [(t, p) for (t, p) in publishes if p.get("action") == "activate"]
    assert not activates
    skipped = _events_of(broadcasts, "socket_auto_activate_skipped")
    assert skipped and "already active" in skipped[-1]["data"]["reason"].lower()


# ═════════════════════════════════════════════════════════════════════════════
# Observability
# ═════════════════════════════════════════════════════════════════════════════

def test_auto_activate_log_returns_20_newest_first(client, auth_headers, clean_state):
    """TC-AA-10 — endpoint caps at 20 rows, descending by timestamp."""
    # Register pedestal.
    asyncio.run(_fire_user_plugged_in_capture(outlet="Q1"))
    pid = _pedestal_id_for_cabinet()

    # Seed 25 skipped rows with monotonically increasing timestamps.
    from app.models.auto_activation_log import AutoActivationLog
    db = _TestSession()
    try:
        base = datetime.utcnow()
        for i in range(25):
            db.add(AutoActivationLog(
                pedestal_id=pid, socket_id=1,
                timestamp=base + timedelta(seconds=i),
                result="skipped", reason=f"reason-{i}",
            ))
        db.commit()
    finally:
        db.close()

    r = client.get(
        f"/api/pedestals/{pid}/sockets/1/auto-activate-log",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 20
    reasons = [row["reason"] for row in rows]
    # Newest-first = reason-24 at top.
    assert reasons[0] == "reason-24"
    assert reasons[-1] == "reason-5"
    # Shape of each row.
    assert set(rows[0].keys()) == {"id", "timestamp", "result", "reason", "session_id"}
