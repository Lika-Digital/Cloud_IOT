"""TC-LEG-01..04 — scripts/mark_legacy_reports.py, driven as a real subprocess.

The five report files on cabinet 1 are history: they get a header, never a regeneration. The
header must say what is true of EACH file (partial? sessions missing?), the body must stay the
original bytes, and the mtime — which the API lists as "generated_at" — must not move.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "mark_legacy_reports.py"

# Shaped like the old code's output (pedestal-1_2026-05.txt on the cabinet: 459 bytes, empty).
OLD_EMPTY = ("=" * 64 + "\nUSAGE REPORT — Pedestal 1  (cabinet MAR_KRK_ORM_01)\nMonth: 2026-05  (UTC)\n"
             "Generated: 2026-06-19T10:00:00Z\nRecords: completed sessions only\n" + "=" * 64 +
             "\n\nNo completed sessions for this month.\n\n" + "-" * 64 +
             "\nTOTALS: electricity 0.000 kWh across 0 session(s); water 0.0 L across 0 session(s)\n")
OLD_PARTIAL = ("=" * 64 + "\nUSAGE REPORT — Pedestal 1  (cabinet MAR_KRK_ORM_01)\nMonth: 2026-08  (UTC)\n"
               "Generated: 2026-08-24T09:00:00Z\nRecords: completed sessions only\n" + "=" * 64 +
               "\n\n=== Socket Q1 (electricity) ===\n"
               "2026-08-03 09:00 -> 2026-08-03 10:00         0.000 kWh   customer: —\n"
               "  Subtotal: 1 session(s), 0.000 kWh\n")
NEW_FORMAT = "USAGE REPORT — x\nMonth: 2026-09  (UTC)\nGenerated: 2026-10-01T00:05:00Z\nStatus: FINAL\n"


def _rig(tmp_path: Path):
    d = tmp_path / "reports"; d.mkdir()
    (d / "pedestal-1_2026-05.txt").write_text(OLD_EMPTY, encoding="utf-8")
    (d / "pedestal-1_2026-08.txt").write_text(OLD_PARTIAL, encoding="utf-8")
    (d / "pedestal-1_2026-09.txt").write_text(NEW_FORMAT, encoding="utf-8")
    (d / "pedestal-1_2026-09.staff.txt").write_text(NEW_FORMAT, encoding="utf-8")
    old = 1_750_000_000
    for p in d.iterdir():
        os.utime(p, (old, old))
    db = tmp_path / "pedestal.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, pedestal_id INT, status TEXT, started_at TEXT)")
    rows = [(1, "completed", "2026-05-03 09:00:00"), (1, "completed", "2026-05-10 09:00:00"),
            (1, "completed", "2026-05-20 09:00:00"), (1, "denied", "2026-05-21 09:00:00"),
            (1, "completed", "2026-08-03 09:00:00"), (1, "completed", "2026-08-28 09:00:00")]
    c.executemany("INSERT INTO sessions (pedestal_id,status,started_at) VALUES (?,?,?)", rows)
    c.commit(); c.close()
    return d, db, old


def _run(d, db, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), "--reports-dir", str(d), "--db", str(db),
                           "--today", "2026-10-20", *extra],
                          capture_output=True, text=True, encoding="utf-8")


def test_tc_leg_01_dry_run_writes_nothing_and_prints_each_sha(tmp_path):
    d, db, _ = _rig(tmp_path)
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    r = _run(d, db)
    assert r.returncode == 0, r.stderr
    assert {p.name: p.read_bytes() for p in d.iterdir()} == before
    for name in ("pedestal-1_2026-05.txt", "pedestal-1_2026-08.txt"):
        assert hashlib.sha256(before[name]).hexdigest() in r.stdout, r.stdout
    assert "skip   pedestal-1_2026-09.txt" in r.stdout          # new format: never legacy
    assert "2026-09.staff.txt" not in r.stdout                  # staff files are not even listed


def test_tc_leg_02_header_says_what_is_true_of_each_file(tmp_path):
    d, db, _ = _rig(tmp_path)
    assert _run(d, db, "--apply").returncode == 0
    may = (d / "pedestal-1_2026-05.txt").read_text(encoding="utf-8")
    aug = (d / "pedestal-1_2026-08.txt").read_text(encoding="utf-8")
    # May: generated after the month, but the DB has 3 completed sessions the file never showed.
    assert "INCOMPLETE: the database holds 3 completed session(s) that started in 2026-05" in may
    assert "this report shows 0" in may and "PARTIAL" not in may
    assert "Also 1 session(s) started in 2026-05 that did not end as 'completed'" in may
    # August: generated on the 24th — partial — and the DB has one more session than it shows.
    assert "PARTIAL: generated 2026-08-24, before 2026-08 was over." in aug
    assert "holds 2 completed session(s)" in aug and "this report shows 1" in aug
    assert "NOT a source for billing" in may and "NOT MEASURED" in aug


def test_tc_leg_03_body_bytes_and_mtime_are_preserved(tmp_path):
    d, db, old = _rig(tmp_path)
    originals = {p.name: p.read_bytes() for p in d.iterdir()}
    r = _run(d, db, "--apply")
    assert r.returncode == 0 and r.stdout.count("body unchanged: yes; mtime kept: yes") == 2, r.stdout
    for name in ("pedestal-1_2026-05.txt", "pedestal-1_2026-08.txt"):
        after = (d / name).read_bytes()
        assert after.endswith(originals[name])
        assert f"SHA256 of this file before the header: {hashlib.sha256(originals[name]).hexdigest()}" \
            in after.decode("utf-8")
        assert int((d / name).stat().st_mtime) == old
    assert (d / "pedestal-1_2026-09.txt").read_bytes() == originals["pedestal-1_2026-09.txt"]


def test_tc_leg_04_idempotent(tmp_path):
    d, db, _ = _rig(tmp_path)
    _run(d, db, "--apply")
    once = {p.name: p.read_bytes() for p in d.iterdir()}
    r = _run(d, db, "--apply")
    assert r.returncode == 0 and "marked: 0" in r.stdout, r.stdout
    assert {p.name: p.read_bytes() for p in d.iterdir()} == once
