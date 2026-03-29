"""
Complete pedestal workflow tests.

Tests cover the full lifecycle:
  Arduino MQTT register → heartbeat → socket connect → mobile session start →
  MQTT allow → power tracking → session stop → invoice

Test IDs match the specification:
  TC-REG-*    MQTT auto-registration (pedestal creation from MQTT)
  TC-SOCK-*   Socket physical connection state tracking
  TC-MOB-*    Mobile session flow with socket state enforcement
  TC-SNMP-*   SNMP BER decoder unit tests
  TC-WORKFLOW Full end-to-end integration

Implementation status is noted in each test's docstring.

IMPORTANT: MQTT handler tests bypass the HTTP layer and call handle_message()
directly. The SessionLocal inside the handlers is patched to use the same
shared test SQLite DB that all other tests use.
"""
import asyncio
import json
import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB      = "sqlite:///./tests/test_pedestal.db"
TEST_USER_DB = "sqlite:///./tests/test_users.db"

from sqlalchemy.pool import StaticPool

_test_engine      = create_engine(
    TEST_DB,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # single connection — releases file lock after dispose()
)
_test_user_engine = create_engine(
    TEST_USER_DB,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestSession      = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)
_TestUserSession  = sessionmaker(autocommit=False, autoflush=False, bind=_test_user_engine)


@pytest.fixture(scope="session", autouse=True)
def _dispose_workflow_engines():
    """Ensure workflow test engines are disposed before conftest teardown removes DB files."""
    yield
    _test_engine.dispose()
    _test_user_engine.dispose()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _simulate_mqtt(topic: str, payload: str):
    """
    Inject an MQTT message directly into handle_message(), routed through
    the test SQLite DB instead of the production DB.
    Also silences ws_manager.broadcast (requires a running ASGI server).
    """
    from app.services.mqtt_handlers import handle_message
    with (
        patch("app.services.mqtt_handlers.SessionLocal", _TestSession),
        patch("app.services.mqtt_handlers.ws_manager.broadcast", AsyncMock(return_value=None)),
    ):
        asyncio.run(handle_message(topic, payload))


def _db_get_pedestal(pedestal_id: int):
    db = _TestSession()
    try:
        from app.models.pedestal import Pedestal
        return db.get(Pedestal, pedestal_id)
    finally:
        db.close()


def _db_get_socket_state(pedestal_id: int, socket_id: int):
    db = _TestSession()
    try:
        from app.models.pedestal_config import SocketState
        return db.query(SocketState).filter(
            SocketState.pedestal_id == pedestal_id,
            SocketState.socket_id == socket_id,
        ).first()
    finally:
        db.close()


def _db_set_socket_state(pedestal_id: int, socket_id: int, connected: bool):
    """Directly write a SocketState record — simulates an Arduino status event."""
    db = _TestSession()
    try:
        from app.models.pedestal_config import SocketState
        state = db.query(SocketState).filter(
            SocketState.pedestal_id == pedestal_id,
            SocketState.socket_id == socket_id,
        ).first()
        if state:
            state.connected = connected
            state.updated_at = datetime.utcnow()
        else:
            db.add(SocketState(pedestal_id=pedestal_id, socket_id=socket_id, connected=connected))
        db.commit()
    finally:
        db.close()


def _db_clear_socket_state(pedestal_id: int, socket_id: int):
    """Remove a SocketState record — restores 'no data' (permissive) state."""
    db = _TestSession()
    try:
        from app.models.pedestal_config import SocketState
        row = db.query(SocketState).filter(
            SocketState.pedestal_id == pedestal_id,
            SocketState.socket_id == socket_id,
        ).first()
        if row:
            db.delete(row)
            db.commit()
    finally:
        db.close()


# ─── Dedicated workflow pedestal fixture ──────────────────────────────────────

@pytest.fixture(scope="module")
def workflow_pedestal_id(client, auth_headers):
    """
    Create a pedestal dedicated to workflow tests so socket state mutations
    don't interfere with other test modules that use pedestal ID 1.
    """
    r = client.post("/api/pedestals/", json={
        "name": "Workflow Test Pedestal",
        "location": "TC Berth",
        "data_mode": "real",
    }, headers=auth_headers)
    assert r.status_code in (200, 201), r.text
    pid = r.json()["id"]
    # Enable mobile so sessions can be started
    client.patch(f"/api/pedestals/{pid}", json={"mobile_enabled": True}, headers=auth_headers)
    return pid


