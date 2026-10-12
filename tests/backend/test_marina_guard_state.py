"""Guard on /marina reads the guard service's reconciled state — block 3, 2026-10-12.

`routers/marina.py` imported `services.guard_state.current_guard_state`, which did not exist; the
ImportError was caught and EVERY pedestal read "Guard unavailable" whatever the guard was doing.
The state already existed: `guard.service.effective_state` reconciles the backend's intent with
the worker's liveness (desired ARMED + silent worker → UNAVAILABLE, never ARMED). Now
`services/guard_state.py` reads it per pedestal and the marina maps it to its four words.

  TC-MGS-01  desired OFF                         → off
  TC-MGS-02  ARMED, worker alive, reports ARMED  → on
  TC-MGS-03  ARMED, worker silent                → unavailable (the liveness guarantee)
  TC-MGS-04  ARMED + limited_visibility flag     → paused, "too dark"
  TC-MGS-05  desired SUSPENDED_CPU               → paused, "busy"
  TC-MGS-06  two cameras: one silent             → unavailable (the worse one wins)

TC-MGS-01/02/04/05 FAIL on the code before this change (shown 2026-10-12): it said
"unavailable" for all of them.
"""
from __future__ import annotations

import time

import pytest

from conftest import TestSession as _S

CAMS = (9401, 9402)


@pytest.fixture(scope="module")
def berth(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig
    from app.auth.berth_models import Berth
    from conftest import TestUserSession as _US
    r = client.post("/api/pedestals/", json={"name": "MGS Pedestal", "location": "Dock G",
                                              "data_mode": "real"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    db = _S()
    try:
        if db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first() is None:
            db.add(PedestalConfig(pedestal_id=pid))
            db.commit()
    finally:
        db.close()
    udb = _US()
    try:
        b = Berth(name="MGS 1", pedestal_id=pid, berth_number=1)
        udb.add(b)
        udb.commit()
        return pid, b.id
    finally:
        udb.close()


@pytest.fixture(autouse=True)
def _clean(berth):
    from app.guard.models import GuardConfig
    from app.guard.service import liveness
    pid, _ = berth
    db = _S()
    try:
        db.query(GuardConfig).filter(GuardConfig.camera_id.in_(CAMS)).delete()
        db.commit()
    finally:
        db.close()
    for c in CAMS:
        liveness.forget(c)
    _ctx["pid"], _ctx["bid"] = berth
    yield
    for c in CAMS:
        liveness.forget(c)


_ctx: dict = {}
_client: dict = {}


@pytest.fixture(autouse=True)
def _http(client, auth_headers):
    _client["c"], _client["h"] = client, auth_headers


def _cam(camera_id, desired, *, alive=False, reported=None):
    from app.guard.models import GuardConfig
    from app.guard.service import liveness
    db = _S()
    try:
        db.add(GuardConfig(camera_id=camera_id, pedestal_id=_ctx["pid"], desired_state=desired))
        db.commit()
    finally:
        db.close()
    if alive:
        liveness.mark_seen(camera_id, time.time())
    if reported is not None:
        liveness.set_reported(camera_id, reported)


def _block():
    r = _client["c"].get(f"/api/marina/berths/{_ctx['bid']}", headers=_client["h"])
    assert r.status_code == 200, r.text
    return r.json()["guard"]


def test_tc_mgs_01_off():
    _cam(CAMS[0], "OFF")
    assert _block()["state"] == "off"


def test_tc_mgs_02_armed_and_answering_is_on():
    _cam(CAMS[0], "ARMED", alive=True, reported={"state": "ARMED", "flags": []})
    assert _block()["state"] == "on"


def test_tc_mgs_03_armed_but_silent_is_unavailable_never_on():
    _cam(CAMS[0], "ARMED", alive=False, reported={"state": "ARMED", "flags": []})
    assert _block()["state"] == "unavailable"


def test_tc_mgs_04_too_dark_is_paused():
    _cam(CAMS[0], "ARMED", alive=True,
         reported={"state": "ARMED", "flags": ["limited_visibility"]})
    b = _block()
    assert b["state"] == "paused" and "dark" in b["sentence"], b


def test_tc_mgs_05_suspended_for_cpu_is_paused():
    _cam(CAMS[0], "SUSPENDED_CPU")
    b = _block()
    assert b["state"] == "paused" and "busy" in b["sentence"], b


def test_tc_mgs_06_two_cameras_the_worse_one_wins():
    _cam(CAMS[0], "ARMED", alive=True, reported={"state": "ARMED", "flags": []})
    _cam(CAMS[1], "ARMED", alive=False)
    assert _block()["state"] == "unavailable"
