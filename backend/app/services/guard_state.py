"""Guard state for one pedestal, and the ONE function that words it — spec §5.5.1.

`routers/marina.py` imported this module before it existed (block 3, 2026-10-12). The ImportError
was caught, so every pedestal read "Guard unavailable" whatever the guard was actually doing. The
state was there all along: `guard.service.effective_state` reconciles the backend's intent with
the worker's liveness. This module gathers it per pedestal.

2026-10-16 (owner): four sentences for four states and a fifth for a pause, never one
"unavailable" for all of them. `sentence_for` is the only place a guard state becomes words —
`/api/guard/status` and `/marina` both use it, so the API and the screen cannot disagree
(TC-GU-15).

A pedestal may have several cameras. The marina shows ONE guard line per pedestal, so the
cameras are reduced to the worst state among them: a camera that is not answering must not be
hidden behind one that is.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

NO_GUARD = "No guard on this pedestal"
NOT_ANSWERING = "Guard not answering"
GUARD_ON = "Guard on"
GUARD_OFF = "Guard off"
PAUSED_CPU = "Guard paused — processor overloaded"
PAUSED_DARK = "Guard paused — too dark to see"
PAUSED_UNKNOWN = "Guard paused — reason not reported"
NOT_MEASURED = "Not measured"

_ON = ("ARMING", "ARMED", "ALARM", "RECORDING")

# Worst first. A state not listed is a pause the backend has no reason for — ranked just below
# "not answering", never as "on".
_ORDER = ["UNAVAILABLE", "<unknown>", "SUSPENDED_CPU", "ARMING", "ALARM", "RECORDING", "ARMED",
          "OFF"]


def sentence_for(state: str | None, flags: list | None = None) -> tuple[str, str]:
    """(code, sentence) for one reconciled guard state. Codes: not_answering, on, off, paused."""
    if state == "UNAVAILABLE" or state is None:
        return "not_answering", NOT_ANSWERING
    if state in _ON:
        if "limited_visibility" in (flags or []):
            return "paused", PAUSED_DARK
        return "on", GUARD_ON
    if state == "OFF":
        return "off", GUARD_OFF
    if state == "SUSPENDED_CPU":
        return "paused", PAUSED_CPU
    # NO_DISK (the worker never sends it — `no_disk` is a flag) or any state a later worker adds.
    return "paused", PAUSED_UNKNOWN


def _rank(state: str) -> int:
    return _ORDER.index(state) if state in _ORDER else 1


def current_guard_state(db: DBSession, pedestal_id: int) -> dict | None:
    """The worst camera's reconciled state, its flags and its sentence — or None when the
    pedestal has no guard row (spec §5.5.1 S1: the worker never announced itself)."""
    from ..guard.models import GuardConfig
    from ..guard import service

    cfgs = db.query(GuardConfig).filter(GuardConfig.pedestal_id == pedestal_id).all()
    if not cfgs:
        return None
    states = [service.effective_state(db, c) for c in cfgs]
    worst = min(states, key=lambda s: _rank(s.get("state") or "UNAVAILABLE"))
    return {
        "state": worst.get("state") or "UNAVAILABLE",
        "limited_visibility": "limited_visibility" in (worst.get("flags") or []),
        "sentence_code": worst["sentence_code"],
        "sentence": worst["sentence"],
        "auto_resumes": worst.get("auto_resumes"),
    }
