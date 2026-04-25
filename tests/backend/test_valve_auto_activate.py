"""
Per-Valve Auto-Activation + Post-Diagnostic Auto-Open — Verification Tests (v3.9)
=================================================================================

Coverage for the v3.9 feature. Each test follows the patching convention from
test_socket_plug_state_machine.py — inject the MQTT message via `handle_message`
and capture the resulting WS broadcasts + verify the MQTT publisher was called.

Test IDs:
  TC-VA-01  post-diag fires activate when auto_activate=True AND per-valve sensor=ok
  TC-VA-02  post-diag SKIPS valve whose auto_activate=False
  TC-VA-03  post-diag SKIPS valve that already has an active water session
  TC-VA-04  post-diag only fires for valves whose individual sensor is ok
            (V1 fails → V1 skipped, V2 ok → V2 activated)
  TC-VA-05  post-diag SKIPS valve that was manually stopped in last 10 minutes
            (cooldown guard)
  TC-VA-06  default ValveConfig.auto_activate is TRUE on first discovery
  TC-VA-07  config endpoints: GET returns default true, PATCH persists override
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


TEST_DB = "sqlite:///./tests/test_pedestal.db"
_test_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False}, poolclass=StaticPool)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

CABINET = "MAR_KRK_ORM_V9"


@pytest.fixture(scope="module", autouse=True)
def _dispose_engine():
    yield
    _test_engine.dispose()


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Each test starts with a clean manual-stop dict and no active water
    sessions on the test cabinet so guards are tested in isolation."""
    from app.services import mqtt_handlers as mh
    from app.models.session import Session as SessionModel
    from app.models.pedestal_config import PedestalConfig
    mh.last_valve_manual_stop_at.clear()
    mh.last_diagnostic_ok_at.clear()
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(opta_client_id=CABINET).first()
        if cfg is not None:
            db.query(SessionModel).filter(
                SessionModel.pedestal_id == cfg.pedestal_id,
                SessionModel.type == "water",
                SessionModel.status.in_(("pending", "active")),
            ).delete(synchronize_session=False)
            db.commit()
    finally:
        db.close()
    yield


def _pedestal_id_for_cabinet() -> int:
    """Return the pedestal_id auto-created the first time CABINET was seen."""
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(opta_client_id=CABINET).first()
        return cfg.pedestal_id if cfg else 0
    finally:
        db.close()


def _ensure_cabinet_registered() -> int:
    """Trigger a first MQTT contact so the cabinet row exists."""
    _publish("opta/status", {"cabinetId": CABINET, "seq": 1, "uptime_ms": 1000})
    return _pedestal_id_for_cabinet()


def _publish(topic: str, payload: dict) -> tuple[list[dict], list[tuple[str, str]]]:
    """Run handle_message for a topic+payload; return (ws_broadcasts, mqtt_publishes)."""
    broadcasts: list[dict] = []
    publishes: list[tuple[str, str]] = []

    async def capture_broadcast(msg):
        broadcasts.append(msg)

    def capture_publish(topic: str, payload: str, *a, **kw):
        publishes.append((topic, payload))

    from app.services.mqtt_handlers import handle_message
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", side_effect=capture_broadcast),
        patch("app.services.mqtt_client.mqtt_service.publish", side_effect=capture_publish),
    ):
        asyncio.run(handle_message(topic, json.dumps(payload)))

    return broadcasts, publishes


def _seed_valve_config(pedestal_id: int, valve_id: int, auto_activate: bool) -> None:
    from app.models.valve_config import ValveConfig
    db = _TestSession()
    try:
        row = db.query(ValveConfig).filter_by(pedestal_id=pedestal_id, valve_id=valve_id).first()
        if row is None:
            row = ValveConfig(pedestal_id=pedestal_id, valve_id=valve_id, auto_activate=auto_activate)
            db.add(row)
        else:
            row.auto_activate = auto_activate
        db.commit()
    finally:
        db.close()


