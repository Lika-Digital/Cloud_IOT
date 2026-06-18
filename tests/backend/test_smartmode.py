"""SmartMode (firmware v3.0.0, v3.28) — opta/status parsing, REST, WS, command."""
import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch, AsyncMock

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
CAB = "TST_SM_CAB"


@pytest.fixture(scope="module")
def sm_pid(client, auth_headers):
    r = client.post("/api/pedestals/", json={
        "name": "SmartMode Pedestal", "location": "Dock", "data_mode": "real",
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
        cfg.smart_mode = False
        db.commit()
    finally:
        db.close()
    return pid


def _smart_mode(pid):
    from app.models.pedestal_config import PedestalConfig
    db = _S()
    try:
        return db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first().smart_mode
    finally:
        db.close()


def _set_smart(pid, value):
    from app.models.pedestal_config import PedestalConfig
    db = _S()
    try:
        db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first().smart_mode = value
        db.commit()
    finally:
        db.close()


def _status(pid, payload: dict):
    """Run _handle_marina_status with the given opta/status payload; return broadcasts."""
    from app.services.mqtt_handlers import _handle_marina_status
    broadcasts = []

    async def _cap(msg):
        broadcasts.append(msg)
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _S),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", _cap),
    ):
        asyncio.run(_handle_marina_status(CAB, json.dumps(payload)))
    return broadcasts


# ── opta/status parsing ───────────────────────────────────────────────────────

def test_status_smartmode_true_updates_db(sm_pid):
    _set_smart(sm_pid, False)
    _status(sm_pid, {"cabinetId": CAB, "seq": 1, "uptime_ms": 1000, "door": "open", "smartMode": True})
    assert _smart_mode(sm_pid) is True


def test_status_smartmode_false_updates_db(sm_pid):
    _set_smart(sm_pid, True)
    _status(sm_pid, {"cabinetId": CAB, "seq": 2, "uptime_ms": 2000, "door": "open", "smartMode": False})
    assert _smart_mode(sm_pid) is False


def test_status_without_smartmode_preserves_value(sm_pid):
    _set_smart(sm_pid, True)
    _status(sm_pid, {"cabinetId": CAB, "seq": 3, "uptime_ms": 3000, "door": "open"})
    assert _smart_mode(sm_pid) is True, "absent smartMode must not change stored value"


def test_status_broadcast_includes_smart_mode(sm_pid):
    _set_smart(sm_pid, True)
    bc = _status(sm_pid, {"cabinetId": CAB, "seq": 4, "uptime_ms": 4000, "door": "open", "smartMode": True})
    opta = [m for m in bc if m.get("event") == "opta_status"]
    assert opta, "opta_status broadcast expected"
    assert "smart_mode" in opta[0]["data"] and opta[0]["data"]["smart_mode"] is True


# ── POST /api/pedestals/{cabinet_id}/smartmode ────────────────────────────────

def test_post_smartmode_true_publishes_and_returns(client, auth_headers, sm_pid):
    pubs = []
    with patch("app.services.mqtt_client.mqtt_service.publish",
               side_effect=lambda t, p: pubs.append((t, p))):
        r = client.post(f"/api/pedestals/{CAB}/smartmode", headers=auth_headers, json={"value": True})
    assert r.status_code == 200, r.text
    assert r.json()["smart_mode"] is True
    assert ("opta/cmd/smartmode", json.dumps({"value": True})) in pubs
    assert _smart_mode(sm_pid) is True   # optimistic DB update


def test_post_smartmode_false_publishes_and_returns(client, auth_headers, sm_pid):
    pubs = []
    with patch("app.services.mqtt_client.mqtt_service.publish",
               side_effect=lambda t, p: pubs.append((t, p))):
        r = client.post(f"/api/pedestals/{CAB}/smartmode", headers=auth_headers, json={"value": False})
    assert r.status_code == 200, r.text
    assert r.json()["smart_mode"] is False
    assert ("opta/cmd/smartmode", json.dumps({"value": False})) in pubs


def test_post_smartmode_requires_auth(client, sm_pid):
    # require_admin via HTTPBearer rejects a missing token with 403 (framework
    # default for all admin endpoints); an invalid token would be 401. Either
    # way the endpoint is protected.
    r = client.post(f"/api/pedestals/{CAB}/smartmode", json={"value": True})
    assert r.status_code in (401, 403)


def test_post_smartmode_unknown_cabinet_404(client, auth_headers):
    with patch("app.services.mqtt_client.mqtt_service.publish"):
        r = client.post("/api/pedestals/NO_SUCH_CAB/smartmode", headers=auth_headers, json={"value": True})
    assert r.status_code == 404


# ── REST health ───────────────────────────────────────────────────────────────

def test_health_includes_smart_mode(client, auth_headers, sm_pid):
    _set_smart(sm_pid, True)
    r = client.get("/api/pedestals/health", headers=auth_headers)
    assert r.status_code == 200
    entry = r.json()[str(sm_pid)]
    assert entry["smart_mode"] is True
