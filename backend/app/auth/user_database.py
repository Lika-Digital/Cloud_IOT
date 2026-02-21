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
    UserBase.metadata.create_all(bind=user_engine)
