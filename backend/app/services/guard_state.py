"""Guard state for one pedestal, as /marina needs it — block 3, 2026-10-12.

`routers/marina.py` imported this module before it existed. The ImportError was caught, so every
pedestal read "Guard unavailable" whatever the guard was actually doing. The state was there all
along: `guard.service.effective_state` reconciles the backend's intent with the worker's
liveness — desired ARMED with a silent worker is UNAVAILABLE, never ARMED. This module only
gathers it per pedestal.

A pedestal may have several cameras. The marina shows ONE guard line per pedestal, so the
cameras are reduced to the worst state among them: a camera that is not answering must not be
hidden behind one that is.
"""
from __future__ import annotations

from sqlalchemy.orm import Session as DBSession

# Worst first. Anything not listed (an unknown future state) ranks as UNAVAILABLE.
_ORDER = ["UNAVAILABLE", "NO_DISK", "SUSPENDED_CPU", "ARMING", "ALARM", "RECORDING", "ARMED", "OFF"]


def _rank(state: str) -> int:
    return _ORDER.index(state) if state in _ORDER else 0


def current_guard_state(db: DBSession, pedestal_id: int) -> dict | None:
    """{"state": <guard state>, "limited_visibility": bool} — or None when the pedestal has no
    guard configured at all (no camera row). The caller decides how to word that."""
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
    }
