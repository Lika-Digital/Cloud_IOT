"""v3.35 — energy interval ledger + daily billing. REGISTER-BASED since v3.43.

Rewritten rather than adjusted. Each interval row is now a delta of the meter's own
cumulative register, not a slice of a power x time integral — so the SUM of a session's
rows equals its reported figure by construction (TC-EIV-10), instead of the ledger and
the session total being derived from two different sources that could drift.

`_mk_session(energy_kwh=X)` therefore means "the register has advanced X kWh since this
session opened": it seeds the opening reading AND the socket's current reading. The
delta arithmetic under test is unchanged; only where the numbers come from is.


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


# An arbitrary non-zero opening reading. Non-zero on purpose: a real cabinet's register is
# never 0 (the capture showed 481.760 / 103.380 / 257.500), and a test that only ever starts
# from 0 would pass even if the code forgot to subtract the opening value.
REG_BASE = 500.0


def _set_register(socket_id: int, value: float | None) -> None:
    """Set the socket's cumulative register. None simulates an unreadable meter."""
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        cfg = db.query(SocketConfig).filter(
            SocketConfig.pedestal_id == PID,
            SocketConfig.socket_id == socket_id).first()
        if cfg is None:
            cfg = SocketConfig(pedestal_id=PID, socket_id=socket_id)
            db.add(cfg)
        cfg.meter_energy_kwh = value
        db.commit()
    finally:
        db.close()


def _mk_session(socket_id=1, *, energy_kwh=0.0, energy_logged_kwh=0.0,
                customer_id=None, nfc_user_id=None, origin=None, status="active") -> int:
    db = _S()
    try:
        s = SModel(
            pedestal_id=PID, socket_id=socket_id, type="electricity", status=status,
            started_at=datetime.utcnow() - timedelta(hours=1),
            energy_kwh=energy_kwh, energy_logged_kwh=energy_logged_kwh,
            customer_id=customer_id, nfc_user_id=nfc_user_id, origin=origin,
            # v3.43 — the opening register reading, captured at activation in production.
            meter_energy_start_kwh=REG_BASE,
        )
        db.add(s); db.commit(); db.refresh(s)
        sid = s.id
    finally:
        db.close()
    # The register now reads base + whatever this session has consumed.
    _set_register(socket_id, REG_BASE + energy_kwh)
    return sid


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


def test_flush_never_double_counts_when_no_new_energy():
    """The high-water mark still prevents double-counting — what changed is the zero row.

    Under the old integral-based logger a second flush with nothing new returned None. Now it
    logs a MEASURED ZERO, because the register was readable and reported no further draw, and
    that is an observation worth keeping (v3.43). The property that matters is unchanged and is
    what this asserts: the energy is counted exactly once.
    """
    sid = _mk_session(energy_kwh=2.5)
    db = _S()
    try:
        s = db.get(SModel, sid)
        first = eis.flush_session_interval(db, s, now=datetime.utcnow()); db.commit()
        second = eis.flush_session_interval(db, s, now=datetime.utcnow()); db.commit()
        assert abs(first.kwh - 2.5) < 1e-6
        assert second is not None and second.kwh == 0.0, \
            "a readable register with no further draw is a measured zero, not a skipped row"
    finally:
        db.close()
    rows = _intervals(sid)
    assert abs(sum(r.kwh for r in rows) - 2.5) < 1e-6, \
        "the 2.5 kWh must be counted exactly once across all rows"


def test_flush_logs_only_the_growth_delta():
    sid = _mk_session(energy_kwh=2.5)
    db = _S()
    try:
        s = db.get(SModel, sid)
        eis.flush_session_interval(db, s, now=datetime.utcnow()); db.commit()
        _set_register(1, REG_BASE + 4.0)   # the meter advanced, not a derived field
        row2 = eis.flush_session_interval(db, s, now=datetime.utcnow()); db.commit()
        assert row2 is not None and abs(row2.kwh - 1.5) < 1e-6
    finally:
        db.close()
    assert len(_intervals(sid)) == 2


