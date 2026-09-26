"""
Guard alarm rule — anti-flicker in time (Stage A.5, v3.41)
==========================================================

The spec's mandatory anti-flicker rule: alarm when a person is detected in at
least N inferences inside a rolling W-second window, then a cooldown before
another alarm can fire. Frame-level recall can look excellent and still produce a
false alarm every ten minutes, so this rule — not per-frame accuracy — is what the
marina actually experiences.

The implementation lives in `scripts/guard_detect_probe.py` as a pure function so
the measurement run and the future Stage B service share one definition. Stage B
must PROMOTE it into `app/guard/` rather than reimplement it; these tests move with
it. Loaded here via importlib because `scripts/` is not an importable package.

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
"""
from __future__ import annotations

import importlib.util
import os

import pytest

_PROBE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "guard_detect_probe.py",
)


def _load_rule():
    spec = importlib.util.spec_from_file_location("guard_detect_probe", _PROBE)
    assert spec and spec.loader, f"could not load {_PROBE}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.evaluate_alarm_rule


evaluate_alarm_rule = _load_rule()


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
    """4 s apart with a 3 s window — the first has aged out before the second."""
    assert evaluate_alarm_rule(_samples([10.0, 14.0])) == []


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
