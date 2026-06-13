"""Configuration backup / restore (v3.16).

Exports all operator-managed configuration from BOTH databases into a single
timestamped JSON bundle — for troubleshooting/support and disaster recovery —
and restores it.

Secrets (passwords, camera/MQTT passwords, the external-API key) are REDACTED by
default; an opt-in `include_secrets=True` "full backup" keeps them. The .env
JWT secret and admin password are NEVER exported (they are not in these tables).

Restore is **additive config only**: it upserts by NATURAL KEY (never by raw
autoincrement PK — pedestal IDs are recreated on every restart) and never
touches sessions / invoices / telemetry. Redacted secret values are skipped on
restore so an existing real secret is preserved rather than overwritten with a
placeholder.
"""
import json
import logging
import os
from datetime import datetime, date, time
from pathlib import Path

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import DateTime

from ..database import SessionLocal
from ..auth.user_database import UserSessionLocal, DATA_DIR
from ..config import settings

logger = logging.getLogger(__name__)

BACKUP_DIR = DATA_DIR / "backups"
SCHEMA_VERSION = 1
REDACTED = "***REDACTED***"
SECRET_COLS = {"password", "mqtt_password", "camera_password", "api_key", "password_hash"}

# Safe .env keys to include for context (NEVER secrets).
_ENV_SAFE_KEYS = [
    "mqtt_broker_host", "mqtt_broker_port", "marina_timezone", "app_env",
    "company_name", "company_address", "company_phone", "company_email",
    "allowed_origins", "allow_self_registration",
]


def _sections():
    """Registry of config tables. (key, model, db, natural_key, restorable).

    db: 'iot' (pedestal.db) | 'user' (users.db). natural_key None ⇒ singleton.
    Operator accounts / customers / telemetry are intentionally excluded.
    """
    from ..models.pedestal import Pedestal
    from ..models.pedestal_config import PedestalConfig, PedestalSensor
    from ..models.socket_config import SocketConfig
    from ..models.valve_config import ValveConfig
    from ..models.led_schedule import LedSchedule
    from ..models.snmp_config import SnmpConfig
    from ..models.external_api import ExternalApiConfig
    from ..models.pilot_assignment import PilotAssignment
    from ..auth.models import SmtpConfig
    from ..auth.customer_models import BillingConfig
    from ..auth.contract_models import ContractTemplate
    from ..auth.berth_models import Berth
    return [
        ("pedestals",          Pedestal,          "iot",  ("name",),               False),
        ("pedestal_configs",   PedestalConfig,    "iot",  ("opta_client_id",),     True),
        ("socket_configs",     SocketConfig,      "iot",  ("pedestal_id", "socket_id"), True),
        ("valve_configs",      ValveConfig,       "iot",  None,                    False),
        ("led_schedules",      LedSchedule,       "iot",  ("pedestal_id",),        True),
        ("pedestal_sensors",   PedestalSensor,    "iot",  None,                    False),
        ("snmp_config",        SnmpConfig,        "iot",  None,                    True),
        ("external_api_config", ExternalApiConfig, "iot", None,                    True),
        ("pilot_assignments",  PilotAssignment,   "iot",  None,                    False),
        ("smtp_config",        SmtpConfig,        "user", None,                    True),
        ("billing_config",     BillingConfig,     "user", None,                    True),
        ("contract_templates", ContractTemplate,  "user", ("title",),             True),
        ("berths",             Berth,             "user", ("name",),              True),
    ]


def _json_safe(v):
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    return v


def _dump_rows(session, model, redact):
    cols = [c.name for c in sa_inspect(model).columns]
    rows = []
    for row in session.query(model).all():
        d = {}
        for name in cols:
            val = getattr(row, name)
            if redact and name in SECRET_COLS and val:
                val = REDACTED
            d[name] = _json_safe(val)
        rows.append(d)
    return rows


