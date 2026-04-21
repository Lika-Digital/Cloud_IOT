"""
Auto-discovery + QR bundle — Verification Tests (v3.7)
======================================================

Covers the MQTT-driven auto-creation of Pedestal / PedestalConfig /
SocketConfig rows, the per-socket printable QR PNG disk cache, the bulk
ZIP + regenerate endpoints, and the throttled `pedestal_registered`
WebSocket broadcast.

Test IDs:
  TC-DISC-01  Unknown cabinet in opta/status → new PedestalConfig row,
              `first_seen_at` + `status=online` set.
  TC-DISC-02  Pedestal.name is prettified on first creation.
  TC-DISC-03  Operator-customised name is NOT overwritten on reconnect.
  TC-DISC-04  last_heartbeat is bumped on second opta/status.
  TC-DISC-05  Unknown socket status → new SocketConfig row with
              `auto_activate=false`.
  TC-DISC-06  Existing SocketConfig with auto_activate=true is preserved.
  TC-DISC-07  QR PNG written to backend/static/qr/{cab}_Q{n}.png on first
              socket discovery.
  TC-DISC-08  QR PNG not regenerated when file already exists.
  TC-QR-ALL   GET /api/pedestals/{cab}/qr/all returns a valid ZIP with the
              correct filename header and 4 PNG entries.
  TC-QR-REGEN POST /api/pedestals/{cab}/qr/regenerate deletes disk cache
              and rewrites all 4 PNGs.
  TC-WS-NEW   `pedestal_registered` broadcast fires with is_new=True the
              first time we see a cabinet.
  TC-WS-REOPEN Second opta/status for the same cabinet broadcasts
              is_new=False (throttle already elapsed).
  TC-WS-THROTTLE Third opta/status within 60s does NOT rebroadcast.
  TC-QR-404   /qr/all returns 404 for an unknown cabinet.
"""
from __future__ import annotations
import asyncio
import json
import zipfile
import io
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


TEST_DB = "sqlite:///./tests/test_pedestal.db"
_test_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False}, poolclass=StaticPool)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


@pytest.fixture(scope="module", autouse=True)
def _dispose_engine():
    yield
    _test_engine.dispose()


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _fire_opta_status(cabinet_id: str, seq: int = 42, capture: list[dict] | None = None):
    """Inject an opta/status payload and optionally capture ws broadcasts."""
    broadcasts = capture if capture is not None else []

    async def grab(msg):
        broadcasts.append(msg)

    from app.services.mqtt_handlers import handle_message
    payload = json.dumps({
        "cabinetId": cabinet_id,
        "seq": seq,
        "uptime_ms": 10_000,
        "door": "closed",
    })
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", side_effect=grab),
    ):
        await handle_message("opta/status", payload)
        # Give any create_task-scheduled announces a tick to run.
        await asyncio.sleep(0.05)
    return broadcasts


async def _fire_opta_socket(cabinet_id: str, socket_name: str, state: str = "idle",
                            capture: list[dict] | None = None):
    broadcasts = capture if capture is not None else []

    async def grab(msg):
        broadcasts.append(msg)

    from app.services.mqtt_handlers import handle_message
    payload = json.dumps({
        "cabinetId": cabinet_id,
        "id": socket_name,
        "state": state,
        "hw_status": "off",
        "ts": 1_000_000,
    })
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", side_effect=grab),
    ):
        await handle_message(f"opta/sockets/{socket_name}/status", payload)
    return broadcasts


def _qr_file(cabinet_id: str, socket_name: str) -> Path:
    """Mirror qr_service._qr_path — test-local so we don't depend on the
    module re-exporting an internal helper."""
    from app.services.qr_service import qr_dir
    return Path(qr_dir()) / f"{cabinet_id}_{socket_name}.png"


def _pedestal_for(cabinet_id: str):
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        return db.query(PedestalConfig).filter_by(opta_client_id=cabinet_id).first()
    finally:
        db.close()


def _clear_throttle():
    """Reset the module-level pedestal_registered throttle between tests so
    each test sees a clean broadcast timeline."""
    from app.services.mqtt_handlers import _pedestal_registered_last_at
    _pedestal_registered_last_at.clear()


def _events_of(broadcasts: list[dict], event: str) -> list[dict]:
    return [b for b in broadcasts if b.get("event") == event]


@pytest.fixture
def clean_fs():
    """Wipe QR PNGs AND SocketConfig rows for the cabinets these tests use
    so we assert on creation / non-regeneration deterministically.

    SocketConfig rows drive the `_auto_discover_socket_config` "newly created"
    branch that triggers QR generation — clearing them on entry guarantees
    each test's first socket status is treated as a first-contact."""
    from app.services.qr_service import delete_all_qr_for_pedestal
    test_cabs = ("TC_DISC_A", "TC_DISC_B", "TC_DISC_C", "TC_DISC_CLEAR")

    # DB cleanup: SocketConfig rows whose pedestal_id points at our test
    # cabinets. The PedestalConfig rows themselves can survive — multiple
    # tests sharing one pedestal is fine.
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    db = _TestSession()
    try:
        pids = [
            cfg.pedestal_id for cfg in
            db.query(PedestalConfig).filter(PedestalConfig.opta_client_id.in_(test_cabs)).all()
        ]
        if pids:
            db.query(SocketConfig).filter(SocketConfig.pedestal_id.in_(pids)).delete(
                synchronize_session=False,
            )
            db.commit()
    finally:
        db.close()

    for cab in test_cabs:
        delete_all_qr_for_pedestal(cab)
    yield
    for cab in test_cabs:
        delete_all_qr_for_pedestal(cab)


