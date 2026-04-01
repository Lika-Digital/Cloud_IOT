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
