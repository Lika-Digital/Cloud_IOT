"""TOTP (RFC 6238) two-factor service + shared 2FA lockout (v3.19).

Uses pyotp for codes and qrcode for the provisioning QR. Fully offline — no
external service, no network. The lockout state (totp_failed_attempts /
totp_locked_until on the User row) is shared by BOTH the TOTP and the
OTP-fallback login paths, and is ALWAYS-ON (every environment, not just prod).
"""
import base64
import io
from datetime import datetime, timedelta, timezone

import pyotp
import qrcode

ISSUER = "Marina IoT"
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def _utcnow() -> datetime:
    # Naive UTC to match the DateTime columns (same convention as otp_service).
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── TOTP primitives ──────────────────────────────────────────────────────────

def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, email: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def qr_png_base64(uri: str) -> str:
    """Return the provisioning QR as a base64-encoded PNG (no data: prefix)."""
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def verify_code(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code, tolerating ±1 time step (clock drift)."""
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:
        return False


# ── Shared 2FA lockout (TOTP + OTP fallback) ─────────────────────────────────

def is_locked(user) -> bool:
    return bool(user.totp_locked_until and user.totp_locked_until > _utcnow())


def lockout_remaining_seconds(user) -> int:
    if not is_locked(user):
        return 0
    return max(0, int((user.totp_locked_until - _utcnow()).total_seconds()))


def record_failure(db, user) -> None:
    """Count a failed second-factor attempt; lock for LOCKOUT_MINUTES at the cap."""
    user.totp_failed_attempts = (user.totp_failed_attempts or 0) + 1
    if user.totp_failed_attempts >= MAX_FAILED_ATTEMPTS:
        user.totp_locked_until = _utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
        user.totp_failed_attempts = 0   # counter reset; the lock window is the gate
    db.commit()


def reset_failures(db, user) -> None:
    """Clear attempt count + lock on a successful login."""
    if user.totp_failed_attempts or user.totp_locked_until:
        user.totp_failed_attempts = 0
        user.totp_locked_until = None
        db.commit()
