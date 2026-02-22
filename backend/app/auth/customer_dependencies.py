"""FastAPI dependency for customer JWT authentication."""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session as DBSession
from .tokens import decode_token
from .customer_models import Customer
from .user_database import get_user_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/customer/auth/login", auto_error=False)


def require_customer(
    token: str = Depends(oauth2_scheme),
    user_db: DBSession = Depends(get_user_db),
) -> Customer:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(token)
    if not payload or payload.get("role") != "customer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid customer token")
    customer_id = int(payload["sub"])
    customer = user_db.get(Customer, customer_id)
    if not customer or not customer.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Customer not found or inactive")
    return customer
