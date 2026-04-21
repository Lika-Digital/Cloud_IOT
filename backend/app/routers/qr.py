"""
QR code bulk endpoints (v3.7).

Only two endpoints live here because single-socket QR preview is already
served by `GET /api/mobile/socket/{pid}/{sid}/qr` (v3.6). These cover the
printable-sheet workflow:

  GET  /api/pedestals/{cabinet_id}/qr/all         — ZIP of all 4 socket PNGs
  POST /api/pedestals/{cabinet_id}/qr/regenerate  — delete disk cache + rebuild

Both are admin-only. Both resolve `cabinet_id` via the existing PedestalConfig
lookup so a 404 fires for unknown cabinets without doing any filesystem work.
"""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session as DBSession

from ..database import get_db
from ..models.pedestal_config import PedestalConfig
from ..auth.dependencies import require_admin
from ..services.qr_service import (
    generate_socket_qr,
    regenerate_socket_qr,
    delete_all_qr_for_pedestal,
)


router = APIRouter(prefix="/api/pedestals", tags=["qr"])
logger = logging.getLogger(__name__)


_ELECTRICITY_SOCKETS = ["Q1", "Q2", "Q3", "Q4"]


def _resolve_cabinet(db: DBSession, cabinet_id: str) -> PedestalConfig:
    """Look up a PedestalConfig by opta_client_id string. Raises 404 if absent.
    We accept the cabinet_id string (not the numeric PK) because operators
    printing QR sheets work from the physical label printed on the cabinet."""
    cfg = db.query(PedestalConfig).filter(PedestalConfig.opta_client_id == cabinet_id).first()
    if not cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pedestal not found")
    return cfg


@router.get("/{cabinet_id}/qr/all")
def download_all_qr_codes(
    cabinet_id: str,
    db: DBSession = Depends(get_db),
    _: object = Depends(require_admin),
):
    """Stream a ZIP of `{cabinet_id}_Q{1..4}.png` for this pedestal.

    If a socket's PNG isn't on disk yet it is generated on the fly so the
    response is always a complete set. Filename is
    `{cabinet_id}_qr_codes.zip` via Content-Disposition.
    """
    _resolve_cabinet(db, cabinet_id)

    # Build the archive in memory; four 300x350 PNGs are trivial (<200 KB total).
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for sid in _ELECTRICITY_SOCKETS:
            png_path = generate_socket_qr(cabinet_id, sid)
            try:
                with open(png_path, "rb") as f:
                    zf.writestr(f"{cabinet_id}_{sid}.png", f.read())
            except FileNotFoundError:
                # The file was reported as generated but couldn't be read —
                # skip it rather than 500. The operator will see a missing
                # entry in the archive and can hit /regenerate.
                logger.warning("[QR] expected %s after generate but not found", png_path)
                continue

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{cabinet_id}_qr_codes.zip"',
        },
    )


@router.post("/{cabinet_id}/qr/regenerate")
def regenerate_all_qr_codes(
    cabinet_id: str,
    db: DBSession = Depends(get_db),
    _: object = Depends(require_admin),
):
    """Delete every `{cabinet_id}_*.png` on disk and render a fresh set.

    Used when the URL format changes (shouldn't happen without a migration)
    or when an operator wants to force-refresh the printable labels.
    Returns a tiny summary the dashboard can show as a toast.
    """
    _resolve_cabinet(db, cabinet_id)
    deleted = delete_all_qr_for_pedestal(cabinet_id)
    regenerated: list[str] = []
    for sid in _ELECTRICITY_SOCKETS:
        regenerate_socket_qr(cabinet_id, sid)
        regenerated.append(sid)
    return {
        "cabinet_id": cabinet_id,
        "deleted": deleted,
        "regenerated": regenerated,
    }
