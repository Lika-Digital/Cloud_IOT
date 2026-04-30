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

v3.12 — 90% Auto-Stop Overload Protection (additive)
  TC-ML-31  Auto-stop fires when load_pct >= 90 (boundary)
  TC-ML-32  Auto-stop does NOT fire when load_pct = 89.9 (boundary)
  TC-ML-33  Auto-stop publishes opta/cmd/socket/Q{n} with action="stop" and msgId="autostop-{ts}"
  TC-ML-34  Auto-stop ends active electricity session with end_reason="auto_stop_overload"
  TC-ML-35  Auto-stop inserts meter_load_alarms row with alarm_type="auto_stop"
  TC-ML-36  Auto-stop sets SocketConfig.auto_stop_pending_ack=True
  TC-ML-37  Auto-stop broadcasts meter_load_auto_stop with severity=AUTO_STOP + session_id
  TC-ML-38  Auto-stop skipped when rated_amps is None (relies on TC-ML-05 fall-through)
  TC-ML-39  Auto-stop does NOT fire a second time when prev_status=="auto_stop" (terminal)
  TC-ML-40  Load drops below 90% after auto-stop does NOT change status away from auto_stop
  TC-ML-41  approve_socket returns 409 when auto_stop_pending_ack=True
  TC-ML-42  approve_socket works normally when auto_stop_pending_ack=False
  TC-ML-43  direct_socket_cmd activate returns 409 when auto_stop_pending_ack=True
  TC-ML-44  direct_socket_cmd stop works regardless of auto_stop_pending_ack
  TC-ML-45  _auto_activate_precondition_check returns "overload alarm pending acknowledgment" (D8)
  TC-ML-46  Acknowledge endpoint clears auto_stop_pending_ack
  TC-ML-47  Acknowledge endpoint marks latest auto_stop alarm row with admin email
  TC-ML-48  Acknowledge endpoint broadcasts meter_load_auto_stop_acknowledged
  TC-ML-49  Acknowledge endpoint returns 409 when no auto-stop is pending
  TC-ML-50  After acknowledge, the same socket can be re-activated normally
  TC-ML-51  ERP acknowledge endpoint records acknowledged_by="erp-service" (D7)
  TC-ML-52  ERP acknowledge endpoint requires _EP_AUTO_STOP_ACK to be enabled
  TC-ML-53  ERP acknowledge endpoint 401 on missing/invalid auth
  TC-ML-54  api_catalog has load.auto_stop_ack_ext entry under Load Monitoring
  TC-ML-55  api_catalog has both meter_load_auto_stop* events under Load Monitoring
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
    """Each test starts with no open alarms, no leftover sessions, and a
    cleared auto-stop latch on the test cabinet — required so v3.12 tests
    don't leak state into earlier v3.11 tests run later in the suite."""
    from app.models.meter_load_alarm import MeterLoadAlarm
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    from app.models.session import Session as _Session
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(opta_client_id=CABINET).first()
        if cfg is not None:
            db.query(MeterLoadAlarm).filter_by(pedestal_id=cfg.pedestal_id).delete(synchronize_session=False)
            # Wipe any leftover sessions seeded by v3.12 auto-stop tests so
            # the next test's session lookup starts clean.
            db.query(_Session).filter_by(pedestal_id=cfg.pedestal_id).delete(synchronize_session=False)
            # Reset SocketConfig meter fields back to clean state.
            for sc in db.query(SocketConfig).filter_by(pedestal_id=cfg.pedestal_id).all():
                sc.meter_load_status = "unknown"
                sc.meter_load_pct = None
                sc.load_warning_threshold_pct = 60
                sc.load_critical_threshold_pct = 80
                sc.auto_stop_pending_ack = False   # v3.12 — clear latch
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


# ─── v3.12 — 90% auto-stop overload protection ───────────────────────────────

