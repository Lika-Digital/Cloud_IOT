"""The app under test reaches ONLY the per-run test databases — 2026-10-12.

FOUND 2026-10-12 (block 1, part B): /ws looked users up in UserSessionLocal — the app's own
engine on backend/data/users.db — instead of through get_user_db, which conftest overrides.
The old WS tests passed only because the test admin's id matched an active user in the
developer's real file: a check that could not fail, because it looked at the wrong database.

MEASURED the same day, over the whole suite, by counting connection checkouts on the app's own
engines per test: 5 tests in 4 files reached the real users.db, and 223 tests in 62 files
reached the app's pedestal.db engine — `sqlite:///./pedestal.db`, which under pytest is a stray
file in the repo root. Every one of them through APP code that opens a session by hand
(UserSessionLocal() / SessionLocal() in routes, services and background tasks), which the
dependency overrides never reach.

THE FIX is not one patch per call site: conftest points the app's OWN engines at the per-run
test files before the app is imported (DATABASE_URL, USER_DATABASE_URL). A session opened by
hand then lands in the test database like everything else.

  TC-ISO-01  the app's users.db engine is the per-run test users.db
  TC-ISO-02  the app's pedestal.db engine is the per-run test pedestal.db

Both FAIL on the code before this change (shown 2026-10-12).
"""
from __future__ import annotations

import os

from _test_paths import TEST_DB_PATH, TEST_USER_DB_PATH


def _same(engine_url, path: str) -> bool:
    db = engine_url.database or ""
    return os.path.normcase(os.path.abspath(db)) == os.path.normcase(os.path.abspath(path))


def test_tc_iso_01_app_users_engine_is_the_test_database(client):
    from app.auth.user_database import user_engine
    assert _same(user_engine.url, TEST_USER_DB_PATH), (
        f"the app's users.db engine is {user_engine.url}, not the test database — code that "
        f"opens UserSessionLocal() by hand reads a real file")


def test_tc_iso_02_app_pedestal_engine_is_the_test_database(client):
    from app.database import engine
    assert _same(engine.url, TEST_DB_PATH), (
        f"the app's pedestal.db engine is {engine.url}, not the test database — code that "
        f"opens SessionLocal() by hand reads a real file")
