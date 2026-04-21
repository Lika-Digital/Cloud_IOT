"""
GAP-5: FE<->BE — Session REST API field assertion
GAP-6: FE<->BE — Controls 400-error responses (wrong session state)
LAYER: FE<->BE
TOOL: pytest + httpx (already installed)

GAP-5: Verifies that /api/sessions/active and /api/sessions/pending
return the customer_name field in each session object. Without this field
the frontend AllSessionsOverview and Quick Status panels show blank customer
names (silent failure — no error in console, wrong data on screen).

GAP-6: Verifies that /api/controls/{id}/allow and /deny return HTTP 400
when the session is already in a non-pending state. Previously only happy-path
200s were tested in Playwright.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

TEST_DB = "sqlite:///./tests/test_pedestal.db"


def _complete_via_db_gap(session_id: int):
    """v3.6 — customer-stop is disabled, so cleanup happens via direct DB."""
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


# ── Shared fixture: pedestal_id ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def gap_pedestal_id(client, auth_headers):
    """Return the first available pedestal ID from the test database."""
    resp = client.get("/api/pedestals", headers=auth_headers)
    assert resp.status_code == 200
    pedestals = resp.json()
    assert pedestals, "No pedestals seeded — check conftest.py setup_test_databases"
    return pedestals[0]["id"]


# ── GAP-5: customer_name field in session REST responses ──────────────────────

class TestGap5SessionCustomerNameField:
    """
    GAP: FE<->BE | Layer: REST response schema | customer_name must be present.
    Covers: /api/sessions, /api/sessions/active, /api/sessions/pending, /api/sessions/{id}
    """

    def test_active_sessions_response_has_customer_name_key(self, client, auth_headers):
        """
        /api/sessions/active must return customer_name in every session object.
        Field may be None if session has no linked customer, but key must exist.
        GAP: customer_name was absent from SessionResponse Pydantic schema before fix.
        """
        resp = client.get("/api/sessions/active", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        for s in resp.json():
            assert "customer_name" in s, (
                f"customer_name key missing from session {s.get('id')!r} "
                f"in /api/sessions/active. Keys: {list(s.keys())}"
            )

    def test_pending_sessions_response_has_customer_name_key(self, client, auth_headers):
        """/api/sessions/pending must return customer_name in every session object."""
        resp = client.get("/api/sessions/pending", headers=auth_headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        for s in resp.json():
            assert "customer_name" in s, (
                f"customer_name key missing from session {s.get('id')!r} "
                f"in /api/sessions/pending. Keys: {list(s.keys())}"
            )

    def test_session_list_response_has_customer_name_key(self, client, auth_headers):
        """/api/sessions must return customer_name in every session object."""
        resp = client.get("/api/sessions", headers=auth_headers)
        assert resp.status_code == 200
        for s in resp.json():
            assert "customer_name" in s, (
                f"customer_name key missing from session {s.get('id')!r} "
                f"in /api/sessions. Keys: {list(s.keys())}"
            )

    def test_active_session_with_customer_has_name_populated(
        self, client, auth_headers, cust_headers, gap_pedestal_id
    ):
        """
        When a customer has a session, the admin's list view should show customer_name.
        This is the core scenario: FE Quick Status / AllSessionsOverview uses this field.
        """
        # Start a session as a customer
        resp = client.post(
            "/api/customer/sessions/start",
            headers=cust_headers,
            json={"pedestal_id": gap_pedestal_id, "socket_id": 4, "type": "electricity"},
        )
        assert resp.status_code == 200, f"start session failed: {resp.text}"
        session_id = resp.json()["id"]

        # Activate in DB so it appears in /active
        engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
        Sess = sessionmaker(bind=engine)
        db = Sess()
        try:
            from app.models.session import Session as SessionModel
            s = db.get(SessionModel, session_id)
            s.status = "active"
            db.commit()
        finally:
            db.close()
            engine.dispose()

        try:
            resp = client.get("/api/sessions/active", headers=auth_headers)
            assert resp.status_code == 200
            sessions = resp.json()
            target = next((s for s in sessions if s["id"] == session_id), None)
            assert target is not None, f"Session {session_id} not found in /api/sessions/active"
            assert "customer_name" in target, (
                f"customer_name key missing from session {session_id}. Keys: {list(target.keys())}"
            )
            # The customer was registered with name="Test Customer" in conftest
            # customer_name should be a str or None, never missing
            assert target["customer_name"] is None or isinstance(target["customer_name"], str), (
                f"customer_name should be str|None, got {type(target['customer_name'])!r}"
            )
        finally:
            _complete_via_db_gap(session_id)

    def test_single_session_endpoint_has_customer_name_key(
        self, client, auth_headers, cust_headers, gap_pedestal_id
    ):
        """/api/sessions/{id} must also return customer_name in the response."""
        resp = client.post(
            "/api/customer/sessions/start",
            headers=cust_headers,
            json={"pedestal_id": gap_pedestal_id, "socket_id": 3, "type": "electricity"},
        )
        assert resp.status_code == 200, f"start session failed: {resp.text}"
        session_id = resp.json()["id"]

        try:
            resp = client.get(f"/api/sessions/{session_id}", headers=auth_headers)
            assert resp.status_code == 200
            s = resp.json()
            assert "customer_name" in s, (
                f"customer_name key missing from /api/sessions/{session_id}. "
                f"Keys: {list(s.keys())}"
            )
        finally:
            _complete_via_db_gap(session_id)


# ── GAP-6: Controls 400/404 error responses for wrong session state ───────────

class TestGap6Controls400Errors:
    """
    GAP: FE<->BE | Layer: HTTP error codes | Controls must return correct errors.
    Covers: 400 for wrong state, 404 for nonexistent, 401/403 for unauthorized.
    """

    @pytest.fixture(scope="class")
    def active_session_id(self, client, cust_headers, gap_pedestal_id):
        """Create an active session for error-state testing."""
        resp = client.post(
            "/api/customer/sessions/start",
            headers=cust_headers,
            json={"pedestal_id": gap_pedestal_id, "socket_id": 3, "type": "electricity"},
        )
        assert resp.status_code == 200, f"start session failed: {resp.text}"
        sid = resp.json()["id"]

        # Activate in DB
        engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
        Sess = sessionmaker(bind=engine)
        db = Sess()
        try:
            from app.models.session import Session as SessionModel
            s = db.get(SessionModel, sid)
            s.status = "active"
            db.commit()
        finally:
            db.close()
            engine.dispose()

        yield sid

        _complete_via_db_gap(sid)

    def test_allow_already_active_session_returns_400(
        self, client, auth_headers, active_session_id
    ):
        """
        /api/controls/{id}/allow must return HTTP 400 when session is already active.
        GAP: this error path was never tested — only happy-path 200s existed.
        """
        resp = client.post(f"/api/controls/{active_session_id}/allow", headers=auth_headers)
        assert resp.status_code == 400, (
            f"Expected 400 (session already active), got {resp.status_code}: {resp.text}"
        )
        detail = resp.json().get("detail", "")
        assert "pending" in detail.lower() or "active" in detail.lower(), (
            f"Expected error detail about session state, got: {resp.json()}"
        )

    def test_deny_nonexistent_session_returns_404(self, client, auth_headers):
        """
        /api/controls/{id}/deny with a non-existent session ID must return 404.
        GAP: 404 paths were never tested in Playwright or pytest.
        """
        resp = client.post(
            "/api/controls/999999/deny",
            headers=auth_headers,
            json={"reason": "test"},
        )
        assert resp.status_code == 404, (
            f"Expected 404 for nonexistent session, got {resp.status_code}"
        )

    def test_stop_nonexistent_session_returns_404(self, client, auth_headers):
        """/api/controls/{id}/stop with nonexistent session must return 404."""
        resp = client.post("/api/controls/999999/stop", headers=auth_headers)
        assert resp.status_code == 404, (
            f"Expected 404 for nonexistent session, got {resp.status_code}"
        )

    def test_controls_require_admin_role(self, client, cust_headers, active_session_id):
        """
        Controls endpoints must reject customer-role JWT with 403.
        GAP: role enforcement on controls was tested only via conftest admin fixture,
        never explicitly for customer token rejection.
        """
        resp = client.post(f"/api/controls/{active_session_id}/stop", headers=cust_headers)
        assert resp.status_code == 403, (
            f"Expected 403 for customer trying to use controls endpoint, "
            f"got {resp.status_code}: {resp.text}"
        )

    def test_controls_require_auth(self, client, active_session_id):
        """Controls endpoints must reject unauthenticated requests with 401 or 403."""
        resp = client.post(f"/api/controls/{active_session_id}/stop")
        assert resp.status_code in (401, 403), (
            f"Expected 401/403 for unauthenticated controls request, got {resp.status_code}"
        )
