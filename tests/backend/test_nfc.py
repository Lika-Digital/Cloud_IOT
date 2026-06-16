"""NFC provisioning + ERP integration HTTP tests (v3.26).

Covers admin provisioning (require_admin) and the ERP X-API-Key endpoints
(/scan, /session, /session/stop) + provisioning-mode auto_activate flip.

Uses the conftest `client`/`auth_headers` fixtures (TestSession-backed) and a
local engine handle on the same sqlite file to seed cabinet/socket/session rows.
"""
import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

ERP_KEY = "test-erp-key-v326"
CAB = "TST_NFC_CAB"


@pytest.fixture(autouse=True)
def _erp_key():
    """Configure the ERP API key for the duration of each test."""
    from app.config import settings
    prev = settings.erp_api_key
    settings.erp_api_key = ERP_KEY
    yield
    settings.erp_api_key = prev


@pytest.fixture(scope="module")
def nfc_pid(client, auth_headers):
    """A dedicated real pedestal with an opta_client_id (cabinet) + berth_ref +
    four socket_configs, for NFC tests."""
    r = client.post("/api/pedestals/", json={
        "name": "NFC Test Pedestal", "location": "NFC Dock", "data_mode": "real",
    }, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]

    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        cfg.opta_client_id = CAB
        cfg.berth_ref = "VEZ_A1"
        cfg.provisioning_mode = "qr"
        for sid in (1, 2, 3, 4):
            sc = db.query(SocketConfig).filter(
                SocketConfig.pedestal_id == pid, SocketConfig.socket_id == sid).first()
            if sc is None:
                db.add(SocketConfig(pedestal_id=pid, socket_id=sid, auto_activate=True))
        db.commit()
    finally:
        db.close()
    return pid


def _erp(extra=None):
    h = {"X-API-Key": ERP_KEY}
    if extra:
        h.update(extra)
    return h


def _clear_nfc(cabinet_id=CAB):
    from app.models.nfc_tag import NfcTag
    from app.models.nfc_pending_session import NfcPendingSession
    db = _S()
    try:
        db.query(NfcTag).filter(NfcTag.cabinet_id == cabinet_id).delete()
        db.query(NfcPendingSession).filter(NfcPendingSession.cabinet_id == cabinet_id).delete()
        db.commit()
    finally:
        db.close()


def _clear_sessions(pid, socket_id):
    from app.models.session import Session
    db = _S()
    try:
        db.query(Session).filter(Session.pedestal_id == pid, Session.socket_id == socket_id).delete()
        db.commit()
    finally:
        db.close()


# ── Provisioning (admin) ──────────────────────────────────────────────────────

def test_provision_tag_stored(client, auth_headers, nfc_pid):
    _clear_nfc()
    r = client.post("/api/nfc/tags", headers=auth_headers,
                    json={"cabinet_id": CAB, "socket_id": "Q1", "nfc_tag_id": "TAG-A"})
    assert r.status_code == 200, r.text
    assert r.json()["nfc_tag_id"] == "TAG-A" and r.json()["socket_id"] == "Q1"
    lst = client.get(f"/api/nfc/tags/{CAB}", headers=auth_headers).json()
    assert any(t["nfc_tag_id"] == "TAG-A" and t["socket_id"] == "Q1" for t in lst)


def test_provision_duplicate_rejected_with_owner(client, auth_headers, nfc_pid):
    _clear_nfc()
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q1", "nfc_tag_id": "DUP"})
    r = client.post("/api/nfc/tags", headers=auth_headers,
                    json={"cabinet_id": CAB, "socket_id": "Q2", "nfc_tag_id": "DUP"})
    assert r.status_code == 409
    assert CAB in r.json()["detail"] and "Q1" in r.json()["detail"]


def test_provision_replaces_existing_for_socket(client, auth_headers, nfc_pid):
    _clear_nfc()
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q3", "nfc_tag_id": "OLD"})
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q3", "nfc_tag_id": "NEW"})
    active = client.get(f"/api/nfc/tags/{CAB}", headers=auth_headers).json()
    q3 = [t for t in active if t["socket_id"] == "Q3"]
    assert len(q3) == 1 and q3[0]["nfc_tag_id"] == "NEW"


