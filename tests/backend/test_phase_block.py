"""TC-PHB-01..05 — berth detail carries per-phase currents for <PhaseBlock> (block 4, 2026-10-15).

Spec §5.3: a three-phase socket shows "Phase 1 / 2 / 3" in berth detail, and ONLY when the
payload actually contains per-phase values (§4.7: the cabinet is not four identical sockets —
Q1 sends currentAmpsL1..L3, Q2-Q4 send currentAmps). The handler stores the three values in
socket_configs.meter_current_l1..l3; `power.phase_amps` reports them, or null.

  TC-PHB-01  three-phase, a session running, telemetry fresh -> the three values, in order
  TC-PHB-02  single-phase (no per-phase values stored) -> null, so the block is absent
  TC-PHB-03  no session running -> null: a leftover figure on an idle socket reads as "drawing"
  TC-PHB-04  telemetry older than the outlet window -> null, even with a session: not live
  TC-PHB-05  one phase missing from the payload -> that phase is None, never 0
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from conftest import TestSession as _S, TestUserSession as _US


@pytest.fixture(scope="module")
def setup(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    from app.auth.berth_models import Berth
    r = client.post("/api/pedestals/", json={"name": "PHB Pedestal", "location": "Dock P",
                                              "data_mode": "real"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        cfg.smart_mode = True
        if db.query(SocketConfig).filter(SocketConfig.pedestal_id == pid,
                                         SocketConfig.socket_id == 1).first() is None:
            db.add(SocketConfig(pedestal_id=pid, socket_id=1, auto_activate=False))
        db.commit()
    finally:
        db.close()
    udb = _US()
    try:
        b = Berth(name="PHB 1", pedestal_id=pid, berth_number=1)
        udb.add(b)
        udb.commit()
        bid = b.id
    finally:
        udb.close()
    r = client.put(f"/api/marina/berth-assignments/{pid}", headers=auth_headers,
                   json={"assignments": [{"berth_id": bid, "socket_id": 1}]})
    assert r.status_code == 200, r.text
    return pid, bid


def _meter(pid, *, l1, l2, l3, total, at, phases):
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        cfg = db.query(SocketConfig).filter(SocketConfig.pedestal_id == pid,
                                            SocketConfig.socket_id == 1).first()
        cfg.meter_current_l1, cfg.meter_current_l2, cfg.meter_current_l3 = l1, l2, l3
        cfg.meter_current_amps = total
        cfg.meter_load_updated_at = at
        cfg.phases = phases
        db.commit()
    finally:
        db.close()


def _session(pid, *, running: bool):
    from app.models.session import Session
    db = _S()
    try:
        db.query(Session).filter(Session.pedestal_id == pid).delete()
        if running:
            db.add(Session(pedestal_id=pid, socket_id=1, type="electricity", status="active",
                           started_at=datetime.utcnow() - timedelta(minutes=5)))
        db.commit()
    finally:
        db.close()


def _phases(client, auth_headers, bid):
    from app.services.mqtt_handlers import last_heartbeat
    from app.auth.berth_models import Berth
    udb = _US()
    try:
        pid = udb.get(Berth, bid).pedestal_id
    finally:
        udb.close()
    last_heartbeat[pid] = datetime.utcnow()
    try:
        r = client.get(f"/api/marina/berths/{bid}", headers=auth_headers)
    finally:
        last_heartbeat.pop(pid, None)
    assert r.status_code == 200, r.text
    power = r.json()["power"]
    assert "phase_amps" in power, f"berth detail has no phase_amps at all: {power}"
    return power["phase_amps"]


def test_tc_phb_01_three_phase_running_fresh(client, auth_headers, setup):
    pid, bid = setup
    _meter(pid, l1=10.04, l2=9.5, l3=11.0, total=30.54, at=datetime.utcnow(), phases=3)
    _session(pid, running=True)
    assert _phases(client, auth_headers, bid) == [10.04, 9.5, 11.0]


def test_tc_phb_02_single_phase_is_null(client, auth_headers, setup):
    pid, bid = setup
    _meter(pid, l1=None, l2=None, l3=None, total=7.0, at=datetime.utcnow(), phases=1)
    _session(pid, running=True)
    assert _phases(client, auth_headers, bid) is None


def test_tc_phb_03_no_session_is_null(client, auth_headers, setup):
    pid, bid = setup
    _meter(pid, l1=10.0, l2=9.5, l3=11.0, total=30.5, at=datetime.utcnow(), phases=3)
    _session(pid, running=False)
    assert _phases(client, auth_headers, bid) is None


def test_tc_phb_04_stale_telemetry_is_null(client, auth_headers, setup):
    pid, bid = setup
    _meter(pid, l1=10.0, l2=9.5, l3=11.0, total=30.5,
           at=datetime.utcnow() - timedelta(seconds=120), phases=3)
    _session(pid, running=True)
    assert _phases(client, auth_headers, bid) is None


def test_tc_phb_05_missing_phase_is_none_not_zero(client, auth_headers, setup):
    pid, bid = setup
    _meter(pid, l1=10.0, l2=None, l3=11.0, total=21.0, at=datetime.utcnow(), phases=3)
    _session(pid, running=True)
    assert _phases(client, auth_headers, bid) == [10.0, None, 11.0]
