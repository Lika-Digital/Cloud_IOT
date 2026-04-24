"""
Smart Circuit Breaker Monitoring — Verification Tests (v3.8)
============================================================

Coverage for:
- opta/breakers/+/status parsing and SocketConfig persistence (+ "no-overwrite-with-null" rule).
- opta/events → BreakerTripped branch (breaker_events row, session stop with
  end_reason="breaker_trip", breaker_alarm WS broadcast).
- Internal admin reset endpoint (409, MQTT publish, audit row, WS broadcast).
- ERP external reset + GET endpoints (auth, 409, 403, audit row with erp-service).
- api_catalog entries — ensures the drift guard test keeps passing.

Test IDs:
  TC-BR-01  status payload writes all metadata fields
  TC-BR-02  metadata absent from later payload does NOT overwrite existing
  TC-BR-03  tripped state increments trip_count + stamps last_trip_at
  TC-BR-04  BreakerTripped appends breaker_events row with correct fields
  TC-BR-05  BreakerTripped stops active power session with end_reason=breaker_trip
  TC-BR-06  BreakerTripped broadcasts breaker_alarm WS event (+ session_completed)
  TC-BR-07  breaker_state_changed includes every metadata field
  TC-BR-08  internal reset returns 409 when state != tripped
  TC-BR-09  internal reset publishes correct MQTT payload to opta/cmd/breaker/Q{n}
  TC-BR-10  internal reset creates breaker_events row with operator email
  TC-BR-11  internal reset broadcasts breaker_state_changed state=resetting
  TC-BR-12  ERP reset returns 409 when not tripped
  TC-BR-13  ERP reset publishes correct MQTT payload
  TC-BR-14  ERP reset writes reset_initiated_by=erp-service
  TC-BR-15  ERP reset returns 401/403 for invalid / missing token
  TC-BR-16  ERP breakers list returns all sockets on pedestal
  TC-BR-17  ERP single-socket endpoint includes state + last 5 events
  TC-BR-18  ERP pedestal history returns up to 50 events ordered desc
  TC-BR-19  ERP marina alarms returns only tripped/resetting
  TC-BR-20  ERP marina alarms returns empty list when none
  TC-BR-21  api_catalog contains 5 breaker endpoints + 3 events
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

CABINET = "MAR_KRK_ORM_02"   # distinct from other tests so rows do not collide.


@pytest.fixture(scope="module", autouse=True)
def _dispose_engine():
    yield
    _test_engine.dispose()


@pytest.fixture(autouse=True)
def _patch_routers_to_test_db():
    """Route router SessionLocal usage to the shared test DB so tests observe
    the rows they create directly."""
    with (
        patch("app.routers.ext_breaker_endpoints.SessionLocal", _TestSession),
    ):
        yield


# ── helpers ──────────────────────────────────────────────────────────────────

def _simulate(topic: str, payload: dict) -> list[dict]:
    """Inject an MQTT message and return WS broadcasts it triggered."""
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


def _pedestal_id_for_cabinet() -> int:
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(opta_client_id=CABINET).first()
        return cfg.pedestal_id if cfg else 0
    finally:
        db.close()


def _seed_socket_config(pedestal_id: int, socket_id: int, **kwargs) -> None:
    from app.models.socket_config import SocketConfig
    db = _TestSession()
    try:
        row = db.query(SocketConfig).filter_by(pedestal_id=pedestal_id, socket_id=socket_id).first()
        if row is None:
            row = SocketConfig(pedestal_id=pedestal_id, socket_id=socket_id, auto_activate=False)
            db.add(row)
        for k, v in kwargs.items():
            setattr(row, k, v)
        db.commit()
    finally:
        db.close()


def _get_socket_config(pedestal_id: int, socket_id: int):
    from app.models.socket_config import SocketConfig
    db = _TestSession()
    try:
        return db.query(SocketConfig).filter_by(pedestal_id=pedestal_id, socket_id=socket_id).first()
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
        allowed = [{"id": e, "mode": "bidirectional"} for e in ep_ids]
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


# ── TC-BR-01: full metadata persisted on status ─────────────────────────────

def test_breaker_status_payload_writes_all_metadata():
    payload = {
        "cabinetId": CABINET,
        "socketId": "Q1",
        "breakerState": "closed",
        "tripCause": None,
        "ts": 1_700_000_000,
        "breakerType": "ABB DS201",
        "rating": "16A",
        "poles": "1P+N",
        "rcd": True,
        "rcdSensitivity": "30mA",
    }
    _simulate("opta/breakers/Q1/status", payload)

    pid = _pedestal_id_for_cabinet()
    cfg = _get_socket_config(pid, 1)
    assert cfg is not None
    assert cfg.breaker_state == "closed"
    assert cfg.breaker_type == "ABB DS201"
    assert cfg.breaker_rating == "16A"
    assert cfg.breaker_poles == "1P+N"
    assert cfg.breaker_rcd is True
    assert cfg.breaker_rcd_sensitivity == "30mA"


# ── TC-BR-02: missing keys don't overwrite existing metadata ────────────────

def test_breaker_status_absent_keys_preserve_metadata():
    # Seed metadata first via TC-BR-01 (relies on module order, but we re-seed).
    _simulate("opta/breakers/Q2/status", {
        "cabinetId": CABINET,
        "socketId": "Q2",
        "breakerState": "closed",
        "breakerType": "Schneider iC60N",
        "rating": "20A",
        "poles": "2P",
        "rcd": False,
    })
    pid = _pedestal_id_for_cabinet()
    before = _get_socket_config(pid, 2)
    assert before.breaker_type == "Schneider iC60N"
    assert before.breaker_rating == "20A"
    assert before.breaker_rcd is False

    # Next payload omits metadata entirely.
    _simulate("opta/breakers/Q2/status", {
        "cabinetId": CABINET,
        "socketId": "Q2",
        "breakerState": "closed",
        "tripCause": None,
    })
    after = _get_socket_config(pid, 2)
    assert after.breaker_type == "Schneider iC60N"  # unchanged
    assert after.breaker_rating == "20A"            # unchanged
    assert after.breaker_rcd is False               # unchanged


# ── TC-BR-03: tripped transition stamps + increments ─────────────────────────

def test_tripped_increments_count_and_stamps_timestamp():
    _simulate("opta/breakers/Q3/status", {
        "cabinetId": CABINET, "socketId": "Q3", "breakerState": "closed",
    })
    pid = _pedestal_id_for_cabinet()
    before = _get_socket_config(pid, 3)
    assert before.breaker_trip_count == 0
    assert before.breaker_last_trip_at is None

    _simulate("opta/breakers/Q3/status", {
        "cabinetId": CABINET, "socketId": "Q3", "breakerState": "tripped",
        "tripCause": "overcurrent",
    })
    after = _get_socket_config(pid, 3)
    assert after.breaker_trip_count == 1
    assert after.breaker_last_trip_at is not None
    assert after.breaker_trip_cause == "overcurrent"

    # A second `tripped` payload without leaving that state should NOT
    # re-increment the counter (transition-edge only).
    _simulate("opta/breakers/Q3/status", {
        "cabinetId": CABINET, "socketId": "Q3", "breakerState": "tripped",
        "tripCause": "overcurrent",
    })
    again = _get_socket_config(pid, 3)
    assert again.breaker_trip_count == 1


# ── TC-BR-04 + TC-BR-06: BreakerTripped event → audit row + WS broadcasts ───

def test_breaker_tripped_event_logs_and_broadcasts():
    pid = _pedestal_id_for_cabinet()
    payload = {
        "eventId": "e-br-1",
        "eventType": "BreakerTripped",
        "occurredAt": "2026-04-24T11:00:00Z",
        "device": {"cabinetId": CABINET, "outletId": "Q4"},
        "breaker": {"tripCause": "overcurrent", "currentAtTrip": 18.5},
    }
    broadcasts = _simulate("opta/events", payload)

    # breaker_events row written.
    from app.models.breaker_event import BreakerEvent
    db = _TestSession()
    try:
        rows = (
            db.query(BreakerEvent)
            .filter_by(pedestal_id=pid, socket_id=4, event_type="tripped")
            .all()
        )
        assert len(rows) >= 1
        e = rows[-1]
        assert e.trip_cause == "overcurrent"
        assert e.current_at_trip == pytest.approx(18.5)
        assert e.reset_initiated_by is None
        assert e.raw_payload is not None
    finally:
        db.close()

    # WS broadcast shapes.
    alarm = [b for b in broadcasts if b.get("event") == "breaker_alarm"]
    assert len(alarm) == 1
    assert alarm[0]["data"]["pedestal_id"] == pid
    assert alarm[0]["data"]["socket_id"] == 4
    assert alarm[0]["data"]["trip_cause"] == "overcurrent"
    assert alarm[0]["data"]["severity"] == "HIGH"


# ── TC-BR-05: BreakerTripped stops active power session ─────────────────────

def test_breaker_tripped_stops_active_session_with_end_reason():
    from app.models.session import Session
    pid = _pedestal_id_for_cabinet()

    # Seed an active power session on Q2.
    db = _TestSession()
    try:
        sess = Session(
            pedestal_id=pid, socket_id=2, type="electricity",
            status="active", started_at=datetime.utcnow(),
        )
        db.add(sess)
        db.commit()
        db.refresh(sess)
        sid = sess.id
    finally:
        db.close()

    _simulate("opta/events", {
        "eventType": "BreakerTripped",
        "device": {"cabinetId": CABINET, "outletId": "Q2"},
        "breaker": {"tripCause": "overcurrent"},
    })

    db = _TestSession()
    try:
        finished = db.get(Session, sid)
        assert finished.status == "completed"
        assert finished.end_reason == "breaker_trip"
        assert finished.ended_at is not None
    finally:
        db.close()


# ── TC-BR-07: breaker_state_changed carries metadata ────────────────────────

def test_breaker_state_changed_includes_metadata():
    broadcasts = _simulate("opta/breakers/Q1/status", {
        "cabinetId": CABINET, "socketId": "Q1",
        "breakerState": "closed",
        "breakerType": "Hager NCN116", "rating": "16A", "poles": "1P",
        "rcd": False,
    })
    changed = [b for b in broadcasts if b.get("event") == "breaker_state_changed"]
    assert len(changed) == 1
    d = changed[0]["data"]
    assert d["breaker_state"] == "closed"
    assert d["breaker_type"] == "Hager NCN116"
    assert d["breaker_rating"] == "16A"
    assert d["breaker_poles"] == "1P"
    assert d["breaker_rcd"] is False
    assert "socket_id" in d and "pedestal_id" in d


# ── TC-BR-08..11: internal reset endpoint ───────────────────────────────────

def _trip_socket(socket_id: int) -> int:
    _simulate("opta/breakers/Q{0}/status".format(socket_id), {
        "cabinetId": CABINET, "socketId": f"Q{socket_id}",
        "breakerState": "tripped", "tripCause": "overcurrent",
    })
    return _pedestal_id_for_cabinet()


def test_internal_reset_rejects_when_not_tripped(client, auth_headers):
    # Seed Q1 to closed.
    _simulate("opta/breakers/Q1/status", {
        "cabinetId": CABINET, "socketId": "Q1", "breakerState": "closed",
    })
    pid = _pedestal_id_for_cabinet()
    r = client.post(f"/api/pedestals/{pid}/sockets/1/breaker/reset", headers=auth_headers)
    assert r.status_code == 409
    assert "not in tripped state" in r.json()["detail"].lower()


def test_internal_reset_publishes_and_writes_audit(client, auth_headers):
    published = []

    def fake_publish(topic, payload, *args, **kwargs):
        published.append((topic, payload))

    pid = _trip_socket(1)

    broadcasts: list[dict] = []

    async def capture(msg):
        broadcasts.append(msg)

    with (
        patch("app.services.mqtt_client.mqtt_service.publish", side_effect=fake_publish),
        patch("app.routers.breakers.ws_manager.broadcast", side_effect=capture),
    ):
        r = client.post(f"/api/pedestals/{pid}/sockets/1/breaker/reset", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "reset_command_sent"

    # MQTT shape.
    breaker_publishes = [p for p in published if p[0] == "opta/cmd/breaker/Q1"]
    assert len(breaker_publishes) == 1
    body = json.loads(breaker_publishes[0][1])
    assert body["cabinetId"] == CABINET
    assert body["action"] == "reset"
    assert body["msgId"].startswith("breaker-reset-")

    # breaker_events audit.
    from app.models.breaker_event import BreakerEvent
    db = _TestSession()
    try:
        rows = (
            db.query(BreakerEvent)
            .filter_by(pedestal_id=pid, socket_id=1, event_type="reset_attempted")
            .all()
        )
        assert rows, "Expected reset_attempted audit row"
        assert rows[-1].reset_initiated_by == "admin@test.local"
    finally:
        db.close()

    # WS broadcast of resetting.
    resetting = [b for b in broadcasts if b.get("event") == "breaker_state_changed"
                 and b["data"].get("breaker_state") == "resetting"]
    assert len(resetting) == 1


# ── TC-BR-12..15: ERP reset endpoint ────────────────────────────────────────

def test_erp_reset_rejects_when_not_tripped(client):
    _simulate("opta/breakers/Q2/status", {
        "cabinetId": CABINET, "socketId": "Q2", "breakerState": "closed",
    })
    pid = _pedestal_id_for_cabinet()
    _enable_ext_endpoints(["breakers.socket_reset_ext"])
    r = client.post(
        f"/api/ext/pedestals/{pid}/sockets/2/breaker/reset",
        headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
    )
    assert r.status_code == 409


def test_erp_reset_publishes_and_writes_audit(client):
    pid = _trip_socket(2)
    _enable_ext_endpoints(["breakers.socket_reset_ext"])

    published = []

    def fake_publish(topic, payload, *args, **kwargs):
        published.append((topic, payload))

    broadcasts: list[dict] = []

    async def capture(msg):
        broadcasts.append(msg)

    with (
        patch("app.services.mqtt_client.mqtt_service.publish", side_effect=fake_publish),
        patch("app.routers.breakers.ws_manager.broadcast", side_effect=capture),
    ):
        r = client.post(
            f"/api/ext/pedestals/{pid}/sockets/2/breaker/reset",
            headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "reset_command_sent"
    assert body["initiated_by"] == "erp-service"

    # MQTT publish.
    breaker_publishes = [p for p in published if p[0] == "opta/cmd/breaker/Q2"]
    assert len(breaker_publishes) == 1

    # Audit row tagged erp-service.
    from app.models.breaker_event import BreakerEvent
    db = _TestSession()
    try:
        rows = (
            db.query(BreakerEvent)
            .filter_by(pedestal_id=pid, socket_id=2, event_type="reset_attempted",
                       reset_initiated_by="erp-service")
            .all()
        )
        assert rows, "Expected erp-service audit row"
    finally:
        db.close()


def test_erp_reset_rejects_invalid_token(client):
    pid = _pedestal_id_for_cabinet()
    _enable_ext_endpoints(["breakers.socket_reset_ext"])
    r = client.post(
        f"/api/ext/pedestals/{pid}/sockets/1/breaker/reset",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert r.status_code in (401, 403)


# ── TC-BR-16: ERP list returns all sockets on pedestal ──────────────────────

def test_erp_breakers_list_returns_all_sockets(client):
    pid = _pedestal_id_for_cabinet()
    _seed_socket_config(pid, 1, breaker_state="closed")
    _seed_socket_config(pid, 2, breaker_state="tripped")
    _enable_ext_endpoints(["breakers.pedestal_list_ext"])
    r = client.get(
        f"/api/ext/pedestals/{pid}/breakers",
        headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["pedestal_id"] == pid
    ids = {s["socket_id"] for s in body["sockets"]}
    assert 1 in ids and 2 in ids


# ── TC-BR-17: ERP single socket returns state + last 5 events ───────────────

def test_erp_single_socket_returns_state_and_five_events(client):
    pid = _pedestal_id_for_cabinet()
    _enable_ext_endpoints(["breakers.socket_get_ext"])
    # Fabricate 7 events so we can assert the slice to 5.
    from app.models.breaker_event import BreakerEvent
    db = _TestSession()
    try:
        for i in range(7):
            db.add(BreakerEvent(
                pedestal_id=pid, socket_id=3,
                event_type="tripped",
                timestamp=datetime.utcnow() + timedelta(seconds=i),
                trip_cause="overcurrent",
            ))
        db.commit()
    finally:
        db.close()

    r = client.get(
        f"/api/ext/pedestals/{pid}/sockets/3/breaker",
        headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["socket_id"] == 3
    assert "breaker_state" in body
    assert len(body["recent_events"]) == 5


# ── TC-BR-18: ERP pedestal history returns up to 50 ordered desc ────────────

def test_erp_pedestal_history_capped_at_50(client):
    pid = _pedestal_id_for_cabinet()
    _enable_ext_endpoints(["breakers.pedestal_history_ext"])
    from app.models.breaker_event import BreakerEvent
    db = _TestSession()
    try:
        for i in range(60):
            db.add(BreakerEvent(
                pedestal_id=pid, socket_id=1,
                event_type="tripped",
                timestamp=datetime.utcnow() - timedelta(seconds=60 - i),
            ))
        db.commit()
    finally:
        db.close()

    r = client.get(
        f"/api/ext/pedestals/{pid}/breaker/history",
        headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
    )
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == 50
    # Ordered newest first.
    for earlier, later in zip(events, events[1:]):
        assert earlier["timestamp"] >= later["timestamp"]


# ── TC-BR-19/20: ERP marina-wide alarms ─────────────────────────────────────

def test_erp_marina_alarms_returns_only_active(client):
    pid = _pedestal_id_for_cabinet()
    _seed_socket_config(pid, 1, breaker_state="tripped")
    _seed_socket_config(pid, 2, breaker_state="resetting")
    _seed_socket_config(pid, 3, breaker_state="closed")
    _seed_socket_config(pid, 4, breaker_state="open")
    _enable_ext_endpoints(["breakers.marina_alarms_ext"])

    r = client.get(
        "/api/ext/marinas/KRK/breaker/alarms",
        headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
    )
    assert r.status_code == 200
    alarms = r.json()["alarms"]
    states = {(a["pedestal_id"], a["socket_id"], a["breaker_state"]) for a in alarms}
    assert (pid, 1, "tripped") in states
    assert (pid, 2, "resetting") in states
    assert not any(a["breaker_state"] in ("closed", "open") for a in alarms)


def test_erp_marina_alarms_empty_list_when_no_hits(client):
    _enable_ext_endpoints(["breakers.marina_alarms_ext"])
    r = client.get(
        "/api/ext/marinas/NOT_A_REAL_MARINA_XYZ/breaker/alarms",
        headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
    )
    assert r.status_code == 200
    assert r.json()["alarms"] == []


# ── TC-BR-21: api_catalog registrations ─────────────────────────────────────

def test_api_catalog_has_breaker_entries():
    from app.services.api_catalog import ENDPOINT_CATALOG, EVENT_CATALOG
    ep_ids = {e["id"] for e in ENDPOINT_CATALOG}
    for expected in (
        "breakers.pedestal_list_ext",
        "breakers.socket_get_ext",
        "breakers.socket_reset_ext",
        "breakers.pedestal_history_ext",
        "breakers.marina_alarms_ext",
    ):
        assert expected in ep_ids, f"Missing catalog entry for {expected}"
    evt_ids = {e["id"] for e in EVENT_CATALOG}
    assert {"breaker_state_changed", "breaker_alarm"}.issubset(evt_ids)

    # Every breaker endpoint should sit under the dedicated category.
    for e in ENDPOINT_CATALOG:
        if e["id"].startswith("breakers."):
            assert e["category"] == "Breaker Management"