def _seed_active_session(pedestal_id: int, socket_id: int) -> int:
    """Insert a synthetic active electricity session so the auto-stop branch
    has something to complete. Returns the session id."""
    from app.models.session import Session as _Session
    db = _TestSession()
    try:
        s = _Session(
            pedestal_id=pedestal_id,
            socket_id=socket_id,
            type="electricity",
            status="active",
            started_at=datetime.utcnow(),
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return s.id
    finally:
        db.close()


def _capture_mqtt_publishes() -> tuple[list[tuple[str, str]], object]:
    """Return (captured_list, patch_context). Caller uses `with patch_context: ...`."""
    captured: list[tuple[str, str]] = []

    def fake_publish(topic, payload):
        captured.append((topic, payload))

    from unittest.mock import MagicMock
    fake_service = MagicMock()
    fake_service.publish = fake_publish
    return captured, patch("app.services.mqtt_client.mqtt_service", fake_service)


def test_autostop_fires_at_or_above_90_pct():
    """TC-ML-31 — load_pct >= 90% triggers auto-stop sequence."""
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)

    captured, mqtt_patch = _capture_mqtt_publishes()
    with mqtt_patch:
        # 32A * 0.91 = 29.12A → 91.0% (above 90)
        broadcasts = _trip_to(91, pid)

    assert any(b.get("event") == "meter_load_auto_stop" for b in broadcasts)
    cfg = _get_socket_cfg(pid, 1)
    assert cfg.meter_load_status == "auto_stop"


def test_autostop_does_not_fire_at_89_9_pct():
    """TC-ML-32 — load_pct = 89.9% must NOT trigger (must be exactly the
    spec's `>= 90` line). Use 32A * 0.899 = 28.768A directly."""
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)

    captured, mqtt_patch = _capture_mqtt_publishes()
    with mqtt_patch:
        broadcasts = _simulate("opta/meters/Q1/telemetry", {
            "cabinetId": CABINET, "socketId": "Q1",
            "currentAmps": 32.0 * 0.899,  # 89.9% — below the threshold
            "voltageV": 230, "powerKw": 6.6,
        })

    assert not any(b.get("event") == "meter_load_auto_stop" for b in broadcasts)
    cfg = _get_socket_cfg(pid, 1)
    # Should be critical (89.9 > 80%) but NOT auto_stop.
    assert cfg.meter_load_status == "critical"
    assert bool(cfg.auto_stop_pending_ack) is False
    # No autostop-* MQTT publish.
    assert not any("autostop-" in p for _, p in captured)


def test_autostop_publishes_correct_mqtt_payload():
    """TC-ML-33 — publish on opta/cmd/socket/Q{n} with action=stop + autostop-{ts} msgId."""
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)

    captured, mqtt_patch = _capture_mqtt_publishes()
    with mqtt_patch:
        _trip_to(95, pid)

    autostop_pubs = [(t, p) for t, p in captured if t == "opta/cmd/socket/Q1"]
    assert len(autostop_pubs) == 1
    payload = json.loads(autostop_pubs[0][1])
    assert payload["action"] == "stop"
    assert payload["cabinetId"] == CABINET
    assert payload["msgId"].startswith("autostop-")


def test_autostop_completes_active_session_with_end_reason():
    """TC-ML-34 — active electricity session is completed with end_reason='auto_stop_overload'."""
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    sid = _seed_active_session(pid, 1)

    captured, mqtt_patch = _capture_mqtt_publishes()
    with mqtt_patch:
        _trip_to(95, pid)

    from app.models.session import Session as _Session
    db = _TestSession()
    try:
        s = db.get(_Session, sid)
        assert s.status == "completed"
        assert s.end_reason == "auto_stop_overload"
    finally:
        db.close()


def test_autostop_creates_alarm_row_with_alarm_type_auto_stop():
    """TC-ML-35 — meter_load_alarms row inserted with alarm_type='auto_stop'."""
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)

    captured, mqtt_patch = _capture_mqtt_publishes()
    with mqtt_patch:
        _trip_to(95, pid)

    from app.models.meter_load_alarm import MeterLoadAlarm
    db = _TestSession()
    try:
        rows = db.query(MeterLoadAlarm).filter_by(
            pedestal_id=pid, socket_id=1, alarm_type="auto_stop", resolved_at=None,
        ).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.acknowledged is False
        assert row.load_pct == pytest.approx(95.0, rel=1e-2)
        assert row.rated_amps == pytest.approx(32.0)
    finally:
        db.close()


