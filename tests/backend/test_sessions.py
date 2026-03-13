"""Customer session lifecycle: pedestal status → start → list → stop."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB = "sqlite:///./tests/test_pedestal.db"


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
    r = client.post(f"/api/customer/sessions/{active_session_id}/stop",
                    headers=cust_headers)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"


def test_admin_list_sessions(client, auth_headers):
    r = client.get("/api/sessions/", headers=auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_admin_list_sessions_filter_status(client, auth_headers):
    r = client.get("/api/sessions/?status=completed", headers=auth_headers)
    assert r.status_code == 200
    for s in r.json():
        assert s["status"] == "completed"