def test_flush_writes_a_real_zero_interval():
    """A register that did not move is a MEASUREMENT of zero, and gets a row (v3.43).

    It says the meter was read during this window and reported no draw — a boat plugged
    in and drawing nothing. Suppressing it would make "zero" indistinguishable from "we
    could not read the meter" in the ledger, and those need different responses.
    """
    sid = _mk_session(energy_kwh=0.0)
    db = _S()
    try:
        s = db.get(SModel, sid)
        row = eis.flush_session_interval(db, s, now=datetime.utcnow())
        db.commit()
        assert row is not None, "a readable register reporting no draw must still be logged"
        assert row.kwh == 0.0
    finally:
        db.close()
    assert len(_intervals(sid)) == 1


def test_flush_unreadable_register_writes_nothing_and_marks_unknown():
    """And the other half of that distinction: unreadable is NOT zero.

    No row is written, and the session is marked unknown — one unreadable boundary makes
    the whole session unknown, because the sum of a partial set is not the total.
    """
    from app.services import meter_register as mr

    sid = _mk_session(energy_kwh=1.0)
    _set_register(1, None)                 # meter stopped reporting
    db = _S()
    try:
        s = db.get(SModel, sid)
        assert eis.flush_session_interval(db, s, now=datetime.utcnow()) is None
        assert s.consumption_source == mr.SOURCE_UNKNOWN
        db.commit()
    finally:
        db.close()
    assert _intervals(sid) == [], "an unreadable register must not produce a zero row"


def test_flush_final_keeps_a_tiny_delta_rather_than_rounding_it_away():
    """A final flush logs the exact remainder, however small.

    The sum of a session's rows must equal its reported figure (TC-EIV-10), so the last
    fraction of a kWh cannot be dropped for being below the logging threshold.
    """
    sid = _mk_session(energy_kwh=0.0001)
    db = _S()
    try:
        s = db.get(SModel, sid)
        row = eis.flush_session_interval(db, s, now=datetime.utcnow(), final=True)
        db.commit()
        assert row is not None and abs(row.kwh - 0.0001) < 1e-9
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


# ── TC-EIV-10 — the property that keeps the two from drifting ─────────────────

def test_tc_eiv_10_interval_sum_equals_the_session_figure():
    """The sum of a session's interval rows equals its reported consumption.

    This is the assertion that stops the ledger and the session total drifting apart when
    someone changes one and not the other — which is exactly how they came to disagree: the
    session total moved to register deltas while the intervals were still slicing an
    integral. Both now derive from the same monotonic register, so this holds by
    construction rather than by care, and this test is what notices if that stops being
    true.
    """
    from app.services import meter_register as mr
    from app.services.session_service import session_service

    sid = _mk_session(energy_kwh=0.0)

    # Three checkpoints while the meter climbs, then completion.
    for reading in (REG_BASE + 1.5, REG_BASE + 4.25, REG_BASE + 4.25, REG_BASE + 7.0):
        _set_register(1, reading)
        db = _S()
        try:
            eis.flush_session_interval(db, db.get(SModel, sid), now=datetime.utcnow())
            db.commit()
        finally:
            db.close()

    db = _S()
    try:
        s = db.get(SModel, sid)
        session_service.complete(db, s)
        reported = s.energy_kwh
        source = s.consumption_source
    finally:
        db.close()

    assert source == mr.SOURCE_REGISTER, f"expected a register-derived figure, got {source}"
    assert reported is not None and abs(reported - 7.0) < 1e-6, \
        f"session figure {reported} is not the register delta of 7.0 kWh"

    rows = _intervals(sid)
    total = sum(r.kwh for r in rows)
    assert abs(total - reported) < 1e-6, (
        f"the ledger says {total} kWh across {len(rows)} interval(s) but the session reports "
        f"{reported} kWh. The financial record must not contradict its own session total."
    )
    # One of those checkpoints saw no movement, and it is a real zero row, not a gap.
    assert any(r.kwh == 0.0 for r in rows), \
        "the unchanged checkpoint should appear as a measured zero"
