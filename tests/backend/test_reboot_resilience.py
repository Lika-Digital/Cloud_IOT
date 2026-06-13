"""Tests for v3.18 reboot resilience + plug-and-go.

- A2: electricity sockets default auto_activate=True.
- B:  live sessions are ADOPTED on reconnect (active socket/valve with no
      open session -> create one; idempotent; idle -> nothing).
- D:  cabinet door open/unknown no longer BLOCKS auto-activate (warn-only);
      other preconditions still block.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from unittest.mock import patch, AsyncMock

from app.services import mqtt_handlers
from app.services.mqtt_handlers import _auto_activate_precondition_check
from app.models.socket_config import SocketConfig
from app.models.pedestal_config import PedestalConfig
from app.models.session import Session
from tests.backend.conftest import TestSession

CAB = "MAR_ADOPT_T"
PID = 99


def _ensure_cfg():
    db = TestSession()
    if not db.query(PedestalConfig).filter_by(opta_client_id=CAB).first():
        db.add(PedestalConfig(pedestal_id=PID, opta_client_id=CAB))
        db.commit()
    db.close()


def _clear():
    db = TestSession()
    db.query(Session).filter_by(pedestal_id=PID).delete()
    db.query(SocketConfig).filter_by(pedestal_id=PID).delete()
    db.commit()
    db.close()


def _simulate_socket(socket_name: str, state: str):
    payload = json.dumps({"cabinetId": CAB, "id": socket_name, "state": state,
                          "hw_status": "on" if state == "active" else "off", "session": None})
    with patch.object(mqtt_handlers, "SessionLocal", TestSession), \
         patch("app.services.mqtt_handlers.ws_manager.broadcast", new=AsyncMock()), \
         patch("app.services.qr_service.generate_socket_qr", return_value="x"):
        asyncio.run(mqtt_handlers._handle_marina_socket(CAB, socket_name, payload))


def _active_sessions(socket_id: int, stype: str = "electricity"):
    db = TestSession()
    try:
        return db.query(Session).filter_by(
            pedestal_id=PID, socket_id=socket_id, type=stype, status="active").all()
    finally:
        db.close()


# ── A2: default ───────────────────────────────────────────────────────────────

def test_socket_config_defaults_auto_activate_true():
    db = TestSession()
    sc = SocketConfig(pedestal_id=PID, socket_id=7)
    db.add(sc); db.commit(); db.refresh(sc)
    val = sc.auto_activate
    db.delete(sc); db.commit(); db.close()
    assert val is True


# ── B: adoption ────────────────────────────────────────────────────────────────

def test_active_socket_is_adopted():
    _ensure_cfg(); _clear()
    _simulate_socket("Q1", "active")
    assert len(_active_sessions(1)) == 1
    _clear()


def test_adoption_is_idempotent():
    _ensure_cfg(); _clear()
    _simulate_socket("Q1", "active")
    _simulate_socket("Q1", "active")
    assert len(_active_sessions(1)) == 1
    _clear()


def test_idle_socket_creates_no_session():
    _ensure_cfg(); _clear()
    _simulate_socket("Q2", "idle")
    assert len(_active_sessions(2)) == 0
    _clear()


def test_active_water_valve_is_adopted():
    _ensure_cfg(); _clear()
    payload = json.dumps({"cabinetId": CAB, "id": "V1", "state": "active",
                          "total_l": 1.0, "session_l": 0.5, "session": None})
    with patch.object(mqtt_handlers, "SessionLocal", TestSession), \
         patch("app.services.mqtt_handlers.ws_manager.broadcast", new=AsyncMock()):
        asyncio.run(mqtt_handlers._handle_marina_water(CAB, "V1", payload))
    assert len(_active_sessions(1, "water")) == 1
    _clear()


# ── D: door non-blocking ────────────────────────────────────────────────────────

def test_door_open_does_not_block_auto_activate():
    _ensure_cfg(); _clear()
    # make all OTHER preconditions pass
    mqtt_handlers.last_heartbeat[PID] = datetime.utcnow()
    mqtt_handlers.socket_fault_state.clear()
    mqtt_handlers.last_diagnostic_lockout_at.pop(PID, None)
    db = TestSession()
    cfg = db.query(PedestalConfig).filter_by(opta_client_id=CAB).first()
    cfg.door_state = "open"
    db.commit()
    try:
        reason_open = _auto_activate_precondition_check(db, PID, 1)
        cfg.door_state = "unknown"; db.commit()
        reason_unknown = _auto_activate_precondition_check(db, PID, 1)
    finally:
        db.close()
    assert reason_open is None, f"door open should not block, got {reason_open!r}"
    assert reason_unknown is None, f"door unknown should not block, got {reason_unknown!r}"
    _clear()