def test_autostop_sets_pending_ack_latch():
    """TC-ML-36 — SocketConfig.auto_stop_pending_ack flips True."""
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)

    captured, mqtt_patch = _capture_mqtt_publishes()
    with mqtt_patch:
        _trip_to(95, pid)

    cfg = _get_socket_cfg(pid, 1)
    assert bool(cfg.auto_stop_pending_ack) is True


def test_autostop_broadcast_payload_has_severity_and_session_id():
    """TC-ML-37 — meter_load_auto_stop event carries severity=AUTO_STOP and the ended session_id."""
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)
    sid = _seed_active_session(pid, 1)

    captured, mqtt_patch = _capture_mqtt_publishes()
    with mqtt_patch:
        broadcasts = _trip_to(95, pid)

    auto_stops = [b for b in broadcasts if b.get("event") == "meter_load_auto_stop"]
    assert len(auto_stops) == 1
    d = auto_stops[0]["data"]
    assert d["pedestal_id"] == pid
    assert d["socket_id"] == 1
    assert d["severity"] == "AUTO_STOP"
    assert d["session_id"] == sid
    assert d["load_pct"] == pytest.approx(95.0, rel=1e-2)


def test_autostop_terminal_does_not_fire_again():
    """TC-ML-39 — when prev_status='auto_stop', subsequent ticks at >= 90%
    do NOT publish another stop, do NOT add another alarm row, do NOT
    broadcast another auto_stop event."""
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)

    captured, mqtt_patch = _capture_mqtt_publishes()
    with mqtt_patch:
        _trip_to(95, pid)               # initial trip
        # Second tick still at 95% — terminal state, no new effects.
        broadcasts = _trip_to(95, pid)

    assert not any(b.get("event") == "meter_load_auto_stop" for b in broadcasts)
    autostop_pubs = [(t, p) for t, p in captured if "autostop-" in p]
    assert len(autostop_pubs) == 1   # only the first trip published

    from app.models.meter_load_alarm import MeterLoadAlarm
    db = _TestSession()
    try:
        rows = db.query(MeterLoadAlarm).filter_by(
            pedestal_id=pid, socket_id=1, alarm_type="auto_stop", resolved_at=None,
        ).all()
        assert len(rows) == 1     # still just the original row
    finally:
        db.close()


def test_autostop_terminal_persists_when_load_drops_below_90():
    """TC-ML-40 — D1: auto_stop is terminal. After the trip, even if load
    drops to 0%, status stays auto_stop until the operator's ack endpoint
    clears the latch."""
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)

    captured, mqtt_patch = _capture_mqtt_publishes()
    with mqtt_patch:
        _trip_to(95, pid)   # auto-stop
        _trip_to(40, pid)   # load drops back into normal range

    cfg = _get_socket_cfg(pid, 1)
    assert cfg.meter_load_status == "auto_stop"
    assert bool(cfg.auto_stop_pending_ack) is True


def _seed_socket_state(pedestal_id: int, socket_id: int, **fields) -> None:
    """Insert/update a SocketState row so the controls.py guards have a row to read."""
    from app.models.pedestal_config import SocketState
    db = _TestSession()
    try:
        st = db.query(SocketState).filter_by(pedestal_id=pedestal_id, socket_id=socket_id).first()
        if st is None:
            st = SocketState(pedestal_id=pedestal_id, socket_id=socket_id)
            db.add(st)
        for k, v in fields.items():
            setattr(st, k, v)
        db.commit()
    finally:
        db.close()


def _set_auto_stop_latch(pedestal_id: int, socket_id: int, value: bool) -> None:
    from app.models.socket_config import SocketConfig
    db = _TestSession()
    try:
        sc = db.query(SocketConfig).filter_by(pedestal_id=pedestal_id, socket_id=socket_id).first()
        if sc is None:
            sc = SocketConfig(pedestal_id=pedestal_id, socket_id=socket_id, auto_activate=False)
            db.add(sc)
        sc.auto_stop_pending_ack = value
        db.commit()
    finally:
        db.close()


def test_approve_socket_returns_409_when_auto_stop_pending_ack(client, auth_headers):
    """TC-ML-41 — admin approve endpoint blocked while latch is set."""
    pid = _ensure_cabinet()
    _seed_socket_state(pid, 1, operator_status="pending", connected=True)
    _set_auto_stop_latch(pid, 1, True)

    r = client.post(f"/api/controls/sockets/{pid}/1/approve", headers=auth_headers)
    assert r.status_code == 409
    assert "automatically stopped" in r.json()["detail"].lower()
    assert "acknowledge" in r.json()["detail"].lower()


