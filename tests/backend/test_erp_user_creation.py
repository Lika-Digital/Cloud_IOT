"""ERP User (api_client) creation via the operator Add User endpoint.

An admin can create an api_client service account through POST /api/auth/users
with role="api_client". Unlike human operators it skips the forced
password-change + TOTP enrolment, and it authenticates via
POST /api/auth/service-token with the admin-set password.
"""
from __future__ import annotations

from app.auth.models import User
from tests.backend.conftest import TestUserSession


def _get_user(email: str):
    db = TestUserSession()
    try:
        return db.query(User).filter(User.email == email).first()
    finally:
        db.close()


def test_admin_creates_erp_user(client, auth_headers):
    email = "erp-svc@marinaops.io"
    r = client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"email": email, "password": "erp-secret-123", "role": "api_client"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "api_client"
    u = _get_user(email)
    assert u is not None and u.role == "api_client"
    # ERP accounts skip the operator forced-password-change / TOTP flow
    assert u.must_change_password is False


def test_erp_user_can_get_service_token(client, auth_headers):
    email, pwd = "erp-svc2@marinaops.io", "erp-secret-456"
    r = client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"email": email, "password": pwd, "role": "api_client"},
    )
    assert r.status_code == 201, r.text
    # The ERP account logs in directly (no OTP) for a bearer token.
    r2 = client.post("/api/auth/service-token", json={"email": email, "password": pwd})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["role"] == "api_client"
    assert body["access_token"]


def test_operator_still_requires_password_change(client, auth_headers):
    email = "op-monitor@marinaops.io"
    r = client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"email": email, "password": "op-secret-789", "role": "monitor"},
    )
    assert r.status_code == 201, r.text
    u = _get_user(email)
    # Unchanged behaviour for human operators.
    assert u.must_change_password is True


def test_invalid_role_rejected(client, auth_headers):
    r = client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"email": "bad-role@marinaops.io", "password": "whatever12", "role": "superuser"},
    )
    assert r.status_code == 422  # schema pattern rejects before the handler
