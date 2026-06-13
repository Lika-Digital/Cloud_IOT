"""Tests for v3.16 config backup/restore (config_service).

Locks in: redaction-by-default, opt-in full export, restore round-trip,
redacted-secret preservation on restore, and the external-API redacted→inactive
guard. The service opens its own SessionLocal/UserSessionLocal, so we patch both
to the test DBs (same pattern as other service tests).
"""
from __future__ import annotations

import pytest
from unittest.mock import patch

from app.services import config_service
from app.services.config_service import REDACTED
from app.auth.models import SmtpConfig
from app.auth.customer_models import BillingConfig
from app.models.external_api import ExternalApiConfig
from tests.backend.conftest import TestSession, TestUserSession


@pytest.fixture(autouse=True)
def route_to_test_dbs(tmp_path):
    with patch.object(config_service, "SessionLocal", TestSession), \
         patch.object(config_service, "UserSessionLocal", TestUserSession), \
         patch.object(config_service, "BACKUP_DIR", tmp_path / "backups"):
        yield
    # cleanup rows created by these tests so other suites are unaffected
    u = TestUserSession(); u.query(SmtpConfig).delete(); u.commit(); u.close()
    i = TestSession(); i.query(ExternalApiConfig).delete(); i.commit(); i.close()


def _set_smtp(password="realpw"):
    u = TestUserSession()
    u.query(SmtpConfig).delete()
    u.add(SmtpConfig(id=1, host="smtp.example", port=587, username="u",
                     password=password, from_email="f@x"))
    u.commit(); u.close()


def _set_extapi(api_key="jwt-secret-key", active=1):
    i = TestSession()
    i.query(ExternalApiConfig).delete()
    i.add(ExternalApiConfig(id=1, api_key=api_key, active=active, verified=1,
                            allowed_endpoints="[]", allowed_events="[]"))
    i.commit(); i.close()


def test_export_redacts_secrets_by_default():
    _set_smtp("realpw")
    _set_extapi("jwt-secret-key")
    b = config_service.export_config(include_secrets=False)
    assert b["config"]["smtp_config"][0]["password"] == REDACTED
    assert b["config"]["external_api_config"][0]["api_key"] == REDACTED


def test_export_full_includes_secrets():
    _set_smtp("realpw")
    b = config_service.export_config(include_secrets=True)
    assert b["config"]["smtp_config"][0]["password"] == "realpw"


def test_round_trip_restores_billing():
    u = TestUserSession()
    bc = u.query(BillingConfig).first()
    original = bc.kwh_price_eur
    bc.kwh_price_eur = 0.42
    u.commit(); u.close()

    bundle = config_service.export_config()

    u = TestUserSession(); u.query(BillingConfig).first().kwh_price_eur = 0.99; u.commit(); u.close()
    config_service.import_config(bundle)

    u = TestUserSession()
    restored = u.query(BillingConfig).first().kwh_price_eur
    u.query(BillingConfig).first().kwh_price_eur = original  # leave clean for other tests
    u.commit(); u.close()
    assert restored == 0.42


def test_import_preserves_existing_secret_when_redacted():
    _set_smtp("realpw")
    redacted = config_service.export_config(include_secrets=False)
    _set_smtp("changed-pw")            # live secret changes after the redacted export
    config_service.import_config(redacted)
    u = TestUserSession(); pw = u.query(SmtpConfig).first().password; u.close()
    assert pw == "changed-pw"          # redacted placeholder was skipped, not written
    assert pw != REDACTED


def test_external_api_redacted_forces_inactive():
    _set_extapi("jwt-x", active=1)
    redacted = config_service.export_config(include_secrets=False)
    config_service.import_config(redacted)
    i = TestSession(); cfg = i.query(ExternalApiConfig).first(); i.close()
    assert cfg.active == 0             # gateway must not stay active with no real key


def test_backup_written_and_listed():
    path = config_service.write_backup(config_service.export_config())
    assert path.exists()
    assert path.name in [b["filename"] for b in config_service.list_backups()]
