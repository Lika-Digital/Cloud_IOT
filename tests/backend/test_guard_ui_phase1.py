"""TC-GU — Guard UI phase 1, the backend half (spec §5.5, owner 2026-10-16).

Every test here failed on the code before the build (shown 2026-10-16 with the old code checked
out). The UI half — the button, playback, "Not measured" on the page — is `e2e/guard.spec.ts`.

  TC-GU-01..04, 14  one sentence per state: over the whole grid of guard facts each sentence comes
                    out exactly for its condition (§5.5.1 S1..S5), and no state has two
  TC-GU-05          a worker restart: re-armed once, "not answering" until it confirms
  TC-GU-06          a lost acknowledgement is "not answering"
  TC-GU-07          arm / switch off / rearm / config: admin only in the API
  TC-GU-09          the row is created by the worker's live announce, never by a replay or REST
  TC-GU-10          the alarm comes from guard events, not from the alarm table
  TC-GU-11          the event list, frames, recordings and labels: admin only in the API
  TC-GU-13          a failed reading is "Not measured", never "unavailable" or zero
  TC-GU-15          the API and the marina page give the same sentence for the same state
  TC-GU-16          a pause is lifted only by a LIVE ARMED, and the pause and the resume are listed
  TC-GU-17          switched off but recording: said aloud (S6), one switch-off, 5 s → S2, OFF → S4
  TC-GU-18          switched off: a pause reads "Guard off" and is listed; an unknown state reads
                    "Not measured", is logged and listed (Q4b, S4b / S7)
"""
from __future__ import annotations

import asyncio
import itertools
import json
import time
from datetime import datetime
from unittest.mock import patch

import pytest

from conftest import TestSession as _S
from conftest import TestUserSession as _US

S1 = "No guard on this pedestal"
S2 = "Guard not answering"
S3 = "Guard on"
S4 = "Guard off"
S5_CPU = "Guard paused — processor overloaded"
S5_DARK = "Guard paused — too dark to see"
S5_UNKNOWN = "Guard paused — reason not reported"
S6 = "Guard recording although switched off"
NOT_MEASURED = "Not measured"

ON_SET = ("ARMING", "ARMED", "ALARM", "RECORDING")
CAM_GRID = 9611          # the grid's camera; its pedestal is GRID_PID
GRID_PID = 9611
CAM = 9612               # the flow tests' camera


# ── helpers ──────────────────────────────────────────────────────────────────

def _headers(role: str) -> dict:
    from app.auth.models import User
    from app.auth.password import hash_password
    from app.auth.tokens import create_access_token
    db = _US()
    try:
        email = f"gu-{role}@test.local"
        u = db.query(User).filter(User.email == email).first()
        if u is None:
            u = User(email=email, password_hash=hash_password("gu-pass-1234"), role=role,
                     is_active=True)
            db.add(u)
            db.commit()
            db.refresh(u)
        return {"Authorization": f"Bearer {create_access_token(u.id, u.email, role)}"}
    finally:
        db.close()


def _forget(cam: int) -> None:
    from app.guard.service import liveness
    liveness.forget(cam)
    for rid in [r for r, (c, _t) in list(liveness._pending_acks.items()) if c == cam]:
        liveness._pending_acks.pop(rid, None)


def _wipe(cam: int) -> None:
    from app.guard import models as gm
    db = _S()
    try:
        for name in ("GuardEvent", "GuardDetection", "GuardRecording", "GuardStateEvent"):
            model = getattr(gm, name, None)
            if model is not None:
                db.query(model).filter(model.camera_id == cam).delete(synchronize_session=False)
        db.query(gm.GuardConfig).filter(gm.GuardConfig.camera_id == cam).delete(
            synchronize_session=False)
        db.commit()
    finally:
        db.close()
    _forget(cam)


def _row(cam: int, pid: int, desired: str) -> None:
    from app.guard.models import GuardConfig
    db = _S()
    try:
        cfg = db.get(GuardConfig, cam)
        if cfg is None:
            cfg = GuardConfig(camera_id=cam, pedestal_id=pid, desired_state=desired)
            db.add(cfg)
        cfg.desired_state = desired
        cfg.pedestal_id = pid
        db.commit()
    finally:
        db.close()


