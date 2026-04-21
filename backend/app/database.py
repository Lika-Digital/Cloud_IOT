from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
    pool_pre_ping=True,   # verify connection is alive before use; auto-recycles stale ones
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from .models import pedestal, session, sensor_reading, error_log, active_alarm  # noqa: F401
    from .models import pedestal_config  # noqa: F401
    from .models import external_api  # noqa: F401
    from .models import session_audit  # noqa: F401
    from .models import socket_config  # noqa: F401
    from .models import auto_activation_log  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _migrate_schema()


def _migrate_schema():
    """
    Apply any missing column additions to an existing database.
    Uses SQLite PRAGMA to detect missing columns, then ALTER TABLE to add them.
    This is safe to run on every startup — it's a no-op if columns already exist.
    """
    import logging
    log = logging.getLogger(__name__)

    # (table, column, definition)
    migrations = [
        ("pedestals", "camera_ip",      "TEXT"),
        ("pedestals", "initialized",    "INTEGER NOT NULL DEFAULT 0"),
        ("pedestals", "mobile_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("pedestals", "ai_enabled",     "INTEGER NOT NULL DEFAULT 0"),
        ("sessions",  "customer_id", "INTEGER"),
        ("sessions",  "deny_reason", "TEXT"),
        # v3.6 — QR claim timestamp (nullable). NULL for unclaimed sessions
        # AND for sessions started directly from the mobile app; populated
        # only when a customer claims a previously-unowned auto-activated
        # session via QR scan.
        ("sessions",  "owner_claimed_at", "DATETIME"),
        # pedestal_configs columns (table created by metadata, but ALTER handles existing DBs)
        ("pedestal_configs", "site_id",           "TEXT"),
        ("pedestal_configs", "dock_id",           "TEXT"),
        ("pedestal_configs", "berth_ref",         "TEXT"),
        ("pedestal_configs", "pedestal_uid",      "TEXT"),
        ("pedestal_configs", "pedestal_model",    "TEXT"),
        ("pedestal_configs", "mqtt_username",     "TEXT"),
        ("pedestal_configs", "mqtt_password",     "TEXT"),
        ("pedestal_configs", "opta_client_id",    "TEXT"),
        ("pedestal_configs", "camera_stream_url", "TEXT"),
        ("pedestal_configs", "camera_fqdn",       "TEXT"),
        ("pedestal_configs", "camera_username",   "TEXT"),
        ("pedestal_configs", "camera_password",   "TEXT"),
        ("pedestal_configs", "sensor_config_mode","TEXT DEFAULT 'auto'"),
        ("pedestal_configs", "mdns_discovered",   "TEXT"),
        ("pedestal_configs", "snmp_discovered",   "TEXT"),
        ("pedestal_configs", "opta_connected",    "INTEGER DEFAULT 0"),
        ("pedestal_configs", "last_heartbeat",    "DATETIME"),
        ("pedestal_configs", "camera_reachable",  "INTEGER DEFAULT 0"),
        ("pedestal_configs", "last_camera_check", "DATETIME"),
        ("pedestal_configs", "updated_at",           "DATETIME"),
        ("pedestal_configs", "temp_sensor_ip",       "TEXT"),
        ("pedestal_configs", "temp_sensor_port",     "INTEGER DEFAULT 80"),
        ("pedestal_configs", "temp_sensor_protocol", "TEXT DEFAULT 'http'"),
        ("pedestal_configs", "temp_sensor_reachable","INTEGER DEFAULT 0"),
        ("pedestal_configs", "last_temp_sensor_check","DATETIME"),
        # v3.5 — door state persisted for the auto-activate precondition check.
        ("pedestal_configs", "door_state",         "TEXT DEFAULT 'unknown'"),
        # v3.7 — MQTT-driven auto-discovery. first_seen_at is stamped once on
        # first contact; status reflects the backend's view of the opta link.
        ("pedestal_configs", "first_seen_at",      "DATETIME"),
        ("pedestal_configs", "status",             "TEXT DEFAULT 'online'"),
        # external_api_config columns (table created by metadata; ALTER handles existing DBs)
        ("external_api_config", "api_key",              "TEXT"),
        ("external_api_config", "allowed_endpoints",    "TEXT DEFAULT '[]'"),
        ("external_api_config", "webhook_url",          "TEXT"),
        ("external_api_config", "allowed_events",       "TEXT DEFAULT '[]'"),
        ("external_api_config", "active",               "INTEGER DEFAULT 0"),
        ("external_api_config", "verified",             "INTEGER DEFAULT 0"),
        ("external_api_config", "last_verified_at",     "DATETIME"),
        ("external_api_config", "verification_results", "TEXT"),
        ("external_api_config", "created_at",           "DATETIME"),
        ("external_api_config", "updated_at",           "DATETIME"),
        # Operator approval flow columns on socket_states
        ("socket_states", "operator_status",    "TEXT"),
        ("socket_states", "operator_status_at", "DATETIME"),
    ]

    with engine.connect() as conn:
        for table, column, definition in migrations:
            result = conn.execute(
                __import__("sqlalchemy").text(f"PRAGMA table_info({table})")
            )
            existing_columns = {row[1] for row in result.fetchall()}
            if column not in existing_columns:
                conn.execute(
                    __import__("sqlalchemy").text(
                        f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                    )
                )
                conn.commit()
                log.info(f"DB migration: added column '{column}' to '{table}'")

        # Partial unique index: only ONE session in pending|active may exist
        # per (pedestal_id, socket_id, type). SQLite treats NULL as distinct in
        # unique constraints, so legacy water rows with socket_id=NULL are not
        # affected; but any future water session will have socket_id=1|2 and
        # the index blocks firmware-retry duplicates.
        from sqlalchemy import text
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_session_one_active_per_socket "
            "ON sessions(pedestal_id, socket_id, type) "
            "WHERE status IN ('pending', 'active')"
        ))
        conn.commit()

    _backfill_session_totals(log)


