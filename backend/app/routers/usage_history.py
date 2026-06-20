"""Usage history + monthly report endpoints (v3.31).

All endpoints are admin-only (``require_admin``). The read-only GETs are also
opt-in exposable to the ERP via the External API Gateway (see api_catalog) — the
gateway proxies with an internal admin token and monitor-mode permits GET only,
so report DELETION can never be reached from outside.

Usage data comes from completed ``sessions`` rows (retention-safe, kept forever).
Monthly report files live under ``settings.reports_dir`` and are removed only
through the DELETE endpoint below — never by the system.
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..auth.dependencies import require_any_role, require_control
from ..auth.models import User
from ..services import usage_report_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pedestals", tags=["usage-history"])

_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _parse_month(month: str) -> tuple[int, int]:
    m = _MONTH_RE.match(month or "")
    if not m:
        raise HTTPException(status_code=400, detail="month must be 'YYYY-MM'")
    year, mon = int(m.group(1)), int(m.group(2))
    if not (1 <= mon <= 12):
        raise HTTPException(status_code=400, detail="month out of range")
    return year, mon


@router.get("/{pedestal_id}/usage/history")
def get_usage_history(
    pedestal_id: int,
    resource: str | None = Query(None, pattern="^(electricity|water)$"),
    socket_id: int | None = Query(None, ge=1, le=4),
    month: str | None = Query(None, description="Optional 'YYYY-MM' filter"),
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    """Completed-session usage records for a socket/valve (newest first).

    Without ``month`` returns all-time history; ``socket_id``/``resource``
    narrow to one outlet. Customer / NFC fields are blank for sessions the NUC
    never attributed (e.g. Smart Mode off — standalone Opta).
    """
    year = mon = None
    if month:
        year, mon = _parse_month(month)
    return svc.usage_rows(
        db, pedestal_id,
        socket_id=socket_id, resource=resource, year=year, month=mon,
    )


@router.get("/{pedestal_id}/usage/reports")
def list_usage_reports(
    pedestal_id: int,
    _: User = Depends(require_any_role),
):
    """List available monthly report files for this pedestal (newest first)."""
    return svc.list_reports(pedestal_id)


@router.get("/{pedestal_id}/usage/reports/{month}")
def download_usage_report(
    pedestal_id: int,
    month: str,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    """Download the plain-text monthly report. Lazily generated if missing."""
    year, mon = _parse_month(month)
    path = svc.get_or_generate(db, pedestal_id, year, mon)
    if path is None:
        # Disk guard refused the write — surface a clear, actionable error.
        raise HTTPException(
            status_code=507,
            detail="Storage nearly full — report not generated. Free disk space and retry.",
        )
    text = path.read_text(encoding="utf-8")
    filename = svc.report_filename(pedestal_id, year, mon)
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{pedestal_id}/usage/reports/{month}")
def delete_usage_report(
    pedestal_id: int,
    month: str,
    user: User = Depends(require_control),
):
    """Delete a monthly report file. ADMIN ONLY — the system never deletes
    these; this is the sole removal path, so it is audited."""
    year, mon = _parse_month(month)
    removed = svc.delete_report(pedestal_id, year, mon)
    if not removed:
        raise HTTPException(status_code=404, detail="Report not found")
    logger.info(
        "usage report %04d-%02d for pedestal %d deleted by admin %s",
        year, mon, pedestal_id, getattr(user, "email", "?"),
    )
    return {"deleted": True, "pedestal_id": pedestal_id, "month": f"{year:04d}-{mon:02d}"}