def _desired(cam: int) -> str | None:
    from app.guard.models import GuardConfig
    db = _S()
    try:
        cfg = db.get(GuardConfig, cam)
        return cfg.desired_state if cfg is not None else None
    finally:
        db.close()


async def _noop(*a, **k):
    return None


def _run(coro_fn, *args, **kw):
    with patch("app.database.SessionLocal", _S), \
         patch("app.services.websocket_manager.ws_manager.broadcast", new=_noop):
        return asyncio.run(coro_fn(*args, **kw))


def _feed(cam: int, leaf: str, data: dict, *, retained: bool = False) -> None:
    from app.config import settings
    from app.guard import service as svc
    data = {"instance": settings.guard_instance_id, **data}
    _run(svc.handle_guard_message, f"{svc.topic_base(cam)}/{leaf}", json.dumps(data),
         retained=retained)


def _overdue_now() -> None:
    from app.guard import service as svc
    _run(svc.check_overdue_acks)


def _sentence(pid: int) -> str:
    from app.routers.marina import _guard_block
    db = _S()
    try:
        return _guard_block(db, pid)["sentence"]
    finally:
        db.close()


@pytest.fixture
def published():
    sent: list[tuple[str, dict]] = []

    def fake_publish(topic, payload, qos=1, *a, **k):
        if "/guard/cmd" in topic:
            sent.append((topic, json.loads(payload)))

    with patch("app.services.mqtt_client.mqtt_service.publish", side_effect=fake_publish):
        yield sent


# ── the grid (TC-GU-01..04, 14) ──────────────────────────────────────────────

ROWS = (False, True)
DESIRED = ("OFF", "ARMED", "SUSPENDED_CPU")
WORKER = ("live", "stale", "never", "will")
REPORTED = (None, "OFF", "ARMING", "ARMED", "ALARM", "RECORDING", "SUSPENDED_CPU", "NO_DISK")
ACK = ("none", "waiting", "overdue")


def _facts():
    for row in ROWS:
        if not row:
            yield (False, None, "never", None, False, "none")
            continue
        for desired, worker, reported, ack in itertools.product(DESIRED, WORKER, REPORTED, ACK):
            for limited in ((False, True) if reported in ON_SET else (False,)):
                yield (True, desired, worker, reported, limited, ack)


def _expected(f) -> str | None:
    """§5.5.1, written as a function. None = an OPEN cell (§5.5.8 Q4), not asserted."""
    row, desired, worker, reported, limited, ack = f
    if not row:
        return S1
    if worker != "live" or ack == "overdue" or reported is None:
        return S2

    def by_report() -> str:
        if reported == "OFF":
            return S4
        if reported in ON_SET:
            return S5_DARK if limited else S3
        if reported == "SUSPENDED_CPU":
            return S5_CPU
        return S5_UNKNOWN

    if ack == "waiting":                       # a person's command: the reported state alone
        return by_report()
    if desired == "OFF":
        if reported == "OFF":
            return S4
        if reported in ON_SET:
            return S6                                     # S6, owner 2026-10-16
        if reported == "SUSPENDED_CPU":
            return S4                                     # S4b: nothing records, as asked
        return NOT_MEASURED                               # S7: a state we cannot read
    if desired == "SUSPENDED_CPU":
        return S5_CPU
    # desired ARMED
    if reported == "OFF":
        return S2
    return by_report()


def _apply(f) -> None:
    from app.guard.service import liveness
    row, desired, worker, reported, limited, ack = f
    _wipe(CAM_GRID)
    if not row:
        return
    _row(CAM_GRID, GRID_PID, desired)
    now = time.time()
    if reported is not None:
        liveness.set_reported(CAM_GRID, {"state": reported,
                                         "flags": ["limited_visibility"] if limited else []})
    if worker == "live":
        liveness.mark_seen(CAM_GRID, now)
    elif worker == "stale":
        liveness.mark_seen(CAM_GRID, now - 20)
    elif worker == "will":
        liveness.mark_seen(CAM_GRID, now)
        liveness.mark_gone(CAM_GRID)
    if ack == "waiting":
        liveness.expect_ack(f"gu-wait-{CAM_GRID}", CAM_GRID, now)
    elif ack == "overdue":
        liveness.expect_ack(f"gu-late-{CAM_GRID}", CAM_GRID, now - 10)
        _overdue_now()


