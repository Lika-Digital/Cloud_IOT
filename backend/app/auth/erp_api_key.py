"""X-API-Key authentication for the ERP / myMarina NFC integration (v3.26).

A static key (settings.erp_api_key, from ERP_API_KEY in .env) is sent by the ERP
on every /api/nfc/ request via the `X-API-Key` header. This is intentionally
SEPARATE from the JWT-based external-API gateway (role=external_api): the NFC
integration is a simple machine-to-machine key per the integration spec.

Behaviour:
  * key not configured on the server  -> 503 (feature disabled / not set up)
  * header missing or value mismatched -> 401
  * match -> returns the key
"""
import hmac

from fastapi import Header, HTTPException, status

from ..config import settings


async def require_erp_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> str:
    if not settings.erp_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ERP API not configured",
        )
    if not x_api_key or not hmac.compare_digest(settings.erp_api_key, x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return x_api_key
