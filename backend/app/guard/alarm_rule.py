"""
Guard alarm rule — anti-flicker in time, promoted from scripts/guard_detect_probe.py.

Build order step 2. This module is the **alarm decision**, deliberately separate from
detection so it can be replaced without touching the detector (a Phase 2 requirement:
"the alarm decision is a separate replaceable step from detection"). It consumes
`(timestamp, detected)` pairs and knows nothing about models, frames or cameras.

Settled parameters, from the NUC measurements:

    GUARD_FPS=1, GUARD_WINDOW_SECONDS=4, GUARD_FRAMES_REQUIRED=2

1 fps because a single inference costs 273.3 ms of CPU single-threaded, which is 6.8 % of
4 cores at 1 fps and 13.7 % at 2 fps. A 4 s window rather than 3 s because 1 fps yields
only 4 samples in 3 s: widening to 5 samples lifts P(alarm) at per-frame recall 0.6 from
0.821 to 0.913, while max latency stays 4.0 s — inside the 5 s acceptance threshold. The
false-alarm cost is negligible: with 0/1200 observed, the pessimistic 95 % upper bound on
per-frame FP is 0.0025 (rule of three), giving ~0.056 false alarms/hour, about one every
18 hours. The measurement itself was 0.00/hour.

**Why the rule matters more than per-frame accuracy:** frame recall can look excellent and
still produce a false alarm every ten minutes. A guard that cries wolf gets switched off,
and then protects nothing.

Pure stdlib. No numpy, no PIL, no FastAPI, no SQLAlchemy — so the probe can import it from
the staging venv, and the worker and the probe share one definition of "alarm" rather than
two that drift. `test_guard_import_isolation.py` enforces that.
"""
from __future__ import annotations

DEFAULT_FRAMES_REQUIRED = 2
DEFAULT_WINDOW_SECONDS = 4.0
DEFAULT_COOLDOWN_SECONDS = 60.0


def evaluate_alarm_rule(
    samples: list[tuple[float, bool]],
    *,
    frames_required: int = DEFAULT_FRAMES_REQUIRED,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
) -> list[dict]:
    """Replay detections through the alarm rule (batch form, used by the probe).

    Args:
        samples: (timestamp_seconds, person_detected) in chronological order.
        frames_required: positives needed inside the window to alarm.
        window_seconds: rolling window length. Rolling, not bucketed — two detections
            0.4 s apart that straddle a bucket boundary must still alarm.
        cooldown_seconds: after an alarm, suppress further alarms this long. A person
            loitering for 20 s is ONE event, not forty.

    Returns:
        One dict per alarm: {t, first_positive_t, latency_s, positives_in_window}.
    """
    state = AlarmState(
        frames_required=frames_required,
        window_seconds=window_seconds,
        cooldown_seconds=cooldown_seconds,
    )
    alarms: list[dict] = []
    for t, detected in samples:
        fired = state.observe(t, detected)
        if fired is not None:
            alarms.append(fired)
    return alarms


class AlarmState:
    """Incremental form of the same rule, for the live worker.

    The worker cannot accumulate every sample forever, so it feeds frames in one at a
    time. `evaluate_alarm_rule` above is implemented on top of this class so the batch
    replay used for measurement and the live decision are provably the same code — which
    is the "probe and worker share ONE code path" requirement, applied to the decision as
    well as to detection.
    """

    def __init__(
        self,
        *,
        frames_required: int = DEFAULT_FRAMES_REQUIRED,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    ):
        if frames_required < 1:
            raise ValueError("frames_required must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.frames_required = frames_required
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds

        self._window: list[float] = []
        self._cooldown_until: float | None = None
        self._first_positive_t: float | None = None

    @property
    def in_cooldown(self) -> bool:
        return self._cooldown_until is not None

    def cooldown_remaining(self, now: float) -> float:
        if self._cooldown_until is None:
            return 0.0
        return max(0.0, self._cooldown_until - now)

    def reset(self) -> None:
        """Clear all state. Used on disarm, so an old window cannot contribute to a new
        arming session."""
        self._window.clear()
        self._cooldown_until = None
        self._first_positive_t = None

    def observe(self, t: float, detected: bool) -> dict | None:
        """Feed one processed frame. Returns the alarm dict if this frame fired one.

        Negative frames are not merely ignored: they still let the cooldown expire, which
        is why the cooldown check happens before the early return.
        """
        if self._cooldown_until is not None and t >= self._cooldown_until:
            self._cooldown_until = None

        if not detected:
            return None

        if self._first_positive_t is None:
            self._first_positive_t = t

        self._window.append(t)
        # Rolling window: keep only samples within `window_seconds` of now. The bound is
        # inclusive so two detections exactly `window_seconds` apart still count.
        self._window = [w for w in self._window if t - w <= self.window_seconds]

        if self._cooldown_until is not None:
            # Motion is still observed and still logged by the caller, but no new alarm.
            return None

        if len(self._window) < self.frames_required:
            return None

        fired = {
            "t": t,
            "first_positive_t": self._first_positive_t,
            "latency_s": t - self._first_positive_t,
            "positives_in_window": len(self._window),
        }
        self._cooldown_until = t + self.cooldown_seconds
        self._window = []
        self._first_positive_t = None
        return fired
