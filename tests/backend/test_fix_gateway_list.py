"""TC-FGW — scripts/fix_gateway_allowed_endpoints.py restores the ERP's list (spec §16.3b, 2026-10-16).

Run against a THROWAWAY database holding the list measured on cabinet 1 (23 entries, all four
camera.*, three usage.*) — never a real database (rule 16). The catalogue is the repository's own
`api_catalog.py`, as the cabinet's would be.
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "fix_gateway_allowed_endpoints.py"
CATALOG = ROOT / "backend" / "app" / "services" / "api_catalog.py"

TARGET = [
    "pedestals.health", "pedestals.list", "pedestals.status_ext", "berths.list",
    "sessions.active", "sessions.pending", "alarms.active",
    "load.pedestal_get_ext", "load.socket_get_ext", "load.pedestal_alarms_ext",
    "breakers.pedestal_list_ext", "breakers.socket_get_ext", "water.status_ext",
    "sockets.config_list", "valves.config_list", "analytics.daily", "analytics.summary",
]
MISSING_ON_CABINET = {"berths.list", "breakers.pedestal_list_ext", "breakers.socket_get_ext",
                      "sockets.config_list", "valves.config_list"}
EXTRA_ON_CABINET = ["berths.occupancy_ext", "breakers.marina_alarms_ext", "load.marina_alarms_ext",
                    "load.socket_history_ext", "usage.history", "usage.report_download",
                    "usage.reports_list", "camera.frame_ext", "camera.snapshot", "camera.stream",
                    "camera.stream_ext"]
CABINET_23 = [t for t in TARGET if t not in MISSING_ON_CABINET] + EXTRA_ON_CABINET


def _db(tmp_path: Path, entries: list[str]) -> Path:
    p = tmp_path / "pedestal.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE external_api_config (id INTEGER PRIMARY KEY, api_key TEXT, "
                "webhook_url TEXT, allowed_endpoints TEXT, allowed_events TEXT, active INTEGER, "
                "verified INTEGER)")
    lst = [{"id": i, "mode": "bidirectional" if i == "alarms.active" else "monitor"} for i in entries]
    con.execute("INSERT INTO external_api_config VALUES (1, 'KEY', 'https://erp.example/hook', ?, ?, 1, 1)",
                (json.dumps(lst), json.dumps(["heartbeat", "temperature_reading"])))
    con.commit()
    con.close()
    return p


def _row(p: Path):
    con = sqlite3.connect(p)
    r = con.execute("SELECT api_key, webhook_url, allowed_endpoints, allowed_events, active, verified "
                    "FROM external_api_config WHERE id=1").fetchone()
    con.close()
    return r


def _run(*args, catalog: Path = CATALOG):
    return subprocess.run([sys.executable, str(SCRIPT), "--catalog", str(catalog), *args],
                          capture_output=True, text=True)


def test_cabinet_fixture_is_the_measured_list():
    assert len(CABINET_23) == 23


def test_tc_fgw_01_dry_run_shows_the_diff_and_writes_nothing(tmp_path):
    p = _db(tmp_path, CABINET_23)
    before = _row(p)
    r = _run("--db", str(p))
    assert r.returncode == 0, r.stderr
    assert _row(p) == before
    out = r.stdout
    assert "NOW: 23 endpoint(s)" in out
    assert "camera.frame_ext" in out and "image/stream to the ERP" in out
    for i in EXTRA_ON_CABINET:
        assert f"{i}" in out and "REMOVE" in out
    for i in MISSING_ON_CABINET:
        assert any(line.strip().startswith(i) and "ADD" in line for line in out.splitlines()), i
    assert "TO MONITOR (was bidirectional)" in out
    assert "DRY RUN — nothing written" in out


def test_tc_fgw_02_apply_without_backup_is_refused(tmp_path):
    p = _db(tmp_path, CABINET_23)
    before = _row(p)
    r = _run("--db", str(p), "--apply")
    assert r.returncode != 0 and "needs --backup" in (r.stdout + r.stderr)
    assert _row(p) == before


def test_tc_fgw_03_apply_writes_the_17_and_nothing_else(tmp_path):
    p = _db(tmp_path, CABINET_23)
    before = _row(p)
    bak = tmp_path / "pedestal.db.pre-gateway"
    r = _run("--db", str(p), "--apply", "--backup", str(bak))
    assert r.returncode == 0, r.stdout + r.stderr
    after = _row(p)
    got = json.loads(after[2])
    assert [e["id"] for e in got] == TARGET
    assert {e["mode"] for e in got} == {"monitor"}
    assert not any(e["id"].startswith(("camera.", "usage.")) for e in got)
    # every other column untouched: key, webhook_url, allowed_events, active, verified
    assert (after[0], after[1], after[3], after[4], after[5]) == (before[0], before[1], before[3],
                                                                   before[4], before[5])
    # the backup is the database as it was, and intact
    con = sqlite3.connect(bak)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT allowed_endpoints FROM external_api_config").fetchone()[0] == before[2]
    con.close()
    assert "17b: 17" in r.stdout and "17b: []" in r.stdout


def test_tc_fgw_04_a_backup_is_never_overwritten(tmp_path):
    p = _db(tmp_path, CABINET_23)
    bak = tmp_path / "exists.db"
    bak.write_bytes(b"earlier backup")
    r = _run("--db", str(p), "--apply", "--backup", str(bak))
    assert r.returncode != 0 and "already exists" in (r.stdout + r.stderr)
    assert bak.read_bytes() == b"earlier backup"
    assert json.loads(_row(p)[2])[0]["id"] == CABINET_23[0]


def test_tc_fgw_05_an_id_the_catalogue_lacks_is_listed_not_written(tmp_path):
    src = CATALOG.read_text(encoding="utf-8")
    cat = tmp_path / "api_catalog.py"
    cat.write_text("\n".join(l for l in src.splitlines() if '"valves.config_list"' not in l),
                   encoding="utf-8")
    p = _db(tmp_path, CABINET_23)
    r = _run("--db", str(p), "--apply", "--backup", str(tmp_path / "b.db"), catalog=cat)
    assert r.returncode == 0, r.stderr
    assert "valves.config_list" in r.stdout and "NOT IN THIS CABINET'S CATALOGUE" in r.stdout
    ids = [e["id"] for e in json.loads(_row(p)[2])]
    assert "valves.config_list" not in ids and len(ids) == 16


def test_tc_fgw_06_second_run_writes_nothing(tmp_path):
    p = _db(tmp_path, CABINET_23)
    assert _run("--db", str(p), "--apply", "--backup", str(tmp_path / "b1.db")).returncode == 0
    once = _row(p)
    r = _run("--db", str(p), "--apply", "--backup", str(tmp_path / "b2.db"))
    assert r.returncode == 0 and "No difference — nothing written" in r.stdout
    assert _row(p) == once
    assert not (tmp_path / "b2.db").exists()


@pytest.mark.parametrize("bad", ["camera.frame_ext", "usage.history"])
def test_tc_fgw_07_camera_and_usage_never_written_even_if_targeted(tmp_path, bad, monkeypatch):
    """The prefixes are refused by the script itself, not only by the target list."""
    src = SCRIPT.read_text(encoding="utf-8").replace('"analytics.summary",\n]', f'"analytics.summary", "{bad}",\n]')
    assert bad in src
    script = tmp_path / "fix.py"
    script.write_text(src, encoding="utf-8")
    p = _db(tmp_path, CABINET_23)
    r = subprocess.run([sys.executable, str(script), "--catalog", str(CATALOG), "--db", str(p),
                        "--apply", "--backup", str(tmp_path / "b.db")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert bad not in [e["id"] for e in json.loads(_row(p)[2])]