def test_remove_tag(client, auth_headers, nfc_pid):
    _clear_nfc()
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q4", "nfc_tag_id": "RM"})
    r = client.delete(f"/api/nfc/tags/{CAB}/Q4", headers=auth_headers)
    assert r.status_code == 200 and r.json()["removed"] is True
    active = client.get(f"/api/nfc/tags/{CAB}", headers=auth_headers).json()
    assert not any(t["socket_id"] == "Q4" for t in active)


def test_bulk_save_all(client, auth_headers, nfc_pid):
    _clear_nfc()
    r = client.post("/api/nfc/tags/bulk", headers=auth_headers, json={
        "cabinet_id": CAB,
        "items": [
            {"socket_id": "Q1", "nfc_tag_id": "B1"},
            {"socket_id": "Q2", "nfc_tag_id": "B2"},
            {"socket_id": "Q3", "nfc_tag_id": "B3"},
            {"socket_id": "Q4", "nfc_tag_id": "B4"},
        ],
    })
    assert r.status_code == 200, r.text
    assert len(r.json()["tags"]) == 4


# ── Provisioning mode + auto_activate flip ────────────────────────────────────

def _auto_states(pid):
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        return {s.socket_id: s.auto_activate for s in
                db.query(SocketConfig).filter(SocketConfig.pedestal_id == pid).all()}
    finally:
        db.close()


def test_switch_to_nfc_disables_auto_activate(client, auth_headers, nfc_pid):
    r = client.patch(f"/api/nfc/mode/{CAB}", headers=auth_headers, json={"mode": "nfc"})
    assert r.status_code == 200, r.text
    assert r.json()["provisioning_mode"] == "nfc"
    assert all(v is False for v in _auto_states(nfc_pid).values())


def test_switch_back_to_qr_restores_auto_activate(client, auth_headers, nfc_pid):
    client.patch(f"/api/nfc/mode/{CAB}", headers=auth_headers, json={"mode": "nfc"})
    r = client.patch(f"/api/nfc/mode/{CAB}", headers=auth_headers, json={"mode": "qr"})
    assert r.status_code == 200
    assert all(v is True for v in _auto_states(nfc_pid).values())


# ── Scan (ERP, X-API-Key) ─────────────────────────────────────────────────────

