"""
Mobile QR-Claim + Per-Session Monitoring — Verification Tests (v3.6) — DORMANT
=============================================================================

**SKIPPED IN FULL FROM 2026-09-30. QR is not a supported path.**

NFC was chosen as the provisioning and customer-entry mechanism. The QR code, the
`/api/mobile/qr/*` router, the landing screen and this suite are **dormant, not removed** —
nothing is deleted, and nothing here is maintained, extended or brought to parity with
anything. Every test in this module carries the skip reason, so the count in the gate output
shows how much is dormant rather than hiding it behind a single module-level skip.

If QR is ever revived, this suite is the starting point and everything in it was passing on
the day it was parked — including the v3.43 six-outlet parity work, which is finished and
stays. What it does NOT cover is anything added after that date.

Covers the `/api/mobile/` router, the `owner_claimed_at` session column, the short-lived
`websocket_token`, and the session-scoped WebSocket fan-out (`broadcast_to_session`).

Scope matches the v3.6 spec minus the marina-access test (marina access
control is intentionally skipped — any authenticated customer may claim any
socket for monitoring).

Test IDs:
  TC-QR-01  POST /qr/claim without auth → 401/403
  TC-QR-02  POST /qr/claim with unknown pedestal_id → 404
  TC-QR-03  POST /qr/claim with invalid socket_id (e.g. Q9) → 404
  TC-QR-04  POST /qr/claim when no active session → status=no_session
  TC-QR-05  POST /qr/claim when session has no owner → status=claimed, owner + timestamp set
  TC-QR-06  POST /qr/claim by existing owner → status=already_owner, no side-effects
  TC-QR-07  POST /qr/claim by a different customer → status=read_only, is_owner=False
  TC-QR-08  Returned websocket_token validates + carries session_id claim
  TC-QR-09  GET /sessions/{id}/live by owner → 200 + live metrics
  TC-QR-10  GET /sessions/{id}/live by non-owner → 403
  TC-QR-11  GET /socket/{pid}/{sid}/qr by admin → valid PNG
  TC-QR-12  GET /socket/{pid}/{sid}/qr by customer → 403
  TC-TEL-01 TelemetryUpdate broadcasts session_telemetry to subscribed WS
  TC-TEL-02 SessionEnded broadcasts session_ended and closes subscriber
  TC-STOP-01 /api/customer/sessions/{id}/stop now returns 403 for customers
             (monitoring-only enforcement check — exercised elsewhere in
              test_sessions.py; re-verified here for completeness)
"""
from __future__ import annotations
import asyncio
import json
from datetime import datetime
from unittest.mock import patch

import contextlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Marked on the module rather than skipped at import, so every test reports its own skip and
# the gate output states the count and the reason. A single module-level skip would show one
# line and let 21 dormant cases look like one.
pytestmark = pytest.mark.skip(
    reason="QR is not a supported path, decision of 2026-09-30"
)

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_test_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False}, poolclass=StaticPool)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)


@pytest.fixture(scope="module", autouse=True)
def _dispose_engine():
    yield
    _test_engine.dispose()


# ── Shared helpers ───────────────────────────────────────────────────────────

def _seed_pedestal_with_cabinet(cabinet_id: str = "TEST_MOBILE_QR") -> tuple[int, str]:
    """Ensure there's a pedestal + PedestalConfig with this opta_client_id.
    Returns (db_id, opta_client_id)."""
    from app.models.pedestal import Pedestal
    from app.models.pedestal_config import PedestalConfig
    db = _TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(opta_client_id=cabinet_id).first()
        if cfg:
            return cfg.pedestal_id, cabinet_id

        existing_ids = [p.id for p in db.query(Pedestal).all()]
        new_id = max(existing_ids, default=0) + 1
        db.add(Pedestal(id=new_id, name=cabinet_id, location="TestMarina",
                        data_mode="real", mobile_enabled=True, initialized=True))
        db.add(PedestalConfig(pedestal_id=new_id, opta_client_id=cabinet_id, opta_connected=1))
        db.commit()
        return new_id, cabinet_id
    finally:
        db.close()