def export_config(include_secrets: bool = False) -> dict:
    """Build the config bundle from both databases."""
    redact = not include_secrets
    iot = SessionLocal()
    user = UserSessionLocal()
    try:
        config = {}
        for key, model, db, _nk, _r in _sections():
            sess = iot if db == "iot" else user
            try:
                config[key] = _dump_rows(sess, model, redact)
            except Exception as e:  # a missing table shouldn't sink the whole export
                logger.warning("config export: section %s failed: %s", key, e)
                config[key] = []
    finally:
        iot.close()
        user.close()

    env_safe = {k: getattr(settings, k, None) for k in _ENV_SAFE_KEYS}
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "include_secrets": include_secrets,
        "env_safe": env_safe,
        "config": config,
    }


def write_backup(bundle: dict) -> Path:
    """Persist a bundle to data/backups/ with a timestamped name. Atomic write."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    suffix = "full" if bundle.get("include_secrets") else "redacted"
    path = BACKUP_DIR / f"cloud_iot_config_{ts}_{suffix}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    logger.info("Config backup written: %s", path.name)
    return path


def list_backups() -> list:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(BACKUP_DIR.glob("cloud_iot_config_*.json"), reverse=True):
        st = p.stat()
        out.append({
            "filename": p.name,
            "size_bytes": st.st_size,
            "modified": datetime.utcfromtimestamp(st.st_mtime).isoformat() + "Z",
        })
    return out


def _settable_columns(model):
    """Columns we restore: skip PK, created_at and DateTime types (runtime, not
    operator config), keep the rest."""
    out = []
    for c in sa_inspect(model).columns:
        if c.primary_key or c.name == "created_at" or isinstance(c.type, DateTime):
            continue
        out.append(c.name)
    return out


def import_config(bundle: dict) -> dict:
    """Restore config from a bundle. Upsert by natural key; never insert raw PKs.

    Returns a per-section report {section: {updated, inserted, skipped}}.
    """
    if not isinstance(bundle, dict) or "config" not in bundle:
        raise ValueError("Invalid config bundle (missing 'config')")
    cfg = bundle.get("config", {})
    report = {}
    iot = SessionLocal()
    user = UserSessionLocal()
    try:
        for key, model, db, nk, restorable in _sections():
            if not restorable or key not in cfg:
                continue
            sess = iot if db == "iot" else user
            cols = _settable_columns(model)
            res = {"updated": 0, "inserted": 0, "skipped": 0}
            for row in cfg.get(key) or []:
                try:
                    target = None
                    if nk is None:  # singleton
                        target = sess.query(model).first()
                    else:
                        q = sess.query(model)
                        ok = True
                        for f in nk:
                            if row.get(f) is None:
                                ok = False
                                break
                            q = q.filter(getattr(model, f) == row[f])
                        target = q.first() if ok else None
                        if not ok:
                            res["skipped"] += 1
                            continue
                    inserting = target is None
                    if inserting:
                        target = model()
                        sess.add(target)
                    for col in cols:
                        if col not in row:
                            continue
                        val = row[col]
                        if col in SECRET_COLS and val == REDACTED:
                            continue  # preserve existing real secret
                        setattr(target, col, val)
                    # A redacted external-API key must not leave the gateway
                    # "active" with no real key behind it.
                    if key == "external_api_config" and row.get("api_key") == REDACTED:
                        if hasattr(target, "active"):
                            target.active = 0
                        if hasattr(target, "verified"):
                            target.verified = 0
                    res["inserted" if inserting else "updated"] += 1
                except Exception as e:
                    logger.warning("restore %s row failed: %s", key, e)
                    res["skipped"] += 1
            report[key] = res
        iot.commit()
        user.commit()
    except Exception:
        iot.rollback()
        user.rollback()
        raise
    finally:
        iot.close()
        user.close()

    # Refresh runtime caches that mirror restored config.
    try:
        from .webhook_service import invalidate_cache
        invalidate_cache()
    except Exception:
        pass
    return report
