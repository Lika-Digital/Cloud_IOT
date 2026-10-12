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


from _test_paths import TEST_DB  # per-run path, never a literal — see _test_paths.py
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


def _set_smart_mode(pedestal_id: int, on: bool) -> None:
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(pedestal_id=pedestal_id).first()
        if cfg is not None:
            cfg.smart_mode = on
            db.commit()
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

def test_breaker_tripped_leaves_session_running():
    """v3.30 — a breaker trip is alarm/audit-only: the NUC no longer completes
    the active session. The trip has physically cut the socket; fault precedence
    shows it faulted on the UI, but the session row is left untouched."""
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
        unchanged = db.get(Session, sid)
        assert unchanged.status == "active"
        assert unchanged.end_reason is None
        assert unchanged.ended_at is None
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
    """The STATE precondition, kept testing state.

    v3.49 added a capability precondition that is checked FIRST, so without a motorised
    capability this test would still see 409 — for the wrong reason — and silently stop
    covering the state check it was written for. The seed below keeps it honest.
    """
    # Seed Q1 to closed.
    _simulate("opta/breakers/Q1/status", {
        "cabinetId": CABINET, "socketId": "Q1", "breakerState": "closed",
    })
    pid = _pedestal_id_for_cabinet()
    _seed_socket_config(pid, 1, breaker_remote_reset="motorised")
    r = client.post(f"/api/pedestals/{pid}/sockets/1/breaker/reset", headers=auth_headers)
    assert r.status_code == 409
    assert "not in tripped state" in r.json()["detail"].lower(), (
        f"expected the STATE refusal, got: {r.json()['detail']}"
    )


def test_internal_reset_publishes_and_writes_audit(client, auth_headers):
    published = []

    def fake_publish(topic, payload, *args, **kwargs):
        published.append((topic, payload))

    pid = _trip_socket(1)
    _seed_socket_config(pid, 1, breaker_remote_reset="motorised")

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
    _seed_socket_config(pid, 2, breaker_remote_reset="motorised")
    _enable_ext_endpoints(["breakers.socket_reset_ext"])
    _set_smart_mode(pid, True)   # breaker reset is a control action — requires Smart Mode ON

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


def test_erp_reset_blocked_when_smart_mode_off(client):
    """Smart Mode OFF => the API is view-only, so ERP breaker reset is refused."""
    pid = _trip_socket(2)
    _enable_ext_endpoints(["breakers.socket_reset_ext"])
    _set_smart_mode(pid, False)
    r = client.post(
        f"/api/ext/pedestals/{pid}/sockets/2/breaker/reset",
        headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
    )
    assert r.status_code == 409
    assert "Smart Mode" in r.json()["detail"]


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


# ── TC-BR-22/23: REAL Opta firmware contract (v3.13) ─────────────────────────
# Live firmware (cabinet MAR_KRK_ORM_01) publishes opta/breakers/Q*/status as:
#   {"cabinetId","outletId","state","type","rating","poles":int,"rcd":"yes"|"no","ts"}
# — i.e. `state`/`type`/`outletId` (not breakerState/breakerType/socketId) and
# `rcd` as a STRING. The handler must read those keys and coerce `rcd` to a real
# bool (the Boolean column rejected the raw "no" string → TypeError every msg).

def test_breaker_status_real_firmware_contract():
    payload = {
        "cabinetId": CABINET,
        "outletId": "Q3",
        "state": "tripped",
        "type": "MCB",
        "rating": "C",
        "poles": 3,
        "rcd": "no",
        "ts": "1970-01-01T00:00:08Z",
    }
    broadcasts = _simulate("opta/breakers/Q3/status", payload)

    pid = _pedestal_id_for_cabinet()
    cfg = _get_socket_config(pid, 3)
    assert cfg is not None
    assert cfg.breaker_state == "tripped"       # read from `state`
    assert cfg.breaker_type == "MCB"            # read from `type`
    assert cfg.breaker_rating == "C"
    assert cfg.breaker_rcd is False             # "no" coerced to bool, no crash

    # Broadcast carries the corrected, coerced values.
    changed = [b for b in broadcasts if b.get("event") == "breaker_state_changed"]
    assert changed and changed[0]["data"]["breaker_rcd"] is False
    assert changed[0]["data"]["breaker_type"] == "MCB"