def _make_session(pedestal_db_id: int, socket_id: int, customer_id: int | None = None,
                  status: str = "active") -> int:
    """Insert an electricity session and return its id."""
    from app.models.session import Session as SessionModel
    db = _TestSession()
    try:
        # Clear any existing active/pending rows on this socket so the partial
        # unique index on (pedestal_id, socket_id, type) does not collide.
        db.query(SessionModel).filter(
            SessionModel.pedestal_id == pedestal_db_id,
            SessionModel.socket_id == socket_id,
            SessionModel.type == "electricity",
            SessionModel.status.in_(("pending", "active")),
        ).delete()
        s = SessionModel(
            pedestal_id=pedestal_db_id,
            socket_id=socket_id,
            type="electricity",
            status=status,
            customer_id=customer_id,
        )
        db.add(s)
        db.commit()
        db.refresh(s)
        return s.id
    finally:
        db.close()


def _get_session(session_id: int):
    from app.models.session import Session as SessionModel
    db = _TestSession()
    try:
        return db.get(SessionModel, session_id)
    finally:
        db.close()


def _register_second_customer(client) -> dict:
    """Create a second customer via the API and return auth headers for them.
    Uses the same .example TLD the conftest-seeded customer uses so the email
    validator doesn't trip over reserved TLDs like .local."""
    unique = f"second-{id(object())}"
    r = client.post("/api/customer/auth/register", json={
        "email": f"{unique}@example.com",
        "password": "password123",
        "name": "Second Cust",
    })
    assert r.status_code in (200, 201), r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════════════════
# /qr/claim — branches
# ═══════════════════════════════════════════════════════════════════════════════

def test_qr_claim_requires_auth(client):
    """TC-QR-01"""
    r = client.post("/api/mobile/qr/claim", json={"pedestal_id": "x", "socket_id": "Q1"})
    assert r.status_code in (401, 403)


def test_qr_claim_404_pedestal_not_found(client, cust_headers):
    """TC-QR-02"""
    r = client.post(
        "/api/mobile/qr/claim",
        json={"pedestal_id": "NO_SUCH_CABINET", "socket_id": "Q1"},
        headers=cust_headers,
    )
    assert r.status_code == 404
    assert "pedestal not found" in r.json()["detail"].lower()


@pytest.mark.parametrize("outlet", ["Q9", "Q0", "V3", "V0", "WTR-1", "1", "q1"])
def test_qr_claim_404_invalid_outlet(client, cust_headers, outlet):
    """TC-QR-03 — an outlet this hardware does not have is 404.

    Rewritten at v3.43 rather than adjusted to pass. The rule it encodes changed: the QR path
    now addresses all SIX outlets, so "not a valid socket" is no longer the question being
    asked — "not an outlet this cabinet has" is. The message says `outlet` for the same
    reason, and a customer who scanned a damaged water code should not be told about sockets.

    `V3`/`V0` are new and matter: they are valve-shaped but out of range, and a naive
    `int(name[1:])` would have accepted them and looked up valve 3 on a two-valve cabinet.
    `WTR-1` is here because it lived in an MQTT allowlist for months on the strength of a
    docstring; `q1` catches case-insensitivity, which would make one outlet reachable under
    two spellings.
    """
    _seed_pedestal_with_cabinet()
    r = client.post(
        "/api/mobile/qr/claim",
        json={"pedestal_id": "TEST_MOBILE_QR", "socket_id": outlet},
        headers=cust_headers,
    )
    assert r.status_code == 404, f"{outlet!r} returned {r.status_code}"
    assert "outlet not found" in r.json()["detail"].lower(), r.json()["detail"]


def test_qr_claim_accepts_a_water_outlet(client, cust_headers):
    """TC-QR-03b — V1 is a real outlet and must resolve, not 404.

    The parity change. Six outlets reachable by NFC and four by QR is a difference nobody can
    explain to a customer standing at a water outlet with no code on it.
    """
    _seed_pedestal_with_cabinet()
    r = client.post(
        "/api/mobile/qr/claim",
        json={"pedestal_id": "TEST_MOBILE_QR", "socket_id": "V1"},
        headers=cust_headers,
    )
    assert r.status_code == 200, (
        f"a water outlet was rejected by the QR path: {r.status_code} {r.text}"
    )
    body = r.json()
    assert body["outlet_type"] == "valve"
    assert body["session_type"] == "water"
    assert body["socket_state"] == "unknown", (
        f"got socket_state={body['socket_state']!r}. The firmware sends no valve state — no "
        f'"hose connected" signal and no valve state topic — so "idle" would be a '
        f"socket-shaped answer to a question the hardware never answered, indistinguishable "
        f"from a real reading"
    )


