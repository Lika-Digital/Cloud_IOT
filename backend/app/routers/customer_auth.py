"""Customer authentication: register, login, profile."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession
from ..auth.user_database import get_user_db
from ..auth.customer_models import Customer
from ..auth.customer_dependencies import require_customer
from ..auth.tokens import create_customer_token
from ..auth.password import hash_password, verify_password
from ..schemas.customer import RegisterRequest, LoginRequest, TokenResponse, CustomerProfileResponse

router = APIRouter(prefix="/api/customer/auth", tags=["customer-auth"])


@router.post("/register", response_model=TokenResponse)
def register(body: RegisterRequest, user_db: DBSession = Depends(get_user_db)):
    existing = user_db.query(Customer).filter(Customer.email == body.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    customer = Customer(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
        vat_number=body.vat_number,
        ship_name=body.ship_name,
        ship_registration=body.ship_registration,
        is_active=1,
    )
    user_db.add(customer)
    user_db.commit()
    user_db.refresh(customer)
    token = create_customer_token(customer.id, customer.email)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
def login(request: Request, body: LoginRequest, user_db: DBSession = Depends(get_user_db)):
    from ..services.security_monitor import record_login_failure, record_login_success, check_brute_force
    from ..services.error_log_service import log_warning, log_error
    from ..services.alarm_service import trigger_alarm

    client_ip = request.client.host if request.client else "unknown"

    customer = user_db.query(Customer).filter(Customer.email == body.email).first()
    if not customer or not verify_password(body.password, customer.password_hash):
        record_login_failure(client_ip)
        try:
            log_warning(
                "security", "customer_auth/login",
                f"Failed customer login for '{body.email}' from {client_ip}",
            )
            if check_brute_force(client_ip):
                log_error(
                    "security", "customer_auth/login",
                    f"Brute-force detected: {client_ip} exceeded 5 failures in 5 min",
                    details=f"target={body.email}",
                )
                trigger_alarm(
                    alarm_type="security",
                    source="sensor_auto",
                    message=f"Brute-force customer login detected from IP {client_ip}",
                    details=f"target={body.email}",
                    deduplicate=False,
                )
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not customer.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account inactive")

    record_login_success(client_ip)
    token = create_customer_token(customer.id, customer.email)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=CustomerProfileResponse)
def get_me(customer: Customer = Depends(require_customer)):
    return customer


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    ship_name: Optional[str] = None


class PushTokenRequest(BaseModel):
    token: str


@router.patch("/profile", response_model=CustomerProfileResponse)
def update_profile(
    body: ProfileUpdate,
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    if body.name is not None:
        customer.name = body.name
    if body.ship_name is not None:
        customer.ship_name = body.ship_name
    user_db.add(customer)
    user_db.commit()
    user_db.refresh(customer)
    return customer


@router.post("/push-token")
def save_push_token(
    body: PushTokenRequest,
    user_db: DBSession = Depends(get_user_db),
    customer: Customer = Depends(require_customer),
):
    customer.push_token = body.token
    user_db.add(customer)
    user_db.commit()
    return {"ok": True}
