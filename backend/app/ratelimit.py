"""Rate-limit primitives used by auth endpoints.

We use slowapi because it integrates cleanly with FastAPI's dependency system.
The limiter keys requests by the real client IP, honouring X-Forwarded-For when
the app sits behind nginx/Cloudflare. Install once in main.py via:

    from .ratelimit import limiter, rate_limit_exceeded_handler
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

Then decorate the endpoint:

    @router.post("/login")
    @limiter.limit("10/minute")
    def login(request: Request, body: LoginRequest, ...): ...

The Request argument MUST be present on the decorated function, otherwise
slowapi cannot extract the client IP.
"""
from __future__ import annotations

import os
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse


def _client_ip(request: Request) -> str:
    """Use X-Forwarded-For when behind nginx/Cloudflare, else direct remote."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # XFF is a comma-separated list; the leftmost entry is the client.
        return xff.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(key_func=_client_ip, default_limits=[])

# Tests and dev loops hammer auth endpoints rapidly; enabling the limiter
# globally would spuriously fail those. We disable it unless explicitly turned
# on (RATE_LIMIT_ENABLED=true) OR we detect a production environment. Pytest
# and local dev default to disabled — production turns it on via .env.
_enabled_env = os.environ.get("RATE_LIMIT_ENABLED", "").lower()
_app_env     = os.environ.get("APP_ENV", "").lower()
limiter.enabled = _enabled_env in ("1", "true", "yes") or _app_env == "production"


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return 429 with a clear, non-leaky message."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests. Please wait a minute and try again.",
        },
    )
