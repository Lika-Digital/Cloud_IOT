"""The consumption_source migration — four populations, and the cutoff that splits them.

`consumption_source` and `LEGACY_INTEGRAL_CUTOFF` were designed in eb8ba94 for this migration
and it never ran: cabinet 1 carries 172 of 178 sessions with a NULL source while 149 carry a
figure, so most rows hold a number with nothing saying where it came from.

THE CASE THESE TESTS EXIST FOR is population B. `assert_legacy_allowed` RAISES for any session
started on or after the cutoff, and the comment above it predicts the person who reaches for
the nearest convenient label. A blanket UPDATE makes the migration that person — so B must get
`unknown`, and its figure must MOVE to `energy_kwh_integrated` rather than sit under a label
that session.py:93 documents as never carrying a figure.

The script is driven as a subprocess so what is tested is the real file an operator runs,
including its argument handling and its exit codes.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "stamp_consumption_source.py")
BACKEND = os.path.join(REPO_ROOT, "backend")

# Mirrors meter_register.LEGACY_INTEGRAL_CUTOFF = datetime(2026, 9, 30). Imported there, not
# here, so a drift between the two shows up as a test failure rather than silent agreement.
BEFORE = "2026-09-27 10:00:00"
AFTER = "2026-10-11 08:05:00"

_COLS = """
    id INTEGER PRIMARY KEY, pedestal_id INTEGER, socket_id INTEGER, type TEXT,
    status TEXT, started_at TEXT, ended_at TEXT,
    energy_kwh REAL, water_liters REAL,
    energy_kwh_integrated REAL, water_liters_firmware REAL,
    consumption_source TEXT
"""


def _make_db(tmp_path, rows):
    db = str(tmp_path / "pedestal.db")
    con = sqlite3.connect(db)
    con.execute(f"CREATE TABLE sessions ({_COLS})")
    con.executemany(
        "INSERT INTO sessions (id, status, started_at, type, energy_kwh, water_liters, "
        "energy_kwh_integrated, consumption_source) VALUES (?,?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return db


def _run(db, *extra):
    env = dict(os.environ, PYTHONPATH=BACKEND, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, SCRIPT, "--db", db, *extra],
        capture_output=True, text=True, timeout=120, env=env, cwd=REPO_ROOT,
    )


def _row(db, sid):
    con = sqlite3.connect(db)
    try:
        con.row_factory = sqlite3.Row
        return dict(con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone())
    finally:
        con.close()


# One row in each population, plus one already-labelled row that must be left alone.
#  id, status,      started_at, type,          kwh,  litres, kwh_integrated, source
FIXTURE = [
    (1, "completed", BEFORE, "electricity", 46.106, None, None, None),   # A
    (2, "completed", AFTER,  "electricity",  3.250, None, None, None),   # B
    (3, "completed", AFTER,  "water",         None, 12.5,  None, None),  # B (water)
    (4, "completed", AFTER,  "electricity",   None, None,  None, None),  # C
    (5, "active",    AFTER,  "electricity",   None, None,  None, None),  # D
    (6, "pending",   BEFORE, "electricity",   None, None,  None, None),  # D
    (7, "completed", BEFORE, "electricity",  1.000, None, None, "register"),  # untouched
]


@pytest.fixture
def db(tmp_path):
    return _make_db(tmp_path, FIXTURE)


# ═══ dry run ═════════════════════════════════════════════════════════════════

def test_dry_run_writes_nothing_and_reports_four_counts(db):
    before = [_row(db, i) for i in range(1, 8)]
    r = _run(db)
    assert r.returncode == 0, r.stdout + r.stderr

    out = r.stdout
    assert "DRY RUN" in out
    assert "nothing written" in out
    for key in ("A", "B", "C", "D"):
        assert f"  {key}  " in out, f"population {key} not reported:\n{out}"
    assert "partition all" in out, "the script did not confirm the populations partition"

    after = [_row(db, i) for i in range(1, 8)]
    assert before == after, "the dry run modified the database"


def test_dry_run_counts_are_right(db):
    out = _run(db).stdout
    # A=1 (id 1), B=2 (ids 2,3), C=1 (id 4), D=2 (ids 5,6)
    import re
    counts = {k: int(v) for k, v in re.findall(r"^  ([ABCD])\s+(\d+)\s", out, re.M)}
    assert counts == {"A": 1, "B": 2, "C": 1, "D": 2}, f"{counts}\n{out}"


# ═══ apply ═══════════════════════════════════════════════════════════════════

def test_population_a_is_labelled_integrated_legacy_and_keeps_its_figure(db):
    assert _run(db, "--apply").returncode == 0
    a = _row(db, 1)
    assert a["consumption_source"] == "integrated_legacy"
    assert a["energy_kwh"] == 46.106, "a pre-cutoff figure must be kept, only labelled"
    assert a["energy_kwh_integrated"] == 46.106, (
        "the integral was not copied into the comparison column, so it is filled for some "
        "labelled rows and not others for a reason no reader could reconstruct"
    )


def test_population_b_is_unknown_and_the_figure_MOVES(db):
    """The case the cutoff forbids a blanket stamp for."""
    assert _run(db, "--apply").returncode == 0

    b = _row(db, 2)
    assert b["consumption_source"] == "unknown", (
        "a post-cutoff session was stamped integrated_legacy — assert_legacy_allowed forbids "
        "that label here, and its own message says to fix the register path instead"
    )
    assert b["energy_kwh"] is None, (
        "the figure stayed in energy_kwh under an 'unknown' label. session.py:93 documents "
        "unknown as NEVER carrying a figure, so that row contradicts itself"
    )
    assert b["energy_kwh_integrated"] == 3.250, (
        "the figure was ERASED rather than moved. energy_kwh_integrated exists to hold it"
    )


def test_population_b_water_moves_too(db):
    assert _run(db, "--apply").returncode == 0
    b = _row(db, 3)
    assert b["consumption_source"] == "unknown"
    assert b["water_liters"] is None
    assert b["water_liters_firmware"] == 12.5, "the litres were erased rather than moved"


def test_population_c_is_unknown(db):
    assert _run(db, "--apply").returncode == 0
    c = _row(db, 4)
    assert c["consumption_source"] == "unknown"
    assert c["energy_kwh"] is None


@pytest.mark.parametrize("sid", [5, 6])
def test_population_d_is_left_null(db, sid):
    """An unfinished session's source resolves when it closes. NULL is true meanwhile."""
    assert _run(db, "--apply").returncode == 0
    d = _row(db, sid)
    assert d["consumption_source"] is None, (
        f"session {sid} is {d['status']} and was stamped {d['consumption_source']!r}; nothing "
        f"has derived it yet, so NULL is the honest value"
    )


