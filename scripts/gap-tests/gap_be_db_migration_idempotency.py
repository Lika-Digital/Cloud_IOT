#!/usr/bin/env python3
"""
GAP: Migration idempotency
LAYER: BE<->DB
TOOL: custom Python (no extra deps)

Verifies that _migrate_schema() in backend/app/database.py is safe to call
multiple times without raising exceptions (idempotency guarantee).

A non-idempotent migration would crash on the second startup of the server
after columns already exist, potentially taking the service down.

Exit code 0 = migration is idempotent.
Exit code 1 = migration crashes on second call.
"""
import sys
import os
import tempfile

# Run from repo root
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, REPO_ROOT)

def main():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    tmp_path = tmp.name

    try:
        # Override database URL to use temp file
        os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path}"

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        import backend.app.database as db_mod
        from importlib import reload

        # Patch the engine to point at temp DB
        test_engine = create_engine(
            f"sqlite:///{tmp_path}",
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
        db_mod.engine = test_engine
        db_mod.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

        # First call: creates tables and applies migrations
        db_mod.init_db()
        print("Run 1: init_db() OK")

        # Second call: must be a no-op — all columns already exist
        db_mod._migrate_schema()
        print("Run 2: _migrate_schema() idempotency OK")

        # Third call for good measure
        db_mod._migrate_schema()
        print("Run 3: _migrate_schema() idempotency OK")

        print("PASS: migration is idempotent (safe to re-run on startup)")
        sys.exit(0)

    except Exception as e:
        print(f"FAIL: migration is NOT idempotent — crashes on re-run: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
