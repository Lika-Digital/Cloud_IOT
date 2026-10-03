"""
CORE response shape vs the TypeScript the UI renders (v3.44)
===========================================================

The second half of the FE/BE contract. `test_fe_be_contract.py` proves the frontend's URLs
resolve; this proves the FIELDS line up — and it compares the TypeScript interfaces against
the **actual JSON the endpoint produces**, not against a Pydantic model.

That distinction matters. A model can declare a field that the route never fills, because the
route builds a plain dict (ours do). Checking the model would pass while the browser received
`undefined` and rendered a blank — which is precisely the failure the old hand-written GAP
check was supposed to catch and could not.

  TC-SHAPE-01  every field the TS declares for CORE is present in the real response
  TC-SHAPE-02  every field the TS declares for berth detail is present
  TC-SHAPE-03  the parser finds the interfaces — it cannot pass vacuously
  TC-SHAPE-04  nullable-in-TS fields are genuinely nullable, and non-nullable ones never null
  TC-SHAPE-05  `unknown` is reachable for every field that declares it
  TC-SHAPE-06  no field in the response is absent from the TS (the UI would ignore new data)
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

REPO = Path(__file__).resolve().parents[2]
TS_FILE = REPO / "frontend" / "src" / "api" / "marina.ts"

TEST_DB = "sqlite:///./tests/test_pedestal.db"
_engine = create_engine(TEST_DB, connect_args={"check_same_thread": False})
_S = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
TEST_USER_DB = "sqlite:///./tests/test_users.db"
_user_engine = create_engine(TEST_USER_DB, connect_args={"check_same_thread": False})
_US = sessionmaker(autocommit=False, autoflush=False, bind=_user_engine)

CAB = "TST_SHAPE_CAB"

_FIELD_RE = re.compile(r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<opt>\?)?\s*:\s*(?P<type>[^\n]+)$",
                       re.MULTILINE)


def parse_interface(name: str) -> dict[str, str]:
    """{field: type-text} for `export interface <name> { ... }`, brace-counted.

    No fallback to a literal list. If the interface is renamed this raises, because a silent
    fallback would reintroduce the exact problem: a check that verifies a copy of the truth
    rather than the truth.
    """
    src = io.open(TS_FILE, encoding="utf-8").read()
    m = re.search(r"\bexport\s+interface\s+" + re.escape(name) + r"[^{]*\{", src)
    if not m:
        raise AssertionError(
            f"`export interface {name}` not found in {TS_FILE.name}. Renamed or moved — "
            f"update this test rather than letting it verify nothing."
        )
    i, depth = m.end(), 1
    while i < len(src) and depth:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    body = src[m.end():i - 1]

    out: dict[str, str] = {}
    for f in _FIELD_RE.finditer(body):
        line = f.group(0).strip()
        if line.startswith("//") or line.startswith("*"):
            continue
        out[f.group("name")] = f.group("type").rstrip(",").strip()
    return out


# `export type Name = 'a' | 'b' | null`, including the multi-line form where the union
# continues on following lines each starting with `|`.
_ALIAS_RE = re.compile(
    r"^export\s+type\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"(?P<body>[^\r\n]+(?:\s*\|[^\r\n]+)*)",
    re.MULTILINE,
)

def _aliases() -> dict[str, str]:
    """`export type UnavailableReason = 'no_socket' | 'standalone' | null` -> its union text.

    Resolved because the TypeScript is allowed to be idiomatic. The first version of this
    test flagged `unavailable_reason: UnavailableReason` as a non-nullable field arriving
    null — the field IS nullable, via the alias, and the parser simply could not see through
    it. Flattening the TS to satisfy the checker would have been the wrong repair: a test that
    requires the code to be written for its convenience stops describing the code.
    """
    src = io.open(TS_FILE, encoding="utf-8").read()
    return {m.group("name"): m.group("body") for m in _ALIAS_RE.finditer(src)}


def is_nullable(type_text: str) -> bool:
    """True when the declared type admits null — following one level of alias.

    One level, not arbitrary depth: every alias in this file resolves directly to a union of
    literals, and a recursive resolver would be more machinery than the problem has. If a
    nested alias is ever added, TC-SHAPE-04 fails loudly on it rather than quietly assuming
    non-nullable, which is the safe direction.
    """
    seen: set[str] = set()
    text = type_text
    for _ in range(2):
        parts = [p.strip().strip("()") for p in text.split("|")]
        if "null" in parts or "undefined" in parts:
            return True
        # A bare alias reference, e.g. `UnavailableReason`.
        if len(parts) == 1 and parts[0] in _aliases() and parts[0] not in seen:
            seen.add(parts[0])
            text = _aliases()[parts[0]]
            continue
        return False
    return False


@pytest.fixture(scope="module")
def shape_fixture(client, auth_headers):
    """A cabinet with one assigned berth, one unassigned berth, and two valves."""
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    from app.models.valve_config import ValveConfig
    from app.auth.berth_models import Berth

    r = client.post("/api/pedestals/", json={
        "name": "Shape Pedestal", "location": "Dock S", "data_mode": "real",
    }, headers=auth_headers)
    pid = r.json()["id"]

    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == pid).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=pid)
            db.add(cfg)
        cfg.opta_client_id = CAB
        cfg.dock_id = "S"
        cfg.smart_mode = True
        for sid in (1, 2, 3, 4):
            if db.query(SocketConfig).filter(
                    SocketConfig.pedestal_id == pid,
                    SocketConfig.socket_id == sid).first() is None:
                db.add(SocketConfig(pedestal_id=pid, socket_id=sid, auto_activate=True))
        for vid in (1, 2):
            if db.query(ValveConfig).filter(
                    ValveConfig.pedestal_id == pid,
                    ValveConfig.valve_id == vid).first() is None:
                db.add(ValveConfig(pedestal_id=pid, valve_id=vid, auto_activate=True))
        db.commit()
    finally:
        db.close()

    udb = _US()
    ids = []
    try:
        for n in (11, 12):
            b = (udb.query(Berth)
                 .filter(Berth.pedestal_id == pid, Berth.berth_number == n).first())
            if b is None:
                b = Berth(name=f"Shape berth {n}", pedestal_id=pid, berth_number=n)
                udb.add(b)
                udb.commit()
                udb.refresh(b)
            ids.append(b.id)
    finally:
        udb.close()

    # Berth 11 gets a socket; berth 12 deliberately gets none, so the null-bearing branch of
    # the payload is covered by the same fixture.
    client.put(f"/api/marina/berth-assignments/{pid}", headers=auth_headers, json={
        "assignments": [{"berth_id": ids[0], "socket_id": 1}],
    })
    return pid, ids


@pytest.fixture(autouse=True)
def _alive(shape_fixture):
    from app.services.mqtt_handlers import last_heartbeat
    pid, _ = shape_fixture
    last_heartbeat[pid] = datetime.utcnow()
    yield
    last_heartbeat.pop(pid, None)


def _ped(client, auth_headers, pid):
    r = client.get("/api/marina/berths", headers=auth_headers)
    assert r.status_code == 200, r.text
    return next(p for p in r.json()["pedestals"] if p["pedestal_id"] == pid)


# ═══ TC-SHAPE-03 ══════════════════════════════════════════════════════════════

def test_tc_shape_03_the_interfaces_parse():
    """A parser that finds nothing would make every other test here green."""
    assert TS_FILE.is_file(), f"{TS_FILE} is missing"
    for name, floor in [
        ("MarinaPedestal", 8), ("Berth", 10), ("PowerFacility", 6),
        ("WaterOutlet", 7), ("GuardBlock", 3), ("BerthDetail", 4),
    ]:
        fields = parse_interface(name)
        assert len(fields) >= floor, (
            f"interface {name} parsed to {len(fields)} field(s), expected at least {floor} — "
            f"the parser is broken and the comparisons below would be vacuous"
        )


# ═══ TC-SHAPE-01 ══════════════════════════════════════════════════════════════

def test_tc_shape_01_core_has_every_field_the_ui_declares(client, auth_headers, shape_fixture):
    """Compared against the REAL response, not a Pydantic model.

    The routes build plain dicts, so a model would be a second description of the truth. A
    field the UI reads and the serialiser forgets arrives as `undefined` and renders blank —
    invisible in review, visible to a customer.
    """
    pid, _ = shape_fixture
    ped = _ped(client, auth_headers, pid)

    def check(iface: str, obj: dict, where: str):
        declared = parse_interface(iface)
        missing = [f for f in declared if f not in obj]
        assert not missing, (
            f"{where}: field(s) declared by TS interface {iface} but absent from the "
            f"response — the UI would render these blank:\n"
            + "\n".join(f"  {f}: {declared[f]}" for f in missing)
        )

    check("MarinaPedestal", ped, "pedestals[0]")
    check("GuardBlock", ped["guard"], "pedestals[0].guard")
    check("SharedFacility", ped["light"], "pedestals[0].light")

    assert ped["berths"], "the fixture produced no berths"
    for b in ped["berths"]:
        check("Berth", b, f"berth {b.get('berth_number')}")
        check("PowerFacility", b["power"], f"berth {b.get('berth_number')}.power")

    assert ped["water_outlets"], "the fixture produced no water outlets"
    for w in ped["water_outlets"]:
        check("WaterOutlet", w, f"water {w.get('outlet')}")


def test_tc_shape_02_berth_detail_has_every_field(client, auth_headers, shape_fixture):
    """Berth detail extends Berth, so both halves must be present."""
    _pid, ids = shape_fixture
    r = client.get(f"/api/marina/berths/{ids[0]}", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    for iface in ("Berth", "BerthDetail"):
        declared = parse_interface(iface)
        missing = [f for f in declared if f not in body]
        assert not missing, (
            f"berth detail is missing field(s) from TS interface {iface}:\n"
            + "\n".join(f"  {f}: {declared[f]}" for f in missing)
        )

    for iface, key in (("OutletSpec", "outlet_spec"), ("ConsumptionSummary", "consumption")):
        declared = parse_interface(iface)
        missing = [f for f in declared if f not in body[key]]
        assert not missing, f"{key} is missing {missing} (TS interface {iface})"


# ═══ TC-SHAPE-04 ══════════════════════════════════════════════════════════════

def test_tc_shape_04_non_nullable_fields_are_never_null(client, auth_headers, shape_fixture):
    """A field the TS declares non-nullable must never arrive as null.

    This is the direction that crashes rather than renders blank: the UI calls `.toFixed()` or
    `.toLocaleString()` on it with no guard, because the type said it was safe. Checked across
    BOTH berths in the fixture — one with a socket and one without — since the no-socket
    branch is where nulls appear.
    """
    pid, _ = shape_fixture
    ped = _ped(client, auth_headers, pid)

    def check(iface: str, obj: dict, where: str):
        for field, type_text in parse_interface(iface).items():
            if field not in obj:
                continue        # TC-SHAPE-01 reports absence
            if obj[field] is None and not is_nullable(type_text):
                raise AssertionError(
                    f"{where}.{field} is null, but TS declares it `{type_text}` — the UI "
                    f"will use it without a guard"
                )

    check("MarinaPedestal", ped, "pedestal")
    check("GuardBlock", ped["guard"], "pedestal.guard")
    for b in ped["berths"]:
        check("Berth", b, f"berth {b.get('berth_number')}")
        check("PowerFacility", b["power"], f"berth {b.get('berth_number')}.power")
    for w in ped["water_outlets"]:
        check("WaterOutlet", w, f"water {w.get('outlet')}")


def test_tc_shape_05_unknown_and_null_are_both_reachable(client, auth_headers, shape_fixture):
    """`unknown` is a real state in eleven of our sentences, so it is not an edge case.

    Asserts the UI will actually meet it: a berth with no socket, and a valve the cabinet has
    never described. If these could not occur, the UI's handling of them would be untested
    code that runs for the first time in front of a customer.
    """
    pid, _ = shape_fixture
    ped = _ped(client, auth_headers, pid)

    no_socket = [b for b in ped["berths"] if b["power"]["outlet"] is None]
    assert no_socket, (
        "the fixture has no socket-less berth, so the null-bearing branch of PowerFacility "
        "is never exercised"
    )
    p = no_socket[0]["power"]
    assert p["state"] == "unknown"
    assert p["watts"] is None, "no socket must mean no figure, not 0"
    assert p["available"] is False
    assert p["unavailable_reason"] == "no_socket"

    # The valves have never reported, so their state must be `unknown` — distinctly from
    # `idle`, which would tell a customer the outlet is free.
    assert all(w["state"] == "unknown" for w in ped["water_outlets"]), (
        f"valve states {[w['state'] for w in ped['water_outlets']]} — a valve the cabinet "
        f"has never described must be `unknown`, never `idle`"
    )


# ═══ TC-SHAPE-06 ══════════════════════════════════════════════════════════════

def test_tc_shape_06_the_response_has_no_fields_the_ui_ignores(client, auth_headers,
                                                               shape_fixture):
    """The other direction: a field in the response that the TS does not declare.

    Not a crash, but it means data was added to CORE and nothing renders it — so either the UI
    is missing a change, or the field is dead weight on every request. Both are worth one line
    of attention, and finding out six months later costs more.
    """
    pid, _ = shape_fixture
    ped = _ped(client, auth_headers, pid)

    def check(iface: str, obj: dict, where: str) -> list[str]:
        declared = set(parse_interface(iface))
        return [f"{where}.{k}" for k in obj if k not in declared]

    undeclared: list[str] = []
    undeclared += check("MarinaPedestal", ped, "pedestal")
    undeclared += check("GuardBlock", ped["guard"], "pedestal.guard")
    undeclared += check("SharedFacility", ped["light"], "pedestal.light")
    for b in ped["berths"]:
        undeclared += check("Berth", b, "berth")
        undeclared += check("PowerFacility", b["power"], "berth.power")
    for w in ped["water_outlets"]:
        undeclared += check("WaterOutlet", w, "water")

    assert not undeclared, (
        "CORE sends field(s) no TypeScript interface declares — nothing renders them:\n"
        + "\n".join(f"  {u}" for u in sorted(set(undeclared)))
    )
