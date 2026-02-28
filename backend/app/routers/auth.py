from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from ..auth.user_database import get_user_db
from ..auth.models import User
from ..auth.password import hash_password, verify_password
from ..auth.tokens import create_access_token
from ..auth.otp_service import generate_otp, verify_otp
from ..auth.email_service import send_otp_email
from ..auth.dependencies import require_admin, require_any_role, _get_current_user
from ..auth.schemas import (
    LoginRequest,
    VerifyOtpRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
    ChangePasswordRequest,
    RegisterRequest,
    UserPatch,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(request: Request, body: LoginRequest, db: Session = Depends(get_user_db)):
    """Step 1: validate credentials and send OTP to email."""
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
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")

    record_login_success(client_ip)
    code = generate_otp(db, user.id)
    send_otp_email(user.email, code)
    return {"message": "OTP sent to your email address"}


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp_endpoint(body: VerifyOtpRequest, db: Session = Depends(get_user_db)):
    """Step 2: verify OTP code and return JWT token."""
    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid request")

    if not verify_otp(db, user.id, body.code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired OTP code",
        )

    token = create_access_token(user.id, user.email, user.role)
    return TokenResponse(access_token=token, role=user.role, email=user.email)


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_user_db)):
    """Public self-registration. Creates a monitor-role account; admin can promote later."""
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
    if body.role not in ("admin", "monitor"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'monitor'")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
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
