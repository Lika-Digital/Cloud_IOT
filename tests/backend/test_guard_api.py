"""
Guard REST + MQTT contract (step 5, v3.42)
=========================================

Step 6 (the guard admin screen) is cancelled and merged into UI v2, so this contract must
already carry everything a UI needs — and **guard must be fully operable from a terminal**,
which is the requirement for the watching week. These tests are the proof of both: every
endpoint is exercised the way `curl` would, with no UI involved.

Two properties matter more than the endpoint list:

  * **The backend is the only DB writer.** The worker publishes; `service.py` persists.
  * **A false ARMED is impossible.** Desired ARMED with a silent worker reports UNAVAILABLE.

  TC-GAPI-01  status is empty-safe and reports the marina id
  TC-GAPI-02  enable returns 202 + req_id and state ARMING, never ARMED
  TC-GAPI-03  ...and publishes a NON-retained cmd carrying the config
  TC-GAPI-04  desired ARMED + silent worker reports UNAVAILABLE, never ARMED
  TC-GAPI-05  an ack from the worker makes it ARMED
  TC-GAPI-06  a heartbeat gap returns it to UNAVAILABLE
  TC-GAPI-07  a RETAINED state replay is last-known only, never liveness
  TC-GAPI-08  disable sets OFF and OFF wins over anything the worker reports
  TC-GAPI-09  rearm is distinct from enable and reports the previous state
  TC-GAPI-10  config PATCH bumps the version and pushes when armed
  TC-GAPI-11  config PATCH rejects an empty uncertain band
  TC-GAPI-12  config PATCH validates the zone
  TC-GAPI-13  an alarm from MQTT is persisted and is idempotent on event_uuid
  TC-GAPI-14  detections persist in a batch; `none` frames write nothing
  TC-GAPI-15  events list paginates, filters by label, counts unlabelled
  TC-GAPI-16  labelling stores actor and time, and is re-labellable
  TC-GAPI-17  monitor (read-only) may label but may NOT arm
  TC-GAPI-18  video: 404 never-existed vs 410 gone vs 404 skipped
  TC-GAPI-19  a missing file self-corrects the row and returns 410
  TC-GAPI-20  frame endpoint serves the annotated JPEG
  TC-GAPI-21  detections endpoint filters by band and confidence
  TC-GAPI-22  recording links onto its event
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from conftest import TestSession as _S

CAM = 7
PED = 7


@pytest.fixture(autouse=True)
def _clean():
    from app.guard.models import GuardConfig, GuardDetection, GuardEvent, GuardRecording
    from app.guard.service import liveness

    liveness.forget(CAM)
    liveness._pending_acks.clear()
    db = _S()
    try:
        for model in (GuardEvent, GuardDetection, GuardRecording):
            db.query(model).filter(model.camera_id == CAM).delete(synchronize_session=False)
        db.query(GuardConfig).filter(GuardConfig.camera_id == CAM).delete(
            synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture
def published():
    """Capture what the backend publishes, so the MQTT contract is asserted not assumed."""
    sent: list[tuple[str, str, int]] = []

    def fake_publish(topic, payload, qos=1):
        sent.append((topic, payload, qos))

    with patch("app.services.mqtt_client.mqtt_service.publish", side_effect=fake_publish):
        yield sent


async def _feed(topic_leaf: str, data: dict, *, retained: bool = False):
    from app.guard.service import handle_guard_message, topic_base
    with patch("app.guard.service.SessionLocal", _S, create=True):
        await handle_guard_message(
            f"{topic_base(CAM)}/{topic_leaf}", json.dumps(data), retained=retained)


def _feed_sync(topic_leaf: str, data: dict, *, retained: bool = False):
    """Drive an inbound MQTT message with the DB and WS patched to the test rig."""
    import asyncio

    from app.guard import service as svc

    async def _noop(*a, **k):
        return None

    with patch("app.database.SessionLocal", _S), \
         patch("app.services.websocket_manager.ws_manager.broadcast", new=_noop):
        asyncio.run(svc.handle_guard_message(
            f"{svc.topic_base(CAM)}/{topic_leaf}", json.dumps(data), retained=retained))


def _cam(client, headers):
    """Ensure a config row exists by arming then disarming."""
    client.post(f"/api/guard/{CAM}/enable", headers=headers)
    client.post(f"/api/guard/{CAM}/disable", headers=headers)


# ═══════════════════════════════════════════════════════════════════════════
# Status + control
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gapi_01_status_is_empty_safe(client, auth_headers):
    r = client.get("/api/guard/status", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "marina_id" in body and isinstance(body["cameras"], list)


def test_tc_gapi_02_03_enable_is_arming_and_publishes_cmd(client, auth_headers, published):
    r = client.post(f"/api/guard/{CAM}/enable", headers=auth_headers)
    assert r.status_code == 202
    body = r.json()
    assert body["state"] == "ARMING", "must NOT claim ARMED before the worker acknowledges"
    assert body["req_id"]

    assert len(published) == 1
    topic, payload, qos = published[0]
    assert topic == f"marina/KRK/camera/{CAM}/guard/cmd"
    assert qos == 1
    cmd = json.loads(payload)
    assert cmd["cmd"] == "arm"
    assert cmd["req_id"] == body["req_id"]
    # The command carries config, so the worker cannot run a stale threshold set.
    assert cmd["config"]["conf_threshold"] == 0.5
    assert cmd["config"]["fps"] == 1.0
    assert cmd["config"]["window_seconds"] == 4.0
    assert cmd["config"]["frames_required"] == 2
    assert cmd["config"]["zone"] == [0.2, 0.2, 0.8, 0.8]


def test_tc_gapi_04_silent_worker_is_unavailable_never_armed(client, auth_headers, published):
    """THE guarantee. Desired ARMED with nobody answering must never render as ARMED."""
    client.post(f"/api/guard/{CAM}/enable", headers=auth_headers)
    cam = _status(client, auth_headers)
    assert cam["desired_state"] == "ARMED"
    assert cam["state"] == "UNAVAILABLE"
    assert cam["worker_alive"] is False
    assert cam["worker_seen_at"] is None
    assert "not responding" in (cam["reason"] or "")


def test_tc_gapi_05_06_ack_then_heartbeat_gap(client, auth_headers, published):
    from app.guard.service import liveness

    client.post(f"/api/guard/{CAM}/enable", headers=auth_headers)
    req_id = json.loads(published[0][1])["req_id"]

    _feed_sync("ack", {"req_id": req_id, "accepted": True, "state": "ARMED"})
    _feed_sync("state", {"state": "ARMED", "flags": [], "config_version": 1})
    cam = _status(client, auth_headers)
    assert cam["state"] == "ARMED"
    assert cam["worker_alive"] is True

    # Silence past the heartbeat timeout -> UNAVAILABLE, whatever state reported.
    liveness.mark_seen(CAM, now=0.0)
    cam = _status(client, auth_headers)
    assert cam["state"] == "UNAVAILABLE", "a heartbeat gap must override reported ARMED"


def test_tc_gapi_07_retained_state_is_not_liveness(client, auth_headers, published):
    """v3.40 applied to guard: a retained replay updates last-known, never liveness."""
    client.post(f"/api/guard/{CAM}/enable", headers=auth_headers)
    _feed_sync("state", {"state": "ARMED", "flags": []}, retained=True)
    cam = _status(client, auth_headers)
    assert cam["worker_alive"] is False, "retained must not prove the worker is alive"
    assert cam["state"] == "UNAVAILABLE", "and must never be rendered as ARMED"


def test_tc_gapi_08_off_wins(client, auth_headers, published):
    client.post(f"/api/guard/{CAM}/enable", headers=auth_headers)
    _feed_sync("state", {"state": "ARMED", "flags": []})
    client.post(f"/api/guard/{CAM}/disable", headers=auth_headers)
    cam = _status(client, auth_headers)
    assert cam["state"] == "OFF" and cam["enabled"] is False
    assert json.loads(published[-1][1])["cmd"] == "disarm"


def test_tc_gapi_09_rearm_is_distinct_from_enable(client, auth_headers, published):
    """Separate endpoint on purpose: rearm means a human looked, and resets the auto-resume
    budget. Folding it into enable would let a script clear that budget repeatedly."""
    client.post(f"/api/guard/{CAM}/enable", headers=auth_headers)
    _feed_sync("state", {"state": "SUSPENDED_CPU", "reason": "60s avg 71%"})
    cam = _status(client, auth_headers)
    assert cam["state"] == "SUSPENDED_CPU"
    assert "71%" in (cam["reason"] or "")

    r = client.post(f"/api/guard/{CAM}/rearm", headers=auth_headers)
    assert r.status_code == 202
    assert r.json()["previous_state"] == "SUSPENDED_CPU"
    assert json.loads(published[-1][1])["cmd"] == "rearm"


# ═══════════════════════════════════════════════════════════════════════════
# Runtime config
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gapi_10_config_patch_bumps_version_and_pushes(client, auth_headers, published):
    client.post(f"/api/guard/{CAM}/enable", headers=auth_headers)
    before = len(published)

    r = client.patch(f"/api/guard/{CAM}/config", headers=auth_headers,
                     json={"conf_threshold": 0.65, "fps": 2, "window_seconds": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["config_version"] == 2
    assert body["changed"] == {"conf_threshold": 0.65, "fps": 2.0, "window_seconds": 3.0}
    assert body["pushed_to_worker"] is True
    pushed = json.loads(published[-1][1])
    assert pushed["config"]["conf_threshold"] == 0.65
    assert pushed["config"]["config_version"] == 2
    assert len(published) == before + 1

    # PATCH semantics: untouched fields keep their values.
    assert body["config"]["frames_required"] == 2
    assert client.patch(f"/api/guard/{CAM}/config", headers=auth_headers,
                        json={}).status_code == 400


def test_tc_gapi_11_config_rejects_empty_uncertain_band(client, auth_headers, published):
    """An empty band would silently stop below-threshold logging — the accuracy evidence
    that cannot be reconstructed later."""
    _cam(client, auth_headers)
    r = client.patch(f"/api/guard/{CAM}/config", headers=auth_headers,
                     json={"conf_threshold": 0.3, "uncertain_min": 0.5})
    assert r.status_code == 400
    assert "uncertain band is empty" in r.json()["detail"]


def test_tc_gapi_12_config_validates_zone(client, auth_headers, published):
    _cam(client, auth_headers)
    for bad in ([0.8, 0.2, 0.2, 0.8], [0.0, 0.0, 1.5, 1.0], [0.1, 0.9, 0.9, 0.1]):
        r = client.patch(f"/api/guard/{CAM}/config", headers=auth_headers, json={"zone": bad})
        assert r.status_code == 400, bad
    ok = client.patch(f"/api/guard/{CAM}/config", headers=auth_headers,
                      json={"zone": [0.1, 0.1, 0.9, 0.9]})
    assert ok.status_code == 200
    assert ok.json()["config"]["zone"] == [0.1, 0.1, 0.9, 0.9]


# ═══════════════════════════════════════════════════════════════════════════
# Persistence from MQTT — the backend is the only writer
# ═══════════════════════════════════════════════════════════════════════════

def _alarm(uuid_: str = "uuid-a", **over) -> dict:
    data = {
        "event_uuid": uuid_, "camera_id": CAM, "pedestal_id": PED, "berth_id": 3,
        "detected_at_utc": "2026-09-27T14:32:07Z",
        "detected_at_local": "2026-09-27 16:32:07 CEST",
        "confidence": 0.81, "px_height": 152.0, "bbox": [0.4, 0.3, 0.5, 0.7],
        "trigger": "2_in_4s", "limited_visibility": False,
        "frame_path": "/var/lib/marina-guard/recordings/7/frames/x_alarm.jpg",
        "video_path": None, "video_skipped": False,
    }
    data.update(over)
    return data


def test_tc_gapi_13_alarm_persists_and_is_idempotent(client, auth_headers, published):
    _cam(client, auth_headers)
    _feed_sync("alarm", _alarm())
    _feed_sync("alarm", _alarm())      # at-least-once delivery must not double-count

    r = client.get("/api/guard/events", headers=auth_headers, params={"camera_id": CAM})
    body = r.json()
    assert body["total"] == 1, "QoS 1 redelivery must not create two events"
    ev = body["events"][0]
    assert ev["confidence"] == 0.81
    assert ev["px_height"] == 152.0
    assert ev["bbox"] == [0.4, 0.3, 0.5, 0.7]
    assert ev["detected_at_local"] == "2026-09-27 16:32:07 CEST"
    assert ev["has_frame"] is True and ev["has_video"] is False
    assert ev["label"] is None


def test_tc_gapi_14_detections_batch_and_absence_writes_nothing(client, auth_headers):
    _cam(client, auth_headers)
    _feed_sync("detection", {"detections": [
        {"ts": "2026-09-27T14:30:00Z", "confidence": 0.31, "px_height": 88, "band": "uncertain"},
        {"ts": "2026-09-27T14:30:01Z", "confidence": 0.77, "px_height": 150, "band": "alarm"},
    ]})
    _feed_sync("detection", {"detections": []})     # a quiet period writes nothing

    r = client.get("/api/guard/detections", headers=auth_headers,
                   params={"camera_id": CAM, "since": "2026-09-01T00:00:00Z"})
    body = r.json()
    assert body["total"] == 2, "an empty batch must add no rows — absence stays absence"
    bands = {d["band"] for d in body["detections"]}
    assert bands == {"uncertain", "alarm"}


def test_tc_gapi_22_recording_links_onto_its_event(client, auth_headers):
    _cam(client, auth_headers)
    _feed_sync("alarm", _alarm("uuid-rec", video_skipped=True))
    _feed_sync("recording", {
        "event_uuid": "uuid-rec", "file_path": "/tmp/2026-09-27T14-32-07Z.mp4",
        "started_at": "2026-09-27T14:32:07Z", "duration_s": 42.0, "file_size": 31457280,
    })
    ev = client.get("/api/guard/events", headers=auth_headers,
                    params={"camera_id": CAM}).json()["events"][0]
    assert ev["has_video"] is True, "the clip must attach to its event"
    assert ev["video_skipped"] is False, "and clear the skipped flag"


# ═══════════════════════════════════════════════════════════════════════════
# Events, labelling, roles
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gapi_15_events_paginate_and_filter(client, auth_headers):
    _cam(client, auth_headers)
    for i in range(5):
        _feed_sync("alarm", _alarm(f"uuid-{i}",
                                   detected_at_utc=f"2026-09-27T14:3{i}:00Z"))
    r = client.get("/api/guard/events", headers=auth_headers,
                   params={"camera_id": CAM, "limit": 2})
    body = r.json()
    assert body["total"] == 5 and len(body["events"]) == 2
    assert body["unlabelled"] >= 5
    # Newest first.
    assert body["events"][0]["detected_at_utc"] > body["events"][1]["detected_at_utc"]

    page2 = client.get("/api/guard/events", headers=auth_headers,
                       params={"camera_id": CAM, "limit": 2, "offset": 2}).json()
    assert {e["event_uuid"] for e in body["events"]} & {
        e["event_uuid"] for e in page2["events"]} == set()


def test_tc_gapi_16_labelling_records_actor_and_is_repeatable(client, auth_headers):
    _cam(client, auth_headers)
    _feed_sync("alarm", _alarm("uuid-label"))
    eid = client.get("/api/guard/events", headers=auth_headers,
                     params={"camera_id": CAM}).json()["events"][0]["id"]

    r = client.post(f"/api/guard/events/{eid}/label", headers=auth_headers,
                    json={"label": "false_alarm", "note": "a gull on the rail"})
    assert r.status_code == 200
    ev = r.json()["event"]
    assert ev["label"] == "false_alarm"
    assert ev["label_note"] == "a gull on the rail"
    assert ev["labelled_by"] == "admin@test.local"
    assert ev["labelled_at"] is not None

    # A second look is legitimate and overwrites.
    r2 = client.post(f"/api/guard/events/{eid}/label", headers=auth_headers,
                     json={"label": "correct"})
    assert r2.json()["event"]["label"] == "correct"

    # Filters work off the label.
    assert client.get("/api/guard/events", headers=auth_headers,
                      params={"camera_id": CAM, "label": "correct"}).json()["total"] == 1
    assert client.get("/api/guard/events", headers=auth_headers,
                      params={"camera_id": CAM, "label": "unlabelled"}).json()["total"] == 0

    # Bad label rejected by the schema.
    assert client.post(f"/api/guard/events/{eid}/label", headers=auth_headers,
                       json={"label": "maybe"}).status_code == 422


def test_tc_gapi_17_monitor_may_label_but_not_arm(client):
    """Deliberate split: the person who spots a gull is often the monitor, and making them
    fetch an admin would cost the labels. Arming is a control action."""
    from app.auth.models import User
    from app.auth.password import hash_password
    from app.auth.tokens import create_access_token
    from conftest import TestUserSession

    udb = TestUserSession()
    try:
        mon = udb.query(User).filter(User.email == "guardmon@test.local").first()
        if mon is None:
            mon = User(email="guardmon@test.local",
                       password_hash=hash_password("x12345678"), role="monitor")
            udb.add(mon)
            udb.commit()
            udb.refresh(mon)
        token = create_access_token(mon.id, mon.email, mon.role)
    finally:
        udb.close()
    mon_headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/guard/status", headers=mon_headers).status_code == 200
    assert client.post(f"/api/guard/{CAM}/enable", headers=mon_headers).status_code == 403
    assert client.post(f"/api/guard/{CAM}/rearm", headers=mon_headers).status_code == 403
    assert client.patch(f"/api/guard/{CAM}/config", headers=mon_headers,
                        json={"fps": 2}).status_code == 403

    _feed_sync("alarm", _alarm("uuid-mon"))
    eid = client.get("/api/guard/events", headers=mon_headers,
                     params={"camera_id": CAM}).json()["events"][0]["id"]
    r = client.post(f"/api/guard/events/{eid}/label", headers=mon_headers,
                    json={"label": "false_alarm"})
    assert r.status_code == 200, "a monitor MUST be able to label"
    assert r.json()["event"]["labelled_by"] == "guardmon@test.local"


# ═══════════════════════════════════════════════════════════════════════════
# Files: gone vs never-existed
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gapi_18_19_20_file_serving_distinguishes_gone_from_missing(
        client, auth_headers, tmp_path):
    _cam(client, auth_headers)

    # 404 for an event that never existed.
    assert client.get("/api/guard/events/999999/video", headers=auth_headers).status_code == 404

    # An alarm whose recording was skipped: 404 WITH a reason, not a bare not-found.
    _feed_sync("alarm", _alarm("uuid-skip", video_skipped=True,
                               video_skip_reason="no_disk", frame_path=None))
    eid = client.get("/api/guard/events", headers=auth_headers,
                     params={"camera_id": CAM}).json()["events"][0]["id"]
    r = client.get(f"/api/guard/events/{eid}/video", headers=auth_headers)
    assert r.status_code == 404
    assert r.json()["detail"]["reason"] == "no_disk"

    # A recording whose file is gone from disk: 410 Gone, and the row self-corrects.
    video = tmp_path / "2026-09-27T14-32-07Z.mp4"
    video.write_bytes(b"data")
    _feed_sync("alarm", _alarm("uuid-gone", video_path=str(video)))
    eid2 = [e for e in client.get("/api/guard/events", headers=auth_headers,
                                  params={"camera_id": CAM}).json()["events"]
            if e["event_uuid"] == "uuid-gone"][0]["id"]
    assert client.get(f"/api/guard/events/{eid2}/video",
                      headers=auth_headers).status_code == 200
    video.unlink()
    r = client.get(f"/api/guard/events/{eid2}/video", headers=auth_headers)
    assert r.status_code == 410, "gone is a different fact from never-existed"
    assert r.json()["detail"]["reason"] == "missing_on_disk"

    # The annotated frame: the dashboard needs it to see boxes on gulls immediately.
    frame = tmp_path / "shot_alarm.jpg"
    frame.write_bytes(b"\xff\xd8jpeg\xff\xd9")
    _feed_sync("alarm", _alarm("uuid-frame", frame_path=str(frame)))
    eid3 = [e for e in client.get("/api/guard/events", headers=auth_headers,
                                  params={"camera_id": CAM}).json()["events"]
            if e["event_uuid"] == "uuid-frame"][0]["id"]
    rf = client.get(f"/api/guard/events/{eid3}/frame", headers=auth_headers)
    assert rf.status_code == 200
    assert rf.headers["content-type"] == "image/jpeg"


def test_tc_gapi_21_detections_filter_by_band_and_confidence(client, auth_headers):
    _cam(client, auth_headers)
    _feed_sync("detection", {"detections": [
        {"ts": "2026-09-27T12:00:00Z", "confidence": 0.22, "band": "uncertain"},
        {"ts": "2026-09-27T12:00:05Z", "confidence": 0.45, "band": "uncertain"},
        {"ts": "2026-09-27T12:00:10Z", "confidence": 0.88, "band": "alarm"},
    ]})
    base = {"camera_id": CAM, "since": "2026-09-01T00:00:00Z"}
    assert client.get("/api/guard/detections", headers=auth_headers,
                      params={**base, "band": "alarm"}).json()["total"] == 1
    assert client.get("/api/guard/detections", headers=auth_headers,
                      params={**base, "min_confidence": 0.4}).json()["total"] == 2


# ─── helper ──────────────────────────────────────────────────────────────────

def _status(client, headers) -> dict:
    body = client.get("/api/guard/status", headers=headers).json()
    for cam in body["cameras"]:
        if cam["camera_id"] == CAM:
            return cam
    raise AssertionError(f"camera {CAM} not in status: {body}")