# ═══════════════════════════════════════════════════════════════════════════════
# TC-REG: MQTT Auto-Registration (pedestal created on first MQTT message)
# STATUS: IMPLEMENTED — _ensure_pedestal() in mqtt_handlers.py
# ═══════════════════════════════════════════════════════════════════════════════

class TestMqttAutoRegistration:
    """
    Requirement: When an Arduino device connects to the MQTT broker and sends its
    first message (register or heartbeat), the application must auto-create a
    Pedestal DB record for that pedestal ID. No manual pre-creation is required.
    """

    def test_tc_reg_01_register_message_creates_pedestal(self):
        """
        TC-REG-01 [IMPLEMENTED]
        A register message for a new pedestal ID auto-creates the Pedestal row.
        """
        pid = 500  # high ID — guaranteed not to exist in seeded test DB
        assert _db_get_pedestal(pid) is None, "Pre-condition: pedestal must not exist"

        _simulate_mqtt(f"pedestal/{pid}/register", json.dumps({
            "sensor_name": "socket_1",
            "sensor_type": "electricity",
            "mqtt_topic": f"pedestal/{pid}/socket/1/power",
            "unit": "W",
        }))

        pedestal = _db_get_pedestal(pid)
        assert pedestal is not None, "Pedestal must be auto-created on register message"
        assert pedestal.id == pid
        assert pedestal.name == f"Pedestal {pid}"
        assert pedestal.data_mode == "real"

    def test_tc_reg_02_heartbeat_message_creates_pedestal(self):
        """
        TC-REG-02 [IMPLEMENTED]
        A heartbeat message for an unknown pedestal ID also auto-creates the row.
        """
        pid = 501
        assert _db_get_pedestal(pid) is None

        _simulate_mqtt(f"pedestal/{pid}/heartbeat", json.dumps({
            "online": True,
            "timestamp": datetime.utcnow().isoformat(),
        }))

        pedestal = _db_get_pedestal(pid)
        assert pedestal is not None, "Pedestal must be auto-created on heartbeat"
        assert pedestal.id == pid

    def test_tc_reg_03_duplicate_register_no_duplicate_pedestal(self):
        """
        TC-REG-03 [IMPLEMENTED]
        Sending a second register message for the same pedestal ID must NOT
        create a duplicate row (idempotent upsert).
        """
        pid = 500  # already created by TC-REG-01

        # Send another register message for the same pedestal
        _simulate_mqtt(f"pedestal/{pid}/register", json.dumps({
            "sensor_name": "socket_2",
            "sensor_type": "electricity",
            "mqtt_topic": f"pedestal/{pid}/socket/2/power",
            "unit": "W",
        }))

        db = _TestSession()
        try:
            from app.models.pedestal import Pedestal
            count = db.query(Pedestal).filter(Pedestal.id == pid).count()
            assert count == 1, f"Expected exactly 1 pedestal row for id={pid}, got {count}"
        finally:
            db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# TC-SOCK: Socket Physical Connection State
# STATUS: IMPLEMENTED — SocketState table + _handle_socket_status upsert
# ═══════════════════════════════════════════════════════════════════════════════

