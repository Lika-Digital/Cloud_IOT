"""Admin data export + database backup downloads (v3.37).

Two self-contained, read-only downloads over HTTPS — no external infra:

  * GET /api/admin/backup/database
      A consistent snapshot of pedestal.db + users.db, zipped. ADMIN ONLY
      (users.db carries password hashes + secrets). This is an on-demand
      disaster-recovery copy the operator saves off the NUC (browser download =
      off-box). Restore: stop the backend, drop the two .db files into
      /opt/cloud-iot/backend/ (users.db under data/), start it again.

  * GET /api/admin/export/usage?format=json|csv&date_from=&date_to=
      Sessions + the 15-min energy-interval ledger + invoices, joined with
      customer name/ship, date-range filtered. For the marina manager to hand to
      the ERP or do offline pricing. Control role (admin / monitor_control*).

Neither is destructive: the backup uses the SQLite online-backup API against a
read-only connection, so it is safe while WAL is active and never blocks writes.
"""
import csv
import io
import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session as DBSession

from ..auth.dependencies import require_admin, require_control
from ..auth.models import User
from ..auth.user_database import get_user_db, user_engine
from ..database import engine as iot_engine, get_db

router = APIRouter(prefix="/api/admin", tags=["data-export"])


# ── Database backup ───────────────────────────────────────────────────────────

def _db_path(eng) -> Path:
    """Absolute path to a SQLite engine's file (url.database)."""
    return Path(eng.url.database).resolve()


