"""Webhook dispatcher for the External API Gateway push model.

Called via ws_manager broadcast hook on every broadcast event.
Uses a 30-second config cache to avoid a DB hit per event.
"""
import json
import logging
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_config_cache: dict | None = None
_cache_ts: float = 0
_CACHE_TTL = 30.0


def _load_config() -> dict | None:
    """Load external API config from DB, cached for 30 s."""
    global _config_cache, _cache_ts
    now = time.monotonic()
    if _config_cache is not None and (now - _cache_ts) < _CACHE_TTL:
        return _config_cache

    try:
        from ..database import SessionLocal
        from ..models.external_api import ExternalApiConfig
        db = SessionLocal()
        try:
            cfg = db.get(ExternalApiConfig, 1)
            if cfg is None:
                _config_cache = None
            else:
                _config_cache = {
                    "active":         bool(cfg.active),
                    "webhook_url":    cfg.webhook_url,
                    "allowed_events": json.loads(cfg.allowed_events or "[]"),
                    "api_key":        cfg.api_key,
                }
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"webhook_service: failed to load config: {e}")
        _config_cache = None

    _cache_ts = now
    return _config_cache


def invalidate_cache() -> None:
    """Force next dispatch to reload config from DB."""
    global _config_cache, _cache_ts
    _config_cache = None
    _cache_ts = 0


async def dispatch_webhook(message: dict) -> None:
    """Fire-and-forget webhook dispatcher — called via ws_manager broadcast hook."""
    try:
        cfg = _load_config()
        if not cfg:
            return
        if not cfg.get("active"):
            return

        webhook_url = cfg.get("webhook_url")
        if not webhook_url:
            return

        event_id = message.get("event", "")
        if event_id not in cfg.get("allowed_events", []):
            return

        import httpx
        api_key = cfg.get("api_key") or ""
        payload = {
            "event":     event_id,
            "data":      message.get("data", {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                webhook_url,
                json=payload,
                headers={
                    "X-API-Key":    api_key,
                    "Content-Type": "application/json",
                },
            )
    except Exception as e:
        logger.warning(f"Webhook dispatch failed: {e}")
