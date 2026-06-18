"""v3.29 — plugged-aware Activate + 3 socket modes (Auto / Activate / Stop).

(1) opta/diagnostic `plugged` per socket → awaiting_activation when plugged & idle,
    cleared when unplugged (Activate button enables/disables accordingly).
(2) Smart Mode ON publishes an immediate opta/cmd/diagnostic request.
(3) A manual Activate disables auto_activate (same as a manual Stop / B6).
"""
import asyncio
import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, AsyncMock, MagicMock

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
CAB = "TST_PLUG_CAB"


@pytest.fixture(scope="module")
def plug_pid(client, auth_headers):
    r = client.post("/api/pedestals/", json={
        "name": "Plug Pedestal", "location": "Dock", "data_mode": "real",
    }, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid); db.add(cfg)
        cfg.opta_client_id = CAB
        for sid in (1, 2, 3, 4):
            if db.query(SocketConfig).filter(
                SocketConfig.pedestal_id == pid, SocketConfig.socket_id == sid).first() is None:
                db.add(SocketConfig(pedestal_id=pid, socket_id=sid, auto_activate=True))
        db.commit()
    finally:
        db.close()
    return pid


def _op_status(pid, sid):
    from app.models.pedestal_config import SocketState
    db = _S()
    try:
        ss = db.query(SocketState).filter(
            SocketState.pedestal_id == pid, SocketState.socket_id == sid).first()
        return ss.operator_status if ss else "__missing__"
    finally:
        db.close()


def _set_op_status(pid, sid, value, connected=True):
    from app.models.pedestal_config import SocketState
    db = _S()
    try:
        ss = db.query(SocketState).filter(
            SocketState.pedestal_id == pid, SocketState.socket_id == sid).first()
        if ss is None:
            ss = SocketState(pedestal_id=pid, socket_id=sid); db.add(ss)
        ss.operator_status = value
        ss.connected = connected
        db.commit()
    finally:
        db.close()


def _get_auto(pid, sid):
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        return db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == pid, SocketConfig.socket_id == sid).first().auto_activate
    finally:
        db.close()


def _set_auto(pid, sid, value):
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        sc = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == pid, SocketConfig.socket_id == sid).first()
        sc.auto_activate = value; db.commit()
    finally:
        db.close()


def _run_diag(pid, power):
    from app.services import mqtt_handlers as mh
    payload = json.dumps({"cabinetId": CAB, "power": power, "water": []})
    with (
        patch.object(mh, "SessionLocal", _S),
        patch.object(mh, "_cabinet_to_pedestal_id", lambda db, cab: pid),
        patch.object(mh.ws_manager, "broadcast", AsyncMock()),
    ):
        asyncio.run(mh._handle_opta_diagnostic(payload))


# --- (1) plugged → awaiting_activation ----------------------------------

def test_plugged_true_sets_awaiting_activation(plug_pid):
    _set_op_status(plug_pid, 1, None)
    _run_diag(plug_pid, [{"id": "Q1", "state": "idle", "hw": "off", "plugged": True}])
    assert _op_status(plug_pid, 1) == "awaiting_activation"


def test_plugged_false_clears_awaiting(plug_pid):
    _set_op_status(plug_pid, 2, "awaiting_activation")
    _run_diag(plug_pid, [{"id": "Q2", "state": "idle", "hw": "off", "plugged": False}])
    assert _op_status(plug_pid, 2) is None


def test_missing_plugged_field_is_noop(plug_pid):
    _set_op_status(plug_pid, 3, "rejected")
    _run_diag(plug_pid, [{"id": "Q3", "state": "idle", "hw": "off"}])
    assert _op_status(plug_pid, 3) == "rejected"   # legacy state untouched


def test_plugged_false_leaves_legacy_pending(plug_pid):
    _set_op_status(plug_pid, 4, "pending")
    _run_diag(plug_pid, [{"id": "Q4", "state": "idle", "hw": "off", "plugged": False}])
    assert _op_status(plug_pid, 4) == "pending"   # only awaiting_activation is cleared


def test_plugged_true_with_active_session_no_pending(plug_pid):
    from app.models.session import Session
    _set_op_status(plug_pid, 1, None)
    db = _S()
    try:
        db.query(Session).filter(Session.pedestal_id == plug_pid, Session.socket_id == 1).delete()
        db.add(Session(pedestal_id=plug_pid, socket_id=1, type="electricity",
                       status="active", started_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()
    _run_diag(plug_pid, [{"id": "Q1", "state": "active", "hw": "on", "plugged": True}])
    assert _op_status(plug_pid, 1) is None   # active session → not awaiting
    db = _S()
    try:
        db.query(Session).filter(Session.pedestal_id == plug_pid, Session.socket_id == 1).delete()
        db.commit()
    finally:
        db.close()


# --- (2) Smart Mode ON sends a diagnostic --------------------------------

def test_smartmode_on_publishes_diagnostic(client, auth_headers, plug_pid):
    pub = MagicMock()
    with patch("app.services.mqtt_client.mqtt_service.publish", pub):
        r = client.post(f"/api/pedestals/{CAB}/smartmode",
                        headers=auth_headers, json={"value": True})
    assert r.status_code == 200, r.text
    topics = [c.args[0] for c in pub.call_args_list]
    assert "opta/cmd/smartmode" in topics
    assert "opta/cmd/diagnostic" in topics, "Smart Mode ON must request a diagnostic"


def test_smartmode_off_does_not_publish_diagnostic(client, auth_headers, plug_pid):
    pub = MagicMock()
    with patch("app.services.mqtt_client.mqtt_service.publish", pub):
        r = client.post(f"/api/pedestals/{CAB}/smartmode",
                        headers=auth_headers, json={"value": False})
    assert r.status_code == 200, r.text
    topics = [c.args[0] for c in pub.call_args_list]
    assert "opta/cmd/diagnostic" not in topics


# --- (3) manual Activate disables auto ------------------------------------

def test_manual_activate_disables_auto(client, auth_headers, plug_pid):
    _set_auto(plug_pid, 2, True)
    _set_op_status(plug_pid, 2, "awaiting_activation", connected=True)
    with patch("app.services.mqtt_client.mqtt_service.publish"):
        r = client.post(f"/api/controls/pedestal/{plug_pid}/socket/Q2/cmd",
                        headers=auth_headers, json={"action": "activate"})
    assert r.status_code == 200, r.text
    assert _get_auto(plug_pid, 2) is False


def test_manual_activate_broadcasts_auto_change(client, auth_headers, plug_pid):
    _set_auto(plug_pid, 3, True)
    _set_op_status(plug_pid, 3, "awaiting_activation", connected=True)
    from app.services.websocket_manager import ws_manager
    events = []

    async def _cap(msg):
        events.append(msg)
    with (
        patch("app.services.mqtt_client.mqtt_service.publish"),
        patch.object(ws_manager, "broadcast", _cap),
    ):
        r = client.post(f"/api/controls/pedestal/{plug_pid}/socket/Q3/cmd",
                        headers=auth_headers, json={"action": "activate"})
    assert r.status_code == 200, r.text
    match = [e for e in events if e.get("event") == "socket_auto_activate_changed"]
    assert match and match[0]["data"]["auto_activate"] is False
