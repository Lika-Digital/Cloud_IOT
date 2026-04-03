"""FastAPI dependency functions for authentication and role checks."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .user_database import get_user_db
from .models import User
from .tokens import decode_token

bearer_scheme = HTTPBearer()

# Operator roles (admin User records in users.db) — never "customer" or "external_api"
_OPERATOR_ROLES = {"admin", "monitor"}


def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_user_db),
) -> User:
    token = credentials.credentials
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # SECURITY: reject non-operator JWTs (customer, external_api) before DB lookup.
    # Without this check, a customer JWT with sub=1 could match admin User id=1
    # when both DBs share the same ID space (confirmed real break, found by GAP-6 test).
    token_role = payload.get("role", "")
    if token_role not in _OPERATOR_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operator access required",
        )

    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_any_role(user: User = Depends(_get_current_user)) -> User:
    """Any authenticated operator (admin or monitor)."""
    return user


def require_admin(user: User = Depends(_get_current_user)) -> User:
    """Admin role only."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
