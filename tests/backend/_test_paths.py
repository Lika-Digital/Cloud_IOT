"""Per-run test paths — the ONE place a test may learn where the test databases live.

WHY THIS EXISTS
---------------
Until 2026-10-11 every test module hard-coded ``sqlite:///./tests/test_pedestal.db``
(31 files) and conftest pointed REPORTS_DIR at ``./tests/test_reports``. Relative to CWD,
so EVERY pytest process on the machine shared one database file and one reports folder.
Two concurrent runs — the pre-push gate in the background while a file is run standalone
to diagnose — raced: one run's drop_all / teardown / report wipe landed in the middle of
the other's tests, and unrelated modules failed with "no such table: socket_configs" or
"table sensor_readings already exists", then passed on retry.

Two full gates started simultaneously against the old layout reproduced it; see
tests/evidence/2026-10-11_shared_test_db_race/.

HOW IT WORKS
------------
The first import in a process creates a fresh temp directory and records it in
CLOUD_IOT_TEST_DIR. Any later import — a second module object for the same file under a
different import name, or a subprocess a test spawns, which inherits the environment —
reads the variable instead of creating a second directory. Without that, a test and its
child process would disagree about where the database is.

Never write a test DB path as a literal. Import it from here.
"""
from __future__ import annotations

import os
import tempfile

_ENV = "CLOUD_IOT_TEST_DIR"

TEST_DIR = os.environ.get(_ENV) or ""
if not TEST_DIR:
    TEST_DIR = tempfile.mkdtemp(prefix="cloudiot-tests-")
    os.environ[_ENV] = TEST_DIR
os.makedirs(TEST_DIR, exist_ok=True)

TEST_DB_PATH = os.path.join(TEST_DIR, "test_pedestal.db")
TEST_USER_DB_PATH = os.path.join(TEST_DIR, "test_users.db")
REPORTS_DIR = os.path.join(TEST_DIR, "test_reports")

# SQLAlchemy URLs. Forward slashes: sqlite:/// + a Windows absolute path with backslashes
# works, but one spelling keeps the URLs greppable and comparable.
TEST_DB = "sqlite:///" + TEST_DB_PATH.replace("\\", "/")
TEST_USER_DB = "sqlite:///" + TEST_USER_DB_PATH.replace("\\", "/")
