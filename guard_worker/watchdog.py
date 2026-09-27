"""
Guard watchdog — CPU, disk, and segment health.

Build order step 4. Mandatory, not a nice-to-have: this is what keeps guard from ever
degrading the marina it is meant to watch.

Three independent conditions, with three deliberately different consequences:

| Condition | Consequence | Why that one |
|---|---|---|
| CPU over limit | **SUSPEND** — stop detecting, release the model | guard is the only thing shed; the backend and berth occupancy are never touched |
| Disk low | **recording disabled ONLY** — detection and alarms continue | an alarm you know about with no video beats no alarm at all |
| Segment ring stalled | **UNAVAILABLE** | an alarm would have no video, so the operator must be told as plainly as a full disk |

`Watchdog.tick()` is a pure decision function over readings, with time injected. Sampling
lives in `CpuSampler`/`disk_reading()` and is separate, so the state machine — hysteresis,
the auto-resume budget, disk margins — is testable without sleeping, loading a CPU, or
filling a disk. Every one of those is otherwise a thing you find out about in production.

Two rules the design exists to enforce:

1. **Never act on a single spike.** Decisions use a rolling average over `window_s`, and
   nothing suspends until the window is actually full. A momentary inference burst is not
   an overload.
2. **Guard is the first and only thing shed.** Nothing here can stop the backend, the MQTT
   bridge or berth occupancy. The verdict surface only describes guard.

Stdlib only, like the rest of the worker: CPU comes from `/proc/stat`, disk from
`shutil.disk_usage`. No psutil, so the worker venv stays at openvino + numpy + Pillow.
"""
from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Guard's own state, as reported to the backend. LIMITED_VISIBILITY is deliberately NOT
# here: it is a health FLAG, because detection keeps running while it is set and it would
# otherwise have to compete with ARMED.
STATE_OFF = "OFF"
STATE_ARMED = "ARMED"
STATE_SUSPENDED_CPU = "SUSPENDED_CPU"
STATE_UNAVAILABLE = "UNAVAILABLE"

FLAG_CPU_WARN = "cpu_warn"
FLAG_NO_DISK = "no_disk"
FLAG_SEGMENTS_STALLED = "segments_stalled"
FLAG_AWAITING_MANUAL_REARM = "awaiting_manual_rearm"
FLAG_LIMITED_VISIBILITY = "limited_visibility"

_SECONDS_PER_DAY = 86_400.0


@dataclass
class WatchdogConfig:
    # CPU, as a percentage of ALL cores. CPUQuota=60% in the unit caps guard at 15 % of a
    # 4-core box independently; these thresholds are about the whole machine, so a busy
    # backend also sheds guard.
    cpu_warn: float = 50.0
    cpu_limit: float = 60.0
    cpu_resume: float = 45.0
    resume_after_s: float = 300.0
    max_auto_resumes: int = 2
    window_s: float = 60.0

    # Disk, on the recordings volume.
    disk_min_gb: float = 5.0
    disk_min_percent: float = 10.0
    disk_margin_gb: float = 1.0
    disk_margin_percent: float = 1.0

    def __post_init__(self) -> None:
        if not (self.cpu_resume < self.cpu_limit):
            raise ValueError("cpu_resume must be BELOW cpu_limit or resume would flap")
        if not (self.cpu_warn <= self.cpu_limit):
            raise ValueError("cpu_warn must be at or below cpu_limit")
        if self.window_s <= 0:
            raise ValueError("window_s must be > 0")


@dataclass
class Transition:
    """Something the worker must publish. Every state change is reported, never silent."""
    event: str
    reason: str
    detail: dict = field(default_factory=dict)


@dataclass
class Verdict:
    """Guard's current disposition. Describes ONLY guard — by construction."""
    state: str
    recording_enabled: bool
    flags: list[str]
    cpu_avg: float | None
    disk_free_gb: float | None
    transitions: list[Transition]

    @property
    def detecting(self) -> bool:
        return self.state == STATE_ARMED