def test_approve_socket_works_when_latch_cleared(client, auth_headers):
    """TC-ML-42 — once the latch is cleared the normal approve path resumes."""
    pid = _ensure_cabinet()
    _seed_socket_state(pid, 1, operator_status="pending", connected=True)
    _set_auto_stop_latch(pid, 1, False)

    with patch("app.routers.controls.mqtt_service.publish"):
        r = client.post(f"/api/controls/sockets/{pid}/1/approve", headers=auth_headers)

    # 200 (session created+activated) is the success path.
    assert r.status_code == 200, r.text


def test_direct_socket_cmd_activate_returns_409_when_latch_set(client, auth_headers):
    """TC-ML-43 — direct admin activate also guarded."""
    pid = _ensure_cabinet()
    _seed_socket_state(pid, 1, connected=True)
    _set_auto_stop_latch(pid, 1, True)

    with patch("app.routers.controls.mqtt_service.publish"):
        r = client.post(
            f"/api/controls/pedestal/{pid}/socket/Q1/cmd",
            json={"action": "activate"},
            headers=auth_headers,
        )
    assert r.status_code == 409
    assert "automatically stopped" in r.json()["detail"].lower()


def test_direct_socket_cmd_stop_works_when_latch_set(client, auth_headers):
    """TC-ML-44 — stop is intentionally NOT guarded; operator can always stop."""
    pid = _ensure_cabinet()
    _seed_socket_state(pid, 1, connected=True)
    _set_auto_stop_latch(pid, 1, True)

    with patch("app.routers.controls.mqtt_service.publish"):
        r = client.post(
            f"/api/controls/pedestal/{pid}/socket/Q1/cmd",
            json={"action": "stop"},
            headers=auth_headers,
        )
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "stop"


def test_auto_activate_precondition_returns_overload_reason_when_latch_set():
    """TC-ML-45 — D8: _auto_activate_precondition_check skips with the
    documented reason string when auto_stop_pending_ack is True. This
    guards the auto-activation path that fires from UserPluggedIn."""
    pid = _ensure_cabinet()
    _seed_socket_state(pid, 1, connected=True)
    _set_auto_stop_latch(pid, 1, True)

    # Make all earlier checks pass: door closed, fresh heartbeat, no faults,
    # no diagnostic, no active session. Door state lives on PedestalConfig.
    from app.models.pedestal_config import PedestalConfig
    from datetime import datetime as _dt
    db = _TestSession()
    try:
        pc = db.query(PedestalConfig).filter_by(pedestal_id=pid).first()
        if pc is not None:
            pc.door_state = "closed"
            db.commit()
    finally:
        db.close()

    # Stamp the in-memory heartbeat dict so the heartbeat check passes.
    from app.services import mqtt_handlers as _mh
    _mh.last_heartbeat[pid] = _dt.utcnow()
    # Clear any leftover diagnostic lockout / faults from earlier tests.
    _mh.last_diagnostic_lockout_at.pop(pid, None)
    for k in list(_mh.socket_fault_state.keys()):
        if k[0] == pid:
            _mh.socket_fault_state.pop(k, None)

    db = _TestSession()
    try:
        with patch("app.services.mqtt_handlers.SessionLocal", _TestSession):
            reason = _mh._auto_activate_precondition_check(db, pid, 1)
    finally:
        db.close()
    assert reason == "overload alarm pending acknowledgment"


def _trigger_auto_stop(pedestal_id: int, socket_id: int = 1) -> None:
    """Drive the socket into auto_stop state via a 95% telemetry tick.
    Used by the ack-endpoint tests so they exercise the real state."""
    _seed_hw_config(pedestal_id, socket_id, meter_type="ABB", phases=1, rated_amps=32.0)
    captured, mqtt_patch = _capture_mqtt_publishes()
    with mqtt_patch:
        _trip_to(95, pedestal_id, socket_id)


