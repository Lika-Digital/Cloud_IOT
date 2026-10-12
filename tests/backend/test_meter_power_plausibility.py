"""
The PF<=1 power-plausibility detector, pinned to the real captured payloads (v3.45)
==================================================================================

On 2026-10-09 a 5-minute capture of `opta/meters/+/telemetry` from MAR_KRK_ORM_01 showed the
single-phase ABB D11 meters reporting `powerKw` roughly 100x too high:

    socket   reported powerKw   expected gain / 5 min   actual register gain
    Q4           2.65 kW              0.221 kWh               0.010 kWh
    Q3           0.661 kW             0.055 kWh               0.000
    Q2           0.119 kW             0.010 kWh               0.000
    Q1 (3-ph)    0.000 kW             0                       0          <- consistent

Consequence on live hardware: every socket cleared the old 50 W session threshold
permanently, so the backend opened a standalone session on each and held it. Three were open
when this was found — session 130 on Q2 since 27 September, holding 42.40 kWh that never
happened.

WHY THE INVARIANT NEEDS NO POWER FACTOR
---------------------------------------
Real power P = V x I x PF, and PF <= 1 always, so P <= V x I for every load. A reported P
above V x I is impossible whatever PF happens to be. That matters here because PF is the
OTHER field caught misbehaving: Q4 reported PF 0.447 then 0.033 in consecutive samples 5 s
apart while `powerKw` did not move.

The previous rule compared against `V x I` with a 50x tolerance and did NOT fire: Q4 sits at
46.3x. The rule it replaced also omitted PF from the single-phase formula, which inflated the
computed baseline 2.24x and pushed a 103x error under a 50x threshold.

  TC-PWR-01  Q4's real captured payload is called impossible
  TC-PWR-02  Q1's three-phase payload is NOT called impossible — it has never lied
  TC-PWR-03  every single-phase socket from the capture is caught
  TC-PWR-04  the detector DETECTS and does not CORRECT
  TC-PWR-05  zero or missing current never alarms
  TC-PWR-06  a plausible load passes, so the check is not simply always-true
  TC-PWR-07  the 50x-tolerance rule would have missed Q4 — the regression being closed
  TC-PWR-08  the session gate reads CURRENT, not power
  TC-PWR-09  Q4's real current does NOT open a session; a real load does
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest


# ── The real payloads, as captured. Do not "tidy" these numbers. ─────────────────────────
#
# Taken from opta/meters/+/telemetry on MAR_KRK_ORM_01, firmware 3.1.0, 2026-10-09.
Q4_SINGLE_PHASE = {
    "id": "Q4",
    "currentAmps": 0.26,
    "voltageV": 228.0,
    "powerKw": 2.747,          # impossible: 228 V x 0.26 A = 0.0593 kVA
    "powerFactor": 0.447,      # and 0.033 five seconds later, on the same socket
    "energyKwh": 1234.56,
}

Q3_SINGLE_PHASE = {"id": "Q3", "currentAmps": 0.26, "voltageV": 228.0, "powerKw": 0.661}
Q2_SINGLE_PHASE = {"id": "Q2", "currentAmps": 0.26, "voltageV": 228.0, "powerKw": 0.119}

# Q1 is a three-phase ABB D13 and reports honestly. Whatever the invariant does, it must not
# start alarming on the meter that has never lied.
Q1_THREE_PHASE = {
    "id": "Q1",
    "currentAmpsTotal": 0.0,
    "currentAmpsL1": 0.0, "currentAmpsL2": 0.0, "currentAmpsL3": 0.0,
    "voltageL1": 230.7, "voltageL2": 229.9, "voltageL3": 231.2,
    "powerKwTotal": 0.000,
    "powerFactor": 0.0,
    "energyKwh": 987.65,
}


@pytest.fixture(autouse=True)
def _clear_power_throttle():
    """Each test is a fresh cabinet as far as the report throttle is concerned."""
    from app.services import mqtt_handlers
    mqtt_handlers._power_implausible_reports.clear()
    yield
    mqtt_handlers._power_implausible_reports.clear()


def _check(payload, *, three_phase=False, pedestal_id=1):
    """Run the real detector against a payload, with the alarm suppressed."""
    from app.services.mqtt_handlers import check_power_plausible

    if three_phase:
        vs = [payload[k] for k in ("voltageL1", "voltageL2", "voltageL3")]
        v = sum(vs) / 3.0
        i = payload["currentAmpsTotal"]
        rep = payload["powerKwTotal"]
    else:
        v = payload["voltageV"]
        i = payload["currentAmps"]
        rep = payload["powerKw"]

    with patch("app.services.meter_register.raise_meter_alarm") as alarm:
        ok = check_power_plausible(rep, voltage=v, current=i,
                                   socket_name=payload["id"], pedestal_id=pedestal_id)
    return ok, alarm


# ═══ TC-PWR-01 ════════════════════════════════════════════════════════════════

def test_tc_pwr_01_q4_real_payload_is_impossible():
    """The exact capture that started this. If this verdict ever flips, say why.

    2.747 kW claimed against 228 V x 0.26 A = 0.0593 kVA. Real power cannot exceed apparent
    power, so this is impossible by a factor of 46 regardless of power factor.
    """
    ok, alarm = _check(Q4_SINGLE_PHASE)

    assert ok is False, (
        "Q4's captured payload was accepted as plausible. 2.747 kW through 0.26 A at 228 V "
        "would require a power factor of 46, and power factor cannot exceed 1"
    )
    assert alarm.called, "an impossible reading must raise an alarm, not only return False"
    args = alarm.call_args[0]
    assert args[0] == "meter_power_implausible"
    # The message has to be actionable by someone who did not write this code.
    msg = args[1].lower()
    assert "cannot exceed" in msg, f"the message must state the invariant: {args[1]!r}"
    assert "register" in msg, (
        "the message must say consumption is unaffected, or an operator reading it will "
        f"assume billing is broken too: {args[1]!r}"
    )


# ═══ TC-PWR-02 ════════════════════════════════════════════════════════════════

def test_tc_pwr_02_q1_three_phase_is_not_accused():
    """Q1 has never lied. Reporting 0.000 kW at 0.000 A must NOT alarm.

    The failure this prevents is the worst kind of fix: one that silences a real fault on
    three sockets by starting to cry wolf on the fourth. At zero current there is no basis
    for a ratio at all — 0/0 is not a fault, it is an absence of evidence.
    """
    ok, alarm = _check(Q1_THREE_PHASE, three_phase=True)

    assert ok is True, "the three-phase meter that reports honestly was called faulty"
    assert not alarm.called, (
        "an alarm was raised for Q1 at zero current and zero power. The meter that has never "
        "lied must not start alarming."
    )


def test_tc_pwr_02b_a_loaded_three_phase_reading_still_passes():
    """And it must keep passing once Q1 actually carries load.

    Zero current passing is partly the floor doing the work, so this covers the real case:
    a plausible three-phase draw must not trip the invariant either.
    """
    loaded = dict(Q1_THREE_PHASE)
    loaded.update({
        "currentAmpsTotal": 12.0,
        "currentAmpsL1": 4.1, "currentAmpsL2": 3.9, "currentAmpsL3": 4.0,
        # 230.6 V avg x 12 A = 2.767 kVA apparent; 2.3 kW real is PF 0.83 — ordinary.
        "powerKwTotal": 2.3,
    })
    ok, alarm = _check(loaded, three_phase=True)
    assert ok is True, "a normal three-phase load at PF 0.83 was called impossible"
    assert not alarm.called


# ═══ TC-PWR-03 ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("payload", [Q4_SINGLE_PHASE, Q3_SINGLE_PHASE, Q2_SINGLE_PHASE],
                         ids=["Q4", "Q3", "Q2"])
def test_tc_pwr_03_every_captured_single_phase_socket_is_caught(payload):
    """All three single-phase sockets from the capture, not just the worst one.

    Q2 is the quiet one — 0.119 kW against 0.0593 kVA is only 2x over, where Q4 is 46x. A
    detector tuned to catch Q4 alone would leave Q2 reporting twice the power physically
    available, and Q2 is the socket that held 42.40 phantom kWh since September.
    """
    ok, alarm = _check(payload)
    assert ok is False, (
        f"{payload['id']} reported {payload['powerKw']} kW against "
        f"{payload['voltageV'] * payload['currentAmps'] / 1000:.4f} kVA available, and was "
        f"accepted"
    )
    assert alarm.called


# ═══ TC-PWR-11 — the report throttle ═════════════════════════════════════════
#
# v3.46. Telemetry is every 5 s and a meter fault does not clear itself, so the detector
# was writing a line per reading per socket — ~69k a day on the Krk cabinet with two bad
# meters. journald rotates on size, so the cost was not a full disk but the eviction of
# every other line of history.
#
# THE INVARIANT THESE TESTS EXIST TO PROTECT: the throttle suppresses the REPORT, never
# the REFUSAL. If a throttled window ever returned True, the bad figure would reach the
# display and the session gate for 5 minutes at a time — which is the original bug with a
# timer bolted on.

def test_tc_pwr_11_a_throttled_reading_is_still_refused():
    """The one that matters. Quiet must never mean accepted."""
    first_ok, first_alarm = _check(Q4_SINGLE_PHASE)
    assert first_ok is False
    assert first_alarm.called, "the first sighting must always be reported"

    # Same socket, immediately after — inside the 5-minute window.
    for n in range(12):
        ok, alarm = _check(Q4_SINGLE_PHASE)
        assert ok is False, (
            f"reading {n + 2} was ACCEPTED while the report was throttled — the throttle "
            f"has been wired to the verdict instead of to the logging"
        )
        assert not alarm.called, f"reading {n + 2} re-reported inside the window"


def test_tc_pwr_11b_the_window_reopens_and_names_what_it_swallowed():
    """After the interval the fault speaks again, and says how much was suppressed.

    Without the count the throttle would hide the rate as well as the noise, and the rate
    is the thing that tells you whether one meter is bad or four.
    """
    from app.services import mqtt_handlers
    from app.services.mqtt_handlers import _POWER_ALARM_REPORT_INTERVAL_S

    _check(Q4_SINGLE_PHASE)                       # reports, opens the window
    for _ in range(7):
        _check(Q4_SINGLE_PHASE)                   # suppressed

    # Rewind the stored timestamp rather than sleeping 5 real minutes.
    key = (1, "Q4")
    assert key in mqtt_handlers._power_implausible_reports, "throttle key shape changed"
    mqtt_handlers._power_implausible_reports[key][0] -= (_POWER_ALARM_REPORT_INTERVAL_S + 1)

    ok, alarm = _check(Q4_SINGLE_PHASE)
    assert ok is False
    assert alarm.called, "the window never reopened — a permanent fault went silent"
    msg = alarm.call_args[0][1]
    assert "7 further implausible readings were suppressed" in msg, (
        f"the reopened report does not account for what it swallowed: {msg}"
    )
    assert "discarded too" in msg, (
        "the message must say the suppressed readings were also refused, or a reader will "
        "assume silence meant they were accepted"
    )


def test_tc_pwr_11c_the_throttle_is_per_socket():
    """Q3 going quiet must not silence Q4. Two faults are not one fault."""
    _check(Q3_SINGLE_PHASE)
    ok, alarm = _check(Q3_SINGLE_PHASE)
    assert not alarm.called, "Q3 re-reported inside its own window"

    ok, alarm = _check(Q4_SINGLE_PHASE)
    assert ok is False
    assert alarm.called, (
        "Q4 was silenced by Q3's throttle — a second failing meter would never be seen"
    )


def test_tc_pwr_11d_the_throttle_is_per_pedestal():
    """Same socket name on a different cabinet is a different fault."""
    _check(Q4_SINGLE_PHASE, pedestal_id=1)
    ok, alarm = _check(Q4_SINGLE_PHASE, pedestal_id=2)
    assert ok is False
    assert alarm.called, (
        "cabinet 2 was silenced by cabinet 1 — in a multi-cabinet marina the second "
        "cabinet's meter fault would never be reported"
    )


def test_tc_pwr_11e_a_restart_reports_immediately():
    """The throttle is in-memory on purpose.

    A process that has just come up should say what it finds, not inherit a five-minute
    silence from before the restart.
    """
    from app.services import mqtt_handlers

    _check(Q4_SINGLE_PHASE)
    _, alarm = _check(Q4_SINGLE_PHASE)
    assert not alarm.called

    mqtt_handlers._power_implausible_reports.clear()        # restart
    ok, alarm = _check(Q4_SINGLE_PHASE)
    assert ok is False
    assert alarm.called, "after a restart the first bad reading stayed silent"


def test_tc_pwr_11f_single_log_site():
    """The detector must not log the text itself — raise_meter_alarm does that.

    Both used to log the same message, doubling an already-excessive stream. Asserting on
    the source keeps the duplicate from creeping back under a refactor.
    """
    import inspect
    from app.services.mqtt_handlers import check_power_plausible

    src = inspect.getsource(check_power_plausible)
    assert 'logger.warning("[Meter] %s", message)' not in src, (
        "check_power_plausible logs the message again; meter_register.raise_meter_alarm "
        "already does, so every fault would be recorded twice"
    )


# ═══ TC-PWR-04 ════════════════════════════════════════════════════════════════

def test_tc_pwr_04_the_detector_does_not_correct():
    """It returns a verdict. It must not return a substitute value.

    The function this replaced CORRECTED: it returned the computed figure, which then looked
    exactly like a correct reading and flowed to the display and the session gate. That is
    how a 100x meter fault survived from firmware 2.x to October 2026 — the clamp hid the
    fault it was written to catch.
    """
    from app.services.mqtt_handlers import check_power_plausible
    import app.services.mqtt_handlers as mh

    with patch("app.services.meter_register.raise_meter_alarm"):
        out = check_power_plausible(2.747, voltage=228.0, current=0.26,
                                    socket_name="Q4", pedestal_id=1)
    assert out is False, "the return value must be a verdict"
    assert isinstance(out, bool), (
        f"returned {out!r} ({type(out).__name__}) — a numeric return means it is correcting "
        f"again, and a corrected value is indistinguishable from a correct one"
    )
    assert not hasattr(mh, "_sanity_clamp_power_kw"), (
        "the old correcting clamp is still present; two mechanisms is how the first one "
        "survived unnoticed"
    )


# ═══ TC-PWR-05 ════════════════════════════════════════════════════════════════

# REWRITTEN 2026-10-11 (v3.48). TWO OF THE SIX CASES HERE ASSERTED THE DEFECT.
#
#   (228.0, 0.0,  2.747, "zero current — no basis for a ratio")
#   (228.0, 0.02, 0.050, "below the 10 VA floor — quantisation noise, not a fault")
#
# Both expected True. Both are now refused, and both refusals are the fix:
#
#   * 2.747 kW at a reported 0.000 A. The old reasoning was "no basis for a ratio", but a
#     reported zero is a MEASUREMENT with a known resolution — the true current is at most
#     half a step, so apparent power is bounded at about 1.15 VA and 2747 W is impossible
#     by a factor of 2400. The detector was making the zero-versus-unknown mistake about
#     its own inputs.
#
#   * 50 W at 0.02 A. The case name calls this "quantisation noise". It is 8.8x over the
#     most generous bound those readings permit. This is the exemption that let socket 2
#     report 0.129 kW at 4.6 VA on the live cabinet, drifting to 0.189 kW within the hour.
#
# What remains "cannot tell" is a reading that is ABSENT, not one that is zero. They moved
# to TC-PWR-05b below, with the distinction stated.
@pytest.mark.parametrize("v,i,rep,why", [
    (0.0,   5.0,  2.747, "zero voltage — no voltage reading is no basis at all"),
    (None,  0.26, 2.747, "voltage ABSENT from the payload"),
    (228.0, None, 2.747, "current ABSENT from the payload — not the same as 0.000 A"),
    (228.0, 0.26, None,  "no power reported at all"),
])
def test_tc_pwr_05_cannot_tell_is_not_faulty(v, i, rep, why):
    """Missing or zero inputs must never alarm.

    "Cannot tell" and "impossible" are different answers, and conflating them would fill the
    marina's alarm list with rows nobody can act on — which is how an alarm list stops being
    read. Same reasoning as unknown-vs-zero everywhere else in this codebase.
    """
    from app.services.mqtt_handlers import check_power_plausible

    with patch("app.services.meter_register.raise_meter_alarm") as alarm:
        ok = check_power_plausible(rep, voltage=v, current=i,
                                   socket_name="Qx", pedestal_id=1)
    assert ok is True, f"alarmed when it could not tell: {why}"
    assert not alarm.called, f"raised an alarm when it could not tell: {why}"


# ═══ TC-PWR-05b — a reported zero is a measurement ═══════════════════════════

@pytest.mark.parametrize("v,i,rep,bound_va,why", [
    (228.0, 0.000, 2.747, 1.14,
     "2.747 kW at a reported 0.000 A is impossible by ~2400x; the old floor called it "
     "'no basis for a ratio'"),
    (228.0, 0.02,  0.050, 5.70,
     "50 W at 0.02 A is 8.8x over the most generous bound; the old floor called it "
     "quantisation noise"),
    (229.9, 0.02,  0.129, 5.75,
     "socket 2 on cabinet 1, measured 2026-10-11 — accepted by the old floor at 28x"),
    (229.9, 0.02,  0.189, 5.75,
     "socket 2 an hour later, at 41x — the value drifts, the acceptance did not"),
])
def test_tc_pwr_05b_a_reported_zero_is_bounded_not_exempt(v, i, rep, bound_va, why):
    """A zero or near-zero CURRENT reading still bounds apparent power.

    The floor these replace was expressed in apparent power but exempted reported power
    without limit: a 10 VA floor does not let through 10 W, it lets through anything.
    """
    ok, alarm = _check({"id": "Qx", "currentAmps": i, "voltageV": v, "powerKw": rep})
    assert ok is False, f"ACCEPTED {rep} kW against a ~{bound_va} VA bound: {why}"
    assert alarm.called, "refused but raised no alarm"


def test_tc_pwr_05c_an_idle_socket_reporting_rounding_noise_stays_quiet():
    """The case the old floor was actually written for, kept working by the POWER floor.

    A pure resolution bound would refuse 2 W at 0.000 A — technically correct, operationally
    useless. `_POWER_REPORT_FLOOR_KW` keeps it quiet, and because that floor bounds the
    REPORTED figure, nothing above 5 W is exempt at any current.
    """
    from app.services.mqtt_handlers import _POWER_REPORT_FLOOR_KW
    assert _POWER_REPORT_FLOOR_KW == 0.005, "this test encodes the 5 W floor"

    for rep in (0.000, 0.001, 0.002, 0.004):
        ok, alarm = _check({"id": "Q1", "currentAmps": 0.000, "voltageV": 230.0,
                            "powerKw": rep})
        assert ok is True, f"{rep * 1000:.0f} W of rounding noise at 0.000 A alarmed"
        assert not alarm.called

    # And immediately above the floor it is refused — the gap has a lid.
    ok, _ = _check({"id": "Q1", "currentAmps": 0.000, "voltageV": 230.0, "powerKw": 0.050})
    assert ok is False, "50 W at 0.000 A was exempt — the power floor has no lid"


def test_tc_pwr_05d_three_phase_gets_three_half_steps():
    """A three-phase total is a SUM of three measured phases, so three half-steps.

    Q1 is the meter that has never lied. It must not start alarming for the arithmetic
    reason that it reports a sum — which it would if the bound used one half-step.
    """
    from app.services.mqtt_handlers import (
        check_power_plausible, _METER_CURRENT_STEP_A, _METER_VOLTAGE_STEP_V,
        _POWER_IMPLAUSIBLE_MARGIN,
    )

    v, i_total = 230.0, 0.03          # three phases of 0.01 A, every one at its own floor
    v_max = v + _METER_VOLTAGE_STEP_V / 2.0
    one = (i_total + _METER_CURRENT_STEP_A / 2.0) * v_max * 0.001
    three = (i_total + 3 * _METER_CURRENT_STEP_A / 2.0) * v_max * 0.001
    assert three > one, "the widening does nothing"

    # A figure between the two bounds: refused on one half-step, allowed on three.
    between = (one + three) / 2.0 * _POWER_IMPLAUSIBLE_MARGIN
    assert between > 0.005, "pick a figure above the power floor or this proves nothing"

    with patch("app.services.meter_register.raise_meter_alarm"):
        assert check_power_plausible(between, voltage=v, current=i_total,
                                     socket_name="Q1", pedestal_id=1,
                                     current_steps=3) is True, (
            "a three-phase total was called impossible using a single-phase bound"
        )
        assert check_power_plausible(between, voltage=v, current=i_total,
                                     socket_name="Q1", pedestal_id=1,
                                     current_steps=1) is False, (
            "the single-phase bound no longer refuses what the three-phase bound allows, "
            "so this test is not measuring the widening any more"
        )


# ═══ TC-PWR-06 ════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("v,i,rep,pf_implied", [
    (230.0, 16.0, 3.4,  0.92),
    (230.0, 10.0, 2.0,  0.87),
    (230.0, 32.0, 7.36, 1.00),   # PF exactly 1 — the boundary, must pass
])
def test_tc_pwr_06_plausible_loads_pass(v, i, rep, pf_implied):
    """A detector that rejects everything is as useless as one that accepts everything.

    PF = 1 is included deliberately: it is the boundary of the invariant, it is physically
    attainable by a purely resistive load, and an off-by-one in the comparison would reject it.
    """
    from app.services.mqtt_handlers import check_power_plausible

    with patch("app.services.meter_register.raise_meter_alarm") as alarm:
        ok = check_power_plausible(rep, voltage=v, current=i,
                                   socket_name="Qx", pedestal_id=1)
    assert ok is True, (
        f"{rep} kW at {v} V x {i} A (power factor {pf_implied}) was called impossible"
    )
    assert not alarm.called


# ═══ TC-PWR-07 ════════════════════════════════════════════════════════════════

def test_tc_pwr_07_the_old_50x_rule_would_have_missed_q4():
    """The regression being closed, stated as arithmetic rather than as a claim.

    The replaced rule fired at `reported > computed * 50`, with `computed = V x I` and no
    power factor. On Q4 that is 46.3x — under the threshold. The fault ran for months with a
    check in place that could not see it.
    """
    v, i, rep = 228.0, 0.26, 2.747
    computed = v * i * 0.001

    old_rule_fires = rep > computed * 50.0
    assert old_rule_fires is False, (
        "the arithmetic behind this regression has changed; re-derive it before trusting "
        "the rest of this file"
    )
    assert rep / computed == pytest.approx(46.3, abs=0.5)

    from app.services.mqtt_handlers import check_power_plausible
    with patch("app.services.meter_register.raise_meter_alarm"):
        assert check_power_plausible(rep, voltage=v, current=i,
                                     socket_name="Q4", pedestal_id=1) is False, (
            "the new rule must catch what the 50x rule missed"
        )


# ═══ TC-PWR-08 / TC-PWR-09 — the gate ════════════════════════════════════════

class _Cfg:
    """The fields `_socket_delivering_power` reads."""
    def __init__(self, *, amps=None, power_kw=None, age_s=1.0,
                 l1=None, l2=None, l3=None):
        self.meter_current_amps = amps
        self.meter_power_kw = power_kw
        self.meter_current_l1 = l1
        self.meter_current_l2 = l2
        self.meter_current_l3 = l3
        self.meter_load_updated_at = datetime.utcnow() - timedelta(seconds=age_s)


def test_tc_pwr_08_the_gate_ignores_power_entirely():
    """Session detection must not read `meter_power_kw` at all.

    Asserted as a pair, because only the pair proves the field is ignored rather than
    merely deprioritised: a huge power with no current must NOT open a session, and a real
    current with no power reported MUST.
    """
    from app.services.mqtt_handlers import _socket_delivering_power

    assert _socket_delivering_power(_Cfg(amps=0.0, power_kw=99.0)) is False, (
        "99 kW with zero current opened a session — the gate is still reading power, which "
        "is the field that manufactured three phantom sessions on live hardware"
    )
    assert _socket_delivering_power(_Cfg(amps=12.0, power_kw=None)) is True, (
        "a genuine 12 A draw did not open a session because no power figure was reported"
    )


def test_tc_pwr_09_q4s_real_current_opens_no_session():
    """The live fault, at the gate. 0.26 A is below the 0.30 A threshold.

    This is the assertion that says the phantom sessions stop. Paired with a real load so it
    cannot pass by the gate simply never firing.
    """
    from app.services.mqtt_handlers import _socket_delivering_power, _METER_ACTIVE_AMPS

    assert _METER_ACTIVE_AMPS == 0.30

    # Q4 as captured: trickle current, impossible power claim.
    assert _socket_delivering_power(_Cfg(amps=0.26, power_kw=2.747)) is False, (
        "Q4's real reading still opens a standalone session"
    )
    # A boat actually charging.
    assert _socket_delivering_power(_Cfg(amps=9.5, power_kw=2.747)) is True

    # And a stale reading is never a draw, whatever it says.
    assert _socket_delivering_power(_Cfg(amps=9.5, age_s=600)) is False, (
        "a reading 10 minutes old was treated as a live draw"
    )


# ═══ TC-PWR-10 — the ERP backstop ════════════════════════════════════════════
#
# The defence that holds whatever the NEXT bad field turns out to be.
#
# `erp_webhook.build()` had no attribution check, so a standalone session — opened by the
# backend itself, customer_id NULL, nfc_user_id NULL — reached myMarina like any other. On
# the live cabinet three such sessions were open, one carrying 42.40 kWh that never happened.
#
# The gate fix above stops THESE sessions being created. This stops the NEXT ones leaving,
# whatever creates them: a figure we cannot attribute to a customer does not go to the ERP.

class _Sess:
    def __init__(self, sid=1, customer_id=None, nfc_user_id=None, origin="standalone",
                 erp_ref=None):
        self.id = sid
        self.pedestal_id = 3
        self.customer_id = customer_id
        self.nfc_user_id = nfc_user_id
        self.erp_ref = erp_ref
        self.origin = origin
        self.socket_id = 2
        self.type = "electricity"
        self.status = "completed"


@pytest.mark.parametrize("sess,reportable,why", [
    (_Sess(customer_id=None, nfc_user_id=None, origin="standalone"), False,
     "a standalone session belongs to nobody — this is the live case"),
    (_Sess(customer_id=None, nfc_user_id=None, origin="operator"), False,
     "an operator-started session has no one for the ERP to bill either"),
    # D6.1 (2026-10-12): the ERP's own reference is the attribution. A session carrying only
    # a legacy customer_id or nfc_user_id would reach the ERP with erp_ref null — a figure
    # with nobody it can bill — so it is now withheld too.
    (_Sess(customer_id=7, nfc_user_id=None, origin="customer"), False,
     "a legacy customer-app session has no erp_ref, so nothing the ERP can bill"),
    (_Sess(customer_id=None, nfc_user_id="erp-abc", origin="nfc"), False,
     "a pre-D6.1 NFC session has no erp_ref either"),
    (_Sess(erp_ref="erp-abc", origin="nfc"), True,
     "a session carrying the ERP's reference is attributable"),
])
def test_tc_pwr_10_only_attributable_sessions_reach_the_erp(sess, reportable, why):
    from app.services.erp_webhook import is_erp_reportable
    assert is_erp_reportable(sess) is reportable, why


def test_tc_pwr_10b_build_withholds_an_unattributed_session():
    """End to end through `build()`, with a webhook URL configured.

    Asserted through `build` and not only the predicate, because `build` is what the three
    MQTT call sites use. A predicate that is right and unwired protects nothing.
    """
    from app.config import settings
    from app.services import erp_webhook

    prev = settings.erp_webhook_url
    settings.erp_webhook_url = "https://erp.example.test/hook"
    try:
        assert erp_webhook.build(None, _Sess(), "session_ended") is None, (
            "an unattributed session produced an ERP payload; 42.40 phantom kWh would have "
            "left the cabinet"
        )
    finally:
        settings.erp_webhook_url = prev
