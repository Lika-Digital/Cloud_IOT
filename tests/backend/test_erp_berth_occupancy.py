"""Tests for v3.16 ERP berth-occupancy exchange.

- Outbound webhook is trimmed to {pedestal_id, berths:[{berth_id, occupied}]}
  and never leaks zones/camera URL/scores/embedding paths.
- ERP image-push endpoint stores an image against an EXISTING berth.
- Sector creation is NOT reachable by ERP (not in the catalog).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt as pyjwt

from app.services.webhook_service import _project_berth_occupancy
from app.services.api_catalog import ENDPOINT_CATALOG
from app.routers import ext_pedestal_endpoints as ext
from app.models.external_api import ExternalApiConfig
from app.models.pedestal import Pedestal
from app.auth.berth_models import Berth
from tests.backend.conftest import TestSession, TestUserSession

JWT_SECRET = "test-secret-key-for-ci"  # set by conftest before app import


# ── outbound projection ───────────────────────────────────────────────────────

def test_project_trims_and_does_not_leak():
    rich = {"berths": [{
        "id": 7, "pedestal_id": 1, "occupied_bit": 1, "name": "Sector A",
        "zone_x1": 0.2, "camera_stream_url": "rtsp://admin:secret@host/profile1",
        "match_score": 0.91, "sample_embedding_path": "/x/emb.npy", "alarm": 1,
        "state_code": 2,
    }]}
    out = _project_berth_occupancy(rich)
    assert out["pedestal_id"] == 1
    assert out["berths"] == [{"berth_id": 7, "occupied": True}]
    flat = json.dumps(out)
    for leak in ("zone_x1", "camera_stream_url", "match_score",
                 "sample_embedding_path", "alarm", "state_code"):
        assert leak not in flat


def test_project_marks_unoccupied():
    out = _project_berth_occupancy({"berths": [{"id": 3, "pedestal_id": 2, "occupied_bit": 0}]})
    assert out["berths"] == [{"berth_id": 3, "occupied": False}]


# ── catalog / sector-creation guard ──────────────────────────────────────────

def test_push_image_endpoint_in_catalog():
    ep = {e["id"]: e for e in ENDPOINT_CATALOG}
    assert "berths.push_image_ext" in ep
    assert ep["berths.push_image_ext"]["method"] == "POST"
    assert ep["berths.push_image_ext"]["allow_bidirectional"] is True


def test_sector_creation_not_erp_reachable():
    # POST /api/admin/berths (sector creation) must never be in the ERP catalog.
    assert not any("admin/berths" in e["path"] for e in ENDPOINT_CATALOG)


# ── inbound image push ────────────────────────────────────────────────────────

def _ext_token():
    return pyjwt.encode(
        {"sub": "erp", "role": "api_client",
         "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        JWT_SECRET, algorithm="HS256")


def _enable_push_endpoint():
    db = TestSession()
    db.query(ExternalApiConfig).delete()
    db.add(ExternalApiConfig(
        id=1, active=1, verified=1, api_key="unused-for-api_client",
        allowed_endpoints=json.dumps([{"id": "berths.push_image_ext", "mode": "bidirectional"}]),
        allowed_events="[]"))
    db.commit(); db.close()


def test_ext_push_image_stores_to_existing_berth(client):
    _enable_push_endpoint()
    udb = TestUserSession()
    b = Berth(name="ERP Sector", pedestal_id=1, berth_type="transit",
              status="free", detected_status="free")
    udb.add(b); udb.commit(); udb.refresh(b); bid = b.id; udb.close()

    captured = {}

    def fake_save(berth_id, filename, data):
        captured.update(berth_id=berth_id, length=len(data))
        return f"/refs/{filename}"

    try:
        with patch.object(ext, "SessionLocal", TestSession), \
             patch.object(ext, "UserSessionLocal", TestUserSession), \
             patch("app.services.berth_analyzer.save_reference_image", side_effect=fake_save):
            r = client.post(
                f"/api/ext/pedestals/1/berths/{bid}/reference-image",
                content=b"JPEGBYTES",
                headers={"Authorization": f"Bearer {_ext_token()}"},
            )
    finally:
        udb = TestUserSession(); udb.query(Berth).filter(Berth.id == bid).delete(); udb.commit(); udb.close()
        db = TestSession(); db.query(ExternalApiConfig).delete(); db.commit(); db.close()

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["berth_id"] == bid
    assert captured["berth_id"] == bid and captured["length"] == len(b"JPEGBYTES")
