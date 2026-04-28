"""
Live socket meter telemetry + load monitoring (v3.11)
======================================================

Test coverage map:
  TC-ML-01  Hardware config payload writes all socket fields
  TC-ML-02  Hardware config update modifies existing rows
  TC-ML-03  Absent fields preserve existing values (no-overwrite-with-null)
  TC-ML-04  hardware_config_updated WS event broadcast
  TC-ML-05  Telemetry skips load calc when rated_amps null + logs warning
  TC-ML-06  Single-phase detection from currentAmps presence
  TC-ML-07  Three-phase detection from currentAmpsTotal presence
  TC-ML-08  Load pct correct: single-phase = currentAmps / rated × 100
  TC-ML-09  Load pct correct: three-phase = max(L1,L2,L3) / rated × 100
            (D2 — bottleneck phase, NOT total/rated which the spec said wrongly)
  TC-ML-10  normal → warning: row created, broadcast fired
  TC-ML-11  warning → critical: warning auto-resolved (auto-upgrade), critical
            row inserted, broadcast fired
  TC-ML-12  critical → warning: critical auto-resolved (auto-downgrade)
  TC-ML-13  any → normal: all open rows resolved (auto-resolve), broadcast fired
  TC-ML-14  No duplicate alarm row when load stays in same status
  TC-ML-15  Hysteresis on resolve — load drops to threshold itself stays in
            elevated state, only drops out when below threshold − 2
  TC-ML-16  Three-phase WS payload includes per-phase currents
  TC-ML-17  Single-phase WS payload omits per-phase fields
  TC-ML-18  PATCH thresholds 400 when warning >= critical
  TC-ML-19  PATCH thresholds 400 when value out of 1..99 range
  TC-ML-20  GET socket load returns all fields including hw_config_received_at
  TC-ML-21  GET pedestal load returns all sockets
  TC-ML-22  GET load alarms returns ONLY unresolved rows
  TC-ML-23  POST acknowledge flips flag, alarm stays open
  TC-ML-24  POST resolve closes alarm with operator email
  TC-ML-25  ERP socket load endpoint returns load state
  TC-ML-26  ERP marina alarms returns active alarms across pedestals
  TC-ML-27  All 5 ERP load endpoints registered in api_catalog
  TC-ML-28  All 4 EVENT_CATALOG meter events present
  TC-ML-29  ERP endpoint 401 on missing auth
  TC-ML-30  Drift guard — every backend `meter_*`/`hardware_config_updated`
            event has a frontend handler (run as part of full suite)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


TEST_DB = "sqlite:///./tests/test_pedestal.db"
_test_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False}, poolclass=StaticPool)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

CABINET = "MAR_KRK_ORM_LOAD"


@pytest.fixture(scope="module", autouse=True)
def _dispose_engine():
    yield
    _test_engine.dispose()


@pytest.fixture(autouse=True)
def _patch_routers_to_test_db():
    """Same trick as test_breaker_monitoring — make ERP routes use the
    shared test DB so direct ORM seeding round-trips through HTTP."""
    with patch("app.routers.ext_meter_load_endpoints.SessionLocal", _TestSession):
        yield


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test starts with no open alarms on the test cabinet."""
    from app.models.meter_load_alarm import MeterLoadAlarm
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(opta_client_id=CABINET).first()
        if cfg is not None:
            db.query(MeterLoadAlarm).filter_by(pedestal_id=cfg.pedestal_id).delete(synchronize_session=False)
            # Reset SocketConfig meter fields back to clean state.
            for sc in db.query(SocketConfig).filter_by(pedestal_id=cfg.pedestal_id).all():
                sc.meter_load_status = "unknown"
                sc.meter_load_pct = None
                sc.load_warning_threshold_pct = 60
                sc.load_critical_threshold_pct = 80
            db.commit()
    finally:
        db.close()
    yield


# ── helpers ──────────────────────────────────────────────────────────────────