class RollingWindow:
    """Timestamped samples over a fixed span.

    `average()` returns None until the window is FULL. That is the whole point: a
    half-populated window would let one inference burst at startup look like sustained
    overload and suspend guard seconds after arming.
    """

    def __init__(self, span_s: float):
        self.span_s = span_s
        self._samples: list[tuple[float, float]] = []

    def add(self, at: float, value: float) -> None:
        self._samples.append((at, value))
        cutoff = at - self.span_s
        self._samples = [(t, v) for t, v in self._samples if t >= cutoff]

    def clear(self) -> None:
        self._samples.clear()

    @property
    def span(self) -> float:
        if len(self._samples) < 2:
            return 0.0
        return self._samples[-1][0] - self._samples[0][0]

    def ready(self) -> bool:
        return len(self._samples) >= 2 and self.span >= self.span_s

    def average(self) -> float | None:
        if not self.ready():
            return None
        return sum(v for _, v in self._samples) / len(self._samples)

    def latest(self) -> float | None:
        return self._samples[-1][1] if self._samples else None


class Watchdog:
    """The state machine. Feed it readings; it tells you what guard should be doing."""

    def __init__(self, cfg: WatchdogConfig | None = None):
        self.cfg = cfg or WatchdogConfig()
        self._cpu = RollingWindow(self.cfg.window_s)
        self.state = STATE_ARMED
        self.recording_enabled = True
        self._flags: set[str] = set()
        self._below_resume_since: float | None = None
        self._auto_resumes: list[float] = []      # timestamps, pruned to 24 h
        self._suspended_at: float | None = None

    # ── introspection ──

    @property
    def cpu_avg(self) -> float | None:
        return self._cpu.average()

    def auto_resumes_used(self, now: float) -> int:
        self._prune_resumes(now)
        return len(self._auto_resumes)

    def _prune_resumes(self, now: float) -> None:
        self._auto_resumes = [t for t in self._auto_resumes
                              if now - t < _SECONDS_PER_DAY]

    # ── human control ──

    def manual_rearm(self, now: float) -> list[Transition]:
        """An operator re-enabling guard after a suspension.

        Clears the auto-resume budget deliberately: the human has looked at it, so the
        machine gets its allowance back. This is why `/api/guard/{id}/rearm` is a separate
        endpoint from `enable` — the two mean different things.
        """
        was = self.state
        self.state = STATE_ARMED
        self._flags.discard(FLAG_AWAITING_MANUAL_REARM)
        self._below_resume_since = None
        self._suspended_at = None
        self._auto_resumes.clear()
        # Start the CPU window fresh: pre-suspension samples describe a machine that was
        # overloaded, and judging the re-armed guard on them would re-suspend it at once.
        self._cpu.clear()
        return [Transition("rearmed", f"manual re-arm from {was}", {"previous": was})]

    def disarm(self) -> list[Transition]:
        was = self.state
        self.state = STATE_OFF
        self._flags.clear()
        self._cpu.clear()
        self._below_resume_since = None
        self._suspended_at = None
        return [Transition("disarmed", f"guard disabled from {was}", {"previous": was})]

    # ── the tick ──

    def tick(
        self,
        *,
        now: float,
        cpu_pct: float | None = None,
        disk_free_gb: float | None = None,
        disk_free_percent: float | None = None,
        segments_stalled: bool = False,
        stall_reason: str | None = None,
        limited_visibility: bool = False,
    ) -> Verdict:
        """One watchdog cycle. Call every `sample_interval` seconds while armed."""
        transitions: list[Transition] = []

        if self.state == STATE_OFF:
            return Verdict(STATE_OFF, self.recording_enabled, [], None, disk_free_gb, [])

        if cpu_pct is not None:
            self._cpu.add(now, cpu_pct)

        # ── visibility: a flag, never a state ──
        if limited_visibility and FLAG_LIMITED_VISIBILITY not in self._flags:
            self._flags.add(FLAG_LIMITED_VISIBILITY)
            transitions.append(Transition(
                "limited_visibility_on",
                "the view is too dark or too featureless to detect reliably; detection "
                "CONTINUES and every event raised now is stamped so a weak detection is "
                "explainable later",
            ))
        elif not limited_visibility and FLAG_LIMITED_VISIBILITY in self._flags:
            self._flags.discard(FLAG_LIMITED_VISIBILITY)
            transitions.append(Transition("limited_visibility_off", "the view is usable again"))

        # ── segment ring: an alarm with no video must be said out loud ──
        transitions += self._check_segments(segments_stalled, stall_reason)

        # ── disk: disables RECORDING only ──
        transitions += self._check_disk(disk_free_gb, disk_free_percent)

        # ── CPU: suspends guard ──
        transitions += self._check_cpu(now)

        return Verdict(
            state=self.state,
            recording_enabled=self.recording_enabled,
            flags=sorted(self._flags),
            cpu_avg=self._cpu.average(),
            disk_free_gb=disk_free_gb,
            transitions=transitions,
        )

    # ── conditions ──

    def _check_segments(self, stalled: bool, reason: str | None) -> list[Transition]:
        """A stalled ring is a REQUIRED input, not an optional extra.

        Without it the failure is silent: the process runs, frames arrive, the dashboard
        says ARMED — and nothing is being retained, so an alarm would have no video. It is
        reported as plainly as a full disk, and it makes guard UNAVAILABLE rather than a
        flag on an otherwise-healthy state, because guard genuinely cannot do its job.
        """
        out: list[Transition] = []
        if stalled and FLAG_SEGMENTS_STALLED not in self._flags:
            self._flags.add(FLAG_SEGMENTS_STALLED)
            if self.state == STATE_ARMED:
                self.state = STATE_UNAVAILABLE
            out.append(Transition(
                "segments_stalled",
                reason or "the segment ring has stopped producing files, so an alarm "
                          "would have no video",
            ))
            logger.error("Guard watchdog: segment ring STALLED — %s", reason or "no detail")
        elif not stalled and FLAG_SEGMENTS_STALLED in self._flags:
            self._flags.discard(FLAG_SEGMENTS_STALLED)
            if self.state == STATE_UNAVAILABLE:
                self.state = STATE_ARMED
            out.append(Transition("segments_recovered", "the segment ring is producing again"))
        return out

    def _check_disk(self, free_gb: float | None, free_percent: float | None) -> list[Transition]:
        """Low disk disables RECORDING only. Detection and alarms continue.

        Deliberate asymmetry with CPU: an alarm you know about with no video is far more
        useful than no alarm at all, so the event is still logged and published with
        `video_skipped`. Re-enabling needs a margin above the threshold, or a disk hovering
        at the limit would flap recording on and off around every clip.
        """
        out: list[Transition] = []
        if free_gb is None and free_percent is None:
            return out

        below = (
            (free_gb is not None and free_gb < self.cfg.disk_min_gb)
            or (free_percent is not None and free_percent < self.cfg.disk_min_percent)
        )
        above_with_margin = (
            (free_gb is None or free_gb >= self.cfg.disk_min_gb + self.cfg.disk_margin_gb)
            and (free_percent is None
                 or free_percent >= self.cfg.disk_min_percent + self.cfg.disk_margin_percent)
        )

        if below and self.recording_enabled:
            self.recording_enabled = False
            self._flags.add(FLAG_NO_DISK)
            out.append(Transition(
                "recording_disabled",
                f"free space below the floor (free={free_gb} GB / {free_percent} %, "
                f"floor={self.cfg.disk_min_gb} GB / {self.cfg.disk_min_percent} %). "
                f"DETECTION CONTINUES — events are logged with video_skipped.",
                {"free_gb": free_gb, "free_percent": free_percent},
            ))
            logger.warning("Guard watchdog: recording disabled — low disk "
                           "(%s GB / %s %%). Detection continues.", free_gb, free_percent)
        elif not self.recording_enabled and above_with_margin:
            self.recording_enabled = True
            self._flags.discard(FLAG_NO_DISK)
            out.append(Transition(
                "recording_enabled",
                f"free space recovered past the margin (free={free_gb} GB / "
                f"{free_percent} %)",
                {"free_gb": free_gb, "free_percent": free_percent},
            ))
        return out

    def _check_cpu(self, now: float) -> list[Transition]:
        out: list[Transition] = []
        avg = self._cpu.average()
        if avg is None:
            # Window not full yet. Deliberately no decision — see RollingWindow.
            return out

        if self.state == STATE_SUSPENDED_CPU:
            if avg < self.cfg.cpu_resume:
                if self._below_resume_since is None:
                    self._below_resume_since = now
                elif now - self._below_resume_since >= self.cfg.resume_after_s:
                    out += self._try_auto_resume(now, avg)
            else:
                # Went back up: the sustained-quiet clock restarts.
                self._below_resume_since = None
            return out

        if self.state != STATE_ARMED:
            return out          # UNAVAILABLE: the ring is the problem, not the CPU

        if avg > self.cfg.cpu_limit:
            self.state = STATE_SUSPENDED_CPU
            self._suspended_at = now
            self._below_resume_since = None
            self._flags.discard(FLAG_CPU_WARN)
            out.append(Transition(
                "suspended_cpu",
                f"60 s average CPU {avg:.1f} % exceeded the limit "
                f"{self.cfg.cpu_limit:.0f} %. Guard is shed FIRST and alone — the backend "
                f"and berth occupancy are not touched.",
                {"cpu_avg": round(avg, 1), "limit": self.cfg.cpu_limit},
            ))
            logger.warning("Guard watchdog: SUSPENDED on CPU (%.1f %% > %.0f %%)",
                           avg, self.cfg.cpu_limit)
        elif avg > self.cfg.cpu_warn:
            if FLAG_CPU_WARN not in self._flags:
                self._flags.add(FLAG_CPU_WARN)
                out.append(Transition(
                    "cpu_warn",
                    f"60 s average CPU {avg:.1f} % is above the warning level "
                    f"{self.cfg.cpu_warn:.0f} % — visible before it becomes a suspension",
                    {"cpu_avg": round(avg, 1)},
                ))
        elif FLAG_CPU_WARN in self._flags:
            self._flags.discard(FLAG_CPU_WARN)
            out.append(Transition("cpu_ok", f"60 s average CPU {avg:.1f} % back to normal"))
        return out

    def _try_auto_resume(self, now: float, avg: float) -> list[Transition]:
        self._prune_resumes(now)
        if len(self._auto_resumes) >= self.cfg.max_auto_resumes:
            if FLAG_AWAITING_MANUAL_REARM not in self._flags:
                self._flags.add(FLAG_AWAITING_MANUAL_REARM)
                logger.warning(
                    "Guard watchdog: auto-resume budget exhausted (%d in 24 h) — staying "
                    "suspended until a human re-arms", len(self._auto_resumes),
                )
                return [Transition(
                    "awaiting_manual_rearm",
                    f"CPU has recovered, but {len(self._auto_resumes)} automatic resumes "
                    f"have already been used in 24 h (limit "
                    f"{self.cfg.max_auto_resumes}). Guard stays suspended until an "
                    f"operator re-arms it: something is repeatedly overloading this box "
                    f"and hiding that behind endless auto-resumes would be wrong.",
                    {"auto_resumes": len(self._auto_resumes)},
                )]
            return []

        self._auto_resumes.append(now)
        self.state = STATE_ARMED
        self._below_resume_since = None
        self._suspended_at = None
        self._cpu.clear()       # judge the re-armed guard on fresh samples only
        return [Transition(
            "resumed_cpu",
            f"60 s average CPU stayed below {self.cfg.cpu_resume:.0f} % for "
            f"{self.cfg.resume_after_s:.0f} s (last {avg:.1f} %)",
            {"auto_resumes": len(self._auto_resumes),
             "max": self.cfg.max_auto_resumes},
        )]


