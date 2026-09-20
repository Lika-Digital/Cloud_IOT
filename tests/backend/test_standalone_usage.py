"""Standalone usage recording (v3.32).

When Smart Mode is OFF the Opta runs the sockets and emits no control session,
but it reports the meter. The standalone-usage watchdog turns sustained draw
into a usage session (origin="standalone", customer blank), integrates energy
(power x time, since the firmware reports energyKwh=0), and completes it when
the draw stops — so the consumption shows in Usage History in both modes.
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


def _set_power(socket_id: int, power_kw: float, at: datetime = T0):
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
        sc.meter_current_amps = 0.0
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
    _set_power(1, 0.49)
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
    _set_power(1, 0.49)
    t0 = datetime(2026, 6, 19, 12, 0, 0)
    _tick(t0)                                  # create
    _set_power(1, 0.0)                          # draw stops
    _tick(t0 + timedelta(seconds=10))           # below threshold -> low_since
    assert _active(1) is not None              # still within grace
    _tick(t0 + timedelta(seconds=200))          # past 120s grace -> complete
    assert _active(1) is None

    db = _S()
    try:
        rows = svc.usage_rows(db, PID, socket_id=1, resource="electricity")
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0]["customer_name"] is None     # standalone — customer blank


def test_no_standalone_session_when_smart_mode_on():
    _set_mode(smart=True)
    _set_power(1, 0.49)
    _tick(datetime(2026, 6, 19, 12, 0, 0))
    assert _active(1) is None


def test_smart_mode_on_completes_existing_standalone_session():
    _set_mode(smart=False)
    _set_power(1, 0.49)
    _tick(datetime(2026, 6, 19, 12, 0, 0))
    assert _active(1) is not None
    # Operator turns Smart Mode ON — the watchdog hands the socket back.
    _set_mode(smart=True)
    _tick(datetime(2026, 6, 19, 12, 0, 30))
    assert _active(1) is None


def test_no_session_when_no_draw():
    _set_mode(smart=False)
    _set_power(1, 0.0)
    _tick(datetime(2026, 6, 19, 12, 0, 0))
    assert _active(1) is None
