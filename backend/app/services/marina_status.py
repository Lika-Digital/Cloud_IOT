"""v3.44 — the marina status reduction. ONE module, ONE table, computed server-side.

> Status and labels are computed server-side, once, and consumed by the web UI, the mobile app
> and the ERP alike. No client computes status. There is nothing to drift.

Everything the marina sees about a berth's condition reduces to three values — `ok`,
`attention`, `unknown` — plus one plain sentence. The frontend renders what it is given.

WHY THE STRING TABLE IS CLOSED
------------------------------
`SENTENCES` is the complete set of marina-facing strings for these conditions. A condition
with no entry CANNOT be rendered: `reduce()` falls through to `UNRECOGNISED`, which is
`unknown` / "Something needs checking". That is deliberately unhelpful — it is honest, and it
forces the entry to be added instead of letting a blank or a raw error code reach a screen.

The UI v2 audit found that plain-language compliance was accidental: each component worded its
own states and the compliant ones were compliant by luck. A table makes it structural.

WHY RANK 1 AND 2 ARE `unknown`, NOT `attention`
-----------------------------------------------
"Needs attention" means *go and do something about this berth*. A pedestal with no contact, or
running in non-smart mode, needs something done about the **pedestal** — and the berth's actual
state is genuinely not known. Marking those `attention` would send staff to check a berth where
nothing is wrong and fill the attention filter with rows that need nothing.

Non-smart mode especially: the Opta is doing its job and switching outlets itself. Nothing is
faulty. We simply cannot control it from here, which is a monitoring statement, not an alarm.

PRECEDENCE
----------
Highest rank wins, so the sentence shown is always the most serious thing true about the berth.
`status_rank` travels in the payload for sorting and is never displayed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

# Three states. Nothing else is a status.
OK = "ok"
ATTENTION = "attention"
UNKNOWN = "unknown"

# How stale a cabinet heartbeat may be before the berth is UNKNOWN. Identical to
# nfc.COMM_LOSS_TIMEOUT_S and main.COMM_LOSS_TIMEOUT_SECONDS on purpose — two different
# opinions about when a cabinet is dead is how the dashboard and the NFC path come to
# disagree in front of a customer.
COMM_LOSS_TIMEOUT_S = 60

# How stale a stored valve state may be. Same window, same reasoning: a stored state is only
# as good as its age (docs/engineering_notes.md rule 1).
OUTLET_STALE_S = 60


@dataclass(frozen=True)
class Sentence:
    code: str
    rank: float
    status: str
    text: str


# ── The table. Approved 2026-10-01. ──────────────────────────────────────────────────────
#
# Ranks 2.5 and 7.5 are not padding: both were forced by the foundation work and are
# fractional so the nine approved ranks keep the numbers they were approved with.
SENTENCES: dict[str, Sentence] = {s.code: s for s in (
    Sentence("no_contact", 1, UNKNOWN,
             "No contact with this pedestal"),
    Sentence("standalone", 2, UNKNOWN,
             "This pedestal is running on its own, monitoring only"),
    # Forced by the valve-state work: the cabinet can be reachable while one outlet is stale.
    # Without this the row would show `idle` for a valve nobody has heard from — the precise
    # defect the 60 s expiry fixed one layer down.
    Sentence("outlet_silent", 2.5, UNKNOWN,
             "This outlet has not reported recently"),
    Sentence("water_leak", 3, ATTENTION,
             "Water leak detected"),
    Sentence("too_hot", 4, ATTENTION,
             "Pedestal too hot"),
    Sentence("auto_off_overload", 5, ATTENTION,
             "Power switched off automatically — too much load"),
    Sentence("breaker_tripped", 6, ATTENTION,
             "Power tripped — needs resetting"),
    Sentence("guard_unreviewed", 7, ATTENTION,
             "Someone was seen — needs checking"),
    # Forced by the register work. Its first justification was invoicing, which is closed —
    # we do not invoice. It stands on its own and is MORE necessary without an invoice step:
    # we report the figure and the ERP bills it, so an `unknown` leaves the ERP nothing to
    # charge and nobody here aware. This sentence is the only thing that tells a human.
    Sentence("measurement_missing", 7.5, ATTENTION,
             "Consumption could not be measured — needs review"),
    Sentence("vessel_mismatch", 8, ATTENTION,
             "Vessel does not match the photo"),
    Sentence("ok", 9, OK, ""),
)}

# The fall-through. Not in SENTENCES, because it is not a condition anyone detects — it is
# what happens when a condition HAS been detected and nobody wrote its sentence.
UNRECOGNISED = Sentence("unrecognised", 0.5, UNKNOWN, "Something needs checking")


@dataclass
class BerthFacts:
    """Everything the reduction needs, gathered once by the caller.

    A plain value object on purpose: `reduce()` does no I/O, so it is trivially testable and
    cannot accidentally become slow inside a loop over every berth on every cabinet.
    """
    heartbeat_age_s: float | None = None     # None = never heard from
    smart_mode: bool = True
    outlet_state_unknown: bool = False       # a stale/never-reported outlet serving this berth
    moisture_alarm: bool = False
    temperature_alarm: bool = False
    auto_stop_pending_ack: bool = False
    breaker_tripped: bool = False
    guard_alarm_unreviewed: bool = False
    consumption_unmeasured: bool = False
    vessel_mismatch: bool = False
    vessel_match_configured: bool = False
    # Any condition the caller detected but could not name. Drives UNRECOGNISED.
    unnamed_condition: str | None = None


def reduce(facts: BerthFacts) -> Sentence:
    """The single reduction. Highest-ranked true condition wins.

    Ordered explicitly rather than by sorting a predicate list: the order IS the specification,
    and an explicit cascade is what a reader checks against the approved table. A sort over
    `(rank, predicate)` pairs reads as cleverer and hides the precedence it implements.
    """
    # 1 — never heard from, or silent past the threshold. Checked FIRST because every other
    # fact below was read from a database that may be describing a cabinet that is long gone.
    if facts.heartbeat_age_s is None or facts.heartbeat_age_s > COMM_LOSS_TIMEOUT_S:
        return SENTENCES["no_contact"]

    # 2 — the NUC cannot act. Not a fault: the Opta is switching outlets itself.
    if not facts.smart_mode:
        return SENTENCES["standalone"]

    # 2.5 — reachable cabinet, stale outlet.
    if facts.outlet_state_unknown:
        return SENTENCES["outlet_silent"]

    if facts.moisture_alarm:
        return SENTENCES["water_leak"]
    if facts.temperature_alarm:
        return SENTENCES["too_hot"]
    if facts.auto_stop_pending_ack:
        return SENTENCES["auto_off_overload"]
    if facts.breaker_tripped:
        return SENTENCES["breaker_tripped"]
    if facts.guard_alarm_unreviewed:
        return SENTENCES["guard_unreviewed"]
    if facts.consumption_unmeasured:
        return SENTENCES["measurement_missing"]

    # 8 — only where someone configured a reference photo. An unconfigured berth is not
    # "matching" and is not "mismatched"; it is simply not a question we asked.
    if facts.vessel_match_configured and facts.vessel_mismatch:
        return SENTENCES["vessel_mismatch"]

    # A condition was detected that has no sentence. Never silently OK.
    if facts.unnamed_condition:
        return UNRECOGNISED

    return SENTENCES["ok"]


def heartbeat_age(last_seen: datetime | None, *, now: datetime | None = None) -> float | None:
    """Seconds since a cabinet was last heard from, or None if never.

    The caller must pass the IN-MEMORY heartbeat, never a stored column. An MQTT broker
    replays the last retained `opta/status` to every new subscriber, so after a restart a
    cabinet dead for three weeks looks healthy and `PedestalConfig.opta_connected` reads 1.
    `TC-NFCE-06` pins this for the NFC path; the dashboard must not reintroduce it.
    """
    if last_seen is None:
        return None
    now = now or datetime.utcnow()
    return max(0.0, (now - last_seen).total_seconds())


def outlet_state_is_stale(updated_at: datetime | None, *, now: datetime | None = None) -> bool:
    """True when a stored outlet state is missing or too old to report as current."""
    if updated_at is None:
        return True
    now = now or datetime.utcnow()
    return (now - updated_at) > timedelta(seconds=OUTLET_STALE_S)


def as_payload(sentence: Sentence) -> dict:
    """The three status fields every CORE berth carries.

    `status_code` ships alongside the sentence so tests and logs have a stable key while
    humans get the words. Asserting on display text makes every wording change a test
    failure, which is how wording stops being improved.
    """
    return {
        "status": sentence.status,
        "status_code": sentence.code,
        "status_sentence": sentence.text or None,
        "status_rank": sentence.rank,
    }