def _snapshot(src_path: Path, dst_path: Path) -> None:
    """Consistent hot copy via the SQLite online-backup API (WAL-safe).

    Opens the source read-only so it can never interfere with the running app's
    writers; the backup API produces a transactionally-consistent file even
    while the WAL is being appended to.
    """
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(dst_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


@router.get("/backup/database")
def download_database_backup(_: User = Depends(require_admin)):
    """Download a consistent snapshot of both databases as one zip. Admin only."""
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    targets = {
        "pedestal.db": _db_path(iot_engine),
        "users.db":    _db_path(user_engine),
    }
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for arcname, src in targets.items():
                if not src.exists():
                    continue
                snap = tmpdir / arcname
                _snapshot(src, snap)
                zf.write(snap, arcname=arcname)
    buf.seek(0)
    filename = f"cloud_iot_db_backup_{ts}.zip"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Usage / billing export ────────────────────────────────────────────────────

SESSION_FIELDS = [
    "id", "pedestal_id", "socket_id", "type", "status", "started_at", "ended_at",
    "energy_kwh", "water_liters", "customer_id", "customer_name", "ship_name",
    "nfc_user_id", "origin", "end_reason",
]
INTERVAL_FIELDS = [
    "id", "pedestal_id", "socket_id", "session_id", "origin", "customer_id",
    "nfc_user_id", "berth_ref", "interval_start", "interval_end", "kwh", "avg_power_kw",
]
INVOICE_FIELDS = [
    "id", "session_id", "customer_id", "customer_name", "energy_kwh", "water_liters",
    "energy_cost_eur", "water_cost_eur", "total_eur", "paid", "created_at",
]


def _parse_date(s: str | None, *, end: bool = False) -> datetime | None:
    """'YYYY-MM-DD' → datetime. For the end bound, return the next midnight so the
    filter (start < end) is inclusive of the whole `date_to` day."""
    if not s:
        return None
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be YYYY-MM-DD")
    return d + timedelta(days=1) if end else d


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


@router.get("/export/usage")
def export_usage(
    format: str = Query("json", pattern="^(json|csv)$", description="json (default) or csv (zip)"),
    date_from: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    date_to: str | None = Query(None, description="YYYY-MM-DD, inclusive"),
    db: DBSession = Depends(get_db),
    udb: DBSession = Depends(get_user_db),
    _: User = Depends(require_control),
):
    """Export usage/billing data for the ERP or offline pricing (control role)."""
    from ..auth.customer_models import Customer, Invoice
    from ..models.energy_interval import EnergyInterval
    from ..models.session import Session as Sess

    start = _parse_date(date_from)
    end = _parse_date(date_to, end=True)

    cust = {c.id: c for c in udb.query(Customer).all()}

    def _name(cid):
        c = cust.get(cid)
        return c.name if c else None

    def _ship(cid):
        c = cust.get(cid)
        return c.ship_name if c else None

    sq = db.query(Sess)
    if start:
        sq = sq.filter(Sess.started_at >= start)
    if end:
        sq = sq.filter(Sess.started_at < end)
    sessions = [
        {
            "id": s.id, "pedestal_id": s.pedestal_id, "socket_id": s.socket_id,
            "type": s.type, "status": s.status,
            "started_at": _iso(s.started_at), "ended_at": _iso(s.ended_at),
            "energy_kwh": s.energy_kwh, "water_liters": s.water_liters,
            "customer_id": s.customer_id, "customer_name": _name(s.customer_id),
            "ship_name": _ship(s.customer_id), "nfc_user_id": s.nfc_user_id,
            "origin": s.origin, "end_reason": s.end_reason,
        }
        for s in sq.order_by(Sess.started_at).all()
    ]

    iq = db.query(EnergyInterval)
    if start:
        iq = iq.filter(EnergyInterval.interval_start >= start)
    if end:
        iq = iq.filter(EnergyInterval.interval_start < end)
    intervals = [
        {
            "id": iv.id, "pedestal_id": iv.pedestal_id, "socket_id": iv.socket_id,
            "session_id": iv.session_id, "origin": iv.origin,
            "customer_id": iv.customer_id, "nfc_user_id": iv.nfc_user_id,
            "berth_ref": iv.berth_ref,
            "interval_start": _iso(iv.interval_start), "interval_end": _iso(iv.interval_end),
            "kwh": iv.kwh, "avg_power_kw": iv.avg_power_kw,
        }
        for iv in iq.order_by(EnergyInterval.interval_start).all()
    ]

    vq = udb.query(Invoice)
    if start:
        vq = vq.filter(Invoice.created_at >= start)
    if end:
        vq = vq.filter(Invoice.created_at < end)
    invoices = [
        {
            "id": v.id, "session_id": v.session_id, "customer_id": v.customer_id,
            "customer_name": _name(v.customer_id),
            "energy_kwh": v.energy_kwh, "water_liters": v.water_liters,
            "energy_cost_eur": v.energy_cost_eur, "water_cost_eur": v.water_cost_eur,
            "total_eur": v.total_eur, "paid": bool(v.paid), "created_at": _iso(v.created_at),
        }
        for v in vq.order_by(Invoice.created_at).all()
    ]

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    meta = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "date_from": date_from, "date_to": date_to,
        "counts": {
            "sessions": len(sessions),
            "energy_intervals": len(intervals),
            "invoices": len(invoices),
        },
    }

    if format == "json":
        body = json.dumps(
            {"meta": meta, "sessions": sessions, "energy_intervals": intervals, "invoices": invoices},
            indent=2,
        ).encode("utf-8")
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="cloud_iot_usage_{ts}.json"'},
        )

    # CSV → a zip of three CSVs + meta.json. Explicit fieldnames so an empty
    # export still carries headers.
    def _csv(rows, fields) -> str:
        out = io.StringIO()
        w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return out.getvalue()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("sessions.csv", _csv(sessions, SESSION_FIELDS))
        zf.writestr("energy_intervals.csv", _csv(intervals, INTERVAL_FIELDS))
        zf.writestr("invoices.csv", _csv(invoices, INVOICE_FIELDS))
        zf.writestr("meta.json", json.dumps(meta, indent=2))
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="cloud_iot_usage_{ts}.zip"'},
    )
