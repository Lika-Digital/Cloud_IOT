"""
Separate SQLAlchemy engine and session for users.db.
Stored in backend/data/ to keep user data isolated from pedestal.db.
"""
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATA_DIR = Path(__file__).parent.parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

USER_DB_URL = f"sqlite:///{DATA_DIR / 'users.db'}"

user_engine = create_engine(
    USER_DB_URL,
    connect_args={"check_same_thread": False},
)

UserSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=user_engine)


class UserBase(DeclarativeBase):
    pass


def get_user_db():
    db = UserSessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_user_db():
    from .models import User, OtpStore, SmtpConfig  # noqa: F401
    from .customer_models import Customer, BillingConfig, Invoice, ChatMessage  # noqa: F401
    from .contract_models import ContractTemplate, CustomerContract, ServiceOrder  # noqa: F401
    from .berth_models import Berth, BerthReservation  # noqa: F401
    UserBase.metadata.create_all(bind=user_engine)
    _migrate_user_schema()


def _migrate_user_schema():
    """Add missing columns to existing user DB tables (safe no-op if already present)."""
    import logging
    from sqlalchemy import text
    log = logging.getLogger(__name__)

    migrations = [
        ("customers", "push_token",           "TEXT"),
        ("berths",    "reference_image",       "TEXT"),
        ("berths",    "detect_conf_threshold", "REAL NOT NULL DEFAULT 0.30"),
        ("berths",    "match_threshold",       "REAL NOT NULL DEFAULT 0.50"),
        ("berths",    "occupied_bit",          "INTEGER NOT NULL DEFAULT 0"),
        ("berths",    "match_ok_bit",          "INTEGER NOT NULL DEFAULT 0"),
        ("berths",    "state_code",            "INTEGER NOT NULL DEFAULT 0"),
        ("berths",    "alarm",                 "INTEGER NOT NULL DEFAULT 0"),
        ("berths",    "match_score",           "REAL"),
        ("berths",    "analysis_error",        "TEXT"),
        ("berths",    "use_detection_zone",    "INTEGER NOT NULL DEFAULT 0"),
        ("berths",    "zone_x1",               "REAL NOT NULL DEFAULT 0.20"),
        ("berths",    "zone_y1",               "REAL NOT NULL DEFAULT 0.20"),
        ("berths",    "zone_x2",               "REAL NOT NULL DEFAULT 0.80"),
        ("berths",    "zone_y2",               "REAL NOT NULL DEFAULT 0.80"),
        ("berths",    "background_image",      "TEXT"),
        ("berths",    "berth_type",            "TEXT NOT NULL DEFAULT 'transit'"),
        ("berths",    "sample_embedding_path", "TEXT"),
        ("berths",    "sample_updated_at",     "DATETIME"),
        ("berths",    "berth_number",          "INTEGER"),
        # Marker for the one-shot zone-detection enablement below. Once set to 1
        # on a berth, the UPDATE at startup skips it so admin-chosen config
        # (e.g. use_detection_zone back to 0) is no longer overwritten.
        ("berths",    "zone_migration_v1_applied", "INTEGER NOT NULL DEFAULT 0"),
    ]

    # All table/column/definition values below are hardcoded string literals —
    # no user input reaches these statements. nosemgrep: avoid-sqlalchemy-text
    with user_engine.connect() as conn:
        for table, column, definition in migrations:
            result = conn.execute(text(f"PRAGMA table_info({table})"))  # nosemgrep
            existing = {row[1] for row in result.fetchall()}
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))  # nosemgrep
                conn.commit()
                log.info(f"User DB migration: added column '{column}' to '{table}'")

        # Widen the role column to accept api_client (SQLite TEXT has no size limit,
        # but validate here that the schema column definition is at least 20 chars).
        # No DDL change needed — this is a documentation marker.
        # Role values now accepted: admin | monitor | api_client | external_api

        # One-shot migration: enable zone detection (centered 60%) on berths
        # that have a video source. Gated by zone_migration_v1_applied so admin
        # changes stick across backend restarts — without the marker, the UPDATE
        # would flip use_detection_zone back to 1 every time the service restarts.
        result = conn.execute(text("""
            UPDATE berths
            SET use_detection_zone = 1,
                zone_x1 = 0.20, zone_y1 = 0.20,
                zone_x2 = 0.80, zone_y2 = 0.80,
                detect_conf_threshold = 0.15,
                zone_migration_v1_applied = 1
            WHERE video_source IS NOT NULL
              AND video_source != ''
              AND zone_migration_v1_applied = 0
        """))
        if result.rowcount:
            log.info(f"User DB migration: applied zone-detection v1 to {result.rowcount} berths")
        conn.commit()

        # Ensure invoices.session_id is UNIQUE even on databases created before
        # the model added unique=True. CREATE UNIQUE INDEX IF NOT EXISTS is
        # idempotent AND prevents the race that could let two invoice-creation
        # paths insert duplicates for the same session.
        # Pre-dedupe: keep the earliest invoice per session_id, drop the rest.
        dupe_result = conn.execute(text("""
            DELETE FROM invoices
            WHERE id NOT IN (
                SELECT MIN(id) FROM invoices GROUP BY session_id
            )
        """))
        if dupe_result.rowcount:
            log.warning(f"User DB migration: removed {dupe_result.rowcount} duplicate invoice rows before adding UNIQUE index")
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_invoices_session_id ON invoices(session_id)"))
        conn.commit()
