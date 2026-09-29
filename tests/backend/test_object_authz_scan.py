"""
Object-level authorisation scan (v3.43)
======================================

**Authentication answers "who is this". It never answers "may this caller touch this
record".** Four NFC endpoints authenticated a caller and then acted on whatever session id or
`user_id` the request named, and the credential involved is compiled into the mobile app
bundle — a boundary is only as good as who holds the credential.

Per-endpoint assertions did not catch that and would not catch the next one, because the
failure is *an endpoint nobody thought about*. So this is a scan, in the same shape as the WS
event-catalog drift guard: enumerate the real route table, and fail on anything unclassified.

**What the scan covers, and what it deliberately does not.** Operator routes
(`require_admin` / `require_control` / `require_any_role`) are excluded: an operator is
role-authorised for every record by design, which is what being an operator means. The rule
applies to credentials that identify *one party among many* — a customer token, or a machine
key acting for an external system.

A useful thing this established while being written: of the ten record-scoped non-operator
routes, the six under `require_customer` were **already** correct. The gap was confined to the
machine-key path, where "the caller is a trusted server" was assumed and never written down as
a check.

  TC-OAZ-01  every record-scoped non-operator route is classified here
  TC-OAZ-02  every route classified as guarded still contains a guard
  TC-OAZ-03  the registry contains no stale entries
  TC-OAZ-04  an 'exempt' classification must carry a written reason
  TC-OAZ-05  the scan actually bites — drop an entry and it fails
"""
from __future__ import annotations

import inspect
import re
import sys

import pytest

# Credentials that identify ONE party among many. Operator roles are absent on purpose.
NON_OPERATOR_DEPS = {"require_customer", "optional_customer", "require_erp_api_key"}

# A path parameter naming a specific record.
ID_PARAM = re.compile(r"\{(\w*(?:id|uuid)\w*)\}", re.IGNORECASE)

# Tokens that indicate an ownership decision is being made in the handler.
GUARD_TOKENS = (
    "customer.id",
    "customer_id !=",
    "customer_id ==",
    "_require_session_access",
    "_customer_identities",
    "_owns(",
)

# ─────────────────────────────────────────────────────────────────────────────
# THE REGISTRY.
#
# Every route reached with a non-operator credential that names a specific record. Adding a
# route like that makes TC-OAZ-01 fail until it appears here — which is the entire point: the
# failure mode being guarded against is an endpoint nobody remembered to check.
#
# "guarded" means the handler decides whether THIS caller may touch THIS record.
# "exempt" requires a written reason, and there are none today.
# ─────────────────────────────────────────────────────────────────────────────
RECORD_SCOPED = {
    # ── the machine-key path: this is where the defect was (v3.43) ──
    ("POST", "/api/nfc/scan"):
        "guarded: identity comes from the principal, not body user_id. Not an id in the "
        "PATH, but user_id in the BODY decides who is billed, so it belongs to this class",
    ("GET", "/api/nfc/session/{session_id}"):
        "guarded: _require_session_access — 404 on a mismatch, so ids cannot be walked",
    ("POST", "/api/nfc/session/{session_id}/stop"):
        "guarded: _require_session_access, checked BEFORE the already-ended check",
    ("GET", "/api/nfc/sessions/by-user/{user_id}"):
        "guarded: _customer_identities — 403, since the caller supplied the id itself",

    # ── customer-token routes: already correct before v3.43 ──
    ("DELETE", "/api/customer/berths/reservations/{reservation_id}"):
        "guarded: res.customer_id != customer.id -> 404",
    ("GET", "/api/customer/contracts/{contract_id}/pdf"):
        "guarded: contract.customer_id != customer.id -> 403",
    ("POST", "/api/customer/contracts/{template_id}/sign"):
        "guarded: the template is not customer-scoped; the CustomerContract it creates is "
        "filtered on customer_id",
    ("POST", "/api/customer/invoices/{invoice_id}/pay"):
        "guarded: invoice.customer_id != customer.id -> 403",
    ("GET", "/api/customer/invoices/{invoice_id}/pdf"):
        "guarded: invoice.customer_id != customer.id -> 403",
    ("POST", "/api/customer/sessions/{session_id}/stop"):
        "guarded: session.customer_id != customer.id -> 403",
    ("GET", "/api/mobile/sessions/{session_id}/live"):
        "guarded: session.customer_id != customer.id -> 403",
}

# Routes with a non-operator credential that name NO record, so the rule does not apply
# (they act on "mine" or create something new). Listed so the scan can tell "not
# record-scoped" from "not yet classified".
NOT_RECORD_SCOPED_PREFIXES = (
    "/api/chat/",
    "/api/customer/alarms/trigger",
    "/api/customer/auth/",
    "/api/customer/berths/mine",
    "/api/customer/berths/reserve",
    "/api/customer/contracts/mine",
    "/api/customer/contracts/pending",
    "/api/customer/invoices/mine",
    "/api/customer/reviews/",
    "/api/customer/service-orders/",
    "/api/customer/sessions/mine",
    "/api/customer/sessions/pedestal-status",
    "/api/customer/sessions/start",
    "/api/mobile/qr/claim",
)


