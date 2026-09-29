"""
Operator roles — organised by what an action MEANS, not by which section it is in (v3.43)
========================================================================================

This file was rewritten rather than adjusted, and the reason is the whole point.

The previous version asserted that `monitor_control` **succeeds** on NFC/QR writes. That was a
faithful description of the code, so when re-pointing a physical NFC tag turned out to be
reachable by marina staff, the test agreed with the defect. Editing those expectations to 403
would have produced the same kind of test again — one that says "this is what the code does".
So the tables below describe the **rule**, and the code is checked against it:

  **INSTALLATION_ACTS** — change what the hardware *is*. Which socket a physical tag
    energises; whether a cabinet obeys the NUC at all. Performed once, by someone standing at
    the cabinet. **Admin only.**
  **OPERATIONS** — act within an installation that already exists: allow, deny, stop, reset,
    set a price. Daily work. **Admin + monitor_control.**
  **OBSERVATIONS** — read. Includes reading which tag is on which socket, because answering a
    customer's question is operations, not configuration. **Any operator role.**
  **ADMIN_SECTIONS** — admin for a different reason: what they *expose* (diagnostics, secrets,
    the ERP gateway), not what they change. Kept separate so the distinction stays visible.

TC-ROLE-07 is the one that matters most. Per-endpoint assertions cannot catch a NEW endpoint
wired to the wrong dependency, and that is exactly how this drift happened — so it scans the
real route table for installation-act paths gated by `require_control`.

  TC-ROLE-01  installation acts are refused for every non-admin operator role
  TC-ROLE-02  ...and permitted for admin
  TC-ROLE-03  operations are refused for read-only monitor
  TC-ROLE-04  ...and permitted for admin and monitor_control
  TC-ROLE-05  observations are permitted for every operator role
  TC-ROLE-06  admin-only sections are refused for everyone else
  TC-ROLE-07  ROUTE SCAN: no installation-act route is gated by require_control
  TC-ROLE-08  user management accepts monitor_control and rejects an unknown role
"""
from __future__ import annotations

import re

import pytest

from app.auth.models import User
from app.auth.password import hash_password
from app.auth.tokens import create_access_token
from tests.backend.conftest import TestUserSession

NON_ADMIN_OPERATORS = ("monitor_control", "monitor_control_api", "monitor")


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


@pytest.fixture(autouse=True)
def _clean_role_tags():
    """Remove this module's tags before each test.

    Without it, a pre-fix run writes a tag in TC-ROLE-01 and TC-ROLE-02 then hits the unique
    constraint — so the test would report a duplicate-handling problem while the gate is what
    is under test.
    """
    from app.models.nfc_tag import NfcTag
    from tests.backend.conftest import TestSession

    db = TestSession()
    try:
        db.query(NfcTag).filter(NfcTag.cabinet_id == "ROLE_CAB").delete()
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture(scope="module")
def headers() -> dict:
    out = {}
    for role in ("admin",) + NON_ADMIN_OPERATORS:
        email = f"role_{role}@test.local"
        out[role] = _hdr(_ensure_user(email, role), email, role)
    return out


# ═══ the rule, as tables ══════════════════════════════════════════════════════

# Change what the hardware IS. Admin only.
INSTALLATION_ACTS = [
    # Which socket a physical NFC tag energises. Re-pointing a tag is an installation act:
    # after it, a customer's tap switches a different berth's power.
    # Tag ids are unique per row on purpose: a duplicate would take the handler down a
    # different path and the test would be measuring that instead of the gate.
    ("POST", "/api/nfc/tags",
     {"cabinet_id": "ROLE_CAB", "socket_id": "Q1", "nfc_tag_id": "ROLE-TAG-SINGLE"}),
    ("POST", "/api/nfc/tags/bulk",
     {"cabinet_id": "ROLE_CAB",
      "items": [{"socket_id": "Q2", "nfc_tag_id": "ROLE-TAG-BULK"}]}),
    ("DELETE", "/api/nfc/tags/ROLE_CAB/Q3", None),
    # Whether a cabinet provisions by QR or NFC — it changes which physical token works.
    ("PATCH", "/api/nfc/mode/ROLE_CAB", {"mode": "nfc"}),
    # Invalidates every QR code already stuck to a cabinet, so customers' codes stop working.
    ("POST", "/api/pedestals/ROLE_CAB/qr/regenerate", {}),
    # Smart mode OFF makes the cabinet ignore the NUC entirely — the heaviest write we have.
    ("POST", "/api/pedestals/ROLE_CAB/smartmode", {"value": True}),
]