# ─── sampling (separate from the decision, so the decision is testable) ──────

class CpuSampler:
    """Whole-machine CPU percentage from `/proc/stat`.

    stdlib rather than psutil, so the worker venv stays at openvino + numpy + Pillow. The
    first call returns None because a percentage needs two readings.
    """

    def __init__(self, proc_stat: str = "/proc/stat"):
        self.proc_stat = proc_stat
        self._prev: tuple[int, int] | None = None

    def _read(self) -> tuple[int, int] | None:
        try:
            with open(self.proc_stat, "r", encoding="ascii") as fh:
                line = fh.readline()
        except OSError:
            return None
        parts = line.split()
        if not parts or parts[0] != "cpu":
            return None
        try:
            values = [int(v) for v in parts[1:8]]
        except ValueError:
            return None
        # user nice system idle iowait irq softirq. idle+iowait is "not working".
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle

    def sample(self) -> float | None:
        current = self._read()
        if current is None:
            return None
        if self._prev is None:
            self._prev = current
            return None
        total_d = current[0] - self._prev[0]
        idle_d = current[1] - self._prev[1]
        self._prev = current
        if total_d <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (total_d - idle_d) / total_d))


def disk_reading(path: str | Path) -> tuple[float, float] | None:
    """(free_gb, free_percent) for the filesystem holding `path`.

    Returns None when the path does not exist yet — at first start the recordings directory
    may not have been created, and that is not a disk problem.
    """
    try:
        usage = shutil.disk_usage(str(path))
    except OSError:
        return None
    free_gb = usage.free / 1024 ** 3
    free_percent = (usage.free / usage.total * 100.0) if usage.total else 0.0
    return free_gb, free_percent
