"""
ERP reconciliation tracking — divergence, and silence that means something (v3.43).

In MODE 1 the ERP bills and our session rows are reconciliation data. Nothing compared the two,
so our records could drift from ERP's **silently**: each side kept its own totals and neither
asserted they agreed. `GET /api/nfc/sessions/by-user/{id}` existed so ERP *could* reconcile, but
nothing required it to and nothing noticed if it stopped.

Three things close that, and the third is the one that matters:

1. **`sessions.last_reconciled_at`** — stamped when the ERP reads a session as a machine caller.
   Turns "ERP has never looked at this" from an assumption into a fact.
2. **A divergence view** — sessions with an `nfc_user_id` that ERP has never acknowledged, oldest
   first. Divergence you can see is a problem.
3. **A silence alarm** — because silence is a problem you *cannot* see.

THE PART THAT DECIDES WHETHER THE ALARM IS USEFUL OR MUTED
---------------------------------------------------------
"ERP has not reconciled in seven days" has two completely different causes:

  * **ERP stopped reconciling** while sessions were piling up. The integration is down and the
    marina is billing nothing. Someone must act today.
  * **Nothing happened worth reconciling** — a marina that is simply quiet in winter. Correct,
    expected, and not a fault.

A single alarm for both gets muted within a month, and then the first one goes unnoticed too. So
this module reports three states per pedestal and only one of them alarms:

  RECONCILING       ERP read something inside the window. Healthy.
  SILENT_WITH_BACKLOG   Unreconciled sessions exist AND no read in the window. **ALARMS.**
  IDLE              Nothing awaiting reconciliation. Quiet, not broken. Never alarms.

MODE 2 has no ERP, so none of this applies and the watchdog does not run — an alarm about ERP
silence at a marina with no ERP would be the same kind of noise.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session as DBSession

from ..config import settings
from ..models.session import Session
from ..time_utils import iso_z

logger = logging.getLogger(__name__)

STATE_RECONCILING = "reconciling"
STATE_SILENT_WITH_BACKLOG = "silent_with_backlog"
STATE_IDLE = "idle"

ALARM_TYPE = "erp_reconciliation_silent"


@dataclass
class PedestalReconciliation:
    pedestal_id: int
    state: str
    last_reconciled_at: datetime | None
    unreconciled_count: int
    oldest_unreconciled_at: datetime | None
    unreconciled_energy_kwh: float = 0.0

    @property
    def days_silent(self) -> float | None:
        if self.last_reconciled_at is None:
            return None
        return (datetime.utcnow() - self.last_reconciled_at).total_seconds() / 86400.0

    def as_dict(self) -> dict:
        return {
            "pedestal_id": self.pedestal_id,
            "state": self.state,
            "last_reconciled_at": iso_z(self.last_reconciled_at)
            if self.last_reconciled_at else None,
            "days_since_last_reconciled": (
                round(self.days_silent, 1) if self.days_silent is not None else None
            ),
            "unreconciled_count": self.unreconciled_count,
            "oldest_unreconciled_at": iso_z(self.oldest_unreconciled_at)
            if self.oldest_unreconciled_at else None,
            "unreconciled_energy_kwh": round(self.unreconciled_energy_kwh, 3),
            "explanation": _explain(self),
        }


def _explain(r: PedestalReconciliation) -> str:
    """One sentence saying what this state MEANS, not what it is.

    The alarm and the view share these, so an operator reading either gets the same account.
    """
    if r.state == STATE_IDLE:
        return ("Nothing is waiting to be reconciled. This pedestal is quiet, which is not a "
                "fault.")
    if r.state == STATE_RECONCILING:
        return (f"ERP last reconciled this pedestal "
                f"{'never' if r.last_reconciled_at is None else iso_z(r.last_reconciled_at)}"
                f" and there are {r.unreconciled_count} session(s) still to acknowledge.")
    seen = ("has never reconciled this pedestal"
            if r.last_reconciled_at is None
            else f"has not reconciled this pedestal since {iso_z(r.last_reconciled_at)}")
    return (
        f"ERP {seen}, while {r.unreconciled_count} finished session(s) "
        f"({r.unreconciled_energy_kwh:.2f} kWh) are waiting to be billed — the oldest since "
        f"{iso_z(r.oldest_unreconciled_at) if r.oldest_unreconciled_at else 'unknown'}. "
        f"Either the ERP integration has stopped, or this marina's charges are not reaching it."
    )


def mark_reconciled(db: DBSession, sessions: list[Session]) -> None:
    """Stamp `last_reconciled_at` on sessions the ERP has just read.

    Called only from the machine-caller path. A customer reading their own session must not
    stamp it: that is someone checking their charge, not the billing system reconciling, and
    conflating them would silence the detector whenever a customer opened the app.
    """
    if not sessions:
        return
    now = datetime.utcnow()
    for s in sessions:
        s.last_reconciled_at = now
    db.commit()


def _window_start() -> datetime:
    return datetime.utcnow() - timedelta(days=settings.erp_reconciliation_silence_days)


def status_by_pedestal(db: DBSession) -> list[PedestalReconciliation]:
    """Reconciliation state per pedestal that has ERP-attributed sessions.

    Only sessions carrying an `nfc_user_id` count: those are the ones ERP is responsible for
    billing. Operator-started and standalone sessions are ours alone and are not ERP's to
    acknowledge, so including them would invent a backlog that nobody owes.
    """
    cutoff = _window_start()
    rows = (
        db.query(Session)
        .filter(Session.nfc_user_id.isnot(None))
        .all()
    )

    by_pedestal: dict[int, list[Session]] = {}
    for s in rows:
        by_pedestal.setdefault(s.pedestal_id, []).append(s)

    out: list[PedestalReconciliation] = []
    for pid, sessions in sorted(by_pedestal.items()):
        reconciled_times = [s.last_reconciled_at for s in sessions
                            if s.last_reconciled_at is not None]
        last_seen = max(reconciled_times) if reconciled_times else None

        # A session counts as a backlog item only once it has ENDED. An in-progress session has
        # nothing final to reconcile, so counting it would raise an alarm for a customer who is
        # simply still plugged in.
        pending = [s for s in sessions
                   if s.last_reconciled_at is None and s.status != "active"]

        if not pending:
            state = STATE_IDLE
        elif last_seen is not None and last_seen >= cutoff:
            state = STATE_RECONCILING
        else:
            state = STATE_SILENT_WITH_BACKLOG

        out.append(PedestalReconciliation(
            pedestal_id=pid,
            state=state,
            last_reconciled_at=last_seen,
            unreconciled_count=len(pending),
            oldest_unreconciled_at=min((s.started_at for s in pending), default=None),
            unreconciled_energy_kwh=sum(s.energy_kwh or 0.0 for s in pending),
        ))
    return out


def divergent_sessions(db: DBSession, limit: int = 200) -> list[dict]:
    """Finished ERP sessions never acknowledged, oldest first.

    Oldest first on purpose: the oldest unreconciled charge is the one most likely to be
    disputed or written off, and a newest-first list buries it.
    """
    rows = (
        db.query(Session)
        .filter(
            Session.nfc_user_id.isnot(None),
            Session.last_reconciled_at.is_(None),
            Session.status != "active",
        )
        .order_by(Session.started_at.asc())
        .limit(limit)
        .all()
    )
    return [
        {
            "session_id": s.id,
            "pedestal_id": s.pedestal_id,
            "socket_id": s.socket_id,
            "nfc_user_id": s.nfc_user_id,
            "started_at": iso_z(s.started_at),
            "ended_at": iso_z(s.ended_at) if s.ended_at else None,
            "status": s.status,
            "energy_kwh": s.energy_kwh,
        }
        for s in rows
    ]


async def check_reconciliation_silence() -> None:
    """Raise an alarm per pedestal that is SILENT_WITH_BACKLOG. Never raises.

    Only that state alarms. IDLE does not, because a quiet marina is not a fault and an alarm
    that fires on quiet gets muted — after which the real one goes unnoticed too.
    """
    if settings.nfc_direct_client_mode:
        # MODE 2: there is no ERP to reconcile with. An alarm about ERP silence here would be
        # noise about a system that does not exist.
        return

    from ..database import SessionLocal
    from .alarm_service import trigger_alarm

    db = SessionLocal()
    try:
        states = status_by_pedestal(db)
    except Exception:
        logger.exception("[ERP] reconciliation check failed")
        return
    finally:
        db.close()

    for r in states:
        if r.state != STATE_SILENT_WITH_BACKLOG:
            continue
        try:
            trigger_alarm(
                alarm_type=ALARM_TYPE,
                source="sensor_auto",
                message=_explain(r),
                pedestal_id=r.pedestal_id,
                severity="warning",
                deduplicate=True,
            )
            logger.warning("[ERP] reconciliation silent for pedestal=%d: %s",
                           r.pedestal_id, _explain(r))
        except Exception:
            logger.exception("[ERP] could not raise the reconciliation-silence alarm")
