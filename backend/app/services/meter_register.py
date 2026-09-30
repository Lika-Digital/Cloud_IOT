"""
Meter register deltas — forward what the meter says, never derive it (v3.43).

WHAT WE SEND ERP is exactly two things: consumption per session, tied to the customer who
scanned, and cumulative consumption per outlet. Both must come from the register the meter
already maintains. Nothing is integrated, nothing is derived.

WHY THIS MODULE EXISTS
----------------------
Until v3.43 the per-session electricity figure was `avg(powerKw) x dt`, accumulated every meter
tick. That was the right fix when it was written (`faec850`, 19 June 2026): the firmware reported
`energyKwh` as 0 on every message, so integration was the only figure available. Firmware 3.1.0
reports the register live, so the workaround has outlived its reason — and a fix that stops being
necessary does not fail, so nothing prompted a revisit.

It matters because `powerKw` is not trustworthy. A capture from MAR_KRK_ORM_01 (firmware 3.1.0)
shows Q2 reporting 0.181 kW continuously for six minutes while its `energyKwh` register did not
move at all. **The meter does not believe its own `powerKw` field.** How large the discrepancy is
at real load is unknown and pending a loaded capture; the mechanism is enough to stop deriving
from it.

THE RULES, DECIDED ONCE AND APPLIED TO BOTH energyKwh AND total_l
-----------------------------------------------------------------
Both are monotonic cumulative registers, so a session's consumption is `end - start`.

  * **Store BOTH endpoints, not only the difference.** If ERP ever queries a figure we must be
    able to show what the meter read at each end, rather than a number we cannot reconstruct.
  * **A negative or absurd delta RAISES.** Never forwarded, never silently dropped. Meter
    replacement, firmware reset and counter rollover all produce one, and each needs a human to
    look rather than a guess.
  * **A missing or stale register at either end makes the figure UNKNOWN, not zero.** Zero reads
    as "they used nothing" and ERP would bill accordingly.
  * The integrated figure is kept ALONGSIDE, permanently, for comparison. A divergence between
    the register delta and the integral is a meter or firmware fault worth surfacing whenever it
    appears — not only during this investigation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

# Absurdity ceilings. Deliberately the same constants the completion path already used for
# reading-based sanity, so one idea of "impossible" governs every path.
from ..database import (  # noqa: E402
    _MAX_SANE_KWH_PER_SESSION,
    _MAX_SANE_LITERS_PER_SESSION,
)

# Divergence between the register delta and the comparison figure that is worth a human looking.
# Relative AND absolute must both be exceeded: a 50 % disagreement on 0.02 kWh is rounding, and
# alarming on it is how an alarm gets muted.
DIVERGENCE_RATIO = 0.25
DIVERGENCE_MIN_KWH = 0.25
DIVERGENCE_MIN_LITERS = 5.0

KIND_ENERGY = "energy"
KIND_WATER = "water"

# ── consumption_source: how a session's reported figure was derived ──────────
#
# Permanent, and part of the ERP contract. A figure that does not say how it was derived is how
# the June 2026 workaround survived three months unnoticed: the number looked identical whether
# it came from a meter register or from integrating an untrustworthy power field. If we ever
# have to fall back again, the fallback is visible in the data rather than in a commit message.
SOURCE_REGISTER = "register"                 # end - start of the meter's own register
SOURCE_INTEGRATED_LEGACY = "integrated_legacy"   # closed-ended, see the guard below
SOURCE_UNKNOWN = "unknown"                   # not derivable; never 0.0

# THE CLOSED-ENDED GUARD.
#
# `integrated_legacy` exists for exactly one population: sessions that were already ACTIVE when
# the register change deployed. They have no start register, because nothing captured one when
# they began, so their register delta is genuinely unknowable — but the old integral exists, and
# reporting it (labelled) beats an unbillable session.
#
# That population drains to zero as those sessions complete, and no new session may ever join
# it. This timestamp is the boundary: a session that STARTED after the deploy cannot be stamped
# integrated_legacy, and `assert_legacy_allowed` raises if anything tries.
#
# Why an assertion rather than only a test: a test says the rule was true when someone last ran
# it; an assertion says it cannot become false. A label meant for a handful of sessions is
# exactly the kind of thing that becomes permanent because it is convenient, and the next person
# who finds the register inconvenient will reach for the nearest label that already exists.
LEGACY_INTEGRAL_CUTOFF = datetime(2026, 9, 30, 0, 0, 0)


class LegacySourceNotPermitted(RuntimeError):
    """Raised when something tries to stamp integrated_legacy on a post-cutoff session."""


def assert_legacy_allowed(session) -> None:
    """Refuse `integrated_legacy` for any session that began after the cutoff.

    Called at the single write site. The escape hatch closes itself.
    """
    started = getattr(session, "started_at", None)
    if started is not None and started >= LEGACY_INTEGRAL_CUTOFF:
        raise LegacySourceNotPermitted(
            f"Session {getattr(session, 'id', '?')} started {started.isoformat()}, after the "
            f"{LEGACY_INTEGRAL_CUTOFF.date()} cutoff, so it cannot be reported as "
            f"'{SOURCE_INTEGRATED_LEGACY}'. That label applies ONLY to sessions that were "
            f"already running when the meter-register change deployed and therefore have no "
            f"start reading. A post-cutoff session with no usable register is UNKNOWN — fix the "
            f"register path rather than relabelling the figure as an estimate."
        )

_CEILINGS = {KIND_ENERGY: _MAX_SANE_KWH_PER_SESSION, KIND_WATER: _MAX_SANE_LITERS_PER_SESSION}
_UNITS = {KIND_ENERGY: "kWh", KIND_WATER: "L"}


@dataclass
class DeltaResult:
    """The outcome of asking "how much did this session consume?".

    `value is None` means UNKNOWN — deliberately distinct from 0.0, which would mean "they used
    nothing". Callers must not coalesce the two.
    """
    value: float | None
    status: str                 # "ok" | "unknown" | "rejected"
    reason: str | None = None

    @property
    def is_reportable(self) -> bool:
        return self.status == "ok" and self.value is not None


def session_delta(kind: str, start: float | None, end: float | None) -> DeltaResult:
    """`end - start` from a cumulative meter register, or an honest refusal.

    Pure and side-effect free so the rules can be tested directly, which matters because they
    govern what a customer is billed.
    """
    unit = _UNITS[kind]

    if start is None or end is None:
        missing = "start" if start is None else "end"
        return DeltaResult(
            None, "unknown",
            f"the meter register was not readable at session {missing}, so consumption is "
            f"UNKNOWN — reporting zero would claim nothing was used",
        )

    delta = float(end) - float(start)

    if delta < 0:
        return DeltaResult(
            None, "rejected",
            f"register went BACKWARDS ({start} -> {end} {unit}). A meter replacement, a "
            f"firmware reset or a counter rollover all look like this, and each needs a person "
            f"to decide — so nothing is reported for this session",
        )

    ceiling = _CEILINGS[kind]
    if delta >= ceiling:
        return DeltaResult(
            None, "rejected",
            f"delta of {delta:.3f} {unit} ({start} -> {end}) is at or past the sanity ceiling "
            f"of {ceiling} {unit}; a figure this size is a fault, not a session",
        )

    return DeltaResult(round(delta, 4), "ok")


def divergence(kind: str, register_delta: float | None,
               comparison: float | None) -> tuple[bool, str | None]:
    """Does the register delta disagree with the independently-derived figure?

    Permanent, not a temporary investigation aid. For electricity the comparison is the
    power x time integral; for water it is the firmware's own per-session counter. Either way a
    persistent disagreement means one of the two sources is wrong, and that is a meter or
    firmware fault someone should see — the kind of thing the old sanity clamp corrected in
    silence, which is how it survived unnoticed at 53x.
    """
    if register_delta is None or comparison is None:
        return False, None
    floor = DIVERGENCE_MIN_KWH if kind == KIND_ENERGY else DIVERGENCE_MIN_LITERS
    diff = abs(register_delta - comparison)
    if diff < floor:
        return False, None
    larger = max(abs(register_delta), abs(comparison))
    if larger <= 0 or (diff / larger) < DIVERGENCE_RATIO:
        return False, None
    unit = _UNITS[kind]
    return True, (
        f"the meter register says {register_delta:.3f} {unit} for this session while the "
        f"independent figure says {comparison:.3f} {unit} — a {diff:.3f} {unit} disagreement. "
        f"One of the two is wrong; the register is what we report, so this is a meter or "
        f"firmware fault to investigate rather than a billing correction."
    )


def raise_meter_alarm(alarm_type: str, message: str, pedestal_id: int | None,
                      severity: str = "warning") -> None:
    """Surface a meter fault. Never lets alarm trouble break the calling flow."""
    try:
        from .alarm_service import trigger_alarm
        trigger_alarm(
            alarm_type=alarm_type, source="sensor_auto", message=message,
            pedestal_id=pedestal_id, severity=severity, deduplicate=True,
        )
    except Exception:
        logger.exception("[Meter] could not raise %s alarm", alarm_type)
    logger.warning("[Meter] %s: %s", alarm_type, message)
