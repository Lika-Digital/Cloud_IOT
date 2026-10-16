"""TC-SM — smart mode is consumption only; the camera is security (spec §4.11, owner 2026-10-16).

TC-SM-01  smart mode OFF: occupancy / match and guard answer exactly as with smart mode ON —
          locally and through the ERP's routes. Read from the code 2026-10-16: none of them is
          gated today, so this test passes on the code it was written against; what makes it a
          test is that it FAILS when someone adds a smart-mode check — shown with two mutants
          (a `_require_smart_mode` on the analyze route; `berths.push_image_ext` added to the
          gateway's control resolver).
TC-SM-02  smart mode OFF: socket and valve commands still answer 409 and send nothing — locally
          (kept in test_direct_controls.py) and, added here, through the gateway.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import jwt
import pytest

from conftest import TestSession as _S
from conftest import TestUserSession as _US

# The camera functions, by catalogue id. None may be behind the smart-mode gate (§4.11).
CAMERA_FUNCTION_IDS = {"berths.occupancy_ext", "berths.push_image_ext", "berths.list"}


def _ext_headers() -> dict:
    tok = jwt.encode({"sub": "sm-ext-client", "role": "api_client",
                      "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
                     "test-secret-key-for-ci", algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


def _store(entries: list[tuple[str, str]]) -> None:
    from app.models.external_api import ExternalApiConfig
    db = _S()
    try:
        cfg = db.get(ExternalApiConfig, 1)
        allowed = json.dumps([{"id": i, "mode": m} for i, m in entries])
        if cfg is None:
            db.add(ExternalApiConfig(id=1, allowed_endpoints=allowed, allowed_events="[]", active=1,
                                     verified=0, created_at=datetime.utcnow(),
                                     updated_at=datetime.utcnow()))
        else:
            cfg.allowed_endpoints, cfg.active = allowed, 1
        db.commit()
    finally:
        db.close()


def _smart(pid: int, on: bool) -> None:
    from app.models.pedestal_config import PedestalConfig
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        cfg.smart_mode = on
        db.commit()
    finally:
        db.close()


@pytest.fixture(scope="module")
def rig(client, auth_headers):
    from app.auth.berth_models import Berth
    from app.models.pedestal_config import PedestalConfig
    r = client.post("/api/pedestals/", json={"name": "SM Pedestal", "location": "Dock S",
                                              "data_mode": "real"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        # A camera that "is there", so the analyze route gets past its own checks and a
        # smart-mode check placed anywhere before the analysis would be reached.
        cfg.camera_stream_url = "rtsp://camera.invalid/profile1"
        cfg.camera_reachable = True
        db.commit()
    finally:
        db.close()
    udb = _US()
    try:
        b = Berth(name="SM 1", pedestal_id=pid, berth_number=1)
        udb.add(b)
        udb.commit()
        bid = b.id
    finally:
        udb.close()
    from app.guard.models import GuardConfig
    db = _S()
    try:
        if db.get(GuardConfig, 9711) is None:
            db.add(GuardConfig(camera_id=9711, pedestal_id=pid, desired_state="OFF"))
            db.commit()
    finally:
        db.close()
    return pid, bid


def _camera_calls(client, auth_headers, pid: int, bid: int) -> dict:
    """Every camera-function call, once. Returns {name: status code}."""
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (90, 120, 150)).save(buf, format="JPEG")
    frame = buf.getvalue()
    analysed = {"occupied_bit": 0, "match_ok_bit": 0, "state_code": 0, "alarm": 0,
                "match_score": None, "error": None}
    out = {}
    # The camera and the analysis are stubbed and nothing is written to disk (rule 16): the
    # test is about which routes answer in which mode, not about what the camera sees.
    with patch("app.services.frame_buffer.get_latest_frame", return_value=frame), \
         patch("app.services.berth_analyzer.analyze_berth_now",
               new=AsyncMock(return_value=analysed)), \
         patch("app.services.training_data.save_crop", return_value=(None, None)), \
         patch("app.services.berth_analyzer.save_reference_image", return_value=None), \
         patch("app.services.mqtt_client.mqtt_service.publish"):
        out["local analyze"] = client.post(f"/api/admin/berths/{bid}/analyze",
                                           headers=auth_headers).status_code
        out["ext occupancy"] = client.get(f"/api/ext/pedestals/{pid}/berths/occupancy",
                                          headers=_ext_headers()).status_code
        out["ext reference image"] = client.post(
            f"/api/ext/pedestals/{pid}/berths/{bid}/reference-image",
            headers={**_ext_headers(), "Content-Type": "image/jpeg"},
            content=b"\xff\xd8\xff\xe0not-really-a-jpeg").status_code
        out["gateway berths.list"] = client.get("/api/ext/berths",
                                                headers=_ext_headers()).status_code
        out["guard status"] = client.get("/api/guard/status", headers=auth_headers).status_code
        out["guard enable"] = client.post("/api/guard/9711/enable",
                                          headers=auth_headers).status_code
        out["guard disable"] = client.post("/api/guard/9711/disable",
                                           headers=auth_headers).status_code
    return out


def test_tc_sm_01_camera_functions_ignore_smart_mode(client, auth_headers, rig):
    pid, bid = rig
    _store([("berths.occupancy_ext", "monitor"), ("berths.push_image_ext", "bidirectional"),
            ("berths.list", "monitor")])
    try:
        _smart(pid, True)
        on = _camera_calls(client, auth_headers, pid, bid)
        _smart(pid, False)
        off = _camera_calls(client, auth_headers, pid, bid)
    finally:
        _smart(pid, True)
        _store([])
    assert 409 not in off.values(), off
    assert off == on, {"smart ON": on, "smart OFF": off}


def test_tc_sm_01_no_camera_function_is_behind_the_gateway_gate():
    from app.routers.external_api_gateway import _CONTROL_PEDESTAL_RESOLVER
    gated = CAMERA_FUNCTION_IDS & set(_CONTROL_PEDESTAL_RESOLVER)
    assert not gated, f"camera functions behind the smart-mode gate: {gated}"


@pytest.mark.parametrize("path", ["socket/Q1/cmd", "water/V1/cmd"])
def test_tc_sm_02_socket_and_valve_commands_still_409_through_the_gateway(client, rig, path):
    pid, _bid = rig
    _store([("controls.socket_cmd", "bidirectional"), ("controls.water_cmd", "bidirectional")])
    _smart(pid, False)
    try:
        with patch("app.services.mqtt_client.mqtt_service.publish") as pub:
            r = client.post(f"/api/ext/controls/pedestal/{pid}/{path}",
                            json={"action": "activate"}, headers=_ext_headers())
        assert r.status_code == 409, r.text
        assert "smart mode" in r.json()["detail"].lower()
        sent = [c.args[0] for c in pub.call_args_list if c.args and "opta/cmd" in c.args[0]]
        assert sent == [], sent
    finally:
        _smart(pid, True)
        _store([])
