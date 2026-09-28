"""
Guard watchdog — CPU, disk, segment health (step 4, v3.42)
=========================================================

Three conditions with three deliberately different consequences, and the differences are
the point:

  * **CPU over limit -> SUSPEND.** Guard stops detecting and releases the model. Guard is
    shed first and alone; nothing here can touch the backend or berth occupancy.
  * **Disk low -> recording disabled ONLY.** Detection and alarms continue, because an
    alarm you know about with no video beats no alarm at all.
  * **Segment ring stalled -> UNAVAILABLE.** An alarm would have no video, so it is said as
    plainly as a full disk. Required input, not an optional extra.

`tick()` is a pure decision function with time injected, so hysteresis, the 24 h
auto-resume budget and the disk margins are all tested without sleeping, loading a CPU or
filling a disk.

  TC-GWD-01  no decision until the rolling window is FULL (never act on a spike)
  TC-GWD-02  sustained overload suspends; a brief burst does not
  TC-GWD-03  suspension does not resume early — quiet must be SUSTAINED
  TC-GWD-04  resume needs resume_after_s below cpu_resume, then re-arms
  TC-GWD-05  the quiet clock RESTARTS if CPU goes back up
  TC-GWD-06  auto-resume budget: 2 per 24 h, then awaits a human
  TC-GWD-07  the budget rolls off after 24 h
  TC-GWD-08  manual re-arm clears the budget and the CPU window
  TC-GWD-09  cpu_warn fires before the limit, and clears again
  TC-GWD-10  low disk disables RECORDING ONLY; detection keeps running
  TC-GWD-11  recording re-enables only past a margin (no flapping)
  TC-GWD-12  either GB or percent floor is enough to disable
  TC-GWD-13  a stalled ring makes guard UNAVAILABLE and reports why
  TC-GWD-14  a recovered ring returns to ARMED
  TC-GWD-15  LIMITED_VISIBILITY is a FLAG — state stays ARMED, detection continues
  TC-GWD-16  config rejects thresholds that would flap
  TC-GWD-17  CpuSampler needs two readings, and parses /proc/stat
  TC-GWD-18  disk_reading returns None for a missing path (not a disk problem)
  TC-GWD-19  the verdict describes ONLY guard — nothing else can be shed
  TC-GWD-20  CPU limit tripping MID-ASSEMBLY leaves no half clip and no stuck pin
  TC-GWD-21  arm() preserves the auto-resume budget; only rearm() clears it
  TC-GWD-22  arm() is refused while awaiting a manual re-arm
  TC-GWD-23  reading current_flags does NOT advance the state machine
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from guard_worker.watchdog import (
    FLAG_AWAITING_MANUAL_REARM,
    FLAG_CPU_WARN,
    FLAG_LIMITED_VISIBILITY,
    FLAG_NO_DISK,
    FLAG_SEGMENTS_STALLED,
    STATE_ARMED,
    STATE_OFF,
    STATE_SUSPENDED_CPU,
    STATE_UNAVAILABLE,
    CpuSampler,
    RollingWindow,
    Watchdog,
    WatchdogConfig,
    disk_reading,
)

HEALTHY_DISK = dict(disk_free_gb=100.0, disk_free_percent=50.0)


def _feed(wd: Watchdog, start: float, cpu: float, seconds: float, step: float = 5.0):
    """Feed a constant CPU reading for `seconds`, returning all transitions."""
    out = []
    t = start
    while t <= start + seconds:
        out += wd.tick(now=t, cpu_pct=cpu, **HEALTHY_DISK).transitions
        t += step
    return out


def _events(transitions) -> list[str]:
    return [t.event for t in transitions]


# ═══════════════════════════════════════════════════════════════════════════
# Never act on a spike
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gwd_01_no_decision_until_the_window_is_full():
    """A half-full window would let one inference burst at startup look like sustained
    overload and suspend guard seconds after arming."""
    w = RollingWindow(60.0)
    assert w.average() is None
    w.add(0.0, 99.0)
    assert w.ready() is False and w.average() is None
    w.add(30.0, 99.0)
    assert w.ready() is False, "30 s of samples is not a 60 s window"
    w.add(60.0, 99.0)
    assert w.ready() is True
    assert w.average() == pytest.approx(99.0)

    wd = Watchdog()
    # Screaming CPU, but only for 30 s: no suspension.
    assert _events(_feed(wd, 1_000.0, 95.0, seconds=30.0)) == []
    assert wd.state == STATE_ARMED


def test_tc_gwd_02_sustained_overload_suspends_a_burst_does_not():
    wd = Watchdog()
    events = _events(_feed(wd, 1_000.0, 95.0, seconds=60.0))
    assert "suspended_cpu" in events
    assert wd.state == STATE_SUSPENDED_CPU

    # A brief burst inside an otherwise quiet window must not.
    wd2 = Watchdog()
    t = 2_000.0
    for i in range(13):                       # 60 s of 10 %
        wd2.tick(now=t + i * 5, cpu_pct=10.0, **HEALTHY_DISK)
    v = wd2.tick(now=t + 70, cpu_pct=99.0, **HEALTHY_DISK)   # one spike
    assert wd2.state == STATE_ARMED, "a single spike must not suspend"
    assert v.cpu_avg is not None and v.cpu_avg < 60.0


# ═══════════════════════════════════════════════════════════════════════════
# Hysteresis
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gwd_03_and_04_resume_needs_sustained_quiet():
    cfg = WatchdogConfig(resume_after_s=300.0)
    wd = Watchdog(cfg)
    _feed(wd, 0.0, 95.0, seconds=60.0)
    assert wd.state == STATE_SUSPENDED_CPU

    # Quiet, but not for long enough yet.
    events = _events(_feed(wd, 100.0, 10.0, seconds=200.0))
    assert "resumed_cpu" not in events
    assert wd.state == STATE_SUSPENDED_CPU, "200 s < resume_after_s"

    # Keep going past the threshold.
    events = _events(_feed(wd, 310.0, 10.0, seconds=200.0))
    assert "resumed_cpu" in events
    assert wd.state == STATE_ARMED


def test_tc_gwd_05_quiet_clock_restarts_if_cpu_rises_again():
    """Otherwise a machine flapping around the limit would eventually resume on an
    accumulation of unrelated quiet moments."""
    wd = Watchdog(WatchdogConfig(resume_after_s=300.0))
    _feed(wd, 0.0, 95.0, seconds=60.0)
    assert wd.state == STATE_SUSPENDED_CPU

    _feed(wd, 100.0, 10.0, seconds=200.0)      # 200 s quiet
    _feed(wd, 310.0, 70.0, seconds=70.0)       # back above cpu_resume -> clock resets
    events = _events(_feed(wd, 390.0, 10.0, seconds=200.0))
    assert "resumed_cpu" not in events, "the sustained-quiet clock must have restarted"
    assert wd.state == STATE_SUSPENDED_CPU


def test_tc_gwd_06_auto_resume_budget_then_awaits_a_human():
    """Endless auto-resumes would hide a box that is repeatedly overloaded."""
    cfg = WatchdogConfig(resume_after_s=60.0, max_auto_resumes=2)
    wd = Watchdog(cfg)
    t = 0.0
    for cycle in range(2):
        _feed(wd, t, 95.0, seconds=60.0)
        assert wd.state == STATE_SUSPENDED_CPU, f"cycle {cycle}"
        t += 70.0
        _feed(wd, t, 5.0, seconds=140.0)
        assert wd.state == STATE_ARMED, f"cycle {cycle} should auto-resume"
        t += 150.0
    assert wd.auto_resumes_used(t) == 2

    # Third overload: suspends, and does NOT auto-resume.
    _feed(wd, t, 95.0, seconds=60.0)
    assert wd.state == STATE_SUSPENDED_CPU
    t += 70.0
    events = _events(_feed(wd, t, 5.0, seconds=200.0))
    assert "resumed_cpu" not in events
    assert FLAG_AWAITING_MANUAL_REARM in events or "awaiting_manual_rearm" in events
    assert wd.state == STATE_SUSPENDED_CPU, "must wait for a human"


def test_tc_gwd_07_budget_rolls_off_after_24h():
    wd = Watchdog(WatchdogConfig(resume_after_s=60.0, max_auto_resumes=2))
    wd._auto_resumes = [1_000.0, 2_000.0]
    assert wd.auto_resumes_used(3_000.0) == 2
    assert wd.auto_resumes_used(1_000.0 + 86_400.0 + 1) == 1, "the first has aged out"
    assert wd.auto_resumes_used(2_000.0 + 86_400.0 + 1) == 0


def test_tc_gwd_08_manual_rearm_clears_budget_and_window():
    """A human has looked at it, so the machine gets its allowance back — and must not be
    re-suspended instantly by samples describing the overload it just recovered from."""
    wd = Watchdog(WatchdogConfig(resume_after_s=60.0, max_auto_resumes=1))
    _feed(wd, 0.0, 95.0, seconds=60.0)
    assert wd.state == STATE_SUSPENDED_CPU
    assert wd.cpu_avg is not None

    events = _events(wd.manual_rearm(now=500.0))
    assert events == ["rearmed"]
    assert wd.state == STATE_ARMED
    assert wd.auto_resumes_used(500.0) == 0, "budget restored"
    assert wd.cpu_avg is None, "the CPU window must be cleared, not inherited"


def test_tc_gwd_09_cpu_warn_fires_before_the_limit():
    wd = Watchdog(WatchdogConfig(cpu_warn=50.0, cpu_limit=60.0))
    events = _events(_feed(wd, 0.0, 55.0, seconds=60.0))
    assert "cpu_warn" in events, "a warning must be visible before it becomes a suspension"
    assert wd.state == STATE_ARMED
    assert FLAG_CPU_WARN in wd.tick(now=100.0, cpu_pct=55.0, **HEALTHY_DISK).flags

    # Fires once, not per tick.
    more = _events(_feed(wd, 110.0, 55.0, seconds=30.0))
    assert "cpu_warn" not in more

    events = _events(_feed(wd, 200.0, 10.0, seconds=70.0))
    assert "cpu_ok" in events
    assert FLAG_CPU_WARN not in wd.tick(now=400.0, cpu_pct=10.0, **HEALTHY_DISK).flags


# ═══════════════════════════════════════════════════════════════════════════
# Disk — recording only
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gwd_10_low_disk_disables_recording_only():
    """Deliberate asymmetry with CPU: an alarm you know about with no video is far more
    useful than no alarm at all."""
    wd = Watchdog()
    v = wd.tick(now=0.0, cpu_pct=5.0, disk_free_gb=2.0, disk_free_percent=4.0)
    assert v.recording_enabled is False
    assert FLAG_NO_DISK in v.flags
    assert v.state == STATE_ARMED, "detection must CONTINUE on a low disk"
    assert v.detecting is True
    ev = [t for t in v.transitions if t.event == "recording_disabled"]
    assert ev and "DETECTION CONTINUES" in ev[0].reason


def test_tc_gwd_11_recording_reenables_only_past_a_margin():
    """A disk hovering at the floor would otherwise flap recording on and off around every
    clip."""
    cfg = WatchdogConfig(disk_min_gb=5.0, disk_margin_gb=1.0,
                         disk_min_percent=10.0, disk_margin_percent=1.0)
    wd = Watchdog(cfg)
    wd.tick(now=0.0, cpu_pct=5.0, disk_free_gb=2.0, disk_free_percent=4.0)
    assert wd.recording_enabled is False

    # Just back over the floor, but inside the margin: still disabled.
    v = wd.tick(now=60.0, cpu_pct=5.0, disk_free_gb=5.2, disk_free_percent=10.2)
    assert v.recording_enabled is False, "must clear the margin, not just the floor"

    v = wd.tick(now=120.0, cpu_pct=5.0, disk_free_gb=6.5, disk_free_percent=12.0)
    assert v.recording_enabled is True
    assert "recording_enabled" in _events(v.transitions)
    assert FLAG_NO_DISK not in v.flags


def test_tc_gwd_12_either_floor_is_enough():
    """A big disk can be under 10 % while still holding plenty of GB, and a small one the
    reverse. Either alone must disable recording."""
    wd = Watchdog()
    v = wd.tick(now=0.0, cpu_pct=5.0, disk_free_gb=200.0, disk_free_percent=4.0)
    assert v.recording_enabled is False, "percent floor alone"

    wd2 = Watchdog()
    v2 = wd2.tick(now=0.0, cpu_pct=5.0, disk_free_gb=1.0, disk_free_percent=80.0)
    assert v2.recording_enabled is False, "GB floor alone"


# ═══════════════════════════════════════════════════════════════════════════
# Segment health — required, not optional
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gwd_13_stalled_ring_makes_guard_unavailable():
    """Without this the failure is SILENT: the process runs, frames arrive, the dashboard
    says ARMED — and nothing is retained, so an alarm would have no video."""
    wd = Watchdog()
    v = wd.tick(now=0.0, cpu_pct=5.0, segments_stalled=True,
                stall_reason="no new segment and no byte growth for 45s", **HEALTHY_DISK)
    assert v.state == STATE_UNAVAILABLE, "guard genuinely cannot do its job"
    assert v.detecting is False
    assert FLAG_SEGMENTS_STALLED in v.flags
    ev = [t for t in v.transitions if t.event == "segments_stalled"]
    assert ev and "45s" in ev[0].reason


def test_tc_gwd_14_recovered_ring_returns_to_armed():
    wd = Watchdog()
    wd.tick(now=0.0, cpu_pct=5.0, segments_stalled=True, **HEALTHY_DISK)
    assert wd.state == STATE_UNAVAILABLE
    v = wd.tick(now=30.0, cpu_pct=5.0, segments_stalled=False, **HEALTHY_DISK)
    assert v.state == STATE_ARMED
    assert "segments_recovered" in _events(v.transitions)
    assert FLAG_SEGMENTS_STALLED not in v.flags


def test_tc_gwd_15_limited_visibility_is_a_flag_not_a_state():
    """It must not compete with ARMED: detection keeps running while it is set, and every
    event raised now is stamped so a weak detection is explainable rather than mysterious."""
    wd = Watchdog()
    v = wd.tick(now=0.0, cpu_pct=5.0, limited_visibility=True, **HEALTHY_DISK)
    assert v.state == STATE_ARMED, "visibility must NOT change the state"
    assert v.detecting is True
    assert FLAG_LIMITED_VISIBILITY in v.flags
    ev = [t for t in v.transitions if t.event == "limited_visibility_on"]
    assert ev and "CONTINUES" in ev[0].reason

    v = wd.tick(now=10.0, cpu_pct=5.0, limited_visibility=False, **HEALTHY_DISK)
    assert FLAG_LIMITED_VISIBILITY not in v.flags
    assert "limited_visibility_off" in _events(v.transitions)


# ═══════════════════════════════════════════════════════════════════════════
# Config, sampling, and the scope guarantee
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gwd_16_config_rejects_flapping_thresholds():
    WatchdogConfig()
    with pytest.raises(ValueError, match="cpu_resume"):
        WatchdogConfig(cpu_limit=60.0, cpu_resume=60.0)      # equal -> flaps
    with pytest.raises(ValueError, match="cpu_resume"):
        WatchdogConfig(cpu_limit=50.0, cpu_resume=70.0)      # inverted
    with pytest.raises(ValueError, match="cpu_warn"):
        WatchdogConfig(cpu_warn=80.0, cpu_limit=60.0)
    with pytest.raises(ValueError, match="window_s"):
        WatchdogConfig(window_s=0)


def test_tc_gwd_17_cpu_sampler_needs_two_readings(tmp_path):
    stat = tmp_path / "stat"
    # user nice system idle iowait irq softirq
    stat.write_text("cpu  100 0 50 800 50 0 0\ncpu0 1 2 3 4\n", encoding="ascii")
    s = CpuSampler(str(stat))
    assert s.sample() is None, "a percentage needs two readings"

    # +100 busy, +100 idle -> 50 %
    stat.write_text("cpu  150 0 100 850 100 0 0\ncpu0 1 2 3 4\n", encoding="ascii")
    assert s.sample() == pytest.approx(50.0, abs=0.5)

    # A missing or malformed file must not raise — sampling failure is not a crash.
    assert CpuSampler(str(tmp_path / "nope")).sample() is None
    bad = tmp_path / "bad"
    bad.write_text("not-cpu-at-all\n", encoding="ascii")
    assert CpuSampler(str(bad)).sample() is None


def test_tc_gwd_18_disk_reading_missing_path_is_not_a_disk_problem(tmp_path):
    """At first start the recordings directory may not exist yet."""
    assert disk_reading(tmp_path / "does-not-exist") is None
    reading = disk_reading(tmp_path)
    assert reading is not None
    free_gb, free_pct = reading
    assert free_gb > 0 and 0 <= free_pct <= 100


def test_tc_gwd_19_verdict_describes_only_guard():
    """Guard is the first and only thing shed. The verdict surface must offer no way to
    stop the backend, MQTT or berth occupancy — the guarantee is structural, not a promise
    in a comment."""
    wd = Watchdog()
    v = wd.tick(now=0.0, cpu_pct=5.0, **HEALTHY_DISK)
    fields = set(vars(v))
    assert fields == {"state", "recording_enabled", "flags", "cpu_avg",
                      "disk_free_gb", "transitions"}
    for forbidden in ("backend", "berth", "mqtt", "uvicorn", "stop_backend"):
        assert not any(forbidden in f for f in fields)

    # Disarm only ever moves guard to OFF.
    assert _events(wd.disarm()) == ["disarmed"]
    assert wd.state == STATE_OFF
    assert wd.tick(now=10.0, cpu_pct=99.0, **HEALTHY_DISK).state == STATE_OFF


# ═══════════════════════════════════════════════════════════════════════════
# TC-GWD-20 — the requested integration: CPU limit trips MID-ASSEMBLY
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_gwd_20_cpu_suspension_mid_assembly_leaves_no_half_clip(tmp_path, monkeypatch):
    """The watchdog kills the worker abruptly BY DESIGN, so step 3's atomic rename is what
    makes that safe. This drives the two together.

    Simulated kill: the concat subprocess writes a partial `.part` and then dies, exactly as
    a SIGKILL mid-assembly would leave it. The assertions are the ones that matter — no file
    under a COMPLETE name, no `.part` survivor, and no pin left holding the ring.
    """
    import subprocess as real_subprocess

    from guard_worker import recorder as rec
    from guard_worker.capture import prune_segments
    from guard_worker.recorder import ClipAssembler, RecordingConfig, sweep_orphan_parts

    seg_dir = tmp_path / "segments"
    seg_dir.mkdir()
    segs = []
    for i in range(4):
        p = seg_dir / f"seg_{i:06d}.ts"
        p.write_bytes(b"x" * 256)
        segs.append(p)

    cfg = RecordingConfig(storage_path=tmp_path / "recordings", segment_seconds=2,
                          record_seconds=60, ffmpeg="ffmpeg")
    asm = ClipAssembler(cfg, seg_dir)

    wd = Watchdog()
    pin_seen_during_assembly: set[str] = set()

    def killed_mid_write(cmd, *args, **kwargs):
        """Write a partial .part, then report death — as SIGKILL would."""
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 128)          # a truncated, unplayable fragment
        # The pin MUST be held while the assembly is outstanding, or the ring could delete
        # the pre-roll from under it.
        pin_seen_during_assembly.update(asm.pinned_segments)
        # Meanwhile CPU goes through the roof and the watchdog decides to shed guard.
        _feed(wd, 0.0, 97.0, seconds=60.0)
        return real_subprocess.CompletedProcess(cmd, returncode=137, stdout="",
                                                stderr="Killed")

    monkeypatch.setattr(rec.subprocess, "run", killed_mid_write)

    clip = asm.assemble(1, datetime(2026, 9, 27, 14, 32, 7), segs[:3])

    # The watchdog did suspend, which is the scenario.
    assert wd.state == STATE_SUSPENDED_CPU
    assert pin_seen_during_assembly, "segments must be pinned DURING assembly"

    # 1. No clip under a complete name.
    assert clip is None
    out_dir = cfg.camera_dir(1)
    finals = list(out_dir.glob("*.mp4")) if out_dir.exists() else []
    assert finals == [], (
        f"a half clip appeared under a COMPLETE name: {finals}. The atomic .part -> rename "
        "is what prevents an abrupt kill from producing evidence that looks whole."
    )

    # 2. No .part survivor, and the sweep is a no-op because assemble already cleaned up.
    parts = list(out_dir.glob("*.part")) if out_dir.exists() else []
    assert parts == [], f"a .part was left behind: {parts}"
    assert sweep_orphan_parts(cfg, 1) == []

    # 3. No pin left holding the ring — a leak here would stop it reclaiming space forever.
    assert asm.pinned_segments == frozenset(), "the pin MUST be released after a kill"
    deleted = prune_segments(seg_dir, keep=1, pinned=asm.pinned_segments)
    assert len(deleted) == 3, (
        "the ring must be free to prune again; a stuck pin would silently fill the disk"
    )

    # 4. And the recovery path works: a human re-arms, and guard is usable again.
    assert _events(wd.manual_rearm(now=1_000.0)) == ["rearmed"]
    assert wd.state == STATE_ARMED


# ─── TC-GWD-21 .. TC-GWD-23 — arm(), added with the worker entrypoint ─────────
#
# These exist because building the entrypoint exposed that the watchdog had no way to be
# ARMED at all: `manual_rearm` was the only path back from OFF, and it clears the
# auto-resume budget. Using it for an ordinary `enable` would have quietly given an operator
# an unlimited budget just by disabling and re-enabling.

def test_tc_gwd_21_arm_preserves_the_auto_resume_budget():
    """`enable` must NOT hand back the auto-resume allowance; only `rearm` does.

    Otherwise disable-then-enable is a budget reset, and a persistently overloaded box goes
    back to shedding guard every few minutes forever — the exact loop the budget prevents.
    """
    wd = Watchdog(WatchdogConfig(cpu_limit=60.0, cpu_resume=45.0, resume_after_s=300.0,
                                 max_auto_resumes=2, window_s=60.0))
    # Burn one auto-resume: overload, then sustained quiet.
    _feed(wd, 0.0, 90.0, 120.0)
    assert wd.state == STATE_SUSPENDED_CPU
    _feed(wd, 200.0, 10.0, 400.0)
    assert wd.state == STATE_ARMED
    assert wd.auto_resumes_used(700.0) == 1

    wd.disarm()
    assert wd.state == STATE_OFF
    events = _events(wd.arm())
    assert events == ["armed"], f"expected a single armed transition, got {events}"
    assert wd.state == STATE_ARMED
    assert wd.auto_resumes_used(700.0) == 1, (
        "arm() reset the auto-resume budget; that is what rearm is for, and letting enable "
        "do it makes the budget meaningless"
    )


def test_tc_gwd_22_arm_is_refused_while_awaiting_a_manual_rearm():
    """Once the machine has given up resuming itself, `enable` is not the answer.

    The flag means "a human needs to look". Arming on `enable` would let the UI's ordinary
    toggle bypass that, and guard would be suspended again within the minute — which reads
    to the operator as guard being broken rather than the box being overloaded.
    """
    wd = Watchdog(WatchdogConfig(cpu_limit=60.0, cpu_resume=45.0, resume_after_s=300.0,
                                 max_auto_resumes=1, window_s=60.0))
    _feed(wd, 0.0, 90.0, 120.0)
    _feed(wd, 200.0, 10.0, 400.0)          # spends the only auto-resume
    _feed(wd, 700.0, 90.0, 120.0)          # overloaded again -> suspended
    _feed(wd, 900.0, 10.0, 400.0)          # quiet, but the budget is gone
    assert wd.state == STATE_SUSPENDED_CPU
    assert FLAG_AWAITING_MANUAL_REARM in wd.current_flags

    events = _events(wd.arm())
    assert events == ["arm_refused"], f"arm() should refuse, got {events}"
    assert wd.state == STATE_SUSPENDED_CPU, "a refused arm must not change the state"

    # And the documented way out still works.
    assert _events(wd.manual_rearm(now=1_400.0)) == ["rearmed"]
    assert wd.state == STATE_ARMED
    assert FLAG_AWAITING_MANUAL_REARM not in wd.current_flags


def test_tc_gwd_23_current_flags_does_not_advance_the_machine():
    """Reading the flags must not be a tick.

    The worker publishes state on every transition, and the obvious way to fill in `flags`
    is `tick().flags`. But a tick with no readings looks like "disk fine, ring healthy, view
    usable", so publishing a state message would CLEAR segments_stalled and
    limited_visibility as a side effect — the flag would vanish from the very message meant
    to report it.
    """
    wd = Watchdog(WatchdogConfig(window_s=60.0))
    wd.tick(now=0.0, segments_stalled=True, stall_reason="no new segments",
            limited_visibility=True, **HEALTHY_DISK)
    assert FLAG_SEGMENTS_STALLED in wd.current_flags
    assert FLAG_LIMITED_VISIBILITY in wd.current_flags
    state_before = wd.state

    for _ in range(5):
        flags = wd.current_flags

    assert FLAG_SEGMENTS_STALLED in flags, "reading the flags cleared segments_stalled"
    assert FLAG_LIMITED_VISIBILITY in flags, "reading the flags cleared limited_visibility"
    assert wd.state == state_before, "reading the flags changed the state"
