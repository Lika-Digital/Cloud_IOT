"""External-API activity is written to the security log so ERP connections and
attempts are visible in the dashboard log viewer (category "security").

We spy on error_log_service.log_info / log_warning rather than hitting the DB,
so these tests assert the audit call is made with the right category/source.
"""
from __future__ import annotations

from unittest.mock import patch


def _make_erp_user(client, auth_headers, email, pwd):
    client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"email": email, "password": pwd, "role": "api_client"},
    )


def test_erp_auth_success_is_audited(client, auth_headers):
    _make_erp_user(client, auth_headers, "erp-audit@marinaops.io", "erp-secret-999")
    with patch("app.services.error_log_service.log_info") as mock_info:
        r = client.post(
            "/api/auth/service-token",
            json={"email": "erp-audit@marinaops.io", "password": "erp-secret-999"},
        )
        assert r.status_code == 200, r.text
    assert mock_info.called
    cat, source, message = mock_info.call_args.args[:3]
    assert cat == "security"
    assert source == "ext-api/auth"
    assert "erp-audit@marinaops.io" in message
    assert "authenticated" in message


def test_erp_auth_failure_is_audited(client, auth_headers):
    _make_erp_user(client, auth_headers, "erp-audit2@marinaops.io", "erp-secret-000")
    with patch("app.services.error_log_service.log_warning") as mock_warn:
        r = client.post(
            "/api/auth/service-token",
            json={"email": "erp-audit2@marinaops.io", "password": "WRONG-PASSWORD"},
        )
        assert r.status_code == 401
    assert mock_warn.called
    cat, source = mock_warn.call_args.args[:2]
    assert cat == "security"
    assert source == "ext-api/auth"


def test_non_erp_role_service_token_is_audited(client, auth_headers):
    # A human operator account must not be usable as an ERP credential, and the
    # attempt is logged.
    client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"email": "op-tries-api@marinaops.io", "password": "op-secret-123", "role": "monitor"},
    )
    with patch("app.services.error_log_service.log_warning") as mock_warn:
        r = client.post(
            "/api/auth/service-token",
            json={"email": "op-tries-api@marinaops.io", "password": "op-secret-123"},
        )
        assert r.status_code == 403
    assert mock_warn.called
    assert mock_warn.call_args.args[1] == "ext-api/auth"


def test_gateway_invalid_token_is_audited(client):
    # A bad token is rejected before any DB work, and the denial is audited.
    with patch("app.services.error_log_service.log_warning") as mock_warn:
        r = client.get(
            "/api/ext/pedestals",
            headers={"Authorization": "Bearer not-a-valid-jwt"},
        )
        assert r.status_code == 401
    assert mock_warn.called
    cat, source = mock_warn.call_args.args[:2]
    assert cat == "security"
    assert source == "ext-api/gateway"
