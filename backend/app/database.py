from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
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
    from .models import pedestal, session, sensor_reading  # noqa: F401
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
        ("pedestals", "camera_ip",   "TEXT"),
        ("pedestals", "initialized", "INTEGER NOT NULL DEFAULT 0"),
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