def test_acknowledge_endpoint_clears_latch(client, auth_headers):
    """TC-ML-46 — POST .../auto-stop/acknowledge sets auto_stop_pending_ack=False."""
    pid = _ensure_cabinet()
    _trigger_auto_stop(pid, 1)
    assert _get_socket_cfg(pid, 1).auto_stop_pending_ack is True

    r = client.post(
        f"/api/pedestals/{pid}/sockets/1/load/auto-stop/acknowledge",
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "acknowledged"
    assert body["socket_id"] == 1

    cfg = _get_socket_cfg(pid, 1)
    assert bool(cfg.auto_stop_pending_ack) is False
    assert cfg.meter_load_status != "auto_stop"


def test_acknowledge_endpoint_marks_alarm_with_admin_email(client, auth_headers):
    """TC-ML-47 — alarm row gets acknowledged=True with admin email."""
    pid = _ensure_cabinet()
    _trigger_auto_stop(pid, 1)

    r = client.post(
        f"/api/pedestals/{pid}/sockets/1/load/auto-stop/acknowledge",
        headers=auth_headers,
    )
    assert r.status_code == 200

    from app.models.meter_load_alarm import MeterLoadAlarm
    db = _TestSession()
    try:
        rows = db.query(MeterLoadAlarm).filter_by(
            pedestal_id=pid, socket_id=1, alarm_type="auto_stop",
        ).order_by(MeterLoadAlarm.id.desc()).all()
        assert rows[0].acknowledged is True
        assert rows[0].acknowledged_by == "admin@test.local"
        assert rows[0].acknowledged_at is not None
    finally:
        db.close()


def test_acknowledge_endpoint_broadcasts_event(client, auth_headers):
    """TC-ML-48 — meter_load_auto_stop_acknowledged broadcast emitted."""
    pid = _ensure_cabinet()
    _trigger_auto_stop(pid, 1)

    captured: list[dict] = []

    async def capture(msg):
        captured.append(msg)

    with patch("app.routers.meter_load.ws_manager.broadcast", side_effect=capture):
        r = client.post(
            f"/api/pedestals/{pid}/sockets/1/load/auto-stop/acknowledge",
            headers=auth_headers,
        )
    assert r.status_code == 200

    acks = [m for m in captured if m.get("event") == "meter_load_auto_stop_acknowledged"]
    assert len(acks) == 1
    d = acks[0]["data"]
    assert d["pedestal_id"] == pid
    assert d["socket_id"] == 1
    assert d["acknowledged_by"] == "admin@test.local"
    assert d["alarm_id"] is not None
    assert d["load_status"] != "auto_stop"


def test_acknowledge_endpoint_returns_409_when_nothing_pending(client, auth_headers):
    """TC-ML-49 — 409 when the latch isn't set."""
    pid = _ensure_cabinet()
    # Make sure there is a SocketConfig row but the latch is clear.
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)

    r = client.post(
        f"/api/pedestals/{pid}/sockets/1/load/auto-stop/acknowledge",
        headers=auth_headers,
    )
    assert r.status_code == 409


def test_socket_can_be_reactivated_after_acknowledge(client, auth_headers):
    """TC-ML-50 — after ack, the approve flow no longer returns 409."""
    pid = _ensure_cabinet()
    _trigger_auto_stop(pid, 1)
    _seed_socket_state(pid, 1, operator_status="pending", connected=True)

    # Pre-ack: approve is blocked.
    r1 = client.post(f"/api/controls/sockets/{pid}/1/approve", headers=auth_headers)
    assert r1.status_code == 409

    # Ack.
    r2 = client.post(
        f"/api/pedestals/{pid}/sockets/1/load/auto-stop/acknowledge",
        headers=auth_headers,
    )
    assert r2.status_code == 200

    # Post-ack: approve succeeds.
    with patch("app.routers.controls.mqtt_service.publish"):
        r3 = client.post(f"/api/controls/sockets/{pid}/1/approve", headers=auth_headers)
    assert r3.status_code == 200, r3.text


