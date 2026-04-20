"""
Regression guard for H-6: /api/auth/register is public by default and leaks
read access to anyone on the internet. The gate ALLOW_SELF_REGISTRATION must
be off by default; turning it on opens the endpoint.
"""
from __future__ import annotations
import pytest


@pytest.fixture
def register_payload():
    return {"email": f"register-test-{id(object())}@test.local", "password": "correcthorsebatterystaple"}


def test_register_returns_404_when_flag_off(client, register_payload):
    """Default config: register route is hidden."""
    from app.config import settings
    prev = settings.allow_self_registration
    settings.allow_self_registration = False
    try:
        r = client.post("/api/auth/register", json=register_payload)
        assert r.status_code == 404, (
            f"Expected 404 when ALLOW_SELF_REGISTRATION=false; got {r.status_code} {r.text}"
        )
    finally:
        settings.allow_self_registration = prev


def test_register_works_when_flag_on(client, register_payload):
    """Flag on: register accepts a new account."""
    from app.config import settings
    prev = settings.allow_self_registration
    settings.allow_self_registration = True
    try:
        r = client.post("/api/auth/register", json=register_payload)
        assert r.status_code in (201, 400), (
            f"Expected 201 (or 400 if email already exists); got {r.status_code} {r.text}"
        )
    finally:
        settings.allow_self_registration = prev
