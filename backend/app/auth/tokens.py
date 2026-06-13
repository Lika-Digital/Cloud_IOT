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


def create_partial_token(user_id: int, email: str) -> str:
    """v3.19 — short-lived (5 min) pre-2FA token issued after a correct password.

    Role 'totp_pending' is NOT an operator role, so `_get_current_user` rejects
    it: a partial token cannot reach any protected endpoint. It only authorizes
    the second-factor completion endpoints (/totp/login, /otp/request, /otp/login).
    """
    expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": "totp_pending",
        "totp_pending": True,
        "exp": expires,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_partial_token(token: str) -> Optional[dict]:
    """Return the payload only if it is a valid, unexpired partial token."""
    payload = decode_token(token)
    if not payload or payload.get("role") != "totp_pending" or not payload.get("totp_pending"):
        return None
    return payload


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