def _seed_active_water_session(pedestal_id: int, valve_id: int) -> int:
    from app.models.session import Session as SessionModel
    db = _TestSession()
    try:
        s = SessionModel(
            pedestal_id=pedestal_id, socket_id=valve_id, type="water",
            status="active", started_at=datetime.utcnow(),
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return s.id
    finally:
        db.close()


def _build_diag_payload(cabinet_id: str, v1_ok: bool, v2_ok: bool) -> dict:
    return {
        "cabinetId": cabinet_id,
        "power": [
            {"id": "Q1", "hw": "ok", "state": "idle"},
            {"id": "Q2", "hw": "ok", "state": "idle"},
            {"id": "Q3", "hw": "ok", "state": "idle"},
            {"id": "Q4", "hw": "ok", "state": "idle"},
        ],
        "water": [
            {"id": "V1", "hw": "ok" if v1_ok else "fault"},
            {"id": "V2", "hw": "ok" if v2_ok else "fault"},
        ],
        "mqtt": "connected",
        "time": "2026-04-24T10:00:00Z",
    }


# ── TC-VA-01 ──────────────────────────────────────────────────────────────────

def test_post_diag_fires_activate_when_config_true_and_sensor_ok():
    pid = _ensure_cabinet_registered()
    _seed_valve_config(pid, 1, auto_activate=True)
    _seed_valve_config(pid, 2, auto_activate=True)

    _broadcasts, publishes = _publish("opta/diagnostic", _build_diag_payload(CABINET, v1_ok=True, v2_ok=True))

    v1_publishes = [p for p in publishes if p[0] == "opta/cmd/water/V1"]
    v2_publishes = [p for p in publishes if p[0] == "opta/cmd/water/V2"]
    assert len(v1_publishes) == 1
    assert len(v2_publishes) == 1
    for _topic, body in v1_publishes + v2_publishes:
        msg = json.loads(body)
        assert msg["action"] == "activate"
        assert msg["cabinetId"] == CABINET


# ── TC-VA-02 ──────────────────────────────────────────────────────────────────

def test_post_diag_skips_valve_with_auto_activate_false():
    pid = _ensure_cabinet_registered()
    _seed_valve_config(pid, 1, auto_activate=False)
    _seed_valve_config(pid, 2, auto_activate=True)

    _broadcasts, publishes = _publish("opta/diagnostic", _build_diag_payload(CABINET, v1_ok=True, v2_ok=True))

    v1_publishes = [p for p in publishes if p[0] == "opta/cmd/water/V1"]
    v2_publishes = [p for p in publishes if p[0] == "opta/cmd/water/V2"]
    assert len(v1_publishes) == 0, "V1 had auto_activate=False — must NOT publish activate"
    assert len(v2_publishes) == 1


# ── TC-VA-03 ──────────────────────────────────────────────────────────────────

def test_post_diag_skips_valve_with_active_session():
    pid = _ensure_cabinet_registered()
    _seed_valve_config(pid, 1, auto_activate=True)
    _seed_valve_config(pid, 2, auto_activate=True)
    _seed_active_water_session(pid, 1)   # Pre-existing active session on V1

    _broadcasts, publishes = _publish("opta/diagnostic", _build_diag_payload(CABINET, v1_ok=True, v2_ok=True))

    v1_publishes = [p for p in publishes if p[0] == "opta/cmd/water/V1"]
    v2_publishes = [p for p in publishes if p[0] == "opta/cmd/water/V2"]
    assert len(v1_publishes) == 0, "V1 already has an active session — must NOT publish activate"
    assert len(v2_publishes) == 1


# ── TC-VA-04 ──────────────────────────────────────────────────────────────────

def test_post_diag_only_fires_valves_whose_sensor_is_ok():
    pid = _ensure_cabinet_registered()
    _seed_valve_config(pid, 1, auto_activate=True)
    _seed_valve_config(pid, 2, auto_activate=True)

    _broadcasts, publishes = _publish("opta/diagnostic", _build_diag_payload(CABINET, v1_ok=False, v2_ok=True))

    v1_publishes = [p for p in publishes if p[0] == "opta/cmd/water/V1"]
    v2_publishes = [p for p in publishes if p[0] == "opta/cmd/water/V2"]
    assert len(v1_publishes) == 0, "V1 sensor reported fault — must NOT publish activate"
    assert len(v2_publishes) == 1


# ── TC-VA-05 ──────────────────────────────────────────────────────────────────

def test_post_diag_skips_valve_within_manual_stop_cooldown():
    pid = _ensure_cabinet_registered()
    _seed_valve_config(pid, 1, auto_activate=True)
    _seed_valve_config(pid, 2, auto_activate=True)

    # Simulate an operator manual stop 5 minutes ago (< 10-min cooldown).
    from app.services import mqtt_handlers as mh
    mh.last_valve_manual_stop_at[(pid, 1)] = datetime.utcnow() - timedelta(minutes=5)

    _broadcasts, publishes = _publish("opta/diagnostic", _build_diag_payload(CABINET, v1_ok=True, v2_ok=True))

    v1_publishes = [p for p in publishes if p[0] == "opta/cmd/water/V1"]
    v2_publishes = [p for p in publishes if p[0] == "opta/cmd/water/V2"]
    assert len(v1_publishes) == 0, "V1 within 10-min cooldown — must NOT publish activate"
    assert len(v2_publishes) == 1

    # Now verify cooldown expires cleanly.
    mh.last_valve_manual_stop_at[(pid, 1)] = datetime.utcnow() - timedelta(minutes=15)

    _broadcasts2, publishes2 = _publish("opta/diagnostic", _build_diag_payload(CABINET, v1_ok=True, v2_ok=True))
    v1_publishes_post = [p for p in publishes2 if p[0] == "opta/cmd/water/V1"]
    assert len(v1_publishes_post) == 1, "V1 past 10-min cooldown — must publish activate"


# ── TC-VA-06 ──────────────────────────────────────────────────────────────────

def test_valve_auto_discovery_defaults_to_true():
    from app.models.valve_config import ValveConfig
    # Fresh cabinet so discovery runs for the first time on the next water status.
    cab = "MAR_KRK_FRESH_V9"
    payload = {
        "cabinetId": cab, "id": "V1", "state": "idle", "ts": 1,
        "total_l": 0.0, "session_l": 0.0,
    }
    # Register pedestal first via a status heartbeat.
    _publish("opta/status", {"cabinetId": cab, "seq": 0, "uptime_ms": 1000})
    # Then water status triggers _auto_discover_valve_config.
    _publish("opta/water/V1/status", payload)

    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        pcfg = db.query(PedestalConfig).filter_by(opta_client_id=cab).first()
        assert pcfg is not None
        vcfg = db.query(ValveConfig).filter_by(pedestal_id=pcfg.pedestal_id, valve_id=1).first()
        assert vcfg is not None
        assert vcfg.auto_activate is True, "Default for fresh valve must be TRUE (v3.9 design)"
    finally:
        db.close()


# ── TC-VA-07 ──────────────────────────────────────────────────────────────────

def test_valve_config_endpoints_get_and_patch(client, auth_headers):
    pid = _ensure_cabinet_registered()

    # GET before any seeding: both valves should default to True.
    r = client.get(f"/api/pedestals/{pid}/valves/config", headers=auth_headers)
    assert r.status_code == 200
    rows = r.json()
    assert {r["valve_id"] for r in rows} == {1, 2}
    assert all(r["auto_activate"] is True for r in rows)

    # PATCH V1 to False and re-read.
    r = client.patch(
        f"/api/pedestals/{pid}/valves/1/config",
        json={"auto_activate": False},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json() == {"valve_id": 1, "auto_activate": False}

    r = client.get(f"/api/pedestals/{pid}/valves/config", headers=auth_headers)
    v1 = next(r for r in r.json() if r["valve_id"] == 1)
    assert v1["auto_activate"] is False
