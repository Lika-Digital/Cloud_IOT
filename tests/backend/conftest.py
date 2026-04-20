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

# ── Test DB URLs (file-based so cross-module fixtures share state) ────────────
TEST_DB     = "sqlite:///./tests/test_pedestal.db"
TEST_USER_DB = "sqlite:///./tests/test_users.db"

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
        from app.database import Base
        from app.auth.user_database import UserBase
        from app.models import pedestal, session as session_model, sensor_reading  # noqa
        from app.models import pedestal_config, active_alarm, error_log, external_api, pilot_assignment, session_audit  # noqa
        from app.auth import models, customer_models, contract_models, berth_models  # noqa

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
    for path in ["tests/test_pedestal.db", "tests/test_users.db"]:
        try:
            os.remove(path)
        except (FileNotFoundError, PermissionError):
            pass


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
