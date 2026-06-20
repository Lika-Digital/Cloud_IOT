"""v3.35 — energy interval ledger + daily billing.

Covers the checkpoint math (delta vs energy_logged_kwh high-water mark, restart-
safe & idempotent), empty-interval skipping, origin labelling, the immediate
flush inside session_service.complete(), the interval logger tick, and the daily
billing aggregation endpoint.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from conftest import TestSession as _S, TestUserSession as _US

from app.models.session import Session as SModel
from app.models.energy_interval import EnergyInterval
from app.services import energy_interval_service as eis

PID = 9200


@pytest.fixture(autouse=True)
def _isolate():
    from app.models.pedestal import Pedestal
    db = _S()
    try:
        if db.get(Pedestal, PID) is None:
            db.add(Pedestal(id=PID, name="Energy Test Pedestal", location="Dock E",
                            data_mode="synthetic"))
        db.query(EnergyInterval).filter(EnergyInterval.pedestal_id == PID).delete(synchronize_session=False)
        db.query(SModel).filter(SModel.pedestal_id == PID).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield


def _mk_session(socket_id=1, *, energy_kwh=0.0, energy_logged_kwh=0.0,
                customer_id=None, nfc_user_id=None, origin=None, status="active") -> int:
    db = _S()
    try:
        s = SModel(
            pedestal_id=PID, socket_id=socket_id, type="electricity", status=status,
            started_at=datetime.utcnow() - timedelta(hours=1),
            energy_kwh=energy_kwh, energy_logged_kwh=energy_logged_kwh,
            customer_id=customer_id, nfc_user_id=nfc_user_id, origin=origin,
        )
        db.add(s); db.commit(); db.refresh(s)
        return s.id
    finally:
        db.close()


def _intervals(session_id):
    # Filter by PID too: the session-scoped test DB reuses deleted session
    # rowids, so a fresh session_id can collide with another pedestal's stale
    # interval rows. Scoping to PID keeps this test's view clean.
    db = _S()
    try:
        return db.query(EnergyInterval).filter(
            EnergyInterval.session_id == session_id,
            EnergyInterval.pedestal_id == PID,
        ).order_by(EnergyInterval.id).all()
    finally:
        db.close()


# ── checkpoint math ────────────────────────────────────────────────────────────

def test_flush_writes_delta_and_advances_mark():
    sid = _mk_session(energy_kwh=2.5)
    db = _S()
    try:
        s = db.get(SModel, sid)
        row = eis.flush_session_interval(db, s, now=datetime.utcnow())
        db.commit()
        assert row is not None
        assert abs(row.kwh - 2.5) < 1e-6
        assert abs(s.energy_logged_kwh - 2.5) < 1e-6
    finally:
        db.close()
    assert len(_intervals(sid)) == 1


def test_flush_idempotent_when_no_new_energy():
    sid = _mk_session(energy_kwh=2.5)
    db = _S()
    try:
        s = db.get(SModel, sid)
        eis.flush_session_interval(db, s, now=datetime.utcnow()); db.commit()
        second = eis.flush_session_interval(db, s, now=datetime.utcnow()); db.commit()
        assert second is None
    finally:
        db.close()
    assert len(_intervals(sid)) == 1


def test_flush_logs_only_the_growth_delta():
    sid = _mk_session(energy_kwh=2.5)
    db = _S()
    try:
        s = db.get(SModel, sid)
        eis.flush_session_interval(db, s, now=datetime.utcnow()); db.commit()
        s.energy_kwh = 4.0; db.commit()
        row2 = eis.flush_session_interval(db, s, now=datetime.utcnow()); db.commit()
        assert row2 is not None and abs(row2.kwh - 1.5) < 1e-6
    finally:
        db.close()
    assert len(_intervals(sid)) == 2


def test_flush_skips_empty_interval():
    sid = _mk_session(energy_kwh=0.0)
    db = _S()
    try:
        s = db.get(SModel, sid)
        assert eis.flush_session_interval(db, s, now=datetime.utcnow()) is None
        db.commit()
    finally:
        db.close()
    assert _intervals(sid) == []


def test_flush_final_advances_mark_even_when_tiny():
    sid = _mk_session(energy_kwh=0.0001)   # below _MIN_LOG_KWH
    db = _S()
    try:
        s = db.get(SModel, sid)
        row = eis.flush_session_interval(db, s, now=datetime.utcnow(), final=True)
        db.commit()
        assert row is None
        assert abs(s.energy_logged_kwh - 0.0001) < 1e-9
    finally:
        db.close()


# ── origin labelling ────────────────────────────────────────────────────────────

def test_origin_labels():
    db = _S()
    try:
        assert eis.derive_origin(SModel(customer_id=5)) == "customer"
        assert eis.derive_origin(SModel(nfc_user_id="erp-7")) == "nfc"
        assert eis.derive_origin(SModel(origin="standalone")) == "berth-marina"
        assert eis.derive_origin(SModel()) == "operator"
    finally:
        db.close()


# ── immediate flush on completion ───────────────────────────────────────────────

def test_complete_flushes_final_interval():
    from app.services.session_service import session_service
    sid = _mk_session(energy_kwh=3.0)
    db = _S()
    try:
        s = db.get(SModel, sid)
        session_service.complete(db, s)
        assert s.status == "completed"
    finally:
        db.close()
    rows = _intervals(sid)
    assert len(rows) == 1 and abs(rows[0].kwh - 3.0) < 1e-6


# ── interval logger tick ────────────────────────────────────────────────────────

def test_interval_tick_writes_for_active(monkeypatch):
    monkeypatch.setattr(eis, "SessionLocal", _S)
    sid = _mk_session(energy_kwh=1.25)
    eis._interval_tick(datetime.utcnow())
    rows = _intervals(sid)
    assert len(rows) == 1 and abs(rows[0].kwh - 1.25) < 1e-6


# ── daily billing endpoint ──────────────────────────────────────────────────────

def _seed_interval(socket_id, day, kwh, *, origin, customer_id=None, berth_ref=None, session_id=None):
    db = _S()
    try:
        db.add(EnergyInterval(
            pedestal_id=PID, socket_id=socket_id, session_id=session_id,
            origin=origin, customer_id=customer_id, berth_ref=berth_ref,
            interval_start=day, interval_end=day + timedelta(minutes=15), kwh=kwh,
        ))
        db.commit()
    finally:
        db.close()


def test_daily_billing_aggregates(client, auth_headers):
    # Collision-free date — no other test writes intervals here, so a stale
    # snapshot of the per-test cleanup can't perturb the aggregate.
    d = datetime(2031, 7, 7, 10, 0)
    _seed_interval(2, d, 1.0, origin="berth-marina", berth_ref="B-12")
    _seed_interval(2, d + timedelta(minutes=15), 0.5, origin="berth-marina", berth_ref="B-12")
    _seed_interval(3, d, 2.0, origin="customer", customer_id=1)

    # Price can be mutated by other tests (shared BillingConfig) — read it back.
    price = client.get("/api/billing/config", headers=auth_headers).json()["kwh_price_eur"]

    r = client.get("/api/billing/daily", params={"start": "2031-07-07", "end": "2031-07-07"},
                   headers=auth_headers)
    assert r.status_code == 200, r.text
    rows = [x for x in r.json() if x["pedestal_id"] == PID]
    by_socket = {x["socket_id"]: x for x in rows}
    # Socket 2 berth-marina: 1.0 + 0.5 = 1.5 kWh, cost = kwh * current price.
    assert abs(by_socket[2]["kwh"] - 1.5) < 1e-6
    assert by_socket[2]["origin"] == "berth-marina" and by_socket[2]["berth_ref"] == "B-12"
    assert abs(by_socket[2]["cost_eur"] - round(1.5 * price, 4)) < 1e-6
    # Socket 3 customer: 2.0 kWh
    assert abs(by_socket[3]["kwh"] - 2.0) < 1e-6 and by_socket[3]["origin"] == "customer"


def test_daily_billing_readable_by_monitor(client):
    from app.auth.tokens import create_access_token
    from app.auth.models import User
    from app.auth.password import hash_password
    db = _US()
    try:
        u = db.query(User).filter(User.email == "mon-bill@test.local").first()
        if not u:
            u = User(email="mon-bill@test.local", password_hash=hash_password("x12345678"),
                     role="monitor", is_active=True)
            db.add(u); db.commit(); db.refresh(u)
        hdr = {"Authorization": f"Bearer {create_access_token(u.id, u.email, 'monitor')}"}
    finally:
        db.close()
    assert client.get("/api/billing/daily", headers=hdr).status_code == 200
