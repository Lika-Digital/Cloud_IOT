"""Per-pedestal usage history + monthly plain-text reports (v3.31).

Usage history is derived from COMPLETED ``sessions`` rows — the source of truth,
which the retention sweeper keeps forever (see ``retention_service``). Each
completed session contributes one usage record:

    timestamp · socket/valve · kWh · liters · customer / NFC user (when known)

When Smart Mode is OFF the Opta runs standalone and the NUC never attaches a
customer, so those fields are simply left blank — we report whatever the session
row actually holds.

Monthly reports are plain-text files, ONE per pedestal per month
(``pedestal-{id}_{YYYY}-{MM}.txt``), written under ``settings.reports_dir`` —
persistent storage that survives a ``cloud-iot upgrade``. Files are created by
the monthly scheduler (previous month at rollover) or lazily on first download.
They are deleted ONLY by an admin via the API; the retention sweeper never
touches this directory (it only prunes DB telemetry tables).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from ..config import settings
from ..database import SessionLocal
from ..time_utils import iso_z
from ..models.session import Session as SessionModel
from ..models.pedestal import Pedestal
from ..models.pedestal_config import PedestalConfig

logger = logging.getLogger(__name__)

_FILE_RE = re.compile(r"^pedestal-(\d+)_(\d{4})-(\d{2})\.txt$")


# ── Paths ─────────────────────────────────────────────────────────────────────

def reports_dir() -> Path:
    """Return the (created) reports directory from settings."""
    d = Path(settings.reports_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def report_filename(pedestal_id: int, year: int, month: int) -> str:
    return f"pedestal-{pedestal_id}_{year:04d}-{month:02d}.txt"


def report_path(pedestal_id: int, year: int, month: int) -> Path:
    return reports_dir() / report_filename(pedestal_id, year, month)


# ── Time helpers ───────────────────────────────────────────────────────────────

def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """[start, end) UTC datetimes for the given calendar month."""
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def _prev_month(now: datetime) -> tuple[int, int]:
    return (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)


# ── Data access ────────────────────────────────────────────────────────────────

def _resolve_customer_names(customer_ids: set[int]) -> dict[int, str]:
    """Map customer_id → display name from the users.db Customer table.

    Best-effort: a missing customer or a DB hiccup yields no entry (the caller
    falls back to a blank). Never raises into the caller.
    """
    ids = {c for c in customer_ids if c is not None}
    if not ids:
        return {}
    try:
        from ..auth.user_database import UserSessionLocal
        from ..auth.customer_models import Customer
    except Exception:  # pragma: no cover - defensive import guard
        return {}
    db = UserSessionLocal()
    try:
        out: dict[int, str] = {}
        for row in db.query(Customer).filter(Customer.id.in_(ids)).all():
            out[row.id] = row.name or row.email or f"#{row.id}"
        return out
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("usage report: customer name resolution failed: %s", e)
        return {}
    finally:
        db.close()


def usage_rows(
    db,
    pedestal_id: int,
    *,
    socket_id: int | None = None,
    resource: str | None = None,
    year: int | None = None,
    month: int | None = None,
) -> list[dict]:
    """Completed-session usage records for a pedestal, newest first.

    Optional filters: a single socket/valve (``socket_id`` + ``resource``), and
    a calendar month. ``resource`` is "electricity" or "water".
    """
    q = db.query(SessionModel).filter(
        SessionModel.pedestal_id == pedestal_id,
        SessionModel.status == "completed",
    )
    if resource:
        q = q.filter(SessionModel.type == resource)
    if socket_id is not None:
        q = q.filter(SessionModel.socket_id == socket_id)
    if year is not None and month is not None:
        start, end = month_bounds(year, month)
        q = q.filter(SessionModel.started_at >= start, SessionModel.started_at < end)
    sessions = q.order_by(SessionModel.started_at.desc()).all()

    names = _resolve_customer_names({s.customer_id for s in sessions})
    rows: list[dict] = []
    for s in sessions:
        rows.append({
            "session_id": s.id,
            "socket_id": s.socket_id,
            "type": s.type,
            "started_at": iso_z(s.started_at),
            "ended_at": iso_z(s.ended_at),
            "energy_kwh": s.energy_kwh,
            "water_liters": s.water_liters,
            "customer_id": s.customer_id,
            "customer_name": names.get(s.customer_id),
            "nfc_user_id": s.nfc_user_id,
            "end_reason": s.end_reason,
        })
    return rows


# ── Report rendering ───────────────────────────────────────────────────────────

def _fmt_dt(iso: str | None) -> str:
    if not iso:
        return "?"
    return iso.replace("T", " ")[:16]


def _socket_label(resource: str, socket_id: int | None) -> str:
    if resource == "water":
        return f"Valve V{socket_id}" if socket_id is not None else "Valve V?"
    return f"Socket Q{socket_id}" if socket_id is not None else "Socket ?"


def build_report_text(db, pedestal_id: int, year: int, month: int) -> str:
    """Render the plain-text monthly report for one pedestal."""
    ped = db.get(Pedestal, pedestal_id)
    cfg = db.query(PedestalConfig).filter(
        PedestalConfig.pedestal_id == pedestal_id
    ).first()
    cabinet = (cfg.opta_client_id if cfg else None) or "?"
    ped_name = (getattr(ped, "name", None) if ped else None) or f"Pedestal {pedestal_id}"

    rows = usage_rows(db, pedestal_id, year=year, month=month)
    # Group by (type, socket_id); sort chronologically within a group.
    groups: dict[tuple[str, int | None], list[dict]] = {}
    for r in rows:
        groups.setdefault((r["type"], r["socket_id"]), []).append(r)
    for g in groups.values():
        g.sort(key=lambda r: r["started_at"] or "")

    L: list[str] = []
    L.append("=" * 64)
    L.append(f"USAGE REPORT — {ped_name}  (cabinet {cabinet})")
    L.append(f"Month: {year:04d}-{month:02d}  (UTC)")
    L.append(f"Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z")
    L.append("Records: completed sessions only")
    L.append("=" * 64)

    total_kwh = 0.0
    total_l = 0.0
    n_elec = 0
    n_water = 0

    # Deterministic section order: electricity Q1..Qn, then water V1..Vn.
    def _order_key(k: tuple[str, int | None]) -> tuple[int, int]:
        resource, sid = k
        return (0 if resource == "electricity" else 1, sid if sid is not None else 0)

    if not groups:
        L.append("")
        L.append("No completed sessions for this month.")
    for key in sorted(groups.keys(), key=_order_key):
        resource, sid = key
        grp = groups[key]
        L.append("")
        L.append(f"=== {_socket_label(resource, sid)} ({resource}) ===")
        sub_kwh = 0.0
        sub_l = 0.0
        for r in grp:
            who_parts = []
            if r["customer_name"]:
                cid = f" (#{r['customer_id']})" if r["customer_id"] is not None else ""
                who_parts.append(f"{r['customer_name']}{cid}")
            if r["nfc_user_id"]:
                who_parts.append(f"nfc:{r['nfc_user_id']}")
            who = " / ".join(who_parts) if who_parts else "—"
            if resource == "water":
                amt = f"{(r['water_liters'] or 0.0):.1f} L".rjust(12)
                sub_l += r["water_liters"] or 0.0
            else:
                amt = f"{(r['energy_kwh'] or 0.0):.3f} kWh".rjust(12)
                sub_kwh += r["energy_kwh"] or 0.0
            L.append(
                f"{_fmt_dt(r['started_at'])} -> {_fmt_dt(r['ended_at'])}  "
                f"{amt}   customer: {who}"
            )
        if resource == "water":
            L.append(f"  Subtotal: {len(grp)} session(s), {sub_l:.1f} L")
            total_l += sub_l
            n_water += len(grp)
        else:
            L.append(f"  Subtotal: {len(grp)} session(s), {sub_kwh:.3f} kWh")
            total_kwh += sub_kwh
            n_elec += len(grp)

    L.append("")
    L.append("-" * 64)
    L.append(
        f"TOTALS: electricity {total_kwh:.3f} kWh across {n_elec} session(s); "
        f"water {total_l:.1f} L across {n_water} session(s)"
    )
    L.append("")
    return "\n".join(L)


# ── File operations ────────────────────────────────────────────────────────────

def write_report(db, pedestal_id: int, year: int, month: int) -> Path | None:
    """Render + persist the monthly report. Returns the path, or None if the
    disk guard refused the write (so we never fill the disk with reports)."""
    from .disk_guard import has_free_space, note_storage_full
    if not has_free_space():
        note_storage_full(lambda m: logger.warning("usage report skipped: %s", m))
        return None
    text = build_report_text(db, pedestal_id, year, month)
    path = report_path(pedestal_id, year, month)
    path.write_text(text, encoding="utf-8")
    logger.info("usage report written: %s (%d bytes)", path.name, len(text))
    return path


def get_or_generate(db, pedestal_id: int, year: int, month: int) -> Path | None:
    """Return an existing report file, lazily generating it if missing."""
    path = report_path(pedestal_id, year, month)
    if path.exists():
        return path
    return write_report(db, pedestal_id, year, month)


def list_reports(pedestal_id: int) -> list[dict]:
    """List available monthly report files for a pedestal, newest first."""
    out: list[dict] = []
    for p in reports_dir().glob(f"pedestal-{pedestal_id}_*.txt"):
        m = _FILE_RE.match(p.name)
        if not m or int(m.group(1)) != pedestal_id:
            continue
        try:
            st = p.stat()
        except OSError:
            continue
        out.append({
            "month": f"{m.group(2)}-{m.group(3)}",
            "filename": p.name,
            "size_bytes": st.st_size,
            "generated_at": datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z",
        })
    out.sort(key=lambda r: r["month"], reverse=True)
    return out


def delete_report(pedestal_id: int, year: int, month: int) -> bool:
    """Delete one monthly report file. Returns True if a file was removed."""
    path = report_path(pedestal_id, year, month)
    if path.exists():
        path.unlink()
        logger.info("usage report deleted: %s", path.name)
        return True
    return False


def generate_due_reports(db, now: datetime | None = None) -> int:
    """Ensure each pedestal's PREVIOUS-month report file exists. Idempotent:
    only writes a file that is not already present. Returns the count written.
    Used by the monthly scheduler."""
    now = now or datetime.utcnow()
    year, month = _prev_month(now)
    written = 0
    for (pid,) in db.query(Pedestal.id).all():
        if report_path(pid, year, month).exists():
            continue
        if write_report(db, pid, year, month) is not None:
            written += 1
    if written:
        logger.info("monthly reports: generated %d file(s) for %04d-%02d", written, year, month)
    return written


__all__ = [
    "reports_dir", "report_filename", "report_path", "month_bounds",
    "usage_rows", "build_report_text", "write_report", "get_or_generate",
    "list_reports", "delete_report", "generate_due_reports",
]
