"""
Guard alarm rule — anti-flicker in time (Stage A.5, v3.41)
==========================================================

The spec's mandatory anti-flicker rule: alarm when a person is detected in at
least N inferences inside a rolling W-second window, then a cooldown before
another alarm can fire. Frame-level recall can look excellent and still produce a
false alarm every ten minutes, so this rule — not per-frame accuracy — is what the
marina actually experiences.

Promoted in step 2 to `app/guard/alarm_rule.py`, so the worker, the probe and these
tests all use ONE definition. `evaluate_alarm_rule` (batch, for clip replay) is
implemented on top of `AlarmState` (incremental, for the live worker), so the two
cannot drift — TC-GAR-12 asserts that equivalence directly.

  TC-GAR-01  two detections inside the window raise exactly one alarm
  TC-GAR-02  a single lone detection raises nothing
  TC-GAR-03  two detections spread wider than the window raise nothing
  TC-GAR-04  cooldown suppresses a second alarm while a person stays in view
  TC-GAR-05  a new alarm fires once the cooldown has expired
  TC-GAR-06  frames_required=3 needs three hits, not two
  TC-GAR-07  rule latency is measured from the FIRST detection
  TC-GAR-08  no detections / empty input → no alarms
  TC-GAR-09  a sparse flicker at 2 fps does not alarm (the anti-flicker purpose)
  TC-GAR-10  window is rolling, not a fixed bucket
  TC-GAR-11  the settled defaults (2 frames / 4 s) are what the code actually uses
  TC-GAR-12  incremental AlarmState matches batch evaluate_alarm_rule exactly
  TC-GAR-13  reset() clears state, so disarm does not leak into the next arming
  TC-GAR-14  cooldown expires on NEGATIVE frames too
  TC-GAR-15  invalid parameters are rejected
"""
from __future__ import annotations

import pytest

# Step 2: the rule was promoted from scripts/guard_detect_probe.py into the backend so the
# worker and the probe share one definition. Imported directly now — no importlib needed.
from app.guard.alarm_rule import (
    DEFAULT_FRAMES_REQUIRED,
    DEFAULT_WINDOW_SECONDS,
    AlarmState,
    evaluate_alarm_rule,
)

def _samples(hits: list[float], duration: float = 30.0, fps: float = 2.0) -> list[tuple[float, bool]]:
    """Build a 2 fps sample series where `hits` lists the positive timestamps."""
    n = int(duration * fps)
    hit_set = {round(h, 3) for h in hits}
    return [(round(i / fps, 3), round(i / fps, 3) in hit_set) for i in range(n)]


# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gar_01_two_in_window_raises_one_alarm():
    alarms = evaluate_alarm_rule(_samples([10.0, 10.5]))
    assert len(alarms) == 1
    assert alarms[0]["t"] == pytest.approx(10.5)
    assert alarms[0]["positives_in_window"] == 2


def test_tc_gar_02_single_detection_raises_nothing():
    assert evaluate_alarm_rule(_samples([10.0])) == []


def test_tc_gar_03_detections_wider_than_window_raise_nothing():
    """Two positives further apart than the window must not combine.

    The default window became 4 s in step 2 (settled from the 1 fps measurement), so the
    original form of this test — 4 s apart, expecting nothing — now correctly alarms,
    because the bound is inclusive. Both the explicit 3 s case and the new 4 s default are
    covered so neither can drift unnoticed.
    """
    # Explicit 3 s window: 4 s apart is outside it.
    assert evaluate_alarm_rule(_samples([10.0, 14.0]), window_seconds=3.0) == []
    # Default 4 s window: 5 s apart is outside it.
    assert evaluate_alarm_rule(_samples([10.0, 15.0])) == []
    # ...but exactly 4 s apart IS inside it — the bound is inclusive, deliberately, so a
    # detection landing exactly on the edge is not silently discarded.
    assert len(evaluate_alarm_rule(_samples([10.0, 14.0]))) == 1


def test_tc_gar_04_cooldown_suppresses_second_alarm():
    """A person loitering for 20 s is ONE event, not forty."""
    hits = [round(10.0 + i * 0.5, 3) for i in range(40)]      # 10.0 → 29.5 s, every frame
    alarms = evaluate_alarm_rule(_samples(hits, duration=40.0), cooldown_seconds=60.0)
    assert len(alarms) == 1, f"expected a single alarm, got {len(alarms)}"
    assert alarms[0]["t"] == pytest.approx(10.5)


def test_tc_gar_05_new_alarm_after_cooldown_expires():
    hits = [10.0, 10.5, 25.0, 25.5]
    # 10 s cooldown → the 25 s pair is a fresh event.
    alarms = evaluate_alarm_rule(_samples(hits, duration=40.0), cooldown_seconds=10.0)
    assert len(alarms) == 2
    assert alarms[0]["t"] == pytest.approx(10.5)
    assert alarms[1]["t"] == pytest.approx(25.5)

    # 60 s cooldown → still one event.
    assert len(evaluate_alarm_rule(_samples(hits, duration=40.0), cooldown_seconds=60.0)) == 1