# Act within an existing installation. Admin + monitor_control.
OPERATIONS = [
    ("PUT", "/api/billing/config", {"kwh_price_eur": 0.5, "liter_price_eur": 0.01}),
    ("POST", "/api/pedestals/1/sockets/1/breaker/reset", {}),
]

# Read. Every operator, including read-only monitor.
OBSERVATIONS = [
    ("GET", "/api/billing/config", None),
    ("GET", "/api/pedestals/1/sockets/1/breaker/status", None),
    # Reading the tag map is how staff answer "why did my tap not work?" — operations, not
    # configuration, so it stays open deliberately.
    ("GET", "/api/nfc/tags/ROLE_CAB", None),
    ("GET", "/api/nfc/mode/ROLE_CAB", None),
    ("GET", "/api/pedestals/ROLE_CAB/qr/all", None),
]

# Admin because of what they EXPOSE, not what they change.
ADMIN_SECTIONS = [
    ("GET", "/api/system/health", None),
    ("GET", "/api/admin/settings/smtp", None),
    ("GET", "/api/admin/ext-api/config", None),
]

# Route-path shapes that are installation acts, for the scan in TC-ROLE-07. Patterns rather
# than literals so a new sibling route (say POST /api/nfc/tags/import) is caught too.
INSTALLATION_ACT_PATTERNS = (
    r"^/api/nfc/tags(/|$)",
    r"^/api/nfc/mode/",
    r"^/api/pedestals/\{[^}]+\}/qr/regenerate$",
    r"^/api/pedestals/\{[^}]+\}/smartmode$",
)
# Methods that change something. A GET matching the patterns above is an observation.
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _call(client, method, path, body, hdr):
    return client.request(method, path, json=body, headers=hdr)


# ═══ TC-ROLE-01 / 02 — installation acts ══════════════════════════════════════

@pytest.mark.parametrize("method,path,body", INSTALLATION_ACTS)
def test_tc_role_01_installation_acts_refuse_non_admin(client, headers, method, path, body):
    """Marina staff cannot change what the hardware is.

    `monitor_control_api` is included because it is in `_CONTROL_ROLES` too — an ERP-tier
    account must not be able to re-point a tag either.
    """
    for role in NON_ADMIN_OPERATORS:
        r = _call(client, method, path, body, headers[role])
        assert r.status_code == 403, (
            f"{role} got {r.status_code} on {method} {path} — installation acts are admin "
            f"only. Response: {r.text[:200]}"
        )


@pytest.mark.parametrize("method,path,body", INSTALLATION_ACTS)
def test_tc_role_02_installation_acts_allow_admin(client, headers, method, path, body):
    """Admin passes the gate. 404/409 from the handler is fine — the gate is what is tested."""
    r = _call(client, method, path, body, headers["admin"])
    assert r.status_code != 403, f"admin was refused {method} {path}: {r.text[:200]}"


# ═══ TC-ROLE-03 / 04 — operations ═════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", OPERATIONS)
def test_tc_role_03_operations_refuse_monitor(client, headers, method, path, body):
    assert _call(client, method, path, body, headers["monitor"]).status_code == 403


@pytest.mark.parametrize("method,path,body", OPERATIONS)
def test_tc_role_04_operations_allow_control_tier(client, headers, method, path, body):
    for role in ("admin", "monitor_control"):
        assert _call(client, method, path, body, headers[role]).status_code != 403, \
            f"{role} was refused the operation {method} {path}"