# ═════════════════════════════════════════════════════════════════════════════
# Pedestal discovery
# ═════════════════════════════════════════════════════════════════════════════

def test_unknown_cabinet_creates_pedestal_config(clean_fs):
    """TC-DISC-01, TC-DISC-02"""
    _clear_throttle()
    asyncio.run(_fire_opta_status("TC_DISC_A"))

    cfg = _pedestal_for("TC_DISC_A")
    assert cfg is not None
    assert cfg.first_seen_at is not None
    assert cfg.status == "online"

    # TC-DISC-02 — name prettified.
    from app.models.pedestal import Pedestal
    db = _TestSession()
    try:
        p = db.get(Pedestal, cfg.pedestal_id)
        assert p is not None
        assert p.name == "TC DISC A"
    finally:
        db.close()


def test_operator_renamed_pedestal_survives_reconnect(clean_fs):
    """TC-DISC-03 — admin rename must not be clobbered by heartbeat."""
    _clear_throttle()
    asyncio.run(_fire_opta_status("TC_DISC_A"))
    from app.models.pedestal import Pedestal
    cfg = _pedestal_for("TC_DISC_A")
    db = _TestSession()
    try:
        p = db.get(Pedestal, cfg.pedestal_id)
        p.name = "Custom Operator Name"
        db.commit()
    finally:
        db.close()

    asyncio.run(_fire_opta_status("TC_DISC_A"))
    db = _TestSession()
    try:
        p = db.get(Pedestal, cfg.pedestal_id)
        assert p.name == "Custom Operator Name"
    finally:
        db.close()


def test_last_heartbeat_updated_on_reconnect(clean_fs):
    """TC-DISC-04"""
    _clear_throttle()
    asyncio.run(_fire_opta_status("TC_DISC_A"))
    cfg = _pedestal_for("TC_DISC_A")
    # Zero out last_heartbeat
    db = _TestSession()
    try:
        from app.models.pedestal_config import PedestalConfig
        row = db.query(PedestalConfig).filter_by(opta_client_id="TC_DISC_A").first()
        row.last_heartbeat = datetime.utcnow() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    asyncio.run(_fire_opta_status("TC_DISC_A"))

    cfg2 = _pedestal_for("TC_DISC_A")
    assert cfg2.last_heartbeat is not None
    assert (datetime.utcnow() - cfg2.last_heartbeat).total_seconds() < 60


# ═════════════════════════════════════════════════════════════════════════════
# Socket discovery + QR cache
# ═════════════════════════════════════════════════════════════════════════════

def test_unknown_socket_creates_socket_config(clean_fs):
    """TC-DISC-05"""
    _clear_throttle()
    asyncio.run(_fire_opta_status("TC_DISC_A"))
    cfg = _pedestal_for("TC_DISC_A")

    asyncio.run(_fire_opta_socket("TC_DISC_A", "Q3"))

    from app.models.socket_config import SocketConfig
    db = _TestSession()
    try:
        row = db.query(SocketConfig).filter_by(
            pedestal_id=cfg.pedestal_id, socket_id=3,
        ).first()
        assert row is not None
        assert row.auto_activate is False
    finally:
        db.close()


def test_existing_socket_config_not_modified(clean_fs):
    """TC-DISC-06 — auto_activate=true must survive a subsequent status."""
    _clear_throttle()
    asyncio.run(_fire_opta_status("TC_DISC_A"))
    cfg = _pedestal_for("TC_DISC_A")
    from app.models.socket_config import SocketConfig
    db = _TestSession()
    try:
        db.add(SocketConfig(pedestal_id=cfg.pedestal_id, socket_id=2, auto_activate=True))
        db.commit()
    finally:
        db.close()

    asyncio.run(_fire_opta_socket("TC_DISC_A", "Q2"))

    db = _TestSession()
    try:
        row = db.query(SocketConfig).filter_by(pedestal_id=cfg.pedestal_id, socket_id=2).first()
        assert row.auto_activate is True
    finally:
        db.close()


def test_qr_png_generated_on_first_socket(clean_fs):
    """TC-DISC-07"""
    _clear_throttle()
    asyncio.run(_fire_opta_status("TC_DISC_A"))
    asyncio.run(_fire_opta_socket("TC_DISC_A", "Q1"))
    # First-contact socket write + discovery hook creates the PNG.
    assert _qr_file("TC_DISC_A", "Q1").exists(), "Expected QR PNG on disk"


