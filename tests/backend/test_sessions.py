"""Customer session lifecycle: pedestal status → start → list → stop."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB = "sqlite:///./tests/test_pedestal.db"


def _complete_session_direct(session_id: int) -> None:
    """Mark a session `completed` via direct DB write. Used as a cleanup step
    in tests — replaces `POST /api/customer/sessions/{id}/stop` since the
    customer-stop endpoint is intentionally locked down (403) in v3.6."""
    engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
    S = sessionmaker(bind=engine)
    db = S()
    try:
        from app.models.session import Session as SessionModel
        row = db.get(SessionModel, session_id)
        if row:
            row.status = "completed"
            db.commit()
    finally:
        db.close()
        engine.dispose()


@pytest.fixture(scope="module")
def active_session_id(client, cust_headers):
    """Start a session, activate it directly in the test DB, return its id."""
    r = client.get("/api/customer/sessions/pedestal-status", headers=cust_headers)
    assert r.status_code == 200
    pedestals = r.json()
    assert len(pedestals) > 0, "No mobile-enabled pedestals in test DB"

    pedestal_id = pedestals[0]["id"]
    r2 = client.post("/api/customer/sessions/start", json={
        "pedestal_id": pedestal_id,
        "type": "electricity",
        "socket_id": 1,
    }, headers=cust_headers)
    assert r2.status_code == 200
    session_id = r2.json()["id"]

    # Activate the session directly in the DB so it can be stopped
    engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        from app.models.session import Session as SessionModel
        s = db.get(SessionModel, session_id)
        s.status = "active"
        db.commit()
    finally:
        db.close()
        engine.dispose()

    return session_id


def test_pedestal_status_requires_auth(client):
    r = client.get("/api/customer/sessions/pedestal-status")
    assert r.status_code in (401, 403)


def test_pedestal_status_returns_list(client, cust_headers):
    r = client.get("/api/customer/sessions/pedestal-status", headers=cust_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_start_session(active_session_id):
    """Fixture already asserts 200; confirm id is positive int."""
    assert isinstance(active_session_id, int)
    assert active_session_id > 0


def test_start_duplicate_session_rejected(client, cust_headers, active_session_id):
    """Starting a second session while one is active should fail."""
    r = client.get("/api/customer/sessions/pedestal-status", headers=cust_headers)
    pedestal_id = r.json()[0]["id"]
    r2 = client.post("/api/customer/sessions/start", json={
        "pedestal_id": pedestal_id,
        "type": "electricity",
        "socket_id": 2,
    }, headers=cust_headers)
    assert r2.status_code in (400, 409)


def test_list_my_sessions(client, cust_headers, active_session_id):
    r = client.get("/api/customer/sessions/mine", headers=cust_headers)
    assert r.status_code == 200
    sessions = r.json()
    assert any(s["id"] == active_session_id for s in sessions)


def test_stop_session(client, cust_headers, active_session_id):
    """v3.6 — customer stop is disabled (monitoring-only model).

    Mobile clients can no longer end their session via API; they must unplug
    the cable (firmware emits UserPluggedOut → backend completes the session)
    or wait for the operator to stop it from the dashboard.
    """
    r = client.post(f"/api/customer/sessions/{active_session_id}/stop",
                    headers=cust_headers)
    assert r.status_code == 403
    assert "customer stop is disabled" in r.json()["detail"].lower()

    # Leftover active session would block subsequent "one session per customer"
    # checks in later tests — tidy up via direct DB write (admin stop path is
    # tested separately in test_operator_stop_sends_completed).
    _complete_session_direct(active_session_id)


def test_admin_list_sessions(client, auth_headers):
    r = client.get("/api/sessions/", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_admin_list_sessions_filter_status(client, auth_headers):
    r = client.get("/api/sessions/?status=completed", headers=auth_headers)
    assert r.status_code == 200
    for s in r.json():
        assert s["status"] == "completed"


# ─── Auto-start: sessions must activate immediately ───────────────────────────

def test_session_starts_as_active(client, cust_headers):
    """
    Key functional requirement: customer sessions auto-activate without
    operator approval. The session returned from /start must have
    status='active', never 'pending'.
    """
    r = client.get("/api/customer/sessions/pedestal-status", headers=cust_headers)
    assert r.status_code == 200
    pedestals = r.json()
    assert len(pedestals) > 0, "No mobile-enabled pedestal for auto-start test"

    pedestal_id = pedestals[0]["id"]
    # Use socket 3 to avoid conflict with session fixture (which uses socket 1 & 2)
    r2 = client.post("/api/customer/sessions/start", json={
        "pedestal_id": pedestal_id,
        "type": "electricity",
        "socket_id": 3,
    }, headers=cust_headers)
    assert r2.status_code == 200
    session = r2.json()
    assert session["status"] == "active", (
        f"Expected status='active' (auto-start), got '{session['status']}'"
    )

    _complete_session_direct(session["id"])


def test_session_invalid_socket_id(client, cust_headers):
    """socket_id must be 1–4 for electricity sessions."""
    r = client.get("/api/customer/sessions/pedestal-status", headers=cust_headers)
    pedestal_id = r.json()[0]["id"]
    r2 = client.post("/api/customer/sessions/start", json={
        "pedestal_id": pedestal_id,
        "type": "electricity",
        "socket_id": 99,
    }, headers=cust_headers)
    assert r2.status_code == 422


def test_water_session_no_socket_id_required(client, cust_headers):
    """Water sessions don't need a socket_id and also auto-start as active."""
    r = client.get("/api/customer/sessions/pedestal-status", headers=cust_headers)
    pedestal_id = r.json()[0]["id"]
    r2 = client.post("/api/customer/sessions/start", json={
        "pedestal_id": pedestal_id,
        "type": "water",
    }, headers=cust_headers)
    assert r2.status_code == 200
    session = r2.json()
    assert session["status"] == "active"
    assert session["socket_id"] is None

    _complete_session_direct(session["id"])


def test_operator_stop_sends_completed(client, auth_headers, cust_headers):
    """
    Operator (admin) stopping an active session via /api/controls/{id}/stop
    returns status='completed'.
    """
    # Start a session as customer
    r = client.get("/api/customer/sessions/pedestal-status", headers=cust_headers)
    pedestal_id = r.json()[0]["id"]
    r2 = client.post("/api/customer/sessions/start", json={
        "pedestal_id": pedestal_id,
        "type": "electricity",
        "socket_id": 4,
    }, headers=cust_headers)
    assert r2.status_code == 200
    session_id = r2.json()["id"]

    # Operator stops it
    r3 = client.post(f"/api/controls/{session_id}/stop", headers=auth_headers)
    assert r3.status_code == 200
    assert r3.json()["status"] == "completed"
