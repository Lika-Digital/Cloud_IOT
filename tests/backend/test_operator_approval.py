"""
Operator Approval Flow — Verification Tests
============================================

Tests cover the socket-level operator approval/rejection introduced alongside
the existing mobile-first session flow.

State machine under test:
  IDLE → PENDING (MQTT connected) → ACTIVE (operator or mobile approves)
  IDLE → PENDING (MQTT connected) → IDLE  (operator rejects)
  IDLE → PENDING (MQTT connected) → IDLE  (timeout, no action)

Test IDs:
  TC-OA-01  MQTT registers + socket state initialises to IDLE (no session)
  TC-OA-02  MQTT "connected" → operator_status="pending" + socket_pending WS event
  TC-OA-03  Operator approves → session ACTIVE + MQTT {"cmd":"approved"} command
  TC-OA-04  Operator rejects → MQTT {"cmd":"rejected","reason":"Operator denied"} + socket IDLE
  TC-OA-05  Mobile approves when operator already approved → 200 (no conflict), customer claimed
  TC-OA-06  Mobile approves when operator has done nothing → normal flow (200, active session)
  TC-OA-07  Timeout with no action → auto-reject → MQTT rejection + socket IDLE
  TC-OA-08  All transitions recorded in audit log with actor, action, timestamp
"""
import asyncio
import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# ── shared test DBs (same files as conftest) ──────────────────────────────────
TEST_DB      = "sqlite:///./tests/test_pedestal.db"
TEST_USER_DB = "sqlite:///./tests/test_users.db"

_test_engine      = create_engine(TEST_DB,      connect_args={"check_same_thread": False}, poolclass=StaticPool)
_test_user_engine = create_engine(TEST_USER_DB, connect_args={"check_same_thread": False}, poolclass=StaticPool)
_TestSession      = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)
_TestUserSession  = sessionmaker(autocommit=False, autoflush=False, bind=_test_user_engine)


@pytest.fixture(scope="session", autouse=True)
def _dispose_oa_engines():
    yield
    _test_engine.dispose()
    _test_user_engine.dispose()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _simulate_mqtt(topic: str, payload: str):
    from app.services.mqtt_handlers import handle_message
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock(return_value=None)),
    ):
        asyncio.run(handle_message(topic, payload))


def _get_socket_state(pedestal_id: int, socket_id: int):
    from app.models.pedestal_config import SocketState
    db = _TestSession()
    try:
        return db.query(SocketState).filter(
            SocketState.pedestal_id == pedestal_id,
            SocketState.socket_id == socket_id,
        ).first()
    finally:
        db.close()


def _set_socket_state(pedestal_id: int, socket_id: int, **kwargs):
    """Directly write / update a SocketState row."""
    from app.models.pedestal_config import SocketState
    db = _TestSession()
    try:
        state = db.query(SocketState).filter(
            SocketState.pedestal_id == pedestal_id,
            SocketState.socket_id == socket_id,
        ).first()
        if state:
            for k, v in kwargs.items():
                setattr(state, k, v)
        else:
            db.add(SocketState(
                pedestal_id=pedestal_id,
                socket_id=socket_id,
                connected=kwargs.get("connected", True),
                operator_status=kwargs.get("operator_status"),
                operator_status_at=kwargs.get("operator_status_at"),
            ))
        db.commit()
    finally:
        db.close()


def _get_audit_entries(pedestal_id: int, socket_id: int):
    from app.models.session_audit import SessionAuditLog
    db = _TestSession()
    try:
        return (
            db.query(SessionAuditLog)
            .filter(
                SessionAuditLog.pedestal_id == pedestal_id,
                SessionAuditLog.socket_id == socket_id,
            )
            .order_by(SessionAuditLog.id)
            .all()
        )
    finally:
        db.close()


def _clear_sessions_for_socket(pedestal_id: int, socket_id: int):
    from app.models.session import Session as SessionModel
    db = _TestSession()
    try:
        db.query(SessionModel).filter(
            SessionModel.pedestal_id == pedestal_id,
            SessionModel.socket_id == socket_id,
        ).delete()
        db.commit()
    finally:
        db.close()


