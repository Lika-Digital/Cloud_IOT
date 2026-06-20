"""Usage history + monthly reports (v3.31).

Covers the report service (content, totals, month boundary, blank customer when
the NUC never attributed a session — e.g. Smart Mode off), the admin HTTP
endpoints (history/list/download), admin-only deletion, retention-safety of the
report files, and the disk-guard skip path.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

# Seed/clean through the SAME sessionmakers the HTTP endpoints use (conftest's
# overrides bind get_db/get_user_db to these). Using a separate engine to the
# same SQLite file gave a second connection whose snapshot saw stale rows from
# earlier tests in the full-suite run, so the endpoint read the wrong session.
from conftest import TestSession as _S, TestUserSession as _US

PID = 9100   # dedicated pedestal id so these tests don't collide with others


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """Start each test from a clean reports dir + clean pedestal.

    The reports dir is set process-wide via the REPORTS_DIR env in conftest
    (./tests/test_reports). We wipe it per-test so stale files from earlier
    tests are never served. Also pin the disk guard to "has space" — the real
    one caches its measurement for 30 s and test_disk_guard.py mocks a low
    reading that would otherwise bleed in. Low-space tests override locally.
    """
    monkeypatch.setattr("app.services.disk_guard.has_free_space", lambda: True)

    from app.services.usage_report_service import reports_dir
    d = reports_dir()
    for f in d.glob("*.txt"):
        try:
            f.unlink()
        except OSError:
            pass

    from app.models.pedestal import Pedestal
    from app.models.session import Session as SModel
    db = _S()
    try:
        if db.get(Pedestal, PID) is None:
            db.add(Pedestal(id=PID, name="Usage Test Pedestal", location="Dock U",
                            data_mode="synthetic"))
        db.query(SModel).filter(SModel.pedestal_id == PID).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield


def _seed_session(socket_id, resource, started, ended, *, kwh=None, liters=None,
                  customer_id=None, nfc_user_id=None, status="completed") -> int:
    from app.models.session import Session as SModel
    db = _S()
    try:
        s = SModel(
            pedestal_id=PID, socket_id=socket_id, type=resource, status=status,
            started_at=started, ended_at=ended, energy_kwh=kwh, water_liters=liters,
            customer_id=customer_id, nfc_user_id=nfc_user_id,
        )
        db.add(s); db.commit(); db.refresh(s)
        return s.id
    finally:
        db.close()


def _monitor_headers() -> dict:
    """Mint a JWT for a real (DB-backed) monitor user — require_admin reads the
    role off the DB user, so the user must exist in the test users.db."""
    from app.auth.models import User
    from app.auth.password import hash_password
    from app.auth.tokens import create_access_token
    db = _US()
    try:
        u = db.query(User).filter(User.email == "monitor-usage@test.local").first()
        if u is None:
            u = User(email="monitor-usage@test.local",
                     password_hash=hash_password("monitor1234"),
                     role="monitor", is_active=True)
            db.add(u); db.commit(); db.refresh(u)
        return {"Authorization": f"Bearer {create_access_token(u.id, u.email, 'monitor')}"}
    finally:
        db.close()


# ── service: report rendering ──────────────────────────────────────────────────

def test_report_contains_sections_amounts_and_totals():
    from app.services import usage_report_service as svc
    _seed_session(1, "electricity", datetime(2026, 5, 3, 14, 0), datetime(2026, 5, 3, 16, 0), kwh=3.42)
    _seed_session(1, "electricity", datetime(2026, 5, 8, 9, 0), datetime(2026, 5, 8, 11, 0), kwh=1.88)
    _seed_session(1, "water", datetime(2026, 5, 4, 10, 0), datetime(2026, 5, 4, 10, 30), liters=120.0)

    db = _S()
    try:
        text = svc.build_report_text(db, PID, 2026, 5)
    finally:
        db.close()

    assert "Socket Q1 (electricity)" in text
    assert "Valve V1 (water)" in text
    assert "3.420 kWh" in text and "1.880 kWh" in text
    assert "120.0 L" in text
    # Subtotal + grand total reflect the seeded usage.
    assert "5.300 kWh" in text          # 3.42 + 1.88
    assert "electricity 5.300 kWh across 2 session(s); water 120.0 L across 1 session(s)" in text


def test_report_blank_customer_when_none():
    """Smart-Mode-off / unattributed sessions: customer column is '—'."""
    from app.services import usage_report_service as svc
    _seed_session(2, "electricity", datetime(2026, 5, 6, 8, 0), datetime(2026, 5, 6, 9, 0), kwh=2.0)
    db = _S()
    try:
        text = svc.build_report_text(db, PID, 2026, 5)
    finally:
        db.close()
    assert "customer: —" in text


def test_month_boundary_filtering():
    from app.services import usage_report_service as svc
    _seed_session(1, "electricity", datetime(2026, 5, 31, 23, 0), datetime(2026, 5, 31, 23, 30), kwh=1.0)
    _seed_session(1, "electricity", datetime(2026, 6, 1, 0, 30), datetime(2026, 6, 1, 1, 0), kwh=9.0)
    db = _S()
    try:
        may = svc.usage_rows(db, PID, year=2026, month=5)
        jun = svc.usage_rows(db, PID, year=2026, month=6)
    finally:
        db.close()
    assert [r["energy_kwh"] for r in may] == [1.0]
    assert [r["energy_kwh"] for r in jun] == [9.0]


def test_customer_and_nfc_resolved():
    """When a session has a customer / NFC id, the report names them."""
    from app.services import usage_report_service as svc
    from app.auth.customer_models import Customer
    from app.auth.password import hash_password
    udb = _US()
    try:
        cust = udb.query(Customer).filter(Customer.email == "u-hist@example.com").first()
        if cust is None:
            cust = Customer(email="u-hist@example.com", password_hash=hash_password("x12345678"),
                            name="Marina Guest")
            udb.add(cust); udb.commit(); udb.refresh(cust)
        cid = cust.id
    finally:
        udb.close()

    _seed_session(3, "electricity", datetime(2026, 5, 9, 8, 0), datetime(2026, 5, 9, 9, 0),
                  kwh=4.0, customer_id=cid, nfc_user_id="ERP-777")

    db = _S()
    try:
        with patch("app.auth.user_database.UserSessionLocal", _US):
            text = svc.build_report_text(db, PID, 2026, 5)
    finally:
        db.close()
    assert "Marina Guest" in text
    assert "nfc:ERP-777" in text


# ── HTTP endpoints ─────────────────────────────────────────────────────────────

def test_history_endpoint_returns_rows(client, auth_headers):
    _seed_session(1, "electricity", datetime(2026, 5, 3, 14, 0), datetime(2026, 5, 3, 16, 0), kwh=3.42)
    r = client.get(f"/api/pedestals/{PID}/usage/history?resource=electricity&socket_id=1&month=2026-05",
                   headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["energy_kwh"] == 3.42
    assert rows[0]["socket_id"] == 1
    assert rows[0]["customer_name"] is None


def test_history_endpoint_readable_by_monitor(client):
    # v3.34 — usage history is a read; every operator (incl. read-only monitor)
    # may view it. The role gate must NOT 403 a monitor here.
    r = client.get(f"/api/pedestals/{PID}/usage/history", headers=_monitor_headers())
    assert r.status_code != 403


def test_report_delete_blocks_monitor(client):
    # ...but deleting a monthly report is a control action — monitor is rejected.
    r = client.delete(f"/api/pedestals/{PID}/usage/reports/2026-05", headers=_monitor_headers())
    assert r.status_code == 403


def test_history_endpoint_bad_month(client, auth_headers):
    r = client.get(f"/api/pedestals/{PID}/usage/history?month=2026-13", headers=auth_headers)
    assert r.status_code == 400


def test_report_download_lazy_generate_and_list(client, auth_headers):
    _seed_session(1, "electricity", datetime(2026, 5, 3, 14, 0), datetime(2026, 5, 3, 16, 0), kwh=3.42)
    # No file yet — download lazily generates it.
    r = client.get(f"/api/pedestals/{PID}/usage/reports/2026-05", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    assert "attachment; filename=" in r.headers["content-disposition"]
    assert "USAGE REPORT" in r.text and "3.420 kWh" in r.text

    # Now it appears in the listing.
    rl = client.get(f"/api/pedestals/{PID}/usage/reports", headers=auth_headers)
    assert rl.status_code == 200
    months = [row["month"] for row in rl.json()]
    assert "2026-05" in months


def test_report_delete_admin_only(client, auth_headers):
    _seed_session(1, "electricity", datetime(2026, 5, 3, 14, 0), datetime(2026, 5, 3, 16, 0), kwh=1.0)
    # Generate the file via a download.
    assert client.get(f"/api/pedestals/{PID}/usage/reports/2026-05", headers=auth_headers).status_code == 200

    # Monitor cannot delete.
    assert client.delete(f"/api/pedestals/{PID}/usage/reports/2026-05",
                         headers=_monitor_headers()).status_code == 403
    # Admin can.
    d = client.delete(f"/api/pedestals/{PID}/usage/reports/2026-05", headers=auth_headers)
    assert d.status_code == 200, d.text
    assert d.json()["deleted"] is True
    # Deleting again → 404 (file gone).
    assert client.delete(f"/api/pedestals/{PID}/usage/reports/2026-05",
                         headers=auth_headers).status_code == 404


# ── protection: retention + disk guard ─────────────────────────────────────────

def test_retention_purge_leaves_report_files():
    """The retention sweeper only prunes DB telemetry tables; it must NEVER
    remove usage report files."""
    from app.services import usage_report_service as svc
    from app.services import retention_service
    _seed_session(1, "electricity", datetime(2026, 5, 3, 14, 0), datetime(2026, 5, 3, 16, 0), kwh=1.0)
    db = _S()
    try:
        path = svc.write_report(db, PID, 2026, 5)
    finally:
        db.close()
    assert path is not None and path.exists()

    with patch.object(retention_service, "SessionLocal", _S):
        retention_service.purge_old_data(retention_days=0)
    assert path.exists(), "retention must not delete report files"


def test_disk_guard_skips_write_and_download_507(client, auth_headers):
    from app.services import usage_report_service as svc
    _seed_session(1, "electricity", datetime(2026, 5, 3, 14, 0), datetime(2026, 5, 3, 16, 0), kwh=1.0)
    db = _S()
    try:
        with patch("app.services.disk_guard.has_free_space", return_value=False):
            assert svc.write_report(db, PID, 2026, 5) is None
    finally:
        db.close()

    # The endpoint surfaces a 507 when the guard refuses to generate.
    with patch("app.services.disk_guard.has_free_space", return_value=False):
        r = client.get(f"/api/pedestals/{PID}/usage/reports/2026-05", headers=auth_headers)
    assert r.status_code == 507


def test_generate_due_reports_writes_previous_month():
    from app.services import usage_report_service as svc
    _seed_session(1, "electricity", datetime(2026, 5, 10, 9, 0), datetime(2026, 5, 10, 10, 0), kwh=2.0)
    db = _S()
    try:
        # 'now' = June → previous month is May.
        written = svc.generate_due_reports(db, now=datetime(2026, 6, 2, 0, 5))
        assert svc.report_path(PID, 2026, 5).exists()
        # Idempotent: a second run writes nothing new.
        again = svc.generate_due_reports(db, now=datetime(2026, 6, 2, 0, 5))
    finally:
        db.close()
    assert written >= 1
    assert again == 0


def test_api_catalog_has_usage_entries():
    from app.services.api_catalog import ENDPOINT_CATALOG
    ids = {e["id"] for e in ENDPOINT_CATALOG}
    assert {"usage.history", "usage.reports_list", "usage.report_download"} <= ids
    # All read-only (GET).
    for e in ENDPOINT_CATALOG:
        if e["id"].startswith("usage."):
            assert e["method"] == "GET"
            assert e["allow_bidirectional"] is False