def _simulate(topic: str, payload: dict) -> list[dict]:
    """Inject an MQTT message; return all WS broadcasts it triggered."""
    broadcasts: list[dict] = []

    async def capture(msg):
        broadcasts.append(msg)

    from app.services.mqtt_handlers import handle_message
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", side_effect=capture),
    ):
        asyncio.run(handle_message(topic, json.dumps(payload)))
    return broadcasts


def _ensure_cabinet() -> int:
    """Trigger a status heartbeat so the cabinet auto-discovery row exists."""
    _simulate("opta/status", {"cabinetId": CABINET, "seq": 1, "uptime_ms": 1000})
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(opta_client_id=CABINET).first()
        return cfg.pedestal_id if cfg else 0
    finally:
        db.close()


def _seed_hw_config(pedestal_id: int, socket_id: int, **fields) -> None:
    from app.models.socket_config import SocketConfig
    db = _TestSession()
    try:
        cfg = db.query(SocketConfig).filter_by(pedestal_id=pedestal_id, socket_id=socket_id).first()
        if cfg is None:
            cfg = SocketConfig(pedestal_id=pedestal_id, socket_id=socket_id, auto_activate=False)
            db.add(cfg)
        for k, v in fields.items():
            setattr(cfg, k, v)
        cfg.hw_config_received_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _make_ext_jwt(role: str = "api_client") -> str:
    import jwt
    payload = {
        "sub": "test-erp",
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, "test-secret-key-for-ci", algorithm="HS256")


def _enable_ext_endpoints(ep_ids: list[str]) -> None:
    from app.models.external_api import ExternalApiConfig
    db = _TestSession()
    try:
        cfg = db.get(ExternalApiConfig, 1)
        allowed = [{"id": e, "mode": "monitor"} for e in ep_ids]
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
        db.commit()
    finally:
        db.close()


def _get_socket_cfg(pedestal_id: int, socket_id: int):
    from app.models.socket_config import SocketConfig
    db = _TestSession()
    try:
        return db.query(SocketConfig).filter_by(pedestal_id=pedestal_id, socket_id=socket_id).first()
    finally:
        db.close()


# ── TC-ML-01..04 ─────────────────────────────────────────────────────────────

def test_hw_config_writes_all_socket_fields():
    pid = _ensure_cabinet()
    _simulate("opta/config/hardware", {
        "cabinetId": CABINET,
        "firmwareVersion": "2.1.0",
        "sockets": [
            {"socketId": "Q1", "meterType": "ABB D11 15-M 40", "phases": 1, "ratedAmps": 16, "modbusAddress": 1},
            {"socketId": "Q4", "meterType": "ABB D13 15-M 65", "phases": 3, "ratedAmps": 65, "modbusAddress": 4},
        ],
    })
    q1 = _get_socket_cfg(pid, 1)
    q4 = _get_socket_cfg(pid, 4)
    assert q1.meter_type == "ABB D11 15-M 40"
    assert q1.phases == 1
    assert q1.rated_amps == pytest.approx(16.0)
    assert q1.modbus_address == 1
    assert q1.hw_config_received_at is not None
    assert q4.phases == 3
    assert q4.rated_amps == pytest.approx(65.0)


def test_hw_config_update_modifies_existing_rows():
    pid = _ensure_cabinet()
    _simulate("opta/config/hardware", {
        "cabinetId": CABINET,
        "sockets": [{"socketId": "Q1", "ratedAmps": 16, "phases": 1, "meterType": "OLD"}],
    })
    _simulate("opta/config/hardware", {
        "cabinetId": CABINET,
        "sockets": [{"socketId": "Q1", "ratedAmps": 32, "phases": 1, "meterType": "NEW"}],
    })
    cfg = _get_socket_cfg(pid, 1)
    assert cfg.rated_amps == pytest.approx(32.0)
    assert cfg.meter_type == "NEW"


