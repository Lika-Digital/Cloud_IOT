"""Tests for TOTP 2FA (v3.33 — the authenticator is the only second factor).

Covers setup/verify/disable/status, the mandatory two-step partial-token login,
first-login TOTP enrolment (enroll -> enroll-verify), first-login forced password
change, admin 2FA reset (lost-device recovery), clock-drift tolerance, and the
shared always-on lockout (5 fails -> 15 min). Email OTP was removed.

Uses a dedicated admin user so it never pollutes the shared `admin_token`.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pyotp
import pytest

from app.auth.models import User, OtpStore
from app.auth.password import hash_password
from app.auth.tokens import create_access_token
from tests.backend.conftest import TestUserSession

EMAIL = "totp_admin@test.local"
PW = "totppass1234"
JWT_SECRET = "test-secret-key-for-ci"


@pytest.fixture
def totp_user():
    """Fresh admin user for TOTP tests; cleaned up before and after."""
    def _wipe(db):
        u = db.query(User).filter(User.email == EMAIL).first()
        if u:
            db.query(OtpStore).filter(OtpStore.user_id == u.id).delete()
            db.delete(u)
            db.commit()
    db = TestUserSession()
    _wipe(db)
    u = User(email=EMAIL, password_hash=hash_password(PW), role="admin", is_active=True)
    db.add(u); db.commit(); db.refresh(u)
    uid = u.id
    db.close()
    yield uid
    db = TestUserSession(); _wipe(db); db.close()


def _hdr(uid):
    return {"Authorization": f"Bearer {create_access_token(uid, EMAIL, 'admin')}"}


def _get_user(uid):
    db = TestUserSession()
    try:
        return db.get(User, uid)
    finally:
        db.close()


def _set(uid, **fields):
    db = TestUserSession()
    try:
        u = db.get(User, uid)
        for k, v in fields.items():
            setattr(u, k, v)
        db.commit()
    finally:
        db.close()


def _otp_code(uid):
    db = TestUserSession()
    try:
        row = db.query(OtpStore).filter(OtpStore.user_id == uid).first()
        return row.code if row else None
    finally:
        db.close()


def _login(client):
    r = client.post("/api/auth/login", json={"email": EMAIL, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()


def _setup_totp(client, uid) -> str:
    """Run setup + verify-setup; return the secret (TOTP now enabled)."""
    r = client.post("/api/auth/totp/setup", headers=_hdr(uid))
    assert r.status_code == 200, r.text
    secret = r.json()["secret"]
    code = pyotp.TOTP(secret).now()
    rv = client.post("/api/auth/totp/verify-setup", json={"code": code}, headers=_hdr(uid))
    assert rv.status_code == 200, rv.text
    return secret


# ── setup ─────────────────────────────────────────────────────────────────────

def test_setup_returns_secret_and_valid_base64_png_qr(client, totp_user):
    r = client.post("/api/auth/totp/setup", headers=_hdr(totp_user))
    assert r.status_code == 200
    body = r.json()
    assert len(body["secret"]) >= 16
    raw = base64.b64decode(body["qr_code"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"   # PNG magic
    assert "Marina%20IoT" in body["provisioning_uri"] or "Marina IoT" in body["provisioning_uri"]


def test_setup_generates_new_secret_each_call(client, totp_user):
    s1 = client.post("/api/auth/totp/setup", headers=_hdr(totp_user)).json()["secret"]
    s2 = client.post("/api/auth/totp/setup", headers=_hdr(totp_user)).json()["secret"]
    assert s1 != s2


def test_verify_setup_accepts_correct_code_enables(client, totp_user):
    _setup_totp(client, totp_user)
    assert _get_user(totp_user).totp_enabled is True
    assert _get_user(totp_user).totp_verified_at is not None


def test_verify_setup_rejects_wrong_code(client, totp_user):
    client.post("/api/auth/totp/setup", headers=_hdr(totp_user))
    r = client.post("/api/auth/totp/verify-setup", json={"code": "000000"}, headers=_hdr(totp_user))
    assert r.status_code == 400
    assert _get_user(totp_user).totp_enabled is False


def test_status_reflects_state(client, totp_user):
    r0 = client.get("/api/auth/totp/status", headers=_hdr(totp_user))
    assert r0.json()["totp_enabled"] is False
    _setup_totp(client, totp_user)
    r1 = client.get("/api/auth/totp/status", headers=_hdr(totp_user))
    assert r1.json()["totp_enabled"] is True and r1.json()["totp_verified_at"]


# ── login: mandatory 2FA, partial token ───────────────────────────────────────

def test_login_no_totp_returns_flags_no_jwt_no_otp(client, totp_user):
    """v3.33 — login returns the partial token + next-step flags; no email OTP,
    no JWT. A fresh user has totp_enabled False so they enrol next."""
    body = _login(client)
    assert body["partial_token"]
    assert body["totp_enabled"] is False
    assert body["must_change_password"] is False   # this fixture user wasn't admin-created
    assert "access_token" not in body              # never a JWT here
    assert "otp_sent" not in body and "method" not in body  # OTP removed


def test_login_totp_enabled_sets_flag(client, totp_user):
    _setup_totp(client, totp_user)
    body = _login(client)
    assert body["totp_enabled"] is True
    assert body["partial_token"]


def test_partial_token_cannot_access_protected_endpoint(client, totp_user):
    partial = _login(client)["partial_token"]
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {partial}"})
    assert r.status_code in (401, 403)


# ── TOTP login ─────────────────────────────────────────────────────────────────

def test_totp_login_valid_returns_jwt(client, totp_user):
    secret = _setup_totp(client, totp_user)
    partial = _login(client)["partial_token"]
    r = client.post("/api/auth/totp/login",
                    json={"partial_token": partial, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    assert r.json()["access_token"] and r.json()["role"] == "admin"


def test_totp_login_clock_drift_one_window_tolerated(client, totp_user):
    secret = _setup_totp(client, totp_user)
    partial = _login(client)["partial_token"]
    drift_code = pyotp.TOTP(secret).at(datetime.now() - timedelta(seconds=30))
    r = client.post("/api/auth/totp/login", json={"partial_token": partial, "code": drift_code})
    assert r.status_code == 200, r.text


def test_totp_login_rejects_invalid_code(client, totp_user):
    _setup_totp(client, totp_user)
    partial = _login(client)["partial_token"]
    r = client.post("/api/auth/totp/login", json={"partial_token": partial, "code": "000000"})
    assert r.status_code == 401


def test_totp_login_rejects_expired_partial_token(client, totp_user):
    secret = _setup_totp(client, totp_user)
    expired = pyjwt.encode(
        {"sub": str(totp_user), "email": EMAIL, "role": "totp_pending", "totp_pending": True,
         "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        JWT_SECRET, algorithm="HS256")
    r = client.post("/api/auth/totp/login",
                    json={"partial_token": expired, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 401


# ── first-login TOTP enrolment (partial token) ─────────────────────────────────

def test_enroll_then_verify_returns_jwt_and_enables(client, totp_user):
    """v3.33 — a user without TOTP enrols during login: enroll (QR) →
    enroll-verify (live code) → JWT, with TOTP now enabled."""
    partial = _login(client)["partial_token"]
    en = client.post("/api/auth/totp/enroll", json={"partial_token": partial})
    assert en.status_code == 200, en.text
    secret = en.json()["secret"]
    assert len(secret) >= 16
    r = client.post("/api/auth/totp/enroll-verify",
                    json={"partial_token": partial, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    assert r.json()["access_token"] and r.json()["role"] == "admin"
    assert _get_user(totp_user).totp_enabled is True


def test_enroll_verify_rejects_wrong_code(client, totp_user):
    partial = _login(client)["partial_token"]
    client.post("/api/auth/totp/enroll", json={"partial_token": partial})
    r = client.post("/api/auth/totp/enroll-verify",
                    json={"partial_token": partial, "code": "000000"})
    assert r.status_code == 400
    assert _get_user(totp_user).totp_enabled is False


def test_enroll_requires_valid_partial_token(client, totp_user):
    r = client.post("/api/auth/totp/enroll", json={"partial_token": "not-a-token"})
    assert r.status_code == 401


# ── first-login forced password change ─────────────────────────────────────────

def test_first_password_required_then_clears(client, totp_user):
    _set(totp_user, must_change_password=True)
    body = _login(client)
    assert body["must_change_password"] is True
    partial = body["partial_token"]
    r = client.post("/api/auth/first-password",
                    json={"partial_token": partial, "new_password": "brandnew9999"})
    assert r.status_code == 200, r.text
    assert _get_user(totp_user).must_change_password is False
    # The new password now logs in (and no longer demands a change).
    nb = client.post("/api/auth/login", json={"email": EMAIL, "password": "brandnew9999"}).json()
    assert nb["must_change_password"] is False


def test_first_password_rejects_same_password(client, totp_user):
    _set(totp_user, must_change_password=True)
    partial = _login(client)["partial_token"]
    r = client.post("/api/auth/first-password",
                    json={"partial_token": partial, "new_password": PW})
    assert r.status_code == 400


def test_first_password_400_when_not_required(client, totp_user):
    partial = _login(client)["partial_token"]   # must_change_password False
    r = client.post("/api/auth/first-password",
                    json={"partial_token": partial, "new_password": "whatever12345"})
    assert r.status_code == 400


# ── admin reset 2FA (recovery) ─────────────────────────────────────────────────

def test_admin_reset_2fa_clears_totp(client, totp_user):
    _setup_totp(client, totp_user)
    assert _get_user(totp_user).totp_enabled is True
    r = client.post(f"/api/auth/users/{totp_user}/reset-2fa", headers=_hdr(totp_user))
    assert r.status_code == 200, r.text
    u = _get_user(totp_user)
    assert u.totp_enabled is False and u.totp_secret is None


def test_admin_reset_2fa_requires_admin(client, totp_user):
    r = client.post(f"/api/auth/users/{totp_user}/reset-2fa")
    assert r.status_code in (401, 403)


# ── lockout (always-on) ────────────────────────────────────────────────────────

def test_lockout_after_5_failed_totp(client, totp_user):
    _setup_totp(client, totp_user)
    partial = _login(client)["partial_token"]
    codes = ["000000", "111111", "222222", "333333", "444444"]
    statuses = [client.post("/api/auth/totp/login",
                            json={"partial_token": partial, "code": c}).status_code for c in codes]
    assert statuses[:4] == [401, 401, 401, 401]
    assert statuses[4] == 429                              # 5th failure locks


def test_unlock_after_window(client, totp_user):
    secret = _setup_totp(client, totp_user)
    _set(totp_user, totp_locked_until=datetime.utcnow() - timedelta(minutes=1), totp_failed_attempts=0)
    partial = _login(client)["partial_token"]
    r = client.post("/api/auth/totp/login",
                    json={"partial_token": partial, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200                            # lock expired -> allowed


# ── disable ──────────────────────────────────────────────────────────────────

def test_disable_requires_password_and_code(client, totp_user):
    secret = _setup_totp(client, totp_user)
    r = client.post("/api/auth/totp/disable",
                    json={"password": PW, "code": pyotp.TOTP(secret).now()}, headers=_hdr(totp_user))
    assert r.status_code == 200 and r.json()["totp_enabled"] is False
    u = _get_user(totp_user)
    assert u.totp_enabled is False and u.totp_secret is None


def test_disable_rejects_wrong_password(client, totp_user):
    secret = _setup_totp(client, totp_user)
    r = client.post("/api/auth/totp/disable",
                    json={"password": "wrong", "code": pyotp.TOTP(secret).now()}, headers=_hdr(totp_user))
    assert r.status_code == 400
    assert _get_user(totp_user).totp_enabled is True


def test_disable_rejects_wrong_code(client, totp_user):
    _setup_totp(client, totp_user)
    r = client.post("/api/auth/totp/disable",
                    json={"password": PW, "code": "000000"}, headers=_hdr(totp_user))
    assert r.status_code == 400
    assert _get_user(totp_user).totp_enabled is True
