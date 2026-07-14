import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request

logger = logging.getLogger(__name__)
from sqlalchemy.orm import Session

from ..auth.user_database import get_user_db
from ..auth.models import User
from ..auth.password import hash_password, verify_password
from ..auth.tokens import create_access_token, create_partial_token, decode_partial_token
from ..auth.dependencies import require_admin, require_any_role, _get_current_user
from ..auth.schemas import (
    LoginRequest,
    LoginResponse,
    FirstPasswordRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
    ChangePasswordRequest,
    RegisterRequest,
    UserPatch,
)
from ..config import settings
from ..ratelimit import limiter

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/service-token", response_model=TokenResponse)
def service_token(request: Request, body: LoginRequest, db: Session = Depends(get_user_db)):
    """
    Direct JWT login for api_client service accounts — skips OTP.

    Only accounts with role='api_client' are accepted here. Human operator
    accounts (admin / monitor) must use the two-step /login + TOTP flow.

    ERP auth outcomes are written to the security log (category "security",
    source "ext-api/auth") so "who connected / who tried" is visible in the
    dashboard and queryable, not just in the uvicorn access log.
    """
    from ..services.error_log_service import log_info, log_warning
    xff = request.headers.get("x-forwarded-for")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "unknown")

    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        log_warning("security", "ext-api/auth",
                    f"Failed ERP service-token attempt for '{body.email}' (src {ip})",
                    details="invalid email or password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        log_warning("security", "ext-api/auth",
                    f"ERP service-token denied for disabled account '{body.email}' (src {ip})")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    if user.role != "api_client":
        log_warning("security", "ext-api/auth",
                    f"Non-ERP account '{body.email}' (role={user.role}) attempted service-token (src {ip})")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is only for api_client service accounts",
        )
    token = create_access_token(user.id, user.email, user.role)
    log_info("security", "ext-api/auth",
             f"ERP service account '{user.email}' authenticated (src {ip})")
    return TokenResponse(access_token=token, role=user.role, email=user.email)


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_user_db)):
    """Step 1: validate credentials, return a partial token + next-step flags.

    v3.33 — TOTP is the ONLY second factor (email OTP removed). 2FA is mandatory:
    this never returns a JWT. The caller then completes, in order: a forced
    password change if required, then TOTP (enroll on first login, else enter the
    authenticator code) — see /first-password, /totp/enroll, /totp/login."""
    from ..services.security_monitor import record_login_failure, record_login_success, check_brute_force
    from ..services.error_log_service import log_warning, log_error
    from ..services.alarm_service import trigger_alarm

    client_ip = request.client.host if request.client else "unknown"

    user = db.query(User).filter(User.email == body.email).first()
    if not user or not verify_password(body.password, user.password_hash):
        record_login_failure(client_ip)
        try:
            log_warning(
                "security", "auth/login",
                f"Failed operator login for '{body.email}' from {client_ip}",
            )
            if check_brute_force(client_ip):
                log_error(
                    "security", "auth/login",
                    f"Brute-force detected: {client_ip} exceeded 5 failures in 5 min",
                    details=f"target={body.email}",
                )
                trigger_alarm(
                    alarm_type="security",
                    source="sensor_auto",
                    message=f"Brute-force login detected from IP {client_ip}",
                    details=f"target={body.email}",
                    deduplicate=False,
                )
        except Exception as _sec_exc:
            logger.warning("Security monitor failed during login attempt from %s: %s", client_ip, _sec_exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    record_login_success(client_ip)

    # 2FA is MANDATORY: never return a JWT here. Issue a 5-min partial token and
    # tell the caller what the first-login still needs.
    partial = create_partial_token(user.id, user.email)
    return LoginResponse(
        partial_token=partial,
        must_change_password=bool(user.must_change_password),
        totp_enabled=bool(user.totp_enabled),
    )


def _user_from_partial(token: str, db: Session) -> User:
    """Resolve the user behind a 5-min partial token (the only authorization a
    half-logged-in caller has before completing 2FA)."""
    payload = decode_partial_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session — please log in again",
        )
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")
    return user


@router.post("/first-password")
@limiter.limit("10/minute")
def first_password(request: Request, body: FirstPasswordRequest, db: Session = Depends(get_user_db)):
    """v3.33 — first-login forced password change (authorized by the partial
    token from /login). Sets the new password, clears the flag, and returns the
    next-step flag so the caller proceeds to TOTP. Still no JWT — 2FA follows."""
    user = _user_from_partial(body.partial_token, db)
    if not user.must_change_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Password change is not required for this account")
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="New password must be different from the temporary one")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
    return {"ok": True, "totp_enabled": bool(user.totp_enabled)}


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("3/hour")
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_user_db)):
    """Public self-registration. Creates a monitor-role account; admin can promote later.

    Gated by ALLOW_SELF_REGISTRATION — off by default so production deployments
    do not expose the dashboard to anyone reaching the public URL. Flip the flag
    in .env only if you want open sign-up (dev / admin-invite flows).
    """
    if not settings.allow_self_registration:
        # 404 not 403: do not advertise the route exists at all to callers.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role="monitor",
        is_active=True,
    )
    db.add(user)
    db.commit()
    return {"message": "Account created. You can now sign in."}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(require_any_role)):
    return current_user


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(require_any_role),
    db: Session = Depends(get_user_db),
):
    if not verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password incorrect")
    current_user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"message": "Password updated"}


# ── Admin-only user management ────────────────────────────────────────────────

@router.get("/users", response_model=list[UserResponse])
def list_users(
    _: User = Depends(require_admin),
    db: Session = Depends(get_user_db),
):
    return db.query(User).all()


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_user_db),
):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if body.role not in ("admin", "monitor_control", "monitor", "api_client"):
        raise HTTPException(
            status_code=400,
            detail="Role must be 'admin', 'monitor_control', 'monitor' or 'api_client'",
        )
    # api_client = ERP service account: it authenticates via /api/auth/service-token
    # with this admin-set password and never uses the operator login, so the forced
    # password change + TOTP enrolment (which apply to human operators) do not apply.
    is_erp = body.role == "api_client"
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        # v3.33 — the admin sets a temporary password; human operators must replace
        # it and enrol an authenticator on first login. ERP accounts skip this.
        must_change_password=not is_erp,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/reset-2fa", response_model=UserResponse)
def reset_2fa(
    user_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_user_db),
):
    """v3.33 — admin recovery: clear a user's TOTP so they re-enrol on next
    login (the only second factor is the authenticator, so this is how a
    lost-device lockout is recovered). The password is left unchanged."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.totp_secret = None
    user.totp_enabled = False
    user.totp_verified_at = None
    user.totp_failed_attempts = 0
    user.totp_locked_until = None
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserResponse)
def patch_user(
    user_id: int,
    body: UserPatch,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_user_db),
):
    """Partially update a user: role and/or is_active. Admin only."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        if user.id == current_user.id and not body.is_active:
            raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
        user.is_active = body.is_active
    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_user_db),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"message": "User deleted"}
