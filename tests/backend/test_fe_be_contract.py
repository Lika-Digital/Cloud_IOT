"""
FE ↔ BE contract — every call the frontend makes must hit a real route (v3.44)
=============================================================================

Both ends are moving at once: the marina dashboard is being rebuilt against endpoints that
are also new. That is where things break silently, because a dead `fetch` in a browser fails
in the console and nobody notices until a customer does.

**This reads the frontend source.** It is not a hand-maintained list of what the frontend is
believed to call — that is what `scripts/gap-tests/gap_fe_be_session_schema.py` does, and its
`FRONTEND_SESSION_FIELDS` literal cannot catch a field added to the TypeScript interface,
because nothing compares the two. A claim about the frontend is not a check of it; this is the
third time that distinction has cost something in this codebase (see
`docs/engineering_notes.md` — a docstring is a claim, not a control).

  TC-FEBE-01  every URL the frontend requests resolves to a real FastAPI route
  TC-FEBE-02  no frontend call targets a route removed by the migration
  TC-FEBE-03  the extractor actually finds calls — a scan that finds nothing passes vacuously
  TC-FEBE-04  path parameters line up in count and position

What this does NOT do, stated so the gap is known rather than discovered: it checks the URL
and the method, not the request BODY shape. Body-shape drift is caught by the response-shape
tests (`test_marina_core_contract.py`) on the way back, and by the Pydantic model on the way
in — a wrong body is a 422, which is loud. A silent 404 is what this exists for.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_DIR = REPO / "frontend" / "src" / "api"

# ── What a frontend call looks like ───────────────────────────────────────────────────────
#
# Both idioms are in use:
#     api.get<Thing[]>('/pedestals')                      -> baseURL '/api' is prepended
#     apiClient.post('/api/nfc/scan', body)               -> absolute, no baseURL
#
# The generic (`<Thing[]>`) is optional and skipped. Template literals keep their `${...}`
# so TC-FEBE-04 can count parameters.
_CALL_RE = re.compile(
    r"""\b(?:api|apiClient)\s*\.\s*(get|post|put|patch|delete)\s*"""
    r"""(?:<[^>()]*>)?\s*\(\s*"""
    r"""(?P<q>['"`])(?P<url>[^'"`]+)(?P=q)""",
    re.VERBOSE,
)

# Each API module makes its own axios instance, and THEY DO NOT SHARE A PREFIX:
#     alarms.ts -> baseURL '/api/alarms'
#     auth.ts   -> baseURL '/api/auth'
#     all others -> '/api'
#
# Read per file rather than assumed. A single assumed prefix made 21 live routes look dead on
# the first run of this test -- the same mistake the test exists to catch, one level up.
_BASE_URL_RE = re.compile(
    r"axios\s*\.\s*create\s*\(\s*\{[^}]*?baseURL\s*:\s*"
    r"(?P<q>[\'\"`])(?P<base>[^\'\"`]*)(?P=q)",
    re.DOTALL,
)
# A module with no `axios.create` uses absolute paths on a shared client.
_DEFAULT_BASE = ""


def _base_url_for(text: str) -> str:
    m = _BASE_URL_RE.search(text)
    return m.group("base").rstrip("/") if m else _DEFAULT_BASE


def _frontend_calls() -> list[tuple[str, str, Path, int]]:
    """(method, url, file, line) for every HTTP call in frontend/src/api/**."""
    out: list[tuple[str, str, Path, int]] = []
    for f in sorted(API_DIR.rglob("*.ts")):
        text = io.open(f, encoding="utf-8").read()
        base = _base_url_for(text)
        for m in _CALL_RE.finditer(text):
            # A call on a `//` line is commented out and calls nothing. D6.1 (2026-10-12)
            # comments out the NFC tag API rather than deleting it, and this parser read the
            # commented lines as live calls to routes that are (correctly) gone.
            line_start = text.rfind(chr(10), 0, m.start()) + 1
            if text[line_start:m.start()].lstrip().startswith("//"):
                continue
            url = m.group("url")
            line = text[:m.start()].count(chr(10)) + 1
            if not url.startswith("/"):
                # A full URL or a computed value. Out of scope and worth knowing about, so
                # TC-FEBE-03 asserts the count of these stays at zero rather than ignoring it.
                out.append((m.group(1).upper(), url, f, line))
                continue
            # An already-absolute '/api/...' path is NOT re-prefixed, so a module mixing both
            # idioms still resolves. Everything else gets its own module's base.
            full = url if url.startswith("/api/") else base + url
            out.append((m.group(1).upper(), full, f, line))
    return out


# ── Known dead calls ─────────────────────────────────────────────────────────────────────
#
# Calls that target no route and are KNOWINGLY left alone, each with the reason and a
# deferred-item reference. An allowlist is how a test stops being a test, so this one has two
# properties that keep it honest:
#
#   * TC-FEBE-01 fails on anything NOT listed here, so the list cannot grow by accident;
#   * TC-FEBE-05 fails when a listed entry becomes LIVE, so the list cannot rot. An entry
#     that has been fixed must be deleted, not left as a comment about history.
#
# The reason is a sentence, not a ticket number, so a reader does not have to look it up.
KNOWN_DEAD_CALLS: dict[tuple[str, str], str] = {
}


def _normalise(url: str) -> str:
    """`/api/pedestals/${id}/sockets/${n}/load` -> `/api/pedestals/{}/sockets/{}/load`.

    Query strings are dropped: they are not part of route matching. A trailing slash is
    significant to FastAPI and is preserved.
    """
    url = url.split("?", 1)[0]
    return re.sub(r"\$\{[^}]*\}", "{}", url)


def _route_patterns(app) -> set[tuple[str, str]]:
    """(method, normalised path) for every route the app actually serves."""
    pats: set[tuple[str, str]] = set()
    for r in app.routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if not path or not methods:
            continue
        norm = re.sub(r"\{[^}]*\}", "{}", path)
        for m in methods:
            pats.add((m.upper(), norm))
    return pats


@pytest.fixture(scope="module")
def route_patterns():
    from app.main import app
    return _route_patterns(app)


@pytest.fixture(scope="module")
def calls():
    return _frontend_calls()


# ═══ TC-FEBE-03 — the scan must not pass vacuously ════════════════════════════

def test_tc_febe_03_the_extractor_finds_real_calls(calls):
    """A scanner that matches nothing would make every other test in this file green.

    This is the fifth green-signal-with-nothing-behind-it guard in this suite, and it is here
    because the others were all discovered after the fact. The floor is deliberately well
    below the current count so a legitimate refactor does not trip it, and well above zero so
    a broken regex does.
    """
    assert API_DIR.is_dir(), f"{API_DIR} does not exist — the extractor has nothing to read"
    assert len(calls) >= 20, (
        f"only {len(calls)} frontend API calls found. The regex is probably broken, which "
        f"would make TC-FEBE-01 pass without checking anything"
    )
    relative = [c for c in calls if not c[1].startswith("/")]
    assert not relative, (
        "frontend call(s) with a non-absolute URL — the extractor cannot resolve these, so "
        "they are unchecked:\n"
        + "\n".join(f"  {f.name}:{ln}  {m} {u}" for m, u, f, ln in relative)
    )


# ═══ TC-FEBE-01 / TC-FEBE-02 ══════════════════════════════════════════════════

def test_tc_febe_01_every_frontend_call_hits_a_real_route(calls, route_patterns):
    """The core check. A frontend call with no matching route is a 404 nobody sees.

    Covers TC-FEBE-02 by construction: a route removed by the migration stops appearing in
    the live route table, so any surviving call to it fails here. That is the whole point of
    reading the real table rather than a list — the list would have to be remembered.
    """
    missing = []
    known = []
    for method, url, f, line in calls:
        if not url.startswith("/"):
            continue                      # reported by TC-FEBE-03
        norm = _normalise(url)
        if (method, norm) in route_patterns:
            continue
        if (method, norm) in KNOWN_DEAD_CALLS:
            known.append((method, norm, f, line))
            continue
        missing.append((method, url, norm, f, line))

    # Printed every run, not swallowed. A known defect that stops being mentioned is a
    # defect that stops being fixed.
    for m, n, f, line in known:
        print(f"KNOWN DEAD CALL (allowlisted): {m} {n}  at {f.name}:{line}")

    assert not missing, (
        f"{len(missing)} frontend call(s) target no existing backend route:\n"
        + "\n".join(
            f"  {f.name}:{ln}\n      calls   {m} {u}\n      matched {m} {n}  <- no such route"
            for m, u, n, f, ln in missing
        )
        + "\n\nEither the route was removed and the frontend still calls it (a dead call that "
          "fails silently in a browser), or the frontend was written against a path that was "
          "never implemented."
    )


def test_tc_febe_04_path_parameter_counts_line_up(calls, route_patterns):
    """A call with the right shape but the wrong number of parameters.

    `/api/pedestals/{}/sockets/{}` against a route of `/api/pedestals/{}` is not a 404 — it
    can match a DIFFERENT route, or match with a segment swallowed. Checked separately from
    TC-FEBE-01 because the failure reads completely differently: there the path does not
    exist, here it exists and means something else.
    """
    by_method: dict[str, set[str]] = {}
    for m, p in route_patterns:
        by_method.setdefault(m, set()).add(p)

    suspicious = []
    for method, url, f, line in calls:
        if not url.startswith("/"):
            continue
        norm = _normalise(url)
        if norm in by_method.get(method, set()):
            continue
        # Same literal segments, different parameter count — the confusable case.
        want_segments = [s for s in norm.split("/") if s and s != "{}"]
        for candidate in by_method.get(method, set()):
            have_segments = [s for s in candidate.split("/") if s and s != "{}"]
            if have_segments == want_segments and candidate.count("{}") != norm.count("{}"):
                suspicious.append((method, url, norm, candidate, f, line))

    assert not suspicious, (
        "frontend call(s) whose path parameters do not line up with the route:\n"
        + "\n".join(
            f"  {f.name}:{ln}\n      calls  {m} {n}  ({n.count('{}')} param(s))\n"
            f"      route  {m} {c}  ({c.count('{}')} param(s))"
            for m, u, n, c, f, ln in suspicious
        )
    )

# ═══ TC-FEBE-05 ═══════════════════════════════════════════════════════════════

def test_tc_febe_05_the_allowlist_does_not_rot(route_patterns):
    """A known-dead call that has become live must be removed from the allowlist.

    Without this, the allowlist silently grants permanent amnesty: someone adds the missing
    route, the call starts working, and the entry stays for ever — so the next dead call on
    that path is allowlisted too, by an entry nobody re-read.

    The same reasoning as the skip report and the WHY-IT-FAILED block: a suppression has to
    keep justifying itself.
    """
    resurrected = [
        (m, p) for (m, p) in KNOWN_DEAD_CALLS
        if (m, p) in route_patterns
    ]
    assert not resurrected, (
        "allowlisted dead call(s) now resolve to a real route. Delete them from "
        "KNOWN_DEAD_CALLS:\n"
        + "\n".join(f"  {m} {p}" for m, p in resurrected)
    )


def test_tc_febe_06_every_allowlist_entry_is_still_dead(calls):
    """An allowlist entry for a call the frontend no longer makes is also rot.

    Catches the other direction: the call was deleted from the frontend, so the entry protects
    nothing and merely makes the list look longer than the problem.
    """
    made = {(m, _normalise(u)) for m, u, _f, _l in calls if u.startswith("/")}
    stale = [(m, p) for (m, p) in KNOWN_DEAD_CALLS if (m, p) not in made]
    assert not stale, (
        "allowlisted call(s) that the frontend no longer makes. Delete them from "
        "KNOWN_DEAD_CALLS:\n"
        + "\n".join(f"  {m} {p}" for m, p in stale)
    )
