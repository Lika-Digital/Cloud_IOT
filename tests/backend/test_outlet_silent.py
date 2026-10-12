"""`outlet_silent` (rank 2.5) is emitted — block 3, 2026-10-12.

Spec §3, rank 2.5: "This outlet has not reported recently". The cabinet can be alive while one
outlet is stale; without this the berth row reads `idle` for a socket nobody has heard from.
Until today `routers/marina.py` hard-coded `outlet_state_unknown=False`, so it could never fire.

WHAT "REPORTED" MEANS for a socket, from the two messages the cabinet sends per socket:
  opta/meters/Q{n}/telemetry  every 5 s   → socket_configs.meter_load_updated_at
  opta/sockets/Q{n}/status                → socket_states.updated_at
Silent = the FRESHER of the two is missing or older than OUTLET_STALE_S (60 s, the same window
as valves and the cabinet heartbeat). That the meter really reports every 5 s while a socket is
idle is a cabinet fact — §13 check 11i.

  TC-OS-01  both fresh → not silent, power state as before
  TC-OS-02  both older than 60 s → status outlet_silent, power state `unknown` (not `idle`)
  TC-OS-03  never reported → outlet_silent
  TC-OS-04  only one of the two fresh → not silent (either message proves the socket is heard)
  TC-OS-05  the cabinet itself silent → no_contact outranks it (rank 1 before 2.5)

TC-OS-02/03 FAIL on the code before this change (shown 2026-10-12).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from conftest import TestSession as _S, TestUserSession as _US

OLD = timedelta(seconds=120)


@pytest.fixture(scope="module")
def setup(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    from app.auth.berth_models import Berth
    r = client.post("/api/pedestals/", json={"name": "OS Pedestal", "location": "Dock O",
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
        b = Berth(name="OS 1", pedestal_id=pid, berth_number=1)
        udb.add(b)
        udb.commit()
        bid = b.id
    finally:
        udb.close()
    r = client.put(f"/api/marina/berth-assignments/{pid}", headers=auth_headers,
                   json={"assignments": [{"berth_id": bid, "socket_id": 1}]})
    assert r.status_code == 200, r.text
    return pid, bid


def _reported(pid, *, meter_at, status_at):
    from app.models.socket_config import SocketConfig
    from app.models.pedestal_config import SocketState
    db = _S()
    try:
        cfg = db.query(SocketConfig).filter(SocketConfig.pedestal_id == pid,
                                            SocketConfig.socket_id == 1).first()
        cfg.meter_load_updated_at = meter_at
        st = db.query(SocketState).filter(SocketState.pedestal_id == pid,
                                          SocketState.socket_id == 1).first()
        if status_at is None:
            if st is not None:
                db.delete(st)
        else:
            if st is None:
                st = SocketState(pedestal_id=pid, socket_id=1, connected=False)
                db.add(st)
            st.updated_at = status_at
        db.commit()
    finally:
        db.close()


def _detail(client, auth_headers, bid, *, heartbeat_age_s=1):
    from app.services.mqtt_handlers import last_heartbeat
    from app.auth.berth_models import Berth
    udb = _US()
    try:
        pid = udb.get(Berth, bid).pedestal_id
    finally:
        udb.close()
    last_heartbeat[pid] = datetime.utcnow() - timedelta(seconds=heartbeat_age_s)
    try:
        r = client.get(f"/api/marina/berths/{bid}", headers=auth_headers)
    finally:
        last_heartbeat.pop(pid, None)
    assert r.status_code == 200, r.text
    return r.json()


def test_tc_os_01_fresh_is_not_silent(client, auth_headers, setup):
    pid, bid = setup
    now = datetime.utcnow()
    _reported(pid, meter_at=now, status_at=now)
    d = _detail(client, auth_headers, bid)
    assert d["status_code"] != "outlet_silent" and d["power"]["state"] == "idle", d


def test_tc_os_02_both_stale_is_silent_and_not_idle(client, auth_headers, setup):
    pid, bid = setup
    old = datetime.utcnow() - OLD
    _reported(pid, meter_at=old, status_at=old)
    d = _detail(client, auth_headers, bid)
    assert d["status_code"] == "outlet_silent", d
    assert d["power"]["state"] == "unknown", d["power"]


def test_tc_os_03_never_reported_is_silent(client, auth_headers, setup):
    pid, bid = setup
    _reported(pid, meter_at=None, status_at=None)
    assert _detail(client, auth_headers, bid)["status_code"] == "outlet_silent"


@pytest.mark.parametrize("fresh", ["meter", "status"])
def test_tc_os_04_either_message_is_enough(client, auth_headers, setup, fresh):
    pid, bid = setup
    now, old = datetime.utcnow(), datetime.utcnow() - OLD
    _reported(pid, meter_at=now if fresh == "meter" else old,
              status_at=now if fresh == "status" else old)
    assert _detail(client, auth_headers, bid)["status_code"] != "outlet_silent"


def test_tc_os_05_a_silent_cabinet_is_no_contact_not_outlet_silent(client, auth_headers, setup):
    pid, bid = setup
    old = datetime.utcnow() - OLD
    _reported(pid, meter_at=old, status_at=old)
    assert _detail(client, auth_headers, bid, heartbeat_age_s=600)["status_code"] == "no_contact"
