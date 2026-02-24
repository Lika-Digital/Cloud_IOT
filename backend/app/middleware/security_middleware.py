"""
SecurityMiddleware — observe-only Starlette middleware.

Scans every request / response for:
  1. SQL injection / XSS patterns in URL query strings
  2. Structurally malformed JWT tokens in Authorization header
  3. HTTP 403 Forbidden responses (monitor role hitting admin endpoints)

All findings are logged to error_log_service with category='security'.
The middleware NEVER blocks or modifies requests.
"""
import re
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..services.security_monitor import SQL_INJECTION_PATTERNS
from ..services.error_log_service import log_warning, log_error

# Paths where 403 is expected / noise (skip logging these)
_SKIP_403_PATHS = {"/ws"}

# Minimum token segment length — avoids logging test/empty tokens
_MIN_TOKEN_LEN = 20


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # ── 1. SQL injection / XSS in query string ────────────────────────────
        query_string = request.url.query
        if query_string:
            for pattern in SQL_INJECTION_PATTERNS:
                if pattern.search(query_string):
                    try:
                        log_error(
                            "security", "middleware",
                            f"Suspicious query string from {client_ip} on {path}",
                            details=f"query={query_string[:300]}",
                        )
                    except Exception:
                        pass
                    break  # one entry per request

        # ── 2. Malformed JWT ──────────────────────────────────────────────────
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if len(token) >= _MIN_TOKEN_LEN and not _valid_jwt_structure(token):
                try:
                    log_warning(
                        "security", "middleware",
                        f"Malformed JWT from {client_ip} on {path}",
                        details=f"token_prefix={token[:20]}...",
                    )
                except Exception:
                    pass

        response = await call_next(request)

        # ── 3. Unauthorised access (403) ──────────────────────────────────────
        if response.status_code == 403 and path not in _SKIP_403_PATHS:
            try:
                log_warning(
                    "security", "middleware",
                    f"Unauthorised access (403) from {client_ip} — {request.method} {path}",
                )
            except Exception:
                pass

        # ── 4. Security response headers ──────────────────────────────────────
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response


_B64URL_RE = re.compile(r"^[A-Za-z0-9_\-]+=*$")


def _valid_jwt_structure(token: str) -> bool:
    """A well-formed JWT has exactly 3 base64url segments separated by dots."""
    parts = token.split(".")
    if len(parts) != 3:
        return False
    return all(_B64URL_RE.match(p) for p in parts if p)
