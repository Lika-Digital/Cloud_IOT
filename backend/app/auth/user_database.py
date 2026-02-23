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
    from .models import User, OtpStore  # noqa: F401
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
        ("customers", "push_token", "TEXT"),
    ]

    with user_engine.connect() as conn:
        for table, column, definition in migrations:
            result = conn.execute(text(f"PRAGMA table_info({table})"))
            existing = {row[1] for row in result.fetchall()}
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
                conn.commit()
                log.info(f"User DB migration: added column '{column}' to '{table}'")
