"""v3.35 — energy interval ledger: checkpoint session energy for billing.

The Opta's cumulative ``energyKwh`` register reads 0, so the real energy source
is the backend's power x time integration accumulated on ``sessions.energy_kwh``
(see ``mqtt_handlers._integrate_session_energy``). This service durably
checkpoints that running total into ``energy_intervals`` rows:

  * every ``settings.energy_log_interval_min`` minutes for each ACTIVE
    electricity session (``run_energy_interval_logger``), and
  * once more on session completion (``flush_session_interval(final=True)``,
    called from ``session_service.complete``) so an unplug/stop is billed
    immediately without waiting for the next 15-min boundary.

Each row stores the DELTA since the previous checkpoint. ``sessions.
energy_logged_kwh`` is the high-water mark of energy already written, so a
backend restart mid-session never re-logs (and never double-bills) energy.

Empty intervals (< _MIN_LOG_KWH) are skipped — no zero rows.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from ..config import settings
from ..database import SessionLocal
from ..models.session import Session as SessionModel
from ..models.energy_interval import EnergyInterval
from ..models.pedestal_config import PedestalConfig

logger = logging.getLogger(__name__)

# Skip checkpoints below ~0.5 Wh — avoids noise rows when a socket is idle.
_MIN_LOG_KWH = 0.0005


def derive_origin(session: SessionModel) -> str:
    """Billing attribution label for an interval row."""
    if session.customer_id:
        return "customer"
    if session.nfc_user_id:
        return "nfc"
    if (session.origin or "") == "standalone":
        return "berth-marina"
    return "operator"


def _berth_ref(db, pedestal_id: int) -> str | None:
    cfg = db.query(PedestalConfig).filter(
        PedestalConfig.pedestal_id == pedestal_id
    ).first()
    return getattr(cfg, "berth_ref", None) if cfg else None


def flush_session_interval(
    db, session: SessionModel, *, now: datetime | None = None, final: bool = False
) -> EnergyInterval | None:
    """Write one interval row for energy accrued since the last checkpoint.

    Does NOT commit — the caller owns the transaction (the logger commits per
    tick; ``session_service.complete`` commits with the rest of the finalize).
    Returns the row, or None when the delta is below the log threshold (the
    high-water mark is still advanced on ``final`` so completion is exact).
    """
    if session.type != "electricity":
        return None
    now = now or datetime.utcnow()
    current = float(session.energy_kwh or 0.0)
    logged = float(session.energy_logged_kwh or 0.0)
    delta = current - logged
    if delta < _MIN_LOG_KWH:
        if final:
            session.energy_logged_kwh = current
        return None

    # Interval start = end of the previous checkpoint for this session (restart-
    # safe, read from the DB), else the session start.
    last_row = (
        db.query(EnergyInterval)
        .filter(EnergyInterval.session_id == session.id)
        .order_by(EnergyInterval.interval_end.desc())
        .first()
    )
    start = (last_row.interval_end if last_row else session.started_at) or now
    hours = max((now - start).total_seconds() / 3600.0, 0.0)
    avg_kw = (delta / hours) if hours > 0 else None

    row = EnergyInterval(
        pedestal_id=session.pedestal_id,
        socket_id=session.socket_id,
        session_id=session.id,
        origin=derive_origin(session),
        customer_id=session.customer_id,
        nfc_user_id=session.nfc_user_id,
        berth_ref=_berth_ref(db, session.pedestal_id),
        interval_start=start,
        interval_end=now,
        kwh=round(delta, 6),
        avg_power_kw=round(avg_kw, 4) if avg_kw is not None else None,
    )
    db.add(row)
    session.energy_logged_kwh = current
    return row


def _interval_tick(now: datetime) -> int:
    """Checkpoint every active electricity session. Returns rows written."""
    db = SessionLocal()
    written = 0
    try:
        active = (
            db.query(SessionModel)
            .filter(SessionModel.status == "active", SessionModel.type == "electricity")
            .all()
        )
        for s in active:
            if flush_session_interval(db, s, now=now, final=False) is not None:
                written += 1
        db.commit()
    finally:
        db.close()
    if written:
        logger.info("[EnergyInterval] wrote %d interval row(s)", written)
    return written


async def run_energy_interval_logger() -> None:
    """Lifespan task — checkpoint active sessions every energy_log_interval_min."""
    period = max(1, int(settings.energy_log_interval_min)) * 60
    while True:
        await asyncio.sleep(period)
        try:
            _interval_tick(datetime.utcnow())
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("[EnergyInterval] tick failed: %s", e)
