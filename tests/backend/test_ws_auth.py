"""/ws demands the same authenticated operator as an HTTP route (2026-10-12, part A).

MEASURED ON THE NETWORK BEFORE THIS CHANGE (owner, 2026-10-12): a client with no token, no
cookie and no login got `101 Switching Protocols` on https://marina2.lika.solutions/ws and then
received the cabinet's whole telemetry stream — opta_status, socket states, per-phase amps,
water readings carrying customer_id, door state, temperature, heartbeats. 2FA protected the
screens; the data channel behind them had no check at all.

The rule (docs/engineering_notes.md, rule 13): every channel to data proves identity with the
SAME check as an HTTP route, before it joins any broadcast. Here that is literally the same
function — auth.dependencies.operator_from_token — not a copy of it.

Each refusal test below FAILS on the pre-change code (shown 2026-10-12): the old handler
accepted every connection, so a `ping` came back `pong`. The token travels in the
Sec-WebSocket-Protocol header (["bearer", <jwt>]), never in the query string, which uvicorn and
nginx would write to their access logs.

  TC-WSA-01  no token                  -> refused at the handshake, receives nothing
  TC-WSA-02  a token that is not a JWT -> refused
  TC-WSA-03  a pre-2FA (totp_pending) token -> refused: the password alone is not a login
  TC-WSA-04  a customer token          -> refused: operators only (D6.1 — customers live in the ERP)
  TC-WSA-05  an expired operator token -> refused
  TC-WSA-06  a valid operator token    -> accepted, answers ping, receives broadcasts
  TC-WSA-07  the connection CLOSES when the token expires, instead of streaming for ever
Tokens are minted here, from the test secret — no credential is stored anywhere.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from starlette.websockets import WebSocketDisconnect


def _admin():
    from conftest import TestUserSession
    from app.auth.models import User
    db = TestUserSession()
    try:
        u = db.query(User).filter(User.role == "admin").first()
        assert u is not None, "conftest seeds an admin"
        return u.id, u.email
    finally:
        db.close()


def _admin_token(**override_claims) -> str:
    from app.auth.tokens import create_access_token
    from app.config import settings
    uid, email = _admin()
    if not override_claims:
        return create_access_token(uid, email, "admin")
    payload = {"sub": str(uid), "email": email, "role": "admin", **override_claims}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _smart_mode_on(pedestal_id: int) -> None:
    from conftest import TestSession
    from app.models.pedestal_config import PedestalConfig
    db = TestSession()
    try:
        cfg = db.query(PedestalConfig).filter_by(pedestal_id=pedestal_id).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pedestal_id)
            db.add(cfg)
        cfg.smart_mode = True
        db.commit()
    finally:
        db.close()


def _first_reply(client, subprotocols) -> str | None:
    """Open /ws, send `ping`, return what comes back — or None if the connection was refused.

    A ping keeps the test from blocking on old code: the old handler accepted everything and
    answered `pong`, so a refusal test FAILS there instead of hanging.
    """
    try:
        with client.websocket_connect("/ws", subprotocols=subprotocols) as ws:
            ws.send_text("ping")
            return ws.receive_text()
    except WebSocketDisconnect:
        return None


def test_tc_wsa_01_no_token_is_refused(client):
    assert _first_reply(client, None) is None, "an anonymous client was answered"


def test_tc_wsa_02_a_non_jwt_is_refused(client):
    assert _first_reply(client, ["bearer", "not-a-jwt-at-all"]) is None


def test_tc_wsa_03_a_pre_2fa_token_is_refused(client):
    from app.auth.tokens import create_partial_token
    uid, email = _admin()
    assert _first_reply(client, ["bearer", create_partial_token(uid, email)]) is None, (
        "a token issued after the password but before the second factor opened the data feed")


def test_tc_wsa_04_a_customer_token_is_refused(client):
    from app.auth.tokens import create_customer_token
    assert _first_reply(client, ["bearer", create_customer_token(1, "c@example.test")]) is None


def test_tc_wsa_05_an_expired_operator_token_is_refused(client):
    tok = _admin_token(exp=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert _first_reply(client, ["bearer", tok]) is None


def test_tc_wsa_06_a_valid_operator_token_is_accepted_and_receives_broadcasts(
        client, auth_headers):
    """Positive control. It passes on the old code too — the old code answered everyone —
    which is why the refusal tests above, not this one, are the proof."""
    with client.websocket_connect("/ws", subprotocols=["bearer", _admin_token()]) as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"
        # Any route that broadcasts will do; a water stop broadcasts direct_cmd_sent. Smart
        # mode is switched on first so the route reaches the broadcast instead of a 409.
        _smart_mode_on(1)
        with patch("app.routers.controls.mqtt_service.publish"):
            r = client.post("/api/controls/pedestal/1/water/V1/cmd",
                            json={"action": "stop"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        events = []
        for _ in range(5):
            msg = ws.receive_json()
            events.append(msg.get("event"))
            if msg.get("event") == "direct_cmd_sent":
                break
        assert "direct_cmd_sent" in events, f"no broadcast reached the operator: {events}"


def test_tc_wsa_07_the_connection_closes_when_the_token_expires(client):
    """2026-10-12: this used to sleep 3 s and then ping, i.e. it bet on a 1 s margin over the
    server's expiry task. Under full-gate load the task ran after the ping, the client got
    "pong", and the gate failed once on correct code. It now waits for the CLOSE itself, with an
    upper bound: no margin to lose, and a server that never closes still fails (after 10 s)
    instead of hanging."""
    import queue
    import threading
    import time
    tok = _admin_token(exp=datetime.now(timezone.utc) + timedelta(seconds=2))
    with client.websocket_connect("/ws", subprotocols=["bearer", tok]) as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"
        # Every message until the close. An admin connection also receives broadcasts that
        # background tasks of other tests emit (seen in the gate 2026-10-12: a stray
        # session_completed arrived first) — those are skipped, not counted as the answer.
        got: queue.Queue = queue.Queue()

        def _pump():
            while True:
                m = ws.receive()
                got.put(m)
                if m["type"] == "websocket.close":
                    return
        threading.Thread(target=_pump, daemon=True).start()
        deadline = time.monotonic() + 10
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                pytest.fail("the connection was still open 10 s after its token expired")
            try:
                msg = got.get(timeout=left)
            except queue.Empty:
                continue
            if msg["type"] == "websocket.close":
                break
        assert msg.get("code") == 1008, msg


def test_tc_wsa_08_ws_checks_the_same_user_database_as_http(client):
    """2026-10-12, part B: /ws looked users up in UserSessionLocal (the real users.db), not
    through get_user_db like every HTTP route. An operator who exists ONLY in the test database
    was refused. FAILS on that code (shown 2026-10-12)."""
    from conftest import TestUserSession
    from app.auth.models import User
    from app.auth.password import hash_password
    from app.auth.tokens import create_access_token
    db = TestUserSession()
    try:
        u = User(email="wsa08-only-in-test-db@test.local", password_hash=hash_password("x-unused-x"),
                 role="monitor", is_active=True)
        db.add(u)
        db.commit()
        uid = u.id + 100000  # an id no developer database will hold
        u.id = uid
        db.commit()
    finally:
        db.close()
    tok = create_access_token(uid, "wsa08-only-in-test-db@test.local", "monitor")
    assert _first_reply(client, ["bearer", tok]) is not None, (
        "an operator who exists in the database the HTTP routes use was refused on /ws")