# ── Dedicated pedestal for approval tests ─────────────────────────────────────

@pytest.fixture(scope="module")
def approval_pid(client, auth_headers):
    """Create a mobile-enabled pedestal dedicated to operator approval tests."""
    r = client.post("/api/pedestals/", json={
        "name": "Approval Test Pedestal",
        "location": "TC Dock",
        "data_mode": "real",
    }, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    client.patch(f"/api/pedestals/{pid}", json={"mobile_enabled": True}, headers=auth_headers)
    return pid


# ═══════════════════════════════════════════════════════════════════════════════
# TC-OA-01  MQTT registers and socket state initialises to IDLE
# ═══════════════════════════════════════════════════════════════════════════════

class TestMqttRegistrationIdle:
    def test_tc_oa_01_register_creates_pedestal_no_session(self, approval_pid):
        """
        TC-OA-01 [IMPLEMENTED]
        A register + heartbeat message creates the pedestal row.
        No session is created — socket state is IDLE.
        """
        pid = approval_pid
        socket_id = 1

        _simulate_mqtt(f"pedestal/{pid}/register", json.dumps({
            "sensor_name": "socket_1",
            "sensor_type": "electricity",
            "mqtt_topic": f"pedestal/{pid}/socket/1/power",
            "unit": "W",
        }))
        _simulate_mqtt(f"pedestal/{pid}/heartbeat", json.dumps({
            "online": True, "timestamp": datetime.utcnow().isoformat(),
        }))

        from app.models.session import Session as SessionModel
        db = _TestSession()
        try:
            session_count = db.query(SessionModel).filter(
                SessionModel.pedestal_id == pid,
                SessionModel.socket_id == socket_id,
                SessionModel.status.in_(["pending", "active"]),
            ).count()
        finally:
            db.close()

        assert session_count == 0, (
            "No session should exist after register/heartbeat — socket must be IDLE"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TC-OA-02  MQTT "connected" → operator_status=pending + socket_pending WS event
# ═══════════════════════════════════════════════════════════════════════════════

class TestSocketPendingOnConnect:
    def test_tc_oa_02_connected_sets_pending_and_broadcasts(self, approval_pid):
        """
        TC-OA-02 [IMPLEMENTED]
        When the Opta reports socket "connected", SocketState.operator_status is set
        to "pending" and a socket_pending WebSocket event is broadcast to the dashboard.
        """
        pid = approval_pid
        socket_id = 2

        broadcasts = []

        async def _capture(payload):
            broadcasts.append(payload)

        from app.services.mqtt_handlers import handle_message
        with (
            patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
            patch("app.services.mqtt_handlers.ws_manager.broadcast", side_effect=_capture),
        ):
            asyncio.run(handle_message(f"pedestal/{pid}/socket/{socket_id}/status", "connected"))

        state = _get_socket_state(pid, socket_id)
        assert state is not None, "SocketState must be created on connect"
        assert state.connected is True
        assert state.operator_status == "pending", (
            f"operator_status must be 'pending' after connect, got {state.operator_status!r}"
        )
        assert state.operator_status_at is not None

        pending_events = [b for b in broadcasts if b.get("event") == "socket_pending"]
        assert pending_events, "socket_pending WS event must be broadcast on connect"
        assert pending_events[0]["data"]["pedestal_id"] == pid
        assert pending_events[0]["data"]["socket_id"] == socket_id


# ═══════════════════════════════════════════════════════════════════════════════
# TC-OA-03  Operator approves → session ACTIVE + MQTT {"cmd":"approved"}
# ═══════════════════════════════════════════════════════════════════════════════

class TestOperatorApproves:
    def test_tc_oa_03_operator_approve_creates_active_session_and_publishes(
        self, client, auth_headers, approval_pid
    ):
        """
        TC-OA-03 [IMPLEMENTED]
        Operator calls POST /api/controls/sockets/{pid}/{sid}/approve.
        Session transitions to ACTIVE and MQTT {"cmd":"approved"} is published
        to pedestal/{pid}/socket/{sid}/command.
        """
        pid = approval_pid
        socket_id = 3
        _clear_sessions_for_socket(pid, socket_id)
        _set_socket_state(pid, socket_id, connected=True, operator_status="pending",
                          operator_status_at=datetime.utcnow())

        published = []
        from app.services.mqtt_client import mqtt_service
        original = mqtt_service.publish
        mqtt_service.publish = lambda t, p: published.append((t, p))
        try:
            r = client.post(
                f"/api/controls/sockets/{pid}/{socket_id}/approve",
                headers=auth_headers,
            )
        finally:
            mqtt_service.publish = original

        assert r.status_code == 200, r.text
        session = r.json()
        assert session["status"] == "active"

        expected_topic = f"pedestal/{pid}/socket/{socket_id}/command"
        mqtt_match = [
            (t, p) for t, p in published
            if t == expected_topic and json.loads(p).get("cmd") == "approved"
        ]
        assert mqtt_match, (
            f"Expected MQTT approved command on {expected_topic}, got: {published}"
        )

        state = _get_socket_state(pid, socket_id)
        assert state.operator_status is None, "operator_status must be cleared after approval"

        # Cleanup
        _clear_sessions_for_socket(pid, socket_id)


# ═══════════════════════════════════════════════════════════════════════════════
# TC-OA-04  Operator rejects → MQTT rejection command + socket returns to IDLE
# ═══════════════════════════════════════════════════════════════════════════════

class TestOperatorRejects:
    def test_tc_oa_04_operator_reject_publishes_command_and_marks_rejected(
        self, client, auth_headers, approval_pid
    ):
        """
        TC-OA-04 [IMPLEMENTED]
        Operator calls POST /api/controls/sockets/{pid}/{sid}/reject.
        MQTT {"cmd":"rejected","reason":"Operator denied"} is published.
        SocketState.operator_status becomes "rejected" (socket returns to IDLE visually).
        """
        pid = approval_pid
        socket_id = 4
        _set_socket_state(pid, socket_id, connected=True, operator_status="pending",
                          operator_status_at=datetime.utcnow())

        published = []
        broadcasts = []
        from app.services.mqtt_client import mqtt_service
        original = mqtt_service.publish
        mqtt_service.publish = lambda t, p: published.append((t, p))
        try:
            r = client.post(
                f"/api/controls/sockets/{pid}/{socket_id}/reject",
                json={"reason": "Operator denied"},
                headers=auth_headers,
            )
        finally:
            mqtt_service.publish = original

        assert r.status_code == 200, r.text

        expected_topic = f"pedestal/{pid}/socket/{socket_id}/command"
        mqtt_match = [
            (t, p) for t, p in published
            if t == expected_topic and json.loads(p).get("cmd") == "rejected"
        ]
        assert mqtt_match, f"Expected MQTT rejection on {expected_topic}, got: {published}"
        payload = json.loads(mqtt_match[0][1])
        assert payload.get("reason") == "Operator denied"

        state = _get_socket_state(pid, socket_id)
        assert state.operator_status == "rejected"


# ═══════════════════════════════════════════════════════════════════════════════
# TC-OA-05  Mobile approves when operator already approved → no conflict
# ═══════════════════════════════════════════════════════════════════════════════

class TestMobileLateAfterOperator:
    def test_tc_oa_05_mobile_claims_operator_approved_session(
        self, client, auth_headers, cust_headers, approval_pid
    ):
        """
        TC-OA-05 [IMPLEMENTED]
        Operator approves first (session is ACTIVE, customer_id=None).
        Mobile user then calls /start for the same socket.
        Result: 200 (no conflict), session is returned active, customer_id is assigned.
        The mobile user is now subscribed to the real-time spending stream.
        """
        pid = approval_pid
        socket_id = 3
        _clear_sessions_for_socket(pid, socket_id)
        _set_socket_state(pid, socket_id, connected=True, operator_status="pending",
                          operator_status_at=datetime.utcnow())

        # Operator approves
        r = client.post(f"/api/controls/sockets/{pid}/{socket_id}/approve", headers=auth_headers)
        assert r.status_code == 200, r.text
        op_session_id = r.json()["id"]
        assert r.json()["customer_id"] is None  # no customer yet

        # Mobile user starts (operator already approved — should be no conflict)
        # First stop any existing customer sessions to avoid customer_busy block
        for s in client.get("/api/customer/sessions/mine", headers=cust_headers).json():
            if s["status"] in ("active", "pending"):
                client.post(f"/api/customer/sessions/{s['id']}/stop", headers=cust_headers)

        r2 = client.post("/api/customer/sessions/start", json={
            "pedestal_id": pid,
            "type": "electricity",
            "socket_id": socket_id,
        }, headers=cust_headers)

        assert r2.status_code == 200, (
            f"Expected 200 (no conflict — operator pre-approved), got {r2.status_code}: {r2.text}"
        )
        claimed = r2.json()
        assert claimed["status"] == "active", f"Expected active session, got {claimed['status']}"
        assert claimed["id"] == op_session_id, "Must be the same session operator created"
        assert claimed["customer_id"] is not None, "customer_id must be assigned after claim"

        # Cleanup
        client.post(f"/api/customer/sessions/{op_session_id}/stop", headers=cust_headers)
        _clear_sessions_for_socket(pid, socket_id)


# ═══════════════════════════════════════════════════════════════════════════════
# TC-OA-06  Mobile approves when operator has done nothing → normal flow
# ═══════════════════════════════════════════════════════════════════════════════

class TestMobileNormalFlowNoOperator:
    def test_tc_oa_06_mobile_starts_when_operator_has_not_acted(
        self, client, cust_headers, auth_headers, approval_pid
    ):
        """
        TC-OA-06 [IMPLEMENTED]
        Socket is in pending state (MQTT connected, operator has done nothing).
        Mobile user calls /start → session starts normally, returns 200 active.
        This is identical to the existing flow from the customer perspective.
        """
        pid = approval_pid
        socket_id = 1
        _clear_sessions_for_socket(pid, socket_id)
        _set_socket_state(pid, socket_id, connected=True, operator_status="pending",
                          operator_status_at=datetime.utcnow())

        # Stop any lingering customer sessions
        for s in client.get("/api/customer/sessions/mine", headers=cust_headers).json():
            if s["status"] in ("active", "pending"):
                client.post(f"/api/customer/sessions/{s['id']}/stop", headers=cust_headers)

        r = client.post("/api/customer/sessions/start", json={
            "pedestal_id": pid,
            "type": "electricity",
            "socket_id": socket_id,
        }, headers=cust_headers)

        assert r.status_code == 200, r.text
        session = r.json()
        assert session["status"] == "active"

        # operator_status must be cleared now that a session has started
        state = _get_socket_state(pid, socket_id)
        assert state.operator_status is None, (
            "operator_status must be cleared once mobile user starts session"
        )

        # Cleanup
        client.post(f"/api/customer/sessions/{session['id']}/stop", headers=cust_headers)
        _clear_sessions_for_socket(pid, socket_id)


# ═══════════════════════════════════════════════════════════════════════════════
# TC-OA-07  Timeout → auto-reject → MQTT rejection + socket IDLE
# ═══════════════════════════════════════════════════════════════════════════════

class TestTimeout:
    def test_tc_oa_07_stale_pending_socket_auto_rejected(self, approval_pid):
        """
        TC-OA-07 [IMPLEMENTED]
        A socket_state with operator_status='pending' older than the timeout is
        auto-rejected by the watchdog: operator_status becomes 'rejected',
        MQTT {"cmd":"rejected"} is published, socket_rejected WS event is broadcast.
        """
        pid = approval_pid
        socket_id = 2
        old_time = datetime.utcnow() - timedelta(seconds=120)
        _set_socket_state(pid, socket_id, connected=True, operator_status="pending",
                          operator_status_at=old_time)

        published = []
        broadcasts = []

        from app.services.mqtt_handlers import auto_reject_stale_socket_pending
        db = _TestSession()
        try:
            cutoff = datetime.utcnow() - timedelta(seconds=15)
            asyncio.run(auto_reject_stale_socket_pending(
                db,
                cutoff,
                lambda t, p: published.append((t, p)),
                AsyncMock(side_effect=lambda payload: broadcasts.append(payload)),
                15,
            ))
        finally:
            db.close()

        state = _get_socket_state(pid, socket_id)
        assert state.operator_status == "rejected", (
            f"Expected operator_status='rejected' after timeout, got {state.operator_status!r}"
        )

        expected_topic = f"pedestal/{pid}/socket/{socket_id}/command"
        mqtt_match = [
            (t, p) for t, p in published
            if t == expected_topic and json.loads(p).get("cmd") == "rejected"
        ]
        assert mqtt_match, f"Expected MQTT rejection published, got: {published}"


# ═══════════════════════════════════════════════════════════════════════════════
# TC-OA-08  All transitions recorded in audit log
# ═══════════════════════════════════════════════════════════════════════════════

class TestAuditLog:
    def test_tc_oa_08_audit_log_records_all_transitions(
        self, client, auth_headers, cust_headers, approval_pid
    ):
        """
        TC-OA-08 [IMPLEMENTED]
        Each state transition writes an audit log entry with the correct
        actor_type, action, actor_id, and a valid timestamp.

        Transitions exercised:
          socket_connected  (system, MQTT fires)
          operator_approved (operator, dashboard approves)
          customer_claimed_active (customer, mobile approves after operator)
        """
        pid = approval_pid
        socket_id = 1

        # Stop any lingering customer sessions
        for s in client.get("/api/customer/sessions/mine", headers=cust_headers).json():
            if s["status"] in ("active", "pending"):
                client.post(f"/api/customer/sessions/{s['id']}/stop", headers=cust_headers)

        _clear_sessions_for_socket(pid, socket_id)

        from app.models.session_audit import SessionAuditLog
        from sqlalchemy import text
        db = _TestSession()
        try:
            db.execute(text(
                "DELETE FROM session_audit_log WHERE pedestal_id=:pid AND socket_id=:sid"
            ), {"pid": pid, "sid": socket_id})
            db.commit()
        finally:
            db.close()

        # 1. MQTT connect → socket_connected audit entry
        from app.services.mqtt_handlers import handle_message
        with (
            patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
            patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock(return_value=None)),
        ):
            asyncio.run(handle_message(f"pedestal/{pid}/socket/{socket_id}/status", "connected"))

        entries = _get_audit_entries(pid, socket_id)
        assert any(e.action == "socket_connected" and e.actor_type == "system" for e in entries), (
            f"Expected socket_connected audit entry, got: {[(e.action, e.actor_type) for e in entries]}"
        )

        # 2. Operator approves → operator_approved audit entry
        r = client.post(
            f"/api/controls/sockets/{pid}/{socket_id}/approve",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        session_id = r.json()["id"]

        entries = _get_audit_entries(pid, socket_id)
        op_entries = [e for e in entries if e.action == "operator_approved"]
        assert op_entries, f"Expected operator_approved audit entry, got: {[e.action for e in entries]}"
        assert op_entries[0].actor_type == "operator"
        assert op_entries[0].actor_id is not None
        assert op_entries[0].timestamp is not None

        # 3. Mobile claims active session → customer_claimed_active audit entry
        r2 = client.post("/api/customer/sessions/start", json={
            "pedestal_id": pid,
            "type": "electricity",
            "socket_id": socket_id,
        }, headers=cust_headers)
        assert r2.status_code == 200, r2.text

        entries = _get_audit_entries(pid, socket_id)
        cust_entries = [e for e in entries if e.action == "customer_claimed_active"]
        assert cust_entries, f"Expected customer_claimed_active audit entry, got: {[e.action for e in entries]}"
        assert cust_entries[0].actor_type == "customer"
        assert cust_entries[0].timestamp is not None

        # Cleanup
        client.post(f"/api/customer/sessions/{session_id}/stop", headers=cust_headers)
        _clear_sessions_for_socket(pid, socket_id)
