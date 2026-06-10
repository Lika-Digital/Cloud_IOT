"""Regression guard for v3.14 sensor_readings hot-path indexes.

complete() filters readings by session_id on every session close, and
analytics + the v3.13 retention prune filter by (pedestal_id, timestamp).
These indexes must exist or the high-volume table is full-scanned. This test
fails if a future change drops the index declarations.
"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from tests.backend.conftest import TestSession

EXPECTED = {"ix_sensor_readings_session", "ix_sensor_readings_pedestal_time"}


def _index_names(conn):
    rows = conn.execute(text("PRAGMA index_list('sensor_readings')")).fetchall()
    return {r[1] for r in rows}  # column 1 = index name


def test_model_declares_sensor_readings_indexes():
    """Fresh schema (conftest create_all) carries the indexes from the model."""
    db = TestSession()
    try:
        names = _index_names(db)
    finally:
        db.close()
    assert EXPECTED.issubset(names), f"missing indexes: {EXPECTED - names}"


def test_migration_creates_indexes_idempotently(tmp_path):
    """On an existing DB that lacks them, the CREATE INDEX IF NOT EXISTS DDL
    (run twice) adds them without error."""
    eng = create_engine(f"sqlite:///{tmp_path}/legacy.db")
    ddl = [
        "CREATE TABLE sensor_readings (id INTEGER PRIMARY KEY, session_id INTEGER, "
        "pedestal_id INTEGER NOT NULL, socket_id INTEGER, type TEXT, value REAL, "
        "unit TEXT, timestamp DATETIME)",
        "CREATE INDEX IF NOT EXISTS ix_sensor_readings_session ON sensor_readings(session_id)",
        "CREATE INDEX IF NOT EXISTS ix_sensor_readings_pedestal_time ON sensor_readings(pedestal_id, timestamp)",
    ]
    try:
        with eng.begin() as conn:
            for stmt in ddl:
                conn.execute(text(stmt))
            # Idempotent — running the index DDL again must not raise.
            for stmt in ddl[1:]:
                conn.execute(text(stmt))
        with eng.connect() as conn:
            assert EXPECTED.issubset(_index_names(conn))
    finally:
        eng.dispose()
