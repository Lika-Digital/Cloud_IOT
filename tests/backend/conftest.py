"""
Test fixtures for Cloud_IOT backend.

Strategy:
- Use FastAPI TestClient (synchronous)
- Override get_db and get_user_db with isolated in-memory SQLite databases
- Patch MQTT service start/stop to no-ops (avoids needing a broker)
- Seed minimum data: admin user, pedestal, billing config, contract template
- Expose token fixture helpers for admin and customer auth
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ── Set test env vars BEFORE importing the app ───────────────────────────────
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-ci")
os.environ.setdefault("DEFAULT_ADMIN_EMAIL", "admin@test.local")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "testadmin1234")
os.environ.setdefault("MQTT_BROKER_HOST", "localhost")
# v3.31 — keep usage-report files out of the real ./reports dir. Set via env
# (read at Settings construction) so every imported module tree agrees, rather
# than monkeypatching one settings object.
#
# 2026-10-11 — the reports dir, like the test DBs, lives in a PER-RUN directory. It used to be
# ./tests/test_reports, shared by every pytest process on the machine, and test_usage_history
# wipes it per test — so a second concurrent run deleted the first run's reports mid-test.
from _test_paths import TEST_DIR, TEST_DB, TEST_USER_DB, REPORTS_DIR as _TEST_REPORTS_DIR  # noqa: E402
os.environ.setdefault("REPORTS_DIR", _TEST_REPORTS_DIR)
# 2026-10-12 — the app's OWN engines point at the per-run test databases. The dependency
# overrides below reach only routes that take get_db / get_user_db; app code that opens
# SessionLocal() / UserSessionLocal() by hand used the real engines: 5 tests reached the real
# backend/data/users.db, 223 reached ./pedestal.db (a stray file in the repo root). Set here,
# before anything imports the app. Proof: test_test_isolation.py.
os.environ.setdefault("DATABASE_URL", TEST_DB)
os.environ.setdefault("USER_DATABASE_URL", TEST_USER_DB)
# 2026-10-13 — guard messages are accepted only from the backend's own worker instance; the
# fake-worker tests speak as this one.
os.environ.setdefault("GUARD_INSTANCE_ID", "test-guard-instance")

# ── Test DB URLs (file-based so cross-module fixtures share state) ────────────
# Per-run, from _test_paths — see its docstring for the concurrent-run race this closes.

test_engine      = create_engine(TEST_DB,      connect_args={"check_same_thread": False})
test_user_engine = create_engine(TEST_USER_DB, connect_args={"check_same_thread": False})

TestSession     = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
TestUserSession = sessionmaker(autocommit=False, autoflush=False, bind=test_user_engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


def override_get_user_db():
    db = TestUserSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session", autouse=True)
def setup_test_databases():
    """Create all tables in both test databases, seed baseline data."""
    # Patch MQTT and background services at import time
    with (
        patch("app.services.mqtt_client.mqtt_service.start"),
        patch("app.services.mqtt_client.mqtt_service.stop"),
        patch("app.services.simulator_manager.simulator_manager.stop"),
    ):
        from app.database import Base, import_all_models
        from app.auth.user_database import UserBase

        # v3.44 — ONE list, shared with production.
        #
        # This block used to enumerate the models itself, and the two lists had
        # already drifted in BOTH directions: conftest had `pilot_assignment` and
        # `database.init_db` did not, while `berth_assignment` was added to production
        # and every marina test failed with "no such table". A model's table either
        # exists in both databases or the tests are not testing the application.
        import_all_models()

        Base.metadata.drop_all(bind=test_engine)
        Base.metadata.create_all(bind=test_engine)
        UserBase.metadata.drop_all(bind=test_user_engine)
        UserBase.metadata.create_all(bind=test_user_engine)

        # Seed pedestal (mobile_enabled=True so pedestal-status endpoint returns it)
        from app.models.pedestal import Pedestal
        db = TestSession()
        try:
            if not db.query(Pedestal).first():
                db.add(Pedestal(
                    name="Test Pedestal",
                    location="Test Berth",
                    data_mode="synthetic",
                    mobile_enabled=True,
                ))
                db.commit()
        finally:
            db.close()

        # Seed admin user + billing config + contract template
        from app.auth.models import User
        from app.auth.customer_models import BillingConfig
        from app.auth.contract_models import ContractTemplate
        from app.auth.password import hash_password
        user_db = TestUserSession()
        try:
            if not user_db.query(User).first():
                user_db.add(User(
                    email="admin@test.local",
                    password_hash=hash_password("testadmin1234"),
                    role="admin",
                ))
                user_db.commit()
            if not user_db.get(BillingConfig, 1):
                user_db.add(BillingConfig(id=1, kwh_price_eur=0.30, liter_price_eur=0.015))
                user_db.commit()
            if not user_db.query(ContractTemplate).first():
                user_db.add(ContractTemplate(
                    title="Test Agreement",
                    body="Test contract body.",
                    validity_days=365,
                    active=True,
                    notify_on_register=True,
                ))
                user_db.commit()
        finally:
            user_db.close()

    yield

    # Teardown: drop test DB files. On Windows, sqlite + SQLAlchemy pool can
    # keep file handles for a beat after dispose(); ignore that rather than
    # failing the session with PermissionError — the files get clobbered on
    # the next run anyway.
    test_engine.dispose()
    test_user_engine.dispose()
    #
    # The whole per-run directory goes, and ONLY this run's: the old fixed paths meant a run
    # finishing first deleted the databases another run was still using. Best-effort: on
    # Windows other modules' engines can still hold handles here, so tests/run_tests.sh also
    # removes the directory after the pytest process exits. A standalone run may leave one
    # small cloudiot-tests-* directory in the temp folder; that is the price of not sharing.
    import shutil
    shutil.rmtree(TEST_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def client(setup_test_databases):
    """TestClient with DB dependencies overridden and MQTT patched."""
    with (
        patch("app.services.mqtt_client.mqtt_service.start"),
        patch("app.services.mqtt_client.mqtt_service.stop"),
        patch("app.services.simulator_manager.simulator_manager.stop"),
        patch("app.services.berth_analyzer.run_berth_analysis", return_value=MagicMock()),
    ):
        from app.main import app
        from app.database import get_db
        from app.auth.user_database import get_user_db

        app.dependency_overrides[get_db]      = override_get_db
        app.dependency_overrides[get_user_db] = override_get_user_db

        from starlette.testclient import TestClient
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c

        app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def admin_token(client):
    """Direct JWT for admin user — bypasses OTP."""
    from app.auth.tokens import create_access_token
    from app.auth.models import User
    db = TestUserSession()
    try:
        user = db.query(User).filter(User.email == "admin@test.local").first()
        return create_access_token(user.id, user.email, user.role)
    finally:
        db.close()


@pytest.fixture(scope="session")
def customer_token(client):
    """Register + login a test customer, return JWT."""
    r = client.post("/api/customer/auth/register", json={
        "email": "testcustomer@example.com",
        "password": "customer1234",
        "name": "Test Customer",
        "ship_name": "Test Vessel",
    })
    assert r.status_code in (200, 400)  # 400 = already exists (re-run)
    r2 = client.post("/api/customer/auth/login", json={
        "email": "testcustomer@example.com",
        "password": "customer1234",
    })
    assert r2.status_code == 200
    return r2.json()["access_token"]


@pytest.fixture(scope="session")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def cust_headers(customer_token):
    return {"Authorization": f"Bearer {customer_token}"}
