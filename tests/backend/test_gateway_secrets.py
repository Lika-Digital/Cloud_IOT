"""TC-GS — the camera password and the customer's name never leave through the gateway or an
/api/ext route (spec §16.3d, owner 2026-10-16).

`GET /api/berths` returned `camera_stream_url`, and saving the camera settings writes the
username and password INTO that address — so `berths.list` through the gateway (which proxies
as admin, D3) handed the ERP the camera password. The owner: the field must not exist in
anything the gateway can return, or the first person who puts it back releases it again. And
`sessions.*` may carry `customer_id`, `nfc_user_id`, `erp_ref`, never `customer_name`.

The password is never printed: every assertion names the endpoint, never the value.

  TC-GS-01  berths.list through the gateway has no camera_stream_url; the admin's own
            GET /api/berths still has it (the filter is the gateway's, not a deleted field)
  TC-GS-02  no catalogue GET through the gateway, and no /api/ext route, contains the password
  TC-GS-03  sessions.active through the gateway: customer_id, nfc_user_id, erp_ref — no
            customer_name; the admin's own route still has the name

All three fail on the gateway before the filter.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest

from conftest import TestSession as _S
from conftest import TestUserSession as _US

SECRET = "pw" + secrets.token_hex(12)          # the camera password of this test, never printed
CAB = "MAR_GS_ORM_01"


def _ext_headers() -> dict:
    tok = jwt.encode({"sub": "gs-ext-client", "role": "api_client",
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


@pytest.fixture
def through_gateway(monkeypatch):
    """The gateway proxies to 127.0.0.1:<port>, which no test server listens on: route it into
    the same app in-process instead, so the gateway's own code runs end to end."""
    from app.main import app
    from app.routers import external_api_gateway as gw
    real = httpx.AsyncClient

    class InProcess(real):
        def __init__(self, *a, **k):
            k["transport"] = httpx.ASGITransport(app=app)
            super().__init__(*a, **k)

    monkeypatch.setattr(gw.httpx, "AsyncClient", InProcess)
    yield
    _store([])


@pytest.fixture(scope="module")
def rig(client, auth_headers):
    from app.auth.berth_models import Berth
    from app.models.pedestal_config import PedestalConfig
    r = client.post("/api/pedestals/", json={"name": "GS Pedestal", "location": "Dock G",
                                              "data_mode": "real"}, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        cfg.opta_client_id = CAB
        # As the camera settings save writes it: the credentials INSIDE the address.
        cfg.camera_stream_url = f"rtsp://cam:{SECRET}@10.0.0.5:554/profile1"
        cfg.camera_username = "cam"
        cfg.camera_password = SECRET
        db.commit()
    finally:
        db.close()
    udb = _US()
    try:
        b = Berth(name="GS 1", pedestal_id=pid, berth_number=1)
        udb.add(b)
        udb.commit()
        bid = b.id
    finally:
        udb.close()
    return pid, bid


def _ext_path(path: str, pid: int, bid: int) -> str:
    filled = (path.replace("{pedestal_id}", str(pid)).replace("{id}", str(pid))
              .replace("{cabinet_id}", CAB).replace("{socket_id}", "1")
              .replace("{valve_id}", "1").replace("{berth_id}", str(bid)))
    return filled if filled.startswith("/api/ext/") else "/api/ext" + filled[len("/api"):]


def test_tc_gs_01_berths_list_through_the_gateway_has_no_camera_address(
        client, auth_headers, rig, through_gateway):
    _store([("berths.list", "monitor")])
    r = client.get("/api/ext/berths", headers=_ext_headers())
    assert r.status_code == 200, f"berths.list through the gateway answered {r.status_code}"
    rows = r.json()
    assert rows, "the gateway returned no berths — the check saw nothing"
    assert all("camera_stream_url" not in b for b in rows), \
        "berths.list through the gateway carries camera_stream_url"
    # control: the admin's own route still has the field — the filter is the gateway's
    own = client.get("/api/berths", headers=auth_headers).json()
    assert any("camera_stream_url" in b for b in own)


def test_tc_gs_02_no_gateway_or_ext_answer_contains_the_camera_password(
        client, rig, through_gateway):
    from app.services.api_catalog import ENDPOINT_CATALOG
    pid, bid = rig
    gets = [e for e in ENDPOINT_CATALOG if e["method"] == "GET"]
    _store([(e["id"], "monitor") for e in gets])
    answered, leaked = 0, []
    for e in gets:
        path = _ext_path(e["path"], pid, bid)
        if re.search(r"\{[a-z_]+\}", path):
            continue
        r = client.get(path, headers=_ext_headers())
        answered += r.status_code == 200
        if SECRET in r.text:
            leaked.append(e["id"])               # the id, never the value
    assert not leaked, f"the camera password appears in: {leaked}"
    assert answered >= 10, f"only {answered} endpoints answered 200 — the check saw too little"


def test_tc_gs_03_sessions_through_the_gateway_carry_the_ids_not_the_name(
        client, auth_headers, rig, through_gateway):
    from app.auth.customer_models import Customer
    from app.models.session import Session
    pid, _bid = rig
    udb = _US()
    try:
        c = Customer(name="Ana Kovač", email=f"gs-{secrets.token_hex(4)}@test.local",
                     password_hash="x")
        udb.add(c)
        udb.commit()
        cid = c.id
    finally:
        udb.close()
    db = _S()
    try:
        s = Session(pedestal_id=pid, socket_id=1, type="electricity", status="active",
                    started_at=datetime.utcnow(), customer_id=cid, nfc_user_id="ERP-U-7",
                    erp_ref="ERP-R-7")
        db.add(s)
        db.commit()
        sid = s.id
    finally:
        db.close()
    try:
        _store([("sessions.active", "monitor")])
        r = client.get("/api/ext/sessions/active", headers=_ext_headers())
        assert r.status_code == 200, r.status_code
        row = next(x for x in r.json() if x["id"] == sid)
        assert (row["customer_id"], row["nfc_user_id"], row["erp_ref"]) == (cid, "ERP-U-7", "ERP-R-7")
        assert "customer_name" not in row, "sessions through the gateway carry the customer's name"
        own = next(x for x in client.get("/api/sessions/active", headers=auth_headers).json()
                   if x["id"] == sid)
        assert own["customer_name"] == "Ana Kovač", "control: the admin's own route has the name"
    finally:
        db = _S()
        try:
            db.query(Session).filter(Session.id == sid).delete()
            db.commit()
        finally:
            db.close()
