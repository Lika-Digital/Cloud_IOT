"""Regression guard for v3.14 SQLite WAL + busy_timeout PRAGMAs.

apply_sqlite_pragmas() must put every new connection into WAL with a 5 s
busy_timeout and synchronous=NORMAL, so the MQTT write loop does not block
dashboard reads and contended writes wait instead of failing with
'database is locked'.
"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from app.database import apply_sqlite_pragmas


def test_pragmas_applied_to_new_connection(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/t.db")
    apply_sqlite_pragmas(eng)
    try:
        with eng.connect() as conn:
            journal = conn.execute(text("PRAGMA journal_mode")).scalar()
            busy = conn.execute(text("PRAGMA busy_timeout")).scalar()
            sync = conn.execute(text("PRAGMA synchronous")).scalar()
    finally:
        eng.dispose()
    assert str(journal).lower() == "wal"
    assert busy == 5000
    assert sync == 1  # NORMAL


def test_app_engines_have_pragmas_registered():
    """The real app engines must have WAL applied (listener registered)."""
    from app.database import engine
    with engine.connect() as conn:
        assert str(conn.execute(text("PRAGMA journal_mode")).scalar()).lower() == "wal"