@pytest.fixture(scope="module")
def grid(client):
    out = []
    try:
        for f in _facts():
            _apply(f)
            out.append((f, _expected(f), _sentence(GRID_PID)))
    finally:
        _wipe(CAM_GRID)
    return out


def _check_sentence(grid, sentence: str) -> None:
    decided = [(f, e, a) for f, e, a in grid if e is not None]
    wrong_out = [(f, a) for f, e, a in decided if e == sentence and a != sentence]
    wrong_in = [(f, a) for f, e, a in decided if e != sentence and a == sentence]
    assert not wrong_out and not wrong_in, (
        f"{sentence!r}: should be said but was not ({len(wrong_out)}): {wrong_out[:6]}; "
        f"said where it must not be ({len(wrong_in)}): {wrong_in[:6]}")


def test_grid_is_the_whole_space_and_the_open_cells_are_named(grid):
    open_cells = [f for f, e, _a in grid if e is None]
    assert len(grid) == 1 + 3 * 4 * 3 * (8 + 4)        # no row, + every row combination
    # Q4b answered 2026-10-16 (S4b, S7): no cell is open any more.
    assert open_cells == []
    assert all(f[1] == "OFF" and f[2] == "live" and f[5] == "none" for f in open_cells)


def test_tc_gu_01_no_guard_exactly_when_there_is_no_row(grid):
    _check_sentence(grid, S1)


def test_tc_gu_02_not_answering_exactly_for_its_condition(grid):
    _check_sentence(grid, S2)


def test_tc_gu_03_guard_on_exactly_for_its_condition(grid):
    _check_sentence(grid, S3)


def test_tc_gu_04_guard_off_exactly_for_its_condition(grid):
    _check_sentence(grid, S4)


def test_tc_gu_17_recording_although_off_exactly_for_its_condition(grid):
    _check_sentence(grid, S6)


def test_tc_gu_18_unknown_state_is_not_measured_exactly_for_its_condition(grid):
    _check_sentence(grid, NOT_MEASURED)


def test_tc_gu_14_paused_exactly_for_its_condition_and_never_bare(grid):
    for s in (S5_CPU, S5_DARK, S5_UNKNOWN):
        _check_sentence(grid, s)
    said = {a for _f, _e, a in grid}
    assert "Guard paused" not in said
    assert all(not a.startswith("Guard paused") or a in (S5_CPU, S5_DARK, S5_UNKNOWN)
               for a in said), said


def test_every_decided_state_has_exactly_one_sentence(grid):
    """The same facts twice give the same sentence — no state is spoken two ways."""
    seen: dict = {}
    for f, e, a in grid:
        if e is None:
            continue
        assert seen.setdefault(f, a) == a


# ── flows ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def cam(client):
    _wipe(CAM)
    yield CAM
    _wipe(CAM)


def test_tc_gu_05_worker_restart_is_rearmed_and_not_answering_until_confirmed(cam, published):
    from app.guard.service import liveness
    _row(cam, 61, "ARMED")
    _feed(cam, "state", {"state": "ARMED", "flags": [], "pedestal_id": 61})
    assert _sentence(61) == S3, "precondition: armed and watching"

    # the worker restarts: it comes up OFF and announces itself, live
    _feed(cam, "state", {"state": "OFF", "flags": [], "reason": "worker started",
                         "pedestal_id": 61})
    arms = [p for _t, p in published if p["cmd"] == "arm"]
    assert len(arms) == 1, f"one arm, sent by the backend itself: {published}"
    assert _sentence(61) == S2, "until the worker confirms, never on and never off"

    _feed(cam, "ack", {"req_id": arms[0]["req_id"], "accepted": True, "state": "ARMED"})
    _feed(cam, "state", {"state": "ARMED", "flags": [], "pedestal_id": 61})
    assert _sentence(61) == S3

    # the announce lost: the backend still holds ARMED, a live health says OFF
    _forget(cam)
    liveness.set_reported(cam, {"state": "ARMED", "flags": []})
    liveness.mark_seen(cam)
    _feed(cam, "health", {"state": "OFF", "cpu_pct_now": 3.0})
    assert _sentence(61) != S3, "a worker that is OFF must never read 'Guard on'"
    assert _sentence(61) == S2


