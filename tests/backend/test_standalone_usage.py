"""Standalone usage recording (v3.32).

When Smart Mode is OFF the Opta runs the sockets and emits no control session,
but it reports the meter. The standalone-usage watchdog turns sustained draw
into a usage session (origin="standalone", customer blank) and completes it when
the draw stops — so the consumption shows in Usage History in both modes.

FINDING 8 (v3.46): this docstring used to say the watchdog "integrates energy (power x
time, since the firmware reports energyKwh=0)". Both halves are now false.

The firmware's cumulative register is live — cabinet 1 reads 275.87 -> 275.88 kWh over
twelve minutes, about 50 W, which fits inside the V x I apparent-power bound — while the
reported `powerKw` was measured 35-88x above what voltage and current permit. So the
register is the trustworthy source and the integral is the fabricated one, which is the
reverse of what this file claimed.

Since v3.46 the watchdog CAPTURES THE OPENING REGISTER (it bypasses activate(), so it calls
_capture_start_register directly) and the session's reported figure is the register delta.
The power integral survives only as `energy_kwh_integrated`, a comparison figure never
reported to the ERP. See tests/backend/test_register_chain.py.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from conftest import TestSession as _S

PID = 9200
# Fixed test clock — every tick below is expressed relative to this instant.
T0 = datetime(2026, 6, 19, 12, 0, 0)


@pytest.fixture(autouse=True)
def _isolate():
    from app.models.pedestal import Pedestal
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    from app.models.session import Session as SModel
    from app.services import mqtt_handlers as mh

    mh._standalone_usage_last.clear()
    mh._standalone_usage_low_since.clear()
    mh._meter_energy_last.clear()

    db = _S()
    try:
        if db.get(Pedestal, PID) is None:
            db.add(Pedestal(id=PID, name="Standalone Test", location="Dock S", data_mode="synthetic"))
        db.query(SModel).filter(SModel.pedestal_id == PID).delete(synchronize_session=False)
        db.query(SocketConfig).filter(SocketConfig.pedestal_id == PID).delete(synchronize_session=False)
        db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == PID).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield


def _set_mode(smart: bool):
    from app.models.pedestal_config import PedestalConfig
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter_by(pedestal_id=PID).first()
        if cfg is None:
            cfg = PedestalConfig(pedestal_id=PID, opta_client_id="MAR_STANDALONE", smart_mode=smart)
            db.add(cfg)
        else:
            cfg.smart_mode = smart
        db.commit()
    finally:
        db.close()


def _set_draw(socket_id: int, amps: float, at: datetime = T0, power_kw: float = 0.0):
    """Set what the meter reports for a socket.

    v3.45 — CURRENT is the field that opens a standalone session. This helper used to set
    `meter_power_kw` and leave current at 0.0, which no longer opens anything.

    The change is not cosmetic. On MAR_KRK_ORM_01 the single-phase meters report `powerKw`
    roughly 100x high, so gating on power opened a session on every socket and held it —
    three were open when it was found, one since 27 September holding 42.40 kWh that never
    happened. `power_kw` stays available as a separate argument precisely so a test can prove
    that power alone does NOT open a session.
    """
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        sc = db.query(SocketConfig).filter_by(pedestal_id=PID, socket_id=socket_id).first()
        if sc is None:
            sc = SocketConfig(pedestal_id=PID, socket_id=socket_id, auto_activate=False)
            db.add(sc)
        # v3.39 — the reading's timestamp is what the staleness guard checks.
        sc.meter_load_updated_at = at
        sc.meter_power_kw = power_kw
        sc.meter_current_amps = amps
        sc.meter_current_l1 = 0.0
        sc.meter_current_l2 = 0.0
        sc.meter_current_l3 = 0.0
        db.commit()
    finally:
        db.close()


def _active(socket_id: int):
    from app.models.session import Session as SModel
    db = _S()
    try:
        return db.query(SModel).filter_by(
            pedestal_id=PID, socket_id=socket_id, type="electricity", status="active",
        ).first()
    finally:
        db.close()


def _tick(now: datetime):
    from app.services import mqtt_handlers as mh
    with patch.object(mh, "SessionLocal", _S), \
         patch("app.services.mqtt_handlers.ws_manager.broadcast", new=_AsyncNoop()):
        asyncio.run(mh._standalone_usage_tick(now))


class _AsyncNoop:
    async def __call__(self, *a, **k):
        return None


# ── tests ──────────────────────────────────────────────────────────────────────

def test_standalone_session_created_on_draw():
    _set_mode(smart=False)
    _set_draw(1, 9.5)
    _tick(datetime(2026, 6, 19, 12, 0, 0))
    s = _active(1)
    assert s is not None
    assert s.origin == "standalone"
    assert s.customer_id is None


def test_meter_handler_integrates_energy_power_x_time():
    """v3.32 — energy is integrated by the live meter path (power × time) for
    whatever session is active, since the Opta's energyKwh register reads 0."""
    from app.services import mqtt_handlers as mh
    from app.models.session import Session as SModel
    # An active session (any kind) on Q1.
    db = _S()
    try:
        s = SModel(pedestal_id=PID, socket_id=1, type="electricity",
                   status="active", started_at=datetime(2026, 6, 19, 12, 0, 0),
                   energy_kwh=0.0)
        db.add(s); db.commit(); db.refresh(s)
        sid = s.id
    finally:
        db.close()

    mh._meter_energy_last.clear()
    t0 = datetime(2026, 6, 19, 12, 0, 0)
    db = _S()
    try:
        mh._integrate_session_energy(db, PID, 1, 1.0, now=t0)                       # baseline
        mh._integrate_session_energy(db, PID, 1, 1.0, now=t0 + timedelta(seconds=30))  # +30 s @ 1 kW
        db.commit()
        s = db.get(SModel, sid)
        assert s.energy_kwh == pytest.approx(1.0 * 30 / 3600, abs=1e-6)   # 0.008333 kWh
        # Gap > 60 s (e.g. a restart) is ignored, not over-counted.
        mh._integrate_session_energy(db, PID, 1, 1.0, now=t0 + timedelta(hours=2))
        db.commit()
        s = db.get(SModel, sid)
        assert s.energy_kwh == pytest.approx(1.0 * 30 / 3600, abs=1e-6)   # unchanged
    finally:
        db.close()


