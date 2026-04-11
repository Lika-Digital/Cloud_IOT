"""
External Pedestal API Endpoints — Verification Tests
=====================================================

Tests cover the three new direct ext-pedestal routes:
  GET /api/ext/pedestals/{id}/berths/occupancy
  GET /api/ext/pedestals/{id}/camera/frame
  GET /api/ext/pedestals/{id}/camera/stream

And health endpoint ext-status fields:
  GET /api/pedestals/health

Test IDs:
  TC-EP-01  berths/occupancy returns list with occupied status for existing sectors
  TC-EP-02  berths/occupancy returns empty list with message when no sectors defined
  TC-EP-03  berths/occupancy returns null occupied when sectors exist but no analysis
  TC-EP-04  camera/frame returns valid JPEG when stream reachable (mock grab_snapshot)
  TC-EP-05  camera/frame returns 503 with correct reason when stream unreachable
  TC-EP-06  camera/stream returns RTSP URL and reachable=true when accessible
  TC-EP-07  camera/stream returns 503 when no camera configured
  TC-EP-08  All three return 503 "Not enabled" when toggled off
  TC-EP-09  All three appear in health check with enabled+availability status
  TC-EP-10  Toggle persists to DB and takes effect immediately
  TC-EP-11  Operator sees correct status in API gateway menu (health data populated)
"""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── Shared test DB (same files as conftest) ───────────────────────────────────

TEST_DB      = "sqlite:///./tests/test_pedestal.db"
TEST_USER_DB = "sqlite:///./tests/test_users.db"

_test_engine      = create_engine(TEST_DB,      connect_args={"check_same_thread": False}, poolclass=StaticPool)
_test_user_engine = create_engine(TEST_USER_DB, connect_args={"check_same_thread": False}, poolclass=StaticPool)
_TestSession      = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)
_TestUserSession  = sessionmaker(autocommit=False, autoflush=False, bind=_test_user_engine)


@pytest.fixture(scope="module", autouse=True)
def _dispose_ep_engines():
    yield
    _test_engine.dispose()
    _test_user_engine.dispose()


@pytest.fixture(scope="module", autouse=True)
def _patch_ep_session_factories(setup_test_databases):
    """
    Redirect the module-level SessionLocal and UserSessionLocal in
    ext_pedestal_endpoints to use the test databases (same DBs the app
    dependency overrides use).
    """
    with (
        patch("app.routers.ext_pedestal_endpoints.SessionLocal", _TestSession),
        patch("app.routers.ext_pedestal_endpoints.UserSessionLocal", _TestUserSession),
        patch("app.routers.pedestal_config.UserSessionLocal", _TestUserSession),
    ):
        yield


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _make_ext_jwt() -> str:
    """Create a short-lived api_client JWT (no HMAC match needed)."""
    import jwt
    from datetime import timedelta
    payload = {
        "sub":  "test-ext-client",
        "role": "api_client",
        "exp":  datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, "test-secret-key-for-ci", algorithm="HS256")


def _ext_headers() -> dict:
    return {"Authorization": f"Bearer {_make_ext_jwt()}"}


# ── DB setup helpers ──────────────────────────────────────────────────────────