def test_breaker_status_rcd_yes_coerced_true():
    _simulate("opta/breakers/Q4/status", {
        "cabinetId": CABINET,
        "outletId": "Q4",
        "state": "closed",
        "type": "RCBO",
        "rating": "B",
        "poles": 1,
        "rcd": "yes",
    })
    pid = _pedestal_id_for_cabinet()
    cfg = _get_socket_config(pid, 4)
    assert cfg.breaker_rcd is True              # "yes" coerced to bool
    assert cfg.breaker_state == "closed"
    assert cfg.breaker_type == "RCBO"

# ═══ v3.49 — THE REMOTE-RESET CAPABILITY PRECONDITION ════════════════════════
#
# Cabinet 1's breakers are ordinary MCBs (owner, 2026-10-11). Before this precondition,
# pressing Reset flipped `breaker_state` to 'resetting', wrote a breaker_events row and
# published an MQTT command nothing acts on — so the operator watched a reset in progress
# that could never complete, and SocketBreakerPanel's 15 s watchdog then reported "overload
# condition may still be present", which was the wrong diagnosis entirely.
#
# The state flip is the part that matters most in these tests: a refusal that still mutates
# the breaker record would leave the UI exactly as broken as before.


def _capability_case(client, auth_headers, capability):
    """Trip a socket, set its capability, attempt a reset. Returns (response, config)."""
    pid = _trip_socket(1)
    _seed_socket_config(pid, 1, breaker_remote_reset=capability)
    r = client.post(f"/api/pedestals/{pid}/sockets/1/breaker/reset", headers=auth_headers)
    return r, _get_socket_config(pid, 1)


def test_reset_refused_when_capability_never_established(client, auth_headers):
    """NULL refuses, and the message names what to do about it."""
    r, cfg = _capability_case(client, auth_headers, None)
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "never been established" in detail, detail
    assert "breaker_remote_reset" in detail, (
        "the refusal does not name the field an operator must set"
    )
    assert cfg.breaker_state == "tripped", (
        f"the breaker was moved to {cfg.breaker_state!r} by a REFUSED reset — this is the "
        f"exact failure the precondition exists to prevent"
    )


def test_reset_refused_for_an_ordinary_mcb(client, auth_headers):
    """'no' refuses, and says the reset is manual rather than merely unavailable."""
    r, cfg = _capability_case(client, auth_headers, "no")
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "by hand" in detail or "manual" in detail.lower(), detail
    assert cfg.breaker_state == "tripped", "a refused reset still mutated the record"


def test_a_refused_reset_publishes_nothing_and_writes_no_event(client, auth_headers):
    """No MQTT, no audit row. A refusal must leave no trace of an attempt."""
    from app.models.breaker_event import BreakerEvent
    published = []

    def fake_publish(topic, payload, *args, **kwargs):
        published.append((topic, payload))

    pid = _trip_socket(1)
    _seed_socket_config(pid, 1, breaker_remote_reset="no")

    db = _TestSession()
    try:
        before = db.query(BreakerEvent).filter(
            BreakerEvent.pedestal_id == pid, BreakerEvent.event_type == "reset_attempted",
        ).count()
    finally:
        db.close()

    with patch("app.services.mqtt_client.mqtt_service.publish", side_effect=fake_publish):
        r = client.post(f"/api/pedestals/{pid}/sockets/1/breaker/reset", headers=auth_headers)
    assert r.status_code == 409

    assert not [t for t, _ in published if "breaker" in t], (
        f"a refused reset published to the hardware anyway: {published}"
    )
    db = _TestSession()
    try:
        after = db.query(BreakerEvent).filter(
            BreakerEvent.pedestal_id == pid, BreakerEvent.event_type == "reset_attempted",
        ).count()
    finally:
        db.close()
    assert after == before, "a refused reset wrote a reset_attempted audit row"