def _dependency_names(route) -> set[str]:
    """Every dependency callable in the route's tree, by name."""
    names: set[str] = set()
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return names
    stack = list(dependant.dependencies)
    while stack:
        dep = stack.pop()
        fn = getattr(dep, "call", None)
        name = getattr(fn, "__name__", None)
        if name:
            names.add(name)
        stack.extend(getattr(dep, "dependencies", []))
    return names


def _record_scoped_routes(app) -> dict[tuple[str, str], object]:
    found: dict[tuple[str, str], object] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        if not (_dependency_names(route) & NON_OPERATOR_DEPS):
            continue
        if not ID_PARAM.search(path) and path != "/api/nfc/scan":
            continue
        for method in sorted(getattr(route, "methods", []) or []):
            if method in ("HEAD", "OPTIONS"):
                continue
            found[(method, path)] = endpoint
    return found


@pytest.fixture(scope="module")
def routes(client):
    """The real route table. `client` is used so the app is built exactly as it serves."""
    from app.main import app

    return _record_scoped_routes(app)


# ═══ TC-OAZ-01 ═══════════════════════════════════════════════════════════════

def test_tc_oaz_01_every_record_scoped_route_is_classified(routes):
    """A new endpoint taking a record id under a non-operator credential fails until reviewed.

    This is the regression guard. The v3.43 defect was not a wrong check, it was four endpoints
    where nobody asked the question — so the guard has to be "was this asked about", not "is
    this particular check present".
    """
    unclassified = sorted(set(routes) - set(RECORD_SCOPED))
    assert not unclassified, (
        "These routes take a record id under a non-operator credential and are not in "
        f"RECORD_SCOPED: {unclassified}\n"
        "Decide for each whether the handler verifies that THIS caller may touch THIS "
        "record, then add it as 'guarded: <how>' or 'exempt: <written reason>'. "
        "Authenticating the caller is not enough — that was exactly the v3.43 defect."
    )


# ═══ TC-OAZ-02 ═══════════════════════════════════════════════════════════════

def test_tc_oaz_02_guarded_routes_still_contain_a_guard(routes):
    """A route registered as guarded whose check was later deleted.

    Deliberately shallow — it looks for ownership-decision tokens in the handler source, so it
    proves an intent is still expressed, not that the logic is correct. Correctness is the
    behavioural suite's job (`test_nfc_object_authz.py` and the customer-route tests). Two
    cheap checks catching different failures beat one expensive check catching neither.
    """
    missing = []
    for key, note in RECORD_SCOPED.items():
        if not note.startswith("guarded"):
            continue
        endpoint = routes.get(key)
        if endpoint is None:
            continue                      # stale entry — TC-OAZ-03 reports it
        try:
            source = inspect.getsource(endpoint)
        except OSError:                   # pragma: no cover
            continue
        if not any(token in source for token in GUARD_TOKENS):
            missing.append((key, note))

    assert not missing, (
        "These routes are registered as guarded but no ownership check is visible in the "
        f"handler: {[k for k, _n in missing]}\n"
        f"Either the check was removed — in which case restore it — or it moved into a helper "
        f"that should be added to GUARD_TOKENS."
    )


# ═══ TC-OAZ-03 ═══════════════════════════════════════════════════════════════

def test_tc_oaz_03_registry_has_no_stale_entries(routes):
    """A registry that outlives its routes stops being read.

    Same reasoning as PENDING_FRONTEND_EVENTS: an entry nobody can trace to a real route makes
    the whole list look approximate, and then a genuine gap in it goes unnoticed.
    """
    stale = sorted(set(RECORD_SCOPED) - set(routes))
    assert not stale, (
        f"RECORD_SCOPED lists routes that no longer exist: {stale}. Remove them so the "
        f"registry stays worth reading."
    )


def test_tc_oaz_04_no_exemptions_without_a_reason():
    """An 'exempt' entry must say why. There are none today; the check exists for the first."""
    bad = [k for k, note in RECORD_SCOPED.items()
           if not (note.startswith("guarded") or note.startswith("exempt:"))]
    assert not bad, (
        f"These entries classify nothing: {bad}. Each must start with 'guarded: <how>' or "
        f"'exempt: <written reason>'."
    )


def test_tc_oaz_05_the_scan_actually_bites(routes, monkeypatch):
    """Prove the guard fails when something is missing, rather than trusting that it would.

    A scan that passes because its registry happens to be complete looks identical to a scan
    that cannot fail. So: drop a known entry and confirm TC-OAZ-01's assertion fires. Same
    reasoning as TC-GINT-08 — the mechanism that makes other tests trustworthy gets its own
    test.
    """
    # sys.modules[__name__], not `import tests.backend.test_object_authz_scan` — pytest loads
    # this file as a top-level module (there is no tests/backend/__init__.py), so the dotted
    # import would create a SECOND module object and patch a copy nobody is running. The first
    # version of this test did exactly that and reported DID NOT RAISE.
    module = sys.modules[__name__]

    victim = ("GET", "/api/nfc/session/{session_id}")
    assert victim in RECORD_SCOPED, "fixture drifted — pick another known-guarded route"

    trimmed = {k: v for k, v in RECORD_SCOPED.items() if k != victim}
    monkeypatch.setattr(module, "RECORD_SCOPED", trimmed)

    with pytest.raises(AssertionError) as exc:
        test_tc_oaz_01_every_record_scoped_route_is_classified(routes)
    assert "not in RECORD_SCOPED" in str(exc.value)
    assert "session_id" in str(exc.value)
