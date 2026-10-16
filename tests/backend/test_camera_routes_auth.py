"""TC-CAM — no camera route answers without a login (spec §16.3c, owner 2026-10-16).

`GET /api/camera/{id}/stream` had no identity dependency — the snapshot route beside it had one.
It proxies the camera's MJPEG with the stored credentials, and nginx passes /api/ on :80 to the
tailnet and, through the Cloudflare tunnel, to the internet. Recorded in the audit of 2026-06-10
and never fixed. The owner: fixed before the upgrade, whether or not a picture leaks this second.

  TC-CAM-01  the live stream without a login → 401/403 (200 on the code before)
  TC-CAM-02  EVERY route of the app whose path names a camera, a frame, a stream, an image, a
             video, a photo or a crop → 401/403 without a login. Enumerated from the app, so a
             route added later is covered the day it lands.
"""
from __future__ import annotations

import re
from unittest.mock import patch

import pytest

from conftest import TestSession as _S

CAMERA_WORDS = re.compile(r"camera|snapshot|frame|stream|image|video|photo|crop", re.I)


@pytest.fixture(scope="module")
def pid(client, auth_headers):
    from app.models.pedestal_config import PedestalConfig
    r = client.post("/api/pedestals/", json={"name": "CAM Pedestal", "location": "Dock C",
                                              "data_mode": "real"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    p = r.json()["id"]
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == p).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=p)
            db.add(cfg)
        cfg.camera_stream_url = "rtsp://camera.invalid/profile1"
        db.commit()
    finally:
        db.close()
    return p


def test_tc_cam_01_the_live_stream_needs_a_login(client, auth_headers, pid):
    with patch("app.services.camera_service.stream_ip_camera", return_value=iter([b"FRAME"])):
        anon = client.get(f"/api/camera/{pid}/stream")
        assert anon.status_code in (401, 403), \
            f"the live camera stream answered {anon.status_code} without a login"
        assert b"FRAME" not in anon.content
        # control: with a login the stream answers
        ok = client.get(f"/api/camera/{pid}/stream", headers=auth_headers)
        assert ok.status_code == 200 and ok.content == b"FRAME"


def _camera_routes():
    from app.main import app
    for r in app.routes:
        path = getattr(r, "path", "")
        methods = sorted(m for m in (getattr(r, "methods", None) or []) if m != "HEAD")
        if CAMERA_WORDS.search(path) and methods:
            for m in methods:
                yield m, path


def test_tc_cam_02_no_camera_route_answers_without_a_login(client, pid):
    routes = list(_camera_routes())
    assert len(routes) >= 15, f"the scan saw only {len(routes)} routes — it is not looking"
    open_ = []
    with patch("app.services.camera_service.stream_ip_camera", return_value=iter([b"FRAME"])), \
         patch("app.services.mqtt_client.mqtt_service.publish"):
        for method, path in routes:
            url = re.sub(r"\{[a-z_]+\}", str(pid), path)
            r = client.request(method, url)
            if r.status_code not in (401, 403):
                open_.append(f"{method} {path} → {r.status_code}")
    assert not open_, "camera routes answering without a login: " + "; ".join(open_)
