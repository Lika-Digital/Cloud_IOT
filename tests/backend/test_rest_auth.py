"""Every /api route proves identity before it returns data — block 1, 2026-10-12.

MEASURED 2026-10-12: a scan of the route table found /api routes with no identity check at all,
reachable from the internet through the Cloudflare tunnel (marina2 -> nginx -> /api). Among
them GET /api/sessions, which returns customer_id / customer_name / nfc_user_id / erp_ref; an
anonymous GET reached the SQL query. And POST /api/predictions/train — not a leak but CPU
spent on an Atom without a GPU, on anyone's request.

Rule 13 (docs/engineering_notes.md): every channel to data proves identity with the same check
as an HTTP route. These tests make it structural:

  TC-RA-01  every /api route carries an identity dependency, or is in PUBLIC with a written
            reason. A new unauthenticated route fails this test until someone decides.
  TC-RA-02  PUBLIC has no stale entries.
  TC-RA-03  the routes that were open answer an anonymous caller with a refusal, not data.
  TC-RA-04  the same routes still answer an authenticated operator.

TC-RA-01 and TC-RA-03 FAIL on the code before this change (shown 2026-10-12).
"""
from __future__ import annotations

import re

import pytest

# Dependencies that establish who the caller is. optional_customer is NOT here: it lets an
# anonymous caller through by design.
IDENTITY_DEPS = {
    "_get_current_user", "require_any_role", "require_admin", "require_control",
    "require_api_config", "require_customer", "require_erp_api_key",
}

# Routes that legitimately take no identity dependency — each with its reason. Matched by
# (method, path). Kept short on purpose: every line here is a door, and it must say why.
PUBLIC: dict[tuple[str, str], str] = {
    # Authentication itself: the caller proves identity INSIDE these, by password, partial
    # token or service credentials. There is nothing to be authenticated with yet.
    ("POST", "/api/auth/login"): "the login itself",
    ("POST", "/api/auth/first-password"): "pre-login; authorised by the partial token in the body",
    ("POST", "/api/auth/totp/enroll"): "pre-login second factor; partial token",
    ("POST", "/api/auth/totp/enroll-verify"): "pre-login second factor; partial token",
    ("POST", "/api/auth/totp/login"): "pre-login second factor; partial token",
    ("POST", "/api/auth/service-token"): "the ERP service login (credentials in the body)",
    ("POST", "/api/auth/register"): "404 unless ALLOW_SELF_REGISTRATION (off by default)",
    ("POST", "/api/customer/auth/login"): "legacy customer app login (D6.1: app goes via ERP)",
    ("POST", "/api/customer/auth/register"): "legacy customer app sign-up",
    # The external gateway verifies its bearer token inside each handler, not as a dependency.
    # TC-RA-03 proves one of them refuses an anonymous caller.
    ("GET", "/api/ext/{path:path}"): "gateway: bearer verified in the handler",
    ("POST", "/api/ext/{path:path}"): "gateway: bearer verified in the handler",
    ("PUT", "/api/ext/{path:path}"): "gateway: bearer verified in the handler",
    ("PATCH", "/api/ext/{path:path}"): "gateway: bearer verified in the handler",
    ("DELETE", "/api/ext/{path:path}"): "gateway: bearer verified in the handler",
    # KNOWN OPEN — R4, not block 1: the stream is consumed by an <img> tag, which cannot send an
    # Authorization header, so a dependency would break the camera view. Needs its own design.
    ("GET", "/api/camera/{pedestal_id}/stream"): "R4: <img> cannot send a header — open, known",
}
# Direct ext endpoints (ext_*_endpoints.py) also verify the bearer inside the handler.
PUBLIC_PREFIXES = ("/api/ext/",)


def _identity_names(route) -> set[str]:
    names: set[str] = set()
    d = getattr(route, "dependant", None)
    stack = list(d.dependencies) if d else []
    while stack:
        x = stack.pop()
        n = getattr(getattr(x, "call", None), "__name__", None)
        if n:
            names.add(n)
        stack.extend(getattr(x, "dependencies", []))
    return names


def _api_routes():
    from app.main import app
    for r in app.routes:
        path = getattr(r, "path", "")
        if not path.startswith("/api"):
            continue
        for m in sorted(getattr(r, "methods", []) or []):
            if m in ("HEAD", "OPTIONS"):
                continue
            yield m, path, r


def test_tc_ra_01_every_api_route_proves_identity_or_says_why_not(client):
    missing = []
    for m, path, r in _api_routes():
        if _identity_names(r) & IDENTITY_DEPS:
            continue
        if (m, path) in PUBLIC or path.startswith(PUBLIC_PREFIXES):
            continue
        missing.append(f"{m} {path}")
    assert not missing, (
        "These /api routes return data with NO identity check (rule 13):\n  "
        + "\n  ".join(sorted(missing))
        + "\nAdd require_any_role / require_admin / require_control — or, if a route truly must "
          "be public, add it to PUBLIC with the reason.")


def test_tc_ra_02_public_has_no_stale_entries(client):
    live = {(m, p) for m, p, _ in _api_routes()}
    stale = sorted(k for k in PUBLIC if k not in live)
    assert not stale, f"PUBLIC lists routes that no longer exist: {stale}"


# The routes the 2026-10-12 scan found open, with a concrete URL for each.
WERE_OPEN = [
    ("GET", "/api/sessions"),
    ("GET", "/api/sessions/active"),
    ("GET", "/api/sessions/pending"),
    ("GET", "/api/sessions/1"),
    ("GET", "/api/pedestals"),
    ("GET", "/api/pedestals/1"),
    ("GET", "/api/pedestals/1/led-schedule"),
    ("GET", "/api/pedestals/1/simulator/status"),
    ("GET", "/api/pedestals/1/sockets/config"),
    ("GET", "/api/pedestals/1/sockets/1/auto-activate-log"),
    ("GET", "/api/pedestals/1/valves/config"),
    ("GET", "/api/berths"),
    ("GET", "/api/berths/availability"),
    ("GET", "/api/predictions/electricity"),
    ("GET", "/api/predictions/water"),
    ("GET", "/api/predictions/status"),
    ("POST", "/api/predictions/train"),
    ("GET", "/api/system/training-storage"),
    # handler-verified: proves the PUBLIC_PREFIXES exemption is not a hole
    ("GET", "/api/ext/pedestals/1/status"),
]


@pytest.mark.parametrize("method,url", WERE_OPEN)
def test_tc_ra_03_an_anonymous_caller_is_refused(client, method, url):
    r = client.request(method, url)
    assert r.status_code in (401, 403), (
        f"{method} {url} answered an anonymous caller with {r.status_code}: {r.text[:200]}")


@pytest.mark.parametrize("method,url", [
    (m, u) for m, u in WERE_OPEN if not u.startswith("/api/ext/") and m == "GET"])
def test_tc_ra_04_an_operator_is_still_answered(client, auth_headers, method, url):
    """Positive control: the refusal is about identity, not about the route breaking."""
    r = client.request(method, url, headers=auth_headers)
    assert r.status_code not in (401, 403), f"{method} {url} refused an admin: {r.text[:200]}"
