"""Tests for v3.19 TOTP 2FA + OTP fallback.

Covers setup/verify/disable/status, the mandatory two-step partial-token login
(TOTP and OTP paths), clock-drift tolerance, single-use + expiry, the shared
always-on lockout (5 fails -> 15 min), and partial-token endpoint isolation.

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

def test_login_no_totp_returns_partial_token_and_autosends_otp(client, totp_user):
    body = _login(client)
    assert body["totp_required"] is False
    assert body["otp_available"] is True
    assert body["partial_token"]
    assert body["otp_sent"] is True          # D2 auto-send
    assert body["method"] in ("log", "email")
    assert "access_token" not in body         # D1 — never a JWT here


def test_login_totp_enabled_requires_totp(client, totp_user):
    _setup_totp(client, totp_user)
    body = _login(client)
    assert body["totp_required"] is True
    assert body["otp_available"] is True
    assert body["partial_token"]
    assert body["otp_sent"] is False          # TOTP user: OTP on demand only


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


# ── OTP fallback ────────────────────────────────────────────────────────────────

def test_otp_request_requires_valid_partial_token(client, totp_user):
    r = client.post("/api/auth/otp/request", json={"partial_token": "not-a-token"})
    assert r.status_code == 401


def test_otp_request_writes_code_and_otp_login_returns_jwt(client, totp_user):
    _setup_totp(client, totp_user)            # TOTP enabled — user picks OTP fallback
    partial = _login(client)["partial_token"]
    rq = client.post("/api/auth/otp/request", json={"partial_token": partial})
    assert rq.status_code == 200 and rq.json()["otp_sent"] is True
    code = _otp_code(totp_user)
    assert code and len(code) == 6
    r = client.post("/api/auth/otp/login", json={"partial_token": partial, "code": code})
    assert r.status_code == 200 and r.json()["access_token"]


def test_otp_single_use(client, totp_user):
    partial = _login(client)["partial_token"]           # no-TOTP path already sent an OTP
    code = _otp_code(totp_user)
    r1 = client.post("/api/auth/otp/login", json={"partial_token": partial, "code": code})
    assert r1.status_code == 200
    r2 = client.post("/api/auth/otp/login", json={"partial_token": partial, "code": code})
    assert r2.status_code == 401                          # consumed


def test_otp_expired_rejected(client, totp_user):
    partial = _login(client)["partial_token"]
    # Force the just-issued OTP to be expired.
    db = TestUserSession()
    row = db.query(OtpStore).filter(OtpStore.user_id == totp_user).first()
    code = row.code
    row.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit(); db.close()
    r = client.post("/api/auth/otp/login", json={"partial_token": partial, "code": code})
    assert r.status_code == 401


# ── lockout (always-on, shared) ────────────────────────────────────────────────

def test_lockout_after_5_failed_totp(client, totp_user):
    _setup_totp(client, totp_user)
    partial = _login(client)["partial_token"]
    codes = ["000000", "111111", "222222", "333333", "444444"]
    statuses = [client.post("/api/auth/totp/login",
                            json={"partial_token": partial, "code": c}).status_code for c in codes]
    assert statuses[:4] == [401, 401, 401, 401]
    assert statuses[4] == 429                              # 5th failure locks


def test_lockout_after_5_failed_otp(client, totp_user):
    partial = _login(client)["partial_token"]
    statuses = [client.post("/api/auth/otp/login",
                            json={"partial_token": partial, "code": c}).status_code
                for c in ["000000", "111111", "222222", "333333", "444444"]]
    assert statuses[4] == 429


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
