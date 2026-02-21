"""OTP generation, storage, and verification."""
import random
import string
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from .models import OtpStore
from ..config import settings


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_otp(db: Session, user_id: int) -> str:
    """Generate a 6-digit OTP, persist it, and return the code."""
    # Remove any existing OTPs for this user
    db.query(OtpStore).filter(OtpStore.user_id == user_id).delete()

    code = "".join(random.choices(string.digits, k=6))
    expires_at = _utcnow() + timedelta(minutes=settings.otp_expire_minutes)
    otp = OtpStore(user_id=user_id, code=code, expires_at=expires_at)
    db.add(otp)
    db.commit()
    return code


def verify_otp(db: Session, user_id: int, code: str) -> bool:
    """Return True and delete the OTP if valid; False otherwise."""
    otp = (
        db.query(OtpStore)
        .filter(OtpStore.user_id == user_id, OtpStore.code == code)
        .first()
    )
    if not otp:
        return False
    if otp.expires_at < _utcnow():
        db.delete(otp)
        db.commit()
        return False
    db.delete(otp)
    db.commit()
    return True