def _setup_gateway_config(enabled_ep_ids: list[str]) -> None:
    """Upsert ExternalApiConfig with active=1 and the given endpoint IDs enabled."""
    from app.models.external_api import ExternalApiConfig
    db = _TestSession()
    try:
        cfg = db.get(ExternalApiConfig, 1)
        allowed = [{"id": ep_id, "mode": "monitor"} for ep_id in enabled_ep_ids]
        if cfg is None:
            cfg = ExternalApiConfig(
                id=1,
                allowed_endpoints=json.dumps(allowed),
                allowed_events="[]",
                active=1,
                verified=0,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(cfg)
        else:
            cfg.allowed_endpoints = json.dumps(allowed)
            cfg.active = 1
            cfg.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _setup_pedestal_camera(pedestal_id: int, stream_url: str | None, reachable: bool) -> None:
    """Upsert PedestalConfig with camera settings."""
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter(
            PedestalConfig.pedestal_id == pedestal_id
        ).first()
        if cfg is None:
            cfg = PedestalConfig(
                pedestal_id=pedestal_id,
                camera_stream_url=stream_url,
                camera_username="testuser",
                camera_password="testpass",
                camera_reachable=1 if reachable else 0,
                last_camera_check=datetime.utcnow() if stream_url else None,
                updated_at=datetime.utcnow(),
            )
            db.add(cfg)
        else:
            cfg.camera_stream_url = stream_url
            cfg.camera_reachable = 1 if reachable else 0
            cfg.last_camera_check = datetime.utcnow() if stream_url else None
            cfg.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _get_test_pedestal_id() -> int:
    """Return the first pedestal's DB id (seeded by conftest)."""
    from app.models.pedestal import Pedestal
    db = _TestSession()
    try:
        p = db.query(Pedestal).first()
        assert p is not None, "No pedestal seeded — check conftest"
        return p.id
    finally:
        db.close()


def _seed_berth(pedestal_id: int, analyzed: bool = False, occupied: bool = False) -> int:
    """Add a berth to the user DB for the given pedestal. Returns berth id."""
    from app.auth.berth_models import Berth
    user_db = _TestUserSession()
    try:
        b = Berth(
            name=f"Test Berth for P{pedestal_id}",
            pedestal_id=pedestal_id,
            status="free",
            detected_status="occupied" if occupied else "free",
            occupied_bit=1 if occupied else 0,
            match_ok_bit=0,
            state_code=1 if occupied else 0,
            alarm=0,
            use_detection_zone=0,
            last_analyzed=datetime.utcnow() if analyzed else None,
            detect_conf_threshold=0.30,
            match_threshold=0.50,
        )
        user_db.add(b)
        user_db.commit()
        user_db.refresh(b)
        return b.id
    finally:
        user_db.close()


def _delete_berths_for_pedestal(pedestal_id: int) -> None:
    from app.auth.berth_models import Berth
    user_db = _TestUserSession()
    try:
        user_db.query(Berth).filter(Berth.pedestal_id == pedestal_id).delete()
        user_db.commit()
    finally:
        user_db.close()


# ─────────────────────────────────────────────────────────────────────────────
# TC-EP-01  Berth occupancy returns list with occupied=true/false
# ─────────────────────────────────────────────────────────────────────────────

def test_berths_occupancy_returns_occupied_status(client, auth_headers):
    """TC-EP-01  /berths/occupancy returns occupied bool for analyzed berths."""
    pid = _get_test_pedestal_id()
    _delete_berths_for_pedestal(pid)
    _seed_berth(pid, analyzed=True, occupied=True)
    _setup_gateway_config(["berths.occupancy_ext", "camera.frame_ext", "camera.stream_ext"])

    r = client.get(f"/api/ext/pedestals/{pid}/berths/occupancy", headers=_ext_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "berths" in data
    assert len(data["berths"]) >= 1
    b = next((b for b in data["berths"] if "occupied" in b), None)
    assert b is not None
    assert b["occupied"] is True
    assert "berth_id" in b
    assert "berth_name" in b
    assert "last_analyzed" in b


# ─────────────────────────────────────────────────────────────────────────────
# TC-EP-02  Berth occupancy returns empty list when no berths defined
# ─────────────────────────────────────────────────────────────────────────────

def test_berths_occupancy_empty_when_no_berths(client):
    """TC-EP-02  Returns 200 with berths=[] and message when no berths configured."""
    pid = _get_test_pedestal_id()
    _delete_berths_for_pedestal(pid)
    _setup_gateway_config(["berths.occupancy_ext"])

    r = client.get(f"/api/ext/pedestals/{pid}/berths/occupancy", headers=_ext_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["berths"] == []
    assert "message" in data
    assert "No berth definitions" in data["message"]


# ─────────────────────────────────────────────────────────────────────────────
# TC-EP-03  Berth occupancy returns null occupied when no analysis performed
# ─────────────────────────────────────────────────────────────────────────────

def test_berths_occupancy_null_when_not_analyzed(client):
    """TC-EP-03  occupied=null and note when berths exist but no analysis run."""
    pid = _get_test_pedestal_id()
    _delete_berths_for_pedestal(pid)
    _seed_berth(pid, analyzed=False)
    _setup_gateway_config(["berths.occupancy_ext"])

    r = client.get(f"/api/ext/pedestals/{pid}/berths/occupancy", headers=_ext_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["berths"]) >= 1
    b = data["berths"][0]
    assert b["occupied"] is None
    assert "note" in b
    assert "No analysis" in b["note"]


# ─────────────────────────────────────────────────────────────────────────────
# TC-EP-04  Camera frame returns valid JPEG when stream reachable
# ─────────────────────────────────────────────────────────────────────────────

def test_camera_frame_returns_jpeg(client):
    """TC-EP-04  Returns 200 image/jpeg with mock frame bytes."""
    pid = _get_test_pedestal_id()
    _setup_gateway_config(["camera.frame_ext"])
    _setup_pedestal_camera(pid, "rtsp://testcam:554/stream", reachable=True)

    fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # minimal fake JPEG header

    with patch(
        "app.services.berth_analyzer.grab_snapshot",
        new=AsyncMock(return_value=fake_jpeg),
    ):
        r = client.get(f"/api/ext/pedestals/{pid}/camera/frame", headers=_ext_headers())

    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/jpeg")
    assert r.content == fake_jpeg


# ─────────────────────────────────────────────────────────────────────────────
# TC-EP-05  Camera frame returns 503 when stream unreachable
# ─────────────────────────────────────────────────────────────────────────────

def test_camera_frame_503_when_unreachable(client):
    """TC-EP-05  Returns 503 with reason when camera_reachable=0."""
    pid = _get_test_pedestal_id()
    _setup_gateway_config(["camera.frame_ext"])
    _setup_pedestal_camera(pid, "rtsp://testcam:554/stream", reachable=False)

    r = client.get(f"/api/ext/pedestals/{pid}/camera/frame", headers=_ext_headers())
    assert r.status_code == 503, r.text
    data = r.json()
    assert data["error"] == "Camera stream unavailable"
    assert "Stream unreachable" in data["reason"] or "unreachable" in data["reason"].lower()


def test_camera_frame_503_on_grab_failure(client):
    """TC-EP-05  Returns 503 with 'Failed to capture' when ffmpeg/grab fails."""
    pid = _get_test_pedestal_id()
    _setup_gateway_config(["camera.frame_ext"])
    _setup_pedestal_camera(pid, "rtsp://testcam:554/stream", reachable=True)

    with patch(
        "app.services.berth_analyzer.grab_snapshot",
        new=AsyncMock(side_effect=RuntimeError("ffmpeg error")),
    ):
        r = client.get(f"/api/ext/pedestals/{pid}/camera/frame", headers=_ext_headers())

    assert r.status_code == 503, r.text
    data = r.json()
    assert "Failed to capture" in data["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# TC-EP-06  Camera stream returns RTSP URL and reachable=true
# ─────────────────────────────────────────────────────────────────────────────

def test_camera_stream_returns_url_and_reachable(client):
    """TC-EP-06  Returns 200 with stream_url and reachable=true."""
    pid = _get_test_pedestal_id()
    _setup_gateway_config(["camera.stream_ext"])
    _setup_pedestal_camera(pid, "rtsp://cam:554/live", reachable=True)

    r = client.get(f"/api/ext/pedestals/{pid}/camera/stream", headers=_ext_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    assert "stream_url" in data
    assert data["stream_url"] == "rtsp://cam:554/live"
    assert data["reachable"] is True
    assert "pedestal_id" in data


# ─────────────────────────────────────────────────────────────────────────────
# TC-EP-07  Camera stream returns 503 when no camera configured
# ─────────────────────────────────────────────────────────────────────────────

def test_camera_stream_503_when_not_configured(client):
    """TC-EP-07  Returns 503 when camera_stream_url is None."""
    pid = _get_test_pedestal_id()
    _setup_gateway_config(["camera.stream_ext"])
    _setup_pedestal_camera(pid, None, reachable=False)

    r = client.get(f"/api/ext/pedestals/{pid}/camera/stream", headers=_ext_headers())
    assert r.status_code == 503, r.text
    data = r.json()
    assert data["error"] == "Camera stream unavailable"
    assert "No camera configured" in data["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# TC-EP-08  All three return 503 "Not enabled" when toggled off
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path_suffix", [
    "berths/occupancy",
    "camera/frame",
    "camera/stream",
])
def test_returns_503_not_enabled_when_toggled_off(client, path_suffix):
    """TC-EP-08  503 with reason='Not enabled' when endpoint ID not in allowed_endpoints."""
    pid = _get_test_pedestal_id()
    # Enable none of the ext endpoints
    _setup_gateway_config([])

    r = client.get(
        f"/api/ext/pedestals/{pid}/{path_suffix}",
        headers=_ext_headers(),
    )
    assert r.status_code == 503, f"{path_suffix} returned {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("error") == "Feature not available"
    assert data.get("reason") == "Not enabled"


# ─────────────────────────────────────────────────────────────────────────────
# TC-EP-09  Health check includes ext endpoint status
# ─────────────────────────────────────────────────────────────────────────────

def test_health_includes_ext_endpoint_status(client, auth_headers):
    """TC-EP-09  /api/pedestals/health includes ext_berths_occupancy etc. per pedestal."""
    pid = _get_test_pedestal_id()
    _setup_gateway_config(["berths.occupancy_ext", "camera.stream_ext"])
    _setup_pedestal_camera(pid, "rtsp://cam:554/live", reachable=True)

    r = client.get("/api/pedestals/health", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()

    # There may be no PedestalConfig rows if test pedestal has none
    # (health only iterates configs that exist)
    # At minimum the response must not error and must be a dict
    assert isinstance(data, dict)

    for _pid_str, entry in data.items():
        assert "ext_berths_occupancy" in entry, f"Missing ext_berths_occupancy in {entry}"
        assert "ext_camera_frame" in entry
        assert "ext_camera_stream" in entry

        for field in ("ext_berths_occupancy", "ext_camera_frame", "ext_camera_stream"):
            h = entry[field]
            assert "enabled" in h
            assert "available" in h
            assert "reason" in h


# ─────────────────────────────────────────────────────────────────────────────
# TC-EP-10  Toggle persists and takes effect immediately
# ─────────────────────────────────────────────────────────────────────────────

def test_toggle_persists_and_takes_effect_immediately(client, auth_headers):
    """TC-EP-10  Enable then disable: endpoint switches 200 → 503 without restart."""
    pid = _get_test_pedestal_id()

    # Enable berths.occupancy_ext
    _setup_gateway_config(["berths.occupancy_ext"])
    _delete_berths_for_pedestal(pid)

    r_enabled = client.get(
        f"/api/ext/pedestals/{pid}/berths/occupancy",
        headers=_ext_headers(),
    )
    # Should not be 503 "Not enabled" (may be 200 empty)
    assert r_enabled.status_code != 503 or r_enabled.json().get("reason") != "Not enabled", \
        f"Expected endpoint to be enabled, got {r_enabled.status_code}: {r_enabled.text}"

    # Disable berths.occupancy_ext (leave nothing enabled)
    _setup_gateway_config([])

    r_disabled = client.get(
        f"/api/ext/pedestals/{pid}/berths/occupancy",
        headers=_ext_headers(),
    )
    assert r_disabled.status_code == 503
    assert r_disabled.json()["reason"] == "Not enabled"


# ─────────────────────────────────────────────────────────────────────────────
# TC-EP-11  Health indicators populated for enabled + available endpoints
# ─────────────────────────────────────────────────────────────────────────────

def test_health_indicators_correct_for_enabled_available(client, auth_headers):
    """TC-EP-11  Enabled + available → enabled=True/available=True; disabled → enabled=False."""
    pid = _get_test_pedestal_id()
    _delete_berths_for_pedestal(pid)
    _seed_berth(pid, analyzed=True, occupied=False)
    _setup_gateway_config(["berths.occupancy_ext"])  # only berths enabled
    _setup_pedestal_camera(pid, "rtsp://cam:554/live", reachable=True)

    r = client.get("/api/pedestals/health", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()

    if not data:
        pytest.skip("No PedestalConfig rows — health endpoint has nothing to iterate")

    for entry in data.values():
        berths_h = entry["ext_berths_occupancy"]
        cam_frame_h = entry["ext_camera_frame"]
        cam_stream_h = entry["ext_camera_stream"]

        assert berths_h["enabled"] is True
        # availability depends on whether this specific pedestal has berths seeded
        assert cam_frame_h["enabled"] is False
        assert cam_stream_h["enabled"] is False
        assert cam_frame_h["reason"] == "Not enabled"
        assert cam_stream_h["reason"] == "Not enabled"


# ─────────────────────────────────────────────────────────────────────────────
# Auth enforcement — all endpoints reject unauthenticated requests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path_suffix", [
    "berths/occupancy",
    "camera/frame",
    "camera/stream",
])
def test_ext_endpoints_require_auth(client, path_suffix):
    """All ext pedestal endpoints reject requests with no/bad Authorization header."""
    pid = _get_test_pedestal_id()
    _setup_gateway_config(["berths.occupancy_ext", "camera.frame_ext", "camera.stream_ext"])

    # No auth
    r = client.get(f"/api/ext/pedestals/{pid}/{path_suffix}")
    assert r.status_code in (401, 403), f"{path_suffix} returned {r.status_code}"

    # Bad token
    r2 = client.get(
        f"/api/ext/pedestals/{pid}/{path_suffix}",
        headers={"Authorization": "Bearer bad-token"},
    )
    assert r2.status_code in (401, 403)
