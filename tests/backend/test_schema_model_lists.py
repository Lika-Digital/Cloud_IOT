"""Startup creates EVERY table — the two model lists cannot silently drift (R2).

pedestal.db and users.db each get their schema from one `create_all`, and each `create_all`
only knows the models that were imported before it ran. The import lists are hand-kept in
two places — `import_all_models()` (database.py) and `init_user_db()` (user_database.py).
Today both are complete. Nothing kept them so: v3.44 already fixed one drift of exactly this
shape, and a missing model here does not fail on cabinet 1, which has every table already. It
fails on the next FRESH cabinet, which boots with a table missing.

The check runs the real startup order — `init_db()` then `init_user_db()`, as lifespan does
(main.py) — in a FRESH interpreter, with each `create_all` replaced by a recorder. A fresh
interpreter is the point: inside pytest, conftest has already imported every model, so the
metadata would be complete whatever the lists said and the test could never fail.

Expected tables come from the source, not from an import: every class in backend/app that
assigns `__tablename__` and inherits Base or UserBase.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

from _test_paths import TEST_DIR

BACKEND = Path(__file__).resolve().parents[2] / "backend"

_PROBE = r"""
import json, sys
from unittest.mock import patch
from app import database
from app.auth import user_database

seen = {}
def recorder(name, metadata):
    def _create_all(*a, **k):
        seen[name] = sorted(metadata.tables)   # what create_all WOULD create, at that moment
    return _create_all

with patch.object(database.Base.metadata, "create_all", recorder("Base", database.Base.metadata)), \
     patch.object(user_database.UserBase.metadata, "create_all",
                  recorder("UserBase", user_database.UserBase.metadata)), \
     patch.object(database, "_migrate_schema", lambda: None), \
     patch.object(user_database, "_migrate_user_schema", lambda: None):
    database.init_db()
    user_database.init_user_db()

print("PROBE:" + json.dumps(seen))
"""


def _declared_tables() -> dict[str, set[str]]:
    """{base name: {tablename}} for every model class in backend/app, read from source."""
    out: dict[str, set[str]] = {"Base": set(), "UserBase": set()}
    for path in (BACKEND / "app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            name = None
            for stmt in node.body:
                if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Name)
                        and stmt.targets[0].id == "__tablename__"
                        and isinstance(stmt.value, ast.Constant)):
                    name = stmt.value.value
            if name is None:
                continue
            bases = {b.id for b in node.bases if isinstance(b, ast.Name)}
            hit = bases & set(out)
            assert len(hit) == 1, (
                f"{path.relative_to(BACKEND)}:{node.lineno} class {node.name} declares "
                f"__tablename__={name!r} but inherits {sorted(bases) or 'nothing named'} — "
                f"this test only knows Base and UserBase; teach it the new base")
            out[hit.pop()].add(name)
    return out


def _tables_at_create_all() -> dict[str, list[str]]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(BACKEND)
    # Engines are lazy and create_all is replaced, so nothing connects — but point the
    # main DB at the per-run dir anyway, so a regression in that assumption cannot touch
    # a real pedestal.db.
    env["DATABASE_URL"] = "sqlite:///" + os.path.join(TEST_DIR, "schema_probe.db").replace("\\", "/")
    r = subprocess.run([sys.executable, "-c", _PROBE], cwd=TEST_DIR, env=env,
                       capture_output=True, text=True, timeout=120)
    line = next((l for l in r.stdout.splitlines() if l.startswith("PROBE:")), None)
    assert r.returncode == 0 and line, f"probe failed:\n{r.stdout}\n{r.stderr}"
    return json.loads(line[len("PROBE:"):])


def test_source_scan_finds_models_on_both_bases():
    # Negative control for the scan itself: if it found nothing, the comparison below
    # would pass vacuously.
    d = _declared_tables()
    assert "sessions" in d["Base"] and "energy_intervals" in d["Base"]
    assert "users" in d["UserBase"] and "service_reviews" in d["UserBase"]


def test_startup_create_all_sees_every_declared_table():
    declared = _declared_tables()
    seen = _tables_at_create_all()
    assert set(seen) == {"Base", "UserBase"}, f"a create_all was never called: {seen}"
    for base in ("Base", "UserBase"):
        missing = declared[base] - set(seen[base])
        assert not missing, (
            f"{base}: create_all at startup would NOT create {sorted(missing)}. A fresh "
            f"cabinet boots without them. Add the module to "
            f"{'import_all_models() in database.py' if base == 'Base' else 'init_user_db() in user_database.py'}.")
