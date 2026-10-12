#!/usr/bin/env python3
"""Stamp `consumption_source` on sessions that were never labelled. DRY RUN BY DEFAULT.

WHY THIS EXISTS
---------------
`consumption_source` and `LEGACY_INTEGRAL_CUTOFF` were designed in eb8ba94 for exactly this
migration and the migration never ran. On cabinet 1, 172 of 178 sessions carry a NULL source
while 149 carry a figure — so most rows hold a number with nothing saying where it came from,
which is the defect the column was added to prevent.

The figures are not erased. They are labelled, or moved to the column built to hold them.

THE CUTOFF FORBIDS A BLANKET STAMP
----------------------------------
`meter_register.assert_legacy_allowed` RAISES for any session started on or after
LEGACY_INTEGRAL_CUTOFF (2026-09-30), and its own error text says why:

    "A post-cutoff session with no usable register is UNKNOWN — fix the register path rather
     than relabelling the figure as an estimate."

The comment above it predicts the person who reaches for the nearest convenient label. A
blanket UPDATE would make this script that person. So the population splits four ways:

  A  no source · has a figure · started BEFORE the cutoff
     -> "integrated_legacy". Exactly what the label was built for: these sessions were
        running when the register change deployed, so they have no opening reading and their
        register delta is genuinely unknowable, but the old integral exists.

  B  no source · has a figure · started ON OR AFTER the cutoff
     -> "unknown", AND the figure moves to `energy_kwh_integrated` / `water_liters_firmware`.
        The label is forbidden for these. And session.py:93 documents "unknown" as never
        carrying a figure, so leaving a number in `energy_kwh` under that label would be
        self-contradictory. `energy_kwh_integrated` exists precisely to hold it — "kept
        PERMANENTLY alongside the register delta so the two can be compared" — so nothing is
        lost, it is relocated to the column that describes it.

  C  no source · no figure · status completed
     -> "unknown". It finished and produced nothing derivable. That is terminal and worth
        saying.

  D  no source · no figure · pending / active / denied
     -> LEFT NULL. Nothing has derived it yet, which is true, and an active session's source
        resolves when it closes.

Populations A and B also get `energy_kwh` copied into `energy_kwh_integrated` where that
column is NULL, so every labelled row carries its integral in the same place regardless of
which side of the cutoff it fell on. A comparison column filled for some rows and not others,
for a reason no reader could reconstruct, is worse than one filled consistently.

WHAT THIS DOES NOT TOUCH
------------------------
`energy_intervals`. That table has no `consumption_source` column and is not getting one.
Every row in it is integral-derived, because the ledger froze at 2026-10-10 16:12:59 UTC
before the register path wrote a single one — so the boundary is the whole table, which is a
documented statement (see the model docstring) and not a migration.

USAGE
    python scripts/stamp_consumption_source.py                  # DRY RUN — prints the counts
    python scripts/stamp_consumption_source.py --apply          # writes
    python scripts/stamp_consumption_source.py --db /path/to/pedestal.db

On a cabinet:
    /opt/cloud-iot/backend/.venv/bin/python3 scripts/stamp_consumption_source.py \
        --db /opt/cloud-iot/backend/pedestal.db

EXIT CODES
    0  dry run completed, or apply succeeded
    1  refused — a precondition failed (see the message)
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime

# The cutoff is imported, never copied: a second literal would drift from the guard it is
# supposed to agree with, which is how `cloud_iot` and `cloud-iot` came to coexist.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _c in (os.path.join(os.path.dirname(_HERE), "backend"), "/opt/cloud-iot/backend"):
    if os.path.isdir(os.path.join(_c, "app")):
        sys.path.insert(0, _c)
        break

try:
    from app.services.meter_register import (
        LEGACY_INTEGRAL_CUTOFF, SOURCE_INTEGRATED_LEGACY, SOURCE_UNKNOWN,
    )
except ImportError as e:  # pragma: no cover - import-path problem, not logic
    print(f"FAILED: cannot import meter_register ({e}).")
    print("Run from the repo root, or pass the backend dir on PYTHONPATH.")
    sys.exit(1)

CUTOFF_SQL = LEGACY_INTEGRAL_CUTOFF.strftime("%Y-%m-%d %H:%M:%S")


# ── population predicates, as SQL fragments so the dry run and the apply cannot diverge ──

_HAS_FIGURE = "(energy_kwh IS NOT NULL OR water_liters IS NOT NULL)"
_NO_FIGURE = "(energy_kwh IS NULL AND water_liters IS NULL)"
_NO_SOURCE = "consumption_source IS NULL"

POPULATIONS = {
    "A": {
        "where": f"{_NO_SOURCE} AND {_HAS_FIGURE} AND started_at < ?",
        "params": (CUTOFF_SQL,),
        "label": SOURCE_INTEGRATED_LEGACY,
        "move_figure": False,
        "why": f"has a figure, started before {LEGACY_INTEGRAL_CUTOFF.date()} — the label's "
               f"intended population",
    },
    "B": {
        "where": f"{_NO_SOURCE} AND {_HAS_FIGURE} AND started_at >= ?",
        "params": (CUTOFF_SQL,),
        "label": SOURCE_UNKNOWN,
        "move_figure": True,
        "why": f"has a figure, started on/after {LEGACY_INTEGRAL_CUTOFF.date()} — the guard "
               f"FORBIDS integrated_legacy here; figure moves to the _integrated column",
    },
    "C": {
        "where": f"{_NO_SOURCE} AND {_NO_FIGURE} AND status = 'completed'",
        "params": (),
        "label": SOURCE_UNKNOWN,
        "move_figure": False,
        "why": "completed and produced nothing derivable — terminal, worth saying",
    },
    "D": {
        "where": f"{_NO_SOURCE} AND {_NO_FIGURE} AND status <> 'completed'",
        "params": (),
        "label": None,
        "move_figure": False,
        "why": "not finished — NULL is true, and resolves when it closes. LEFT ALONE",
    },
}


def _count(cur, pop) -> int:
    cur.execute(f"SELECT COUNT(*) FROM sessions WHERE {pop['where']}", pop["params"])
    return cur.fetchone()[0]


def _sample(cur, pop, n=4):
    cur.execute(
        f"SELECT id, status, started_at, energy_kwh, water_liters, energy_kwh_integrated "
        f"FROM sessions WHERE {pop['where']} ORDER BY id DESC LIMIT {n}", pop["params"],
    )
    return cur.fetchall()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(
        os.path.dirname(_HERE), "backend", "pedestal.db"))
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default is a dry run)")
    args = ap.parse_args()

    if not os.path.isfile(args.db):
        print(f"FAILED: no database at {args.db}")
        return 1

    mode = "APPLY" if args.apply else "DRY RUN"
    print("=" * 78)
    print(f"stamp consumption_source — {mode}")
    print(f"  database : {args.db}")
    print(f"  cutoff   : {CUTOFF_SQL}  (imported from meter_register, not copied)")
    print("=" * 78)

    con = sqlite3.connect(args.db)
    try:
        cur = con.cursor()

        cur.execute("SELECT COUNT(*) FROM sessions")
        total = cur.fetchone()[0]
        cur.execute(f"SELECT COUNT(*) FROM sessions WHERE {_NO_SOURCE}")
        unlabelled = cur.fetchone()[0]
        print(f"\nsessions: {total} total, {unlabelled} with no consumption_source\n")

        counts = {}
        for key in ("A", "B", "C", "D"):
            pop = POPULATIONS[key]
            n = _count(cur, pop)
            counts[key] = n
            action = "LEAVE NULL" if pop["label"] is None else f'-> "{pop["label"]}"'
            if pop["move_figure"]:
                action += " + figure moved to the _integrated column"
            print(f"  {key}  {n:>5}  {action}")
            print(f"        {pop['why']}")
            if n:
                print(f"        sample (id, status, started_at, kwh, litres, kwh_integrated):")
                for row in _sample(cur, pop):
                    print(f"          {row}")
            print()

        covered = sum(counts.values())
        if covered != unlabelled:
            print(f"REFUSED: the four populations cover {covered} rows but {unlabelled} have "
                  f"no source. They must partition exactly, or something is unaccounted for "
                  f"and this script would leave it in an unknown state.")
            return 1
        print(f"the four populations partition all {unlabelled} unlabelled rows exactly\n")

        # B promises "moved, not erased". That cannot be honoured for a row whose destination
        # column already holds a DIFFERENT value: the backfill below only fills NULLs, so the
        # clear step would then erase the figure with nowhere to put it. Refuse rather than
        # pick a winner — neither number may be discarded on this script's judgement.
        popB = POPULATIONS["B"]
        cur.execute(
            f"SELECT id, energy_kwh, energy_kwh_integrated, water_liters, water_liters_firmware "
            f"FROM sessions WHERE {popB['where']} AND ("
            f"  (energy_kwh IS NOT NULL AND energy_kwh_integrated IS NOT NULL"
            f"   AND energy_kwh_integrated <> energy_kwh)"
            f" OR (water_liters IS NOT NULL AND water_liters_firmware IS NOT NULL"
            f"   AND water_liters_firmware <> water_liters))", popB["params"])
        conflicts = cur.fetchall()
        if conflicts:
            print(f"REFUSED: {len(conflicts)} population-B row(s) already hold a DIFFERENT value "
                  f"in the column the figure would move to. Moving would erase one of the two "
                  f"numbers. Resolve these by hand first:")
            print("  (id, energy_kwh, energy_kwh_integrated, water_liters, water_liters_firmware)")
            for row in conflicts[:20]:
                print(f"  {row}")
            return 1

        if counts["B"] == 0:
            print("NOTE: population B is EMPTY. The cutoff question was moot on this "
                  "database — no session with a figure started on or after the cutoff.\n")

        if not args.apply:
            print("DRY RUN — nothing written. Re-run with --apply to write.")
            return 0

        # ── apply ────────────────────────────────────────────────────────────
        for key in ("A", "B"):
            pop = POPULATIONS[key]
            # Preserve the integral in the column built for it, where it is not already set.
            cur.execute(
                f"UPDATE sessions SET energy_kwh_integrated = energy_kwh "
                f"WHERE {pop['where']} AND energy_kwh IS NOT NULL "
                f"AND energy_kwh_integrated IS NULL", pop["params"])
            print(f"  {key}: energy_kwh_integrated backfilled on {cur.rowcount} row(s)")
            cur.execute(
                f"UPDATE sessions SET water_liters_firmware = water_liters "
                f"WHERE {pop['where']} AND water_liters IS NOT NULL "
                f"AND water_liters_firmware IS NULL", pop["params"])
            print(f"  {key}: water_liters_firmware backfilled on {cur.rowcount} row(s)")

        for key in ("A", "B", "C"):
            pop = POPULATIONS[key]
            cur.execute(
                f"UPDATE sessions SET consumption_source = ? WHERE {pop['where']}",
                (pop["label"],) + pop["params"])
            print(f"  {key}: labelled {cur.rowcount} row(s) \"{pop['label']}\"")

        # B only: the figure must not remain under an "unknown" label.
        popB = POPULATIONS["B"]
        cur.execute(
            f"UPDATE sessions SET energy_kwh = NULL, water_liters = NULL "
            f"WHERE consumption_source = ? AND started_at >= ? AND {_HAS_FIGURE}",
            (SOURCE_UNKNOWN, CUTOFF_SQL))
        print(f"  B: cleared the reported figure on {cur.rowcount} row(s) "
              f"(preserved above as the _integrated value)")

        con.commit()

        cur.execute(f"SELECT COUNT(*) FROM sessions WHERE {_NO_SOURCE}")
        left = cur.fetchone()[0]
        print(f"\nremaining with no source: {left}  (expected {counts['D']} — population D)")
        if left != counts["D"]:
            print("WARNING: that does not match. Investigate before trusting the result.")
            return 1
        print("APPLIED.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