def test_hw_config_absent_fields_preserve_values():
    pid = _ensure_cabinet()
    _simulate("opta/config/hardware", {
        "cabinetId": CABINET,
        "sockets": [{"socketId": "Q2", "meterType": "Schneider iC60", "phases": 1, "ratedAmps": 20, "modbusAddress": 2}],
    })
    # Second message omits ratedAmps + modbusAddress — must be preserved.
    _simulate("opta/config/hardware", {
        "cabinetId": CABINET,
        "sockets": [{"socketId": "Q2", "meterType": "Schneider iC60", "phases": 1}],
    })
    cfg = _get_socket_cfg(pid, 2)
    assert cfg.rated_amps == pytest.approx(20.0)
    assert cfg.modbus_address == 2


def test_hw_config_broadcasts_event():
    _ensure_cabinet()
    broadcasts = _simulate("opta/config/hardware", {
        "cabinetId": CABINET,
        "sockets": [{"socketId": "Q1", "phases": 1, "ratedAmps": 16, "meterType": "X", "modbusAddress": 1}],
    })
    events = [b for b in broadcasts if b.get("event") == "hardware_config_updated"]
    assert len(events) == 1
    assert events[0]["data"]["sockets"][0]["socket_id"] == 1


# ── TC-ML-05 ─────────────────────────────────────────────────────────────────

def test_telemetry_skips_load_calc_when_no_hw_config(caplog):
    pid = _ensure_cabinet()
    # Make sure socket has no rated_amps.
    from app.models.socket_config import SocketConfig
    db = _TestSession()
    try:
        cfg = db.query(SocketConfig).filter_by(pedestal_id=pid, socket_id=3).first()
        if cfg is None:
            cfg = SocketConfig(pedestal_id=pid, socket_id=3, auto_activate=False)
            db.add(cfg)
        cfg.rated_amps = None
        db.commit()
    finally:
        db.close()

    with caplog.at_level("WARNING"):
        broadcasts = _simulate("opta/meters/Q3/telemetry", {
            "cabinetId": CABINET, "socketId": "Q3",
            "currentAmps": 12.5, "voltageV": 230, "powerKw": 2.9,
        })
    cfg = _get_socket_cfg(pid, 3)
    assert cfg.meter_current_amps == pytest.approx(12.5)
    assert cfg.meter_load_status == "unknown"
    assert cfg.meter_load_pct is None
    assert any(b.get("event") == "meter_telemetry_received" for b in broadcasts)
    assert any("no hardware config" in r.message.lower() for r in caplog.records)


# ── TC-ML-06..09 — phase detection + load formula ────────────────────────────

def test_telemetry_single_phase_detected_and_load_pct_correct():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    _simulate("opta/meters/Q1/telemetry", {
        "cabinetId": CABINET, "socketId": "Q1",
        "currentAmps": 8.0, "voltageV": 230, "powerKw": 1.84, "frequency": 50.0,
    })
    cfg = _get_socket_cfg(pid, 1)
    assert cfg.meter_load_pct == pytest.approx(25.0)        # 8 / 32 * 100
    assert cfg.meter_load_status == "normal"


def test_telemetry_three_phase_uses_max_phase_current():
    """D2 — bottleneck phase, not total/rated which would over-trigger."""
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 4, meter_type="ABB D13", phases=3, rated_amps=65.0)
    # Total = 90A which would be 138% under the spec's literal formula.
    # max(L1,L2,L3) = 32A → 32/65 = 49.2% → normal.
    _simulate("opta/meters/Q4/telemetry", {
        "cabinetId": CABINET, "socketId": "Q4",
        "currentAmpsL1": 30.0, "currentAmpsL2": 28.0, "currentAmpsL3": 32.0,
        "currentAmpsTotal": 90.0,
        "voltageL1": 231, "voltageL2": 230, "voltageL3": 232,
        "powerKwTotal": 21.0, "frequency": 50.0,
    })
    cfg = _get_socket_cfg(pid, 4)
    assert cfg.meter_load_pct == pytest.approx(32.0 / 65.0 * 100, rel=1e-3)
    assert cfg.meter_load_status == "normal"
    assert cfg.meter_current_l1 == pytest.approx(30.0)
    assert cfg.meter_current_l2 == pytest.approx(28.0)
    assert cfg.meter_current_l3 == pytest.approx(32.0)


