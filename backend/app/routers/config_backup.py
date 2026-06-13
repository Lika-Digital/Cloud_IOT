"""Admin config backup / restore endpoints (v3.16)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from fastapi.responses import JSONResponse

from ..auth.dependencies import require_admin
from ..auth.models import User
from ..services import config_service

router = APIRouter(prefix="/api/admin/config", tags=["config-backup"])


@router.get("/export")
def export_config(
    full: bool = Query(default=False, description="Include secrets (full disaster-recovery backup)"),
    _: User = Depends(require_admin),
):
    """Export all configuration as a timestamped JSON bundle.

    Default is redacted (safe to share for troubleshooting). ?full=true includes
    table secrets (camera/MQTT/SMTP passwords, API key) but never the .env JWT
    secret. A copy is saved under data/backups/ and the bundle is returned.
    """
    bundle = config_service.export_config(include_secrets=full)
    try:
        path = config_service.write_backup(bundle)
        bundle["_saved_as"] = path.name
    except Exception as e:
        bundle["_saved_as"] = None
        bundle["_save_error"] = str(e)
    return JSONResponse(content=bundle)


@router.get("/backups")
def list_backups(_: User = Depends(require_admin)):
    """List stored config backups (newest first)."""
    return {"backups": config_service.list_backups()}


@router.get("/backups/{filename}")
def get_backup(filename: str, _: User = Depends(require_admin)):
    """Download a previously stored backup by filename."""
    import json
    # Resolve only against the known backup list — no path traversal.
    known = {b["filename"] for b in config_service.list_backups()}
    if filename not in known:
        raise HTTPException(status_code=404, detail="Backup not found")
    path = config_service.BACKUP_DIR / filename
    return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))


@router.get("/support-bundle")
def support_bundle(_: User = Depends(require_admin)):
    """One-click troubleshooting artifact: redacted config + MQTT/devices status
    + 24h/7d error summary. Saved under data/backups/ and returned for download."""
    import json
    from datetime import datetime
    from ..services.status_service import build_mqtt_status, build_devices_status
    from ..services.error_log_service import get_summary

    bundle = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "config": config_service.export_config(include_secrets=False),
        "mqtt_status": build_mqtt_status(),
        "devices_status": build_devices_status(),
        "error_summary": get_summary(),
    }
    try:
        config_service.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        path = config_service.BACKUP_DIR / f"support_bundle_{ts}.json"
        path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
        bundle["_saved_as"] = path.name
    except Exception as e:
        bundle["_save_error"] = str(e)
    return JSONResponse(content=bundle)


@router.post("/import")
def import_config(
    bundle: dict = Body(..., description="A config bundle from /export"),
    _: User = Depends(require_admin),
):
    """Restore configuration from an uploaded bundle. Upserts by natural key;
    redacted secrets are preserved (not overwritten). Returns a per-section
    applied/updated/skipped report."""
    try:
        report = config_service.import_config(bundle)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Restore failed: {e}")
    return {"status": "restored", "report": report}
