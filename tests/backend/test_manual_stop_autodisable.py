"""B6 (v3.28) — operator manual stop disables auto-activate for that socket.

Only operator stops (controls router: stop_session, direct_socket_cmd stop)
disable auto_activate. ERP stop and the meter overload autostop must NOT.
"""
import asyncio
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, AsyncMock

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
CAB = "TST_B6_CAB"
ERP_KEY = "test-erp-b6"


@pytest.fixture(scope="module")
def b6_pid(client, auth_headers):
    r = client.post("/api/pedestals/", json={
        "name": "B6 Pedestal", "location": "Dock", "data_mode": "real",
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


def _set_auto(pid, sid, value):
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        sc = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == pid, SocketConfig.socket_id == sid).first()
        sc.auto_activate = value
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


def _seed_active(pid, sid, nfc_user=None):
    from app.models.session import Session
    db = _S()
    try:
        db.query(Session).filter(Session.pedestal_id == pid, Session.socket_id == sid).delete()
        s = Session(pedestal_id=pid, socket_id=sid, type="electricity",
                    status="active", started_at=datetime.utcnow(), nfc_user_id=nfc_user)
        db.add(s); db.commit(); db.refresh(s)
        return s.id
    finally:
        db.close()


def test_operator_stop_disables_auto(client, auth_headers, b6_pid):
    _set_auto(b6_pid, 1, True)
    sid = _seed_active(b6_pid, 1)
    with patch("app.services.mqtt_client.mqtt_service.publish"):
        r = client.post(f"/api/controls/{sid}/stop", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert _get_auto(b6_pid, 1) is False


def test_operator_stop_broadcasts_change(client, auth_headers, b6_pid):
    _set_auto(b6_pid, 2, True)
    sid = _seed_active(b6_pid, 2)
    from app.services.websocket_manager import ws_manager
    events = []
    orig = ws_manager.broadcast

    async def _cap(msg):
        events.append(msg)
    with (
        patch("app.services.mqtt_client.mqtt_service.publish"),
        patch.object(ws_manager, "broadcast", _cap),
    ):
        r = client.post(f"/api/controls/{sid}/stop", headers=auth_headers)
    assert r.status_code == 200, r.text
    match = [e for e in events if e.get("event") == "socket_auto_activate_changed"]
    assert match, "expected socket_auto_activate_changed broadcast"
    assert match[0]["data"]["socket_id"] == 2 and match[0]["data"]["auto_activate"] is False


def test_direct_stop_disables_auto_idempotent(client, auth_headers, b6_pid):
    _set_auto(b6_pid, 3, True)
    with patch("app.services.mqtt_client.mqtt_service.publish"):
        r1 = client.post(f"/api/controls/pedestal/{b6_pid}/socket/Q3/cmd",
                         headers=auth_headers, json={"action": "stop"})
        r2 = client.post(f"/api/controls/pedestal/{b6_pid}/socket/Q3/cmd",
                         headers=auth_headers, json={"action": "stop"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert _get_auto(b6_pid, 3) is False   # stays False on the second (idempotent)


def test_erp_stop_does_not_disable_auto(client, auth_headers, b6_pid):
    from app.config import settings
    prev = settings.erp_api_key
    settings.erp_api_key = ERP_KEY
    try:
        _set_auto(b6_pid, 4, True)
        sid = _seed_active(b6_pid, 4)
        with patch("app.services.mqtt_client.mqtt_service.publish"):
            r = client.post(f"/api/nfc/session/{sid}/stop", headers={"X-API-Key": ERP_KEY})
        assert r.status_code == 200, r.text
        assert _get_auto(b6_pid, 4) is True, "ERP stop must NOT disable auto-activate"
    finally:
        settings.erp_api_key = prev


def test_after_disable_userpluggedin_does_not_autoactivate(client, b6_pid):
    _set_auto(b6_pid, 1, False)   # auto off (as left by an operator stop)
    from app.services.mqtt_handlers import _handle_event_user_plugged_in
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _S),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock()),
        patch("app.services.mqtt_handlers._maybe_auto_activate", AsyncMock()) as maa,
    ):
        db = _S()
        try:
            asyncio.run(_handle_event_user_plugged_in(db, b6_pid, "Q1", "POWER", {}))
        finally:
            db.close()
    assert not maa.called, "auto_activate=False must not auto-activate on plug-in"