def test_tc_gar_06_frames_required_three():
    assert evaluate_alarm_rule(_samples([10.0, 10.5]), frames_required=3) == []
    alarms = evaluate_alarm_rule(_samples([10.0, 10.5, 11.0]), frames_required=3)
    assert len(alarms) == 1
    assert alarms[0]["positives_in_window"] == 3


def test_tc_gar_07_latency_is_from_first_detection():
    alarms = evaluate_alarm_rule(_samples([10.0, 12.5]), window_seconds=3.0)
    assert len(alarms) == 1
    assert alarms[0]["first_positive_t"] == pytest.approx(10.0)
    assert alarms[0]["latency_s"] == pytest.approx(2.5)


def test_tc_gar_08_no_detections_no_alarms():
    assert evaluate_alarm_rule([]) == []
    assert evaluate_alarm_rule(_samples([])) == []
    assert evaluate_alarm_rule([(0.0, False), (1.0, False)]) == []


def test_tc_gar_09_sparse_flicker_does_not_alarm():
    """The whole point of the rule: isolated one-frame blips — a gull, a reflection,
    a wave — are 6 s apart and must never raise an alarm."""
    flicker = [5.0, 11.0, 17.0, 23.0, 29.0]
    assert evaluate_alarm_rule(_samples(flicker, duration=40.0)) == []


def test_tc_gar_10_window_is_rolling_not_bucketed():
    """Detections at 9.8 and 10.2 straddle a 10 s bucket boundary but are 0.4 s
    apart, so a rolling window must fire. A fixed-bucket implementation would not."""
    alarms = evaluate_alarm_rule(_samples([9.8, 10.2], duration=20.0, fps=5.0))
    assert len(alarms) == 1

# ═══════════════════════════════════════════════════════════════════════════
# TC-GAR-11..14 — step 2: the settled defaults, and the incremental form
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gar_11_defaults_are_the_settled_values():
    """These numbers were derived from measurement, not taste, so pin them.

    1 fps because one inference costs 273.3 ms CPU single-threaded (6.8 % of 4 cores at
    1 fps, 13.7 % at 2). A 4 s window because 1 fps gives only 4 samples in 3 s; 5 samples
    lifts P(alarm) at recall 0.6 from 0.821 to 0.913 while max latency stays 4.0 s, inside
    the 5 s threshold.
    """
    assert DEFAULT_FRAMES_REQUIRED == 2
    assert DEFAULT_WINDOW_SECONDS == 4.0

    # And the defaults are what the functions actually use.
    at_1fps = [(float(i), i in (10, 13)) for i in range(20)]   # 3 s apart, 1 fps
    assert len(evaluate_alarm_rule(at_1fps)) == 1, (
        "two detections 3 s apart at 1 fps must alarm under the 4 s default"
    )


def test_tc_gar_12_incremental_matches_batch_exactly():
    """The worker feeds frames one at a time; the probe replays a clip in a batch. Both
    must be the same decision, which is why `evaluate_alarm_rule` is implemented ON TOP of
    `AlarmState` rather than beside it. This asserts the equivalence it is built on."""
    for hits, cooldown in (
        ([10.0, 10.5], 60.0),
        ([10.0, 10.5, 25.0, 25.5], 10.0),
        ([5.0, 11.0, 17.0], 60.0),
        ([round(10.0 + i * 0.5, 3) for i in range(30)], 60.0),
    ):
        samples = _samples(hits, duration=40.0)
        batch = evaluate_alarm_rule(samples, cooldown_seconds=cooldown)

        state = AlarmState(cooldown_seconds=cooldown)
        incremental = [f for f in (state.observe(t, d) for t, d in samples) if f]

        assert incremental == batch, f"divergence for hits={hits[:4]}... cooldown={cooldown}"


def test_tc_gar_13_reset_clears_state():
    """Disarm must not leave a half-full window that contributes to the next arming."""
    state = AlarmState()
    assert state.observe(10.0, True) is None          # one positive, window half full
    state.reset()
    assert state.observe(11.0, True) is None, (
        "a positive from before reset must not combine with one after it"
    )
    assert state.observe(12.0, True) is not None      # two after reset -> alarm


def test_tc_gar_14_cooldown_expires_on_negative_frames_too():
    """Cooldown must age out even while nothing is detected.

    If it only expired on positive frames, a quiet period followed by a real intrusion
    would be suppressed by a cooldown that should have lapsed long before.
    """
    state = AlarmState(cooldown_seconds=5.0)
    assert state.observe(10.0, True) is None
    assert state.observe(10.5, True) is not None      # alarm, cooldown until 15.5

    # Negative frames through the cooldown window.
    for t in (11.0, 12.0, 13.0, 14.0, 15.0, 16.0):
        assert state.observe(t, False) is None
    assert not state.in_cooldown, "cooldown should have expired on negative frames"

    assert state.observe(17.0, True) is None
    assert state.observe(18.0, True) is not None, "a new event after cooldown must alarm"


def test_tc_gar_15_invalid_parameters_are_rejected():
    for kwargs in ({"frames_required": 0}, {"window_seconds": 0}, {"window_seconds": -1}):
        with pytest.raises(ValueError):
            AlarmState(**kwargs)