def test_tc_gu_05_control_a_suspended_guard_is_never_rearmed_by_a_restart(cam, published):
    _row(cam, 61, "SUSPENDED_CPU")
    _feed(cam, "state", {"state": "OFF", "flags": [], "reason": "worker started",
                         "pedestal_id": 61})
    assert not [p for _t, p in published if p["cmd"] in ("arm", "rearm")], published
    assert _desired(cam) == "SUSPENDED_CPU"


def _overdue(cam: int) -> None:
    from app.guard.service import liveness
    for rid, (c, _sent) in list(liveness._pending_acks.items()):
        if c == cam:
            liveness._pending_acks[rid] = (c, time.time() - 10)
    _overdue_now()


def _reason(client, cam: int) -> str:
    body = client.get("/api/guard/status", headers=_headers("admin")).json()
    return next(c for c in body["cameras"] if c["camera_id"] == cam)["reason"] or ""


def test_tc_gu_06_a_lost_arm_is_not_answering(client, cam, published):
    _row(cam, 62, "OFF")
    _feed(cam, "state", {"state": "OFF", "flags": [], "pedestal_id": 62})
    assert client.post(f"/api/guard/{cam}/enable", headers=_headers("admin")).status_code == 202
    _overdue(cam)
    assert _sentence(62) == S2
    assert "did not acknowledge" in _reason(client, cam)


def test_tc_gu_06_a_lost_switch_off_is_not_answering(client, cam, published):
    _row(cam, 62, "ARMED")
    _feed(cam, "state", {"state": "ARMED", "flags": [], "pedestal_id": 62})
    assert client.post(f"/api/guard/{cam}/disable", headers=_headers("admin")).status_code == 202
    _overdue(cam)
    assert _sentence(62) == S2
    assert "did not acknowledge" in _reason(client, cam)


def test_tc_gu_06_control_an_ack_in_time_is_not_a_fault(client, cam, published):
    _row(cam, 62, "OFF")
    _feed(cam, "state", {"state": "OFF", "flags": [], "pedestal_id": 62})
    client.post(f"/api/guard/{cam}/enable", headers=_headers("admin"))
    cmd = [p for _t, p in published if p["cmd"] == "arm"][-1]
    _feed(cam, "ack", {"req_id": cmd["req_id"], "accepted": True, "state": "ARMED"})
    _feed(cam, "state", {"state": "ARMED", "flags": [], "pedestal_id": 62})
    _overdue_now()
    assert _sentence(62) == S3


CONTROL = [("post", "enable", None), ("post", "disable", None), ("post", "rearm", None),
           ("patch", "config", {"fps": 2})]


@pytest.mark.parametrize("role", ["monitor_control", "monitor"])
def test_tc_gu_07_arm_and_switch_off_are_admin_only_in_the_api(client, cam, published, role):
    _row(cam, 63, "OFF")
    for method, leaf, body in CONTROL:
        r = getattr(client, method)(f"/api/guard/{cam}/{leaf}", headers=_headers(role),
                                    **({"json": body} if body else {}))
        assert r.status_code == 403, (role, leaf, r.status_code, r.text)
    assert not published, "a refused command must not reach the worker"
    # control: admin is accepted on the same row
    for method, leaf, body in CONTROL:
        r = getattr(client, method)(f"/api/guard/{cam}/{leaf}", headers=_headers("admin"),
                                    **({"json": body} if body else {}))
        assert r.status_code in (200, 202), (leaf, r.status_code, r.text)


def test_tc_gu_09_the_row_comes_from_the_live_announce_only(client, cam, published):
    _feed(cam, "state", {"state": "OFF", "flags": [], "pedestal_id": 64}, retained=True)
    assert _desired(cam) is None, "a retained replay must never create a row"
    assert _sentence(64) == S1

    r = client.post(f"/api/guard/{cam}/enable", headers=_headers("admin"))
    assert r.status_code == 404 and S1 in r.text, r.text
    assert _desired(cam) is None, "REST must not create the row"

    _feed(cam, "state", {"state": "OFF", "flags": []})            # no pedestal_id
    assert _desired(cam) is None, "without its pedestal the worker creates no row"

    _feed(cam, "state", {"state": "OFF", "flags": [], "pedestal_id": 64})
    assert _desired(cam) == "OFF"
    assert _sentence(64) == S4


