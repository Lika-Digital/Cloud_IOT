"""Usage history + monthly report endpoints (v3.31).

ACCESS, CORRECTED 2026-10-01. This docstring said "All endpoints are admin-only
(``require_admin``)" and had said so since v3.31. **None of them was.** The real gates:

  * the three read endpoints — ``require_any_role`` (any operator, including monitor)
  * ``DELETE`` on a report      — ``require_control`` (not admin either)

The third such finding in this codebase, after the NFC provisioning routes and
``/api/analytics``. A docstring is a claim, not a control — see
``docs/engineering_notes.md``.

The read gate is LEFT as ``require_any_role`` deliberately: "what did berth 3 use last
week" is operations, and that is the audience. What changed is the PAYLOAD —
``customer_name`` and ``nfc_user_id`` are returned only to an admin, because marina
staff do not see customer names (decided 2026-10-01).

2026-10-12, part B: ``customer_id`` too. The 2026-10-01 note kept it for staff as "an opaque
join key"; the owner's rule is that staff see NO customer identity, and an id that is stable
across sessions identifies the customer just as well as a name does. For a non-admin the
response now carries none of auth/identity_redaction.IDENTITY_KEYS — removed, not nulled.

The read-only GETs are also opt-in exposable to the ERP via the External API Gateway
(see api_catalog) — the gateway proxies with an internal admin token and monitor-mode
permits GET only, so report DELETION can never be reached from outside. NOTE: because
the proxy token is admin, a gateway-proxied call DOES receive the identity fields.
That is correct — the ERP already holds the customers; it is the marina operator this
withholds them from.

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
from ..auth.dependencies import require_admin, require_any_role
from ..auth.models import User
from ..auth.identity_redaction import redact, sees_identity
from ..services import usage_report_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pedestals", tags=["usage-history"])

# _REPORTS_LOCKED — 2026-10-12, owner's decision: the monthly report FILES are admin only, and
# (2026-10-12: "temporarily"; 2026-10-14: permanently — see below.) They print "customer #<id>".
# Staff do have a legitimate need for consumption per outlet, so the owner considered redacting
# the identifier instead — and chose to lock: redacting generated text is easier to break than a
# lock, and the reports are partial and cached anyway. Whether staff get a version WITHOUT the
# customer identifier is decided when the five legacy .txt reports are labelled (plan item 4).
# DECIDED 2026-10-14 (owner): staff get a SEPARATE file, generated as its own file with no
# customer column at all — not redacted from the admin file. The admin file stays locked. Two
# files with one truth each, never one file in two truths. Routes: /usage/staff-reports below.
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
    user: User = Depends(require_any_role),
):
    """Completed-session usage records for a socket/valve (newest first).

    Without ``month`` returns all-time history; ``socket_id``/``resource``
    narrow to one outlet.

    The identity fields appear ONLY for an admin caller. Marina staff get the consumption,
    which is everything the operational question needs. For an admin, the fields are present
    but still blank for sessions the NUC never attributed (Smart Mode off — standalone Opta).
    (Until 2026-10-12 staff also got ``customer_id`` — see the module docstring.)
    """
    year = mon = None
    if month:
        year, mon = _parse_month(month)
    rows = svc.usage_rows(
        db, pedestal_id,
        include_identity=sees_identity(user.role),
        socket_id=socket_id, resource=resource, year=year, month=mon,
    )
    return rows if sees_identity(user.role) else redact(rows)


@router.get("/{pedestal_id}/usage/reports")
def list_usage_reports(
    pedestal_id: int,
    _: User = Depends(require_admin),  # admin file stays locked (owner, 2026-10-14); staff: /usage/staff-reports
):
    """List available monthly report files for this pedestal (newest first). Admin only."""
    return svc.list_reports(pedestal_id)


@router.get("/{pedestal_id}/usage/reports/{month}")
def download_usage_report(
    pedestal_id: int,
    month: str,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_admin),  # admin file stays locked (owner, 2026-10-14); staff: /usage/staff-reports
):
    """Download the plain-text monthly report. Lazily generated if missing. Admin only."""
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


@router.get("/{pedestal_id}/usage/staff-reports")
def list_staff_reports(
    pedestal_id: int,
    _: User = Depends(require_any_role),
):
    """List the STAFF report files (no customer column). Every operator."""
    return svc.list_reports(pedestal_id, svc.STAFF)


@router.get("/{pedestal_id}/usage/staff-reports/{month}")
def download_staff_report(
    pedestal_id: int,
    month: str,
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    """Download the STAFF monthly report — generated as its own file, never redacted from the
    admin one, so there is no customer column to leak. Lazily generated if missing."""
    year, mon = _parse_month(month)
    path = svc.get_or_generate(db, pedestal_id, year, mon, svc.STAFF)
    if path is None:
        raise HTTPException(
            status_code=507,
            detail="Storage nearly full — report not generated. Free disk space and retry.",
        )
    return Response(
        content=path.read_text(encoding="utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="{svc.report_filename(pedestal_id, year, mon, svc.STAFF)}"'},
    )


@router.delete("/{pedestal_id}/usage/reports/{month}")
def delete_usage_report(
    pedestal_id: int,
    month: str,
    user: User = Depends(require_admin),  # was require_control — see below
):
    """Delete a monthly report file. ADMIN ONLY — the system never deletes
    these; this is the sole removal path, so it is audited.

    2026-10-12: "ADMIN ONLY" was again a claim — the gate was require_control, so
    monitor_control could delete. Now it is what the docstring says.
    """
    year, mon = _parse_month(month)
    removed = svc.delete_report(pedestal_id, year, mon)
    if not removed:
        raise HTTPException(status_code=404, detail="Report not found")
    logger.info(
        "usage report %04d-%02d for pedestal %d deleted by admin %s",
        year, mon, pedestal_id, getattr(user, "email", "?"),
    )
    return {"deleted": True, "pedestal_id": pedestal_id, "month": f"{year:04d}-{mon:02d}"}
