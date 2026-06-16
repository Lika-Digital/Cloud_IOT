"""ERP session webhook delivery (v3.26).

Fire-and-forget POSTs to settings.erp_webhook_url on session lifecycle events
(socket activated, ~60 s telemetry, session ended). The payload matches the
GET /api/nfc/session/{id} structure plus an `event` field.

Design guarantees (per spec):
  * No-op when ERP_WEBHOOK_URL is not configured.
  * Failures are logged and NEVER propagate — webhook delivery must not affect
    session state, MQTT handling, or operator control.
  * Telemetry is throttled to once per ~60 s per session.

Usage from an async MQTT handler (db still open):
    payload = erp_webhook.build(db, session, "session_activated")
    if payload is not None:
        asyncio.create_task(erp_webhook.post_erp_event(payload))
"""
import logging
import time

from ..config import settings

logger = logging.getLogger(__name__)

_TELEMETRY_THROTTLE_S = 60.0
_last_telemetry_sent: dict[int, float] = {}   # session_id -> monotonic ts
_ended_sent: set[int] = set()                 # session_ids whose "ended" already fired


def build(db, session, event: str) -> dict | None:
    """Synchronously build the webhook payload (reads DBs). Returns None when no
    webhook is configured so the caller can skip scheduling a task."""
    if not settings.erp_webhook_url:
        return None
    from ..auth.user_database import UserSessionLocal
    from . import nfc_service
    udb = UserSessionLocal()
    try:
        payload = nfc_service.build_session_payload(db, udb, session)
    finally:
        udb.close()
    payload["event"] = event
    return payload


async def post_erp_event(payload: dict | None) -> None:
    """POST the payload to the ERP webhook. Never raises."""
    url = settings.erp_webhook_url
    if not url or payload is None:
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                url, json=payload,
                headers={"X-API-Key": settings.erp_api_key or "", "Content-Type": "application/json"},
            )
    except Exception as e:
        logger.warning("ERP webhook delivery failed (event=%s, session=%s): %s",
                       payload.get("event"), payload.get("session_id"), e)


def should_send_telemetry(session_id: int) -> bool:
    """True if >= 60 s since the last telemetry webhook for this session."""
    if session_id is None:
        return False
    now = time.monotonic()
    last = _last_telemetry_sent.get(session_id)
    if last is None or (now - last) >= _TELEMETRY_THROTTLE_S:
        _last_telemetry_sent[session_id] = now
        return True
    return False


def mark_ended(session_id: int) -> bool:
    """Return True only the first time a session's 'ended' webhook should fire;
    de-dupes the several end paths (SessionEnded MQTT, unplug, operator/ERP stop)."""
    if session_id is None or session_id in _ended_sent:
        return False
    _ended_sent.add(session_id)
    _last_telemetry_sent.pop(session_id, None)
    return True
