#!/usr/bin/env python3
"""Restore the ERP's API-gateway list on a cabinet to the list approved on 2026-10-14 (spec §16.3b).

MEASURED on cabinet 1, 2026-10-16 (spec §16.3a): 23 endpoints were enabled for the ERP, among them
all four camera endpoints (12 × 200 on the camera routes in 14 days) and the three usage report
endpoints. The configuration approved on 2026-10-14 never reached the cabinet.

TARGET — the 17 ids of 2026-10-14, every one "monitor"; no camera.*, no usage.*. Everything else
enabled today is removed. An id of the target that the cabinet's catalogue does not know is LISTED
and NOT written.

ONLY `external_api_config.allowed_endpoints` (row id 1) changes — one UPDATE of one column inside
BEGIN IMMEDIATE. `active`, `verified`, `webhook_url`, `allowed_events` and the key stay as they are.

DRY RUN by default: prints the current state and the diff old -> new, writes nothing.
--apply requires --backup PATH (a path that does not exist yet): the database is copied there with
SQLite's backup API — consistent while the backend runs, unlike cp on a WAL database — and the copy
must pass PRAGMA integrity_check before anything is written. After writing, the row is read back and
the §13 17b reading is printed; exit 4 if it is not the target. Idempotent: no difference -> nothing
written.

Usage (on the cabinet, as the backend's user):
  sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 fix_gateway_allowed_endpoints.py \\
       --db /opt/cloud-iot/backend/pedestal.db [--apply --backup /path/pedestal.db.pre-gateway-<UTC>]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

TARGET = [
    "pedestals.health", "pedestals.list", "pedestals.status_ext", "berths.list",
    "sessions.active", "sessions.pending", "alarms.active",
    "load.pedestal_get_ext", "load.socket_get_ext", "load.pedestal_alarms_ext",
    "breakers.pedestal_list_ext", "breakers.socket_get_ext", "water.status_ext",
    "sockets.config_list", "valves.config_list", "analytics.daily", "analytics.summary",
]
# Never written by this script, whatever the target says: Phase 1 sends no image or video to the
# ERP (GDPR, owner), and the reports carry customer ids — the owner's decision is open (§16.3a).
NEVER_PREFIXES = ("camera.", "usage.")
DEFAULT_CATALOG = "/opt/cloud-iot/backend/app/services/api_catalog.py"


def load_catalog_ids(path: Path) -> set[str]:
    """The endpoint ids of the catalogue the cabinet RUNS — read from its file, not from here."""
    ns: dict = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)  # nosec B102 — the catalogue file of our own code
    return {e["id"] for e in ns["ENDPOINT_CATALOG"]}


def read_row(con: sqlite3.Connection):
    return con.execute(
        "SELECT allowed_endpoints, active, verified, webhook_url, allowed_events, api_key "
        "FROM external_api_config WHERE id=1").fetchone()


def reading_17b(entries: list[dict]) -> str:
    ids = sorted(e["id"] for e in entries)
    return (f"17b: {len(ids)}\n17b: {ids}\n"
            f"17b: {[i for i in ids if i.startswith('camera.')]}")


def backup(db: Path, dest: Path) -> None:
    if dest.exists():
        sys.exit(f"REFUSED: --backup {dest} already exists — a backup is never overwritten")
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    out = sqlite3.connect(str(dest))
    try:
        src.backup(out)
    finally:
        src.close()
    ok = out.execute("PRAGMA integrity_check").fetchone()[0]
    out.close()
    if ok != "ok":
        sys.exit(f"REFUSED: the backup at {dest} fails integrity_check ({ok}) — nothing written")
    print(f"backup: {dest} (SQLite backup API), integrity_check ok")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--catalog", default=DEFAULT_CATALOG,
                    help="api_catalog.py of the code the cabinet runs")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--backup")
    a = ap.parse_args(argv)

    db = Path(a.db)
    if not db.is_file():
        sys.exit(f"no database at {db}")
    catalog = load_catalog_ids(Path(a.catalog))

    con = sqlite3.connect(str(db))
    row = read_row(con)
    if row is None:
        sys.exit("no external_api_config row id=1 — not created by this script; report it")
    cur = json.loads(row[0] or "[]")
    cur_modes = {e["id"]: e.get("mode") for e in cur}

    print(f"NOW: {len(cur)} endpoint(s) enabled for the ERP; active={row[1]} verified={row[2]} "
          f"webhook_url={'set' if row[3] else 'not set'} "
          f"allowed_events={len(json.loads(row[4] or '[]'))} key={'set' if row[5] else 'not set'}")
    for e in sorted(cur, key=lambda e: e["id"]):
        flag = "   <- image/stream to the ERP" if e["id"].startswith("camera.") else (
            "   <- reports with customer ids" if e["id"].startswith("usage.") else "")
        print(f"  {e['id']:32s} {e.get('mode')}{flag}")

    unknown = [t for t in TARGET if t not in catalog]
    target = [t for t in TARGET if t in catalog and not t.startswith(NEVER_PREFIXES)]
    new = [{"id": t, "mode": "monitor"} for t in target]

    print("\nDIFF old -> new:")
    for t in target:
        old = cur_modes.get(t)
        what = "KEEP" if old == "monitor" else ("ADD" if old is None else f"TO MONITOR (was {old})")
        print(f"  {t:32s} {what}")
    for i in sorted(cur_modes):
        if i not in target:
            print(f"  {i:32s} REMOVE ({cur_modes[i]})")
    for t in unknown:
        print(f"  {t:32s} NOT IN THIS CABINET'S CATALOGUE — listed, not written")
    print(f"\n  total: {len(cur)} -> {len(new)}; active, verified, webhook_url, allowed_events, key: "
          "unchanged")

    if [(e["id"], e.get("mode")) for e in cur] == [(e["id"], e["mode"]) for e in new]:
        print("\nNo difference — nothing written.")
        print(reading_17b(cur))
        return 0
    if not a.apply:
        print("\nDRY RUN — nothing written. Add --apply --backup PATH to write.")
        return 0
    if not a.backup:
        sys.exit("REFUSED: --apply needs --backup PATH — nothing written")

    con.close()
    backup(db, Path(a.backup))

    con = sqlite3.connect(str(db), isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("UPDATE external_api_config SET allowed_endpoints=? WHERE id=1",
                    (json.dumps(new),))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    after_row = read_row(con)
    con.close()

    after = json.loads(after_row[0] or "[]")
    same_rest = tuple(after_row[1:]) == tuple(row[1:])
    print("\nAPPLIED. Read back:")
    print(reading_17b(after))
    if after != new or not same_rest:
        print("DOES NOT MATCH THE TARGET (or another column changed) — restore from the backup "
              "(§13.11) and report", file=sys.stderr)
        return 4
    print("matches the target; every other column unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
