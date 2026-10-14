"""TC-RC-01..07 — row controls: the payload offers exactly what the endpoint will do (block 4).

Every facility on the marina payload (power per berth, each water outlet, the light) carries
`action` ("on" / "off" / null) and, when null, ONE `unavailable_reason`. The UI renders a
button for the action, or the reason's sentence and no control element.

  TC-RC-01  a smart pedestal out of contact says `no_contact` — it said "standalone", i.e.
            "the pedestal is switching this itself", about a pedestal nobody can reach
  TC-RC-02  a read-only account is offered nothing (`read_only`); a control account is
  TC-RC-03  power: running -> off; plug waiting -> on; nothing plugged -> `nothing_plugged`
  TC-RC-04  water (§15): no reservation -> `needs_scan`; a live one -> on; an expired one ->
            `needs_scan`; and the GET does not write (the expired row is left as it was)
  TC-RC-05  the light offers the opposite of its state
  TC-RC-06  AGREEMENT: every offered action is ACCEPTED by its endpoint, and the two
            facility-level refusals are REFUSED by it — the offer cannot drift from the truth
  TC-RC-07  the water refusal is a sentence a person can act on, not only API names
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from conftest import TestSession as _S, TestUserSession as _US

CAB = "RC_CAB_01"


def _headers(role: str) -> dict:
    from app.auth.models import User
    from app.auth.password import hash_password
    from app.auth.tokens import create_access_token
    db = _US()
    try:
        email = f"rc-{role}@test.local"
        u = db.query(User).filter(User.email == email).first()
        if u is None:
            u = User(email=email, password_hash=hash_password("rc-pass-1234"), role=role,
                     is_active=True)
            db.add(u); db.commit(); db.refresh(u)
        return {"Authorization": f"Bearer {create_access_token(u.id, u.email, role)}"}
    finally:
        db.close()


@pytest.fixture(scope="module")
def rig(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    from app.models.valve_config import ValveConfig
    from app.auth.berth_models import Berth
    r = client.post("/api/pedestals/", json={"name": "RC Pedestal", "location": "Dock R",
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
        cfg.opta_client_id = CAB
        cfg.led_on = True
        if db.query(SocketConfig).filter(SocketConfig.pedestal_id == pid,
                                         SocketConfig.socket_id == 1).first() is None:
            db.add(SocketConfig(pedestal_id=pid, socket_id=1, auto_activate=False))
        if db.query(ValveConfig).filter(ValveConfig.pedestal_id == pid,
                                        ValveConfig.valve_id == 1).first() is None:
            db.add(ValveConfig(pedestal_id=pid, valve_id=1))
        db.commit()
    finally:
        db.close()
    udb = _US()
    try:
        b = Berth(name="RC 1", pedestal_id=pid, berth_number=1)
        udb.add(b); udb.commit()
        bid = b.id
    finally:
        udb.close()
    r = client.put(f"/api/marina/berth-assignments/{pid}", headers=auth_headers,
                   json={"assignments": [{"berth_id": bid, "socket_id": 1}]})
    assert r.status_code == 200, r.text
    return pid, bid


def _state(pid, *, plug: bool | None = False, running: bool = False, valve: str = "idle",
           reservation: str | None = None, smart: bool = True):
    """plug: True = connected, False = not, None = never reported (stale)."""
    from app.models.pedestal_config import PedestalConfig, SocketState
    from app.models.socket_config import SocketConfig
    from app.models.valve_config import ValveConfig
    from app.models.session import Session
    from app.models.nfc_pending_session import NfcPendingSession
    now = datetime.utcnow()
    db = _S()
    try:
        db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).update(
            {"smart_mode": smart})
        db.query(Session).filter(Session.pedestal_id == pid).delete()
        if running:
            db.add(Session(pedestal_id=pid, socket_id=1, type="electricity", status="active",
                           started_at=now - timedelta(minutes=3)))
        db.query(SocketState).filter(SocketState.pedestal_id == pid).delete()
        cfg = db.query(SocketConfig).filter(SocketConfig.pedestal_id == pid,
                                            SocketConfig.socket_id == 1).first()
        cfg.meter_load_updated_at = now if plug is not None else None
        if plug is not None:
            db.add(SocketState(pedestal_id=pid, socket_id=1, connected=plug, updated_at=now))
        v = db.query(ValveConfig).filter(ValveConfig.pedestal_id == pid,
                                         ValveConfig.valve_id == 1).first()
        v.last_state, v.state_updated_at = valve, now
        db.query(NfcPendingSession).filter(NfcPendingSession.cabinet_id == CAB).delete()
        if reservation is not None:
            exp = now + timedelta(minutes=4) if reservation == "live" else now - timedelta(minutes=1)
            db.add(NfcPendingSession(nfc_tag_id="erp", user_id="ERP-RC", cabinet_id=CAB,
                                     socket_id="V1", created_at=now - timedelta(minutes=1),
                                     expires_at=exp, status="pending"))
        db.commit()
    finally:
        db.close()


def _core(client, headers, pid, *, heartbeat_age_s=1):
    from app.services.mqtt_handlers import last_heartbeat
    if heartbeat_age_s is None:
        last_heartbeat.pop(pid, None)
    else:
        last_heartbeat[pid] = datetime.utcnow() - timedelta(seconds=heartbeat_age_s)
    try:
        r = client.get("/api/marina/berths", headers=headers)
    finally:
        last_heartbeat.pop(pid, None)
    assert r.status_code == 200, r.text
    ped = next(p for p in r.json()["pedestals"] if p["pedestal_id"] == pid)
    return ped["berths"][0]["power"], ped["water_outlets"][0], ped["light"]


def _offer(x):
    return x["action"], x["unavailable_reason"], x["available"]


def test_tc_rc_01_out_of_contact_is_not_standalone(client, auth_headers, rig):
    pid, _ = rig
    _state(pid, plug=True, running=True)
    power, water, light = _core(client, auth_headers, pid, heartbeat_age_s=None)
    for f in (power, water, light):
        assert _offer(f) == (None, "no_contact", False), f
    # Control: smart mode really OFF still says standalone.
    _state(pid, plug=True, running=True, smart=False)
    power, _, _ = _core(client, auth_headers, pid)
    assert _offer(power) == (None, "standalone", False), power


def test_tc_rc_02_read_only_is_offered_nothing(client, rig):
    pid, _ = rig
    _state(pid, plug=True, running=True)
    for f in _core(client, _headers("monitor"), pid):
        assert _offer(f) == (None, "read_only", False), f
    power, _, light = _core(client, _headers("monitor_control"), pid)
    assert _offer(power) == ("off", None, True) and _offer(light) == ("off", None, True)


def test_tc_rc_03_power_offers_what_a_tap_can_do(client, auth_headers, rig):
    pid, _ = rig
    _state(pid, plug=True, running=True)
    assert _offer(_core(client, auth_headers, pid)[0]) == ("off", None, True)
    _state(pid, plug=True, running=False)
    assert _offer(_core(client, auth_headers, pid)[0]) == ("on", None, True)
    _state(pid, plug=False, running=False)
    assert _offer(_core(client, auth_headers, pid)[0]) == (None, "nothing_plugged", False)
    _state(pid, plug=None, running=False)
    assert _offer(_core(client, auth_headers, pid)[0]) == (None, "state_unknown", False)


def test_tc_rc_04_water_needs_a_scan_and_the_get_does_not_write(client, auth_headers, rig):
    from app.models.nfc_pending_session import NfcPendingSession
    pid, _ = rig
    _state(pid, reservation=None)
    assert _offer(_core(client, auth_headers, pid)[1]) == (None, "needs_scan", False)
    _state(pid, reservation="live")
    assert _offer(_core(client, auth_headers, pid)[1]) == ("on", None, True)
    _state(pid, reservation="expired")
    assert _offer(_core(client, auth_headers, pid)[1]) == (None, "needs_scan", False)
    db = _S()
    try:
        row = db.query(NfcPendingSession).filter(NfcPendingSession.cabinet_id == CAB).one()
        assert row.status == "pending", "a polling GET wrote to the reservation table"
    finally:
        db.close()


def test_tc_rc_05_light_offers_the_opposite(client, auth_headers, rig):
    from app.models.pedestal_config import PedestalConfig
    pid, _ = rig
    _state(pid)
    for on, action in ((True, "off"), (False, "on")):
        db = _S()
        try:
            db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).update(
                {"led_on": on})
            db.commit()
        finally:
            db.close()
        assert _offer(_core(client, auth_headers, pid)[2]) == (action, None, True)


def test_tc_rc_06_offers_agree_with_the_endpoints(client, auth_headers, rig):
    from app.services.mqtt_handlers import last_heartbeat
    pid, _ = rig
    sock = f"/api/controls/pedestal/{pid}/socket/Q1/cmd"
    valve = f"/api/controls/pedestal/{pid}/water/V1/cmd"
    verb = {"on": "activate", "off": "stop"}

    def tap(url, action):
        last_heartbeat[pid] = datetime.utcnow()
        try:
            return client.post(url, json={"action": verb[action]}, headers=auth_headers)
        finally:
            last_heartbeat.pop(pid, None)

    # Offered -> accepted.
    for kw, url, idx in (({"plug": True, "running": False}, sock, 0),
                         ({"plug": True, "running": True}, sock, 0),
                         ({"reservation": "live"}, valve, 1)):
        _state(pid, **kw)
        f = _core(client, auth_headers, pid)[idx]
        assert f["action"] is not None, (kw, f)
        r = tap(url, f["action"])
        assert r.status_code == 200, f"offered {f['action']} on {url} with {kw}, refused: {r.text}"
    # Not offered for a facility reason -> refused by the endpoint too.
    _state(pid, plug=False, running=False)
    assert _core(client, auth_headers, pid)[0]["unavailable_reason"] == "nothing_plugged"
    assert tap(sock, "on").status_code == 409
    _state(pid, reservation=None)
    assert _core(client, auth_headers, pid)[1]["unavailable_reason"] == "needs_scan"
    assert tap(valve, "on").status_code == 409


def test_tc_rc_07_water_refusal_is_a_sentence(client, auth_headers, rig):
    from app.services.mqtt_handlers import last_heartbeat
    pid, _ = rig
    _state(pid, reservation=None)
    last_heartbeat[pid] = datetime.utcnow()
    try:
        r = client.post(f"/api/controls/pedestal/{pid}/water/V1/cmd",
                        json={"action": "activate"}, headers=auth_headers)
    finally:
        last_heartbeat.pop(pid, None)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "scanned at this valve" in detail, detail
