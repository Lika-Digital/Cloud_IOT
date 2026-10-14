"""FastAPI dependency functions for authentication and role checks."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .user_database import get_user_db
from .models import User
from .tokens import decode_token

bearer_scheme = HTTPBearer()

# Operator roles (admin User records in users.db) — never "customer" or "external_api"
# v3.34 — monitor_control is a middle tier: it can control/configure every section
# EXCEPT the three admin-only sections (System Health, Settings, API Gateway).
# v3.35 — monitor_control_api was monitor_control PLUS the API Gateway configurator.
# D14 (owner, 2026-10-01; built 2026-10-14): the configurator is admin only — ERP integration
# is installation work, not operations. monitor_control_api now acts exactly like
# monitor_control; the role is kept so existing accounts keep working.
_OPERATOR_ROLES = {"admin", "monitor", "monitor_control", "monitor_control_api"}

# Roles allowed to act (control/configure) in the non-admin sections.
_CONTROL_ROLES = {"admin", "monitor_control", "monitor_control_api"}


class OperatorAuthError(Exception):
    """Why a token does not identify an operator. Carries the HTTP answer for the HTTP path."""

    def __init__(self, status_code: int, detail: str, headers: dict | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


def operator_from_token(token: str, db: Session) -> tuple[User, dict]:
    """THE identity check for every channel to data — HTTP routes and /ws alike (rule 13).

    Extracted 2026-10-12 so the WebSocket uses this function rather than a copy of it: /ws had
    no check at all while every HTTP route had this one, which is how an anonymous client came
    to receive the whole telemetry stream. Returns (user, payload); raises OperatorAuthError.

    A pre-2FA token (role "totp_pending") and customer/external tokens fail the role check, so
    "authenticated" here always means a full, second-factor operator login.
    """
    payload = decode_token(token)
    if not payload:
        raise OperatorAuthError(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token",
                                {"WWW-Authenticate": "Bearer"})

    # SECURITY: reject non-operator JWTs (customer, external_api) before DB lookup.
    # Without this check, a customer JWT with sub=1 could match admin User id=1
    # when both DBs share the same ID space (confirmed real break, found by GAP-6 test).
    token_role = payload.get("role", "")
    if token_role not in _OPERATOR_ROLES:
        raise OperatorAuthError(status.HTTP_403_FORBIDDEN, "Operator access required")

    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise OperatorAuthError(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user, payload


def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_user_db),
) -> User:
    try:
        user, _payload = operator_from_token(credentials.credentials, db)
    except OperatorAuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail, headers=e.headers)
    return user


def require_any_role(user: User = Depends(_get_current_user)) -> User:
    """Any authenticated operator (admin, monitor_control, or monitor).

    Use for READ endpoints in the non-admin sections — every operator may view
    them. Monitor is read-only; writes must use require_control / require_admin.
    """
    return user


def require_control(user: User = Depends(_get_current_user)) -> User:
    """Admin or monitor_control — OPERATIONS: acting within an installation that exists.

    v3.34 — gates the write/control endpoints outside System Health, Settings and
    API Gateway (e.g. session controls, breaker reset, thresholds, LED, billing
    config, contracts, berths). Monitor is rejected here.

    **The principle, so the next such decision has a rule and not a list to copy (v3.43).**

      * `require_control` = **operations**. Allow, deny, stop, reset, set a price. Daily work
        inside an installation that already exists and is not being changed.
      * `require_admin` = **installation acts**, as well as the admin-only sections. Anything
        that changes what the hardware *is*: which socket a physical NFC tag energises, which
        printed QR codes are valid, whether a cabinet obeys the NUC at all. These are done
        once, by someone standing at the cabinet.

    NFC/QR used to be listed here and are not any more: re-pointing a physical token is an
    installation act. The old entry is worth remembering as a cautionary tale — the list said
    "NFC/QR", `nfc.py`'s docstring said `require_admin`, and the frontend said
    `const isAdmin = canControl(role)`. Three signals reading as admin-only while the code
    admitted marina staff, which is precisely how it went unnoticed. `test_roles.py`
    TC-ROLE-07 now scans the route table for installation-act paths gated here, so the next
    one fails a test rather than waiting to be read.
    """
    if user.role not in _CONTROL_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Control access required (admin or monitor_control)",
        )
    return user


def require_admin(user: User = Depends(_get_current_user)) -> User:
    """Admin role only — System Health, Settings, user management."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user

