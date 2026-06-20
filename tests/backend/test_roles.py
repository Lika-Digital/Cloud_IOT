"""v3.34 — three-tier operator roles.

admin            — everything (incl. System Health, Settings, API Gateway).
monitor_control  — control/configure every NON-admin section; 403 on the three.
monitor          — read every non-admin section; 403 on any write + the three.

These tests assert the dependency gate only (require_admin / require_control /
require_any_role). For "allowed" cases we assert the status is NOT 403 — the
handler may still 404/200 depending on data — which is exactly what the role
gate guarantees. Valid bodies are sent to write endpoints so a denied role
fails with 403, not 422.
"""
from __future__ import annotations

import pytest

from app.auth.models import User
from app.auth.password import hash_password
from app.auth.tokens import create_access_token
from tests.backend.conftest import TestUserSession


def _ensure_user(email: str, role: str) -> int:
    db = TestUserSession()
    try:
        u = db.query(User).filter(User.email == email).first()
        if not u:
            u = User(email=email, password_hash=hash_password("rolepass1234"),
                     role=role, is_active=True)
            db.add(u); db.commit(); db.refresh(u)
        elif u.role != role:
            u.role = role; db.commit()
        return u.id
    finally:
        db.close()


def _hdr(uid: int, email: str, role: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(uid, email, role)}"}


@pytest.fixture(scope="module")
def headers():
    a = _ensure_user("role_admin@test.local", "admin")
    mc = _ensure_user("role_mc@test.local", "monitor_control")
    m = _ensure_user("role_monitor@test.local", "monitor")
    return {
        "admin": _hdr(a, "role_admin@test.local", "admin"),
        "monitor_control": _hdr(mc, "role_mc@test.local", "monitor_control"),
        "monitor": _hdr(m, "role_monitor@test.local", "monitor"),
    }


# Representative endpoints per gate.
ADMIN_ONLY = [
    ("GET", "/api/system/health", None),
    ("GET", "/api/admin/settings/smtp", None),
    ("GET", "/api/admin/ext-api/config", None),
]
CONTROL_WRITE = [
    ("PUT", "/api/billing/config", {"kwh_price_eur": 0.5, "liter_price_eur": 0.01}),
    ("POST", "/api/pedestals/1/sockets/1/breaker/reset", {}),
]
SHARED_READ = [
    ("GET", "/api/billing/config", None),
    ("GET", "/api/pedestals/1/sockets/1/breaker/status", None),
]


def _call(client, method, path, body, hdr):
    return client.request(method, path, json=body, headers=hdr)


# ── admin-only sections (System Health / Settings / API Gateway) ───────────────

@pytest.mark.parametrize("method,path,body", ADMIN_ONLY)
def test_admin_sections_block_non_admin(client, headers, method, path, body):
    assert _call(client, method, path, body, headers["monitor_control"]).status_code == 403
    assert _call(client, method, path, body, headers["monitor"]).status_code == 403


@pytest.mark.parametrize("method,path,body", ADMIN_ONLY)
def test_admin_sections_allow_admin(client, headers, method, path, body):
    assert _call(client, method, path, body, headers["admin"]).status_code != 403


# ── control/write endpoints (non-admin sections) ──────────────────────────────

@pytest.mark.parametrize("method,path,body", CONTROL_WRITE)
def test_control_writes_block_monitor(client, headers, method, path, body):
    assert _call(client, method, path, body, headers["monitor"]).status_code == 403


@pytest.mark.parametrize("method,path,body", CONTROL_WRITE)
def test_control_writes_allow_admin_and_monitor_control(client, headers, method, path, body):
    assert _call(client, method, path, body, headers["admin"]).status_code != 403
    assert _call(client, method, path, body, headers["monitor_control"]).status_code != 403


# ── shared reads (every operator, incl. read-only monitor) ─────────────────────

@pytest.mark.parametrize("method,path,body", SHARED_READ)
def test_shared_reads_allow_all_roles(client, headers, method, path, body):
    for role in ("admin", "monitor_control", "monitor"):
        assert _call(client, method, path, body, headers[role]).status_code != 403


# ── user management accepts the new role ───────────────────────────────────────

def test_create_user_accepts_monitor_control(client, auth_headers):
    import uuid
    email = f"mc_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/users", headers=auth_headers,
                    json={"email": email, "password": "newpass1234", "role": "monitor_control"})
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "monitor_control"


def test_create_user_rejects_unknown_role(client, auth_headers):
    r = client.post("/api/auth/users", headers=auth_headers,
                    json={"email": "bad_role@example.com", "password": "newpass1234", "role": "superuser"})
    assert r.status_code in (400, 422)