# Sanity bounds so a firmware glitch (e.g. garbage packet reading 9999 kWh)
# cannot be adopted as truth by the backfill. A single-session upper bound is
# what we protect against, not a legitimate long-running session.
_MAX_SANE_KWH_PER_SESSION = 1000.0   # 3.5 kW × 286 h; real sessions never hit this.
_MAX_SANE_LITERS_PER_SESSION = 10000.0


def _backfill_session_totals(log, db_engine=None):
    """
    Recompute energy_kwh / water_liters for completed sessions that report 0
    but have non-zero sensor readings. Fixes rows written before the
    session_service.complete() max() correction. Idempotent — only touches
    sessions where the current value is 0/NULL and readings prove otherwise.

    Out-of-bound readings (> _MAX_SANE_*) are excluded from the MAX() so a
    single corrupt packet cannot blow up a real session's total.

    db_engine override is for tests that need to target an isolated engine.
    """
    from sqlalchemy import text
    target = db_engine if db_engine is not None else engine
    # Bound params — the numeric upper bound is treated as data, not SQL, so
    # semgrep's avoid-sqlalchemy-text rule is happy and we're injection-proof.
    fix_kwh = text("""
        UPDATE sessions
        SET energy_kwh = (
            SELECT MAX(value) FROM sensor_readings
            WHERE sensor_readings.session_id = sessions.id
              AND sensor_readings.type = 'kwh_total'
              AND sensor_readings.value < :max_kwh
        )
        WHERE status = 'completed' AND type = 'electricity'
          AND (energy_kwh IS NULL OR energy_kwh = 0)
          AND EXISTS (
            SELECT 1 FROM sensor_readings
            WHERE sensor_readings.session_id = sessions.id
              AND sensor_readings.type = 'kwh_total'
              AND sensor_readings.value > 0
              AND sensor_readings.value < :max_kwh
          )
    """)
    fix_water = text("""
        UPDATE sessions
        SET water_liters = (
            SELECT MAX(value) FROM sensor_readings
            WHERE sensor_readings.session_id = sessions.id
              AND sensor_readings.type = 'total_liters'
              AND sensor_readings.value < :max_liters
        )
        WHERE status = 'completed' AND type = 'water'
          AND (water_liters IS NULL OR water_liters = 0)
          AND EXISTS (
            SELECT 1 FROM sensor_readings
            WHERE sensor_readings.session_id = sessions.id
              AND sensor_readings.type = 'total_liters'
              AND sensor_readings.value > 0
              AND sensor_readings.value < :max_liters
          )
    """)
    with target.connect() as conn:
        kwh_rows = conn.execute(fix_kwh, {"max_kwh": _MAX_SANE_KWH_PER_SESSION}).rowcount
        water_rows = conn.execute(fix_water, {"max_liters": _MAX_SANE_LITERS_PER_SESSION}).rowcount
        conn.commit()
        if kwh_rows or water_rows:
            log.info(f"Backfilled session totals: {kwh_rows} electricity, {water_rows} water sessions")