# ── the alarm (TC-GU-10) ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def marina_rig(client, auth_headers):
    from app.auth.berth_models import Berth
    from app.models.pedestal_config import PedestalConfig
    r = client.post("/api/pedestals/", json={"name": "GU Pedestal", "location": "Dock U",
                                              "data_mode": "real"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        # In contact and in smart mode, so nothing ranked above guard (rank 1 no contact,
        # rank 2 standalone) hides what these tests read — otherwise a berth that never shows
        # rank 7 would pass "the customer alarm is not the guard sentence" vacuously.
        cfg.smart_mode = True
        db.commit()
    finally:
        db.close()
    udb = _US()
    try:
        ids = []
        for n in (1, 2):
            b = Berth(name=f"GU {n}", pedestal_id=pid, berth_number=n)
            udb.add(b)
            udb.commit()
            ids.append(b.id)
    finally:
        udb.close()
    return pid, ids


def _berth_codes(client, pid: int) -> list[str]:
    from app.services.mqtt_handlers import last_heartbeat
    last_heartbeat[pid] = datetime.utcnow()
    body = client.get("/api/marina/berths", headers=_headers("monitor")).json()
    ped = next(p for p in body["pedestals"] if p["pedestal_id"] == pid)
    return [b["status_code"] for b in ped["berths"]]


def test_tc_gu_10_the_alarm_comes_from_guard_events(client, marina_rig):
    from app.guard.models import GuardEvent
    from app.models.active_alarm import ActiveAlarm
    pid, _ids = marina_rig
    cam = 9613
    _wipe(cam)
    db = _S()
    try:
        db.query(ActiveAlarm).filter(ActiveAlarm.pedestal_id == pid).delete()
        ev = GuardEvent(event_uuid="gu10-1", camera_id=cam, pedestal_id=pid,
                        detected_at_utc=datetime.utcnow(), confidence=0.9)
        db.add(ev)
        db.commit()
        eid = ev.id
    finally:
        db.close()
    try:
        codes = _berth_codes(client, pid)
        assert len(codes) >= 2 and set(codes) == {"guard_unreviewed"}, \
            f"every berth of the pedestal, from the unlabelled event: {codes}"
        alarms = client.get("/api/marina/alarms", headers=_headers("monitor")).json()["alarms"]
        mine = [a for a in alarms if a["pedestal_id"] == pid]
        assert [(a["sentence"], a["active"]) for a in mine] == \
            [("Someone was seen — needs checking", True)], mine

        r = client.post(f"/api/guard/events/{eid}/label", headers=_headers("admin"),
                        json={"label": "false_alarm"})
        assert r.status_code == 200, r.text
        assert "guard_unreviewed" not in _berth_codes(client, pid)
        alarms = client.get("/api/marina/alarms", headers=_headers("monitor")).json()["alarms"]
        assert [a["active"] for a in alarms if a["pedestal_id"] == pid] == [False]
    finally:
        _wipe(cam)


def test_tc_gu_10_the_customer_alarm_is_not_the_guard_sentence(client, marina_rig):
    from app.models.active_alarm import ActiveAlarm
    pid, _ids = marina_rig
    db = _S()
    try:
        db.query(ActiveAlarm).filter(ActiveAlarm.pedestal_id == pid).delete()
        db.add(ActiveAlarm(pedestal_id=pid, alarm_type="unauthorized_entry", status="triggered",
                           source="customer_mobile", message="Unauthorized Entry reported",
                           triggered_at=datetime.utcnow()))
        db.commit()
    finally:
        db.close()
    try:
        codes = _berth_codes(client, pid)
        assert codes and "guard_unreviewed" not in codes, codes
        alarms = client.get("/api/marina/alarms", headers=_headers("monitor")).json()["alarms"]
        sentences = [a["sentence"] for a in alarms if a["pedestal_id"] == pid]
        assert "Someone was seen — needs checking" not in sentences, sentences
    finally:
        db = _S()
        try:
            db.query(ActiveAlarm).filter(ActiveAlarm.pedestal_id == pid).delete()
            db.commit()
        finally:
            db.close()


# ── admin only (TC-GU-11) ─────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["monitor_control", "monitor"])
def test_tc_gu_11_what_guard_saw_is_admin_only_in_the_api(client, cam, role):
    from app.guard.models import GuardDetection, GuardEvent
    db = _S()
    try:
        ev = GuardEvent(event_uuid=f"gu11-{role}", camera_id=cam, pedestal_id=65,
                        detected_at_utc=datetime.utcnow(), confidence=0.9)
        det = GuardDetection(camera_id=cam, detected_at=datetime.utcnow(), confidence=0.4,
                             band="uncertain")
        db.add_all([ev, det])
        db.commit()
        eid, did = ev.id, det.id
    finally:
        db.close()
    h = _headers(role)
    for path in ("/api/guard/events", f"/api/guard/events/{eid}/frame",
                 f"/api/guard/events/{eid}/video", "/api/guard/detections",
                 f"/api/guard/detections/{did}/frame"):
        assert client.get(path, headers=h).status_code == 403, (role, path)
    r = client.post(f"/api/guard/events/{eid}/label", headers=h, json={"label": "correct"})
    assert r.status_code == 403, (role, r.status_code)
    assert client.get("/api/guard/status", headers=h).status_code == 200
    # control: admin reads the list
    assert client.get("/api/guard/events", headers=_headers("admin")).status_code == 200


# ── not measured (TC-GU-13) ───────────────────────────────────────────────────

def test_tc_gu_13_a_failed_reading_is_not_measured(client):
    def boom(*a, **k):
        raise RuntimeError("the guard state could not be read")

    with patch("app.services.guard_state.current_guard_state", side_effect=boom):
        from app.routers.marina import _guard_block
        db = _S()
        try:
            g = _guard_block(db, 1)
        finally:
            db.close()
    assert (g["state"], g["sentence"]) == ("not_measured", NOT_MEASURED), g


def test_tc_gu_13_unreadable_guard_events_are_not_measured_not_zero(client):
    def boom(*a, **k):
        raise RuntimeError("guard_events could not be read")

    with patch("app.routers.marina._guard_alarm_rows", side_effect=boom):
        r = client.get("/api/marina/alarms", headers=_headers("monitor"))
    assert r.status_code == 200, r.text
    assert r.json()["guard"] == {"measured": False, "sentence": NOT_MEASURED}, r.json()


# ── the same sentence in the API and on the page (TC-GU-15) ───────────────────

def test_tc_gu_15_the_api_and_the_page_give_the_same_sentence(client, marina_rig):
    from app.guard.service import liveness
    pid, _ids = marina_rig
    cam = 9614
    states = [("ARMED", "OFF")]            # the worker-restart state first
    states += [(d, r) for d in ("OFF", "ARMED", "SUSPENDED_CPU")
               for r in ("OFF", "ARMED", "SUSPENDED_CPU", "NO_DISK")]
    try:
        for desired, reported in states:
            _wipe(cam)
            _row(cam, pid, desired)
            liveness.set_reported(cam, {"state": reported, "flags": []})
            liveness.mark_seen(cam)
            status = client.get("/api/guard/status", headers=_headers("monitor")).json()
            api = next(c for c in status["cameras"] if c["camera_id"] == cam)
            page = next(p for p in client.get("/api/marina/berths",
                                              headers=_headers("monitor")).json()["pedestals"]
                        if p["pedestal_id"] == pid)["guard"]
            assert "sentence" in api, f"/api/guard/status gives no sentence: {api}"
            assert api["sentence"] == page["sentence"], (desired, reported, api, page)
    finally:
        _wipe(cam)


# ── auto-resume (TC-GU-16) ────────────────────────────────────────────────────

def test_tc_gu_16_a_retained_armed_never_lifts_a_pause(cam, published):
    _row(cam, 66, "SUSPENDED_CPU")
    _feed(cam, "state", {"state": "OFF", "flags": [], "pedestal_id": 66})
    _feed(cam, "state", {"state": "ARMED", "flags": [], "pedestal_id": 66}, retained=True)
    assert _desired(cam) == "SUSPENDED_CPU"
    assert _sentence(66) == S5_CPU


def test_tc_gu_16_a_live_armed_lifts_the_pause_and_both_are_listed(client, cam, published):
    _row(cam, 66, "ARMED")
    _feed(cam, "state", {"state": "ARMED", "flags": [], "pedestal_id": 66})
    _feed(cam, "state", {"state": "SUSPENDED_CPU", "flags": [], "pedestal_id": 66,
                         "reason": "60 s average CPU 91 % above 85 %"})
    assert _desired(cam) == "SUSPENDED_CPU" and _sentence(66) == S5_CPU
    _feed(cam, "state", {"state": "ARMED", "flags": [], "pedestal_id": 66,
                         "reason": "CPU back below 45 %"})
    assert _desired(cam) == "ARMED"
    assert _sentence(66) == S3
    body = client.get("/api/guard/events", headers=_headers("admin"),
                      params={"camera_id": cam}).json()
    assert [e["kind"] for e in body["events"]] == ["auto_resumed", "paused_cpu"], body


# ── switched off, but recording (TC-GU-17) ────────────────────────────────────

def _disarms(published) -> list[dict]:
    return [p for _t, p in published if p["cmd"] == "disarm"]


def test_tc_gu_17_recording_although_off_is_said_and_switched_off_once(cam, published):
    _row(cam, 67, "OFF")
    _feed(cam, "state", {"state": "OFF", "flags": [], "pedestal_id": 67})
    assert _sentence(67) == S4

    _feed(cam, "state", {"state": "ARMED", "flags": [], "pedestal_id": 67})
    assert _sentence(67) == S6
    assert len(_disarms(published)) == 1, "the backend sends the switch-off once"
    # more live messages saying the same: still S6, still ONE switch-off
    _feed(cam, "health", {"state": "ARMED", "cpu_pct_now": 4.0})
    _feed(cam, "state", {"state": "RECORDING", "flags": [], "pedestal_id": 67})
    _feed(cam, "health", {"state": "RECORDING", "cpu_pct_now": 4.0})
    assert _sentence(67) == S6
    assert len(_disarms(published)) == 1, f"switch-off sent {len(_disarms(published))} times"

    # not confirmed within 5 s → not answering; and no further switch-off
    _overdue(cam)
    assert _sentence(67) == S2
    _feed(cam, "health", {"state": "RECORDING", "cpu_pct_now": 4.0})
    assert _sentence(67) == S2 and len(_disarms(published)) == 1

    # the worker finally reports OFF → off
    _feed(cam, "state", {"state": "OFF", "flags": [], "pedestal_id": 67})
    assert _sentence(67) == S4


def test_tc_gu_17_a_confirmed_switch_off_reads_off(cam, published):
    _row(cam, 67, "OFF")
    _feed(cam, "state", {"state": "ARMED", "flags": [], "pedestal_id": 67})
    assert _sentence(67) == S6
    req = _disarms(published)[0]["req_id"]
    _feed(cam, "ack", {"req_id": req, "accepted": True, "state": "OFF"})
    assert _sentence(67) == S4
    # a new episode later gets its own single switch-off
    _feed(cam, "state", {"state": "ARMED", "flags": [], "pedestal_id": 67})
    assert _sentence(67) == S6 and len(_disarms(published)) == 2


# ── switched off: a pause, and a state we cannot read (TC-GU-18) ──────────────

def _kinds(client, cam: int) -> list[dict]:
    body = client.get("/api/guard/events", headers=_headers("admin"),
                      params={"camera_id": cam}).json()
    return [(e["kind"], e.get("reason")) for e in body["events"]]


def test_tc_gu_18_a_pause_under_a_requested_off_reads_off_and_is_listed(client, cam, published):
    _row(cam, 68, "OFF")
    _feed(cam, "state", {"state": "OFF", "flags": [], "pedestal_id": 68})
    _feed(cam, "state", {"state": "SUSPENDED_CPU", "flags": [], "pedestal_id": 68,
                         "reason": "60 s average CPU 92 %"})
    assert _sentence(68) == S4, "nothing records — what the person asked for"
    assert _sentence(68) != NOT_MEASURED
    assert ("paused_cpu", "60 s average CPU 92 %") in _kinds(client, cam), "the pause is lost"


def test_tc_gu_18_an_unknown_state_reads_not_measured_and_is_logged(client, cam, published, caplog):
    _row(cam, 68, "OFF")
    _feed(cam, "state", {"state": "OFF", "flags": [], "pedestal_id": 68})
    with caplog.at_level("WARNING"):
        _feed(cam, "state", {"state": "CALIBRATING", "flags": [], "pedestal_id": 68})
    assert _sentence(68) == NOT_MEASURED
    assert _sentence(68) not in (S4, S2)
    assert ("unknown_state", "CALIBRATING") in _kinds(client, cam)
    assert any("CALIBRATING" in r.getMessage() for r in caplog.records), "the raw state is not logged"