def test_scan_creates_pending(client, auth_headers, nfc_pid):
    _clear_nfc(); _clear_sessions(nfc_pid, 1)
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q1", "nfc_tag_id": "S1"})
    r = client.post("/api/nfc/scan", headers=_erp(), json={"nfc_tag_id": "S1", "user_id": "erp-77"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["cabinet_id"] == CAB and body["socket_id"] == "Q1"
    assert body["berth_id"] == "VEZ_A1"
    assert "expires_at" in body


def test_scan_unknown_tag_404(client, nfc_pid):
    r = client.post("/api/nfc/scan", headers=_erp(), json={"nfc_tag_id": "NOPE", "user_id": "u"})
    assert r.status_code == 404


def test_scan_missing_key_401(client, nfc_pid):
    r = client.post("/api/nfc/scan", json={"nfc_tag_id": "x", "user_id": "u"})
    assert r.status_code == 401


def test_scan_invalid_key_401(client, nfc_pid):
    r = client.post("/api/nfc/scan", headers={"X-API-Key": "wrong"},
                    json={"nfc_tag_id": "x", "user_id": "u"})
    assert r.status_code == 401


def test_scan_socket_active_409(client, auth_headers, nfc_pid):
    _clear_nfc(); _clear_sessions(nfc_pid, 2)
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q2", "nfc_tag_id": "ACT"})
    from app.models.session import Session
    db = _S()
    try:
        db.add(Session(pedestal_id=nfc_pid, socket_id=2, type="electricity",
                       status="active", started_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()
    r = client.post("/api/nfc/scan", headers=_erp(), json={"nfc_tag_id": "ACT", "user_id": "u"})
    assert r.status_code == 409
    _clear_sessions(nfc_pid, 2)


def test_scan_socket_fault_503(client, auth_headers, nfc_pid):
    _clear_nfc(); _clear_sessions(nfc_pid, 3)
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q3", "nfc_tag_id": "FLT"})
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        sc = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == nfc_pid, SocketConfig.socket_id == 3).first()
        sc.breaker_state = "tripped"
        db.commit()
    finally:
        db.close()
    r = client.post("/api/nfc/scan", headers=_erp(), json={"nfc_tag_id": "FLT", "user_id": "u"})
    assert r.status_code == 503
    db = _S()
    try:
        sc = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == nfc_pid, SocketConfig.socket_id == 3).first()
        sc.breaker_state = "closed"
        db.commit()
    finally:
        db.close()


def test_two_simultaneous_scans_second_409(client, auth_headers, nfc_pid):
    _clear_nfc(); _clear_sessions(nfc_pid, 1)
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q1", "nfc_tag_id": "S1B"})
    r1 = client.post("/api/nfc/scan", headers=_erp(), json={"nfc_tag_id": "S1B", "user_id": "a"})
    assert r1.status_code == 200
    r2 = client.post("/api/nfc/scan", headers=_erp(), json={"nfc_tag_id": "S1B", "user_id": "b"})
    assert r2.status_code == 409


def test_scan_expired_pending_creates_new(client, auth_headers, nfc_pid):
    _clear_nfc(); _clear_sessions(nfc_pid, 4)
    client.post("/api/nfc/tags", headers=auth_headers,
                json={"cabinet_id": CAB, "socket_id": "Q4", "nfc_tag_id": "EXP"})
    # Seed an expired pending row directly.
    from app.models.nfc_pending_session import NfcPendingSession
    db = _S()
    try:
        db.add(NfcPendingSession(
            nfc_tag_id="EXP", user_id="old", cabinet_id=CAB, socket_id="Q4",
            created_at=datetime.utcnow() - timedelta(minutes=10),
            expires_at=datetime.utcnow() - timedelta(minutes=5), status="pending"))
        db.commit()
    finally:
        db.close()
    r = client.post("/api/nfc/scan", headers=_erp(), json={"nfc_tag_id": "EXP", "user_id": "new"})
    assert r.status_code == 200, r.text


# ── Session API + remote stop (ERP) ───────────────────────────────────────────

def _seed_active_session(pid, socket_id, nfc_user="erp-1"):
    from app.models.session import Session
    db = _S()
    try:
        s = Session(pedestal_id=pid, socket_id=socket_id, type="electricity",
                    status="active", started_at=datetime.utcnow(), nfc_user_id=nfc_user)
        db.add(s); db.commit(); db.refresh(s)
        return s.id
    finally:
        db.close()


def test_get_session_returns_fields(client, nfc_pid):
    _clear_sessions(nfc_pid, 1)
    sid = _seed_active_session(nfc_pid, 1, nfc_user="erp-9")
    r = client.get(f"/api/nfc/session/{sid}", headers=_erp())
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["session_id"] == sid and b["status"] == "active"
    assert b["customer_id"] == "erp-9"
    assert b["socket_id"] == "Q1" and b["cabinet_id"] == CAB
    assert "duration_minutes" in b and "energy_kwh" in b and "power_kw_current" in b
    _clear_sessions(nfc_pid, 1)


def test_get_session_missing_key_401(client, nfc_pid):
    r = client.get("/api/nfc/session/1")
    assert r.status_code == 401


def test_get_session_unknown_404(client, nfc_pid):
    r = client.get("/api/nfc/session/999999", headers=_erp())
    assert r.status_code == 404


def test_stop_session_completes(client, nfc_pid):
    _clear_sessions(nfc_pid, 2)
    sid = _seed_active_session(nfc_pid, 2)
    with patch("app.services.mqtt_client.mqtt_service.publish"):
        r = client.post(f"/api/nfc/session/{sid}/stop", headers=_erp())
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ended"
    _clear_sessions(nfc_pid, 2)


def test_stop_already_ended_409(client, nfc_pid):
    _clear_sessions(nfc_pid, 2)
    from app.models.session import Session
    db = _S()
    try:
        s = Session(pedestal_id=nfc_pid, socket_id=2, type="electricity",
                    status="completed", started_at=datetime.utcnow(), ended_at=datetime.utcnow())
        db.add(s); db.commit(); db.refresh(s); sid = s.id
    finally:
        db.close()
    r = client.post(f"/api/nfc/session/{sid}/stop", headers=_erp())
    assert r.status_code == 409
    assert "operator" in r.json()["detail"].lower()
    _clear_sessions(nfc_pid, 2)


def test_stop_missing_key_401(client, nfc_pid):
    r = client.post("/api/nfc/session/1/stop")
    assert r.status_code == 401
