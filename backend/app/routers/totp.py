"""TOTP 2FA setup + partial-token second-factor login completion (v3.19).

TOTP setup/verify/disable are ADMIN ONLY (D3). 2FA is MANDATORY (D1): /login
(in auth.py) never returns a JWT — it returns a 5-min partial token and the
caller completes a second factor here, via either:
  - /totp/login  (authenticator code), or
  - /otp/request → /otp/login  (email/log OTP fallback, always available).
The legacy /verify-otp (email+code) stays in auth.py for back-compat (D4).
Lockout (5 fails → 15 min) is shared by both paths and always-on (D6).
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from ..auth.user_database import get_user_db
from ..auth.models import User
from ..auth.password import verify_password
from ..auth.tokens import create_access_token, decode_partial_token
from ..auth.otp_service import generate_otp, verify_otp
from ..auth.email_service import send_otp_email, smtp_is_configured
from ..auth import totp_service
from ..auth.dependencies import require_admin, require_any_role
from ..auth.schemas import (
    TotpSetupResponse, TotpCodeRequest, TotpDisableRequest, TotpStatusResponse,
    PartialTokenCodeRequest, OtpRequestRequest, OtpRequestResponse, TokenResponse,
)
from ..ratelimit import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["totp"])

_LOCKED_MSG = "Too many failed attempts — account temporarily locked for 15 minutes"


def _user_from_partial(token: str, db: Session) -> User:
    payload = decode_partial_token(token)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired session — please log in again")
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return user


def _send_otp(db: Session, user: User) -> str:
    """Generate + deliver an OTP. Returns the delivery method ('email'|'log')."""
    code = generate_otp(db, user.id)
    send_otp_email(user.email, code)   # emails if SMTP configured, else logs/prints
    return "email" if smtp_is_configured() else "log"


# ── TOTP setup (admin only) ───────────────────────────────────────────────────

@router.post("/totp/setup", response_model=TotpSetupResponse)
def totp_setup(user: User = Depends(require_admin), db: Session = Depends(get_user_db)):
    """Generate a new secret + QR. Does NOT enable TOTP until verify-setup."""
    secret = totp_service.generate_secret()
    user.totp_secret = secret
    user.totp_enabled = False
    db.commit()
    uri = totp_service.provisioning_uri(secret, user.email)
    return TotpSetupResponse(
        qr_code=totp_service.qr_png_base64(uri), secret=secret, provisioning_uri=uri,
    )


@router.post("/totp/verify-setup", response_model=TotpStatusResponse)
def totp_verify_setup(body: TotpCodeRequest,
                      user: User = Depends(require_admin),
                      db: Session = Depends(get_user_db)):
    """Confirm the scanned secret with a live code; enable TOTP on success."""
    if not user.totp_secret or not totp_service.verify_code(user.totp_secret, body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid code — check that your phone clock is set to automatic",
        )
    user.totp_enabled = True
    user.totp_verified_at = datetime.utcnow()
    totp_service.reset_failures(db, user)
    db.commit()
    return TotpStatusResponse(totp_enabled=True, totp_verified_at=user.totp_verified_at)


@router.post("/totp/disable", response_model=TotpStatusResponse)
def totp_disable(body: TotpDisableRequest,
                 user: User = Depends(require_admin),
                 db: Session = Depends(get_user_db)):
    """Require BOTH current password AND a valid TOTP code to disable + clear secret."""
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password incorrect")
    if not user.totp_enabled or not totp_service.verify_code(user.totp_secret, body.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid TOTP code")
    user.totp_enabled = False
    user.totp_secret = None
    user.totp_verified_at = None
    totp_service.reset_failures(db, user)
    db.commit()
    return TotpStatusResponse(totp_enabled=False, totp_verified_at=None)


@router.get("/totp/status", response_model=TotpStatusResponse)
def totp_status(user: User = Depends(require_any_role)):
    return TotpStatusResponse(totp_enabled=bool(user.totp_enabled), totp_verified_at=user.totp_verified_at)


# ── Second-factor login completion (partial token) ───────────────────────────

@router.post("/totp/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def totp_login(request: Request, body: PartialTokenCodeRequest, db: Session = Depends(get_user_db)):
    user = _user_from_partial(body.partial_token, db)
    if totp_service.is_locked(user):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_LOCKED_MSG)
    if not user.totp_enabled or not totp_service.verify_code(user.totp_secret, body.code):
        totp_service.record_failure(db, user)
        if totp_service.is_locked(user):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_LOCKED_MSG)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authenticator code")
    totp_service.reset_failures(db, user)
    return TokenResponse(access_token=create_access_token(user.id, user.email, user.role),
                         role=user.role, email=user.email)


@router.post("/otp/request", response_model=OtpRequestResponse)
@limiter.limit("5/minute")
def otp_request(request: Request, body: OtpRequestRequest, db: Session = Depends(get_user_db)):
    """Send an OTP fallback code (requires a valid partial token — prevents abuse)."""
    user = _user_from_partial(body.partial_token, db)
    if totp_service.is_locked(user):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_LOCKED_MSG)
    method = _send_otp(db, user)
    return OtpRequestResponse(otp_sent=True, method=method)


@router.post("/otp/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def otp_login(request: Request, body: PartialTokenCodeRequest, db: Session = Depends(get_user_db)):
    user = _user_from_partial(body.partial_token, db)
    if totp_service.is_locked(user):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_LOCKED_MSG)
    if not verify_otp(db, user.id, body.code):
        totp_service.record_failure(db, user)
        if totp_service.is_locked(user):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=_LOCKED_MSG)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired backup code")
    totp_service.reset_failures(db, user)
    return TokenResponse(access_token=create_access_token(user.id, user.email, user.role),
                         role=user.role, email=user.email)
