"""v3.10 — Daily LED on/off scheduler.

A background asyncio task ticks every 60 seconds. For each enabled
`LedSchedule` row it:

1. Converts current UTC to the configured marina-local time
   (`settings.marina_timezone`).
2. Skips the row if today's weekday is not in `days_of_week`.
3. Checks whether the current minute matches `on_time` or `off_time` —
   OR within a 5-minute grace window after the configured time, in case
   the backend was just restarted and missed the exact tick (D7).
4. Dedups via `_led_schedule_last_fired[pedestal_id][slot] = "YYYY-MM-DD HH:MM"`
   so the same fire never publishes twice.
5. Publishes `opta/cmd/led` and broadcasts a `led_changed` WebSocket event
   (D8) so the dashboard reflects the state in real time.

The dedup dict lives in memory only. After a backend restart it is empty —
the firmware's 16-entry msgId idempotency cache absorbs any duplicate
within the same minute (D5 design decision).

Tests call `tick_once(db, now_utc)` directly with a mocked time; the
infinite loop in `run_scheduler` is only exercised in production.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

# Module-level dedup. Key: pedestal_id. Value: dict with optional `on` and
# `off` slots, each holding "YYYY-MM-DD HH:MM" of the last fire for that slot.
_led_schedule_last_fired: dict[int, dict[str, str]] = {}

_TICK_SECONDS = 60
_GRACE_MINUTES = 5  # v3.10 D7 — fire if missed within this window


def _resolve_tz(name: str):
    """Return a tzinfo for the configured zone, falling back to stdlib UTC if
    `tzdata` is missing or the key is unknown. Never raises."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, Exception):
        try:
            return ZoneInfo("UTC")
        except Exception:
            # tzdata not installed at all — use the bare stdlib UTC alias.
            return timezone.utc


def _marina_now() -> datetime:
    """Return current time in the configured marina timezone (naive)."""
    from ..config import settings
    tz = _resolve_tz(settings.marina_timezone)
    # Compute aware UTC now → convert → strip tzinfo so HH:MM comparisons
    # against the operator's "20:00" string are direct.
    return datetime.now(timezone.utc).astimezone(tz).replace(tzinfo=None)


def _parse_days(days_str: str | None) -> set[int]:
    """Parse the comma-separated days string into a set of ints. Returns
    every day on parse failure so the schedule is permissive rather than
    silently dead."""
    if not days_str:
        return {0, 1, 2, 3, 4, 5, 6}
    out: set[int] = set()
    for tok in days_str.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            n = int(tok)
            if 0 <= n <= 6:
                out.add(n)
        except ValueError:
            continue
    return out or {0, 1, 2, 3, 4, 5, 6}


def _hhmm_to_minutes(hhmm: str) -> int | None:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


def _slot_key(now_local: datetime) -> str:
    """Stable key for dedup — `YYYY-MM-DD HH:MM` of the local-time fire."""
    return now_local.strftime("%Y-%m-%d %H:%M")


def _should_fire(
    schedule_time_minutes: int,
    now_local: datetime,
) -> bool:
    """True if `now_local` is at or up to GRACE minutes after the schedule
    time. The exact-minute case is the steady-state path; the grace window
    catches a backend restart that missed the tick."""
    now_minutes = now_local.hour * 60 + now_local.minute
    delta = now_minutes - schedule_time_minutes
    return 0 <= delta <= _GRACE_MINUTES


async def _publish_led(
    pedestal_id: int,
    cabinet_id: str,
    color: str,
    state: str,
    source: str,
) -> None:
    """Shared LED publish + broadcast. Used by the scheduler AND by the
    manual `setLed` endpoint for consistency (D8). Source is "scheduler"
    or "manual" so the dashboard can label the event."""
    from .mqtt_client import mqtt_service
    from .websocket_manager import ws_manager

    msg_id = str(int(datetime.utcnow().timestamp() * 1000))
    payload = json.dumps({"cabinetId": cabinet_id, "color": color, "state": state})
    if cabinet_id:
        mqtt_service.publish("opta/cmd/led", payload)
    else:
        mqtt_service.publish(
            f"pedestal/{pedestal_id}/cmd/led",
            json.dumps({"color": color, "state": state, "msgId": msg_id}),
        )

    await ws_manager.broadcast({
        "event": "led_changed",
        "data": {
            "pedestal_id": pedestal_id,
            "cabinet_id": cabinet_id,
            "color": color,
            "state": state,
            "source": source,
            "timestamp": datetime.utcnow().isoformat(),
        },
    })


