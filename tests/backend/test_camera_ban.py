"""TC-CB — Phase 1: no image and no video to the ERP, enforced by the code (spec §16.3, owner 2026-10-16).

Measured on cabinet 1 the same day: all four camera endpoints were in the ERP's list and 12 camera
calls had answered 200 in 14 days. "A configuration that can be set by hand is not a rule but a
memory" (owner). So `PHASE1_NO_IMAGES_TO_ERP` refuses them on SAVING the list (422) and AT REQUEST
TIME (403) — the second because a list stored before this rule, like cabinet 1's, must not keep
the path open.

TC-CB-02 and TC-CB-03 are the owner's negative controls: saving a list with camera.frame_ext is
refused; a request to that endpoint with such a list already stored is refused.
"""
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest

IMAGE_IDS = {"camera.snapshot", "camera.stream", "camera.frame_ext", "camera.stream_ext"}
SENTENCE = "Camera endpoints are not allowed to the ERP in Phase 1"


def _ext_headers() -> dict:
    tok = jwt.encode({"sub": "test-ext-client", "role": "api_client",
                      "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                     "test-secret-key-for-ci", algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


def _store_list(ids: list[str]) -> None:
    """Write the list straight into the row, as an older configuration on a cabinet would be —
    bypassing the save path on purpose."""
    from app.database import SessionLocal
    from app.models.external_api import ExternalApiConfig
    db = SessionLocal()
    try:
        cfg = db.get(ExternalApiConfig, 1)
        allowed = json.dumps([{"id": i, "mode": "monitor"} for i in ids])
        if cfg is None:
            db.add(ExternalApiConfig(id=1, allowed_endpoints=allowed, allowed_events="[]", active=1,
                                     verified=0, created_at=datetime.utcnow(),
                                     updated_at=datetime.utcnow()))
        else:
            cfg.allowed_endpoints, cfg.active = allowed, 1
        db.commit()
    finally:
        db.close()


def _stored_ids() -> list[str]:
    from app.database import SessionLocal
    from app.models.external_api import ExternalApiConfig
    db = SessionLocal()
    try:
        cfg = db.get(ExternalApiConfig, 1)
        return [e["id"] for e in json.loads(cfg.allowed_endpoints or "[]")] if cfg else []
    finally:
        db.close()


def test_tc_cb_01_every_camera_endpoint_is_marked_image():
    """A new endpoint that returns a frame or a stream must carry `image`, or the ban misses it."""
    from app.services.api_catalog import ENDPOINT_CATALOG
    marked = {e["id"] for e in ENDPOINT_CATALOG if e.get("image")}
    camera_paths = {e["id"] for e in ENDPOINT_CATALOG
                    if "/camera/" in e["path"] or e["category"] == "Camera"}
    assert camera_paths == IMAGE_IDS, camera_paths
    assert marked == IMAGE_IDS, marked


def test_tc_cb_02_saving_a_list_with_a_camera_endpoint_is_refused(client, auth_headers):
    _store_list(["pedestals.health"])
    body = {"allowed_endpoints": [{"id": "pedestals.health", "mode": "monitor"},
                                  {"id": "camera.frame_ext", "mode": "monitor"}],
            "webhook_url": None, "allowed_events": []}
    r = client.put("/api/admin/ext-api/config", json=body, headers=auth_headers)
    assert r.status_code == 422, r.text
    assert SENTENCE in r.json()["detail"] and "camera.frame_ext" in r.json()["detail"]
    assert _stored_ids() == ["pedestals.health"], "the refused save must not have written anything"
    # control: the same save without the camera endpoint is accepted
    body["allowed_endpoints"] = body["allowed_endpoints"][:1]
    r = client.put("/api/admin/ext-api/config", json=body, headers=auth_headers)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("path", ["camera/frame", "camera/stream"])
def test_tc_cb_03_a_stored_camera_entry_is_refused_at_request_time(client, path):
    _store_list(["camera.frame_ext", "camera.stream_ext", "berths.occupancy_ext"])
    r = client.get(f"/api/ext/pedestals/1/{path}", headers=_ext_headers())
    assert r.status_code == 403, r.text
    assert SENTENCE in r.json()["detail"]
    # control: a non-image endpoint in the same stored list is not refused by the ban
    r = client.get("/api/ext/pedestals/1/berths/occupancy", headers=_ext_headers())
    assert r.status_code != 403, r.text


def test_tc_cb_04_the_gateway_refuses_a_stored_camera_entry(client):
    _store_list(["camera.snapshot", "camera.stream"])
    for p in ("/api/ext/camera/1/snapshot", "/api/ext/camera/1/stream"):
        r = client.get(p, headers=_ext_headers())
        assert r.status_code == 403, (p, r.text)
        assert SENTENCE in r.json()["detail"], (p, r.text)


def test_tc_cb_05_the_screen_gets_the_sentence_not_a_tickbox(client, auth_headers):
    r = client.get("/api/admin/ext-api/catalog", headers=auth_headers)
    assert r.status_code == 200
    reasons = {e["id"]: e["refused_reason"] for e in r.json()["endpoints"]}
    assert {i for i, why in reasons.items() if why} == IMAGE_IDS
    assert all(SENTENCE in reasons[i] for i in IMAGE_IDS)


def test_tc_cb_06_health_does_not_call_a_refused_endpoint_enabled(client, auth_headers):
    from app.database import SessionLocal
    from app.models.pedestal_config import PedestalConfig
    db = SessionLocal()
    try:
        if not db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == 1).first():
            db.add(PedestalConfig(pedestal_id=1, updated_at=datetime.utcnow()))
            db.commit()
    finally:
        db.close()
    _store_list(["camera.frame_ext", "camera.stream_ext"])
    r = client.get("/api/pedestals/health", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    entries = [e for e in (body.values() if isinstance(body, dict) else body)
               if isinstance(e, dict) and "ext_camera_frame" in e]
    assert entries, f"no pedestal entry carried ext_camera_frame — the check saw nothing: {body}"
    for entry in entries:
        assert entry["ext_camera_frame"]["enabled"] is False
        assert entry["ext_camera_stream"]["enabled"] is False


def test_tc_cb_07_the_constant_is_the_one_switch(client, auth_headers, monkeypatch):
    """Lifting is ONE reviewed change (§16.3): with the constant False the same save is accepted."""
    monkeypatch.setattr("app.services.api_catalog.PHASE1_NO_IMAGES_TO_ERP", False)
    body = {"allowed_endpoints": [{"id": "camera.frame_ext", "mode": "monitor"}],
            "webhook_url": None, "allowed_events": []}
    r = client.put("/api/admin/ext-api/config", json=body, headers=auth_headers)
    assert r.status_code == 200, r.text
    _store_list([])
