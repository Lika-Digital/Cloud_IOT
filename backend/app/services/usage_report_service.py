"""Per-pedestal usage history + monthly plain-text reports (v3.31).

Usage history is derived from COMPLETED ``sessions`` rows — the source of truth,
which the retention sweeper keeps forever (see ``retention_service``). Each
completed session contributes one usage record:

    timestamp · socket/valve · kWh · liters · customer / NFC user (when known)

When Smart Mode is OFF the Opta runs standalone and the NUC never attaches a
customer, so those fields are simply left blank — we report whatever the session
row actually holds.

Monthly reports are plain-text files, TWO per pedestal per month since 2026-10-14: the admin
file ``pedestal-{id}_{YYYY}-{MM}.txt`` (with ``customer #id``) and the staff file
``pedestal-{id}_{YYYY}-{MM}.staff.txt`` (no customer column at all), written under
``settings.reports_dir`` —
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
# 2026-10-14 — the STAFF version, a file of its own with no customer column at all. It is not
# redacted from the admin file: two files with one truth each, never one file in two truths.
_STAFF_FILE_RE = re.compile(r"^pedestal-(\d+)_(\d{4})-(\d{2})\.staff\.txt$")
ADMIN = "admin"
STAFF = "staff"
_AUDIENCES = (ADMIN, STAFF)


# ── Paths ─────────────────────────────────────────────────────────────────────

def reports_dir() -> Path:
    """Return the (created) reports directory from settings."""
    d = Path(settings.reports_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def report_filename(pedestal_id: int, year: int, month: int, audience: str = ADMIN) -> str:
    if audience not in _AUDIENCES:
        raise ValueError(f"audience must be one of {_AUDIENCES}, not {audience!r}")
    suffix = ".staff.txt" if audience == STAFF else ".txt"
    return f"pedestal-{pedestal_id}_{year:04d}-{month:02d}{suffix}"


def report_path(pedestal_id: int, year: int, month: int, audience: str = ADMIN) -> Path:
    return reports_dir() / report_filename(pedestal_id, year, month, audience)


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
    include_identity: bool = False,
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

    # v3.44 — IDENTITY IS OPT-IN, AND OFF BY DEFAULT.
    #
    # `customer_name` and `nfc_user_id` used to be in every row, and the endpoint above
    # is `require_any_role` — so marina staff could read the name of every customer who
    # had ever used a socket. Decided 2026-10-01: marina staff do not see customer names.
    #
    # Default False rather than True-with-a-filter, so a future caller that forgets to
    # think about it leaks nothing. The admin path asks for identity explicitly, which is
    # also the line a reviewer can find.
    #
    # `customer_id` STAYS in both shapes: it is an opaque integer, it is what the
    # monthly report groups by, and without it the rows cannot be told apart. The name
    # is the exposure, not the key.
    names = _resolve_customer_names({s.customer_id for s in sessions}) if include_identity else {}
    rows: list[dict] = []
    for s in sessions:
        row = {
            "session_id": s.id,
            "socket_id": s.socket_id,
            "type": s.type,
            "started_at": iso_z(s.started_at),
            "ended_at": iso_z(s.ended_at),
            "energy_kwh": s.energy_kwh,
            "water_liters": s.water_liters,
            "customer_id": s.customer_id,
            "end_reason": s.end_reason,
        }
        if include_identity:
            row["customer_name"] = names.get(s.customer_id)
            row["nfc_user_id"] = s.nfc_user_id
        rows.append(row)
    return rows


# ── Report rendering ───────────────────────────────────────────────────────────
#
# 2026-10-14 — REWRITTEN. The report printed `energy_kwh or 0.0`: an unmeasured session read
# "0.000 kWh", was added into the subtotal as zero, and nothing said which figures were meter
# readings and which were estimates. Zero and "we did not measure" were the same line — the
# defect this project has been hunting for months, in a file people read as the record.
#
# Now, per session row:
#   * the figure comes from the SESSION ROW (`energy_kwh` / `water_liters`), labelled by its
#     `consumption_source`, with BOTH register readings printed beside it so anyone can
#     recompute it by hand;
#   * a figure that is not known prints "—", never 0;
# and per total: if ANY session in it was not measured, NO total figure is printed — only
# "PARTIAL — N of M session(s) not measured". A number beside a caveat is still read as the
# number, so the number is not there to be read. (Guarded by TC-REP-02.)
#
# WHY THE SESSION ROW AND NOT THE LEDGER (docs/ui_v2_spec.md §4.4): energy_intervals has
# written no row on cabinet 1 since 2026-10-10 16:12:59 UTC and every row it holds is an
# integral estimate. A report from it would say "not measured" where the meter measured.
# The session row carries the register delta and both readings. The source returns to the
# ledger when the ledger writes again — the condition is in §4.4.
#
# PROVISIONAL vs FINAL: a report generated before its month is over, or while a session that
# started in it is still open, is PROVISIONAL and is regenerated on the next access or the next
# monthly pass. It used to be cached forever: a download on 24 August froze a partial August,
# and a file generated at 00:xx on the 1st silently lost every session still open at that minute.
# Files WITHOUT a "Status:" line predate this and are never regenerated (they carry a legacy
# header instead — scripts/mark_legacy_reports.py).

_STATUS_FINAL = "Status: FINAL"
_STATUS_PROVISIONAL = "Status: PROVISIONAL"
_OPEN_STATUSES = ("pending", "active")

# consumption_source -> the label printed beside the figure
_LABELS = {
    "register": "meter reading",
    "integrated_legacy": "estimate - meter not available",
}
_NOT_MEASURED = "not measured"
_NO_SOURCE = "not measured (no provenance recorded)"


def _fmt_dt(dt) -> str:
    if dt is None:
        return "?"
    return dt.isoformat(sep=" ")[:16]


def _socket_label(resource: str, socket_id: int | None) -> str:
    if resource == "water":
        return f"Valve V{socket_id}" if socket_id is not None else "Valve V?"
    return f"Socket Q{socket_id}" if socket_id is not None else "Socket ?"


def _fmt_qty(value: float, unit: str) -> str:
    return f"{value:.3f} kWh" if unit == "kWh" else f"{value:.1f} L"


def _classify(s: SessionModel) -> tuple[str, float | None, float | None, float | None, str]:
    """(kind, figure, register_start, register_end, unit) for one session.

    kind is "measured" (register), "estimated" (integrated_legacy) or "unmeasured". A figure is
    returned only for the first two; "unknown", a NULL source, or a NULL figure is unmeasured —
    a figure without provenance is not reported as if it had one.
    """
    if s.type == "water":
        fig, start, end, unit = s.water_liters, s.meter_water_start_l, s.meter_water_end_l, "L"
    else:
        fig, start, end, unit = s.energy_kwh, s.meter_energy_start_kwh, s.meter_energy_end_kwh, "kWh"
    src = s.consumption_source
    if fig is not None and src == "register":
        return "measured", float(fig), start, end, unit
    if fig is not None and src == "integrated_legacy":
        return "estimated", float(fig), start, end, unit
    return "unmeasured", None, start, end, unit


def _row_line(s: SessionModel, audience: str) -> str:
    kind, fig, start, end, unit = _classify(s)
    amount = (_fmt_qty(fig, unit) if fig is not None else "—").rjust(12)
    if kind == "unmeasured":
        label = _NO_SOURCE if s.consumption_source is None else _NOT_MEASURED
    else:
        label = _LABELS[s.consumption_source]
    if start is not None and end is not None:
        reg = f"register {_fmt_qty(float(start), unit)} -> {_fmt_qty(float(end), unit)}"
    elif start is not None:
        reg = f"register {_fmt_qty(float(start), unit)} -> ?"
    else:
        reg = "no register reading"
    line = f"{_fmt_dt(s.started_at)} -> {_fmt_dt(s.ended_at)}  {amount}  [{label}]  {reg}"
    if audience == ADMIN:
        # customer_id only — never the name or nfc_user_id (v3.44): WE know the berth and the
        # consumption, the ERP knows the customer. The staff file has no customer column at all.
        cid = s.customer_id
        line += f"  customer: {'customer #' + str(cid) if cid is not None else '—'}"
    return line


def _total_line(prefix: str, sessions: list[SessionModel], unit: str) -> str:
    """A total — or, if any session in it was not measured, explicitly NOT a total."""
    n = len(sessions)
    kinds = [_classify(s) for s in sessions]
    unmeasured = sum(1 for k in kinds if k[0] == "unmeasured")
    if unmeasured:
        return (f"{prefix}: PARTIAL - {unmeasured} of {n} session(s) not measured; "
                f"no total is given, because any figure here would be read as the total")
    total = sum(k[1] for k in kinds)
    estimated = sum(k[1] for k in kinds if k[0] == "estimated")
    line = f"{prefix}: {n} session(s), {_fmt_qty(total, unit)}"
    if estimated:
        line += f" (of which {_fmt_qty(estimated, unit)} estimated - meter not available)"
    return line


def _month_sessions(db, pedestal_id: int, year: int, month: int):
    start, end = month_bounds(year, month)
    base = db.query(SessionModel).filter(
        SessionModel.pedestal_id == pedestal_id,
        SessionModel.started_at >= start, SessionModel.started_at < end,
    )
    done = base.filter(SessionModel.status == "completed").all()
    still_open = base.filter(SessionModel.status.in_(_OPEN_STATUSES)).count()
    return done, still_open


def build_report_text(db, pedestal_id: int, year: int, month: int,
                      audience: str = ADMIN, now: datetime | None = None) -> str:
    """Render the plain-text monthly report for one pedestal, for one audience."""
    if audience not in _AUDIENCES:
        raise ValueError(f"audience must be one of {_AUDIENCES}, not {audience!r}")
    now = now or datetime.utcnow()
    ped = db.get(Pedestal, pedestal_id)
    cfg = db.query(PedestalConfig).filter(
        PedestalConfig.pedestal_id == pedestal_id
    ).first()
    cabinet = (cfg.opta_client_id if cfg else None) or "?"
    ped_name = (getattr(ped, "name", None) if ped else None) or f"Pedestal {pedestal_id}"

    sessions, still_open = _month_sessions(db, pedestal_id, year, month)
    _, month_end = month_bounds(year, month)
    reasons = []
    if now < month_end:
        reasons.append("the month was not over when this was generated")
    if still_open:
        reasons.append(f"{still_open} session(s) that started this month were still open")

    L: list[str] = []
    L.append("=" * 72)
    title = "USAGE REPORT" if audience == ADMIN else "USAGE REPORT - STAFF VERSION (no customer column)"
    L.append(f"{title} — {ped_name}  (cabinet {cabinet})")
    L.append(f"Month: {year:04d}-{month:02d}  (UTC)")
    L.append(f"Generated: {now.isoformat(timespec='seconds')}Z")
    L.append(f"{_STATUS_PROVISIONAL} - " + "; ".join(reasons) + " - regenerated automatically"
             if reasons else _STATUS_FINAL)
    L.append("Records: completed sessions. Each figure is the session's own figure, labelled by")
    L.append("how it was derived, with the two meter register readings it comes from:")
    L.append("  [meter reading]  = end - start of the meter's register; recompute it by hand")
    L.append("  [estimate - meter not available] = the old power x time method (only sessions")
    L.append("                     already running when the register change deployed)")
    L.append("  [not measured]   = no figure exists; shown as —, never as 0")
    L.append("=" * 72)

    groups: dict[tuple[str, int | None], list[SessionModel]] = {}
    for s in sessions:
        groups.setdefault((s.type, s.socket_id), []).append(s)

    def _order_key(k: tuple[str, int | None]) -> tuple[int, int]:
        resource, sid = k
        return (0 if resource == "electricity" else 1, sid if sid is not None else 0)

    if not groups:
        L.append("")
        L.append("No completed sessions for this month.")
    by_type: dict[str, list[SessionModel]] = {"electricity": [], "water": []}
    for key in sorted(groups.keys(), key=_order_key):
        resource, sid = key
        grp = sorted(groups[key], key=lambda s: s.started_at)
        unit = "L" if resource == "water" else "kWh"
        L.append("")
        L.append(f"=== {_socket_label(resource, sid)} ({resource}) ===")
        for s in grp:
            L.append(_row_line(s, audience))
        L.append(_total_line("  Subtotal", grp, unit))
        by_type.setdefault(resource, []).extend(grp)

    L.append("")
    L.append("-" * 72)
    L.append(_total_line("TOTAL electricity", by_type["electricity"], "kWh")
             if by_type["electricity"] else "TOTAL electricity: no completed sessions")
    L.append(_total_line("TOTAL water", by_type["water"], "L")
             if by_type["water"] else "TOTAL water: no completed sessions")
    L.append("")
    return "\n".join(L)


def is_provisional(path: Path) -> bool:
    """True only for a file this code marked PROVISIONAL. A file with no Status line predates
    the marker (a legacy report) and is NEVER regenerated."""
    try:
        with path.open(encoding="utf-8") as f:
            head = [next(f, "") for _ in range(8)]
    except OSError:
        return False
    return any(line.startswith(_STATUS_PROVISIONAL) for line in head)


# ── File operations ────────────────────────────────────────────────────────────

def write_report(db, pedestal_id: int, year: int, month: int,
                 audience: str = ADMIN, now: datetime | None = None) -> Path | None:
    """Render + persist the monthly report. Returns the path, or None if the
    disk guard refused the write (so we never fill the disk with reports)."""
    from .disk_guard import has_free_space, note_storage_full
    if not has_free_space():
        note_storage_full(lambda m: logger.warning("usage report skipped: %s", m))
        return None
    text = build_report_text(db, pedestal_id, year, month, audience, now=now)
    path = report_path(pedestal_id, year, month, audience)
    path.write_text(text, encoding="utf-8")
    logger.info("usage report written: %s (%d bytes)", path.name, len(text))
    return path


def get_or_generate(db, pedestal_id: int, year: int, month: int,
                    audience: str = ADMIN, now: datetime | None = None) -> Path | None:
    """Return the report file, generating it if missing or PROVISIONAL."""
    path = report_path(pedestal_id, year, month, audience)
    if path.exists() and not is_provisional(path):
        return path
    return write_report(db, pedestal_id, year, month, audience, now=now)


def list_reports(pedestal_id: int, audience: str = ADMIN) -> list[dict]:
    """List available monthly report files for a pedestal, newest first."""
    rx = _STAFF_FILE_RE if audience == STAFF else _FILE_RE
    out: list[dict] = []
    for p in reports_dir().glob(f"pedestal-{pedestal_id}_*.txt"):
        m = rx.match(p.name)
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
            "provisional": is_provisional(p),
        })
    out.sort(key=lambda r: r["month"], reverse=True)
    return out


def delete_report(pedestal_id: int, year: int, month: int) -> bool:
    """Delete one month's report files (admin and staff). True if anything was removed."""
    removed = False
    for audience in _AUDIENCES:
        path = report_path(pedestal_id, year, month, audience)
        if path.exists():
            path.unlink()
            logger.info("usage report deleted: %s", path.name)
            removed = True
    return removed


def generate_due_reports(db, now: datetime | None = None) -> int:
    """Ensure each pedestal's PREVIOUS-month reports (admin and staff) exist and are not
    provisional. Idempotent: a FINAL file is never rewritten, a legacy file (no Status line) is
    never touched. Returns the count written. Used by the monthly scheduler."""
    now = now or datetime.utcnow()
    year, month = _prev_month(now)
    written = 0
    for (pid,) in db.query(Pedestal.id).all():
        for audience in _AUDIENCES:
            path = report_path(pid, year, month, audience)
            if path.exists() and not is_provisional(path):
                continue
            if write_report(db, pid, year, month, audience, now=now) is not None:
                written += 1
    # Said every pass, written or not: a job that is silent when it does nothing cannot be told
    # from a job that does not run (§13 checks this line on 1 November).
    logger.info("monthly reports: %d file(s) written for %04d-%02d", written, year, month)
    return written


__all__ = [
    "reports_dir", "report_filename", "report_path", "month_bounds",
    "usage_rows", "build_report_text", "write_report", "get_or_generate",
    "list_reports", "delete_report", "generate_due_reports", "is_provisional",
    "ADMIN", "STAFF",
]