def test_an_already_labelled_row_is_untouched(db):
    before = _row(db, 7)
    assert _run(db, "--apply").returncode == 0
    assert _row(db, 7) == before, "the migration overwrote an existing label"


def test_apply_is_idempotent(db):
    assert _run(db, "--apply").returncode == 0
    first = [_row(db, i) for i in range(1, 8)]
    r2 = _run(db, "--apply")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert [_row(db, i) for i in range(1, 8)] == first, "a second run changed the data"


# ═══ negative controls ══════════════════════════════════════════════════════

def test_it_refuses_when_the_populations_do_not_partition(tmp_path):
    """The partition check must be able to fail, or it is decoration.

    A row with no source, no figure and a status the four predicates do not cover would be
    left in an unknown state by a migration that did not notice. `status = NULL` is exactly
    that gap: `status = 'completed'` is false and `status <> 'completed'` is also false in
    SQL three-valued logic, so it falls through both C and D.
    """
    db = _make_db(tmp_path, [(1, None, BEFORE, "electricity", None, None, None, None)])
    r = _run(db)
    assert r.returncode == 1, (
        f"a row that no population covers did not trigger a refusal:\n{r.stdout}"
    )
    assert "REFUSED" in r.stdout
    assert "unaccounted for" in r.stdout


@pytest.mark.parametrize("column,setup", [
    ("energy", (1, "completed", AFTER, "electricity", 3.250, None, 9.999, None)),
    ("water",  (1, "completed", AFTER, "water",      None,  12.5,  None,  None)),
])
def test_it_refuses_when_b_would_erase_rather_than_move(tmp_path, column, setup):
    """"Moved, not erased" cannot be honoured when the destination already holds a
    DIFFERENT value — the backfill fills only NULLs, so the clear step would destroy the
    figure. Refusing is the only honest outcome, in the dry run and on --apply alike.
    """
    db = _make_db(tmp_path, [setup])
    if column == "water":
        con = sqlite3.connect(db)
        con.execute("UPDATE sessions SET water_liters_firmware = 99.0 WHERE id = 1")
        con.commit()
        con.close()
    before = _row(db, 1)

    for extra in ((), ("--apply",)):
        r = _run(db, *extra)
        assert r.returncode == 1, f"a conflicting destination did not refuse:\n{r.stdout}"
        assert "REFUSED" in r.stdout and "DIFFERENT value" in r.stdout
        assert _row(db, 1) == before, "a refused run modified the row"


def test_b_with_an_equal_destination_value_is_not_a_conflict(tmp_path):
    """The refusal must not fire when nothing would be lost — the same number is already
    where it is going."""
    db = _make_db(tmp_path, [(1, "completed", AFTER, "electricity", 3.250, None, 3.250, None)])
    assert _run(db, "--apply").returncode == 0
    b = _row(db, 1)
    assert b["consumption_source"] == "unknown"
    assert b["energy_kwh"] is None
    assert b["energy_kwh_integrated"] == 3.250


def test_it_refuses_a_missing_database(tmp_path):
    r = _run(str(tmp_path / "nope.db"))
    assert r.returncode == 1
    assert "no database" in r.stdout


def test_the_cutoff_is_imported_not_copied():
    """A second literal would drift from the guard it has to agree with.

    That is how `cloud_iot` and `cloud-iot` came to coexist in one codebase.
    """
    src = open(SCRIPT, encoding="utf-8").read()
    assert "from app.services.meter_register import" in src
    assert "LEGACY_INTEGRAL_CUTOFF" in src
    assert "datetime(2026, 9, 30" not in src, (
        "the cutoff date is hard-coded in the migration as well as in meter_register"
    )


def test_it_does_not_touch_energy_intervals(tmp_path):
    """The 8675 rows are a documented boundary, not a migration.

    energy_intervals has no consumption_source column and is not getting one: every row in it
    is integral-derived because the ledger froze before the register path wrote one, so the
    boundary is the whole table.
    """
    db = _make_db(tmp_path, FIXTURE)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE energy_intervals (id INTEGER PRIMARY KEY, kwh REAL)")
    con.executemany("INSERT INTO energy_intervals (id, kwh) VALUES (?,?)",
                    [(i, 1.0) for i in range(1, 11)])
    con.commit()
    con.close()

    assert _run(db, "--apply").returncode == 0

    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM energy_intervals").fetchone()[0] == 10
        cols = [r[1] for r in con.execute("PRAGMA table_info(energy_intervals)")]
        assert "consumption_source" not in cols, (
            "the migration added a consumption_source column to energy_intervals"
        )
    finally:
        con.close()

    src = open(SCRIPT, encoding="utf-8").read()
    assert "UPDATE energy_intervals" not in src