async def tick_once(db, now_utc: datetime | None = None) -> int:
    """Run a single scheduler tick. Returns the number of LED commands
    published. Pure-Python and side-effect-free except for MQTT publish +
    WS broadcast — safe to call from tests with a mocked `now_utc`."""
    from ..models.led_schedule import LedSchedule
    from ..models.pedestal_config import PedestalConfig

    if now_utc is None:
        now_local = _marina_now()
    else:
        # Caller supplied UTC — convert to marina-local using the same path.
        from ..config import settings
        tz = _resolve_tz(settings.marina_timezone)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        now_local = now_utc.astimezone(tz).replace(tzinfo=None)

    today_dow = now_local.weekday()  # Mon=0 .. Sun=6
    fire_count = 0

    rows = db.query(LedSchedule).filter(LedSchedule.enabled.is_(True)).all()
    for s in rows:
        days = _parse_days(s.days_of_week)
        if today_dow not in days:
            continue

        on_min = _hhmm_to_minutes(s.on_time)
        off_min = _hhmm_to_minutes(s.off_time)
        if on_min is None or off_min is None:
            logger.warning("[LedScheduler] pedestal=%d invalid HH:MM (on=%s, off=%s) — skipping",
                           s.pedestal_id, s.on_time, s.off_time)
            continue

        cfg = db.query(PedestalConfig).filter(PedestalConfig.pedestal_id == s.pedestal_id).first()
        cabinet_id = getattr(cfg, "opta_client_id", None) if cfg else None

        for slot, sched_min, state in (("on", on_min, "on"), ("off", off_min, "off")):
            if not _should_fire(sched_min, now_local):
                continue
            # Build the "this fire window" key — the LOCAL date + scheduled
            # HH:MM. Dedups across ticks within the grace window AND across
            # days (so yesterday's "on" doesn't suppress today's).
            key = f"{now_local.strftime('%Y-%m-%d')} {s.on_time if slot == 'on' else s.off_time}"
            last = _led_schedule_last_fired.setdefault(s.pedestal_id, {})
            if last.get(slot) == key:
                continue  # already fired this window
            try:
                await _publish_led(
                    pedestal_id=s.pedestal_id,
                    cabinet_id=cabinet_id or "",
                    color=s.color,
                    state=state,
                    source="scheduler",
                )
                last[slot] = key
                fire_count += 1
                logger.info(
                    "[LedScheduler] pedestal=%d cabinet=%s scheduled=%s action=%s color=%s",
                    s.pedestal_id, cabinet_id, s.on_time if slot == "on" else s.off_time,
                    state, s.color,
                )
            except Exception as exc:
                logger.warning("[LedScheduler] publish failed pedestal=%d slot=%s: %s",
                               s.pedestal_id, slot, exc)
                try:
                    from .error_log_service import log_warning
                    log_warning(
                        "system", "led_scheduler",
                        f"LED schedule {slot} fire failed for pedestal {s.pedestal_id}: {exc}",
                    )
                except Exception:
                    pass

    return fire_count


async def run_scheduler() -> None:
    """Lifespan task — ticks every 60 seconds forever."""
    from ..database import SessionLocal

    # Wait briefly for DB + MQTT to be ready before the first tick.
    await asyncio.sleep(15)
    while True:
        db = SessionLocal()
        try:
            await tick_once(db)
        except Exception as exc:
            logger.warning("[LedScheduler] tick failed: %s", exc)
        finally:
            db.close()
        await asyncio.sleep(_TICK_SECONDS)
