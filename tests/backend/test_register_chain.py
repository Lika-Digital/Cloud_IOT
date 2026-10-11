"""The register chain: start capture, refused power, and the ledger's silence (v3.46).

WHAT BROKE, MEASURED ON CABINET 1 ON 2026-10-11
-----------------------------------------------
Since eb8ba94 the whole consumption chain is register-derived: the session figure
(`session_service.complete`) and every row of the billing ledger
(`energy_interval_service._register_session_to_date`). Both return None the moment
`sessions.meter_energy_start_kwh` is NULL.

The standalone-usage watchdog creates sessions directly at `mqtt_handlers.py:1311` with
`status="active"`, never calling `activate()` — so it never captured a start register. On a
cabinet in Smart Mode OFF that is the ONLY path that creates sessions. The live result:

    128 standalone sessions, not one with a start register
    energy_intervals frozen at 8675 rows from 2026-10-10 18:12 local — the ERP feed, silent
    session 178 open 2h15m carrying energy_kwh = 0.0 on a socket drawing about 50 W

Three symptoms, two causes. The silent ledger and the NULL session figures are the missing
start register. The false zero is one `or`:

    cfg.meter_power_kw = None            # check_power_plausible correctly refuses it
    _integrate_session_energy(..., None)
    p = float(power_kw or 0.0)           # <- the refusal becomes a measurement of zero

NOTHING HERE MAY WEAKEN TWO BEHAVIOURS THAT WERE ALREADY CORRECT: sessions 176 and 177
closed with a NULL figure and source "unknown" rather than an invented number, and the
ledger refused to write a row it could not derive. Both are the design working. The fix adds
a start register and stops the false zero; it does not make anything guess.

No test ever called `_integrate_session_energy` with power_kw=None. That is why `or 0.0`
shipped.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from conftest import TestSession as _S

PID = 9400
T0 = datetime(2026, 10, 11, 9, 0, 0)


@pytest.fixture(autouse=True)
def _isolate():
    from app.models.pedestal import Pedestal
    from app.models.pedestal_config import PedestalConfig
    from app.models.socket_config import SocketConfig
    from app.models.session import Session as SModel
    from app.models.energy_interval import EnergyInterval
    from app.services import mqtt_handlers as mh

    mh._standalone_usage_last.clear()
    mh._standalone_usage_low_since.clear()
    mh._meter_energy_last.clear()

    db = _S()
    try:
        if db.get(Pedestal, PID) is None:
            db.add(Pedestal(id=PID, name="Register Chain", location="Dock R",
                            data_mode="synthetic"))
        for model in (EnergyInterval, SModel, SocketConfig, PedestalConfig):
            db.query(model).filter(model.pedestal_id == PID).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield


class _AsyncNoop:
    async def __call__(self, *a, **k):
        return None


def _set_mode(smart: bool):
    from app.models.pedestal_config import PedestalConfig
    db = _S()
    try:
        cfg = db.query(PedestalConfig).filter_by(pedestal_id=PID).first()
        if cfg is None:
            db.add(PedestalConfig(pedestal_id=PID, opta_client_id="MAR_REGCHAIN",
                                  smart_mode=smart))
        else:
            cfg.smart_mode = smart
        db.commit()
    finally:
        db.close()


def _set_socket(socket_id: int, *, amps: float, register_kwh: float | None,
                at: datetime = T0, power_kw: float = 0.0):
    """What the meter reports: current (opens a session) and the cumulative register."""
    from app.models.socket_config import SocketConfig
    db = _S()
    try:
        sc = db.query(SocketConfig).filter_by(pedestal_id=PID, socket_id=socket_id).first()
        if sc is None:
            sc = SocketConfig(pedestal_id=PID, socket_id=socket_id, auto_activate=False)
            db.add(sc)
        sc.meter_load_updated_at = at
        sc.meter_power_kw = power_kw
        sc.meter_current_amps = amps
        sc.meter_current_l1 = sc.meter_current_l2 = sc.meter_current_l3 = 0.0
        sc.meter_energy_kwh = register_kwh
        db.commit()
    finally:
        db.close()


def _tick(now: datetime):
    from app.services import mqtt_handlers as mh
    with patch.object(mh, "SessionLocal", _S), \
         patch("app.services.mqtt_handlers.ws_manager.broadcast", new=_AsyncNoop()):
        asyncio.run(mh._standalone_usage_tick(now))


def _active(socket_id: int):
    from app.models.session import Session as SModel
    db = _S()
    try:
        return db.query(SModel).filter_by(
            pedestal_id=PID, socket_id=socket_id, type="electricity", status="active",
        ).first()
    finally:
        db.close()


# ═══ The false zero ══════════════════════════════════════════════════════════

def _open_session(socket_id: int = 1, energy=None):
    from app.models.session import Session as SModel
    db = _S()
    try:
        s = SModel(pedestal_id=PID, socket_id=socket_id, type="electricity",
                   status="active", started_at=T0, energy_kwh=energy,
                   origin="standalone")
        db.add(s)
        db.commit()
        db.refresh(s)
        return s.id
    finally:
        db.close()


def _energy_of(session_id: int):
    from app.models.session import Session as SModel
    db = _S()
    try:
        return db.get(SModel, session_id).energy_kwh
    finally:
        db.close()


def test_a_refused_power_reading_does_not_become_zero_energy():
    """`check_power_plausible` returning None must not integrate as a zero measurement.

    This is session 178: open two and a quarter hours, energy_kwh 0.0, on a socket drawing
    about 50 W. Zero is an answer; the honest state is that there is no answer yet.
    """
    from app.services import mqtt_handlers as mh
    sid = _open_session(1, energy=None)

    db = _S()
    try:
        mh._integrate_session_energy(db, PID, 1, None, now=T0)
        mh._integrate_session_energy(db, PID, 1, None, now=T0 + timedelta(seconds=5))
        mh._integrate_session_energy(db, PID, 1, None, now=T0 + timedelta(seconds=10))
        db.commit()
    finally:
        db.close()

    assert _energy_of(sid) is None, (
        "a refused power reading was integrated as zero draw — `or 0.0` is back"
    )


def test_an_unknown_window_is_not_bridged_by_the_next_good_sample():
    """THE SUBTLE ONE. Returning early is not enough; the anchor must be dropped.

    If the last-sample anchor survives an unknown window, the next usable reading computes
    dt across the whole gap and multiplies it by the average of two readings taken either
    side — fabricating energy for exactly the period we admitted we could not measure.
    """
    from app.services import mqtt_handlers as mh
    sid = _open_session(1, energy=None)

    db = _S()
    try:
        # A good sample, then a long unknown window, then another good sample.
        mh._integrate_session_energy(db, PID, 1, 2.0, now=T0)
        mh._integrate_session_energy(db, PID, 1, None, now=T0 + timedelta(seconds=20))
        mh._integrate_session_energy(db, PID, 1, 2.0, now=T0 + timedelta(seconds=40))
        db.commit()
    finally:
        db.close()

    got = _energy_of(sid)
    assert got is None, (
        f"energy was accumulated across an unmeasured window (got {got}). The 40 s gap at "
        f"2 kW would fabricate about {2.0 * 40 / 3600:.5f} kWh that nobody measured."
    )


def test_real_power_still_integrates():
    """Regression guard: refusing None must not stop the integral working when power is real."""
    from app.services import mqtt_handlers as mh
    sid = _open_session(1, energy=None)

    db = _S()
    try:
        mh._integrate_session_energy(db, PID, 1, 2.0, now=T0)
        mh._integrate_session_energy(db, PID, 1, 2.0, now=T0 + timedelta(seconds=36))
        db.commit()
    finally:
        db.close()

    got = _energy_of(sid)
    assert got is not None, "the integral stopped working for real readings"
    assert got == pytest.approx(2.0 * 36 / 3600.0, rel=1e-6), got


# ═══ The missing start register ══════════════════════════════════════════════

def test_standalone_session_is_not_born_with_a_zero_measurement():
    _set_mode(smart=False)
    _set_socket(1, amps=9.5, register_kwh=100.0)
    _tick(T0)

    s = _active(1)
    assert s is not None, "no standalone session was opened"
    assert s.energy_kwh is None, (
        f"born with energy_kwh={s.energy_kwh} — a measurement of zero on a socket that this "
        f"branch only reaches because it IS drawing power"
    )


def test_standalone_session_captures_the_opening_register():
    """The fix. Without it the ledger and the session figure are both dead on this path."""
    _set_mode(smart=False)
    _set_socket(1, amps=9.5, register_kwh=275.87)
    _tick(T0)

    s = _active(1)
    assert s is not None
    assert s.meter_energy_start_kwh == pytest.approx(275.87), (
        f"opening register not captured (got {s.meter_energy_start_kwh}). The standalone "
        f"path bypasses activate(), so it must call _capture_start_register itself."
    )


def test_an_unreadable_register_leaves_the_start_null_and_still_opens_the_session():
    """Honest unknown, and never at the cost of recording the usage.

    A register we cannot read makes the figure UNKNOWN. It must not stop the session being
    observed — the draw is real whether or not we can price it.
    """
    _set_mode(smart=False)
    _set_socket(1, amps=9.5, register_kwh=None)
    _tick(T0)

    s = _active(1)
    assert s is not None, "an unreadable register stopped the session being recorded"
    assert s.meter_energy_start_kwh is None
    assert s.energy_kwh is None, "an unreadable register must not produce a zero figure"


def test_consecutive_sessions_on_one_socket_chain_their_registers():
    """The register is cumulative per socket, so one session's end IS the next one's start.

    Cabinet 1: 176 ended 07:51:26 at 275.87, 177 started 07:51:56 and should begin there.
    Asserted as an INVARIANT, not used as a data source — a new session reads the live
    register. Reconstructing a start from the previous row is what we declined to do for
    session 178, because the number would look right and nobody could audit it.
    """
    from app.models.session import Session as SModel
    _set_mode(smart=False)

    # First session opens at 275.87 and draws.
    _set_socket(1, amps=9.5, register_kwh=275.87)
    _tick(T0)
    first_id = _active(1).id

    # Draw stops; the register has advanced to 275.88. Close it out.
    _set_socket(1, amps=0.0, register_kwh=275.88, at=T0 + timedelta(minutes=12))
    from app.services import mqtt_handlers as mh
    _tick(T0 + timedelta(minutes=12))
    _tick(T0 + timedelta(minutes=12, seconds=mh._STANDALONE_USAGE_STOP_GRACE_S + 1))

    db = _S()
    try:
        first = db.get(SModel, first_id)
        assert first.status == "completed", f"first session did not close ({first.status})"
        first_end = first.meter_energy_end_kwh
    finally:
        db.close()

    assert first_end == pytest.approx(275.88), f"end register not captured ({first_end})"

    # A new draw opens a second session, which must start where the first ended.
    _set_socket(1, amps=9.5, register_kwh=275.88,
                at=T0 + timedelta(minutes=14))
    _tick(T0 + timedelta(minutes=14))

    second = _active(1)
    assert second is not None and second.id != first_id, "no second session opened"
    assert second.meter_energy_start_kwh == pytest.approx(first_end), (
        f"the register did not chain: first ended {first_end}, second starts "
        f"{second.meter_energy_start_kwh}. On one cumulative meter these must be equal."
    )


# ═══ The silence ═════════════════════════════════════════════════════════════

def test_the_ledger_announces_that_it_wrote_nothing():
    """8675 rows froze and nobody noticed for eighteen hours across two restarts.

    A grep for "interval" over 500 journal lines returned one hit, and it belonged to
    frame_buffer. Nothing announced that this writer existed, so nothing announced that it
    had stopped. Writing only on success makes a dead ledger look like an idle marina.
    """
    from app.services import energy_interval_service as eis
    _open_session(1, energy=None)        # active, electricity, NULL start register

    with patch.object(eis, "SessionLocal", _S):
        with caplog_at(logging.WARNING) as cap:
            written = eis._interval_tick(T0 + timedelta(minutes=15))

    assert written == 0, "a row was written despite a NULL start register"
    text = cap.text
    assert "wrote NO row" in text, f"the tick stayed silent about writing nothing:\n{text}"
    assert "UNKNOWN" in text, "the reason was not given"
    assert "SILENT" in text or "silent" in text, (
        "the message does not say the ERP feed is affected, which is the consequence that "
        "matters to a reader"
    )


def test_the_ledger_writer_announces_itself_at_startup():
    """So there is a line to miss when it stops."""
    from app.services import energy_interval_service as eis

    class _Stop(Exception):
        pass

    async def _boom(_period):
        raise _Stop()

    with patch.object(eis.asyncio, "sleep", _boom):
        with caplog_at(logging.INFO) as cap:
            with pytest.raises(_Stop):
                asyncio.run(eis.run_energy_interval_logger())

    assert "ledger writer started" in cap.text, (
        f"startup is silent about the interval writer:\n{cap.text}"
    )
    assert "register" in cap.text, (
        "the announcement should say it reads the register, since the stale docstring said "
        "it reads integrated power"
    )


# ── a tiny caplog helper, because two tests above need it outside a fixture ───

class _Cap:
    def __init__(self, level):
        self.level = level
        self.records = []
        self._handler = None

    @property
    def text(self):
        return "\n".join(r.getMessage() for r in self.records)

    def __enter__(self):
        cap = self

        class H(logging.Handler):
            def emit(self, record):
                cap.records.append(record)

        self._handler = H(level=self.level)
        root = logging.getLogger()
        self._old_level = root.level
        root.addHandler(self._handler)
        root.setLevel(min(self.level, root.level or self.level))
        return self

    def __exit__(self, *exc):
        logging.getLogger().removeHandler(self._handler)
        logging.getLogger().setLevel(self._old_level)
        return False


def caplog_at(level):
    return _Cap(level)
