"""B5 (v3.28) — duplicate auto-activate dedup in _maybe_auto_activate.

A second UserPluggedIn racing within the 3 s window must not publish a second
`activate`. The lock clears on SessionEnded so genuine re-activation is allowed.
"""
import asyncio
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, AsyncMock, MagicMock

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
CAB = "TST_DEDUP_CAB"


@pytest.fixture(scope="module")
def dedup_pid(client, auth_headers):
    r = client.post("/api/pedestals/", json={
        "name": "Dedup Pedestal", "location": "Dock", "data_mode": "real",
    }, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    from app.models.pedestal_config import PedestalConfig, SocketState
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid); db.add(cfg)
        cfg.opta_client_id = CAB
        cfg.door_state = "closed"
        cfg.smart_mode = True   # v3.30 — control endpoints require SmartMode ON
        for sid in (3, 4):
            if db.query(SocketState).filter(
                SocketState.pedestal_id == pid, SocketState.socket_id == sid).first() is None:
                db.add(SocketState(pedestal_id=pid, socket_id=sid, connected=True))
            if db.query(SocketConfig).filter(
                SocketConfig.pedestal_id == pid, SocketConfig.socket_id == sid).first() is None:
                db.add(SocketConfig(pedestal_id=pid, socket_id=sid, auto_activate=True))
        db.commit()
    finally:
        db.close()
    # heartbeat so the precondition (if not patched) wouldn't block — we patch it anyway.
    from app.services import mqtt_handlers as h
    from datetime import datetime
    h.last_heartbeat[pid] = datetime.utcnow()
    return pid


def _reset_lock():
    from app.services import mqtt_handlers as h
    h._last_activate_ts.clear()


def _run_auto(pid, sid):
    """Run _maybe_auto_activate with internals mocked; return list of activate publishes."""
    from app.services.mqtt_handlers import _maybe_auto_activate
    pubs = []
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _S),
        patch("app.services.mqtt_handlers._auto_activate_precondition_check", return_value=None),
        patch("app.services.mqtt_handlers._log_auto_activation"),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
        patch("app.services.mqtt_handlers._AUTO_ACTIVATE_DELAY_S", 0),
        patch("app.services.mqtt_client.mqtt_service.publish",
              MagicMock(side_effect=lambda t, p: pubs.append((t, p)))),
    ):
        asyncio.run(_maybe_auto_activate(pid, sid, f"Q{sid}"))
    return [t for t, _ in pubs if "cmd/socket" in t]


def test_two_rapid_activates_publish_once(dedup_pid):
    _reset_lock()
    first = _run_auto(dedup_pid, 3)
    second = _run_auto(dedup_pid, 3)
    assert len(first) == 1, "first activate should publish"
    assert len(second) == 0, "duplicate within 3s must be skipped"


def test_cleared_on_session_ended_allows_reactivate(dedup_pid):
    _reset_lock()
    assert len(_run_auto(dedup_pid, 3)) == 1
    assert len(_run_auto(dedup_pid, 3)) == 0
    # SessionEnded clears the lock → next activate publishes again.
    from app.services.mqtt_handlers import _handle_event_session_ended
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _S),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
    ):
        asyncio.run(_handle_event_session_ended(_S(), dedup_pid, "Q3", "POWER", {"totals": {}}))
    assert len(_run_auto(dedup_pid, 3)) == 1, "re-activation after SessionEnded must be allowed"


def test_different_sockets_not_blocked(dedup_pid):
    _reset_lock()
    assert len(_run_auto(dedup_pid, 3)) == 1
    assert len(_run_auto(dedup_pid, 4)) == 1, "different socket must not be blocked by another's lock"


def test_window_boundary(dedup_pid):
    from app.services import mqtt_handlers as h
    key = f"{dedup_pid}-3"
    # t=2.9s ago → still within window → skip
    _reset_lock()
    h._last_activate_ts[key] = time.monotonic() - 2.9
    assert len(_run_auto(dedup_pid, 3)) == 0, "2.9s < 3.0s window → skip"
    # t=3.1s ago → outside window → publish
    _reset_lock()
    h._last_activate_ts[key] = time.monotonic() - 3.1
    assert len(_run_auto(dedup_pid, 3)) == 1, "3.1s > 3.0s window → publish"


def test_operator_manual_activate_not_blocked(client, auth_headers, dedup_pid):
    """direct_socket_cmd (operator) publishes regardless of the auto-activate lock."""
    from app.services import mqtt_handlers as h
    h._last_activate_ts[f"{dedup_pid}-4"] = time.monotonic()  # lock is "hot"
    with patch("app.services.mqtt_client.mqtt_service.publish"):
        r = client.post(f"/api/controls/pedestal/{dedup_pid}/socket/Q4/cmd",
                        headers=auth_headers, json={"action": "activate"})
    assert r.status_code == 200, r.text   # not blocked by the dedup lock
