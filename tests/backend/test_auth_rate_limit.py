"""
Regression guard for C-5: auth endpoints must reject callers who hammer them.

slowapi is disabled in the default test environment (to keep unrelated tests
fast). This file flips the limiter on for just these cases so we prove the
wiring works, then flips it off again on teardown.
"""
from __future__ import annotations
import pytest


@pytest.fixture
def enable_limiter():
    from app.ratelimit import limiter
    prev = limiter.enabled
    limiter.enabled = True
    limiter.reset()
    yield limiter
    limiter.enabled = prev
    limiter.reset()


def test_totp_login_is_rate_limited(client, enable_limiter):
    """v3.33 — email OTP was removed; the second-factor completion endpoint is
    /totp/login (limit 10/minute). The 11th POST within a minute must be 429."""
    payload = {"partial_token": "not-a-real-token", "code": "000000"}
    statuses = []
    for _ in range(12):
        r = client.post("/api/auth/totp/login", json=payload)
        statuses.append(r.status_code)
    assert 429 in statuses, f"Expected rate-limit trip on /totp/login, got statuses: {statuses}"


def test_login_rate_limited_after_burst(client, enable_limiter):
    """Eleven /login attempts in 1 minute — the 11th must be 429 (limit is 10/min)."""
    payload = {"email": "rate-test@test.local", "password": "wrong"}
    statuses = []
    for _ in range(12):
        r = client.post("/api/auth/login", json=payload)
        statuses.append(r.status_code)
    assert 429 in statuses, f"Expected rate-limit trip on /login, got statuses: {statuses}"
