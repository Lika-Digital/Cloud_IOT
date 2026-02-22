"""Customer authentication: register, login, profile."""
from fastapi import APIRouter, Depends, HTTPException, status
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
def login(body: LoginRequest, user_db: DBSession = Depends(get_user_db)):
    customer = user_db.query(Customer).filter(Customer.email == body.email).first()
    if not customer or not verify_password(body.password, customer.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not customer.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account inactive")
    token = create_customer_token(customer.id, customer.email)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=CustomerProfileResponse)
def get_me(customer: Customer = Depends(require_customer)):
    return customer