def test_qr_png_not_regenerated_when_present(clean_fs):
    """TC-DISC-08 — the same mtime before and after a second socket status."""
    _clear_throttle()
    asyncio.run(_fire_opta_status("TC_DISC_A"))
    asyncio.run(_fire_opta_socket("TC_DISC_A", "Q1"))
    p = _qr_file("TC_DISC_A", "Q1")
    first_mtime = p.stat().st_mtime

    asyncio.run(_fire_opta_socket("TC_DISC_A", "Q1"))
    assert p.stat().st_mtime == first_mtime, "File must not be rewritten on idempotent path"


# ═════════════════════════════════════════════════════════════════════════════
# ZIP bundle + regenerate
# ═════════════════════════════════════════════════════════════════════════════

def test_qr_all_endpoint_returns_zip(client, auth_headers, clean_fs):
    """TC-QR-ALL"""
    _clear_throttle()
    asyncio.run(_fire_opta_status("TC_DISC_A"))
    r = client.get("/api/pedestals/TC_DISC_A/qr/all", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert 'TC_DISC_A_qr_codes.zip' in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = sorted(zf.namelist())
    assert names == [
        "TC_DISC_A_Q1.png", "TC_DISC_A_Q2.png", "TC_DISC_A_Q3.png", "TC_DISC_A_Q4.png",
    ]
    # Each entry must be a real PNG (magic 89 50 4E 47).
    for n in names:
        data = zf.read(n)
        assert data[:4] == b"\x89PNG"


def test_qr_regenerate_endpoint_rewrites_files(client, auth_headers, clean_fs):
    """TC-QR-REGEN"""
    _clear_throttle()
    asyncio.run(_fire_opta_status("TC_DISC_A"))
    asyncio.run(_fire_opta_socket("TC_DISC_A", "Q1"))
    p = _qr_file("TC_DISC_A", "Q1")
    before = p.stat().st_mtime

    # Make sure the filesystem mtime resolution doesn't hide the rewrite.
    os.utime(p, (before - 5, before - 5))

    r = client.post("/api/pedestals/TC_DISC_A/qr/regenerate", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cabinet_id"] == "TC_DISC_A"
    assert sorted(body["regenerated"]) == ["Q1", "Q2", "Q3", "Q4"]
    assert p.exists()
    assert p.stat().st_mtime > before - 5


def test_qr_all_404_unknown_cabinet(client, auth_headers):
    """TC-QR-404"""
    r = client.get("/api/pedestals/NOT_A_REAL_CAB/qr/all", headers=auth_headers)
    assert r.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
# pedestal_registered WS event
# ═════════════════════════════════════════════════════════════════════════════

def test_pedestal_registered_is_new_true_on_first_contact(clean_fs):
    """TC-WS-NEW"""
    _clear_throttle()
    broadcasts: list[dict] = []
    asyncio.run(_fire_opta_status("TC_DISC_B", capture=broadcasts))
    events = _events_of(broadcasts, "pedestal_registered")
    assert events, f"No pedestal_registered broadcast; got {[b.get('event') for b in broadcasts]}"
    # The first-contact announce is_new=True.
    assert any(e["data"]["is_new"] is True for e in events)
    first_new = next(e for e in events if e["data"]["is_new"] is True)
    assert first_new["data"]["cabinet_id"] == "TC_DISC_B"
    assert first_new["data"]["socket_ids"] == ["Q1", "Q2", "Q3", "Q4"]
    assert "timestamp" in first_new["data"]


def test_pedestal_registered_is_new_false_on_reconnect(clean_fs):
    """TC-WS-REOPEN"""
    _clear_throttle()
    asyncio.run(_fire_opta_status("TC_DISC_C"))
    # Expire the throttle.
    from app.services.mqtt_handlers import _pedestal_registered_last_at
    for pid in list(_pedestal_registered_last_at.keys()):
        _pedestal_registered_last_at[pid] = datetime.utcnow() - timedelta(seconds=120)

    broadcasts: list[dict] = []
    asyncio.run(_fire_opta_status("TC_DISC_C", capture=broadcasts))
    events = _events_of(broadcasts, "pedestal_registered")
    assert events, "Expected is_new=False broadcast after throttle window"
    assert events[-1]["data"]["is_new"] is False


def test_pedestal_registered_throttle_suppresses_burst(clean_fs):
    """TC-WS-THROTTLE — two heartbeats within 60s => one broadcast."""
    _clear_throttle()
    asyncio.run(_fire_opta_status("TC_DISC_CLEAR"))

    broadcasts: list[dict] = []
    asyncio.run(_fire_opta_status("TC_DISC_CLEAR", capture=broadcasts))
    asyncio.run(_fire_opta_status("TC_DISC_CLEAR", capture=broadcasts))
    events = _events_of(broadcasts, "pedestal_registered")
    # The second heartbeat (first in this capture) may broadcast if the
    # first-contact one set the throttle clock >60s ago — in practice the
    # clock was set <1ms ago so expect 0 or 1, never 2.
    assert len(events) <= 1
