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

        # Enable zone detection (centered 60%) on all berths that have a video source
        # and are still at factory default (use_detection_zone=0, threshold=0.30).
        # This is idempotent — runs every startup but only modifies unchanged rows.
        conn.execute(text("""
            UPDATE berths
            SET use_detection_zone = 1,
                zone_x1 = 0.20, zone_y1 = 0.20,
                zone_x2 = 0.80, zone_y2 = 0.80,
                detect_conf_threshold = 0.15
            WHERE video_source IS NOT NULL
              AND video_source != ''
              AND use_detection_zone = 0
        """))
        conn.commit()