def test_erp_auto_stop_acknowledge_records_erp_service(client):
    """TC-ML-51 — ERP-driven ack records acknowledged_by='erp-service' (D7).
    Verifies the audit trail can distinguish ERP from operator acks."""
    pid = _ensure_cabinet()
    _trigger_auto_stop(pid, 1)
    _enable_ext_endpoints(["load.auto_stop_ack_ext"])

    r = client.post(
        f"/api/ext/pedestals/{pid}/sockets/1/load/auto-stop/acknowledge",
        headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "acknowledged"
    assert body["socket_id"] == 1

    cfg = _get_socket_cfg(pid, 1)
    assert bool(cfg.auto_stop_pending_ack) is False

    from app.models.meter_load_alarm import MeterLoadAlarm
    db = _TestSession()
    try:
        alarm = (
            db.query(MeterLoadAlarm)
            .filter_by(pedestal_id=pid, socket_id=1, alarm_type="auto_stop")
            .order_by(MeterLoadAlarm.id.desc())
            .first()
        )
        assert alarm is not None
        assert alarm.acknowledged is True
        assert alarm.acknowledged_by == "erp-service"
    finally:
        db.close()


def test_erp_auto_stop_acknowledge_503_when_endpoint_disabled(client):
    """TC-ML-52 — disabled per-endpoint toggle returns 503 like the other ERP routes."""
    pid = _ensure_cabinet()
    _trigger_auto_stop(pid, 1)
    # Enable a DIFFERENT endpoint to prove the toggle is per-endpoint.
    _enable_ext_endpoints(["load.pedestal_get_ext"])

    r = client.post(
        f"/api/ext/pedestals/{pid}/sockets/1/load/auto-stop/acknowledge",
        headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
    )
    assert r.status_code == 503


def test_erp_auto_stop_acknowledge_401_on_missing_auth(client):
    """TC-ML-53 — no Authorization header returns 401."""
    pid = _ensure_cabinet()
    _enable_ext_endpoints(["load.auto_stop_ack_ext"])
    r = client.post(f"/api/ext/pedestals/{pid}/sockets/1/load/auto-stop/acknowledge")
    assert r.status_code == 401


def test_autostop_supersedes_open_warning_critical_rows():
    """When transitioning critical → auto_stop, any open warning/critical
    rows are resolved with reason='auto-stop-supersedes' so the alarm
    history is consistent."""
    pid = _ensure_cabinet()
    _seed_hw_config(pid, 1, meter_type="ABB", phases=1, rated_amps=32.0)

    captured, mqtt_patch = _capture_mqtt_publishes()
    with mqtt_patch:
        _trip_to(85, pid)   # opens a critical row
        _trip_to(95, pid)   # auto-stop

    from app.models.meter_load_alarm import MeterLoadAlarm
    db = _TestSession()
    try:
        crit_rows = db.query(MeterLoadAlarm).filter_by(
            pedestal_id=pid, socket_id=1, alarm_type="critical",
        ).all()
        assert len(crit_rows) == 1
        assert crit_rows[0].resolved_at is not None
        assert crit_rows[0].resolved_by == "auto-stop-supersedes"

        autostop_open = db.query(MeterLoadAlarm).filter_by(
            pedestal_id=pid, socket_id=1, alarm_type="auto_stop", resolved_at=None,
        ).all()
        assert len(autostop_open) == 1
    finally:
        db.close()


# ─── v3.12 catalog drift guards ─────────────────────────────────────────────

def test_api_catalog_has_auto_stop_ack_endpoint():
    """TC-ML-54 — load.auto_stop_ack_ext registered under Load Monitoring."""
    from app.services.api_catalog import ENDPOINT_CATALOG
    matches = [e for e in ENDPOINT_CATALOG if e["id"] == "load.auto_stop_ack_ext"]
    assert len(matches) == 1
    e = matches[0]
    assert e["category"] == "Load Monitoring"
    assert e["method"] == "POST"
    assert e["path"].endswith("/auto-stop/acknowledge")


def test_api_catalog_has_auto_stop_events():
    """TC-ML-55 — both auto-stop events registered under Load Monitoring."""
    from app.services.api_catalog import EVENT_CATALOG
    ids = {e["id"] for e in EVENT_CATALOG}
    assert "meter_load_auto_stop" in ids
    assert "meter_load_auto_stop_acknowledged" in ids
    for e in EVENT_CATALOG:
        if e["id"].startswith("meter_load_auto_stop"):
            assert e["category"] == "Load Monitoring"