# ── TC-ML-10..13 — alarm state machine ───────────────────────────────────────

def _trip_to(level_pct: int, pedestal_id: int, socket_id: int = 1) -> list[dict]:
    """Push current to give exactly the load_pct percentage on a 32A 1Φ socket."""
    rated = 32.0
    current = rated * (level_pct / 100.0)
    return _simulate(f"opta/meters/Q{socket_id}/telemetry", {
        "cabinetId": CABINET, "socketId": f"Q{socket_id}",
        "currentAmps": current, "voltageV": 230, "powerKw": current * 0.23,
    })


def test_normal_to_warning_inserts_row_and_broadcasts():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    _trip_to(50, pid)  # under warning (60)
    broadcasts = _trip_to(65, pid)  # over warning, under critical (80)
    assert any(b.get("event") == "meter_load_warning" for b in broadcasts)

    from app.models.meter_load_alarm import MeterLoadAlarm
    db = _TestSession()
    try:
        rows = db.query(MeterLoadAlarm).filter_by(pedestal_id=pid, socket_id=1).all()
        opens = [r for r in rows if r.resolved_at is None]
        assert len(opens) == 1
        assert opens[0].alarm_type == "warning"
    finally:
        db.close()


def test_warning_to_critical_auto_upgrades():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    _trip_to(65, pid)
    broadcasts = _trip_to(85, pid)
    assert any(b.get("event") == "meter_load_critical" for b in broadcasts)

    from app.models.meter_load_alarm import MeterLoadAlarm
    db = _TestSession()
    try:
        rows = db.query(MeterLoadAlarm).filter_by(pedestal_id=pid, socket_id=1).all()
        # One closed warning (auto-upgrade) + one open critical.
        warn_closed = [r for r in rows if r.alarm_type == "warning" and r.resolved_at is not None]
        crit_open  = [r for r in rows if r.alarm_type == "critical" and r.resolved_at is None]
        assert len(warn_closed) == 1
        assert warn_closed[0].resolved_by == "auto-upgrade"
        assert len(crit_open) == 1
    finally:
        db.close()


def test_critical_to_warning_auto_downgrades():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    _trip_to(85, pid)
    broadcasts = _trip_to(70, pid)
    assert any(b.get("event") == "meter_load_warning" for b in broadcasts)

    from app.models.meter_load_alarm import MeterLoadAlarm
    db = _TestSession()
    try:
        rows = db.query(MeterLoadAlarm).filter_by(pedestal_id=pid, socket_id=1).all()
        crit_closed = [r for r in rows if r.alarm_type == "critical" and r.resolved_at is not None]
        assert len(crit_closed) == 1
        assert crit_closed[0].resolved_by == "auto-downgrade"
    finally:
        db.close()


def test_any_to_normal_resolves_all_open_rows():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    _trip_to(85, pid)
    broadcasts = _trip_to(40, pid)
    assert any(b.get("event") == "meter_load_resolved" for b in broadcasts)

    from app.models.meter_load_alarm import MeterLoadAlarm
    db = _TestSession()
    try:
        rows = db.query(MeterLoadAlarm).filter_by(pedestal_id=pid, socket_id=1, resolved_at=None).all()
        assert rows == []
        # And the ones that ARE resolved have resolved_by="auto-resolve" for the latest.
        last = (db.query(MeterLoadAlarm)
                  .filter_by(pedestal_id=pid, socket_id=1)
                  .order_by(MeterLoadAlarm.id.desc())
                  .first())
        assert last.resolved_by == "auto-resolve"
    finally:
        db.close()


# ── TC-ML-14 — no duplicate alarm at same level ──────────────────────────────

def test_no_duplicate_alarm_when_load_stays_in_same_status():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    _trip_to(65, pid)
    _trip_to(67, pid)
    _trip_to(63, pid)
    from app.models.meter_load_alarm import MeterLoadAlarm
    db = _TestSession()
    try:
        opens = db.query(MeterLoadAlarm).filter_by(pedestal_id=pid, socket_id=1, resolved_at=None).all()
        assert len(opens) == 1
    finally:
        db.close()