def test_standalone_completes_when_draw_stops_and_shows_in_history():
    from app.services import usage_report_service as svc
    _set_mode(smart=False)
    _set_draw(1, 9.5)
    t0 = datetime(2026, 6, 19, 12, 0, 0)
    _tick(t0)                                  # create
    _set_draw(1, 0.0)                          # draw stops
    _tick(t0 + timedelta(seconds=10))           # below threshold -> low_since
    assert _active(1) is not None              # still within grace
    _tick(t0 + timedelta(seconds=200))          # past 120s grace -> complete
    assert _active(1) is None

    db = _S()
    try:
        rows = svc.usage_rows(db, PID, socket_id=1, resource="electricity")
        # Identity is opt-in from v3.44, so the DEFAULT call must not carry it at all.
        # Asserted as key ABSENCE rather than a None value: a None would mean "we looked
        # and there was no customer", which is a different claim from "this caller is not
        # shown customers".
        rows_with_identity = svc.usage_rows(
            db, PID, socket_id=1, resource="electricity", include_identity=True,
        )
    finally:
        db.close()

    assert len(rows) == 1
    assert "customer_name" not in rows[0], (
        "the default call leaks the customer name; identity must be opt-in so a caller "
        "that forgets to think about it exposes nothing"
    )
    assert "nfc_user_id" not in rows[0]
    assert rows[0]["customer_id"] is None, (
        "a standalone session has no customer — the opaque id stays in the shape and is "
        "null, which is the honest answer"
    )

    # And the opt-in path still answers the question it exists for.
    assert "customer_name" in rows_with_identity[0]
    assert rows_with_identity[0]["customer_name"] is None   # standalone — nobody to name


def test_no_standalone_session_when_smart_mode_on():
    _set_mode(smart=True)
    _set_draw(1, 9.5)
    _tick(datetime(2026, 6, 19, 12, 0, 0))
    assert _active(1) is None


def test_smart_mode_on_completes_existing_standalone_session():
    _set_mode(smart=False)
    _set_draw(1, 9.5)
    _tick(datetime(2026, 6, 19, 12, 0, 0))
    assert _active(1) is not None
    # Operator turns Smart Mode ON — the watchdog hands the socket back.
    _set_mode(smart=True)
    _tick(datetime(2026, 6, 19, 12, 0, 30))
    assert _active(1) is None


def test_no_session_when_no_draw():
    _set_mode(smart=False)
    _set_draw(1, 0.0)
    _tick(datetime(2026, 6, 19, 12, 0, 0))
    assert _active(1) is None


def test_inflated_power_with_no_current_opens_nothing():
    """v3.45 — THE LIVE FAULT, at the tick that creates sessions.

    MAR_KRK_ORM_01, 2026-10-09: Q4 reported 2.65 kW while drawing 0.26 A at 228 V. Under the
    old rule the 50 W power threshold was cleared permanently and a standalone session opened
    on every socket. Three were open when this was found; session 130 on Q2 had been running
    since 27 September holding 42.40 kWh that never happened.

    Paired with a real draw so it cannot pass by the tick simply never firing.
    """
    _set_mode(smart=False)

    # Q4 exactly as captured: trickle current, impossible power claim.
    _set_draw(4, 0.26, power_kw=2.65)
    _tick(datetime(2026, 6, 19, 13, 0, 0))
    assert _active(4) is None, (
        "2.65 kW reported at 0.26 A opened a standalone session. This is the reading that "
        "manufactured 56 kWh of phantom consumption on the live cabinet."
    )

    # A boat actually charging, on the same socket, with the same lying power figure.
    _set_draw(4, 9.5, at=datetime(2026, 6, 19, 13, 1, 0), power_kw=2.65)
    _tick(datetime(2026, 6, 19, 13, 1, 0))
    s = _active(4)
    assert s is not None, "a genuine 9.5 A draw did not open a session"
    assert s.origin == "standalone"