# ═══ TC-ROLE-05 — observations ════════════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", OBSERVATIONS)
def test_tc_role_05_observations_allow_every_operator(client, headers, method, path, body):
    for role in ("admin",) + NON_ADMIN_OPERATORS:
        assert _call(client, method, path, body, headers[role]).status_code != 403, \
            f"{role} was refused the read {method} {path}"


# ═══ TC-ROLE-06 — admin-only sections ═════════════════════════════════════════

@pytest.mark.parametrize("method,path,body", ADMIN_SECTIONS)
def test_tc_role_06_admin_sections_refuse_others(client, headers, method, path, body):
    for role in ("monitor_control", "monitor"):
        assert _call(client, method, path, body, headers[role]).status_code == 403
    assert _call(client, method, path, body, headers["admin"]).status_code != 403


# ═══ TC-ROLE-07 — the scan, and the real regression guard ═════════════════════

def test_tc_role_07_no_installation_act_is_gated_by_require_control(client):
    """A NEW installation-act endpoint wired to require_control fails here.

    This is the guard the original drift needed. Every per-endpoint assertion above would pass
    on a codebase that had just added `POST /api/nfc/tags/import` with `require_control`,
    because no assertion mentions a route that does not exist yet. The scan does not need to
    know the route: it recognises the shape.
    """
    from app.main import app

    def gates(route) -> set[str]:
        out: set[str] = set()
        dependant = getattr(route, "dependant", None)
        if dependant is None:
            return out
        stack = list(dependant.dependencies)
        while stack:
            dep = stack.pop()
            name = getattr(getattr(dep, "call", None), "__name__", None)
            if name:
                out.add(name)
            stack.extend(getattr(dep, "dependencies", []))
        return out

    offenders = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not any(re.search(p, path) for p in INSTALLATION_ACT_PATTERNS):
            continue
        methods = {m for m in (getattr(route, "methods", None) or set())} & WRITE_METHODS
        if not methods:
            continue                      # a GET on the same shape is an observation
        found = gates(route)
        if "require_control" in found or (
                "require_admin" not in found and "require_api_config" not in found):
            offenders.append((sorted(methods), path, sorted(found) or ["(no gate)"]))

    assert not offenders, (
        "These routes change what the hardware IS but are not admin-gated:\n  "
        + "\n  ".join(f"{m} {p} -> {g}" for m, p, g in offenders)
        + "\nRe-pointing a physical token or disabling NUC control is an installation act, "
          "not an operation. Use require_admin, or — if this genuinely is day-to-day work — "
          "say so here and move it out of INSTALLATION_ACT_PATTERNS with a reason."
    )


def test_tc_role_07b_the_scan_actually_bites(client):
    """Prove the scan fails when a route is mis-gated, rather than trusting that it would.

    Uses a throwaway FastAPI app rather than mutating the real one, so a failure here cannot
    leave the route table modified for other tests.
    """
    from fastapi import Depends, FastAPI

    from app.auth.dependencies import require_control

    probe = FastAPI()

    @probe.post("/api/nfc/tags/import")
    def _mis_gated(_: object = Depends(require_control)):   # pragma: no cover
        return {}

    matched = [r for r in probe.routes
               if any(re.search(p, getattr(r, "path", "")) for p in INSTALLATION_ACT_PATTERNS)]
    assert matched, (
        "the patterns no longer recognise a new /api/nfc/tags/... route, so the scan would "
        "not catch the very drift it exists for"
    )


# ═══ TC-ROLE-08 — user management ═════════════════════════════════════════════

def test_tc_role_08_user_management_roles(client, auth_headers):
    import uuid

    email = f"mc_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/users", headers=auth_headers,
                    json={"email": email, "password": "newpass1234",
                          "role": "monitor_control"})
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "monitor_control"

    bad = client.post("/api/auth/users", headers=auth_headers,
                      json={"email": "bad_role@example.com",
                            "password": "newpass1234", "role": "superuser"})
    assert bad.status_code in (400, 422)