def test_capability_is_checked_before_tripped_state(client, auth_headers):
    """Order matters: "cannot be reset remotely" outranks "not tripped right now".

    Giving the state answer first would imply the action becomes available once it trips,
    which on an ordinary MCB it never does.
    """
    _simulate("opta/breakers/Q1/status", {
        "cabinetId": CABINET, "socketId": "Q1", "breakerState": "closed",
    })
    pid = _pedestal_id_for_cabinet()
    _seed_socket_config(pid, 1, breaker_remote_reset="no")
    r = client.post(f"/api/pedestals/{pid}/sockets/1/breaker/reset", headers=auth_headers)
    assert r.status_code == 409
    detail = r.json()["detail"].lower()
    assert "not in tripped state" not in detail, (
        "a closed, non-motorised breaker was told it is not tripped — which implies the "
        "reset would work once it trips"
    )


def test_erp_reset_is_refused_by_the_same_precondition(client, auth_headers):
    """The ERP path must not be a way around it — it shares perform_breaker_reset.

    ORDERING, FOUND BY WRITING THIS TEST: ext_breaker_endpoints.py:189 checks Smart Mode
    BEFORE delegating, so on a standalone cabinet the ERP gets the Smart-Mode refusal and
    never reaches the capability one. That is the right precedence — Smart Mode is the
    master gate for NUC action — but it means Smart Mode has to be ON here for this test
    to be about capability at all. Without this line it passed on the wrong refusal.
    """
    pid = _trip_socket(1)
    _set_smart_mode(pid, True)
    _seed_socket_config(pid, 1, breaker_remote_reset=None)
    _enable_ext_endpoints(["breakers.socket_reset_ext"])
    r = client.post(
        f"/api/ext/pedestals/{pid}/sockets/1/breaker/reset",
        headers={"Authorization": f"Bearer {_make_ext_jwt()}"},
    )
    assert r.status_code == 409, r.text
    assert "never been established" in r.json()["detail"]


@pytest.mark.parametrize("capability,available,reason_contains", [
    ("motorised", True,  None),
    ("no",        False, "manual"),
    (None,        False, "not established"),
])
def test_status_exposes_the_capability_and_a_reason(client, auth_headers,
                                                     capability, available, reason_contains):
    """The UI renders from these three fields, so they are part of the contract.

    `remote_reset_unavailable_reason` follows FacilityLine's shape: the reason is shown
    rather than the control being silently absent, so an operator learns what to do instead
    of wondering where the button went.
    """
    pid = _trip_socket(1)
    _seed_socket_config(pid, 1, breaker_remote_reset=capability)
    r = client.get(f"/api/pedestals/{pid}/sockets/1/breaker/status", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["breaker_remote_reset"] == capability
    assert body["remote_reset_available"] is available
    if reason_contains is None:
        assert body["remote_reset_unavailable_reason"] is None
    else:
        assert reason_contains in (body["remote_reset_unavailable_reason"] or "").lower(), (
            body["remote_reset_unavailable_reason"]
        )


def test_capability_is_never_set_from_mqtt(client, auth_headers):
    """Firmware cannot know whether an installer fitted a motor operator.

    Every other breaker metadata field IS populated from `opta/breakers/+/status`. This one
    must not be, and a payload claiming it must be ignored — inferring live-hardware
    capability from a string the firmware supplies is the cloud_iot/cloud-iot bug again.
    """
    pid = _trip_socket(1)
    _seed_socket_config(pid, 1, breaker_remote_reset=None)
    _simulate("opta/breakers/Q1/status", {
        "cabinetId": CABINET, "socketId": "Q1", "breakerState": "tripped",
        "breakerType": "ABB S201-C16 MOTORISED",
        "remoteReset": "motorised",
        "breaker_remote_reset": "motorised",
    })
    cfg = _get_socket_config(pid, 1)
    assert cfg.breaker_remote_reset is None, (
        f"MQTT set the capability to {cfg.breaker_remote_reset!r}. The firmware cannot know "
        f"this, and a free-text breakerType must never be parsed into it."
    )