def test_qr_claim_no_session_returns_no_session(client, cust_headers):
    """TC-QR-04 — socket is idle (no active session); response must let the
    mobile app render the 'no_session' view."""
    pid, cab = _seed_pedestal_with_cabinet()
    # Ensure Q4 has no active session (partial unique index prevents dupes).
    from app.models.session import Session as SessionModel
    db = _TestSession()
    try:
        db.query(SessionModel).filter(
            SessionModel.pedestal_id == pid,
            SessionModel.socket_id == 4,
            SessionModel.status.in_(("pending", "active")),
        ).delete()
        db.commit()
    finally:
        db.close()

    r = client.post(
        "/api/mobile/qr/claim",
        json={"pedestal_id": cab, "socket_id": "Q4"},
        headers=cust_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "no_session"
    assert body["socket_state"] in ("idle", "pending")
    # No session-level fields leak out when there's no session.
    assert "session_id" not in body


def test_qr_claim_unowned_session_becomes_claimed(client, cust_headers):
    """TC-QR-05 — session with customer_id=NULL gets claimed."""
    pid, cab = _seed_pedestal_with_cabinet()
    sid = _make_session(pid, socket_id=1, customer_id=None)

    before = _get_session(sid)
    assert before.customer_id is None
    assert before.owner_claimed_at is None

    r = client.post(
        "/api/mobile/qr/claim",
        json={"pedestal_id": cab, "socket_id": "Q1"},
        headers=cust_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "claimed"
    assert body["is_owner"] is True
    assert body["session_id"] == sid
    assert body["websocket_token"], "missing websocket_token"

    after = _get_session(sid)
    assert after.customer_id is not None, "customer_id not set"
    assert after.owner_claimed_at is not None, "owner_claimed_at not set"


def test_qr_claim_second_scan_returns_already_owner(client, cust_headers):
    """TC-QR-06 — same customer scans the QR a second time; no re-claim."""
    pid, cab = _seed_pedestal_with_cabinet()

    # Prime: first scan claims
    sid = _make_session(pid, socket_id=2, customer_id=None)
    r1 = client.post(
        "/api/mobile/qr/claim",
        json={"pedestal_id": cab, "socket_id": "Q2"},
        headers=cust_headers,
    )
    assert r1.status_code == 200 and r1.json()["status"] == "claimed"
    first_claimed_at = _get_session(sid).owner_claimed_at

    # Second scan — must NOT update owner_claimed_at.
    r2 = client.post(
        "/api/mobile/qr/claim",
        json={"pedestal_id": cab, "socket_id": "Q2"},
        headers=cust_headers,
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "already_owner"
    assert r2.json()["is_owner"] is True
    assert _get_session(sid).owner_claimed_at == first_claimed_at, "owner_claimed_at must not rotate"


def test_qr_claim_by_other_customer_is_read_only(client, cust_headers):
    """TC-QR-07 — a different customer scanning an owned session gets a
    read-only view."""
    pid, cab = _seed_pedestal_with_cabinet()

    # Claim as the default customer.
    sid = _make_session(pid, socket_id=3, customer_id=None)
    r1 = client.post(
        "/api/mobile/qr/claim",
        json={"pedestal_id": cab, "socket_id": "Q3"},
        headers=cust_headers,
    )
    assert r1.status_code == 200 and r1.json()["status"] == "claimed"
    first_claimed_at = _get_session(sid).owner_claimed_at

    # Register a second customer and try to claim the same socket.
    second = _register_second_customer(client)
    r2 = client.post(
        "/api/mobile/qr/claim",
        json={"pedestal_id": cab, "socket_id": "Q3"},
        headers=second,
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "read_only"
    assert body["is_owner"] is False
    assert body["session_id"] == sid
    # First owner's claim timestamp must not rotate when someone else scans.
    assert _get_session(sid).owner_claimed_at == first_claimed_at


def test_websocket_token_is_valid_and_scoped(client, cust_headers):
    """TC-QR-08 — decode the token and verify claims."""
    pid, cab = _seed_pedestal_with_cabinet()
    _make_session(pid, socket_id=1, customer_id=None)

    r = client.post(
        "/api/mobile/qr/claim",
        json={"pedestal_id": cab, "socket_id": "Q1"},
        headers=cust_headers,
    )
    assert r.status_code == 200
    token = r.json()["websocket_token"]

    from app.auth.tokens import decode_token
    payload = decode_token(token)
    assert payload is not None
    assert payload["role"] == "ws_session"
    assert payload["session_id"] == r.json()["session_id"]
    assert "exp" in payload


# ═══════════════════════════════════════════════════════════════════════════════
# /sessions/{id}/live
# ═══════════════════════════════════════════════════════════════════════════════

def test_live_endpoint_owner_sees_metrics(client, cust_headers):
    """TC-QR-09 — session owner can fetch live metrics."""
    pid, cab = _seed_pedestal_with_cabinet()
    sid = _make_session(pid, socket_id=1, customer_id=None)
    client.post("/api/mobile/qr/claim",
                json={"pedestal_id": cab, "socket_id": "Q1"},
                headers=cust_headers)

    r = client.get(f"/api/mobile/sessions/{sid}/live", headers=cust_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["session_id"] == sid
    assert "duration_seconds" in body
    assert "energy_kwh" in body
    assert "power_kw" in body
    assert "last_updated_at" in body


def test_live_endpoint_non_owner_403(client, cust_headers):
    """TC-QR-10 — a different customer cannot read live data."""
    pid, cab = _seed_pedestal_with_cabinet()
    sid = _make_session(pid, socket_id=2, customer_id=None)
    client.post("/api/mobile/qr/claim",
                json={"pedestal_id": cab, "socket_id": "Q2"},
                headers=cust_headers)

    second = _register_second_customer(client)
    r = client.get(f"/api/mobile/sessions/{sid}/live", headers=second)
    assert r.status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# /socket/{pid}/{sid}/qr
# ═══════════════════════════════════════════════════════════════════════════════

def test_qr_image_returns_png_for_admin(client, auth_headers):
    """TC-QR-11 — admin can download the QR image."""
    pid, cab = _seed_pedestal_with_cabinet()
    r = client.get(f"/api/mobile/socket/{cab}/Q1/qr", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/png")
    # PNG magic bytes: 89 50 4E 47 ...
    assert r.content[:4] == b"\x89PNG"
    assert "marina.lika.solutions/mobile/socket" in r.headers.get("x-qr-url", "")


def test_qr_image_forbidden_for_customer(client, cust_headers):
    """TC-QR-12 — customers must not fetch QR images (only admins print them)."""
    _seed_pedestal_with_cabinet()
    r = client.get("/api/mobile/socket/TEST_MOBILE_QR/Q1/qr", headers=cust_headers)
    assert r.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════════
# QR parity with NFC (v3.43) — TC-QR-13 / TC-QR-14
# ═══════════════════════════════════════════════════════════════════════════════

@contextlib.contextmanager
def _site_mode(direct_client: bool, app_ready: bool):
    from app.config import settings
    prev = (settings.nfc_direct_client_mode, settings.mobile_app_supports_water_nfc)
    settings.nfc_direct_client_mode = direct_client
    settings.mobile_app_supports_water_nfc = app_ready
    try:
        yield
    finally:
        settings.nfc_direct_client_mode, settings.mobile_app_supports_water_nfc = prev


def test_tc_qr_13_water_outlet_gets_a_printable_code(client, auth_headers):
    """TC-QR-13 — V1 produces a PNG, like every other outlet.

    The parity change in its most concrete form: before this, a water outlet was the one
    outlet on the cabinet with nothing to print.
    """
    _seed_pedestal_with_cabinet()
    with _site_mode(direct_client=False, app_ready=False):
        r = client.get("/api/mobile/socket/TEST_MOBILE_QR/V1/qr", headers=auth_headers)

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(bytes([0x89, 0x50, 0x4E, 0x47])), "not a PNG"
    assert r.headers["X-QR-URL"].endswith("/TEST_MOBILE_QR/V1"), r.headers["X-QR-URL"]


def test_tc_qr_14_water_code_is_gated_by_the_app_version_in_mode_2(client, auth_headers):
    """TC-QR-14 — no printable water code on a mode-2 site whose app cannot read one.

    Stronger than the NFC case rather than merely consistent with it: a printed sticker is a
    PHYSICAL artefact that outlives the deploy which produced it. An NFC mapping can be
    un-pointed from the dashboard in a second; a code glued to a water outlet cannot.
    """
    _seed_pedestal_with_cabinet()
    with _site_mode(direct_client=True, app_ready=False):
        water = client.get("/api/mobile/socket/TEST_MOBILE_QR/V1/qr", headers=auth_headers)
        elec = client.get("/api/mobile/socket/TEST_MOBILE_QR/Q1/qr", headers=auth_headers)

    assert water.status_code == 409, (
        f"a printable water code was generated for a site whose app cannot read one "
        f"({water.status_code})"
    )
    assert "MOBILE_APP_SUPPORTS_WATER_NFC" in water.json()["detail"]
    assert elec.status_code == 200, (
        "the gate is about water only — blocking electricity codes would be a site-wide "
        "outage with nothing pointing at a water flag"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# WebSocket fan-out (TelemetryUpdate → session_telemetry)
# ═══════════════════════════════════════════════════════════════════════════════

def test_telemetry_update_broadcasts_session_telemetry(client, cust_headers):
    """TC-TEL-01 — an MQTT TelemetryUpdate event must push session_telemetry
    to any subscriber registered for that session."""
    pid, cab = _seed_pedestal_with_cabinet()
    sid = _make_session(pid, socket_id=1, customer_id=None)
    # Make sure the pre-subscription lookup in _handle_event_telemetry_update
    # finds the session as owned (claim it).
    client.post("/api/mobile/qr/claim",
                json={"pedestal_id": cab, "socket_id": "Q1"},
                headers=cust_headers)

    captured: list[dict] = []

    async def run():
        # Register a fake subscriber directly on the singleton.
        from app.services.websocket_manager import ws_manager
        class _StubWS:
            async def send_text(self, data):
                captured.append(json.loads(data))
            async def close(self, *a, **k):
                pass
        stub = _StubWS()
        ws_manager.subscribe_to_session(stub, sid)
        try:
            payload = {
                "eventType": "TelemetryUpdate",
                "device": {"cabinetId": cab, "outletId": "Q1", "resource": "POWER"},
                "metrics": {"durationMinutes": 1, "energyKwhTotal": 0.123, "powerKw": 0.8},
            }
            from app.services.mqtt_handlers import handle_message
            with patch("app.services.mqtt_handlers.SessionLocal", _TestSession):
                await handle_message("opta/events", json.dumps(payload))
        finally:
            ws_manager.unsubscribe_from_session(stub, sid)

    asyncio.run(run())

    telemetry = [e for e in captured if e.get("event") == "session_telemetry"]
    assert telemetry, f"No session_telemetry event captured; got {[e.get('event') for e in captured]}"
    data = telemetry[-1]["data"]
    assert data["session_id"] == sid
    assert data["power_kw"] == 0.8
    assert data["energy_kwh"] == 0.123


def test_session_ended_event_fires_and_closes(client, cust_headers):
    """TC-TEL-02 — SessionEnded → `session_ended` to subscriber + channel closed."""
    pid, cab = _seed_pedestal_with_cabinet()
    # Create session, claim it, then end it.
    sid = _make_session(pid, socket_id=2, customer_id=None)
    client.post("/api/mobile/qr/claim",
                json={"pedestal_id": cab, "socket_id": "Q2"},
                headers=cust_headers)

    captured: list[dict] = []
    closed: list[bool] = []

    async def run():
        from app.services.websocket_manager import ws_manager
        class _StubWS:
            async def send_text(self, data):
                captured.append(json.loads(data))
            async def close(self, *a, **k):
                closed.append(True)
        stub = _StubWS()
        ws_manager.subscribe_to_session(stub, sid)

        payload = {
            "eventType": "SessionEnded",
            "device": {"cabinetId": cab, "outletId": "Q2", "resource": "POWER"},
            "totals": {"energyKwh": 0.05, "durationMinutes": 3},
        }
        from app.services.mqtt_handlers import handle_message
        with patch("app.services.mqtt_handlers.SessionLocal", _TestSession):
            await handle_message("opta/events", json.dumps(payload))

    asyncio.run(run())

    events = [e.get("event") for e in captured]
    assert "session_ended" in events, f"Expected session_ended, got {events}"
    assert closed, "Subscriber channel must be closed after session_ended"