# ── TC-ML-15 — hysteresis ────────────────────────────────────────────────────

def test_hysteresis_keeps_warning_until_load_drops_below_minus_2():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    _trip_to(65, pid)         # warning
    # 60% is the threshold — at exactly 60 we should still be warning.
    _trip_to(60, pid)
    cfg = _get_socket_cfg(pid, 1)
    assert cfg.meter_load_status == "warning"
    # 59% — still warning (within 2% hysteresis band).
    _trip_to(59, pid)
    cfg = _get_socket_cfg(pid, 1)
    assert cfg.meter_load_status == "warning"
    # 57% — drops below 60 - 2; should resolve.
    _trip_to(57, pid)
    cfg = _get_socket_cfg(pid, 1)
    assert cfg.meter_load_status == "normal"


# ── TC-ML-16/17 — WS payload phase-aware ─────────────────────────────────────

def test_three_phase_ws_payload_includes_per_phase_currents():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 4, meter_type="ABB D13", phases=3, rated_amps=65.0)
    broadcasts = _simulate("opta/meters/Q4/telemetry", {
        "cabinetId": CABINET, "socketId": "Q4",
        "currentAmpsL1": 12.0, "currentAmpsL2": 11.0, "currentAmpsL3": 13.0,
        "currentAmpsTotal": 36.0,
        "voltageL1": 231, "voltageL2": 230, "voltageL3": 232,
        "powerKwTotal": 8.4,
    })
    tick = [b for b in broadcasts if b.get("event") == "meter_telemetry_received"]
    assert len(tick) == 1
    d = tick[0]["data"]
    assert d["current_l1"] == pytest.approx(12.0)
    assert d["current_l2"] == pytest.approx(11.0)
    assert d["current_l3"] == pytest.approx(13.0)


def test_single_phase_ws_payload_omits_per_phase_fields():
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    broadcasts = _simulate("opta/meters/Q1/telemetry", {
        "cabinetId": CABINET, "socketId": "Q1",
        "currentAmps": 10.0, "voltageV": 230, "powerKw": 2.3,
    })
    tick = [b for b in broadcasts if b.get("event") == "meter_telemetry_received"]
    d = tick[0]["data"]
    assert "current_l1" not in d
    assert "current_l2" not in d


# ── TC-ML-18/19 — threshold validation ───────────────────────────────────────