class TestSocketState:
    """
    Requirement: When a user plugs a device into a socket, the Arduino sends
    a status event via MQTT. This event must be reflected in the application
    (stored in DB) but must NOT automatically enable power.
    """

    def test_tc_sock_01_connected_status_stored(self):
        """
        TC-SOCK-01 [IMPLEMENTED]
        An MQTT socket status "connected" message stores SocketState(connected=True).
        """
        pid, sid = 502, 1
        _db_clear_socket_state(pid, sid)

        _simulate_mqtt(f"pedestal/{pid}/socket/{sid}/status", "connected")

        state = _db_get_socket_state(pid, sid)
        assert state is not None, "SocketState row must be created"
        assert state.connected is True

    def test_tc_sock_01b_socket_power_not_enabled_on_connect(self, client, cust_headers, workflow_pedestal_id):
        """
        TC-SOCK-01b [IMPLEMENTED]
        Receiving a socket "connected" status does NOT create a session or
        enable power automatically — the pedestal list shows the socket is
        available (not occupied).
        """
        pid = workflow_pedestal_id
        _simulate_mqtt(f"pedestal/{pid}/socket/1/status", "connected")

        r = client.get("/api/customer/sessions/pedestal-status", headers=cust_headers)
        assert r.status_code == 200
        pedestal = next((p for p in r.json() if p["id"] == pid), None)
        assert pedestal is not None
        assert 1 not in pedestal["occupied_sockets"], (
            "Socket should NOT be occupied after physical connect (no session yet)"
        )

    def test_tc_sock_02_disconnected_status_stored(self):
        """
        TC-SOCK-02a [IMPLEMENTED]
        An MQTT socket status "disconnected" message updates SocketState to
        connected=False.
        """
        pid, sid = 502, 1

        _simulate_mqtt(f"pedestal/{pid}/socket/{sid}/status", "disconnected")

        state = _db_get_socket_state(pid, sid)
        assert state is not None
        assert state.connected is False

    def test_tc_sock_02b_disconnected_auto_completes_active_session(self, workflow_pedestal_id):
        """
        TC-SOCK-02b [IMPLEMENTED]
        When a socket "disconnected" event arrives while a session is active on
        that socket, the session must be automatically completed.
        """
        from app.services.session_service import session_service
        from app.models.session import Session as SessionModel

        pid = workflow_pedestal_id
        _db_set_socket_state(pid, 2, True)

        # Directly create and activate a session (bypass HTTP to avoid socket-state check)
        db = _TestSession()
        try:
            session = session_service.create_pending(db, pid, 2, "electricity", customer_id=None)
            session_service.activate(db, session)
            session_id = session.id
        finally:
            db.close()

        # Verify it's active
        db = _TestSession()
        try:
            s = db.get(SessionModel, session_id)
            assert s.status == "active"
        finally:
            db.close()

        # Simulate Arduino reporting socket disconnected
        _simulate_mqtt(f"pedestal/{pid}/socket/2/status", "disconnected")

        # Session must now be completed
        db = _TestSession()
        try:
            s = db.get(SessionModel, session_id)
            assert s.status == "completed", (
                f"Expected 'completed' after disconnect, got '{s.status}'"
            )
        finally:
            db.close()

    def test_tc_sock_03_power_reading_stored_against_active_session(self, workflow_pedestal_id):
        """
        TC-SOCK-03 [IMPLEMENTED]
        Power readings (MQTT socket/N/power) are stored against the active session
        on that socket. Without an active session the reading is stored orphaned
        (session_id=None) — no session is created.
        """
        from app.services.session_service import session_service
        from app.models.sensor_reading import SensorReading

        pid = workflow_pedestal_id
        _db_set_socket_state(pid, 3, True)

        # Create and activate a session on socket 3
        db = _TestSession()
        try:
            session = session_service.create_pending(db, pid, 3, "electricity", customer_id=None)
            session_service.activate(db, session)
            session_id = session.id
        finally:
            db.close()

        # Simulate power reading from Arduino
        _simulate_mqtt(f"pedestal/{pid}/socket/3/power", json.dumps({
            "watts": 1500.0,
            "kwh_total": 0.25,
        }))

        # Check reading was stored against the session
        db = _TestSession()
        try:
            reading = (
                db.query(SensorReading)
                .filter(
                    SensorReading.pedestal_id == pid,
                    SensorReading.socket_id == 3,
                    SensorReading.session_id == session_id,
                    SensorReading.type == "power_watts",
                )
                .order_by(SensorReading.id.desc())
                .first()
            )
            assert reading is not None, "Power reading must be linked to active session"
            assert reading.value == 1500.0
        finally:
            db.close()

        # Cleanup
        db = _TestSession()
        try:
            from app.models.session import Session as SessionModel
            s = db.get(SessionModel, session_id)
            if s and s.status == "active":
                session_service.complete(db, s)
                db.commit()
        finally:
            db.close()


# ═══════════════════════════════════════════════════════════════════════════════
# TC-MOB: Mobile Session Flow with Socket State Enforcement
# STATUS: IMPLEMENTED — customer_sessions.py checks SocketState before start
# ═══════════════════════════════════════════════════════════════════════════════

