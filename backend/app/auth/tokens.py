"""JWT access token creation and validation."""
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from ..config import settings


def create_access_token(user_id: int, email: str, role: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_customer_token(customer_id: int, email: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=30)
    payload = {
        "sub": str(customer_id),
        "email": email,
        "role": "customer",
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def create_websocket_token(session_id: int, customer_id: int) -> str:
    """Short-lived JWT issued by `/api/mobile/qr/claim` (v3.6).

    Scoped to a single session — the `/ws` handler reads `session_id` from
    the payload and subscribes the connection to `broadcast_to_session(session_id, ...)`.
    Role `ws_session` is distinct from the long-lived `customer` role so
    these tokens cannot be used against any other authenticated endpoint.
    Re-claiming the same QR rotates the token (new `jti`, new expiry).
    """
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    payload = {
        "sub": str(customer_id),
        "session_id": session_id,
        "role": "ws_session",
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