def test_patch_thresholds_rejects_warning_gte_critical(client, auth_headers):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    r = client.patch(
        f"/api/pedestals/{pid}/sockets/1/load/thresholds",
        json={"warning_threshold_pct": 80, "critical_threshold_pct": 80},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_patch_thresholds_rejects_out_of_range(client, auth_headers):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    r = client.patch(
        f"/api/pedestals/{pid}/sockets/1/load/thresholds",
        json={"warning_threshold_pct": 0, "critical_threshold_pct": 80},
        headers=auth_headers,
    )
    assert r.status_code == 422  # Pydantic ge=1


# ── TC-ML-20/21 — GET endpoints ──────────────────────────────────────────────

def test_get_socket_load_returns_all_fields(client, auth_headers):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB D11 15-M 40", phases=1, rated_amps=32.0, modbus_address=1)
    _simulate("opta/meters/Q1/telemetry", {
        "cabinetId": CABINET, "socketId": "Q1",
        "currentAmps": 8.0, "voltageV": 230, "powerKw": 1.84, "frequency": 50.0,
    })
    r = client.get(f"/api/pedestals/{pid}/sockets/1/load", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["meter_type"] == "ABB D11 15-M 40"
    assert body["phases"] == 1
    assert body["rated_amps"] == pytest.approx(32.0)
    assert body["load_pct"] == pytest.approx(25.0)
    assert body["load_status"] == "normal"
    assert body["hw_config_received_at"] is not None


def test_get_pedestal_load_returns_all_sockets(client, auth_headers):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="A", phases=1, rated_amps=16)
    _seed_hw_config(pid, 2, meter_type="B", phases=1, rated_amps=20)
    r = client.get(f"/api/pedestals/{pid}/load", headers=auth_headers)
    assert r.status_code == 200
    socket_ids = {s["socket_id"] for s in r.json()["sockets"]}
    assert {1, 2}.issubset(socket_ids)


# ── TC-ML-22/23/24 — alarms list + ack + resolve ─────────────────────────────

def test_get_alarms_returns_only_unresolved(client, auth_headers):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    _trip_to(85, pid)
    _trip_to(40, pid)   # auto-resolve
    _trip_to(85, pid)   # new critical alarm
    r = client.get(f"/api/pedestals/{pid}/load/alarms", headers=auth_headers)
    assert r.status_code == 200
    alarms = r.json()["alarms"]
    assert all(a["resolved_at"] is None for a in alarms)
    assert any(a["alarm_type"] == "critical" for a in alarms)


def test_acknowledge_flips_flag_alarm_stays_open(client, auth_headers):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    _trip_to(85, pid)
    r = client.get(f"/api/pedestals/{pid}/load/alarms", headers=auth_headers)
    alarm_id = r.json()["alarms"][0]["id"]
    r2 = client.post(f"/api/pedestals/{pid}/load/alarms/{alarm_id}/acknowledge", headers=auth_headers)
    assert r2.status_code == 200
    body = r2.json()
    assert body["acknowledged"] is True
    assert body["resolved_at"] is None
    assert body["acknowledged_by"] == "admin@test.local"


def test_resolve_closes_alarm_with_admin_email(client, auth_headers):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    _trip_to(85, pid)
    r = client.get(f"/api/pedestals/{pid}/load/alarms", headers=auth_headers)
    alarm_id = r.json()["alarms"][0]["id"]
    r2 = client.post(f"/api/pedestals/{pid}/load/alarms/{alarm_id}/resolve", headers=auth_headers)
    assert r2.status_code == 200
    body = r2.json()
    assert body["resolved_at"] is not None
    assert body["resolved_by"] == "admin@test.local"


# ── TC-ML-25/26/29 — ERP endpoints ───────────────────────────────────────────

def test_erp_socket_load_returns_state(client):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    _enable_ext_endpoints(["load.socket_get_ext"])
    r = client.get(
        f"/api/ext/pedestals/{pid}/sockets/1/load",
        headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
    )
    assert r.status_code == 200
    assert r.json()["socket_id"] == 1
    assert r.json()["meter_type"] == "ABB"


def test_erp_marina_alarms_returns_active_alarms(client):
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    _trip_to(85, pid)
    _enable_ext_endpoints(["load.marina_alarms_ext"])
    r = client.get(
        "/api/ext/marinas/KRK/load/alarms",
        headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
    )
    assert r.status_code == 200
    alarms = r.json()["alarms"]
    assert any(a["pedestal_id"] == pid and a["alarm_type"] == "critical" for a in alarms)


def test_erp_endpoint_401_on_missing_auth(client):
    pid = _ensure_cabinet()
    _enable_ext_endpoints(["load.pedestal_get_ext"])
    r = client.get(f"/api/ext/pedestals/{pid}/load")
    assert r.status_code == 401


# ── TC-ML-27/28 — catalog drift ──────────────────────────────────────────────

def test_api_catalog_has_load_entries():
    from app.services.api_catalog import ENDPOINT_CATALOG, EVENT_CATALOG
    ep_ids = {e["id"] for e in ENDPOINT_CATALOG}
    expected_eps = {
        "load.pedestal_get_ext",
        "load.socket_get_ext",
        "load.marina_alarms_ext",
        "load.pedestal_alarms_ext",
        "load.socket_history_ext",
    }
    assert expected_eps.issubset(ep_ids)
    for e in ENDPOINT_CATALOG:
        if e["id"].startswith("load."):
            assert e["category"] == "Load Monitoring"

    evt_ids = {e["id"] for e in EVENT_CATALOG}
    assert {"hardware_config_updated", "meter_load_warning",
            "meter_load_critical", "meter_load_resolved"}.issubset(evt_ids)
