"""v3.23 — Temperature range alarm evaluation for the networked Papouch TME sensor.

Pure, side-effect-free band logic so it can be unit-tested in isolation. The
background poller (main.py `_temp_sensor_poll`) feeds live readings in and acts
on the returned (severity, kind).

Bands (°C):
    >= 60        -> critical (high)   [red]
    >= 45        -> warning  (high)   [yellow]
    <= -10       -> critical (low)    [red]
    <= 0         -> warning  (low)    [yellow]
    otherwise    -> normal (no alarm)

A 1 °C hysteresis is applied while an alarm is already active so the alarm does
not flap at a boundary (e.g. a warning raised at 45 °C only clears below 44 °C).
"""

HIGH_WARN_C = 45.0
HIGH_CRIT_C = 60.0
LOW_WARN_C = 0.0
LOW_CRIT_C = -10.0
HYSTERESIS_C = 1.0


def evaluate_temp_band(value: float, currently_active: bool) -> tuple[str | None, str | None]:
    """Return (severity, kind):
        severity in {None, "warning", "critical"}
        kind     in {"high", "low", None}

    When `currently_active` is True the thresholds are relaxed by HYSTERESIS_C so
    an existing alarm is held until the value moves comfortably back into normal.
    """
    h = HYSTERESIS_C if currently_active else 0.0
    if value >= HIGH_CRIT_C - h:
        return ("critical", "high")
    if value >= HIGH_WARN_C - h:
        return ("warning", "high")
    if value <= LOW_CRIT_C + h:
        return ("critical", "low")
    if value <= LOW_WARN_C + h:
        return ("warning", "low")
    return (None, None)


def threshold_for(severity: str, kind: str) -> float:
    """The °C threshold that defines a (severity, kind) band — for messages."""
    if kind == "high":
        return HIGH_CRIT_C if severity == "critical" else HIGH_WARN_C
    return LOW_CRIT_C if severity == "critical" else LOW_WARN_C