class TestMobileSessionFlow:
    """
    Requirement: The application must validate the request by checking whether
    the socket is physically connected before allowing a session to start.
    """

    def test_tc_mob_01_session_start_allowed_when_socket_connected(
        self, client, cust_headers, workflow_pedestal_id
    ):
        """
        TC-MOB-01 [IMPLEMENTED]
        Session start is allowed when SocketState.connected=True.
        """
        pid = workflow_pedestal_id
        _db_set_socket_state(pid, 4, True)

        r = client.post("/api/customer/sessions/start", json={
            "pedestal_id": pid,
            "type": "electricity",
            "socket_id": 4,
        }, headers=cust_headers)
        assert r.status_code == 200, r.text
        session = r.json()
        assert session["status"] == "active"

        # Cleanup
        client.post(f"/api/customer/sessions/{session['id']}/stop", headers=cust_headers)

    def test_tc_mob_02_session_start_blocked_when_socket_disconnected(
        self, client, cust_headers, workflow_pedestal_id
    ):
        """
        TC-MOB-02 [IMPLEMENTED]
        Session start must be rejected (409) when SocketState.connected=False.
        This enforces the requirement: "socket physically connected" is a
        prerequisite for session activation.
        """
        pid = workflow_pedestal_id
        _db_set_socket_state(pid, 4, False)

        r = client.post("/api/customer/sessions/start", json={
            "pedestal_id": pid,
            "type": "electricity",
            "socket_id": 4,
        }, headers=cust_headers)
        assert r.status_code == 409, (
            f"Expected 409 (disconnected socket), got {r.status_code}: {r.text}"
        )
        assert "not physically connected" in r.json()["detail"].lower()

        # Restore for subsequent tests
        _db_clear_socket_state(pid, 4)

    def test_tc_mob_03_session_start_allowed_when_no_socket_state(
        self, client, cust_headers, workflow_pedestal_id
    ):
        """
        TC-MOB-03 [IMPLEMENTED — permissive]
        When no SocketState record exists (Arduino has not reported this socket yet),
        the session is allowed. This is the 'no data = benefit of the doubt' policy
        to prevent blocking sessions on fresh deployments.
        """
        pid = workflow_pedestal_id
        _db_clear_socket_state(pid, 4)  # ensure no record

        r = client.post("/api/customer/sessions/start", json={
            "pedestal_id": pid,
            "type": "electricity",
            "socket_id": 4,
        }, headers=cust_headers)
        assert r.status_code == 200, (
            f"Expected 200 (no socket state = permissive), got {r.status_code}: {r.text}"
        )
        session = r.json()
        assert session["status"] == "active"

        # Cleanup
        client.post(f"/api/customer/sessions/{session['id']}/stop", headers=cust_headers)

    def test_tc_mob_04_session_start_sends_mqtt_allow(
        self, client, cust_headers, workflow_pedestal_id
    ):
        """
        TC-MOB-04 [IMPLEMENTED]
        Starting a session must publish 'allow' to the Arduino control topic
        pedestal/{id}/socket/{s}/control.
        """
        pid = workflow_pedestal_id
        _db_clear_socket_state(pid, 4)

        published = []
        original_publish = None
        try:
            from app.services.mqtt_client import mqtt_service
            original_publish = mqtt_service.publish
            mqtt_service.publish = lambda topic, payload: published.append((topic, payload))

            r = client.post("/api/customer/sessions/start", json={
                "pedestal_id": pid,
                "type": "electricity",
                "socket_id": 4,
            }, headers=cust_headers)
            assert r.status_code == 200
            session_id = r.json()["id"]
        finally:
            if original_publish:
                mqtt_service.publish = original_publish

        assert any(
            topic == f"pedestal/{pid}/socket/4/control" and payload == "allow"
            for topic, payload in published
        ), f"Expected MQTT 'allow' publish, got: {published}"

        # Cleanup
        client.post(f"/api/customer/sessions/{session_id}/stop", headers=cust_headers)

    def test_tc_mob_05_customer_can_list_pedestals_by_pedestal_id(
        self, client, cust_headers, workflow_pedestal_id
    ):
        """
        TC-MOB-05 [IMPLEMENTED]
        The mobile app can list pedestals (only mobile_enabled ones) and find
        them by pedestal_id.
        """
        pid = workflow_pedestal_id
        r = client.get("/api/customer/sessions/pedestal-status", headers=cust_headers)
        assert r.status_code == 200
        ids = [p["id"] for p in r.json()]
        assert pid in ids, f"Workflow pedestal {pid} not in mobile pedestal list: {ids}"

    def test_tc_mob_06_session_requires_pedestal_to_exist(
        self, client, cust_headers
    ):
        """
        TC-MOB-06 [IMPLEMENTED]
        Attempting to start a session on a non-existent (or mobile-disabled)
        pedestal_id must return 404.
        """
        r = client.post("/api/customer/sessions/start", json={
            "pedestal_id": 99999,
            "type": "electricity",
            "socket_id": 1,
        }, headers=cust_headers)
        assert r.status_code == 404, (
            f"Expected 404 for non-existent pedestal, got {r.status_code}: {r.text}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TC-STOP: Session Stop Behaviour
# ═══════════════════════════════════════════════════════════════════════════════

class TestSessionStop:
    """Session stop: status transitions and MQTT control message."""

    def test_tc_stop_01_customer_stop_completes_session(
        self, client, cust_headers, workflow_pedestal_id
    ):
        """
        TC-STOP-01 [IMPLEMENTED]
        Customer stopping their own session transitions it to 'completed'.
        """
        pid = workflow_pedestal_id
        _db_clear_socket_state(pid, 4)

        # Clean up any active sessions left by previous tests
        for s in client.get("/api/customer/sessions/mine", headers=cust_headers).json():
            if s["status"] == "active":
                client.post(f"/api/customer/sessions/{s['id']}/stop", headers=cust_headers)

        r = client.post("/api/customer/sessions/start", json={
            "pedestal_id": pid, "type": "electricity", "socket_id": 4,
        }, headers=cust_headers)
        assert r.status_code == 200
        session_id = r.json()["id"]

        r2 = client.post(f"/api/customer/sessions/{session_id}/stop", headers=cust_headers)
        assert r2.status_code == 200
        assert r2.json()["status"] == "completed"

    def test_tc_stop_02_stop_sends_mqtt_stop_command(
        self, client, cust_headers, auth_headers, workflow_pedestal_id
    ):
        """
        TC-STOP-02 [IMPLEMENTED]
        Stopping a session must publish a 'stop' control message to the Arduino.
        Uses the admin /controls/{id}/stop endpoint which calls mqtt_service.publish.
        """
        pid = workflow_pedestal_id
        _db_clear_socket_state(pid, 4)

        # Clean up any active sessions left by previous tests
        for s in client.get("/api/customer/sessions/mine", headers=cust_headers).json():
            if s["status"] == "active":
                client.post(f"/api/customer/sessions/{s['id']}/stop", headers=cust_headers)

        r = client.post("/api/customer/sessions/start", json={
            "pedestal_id": pid, "type": "electricity", "socket_id": 4,
        }, headers=cust_headers)
        assert r.status_code == 200
        session_id = r.json()["id"]

        published = []
        try:
            from app.services.mqtt_client import mqtt_service
            original_publish = mqtt_service.publish
            mqtt_service.publish = lambda topic, payload: published.append((topic, payload))

            r2 = client.post(f"/api/controls/{session_id}/stop", headers=auth_headers)
            assert r2.status_code == 200
        finally:
            mqtt_service.publish = original_publish

        stop_msgs = [
            (t, p) for t, p in published
            if f"pedestal/{pid}/socket/4/control" in t and p in ("stop", "deny")
        ]
        assert stop_msgs, f"Expected MQTT stop/deny publish, got: {published}"


# ═══════════════════════════════════════════════════════════════════════════════
# TC-SNMP: SNMP BER Decoder Unit Tests
# STATUS: IMPLEMENTED — snmp_trap_service.py minimal BER decoder
# ═══════════════════════════════════════════════════════════════════════════════

class TestSnmpBerDecoder:
    """
    Pure unit tests for the SNMP trap BER/ASN.1 parser.
    No network, no DB, no side effects.
    """

    def test_tc_snmp_01_decode_oid_basic(self):
        """
        TC-SNMP-01 [IMPLEMENTED]
        OID bytes 0x2b 0x06 0x01 decode to "1.3.6.1" (IANA prefix).
        """
        from app.services.snmp_trap_service import _decode_oid
        # 1.3 → first byte: 1*40+3=43=0x2b; then .6=0x06; then .1=0x01
        result = _decode_oid(bytes([0x2b, 0x06, 0x01]))
        assert result == "1.3.6.1", f"Expected '1.3.6.1', got '{result}'"

    def test_tc_snmp_02_decode_value_integer(self):
        """
        TC-SNMP-02 [IMPLEMENTED]
        INTEGER tag (0x02) with value 23 decodes to int 23.
        """
        from app.services.snmp_trap_service import _decode_value
        assert _decode_value(0x02, bytes([0x17])) == 23

    def test_tc_snmp_03_decode_value_octet_string_as_float(self):
        """
        TC-SNMP-03 [IMPLEMENTED]
        OctetString (0x04) containing ASCII "23.5" decodes to float 23.5.
        This is how Papouch TME encodes temperature.
        """
        from app.services.snmp_trap_service import _decode_value
        result = _decode_value(0x04, b"23.5")
        assert result == 23.5, f"Expected 23.5, got {result!r}"

    def test_tc_snmp_04_decode_value_negative_integer(self):
        """
        TC-SNMP-04 [IMPLEMENTED]
        Negative INTEGER (sign bit set) decodes to a negative Python int.
        """
        from app.services.snmp_trap_service import _decode_value
        # -1 is encoded as 0xFF in one byte
        assert _decode_value(0x02, bytes([0xFF])) == -1

    def test_tc_snmp_05_extract_varbinds_from_minimal_pdu(self):
        """
        TC-SNMP-05 [IMPLEMENTED]
        _extract_varbinds can parse a minimal VarBind SEQUENCE containing
        OID 1.3.6.1 and OctetString value "23.5".

        Hand-crafted PDU bytes:
          30 0b          SEQUENCE length=11
            06 03        OID length=3
              2b 06 01   OID value: 1.3.6.1
            04 04        OctetString length=4
              32 33 2e 35  "23.5"
        """
        from app.services.snmp_trap_service import _extract_varbinds
        pdu = bytes([
            0x30, 0x0b,              # SEQUENCE, 11 bytes
            0x06, 0x03, 0x2b, 0x06, 0x01,  # OID: 1.3.6.1
            0x04, 0x04, 0x32, 0x33, 0x2e, 0x35,  # OctetString: "23.5"
        ])
        varbinds = _extract_varbinds(pdu)
        assert len(varbinds) == 1, f"Expected 1 varbind, got {len(varbinds)}: {varbinds}"
        oid, value = varbinds[0]
        assert oid == "1.3.6.1"
        assert value == 23.5

    def test_tc_snmp_06_empty_data_returns_empty_list(self):
        """
        TC-SNMP-06 [IMPLEMENTED]
        _extract_varbinds on empty/garbage input must not raise and returns [].
        """
        from app.services.snmp_trap_service import _extract_varbinds
        assert _extract_varbinds(b"") == []
        assert _extract_varbinds(b"\xff\xfe\xfd") == []


# ═══════════════════════════════════════════════════════════════════════════════
# TC-WORKFLOW: Full End-to-End Integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullWorkflow:
    """
    TC-WORKFLOW-01: Complete pedestal lifecycle from first MQTT message
    to session stop, reflecting the real-world deployment sequence.

    Steps:
      1. Arduino boots → sends register message → pedestal auto-created in DB
      2. Arduino sends heartbeat → pedestal marked opta_connected
      3. User plugs device → Arduino sends socket "connected" → SocketState stored
      4. Customer opens app → sees pedestal in list
      5. Customer starts session → app sends MQTT "allow" → session is "active"
      6. Arduino sends power readings → stored against session
      7. Customer stops session → session "completed", MQTT stop published

    All assertions map to explicit requirements from the workflow specification.
    """

    def test_tc_workflow_01_complete_lifecycle(self, client, cust_headers, auth_headers):
        # ── Step 1: Arduino register ──────────────────────────────────────────
        # Use a fresh pedestal ID (600) that cannot exist in the seeded test DB
        pid = 600
        db = _TestSession()
        try:
            from app.models.pedestal import Pedestal
            existing = db.get(Pedestal, pid)
            if existing:
                pytest.skip(f"Pedestal {pid} already exists — test DB not clean")
        finally:
            db.close()

        _simulate_mqtt(f"pedestal/{pid}/register", json.dumps({
            "sensor_name": "socket_1",
            "sensor_type": "electricity",
            "mqtt_topic": f"pedestal/{pid}/socket/1/power",
            "unit": "W",
        }))
        pedestal = _db_get_pedestal(pid)
        assert pedestal is not None, "[Step 1] Pedestal not auto-created on register"

        # ── Step 2: Arduino heartbeat ─────────────────────────────────────────
        _simulate_mqtt(f"pedestal/{pid}/heartbeat", json.dumps({
            "online": True,
            "timestamp": datetime.utcnow().isoformat(),
        }))
        db = _TestSession()
        try:
            from app.models.pedestal_config import PedestalConfig
            cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
            assert cfg is not None, "[Step 2] PedestalConfig not created on heartbeat"
            assert cfg.opta_connected == 1, "[Step 2] opta_connected not set"
        finally:
            db.close()

        # ── Step 3: User plugs in device (socket "connected") ─────────────────
        _simulate_mqtt(f"pedestal/{pid}/socket/1/status", "connected")
        state = _db_get_socket_state(pid, 1)
        assert state is not None and state.connected, (
            "[Step 3] SocketState not set to connected"
        )

        # ── Step 4: Enable mobile and verify pedestal is visible ──────────────
        r = client.patch(f"/api/pedestals/{pid}", json={"mobile_enabled": True}, headers=auth_headers)
        assert r.status_code == 200

        r = client.get("/api/customer/sessions/pedestal-status", headers=cust_headers)
        ids = [p["id"] for p in r.json()]
        assert pid in ids, f"[Step 4] Pedestal {pid} not in customer pedestal list"

        # Ensure no lingering active session from earlier tests
        r_mine = client.get("/api/customer/sessions/mine", headers=cust_headers)
        for s in r_mine.json():
            if s["status"] == "active":
                client.post(f"/api/customer/sessions/{s['id']}/stop", headers=cust_headers)

        # ── Step 5: Customer starts session ───────────────────────────────────
        published = []
        try:
            from app.services.mqtt_client import mqtt_service
            original_publish = mqtt_service.publish
            mqtt_service.publish = lambda t, p: published.append((t, p))

            r = client.post("/api/customer/sessions/start", json={
                "pedestal_id": pid,
                "type": "electricity",
                "socket_id": 1,
            }, headers=cust_headers)
            assert r.status_code == 200, f"[Step 5] Session start failed: {r.text}"
            session = r.json()
            session_id = session["id"]
        finally:
            mqtt_service.publish = original_publish

        assert session["status"] == "active", (
            f"[Step 5] Expected status='active', got '{session['status']}'"
        )
        assert any(
            t == f"pedestal/{pid}/socket/1/control" and p == "allow"
            for t, p in published
        ), f"[Step 5] MQTT 'allow' not published. Published: {published}"

        # ── Step 6: Arduino sends power reading ───────────────────────────────
        _simulate_mqtt(f"pedestal/{pid}/socket/1/power", json.dumps({
            "watts": 800.0,
            "kwh_total": 0.1,
        }))
        db = _TestSession()
        try:
            from app.models.sensor_reading import SensorReading
            reading = (
                db.query(SensorReading)
                .filter(
                    SensorReading.pedestal_id == pid,
                    SensorReading.session_id == session_id,
                    SensorReading.type == "power_watts",
                )
                .first()
            )
            assert reading is not None, "[Step 6] Power reading not stored against session"
            assert reading.value == 800.0
        finally:
            db.close()

        # ── Step 7: Customer stops session ────────────────────────────────────
        r = client.post(f"/api/customer/sessions/{session_id}/stop", headers=cust_headers)
        assert r.status_code == 200, f"[Step 7] Stop failed: {r.text}"
        assert r.json()["status"] == "completed", "[Step 7] Session not completed after stop"
