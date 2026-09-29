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


def optional_customer(
    token: str = Depends(oauth2_scheme),
    user_db: DBSession = Depends(get_user_db),
) -> Customer | None:
    """The customer principal when one is presented, otherwise None.

    This exists for the NFC endpoints, which serve two callers over the same routes: the ERP
    server-to-server (X-API-Key only) and the mobile app. The app already sends
    `Authorization: Bearer <customer JWT>` on **every** request — its axios interceptor adds it
    unconditionally (`mobile/src/api/client.ts:19-20`) — and the backend has simply been
    ignoring it, trusting a `user_id` in the request body instead. So the correct principal was
    already on the wire; this is what reads it.

    A missing token returns None. A token that is **present but invalid** raises 401 rather
    than returning None: silently downgrading a bad token to "anonymous" would mean an expired
    session quietly loses its ownership checks, which is the opposite of what this is for.
    """
    if not token:
        return None
    return require_customer(token=token, user_db=user_db)
