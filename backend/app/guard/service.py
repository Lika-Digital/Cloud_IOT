"""
Guard service (step 5) — the MQTT contract, worker liveness, and persistence.

**The backend is the only database writer.** The worker publishes; everything here
subscribes and persists. The worker is the only writer of files under the recordings path,
and this module only ever reads them.

MQTT contract. `{M}` is `settings.marina_id` (explicit, never derived); `{cam}` is the
camera id.

| Topic | Direction | Retained | Purpose |
|---|---|---|---|
| `marina/{M}/camera/{cam}/guard/cmd` | backend → worker | **no** | arm / disarm / rearm + config |
| `marina/{M}/camera/{cam}/guard/ack` | worker → backend | no | command accepted, with resulting state |
| `marina/{M}/camera/{cam}/guard/state` | worker → backend | **yes** | last known state + flags |
| `marina/{M}/camera/{cam}/guard/health` | worker → backend | no | 5 s heartbeat: cpu/mem/disk/visibility |
| `marina/{M}/camera/{cam}/guard/alarm` | worker → backend | no | one alarm |
| `marina/{M}/camera/{cam}/guard/detection` | worker → backend | no | batched detections, incl. below-threshold |
| `marina/{M}/camera/{cam}/guard/recording` | worker → backend | no | an assembled clip |
| `marina/{M}/camera/{cam}/guard/retention` | worker → backend | no | files deleted, with reasons |

Retain is used on **`state` only**, and that choice is the v3.40 lesson applied: retained
state lets a restarting backend learn the last known value, but retained is NEVER treated as
liveness. `cmd` is deliberately NOT retained — a replayed command would arm a restarting
worker with nobody having asked, which is exactly the shape of the bug v3.40 fixed.

A false ARMED is prevented three independent ways:
  1. the worker sets a Last Will on `state`, so the broker publishes UNAVAILABLE if it dies;
  2. a heartbeat gap beyond `guard_heartbeat_timeout_s` marks it unavailable regardless of
     what retained state says;
  3. `worker_seen_at` is **in-memory and deliberately not persisted**, so a stale retained
     ARMED cannot survive a backend restart as truth.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session as DBSession

from ..config import settings
from ..time_utils import iso_z, now_iso
from .models import (
    BAND_ALARM,
    STATE_ARMED,
    STATE_ARMING,
    STATE_OFF,
    STATE_SUSPENDED_CPU,
    STATE_UNAVAILABLE,
    GuardConfig,
    GuardDetection,
    GuardEvent,
    GuardRecording,
)

logger = logging.getLogger(__name__)

CMD_ARM = "arm"
CMD_DISARM = "disarm"
CMD_REARM = "rearm"


# ─── topics ──────────────────────────────────────────────────────────────────

def topic_base(camera_id: int) -> str:
    return f"marina/{settings.marina_id}/camera/{camera_id}/guard"


def topic_cmd(camera_id: int) -> str:
    return f"{topic_base(camera_id)}/cmd"


def subscription_patterns() -> list[str]:
    """Worker → backend topics, for `mqtt_client.TOPICS`.

    `cmd` is deliberately absent: the backend publishes it and must not consume its own
    commands, or a restart would re-process them.
    """
    m = settings.marina_id
    return [
        f"marina/{m}/camera/+/guard/ack",
        f"marina/{m}/camera/+/guard/state",
        f"marina/{m}/camera/+/guard/health",
        f"marina/{m}/camera/+/guard/alarm",
        f"marina/{m}/camera/+/guard/detection",
        f"marina/{m}/camera/+/guard/recording",
        f"marina/{m}/camera/+/guard/retention",
    ]


def parse_topic(topic: str) -> tuple[int, str] | None:
    """`marina/{M}/camera/{cam}/guard/{leaf}` → (camera_id, leaf). None if not ours."""
    parts = topic.split("/")
    if len(parts) != 6 or parts[0] != "marina" or parts[2] != "camera" or parts[4] != "guard":
        return None
    if parts[1] != settings.marina_id:
        return None
    try:
        return int(parts[3]), parts[5]
    except ValueError:
        return None


# ─── in-memory liveness (deliberately NOT persisted) ─────────────────────────

class WorkerLiveness:
    """Tracks whether each camera's worker is actually answering.

    Not persisted, on purpose. If `worker_seen_at` survived a restart, a retained ARMED from
    a worker that died hours ago would be rendered as ARMED — the exact false-liveness bug
    v3.40 fixed for cabinets. After a backend restart every worker is unknown until it
    speaks.
    """

    def __init__(self) -> None:
        self._seen: dict[int, float] = {}
        self._reported_state: dict[int, dict] = {}
        self._pending_acks: dict[str, tuple[int, float]] = {}   # req_id -> (cam, sent_at)

    def mark_seen(self, camera_id: int, now: float | None = None) -> None:
        self._seen[camera_id] = now if now is not None else time.time()

    def seen_at(self, camera_id: int) -> float | None:
        return self._seen.get(camera_id)

    def is_alive(self, camera_id: int, now: float | None = None) -> bool:
        seen = self._seen.get(camera_id)
        if seen is None:
            return False
        now = now if now is not None else time.time()
        return (now - seen) <= settings.guard_heartbeat_timeout_s

    def set_reported(self, camera_id: int, payload: dict) -> None:
        self._reported_state[camera_id] = payload

    def reported(self, camera_id: int) -> dict:
        return self._reported_state.get(camera_id, {})

    def expect_ack(self, req_id: str, camera_id: int, now: float | None = None) -> None:
        self._pending_acks[req_id] = (camera_id, now if now is not None else time.time())

    def ack_received(self, req_id: str) -> None:
        self._pending_acks.pop(req_id, None)

    def overdue_acks(self, now: float | None = None) -> list[tuple[str, int]]:
        now = now if now is not None else time.time()
        return [
            (rid, cam) for rid, (cam, sent) in self._pending_acks.items()
            if now - sent > settings.guard_ack_timeout_s
        ]

    def forget(self, camera_id: int) -> None:
        self._seen.pop(camera_id, None)
        self._reported_state.pop(camera_id, None)


liveness = WorkerLiveness()


# ─── config row ──────────────────────────────────────────────────────────────

def get_or_create_config(db: DBSession, camera_id: int,
                         pedestal_id: int | None = None,
                         berth_id: int | None = None) -> GuardConfig:
    cfg = db.get(GuardConfig, camera_id)
    if cfg is None:
        cfg = GuardConfig(
            camera_id=camera_id,
            pedestal_id=pedestal_id if pedestal_id is not None else camera_id,
            berth_id=berth_id,
            desired_state=STATE_OFF,
        )
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def config_payload(cfg: GuardConfig) -> dict:
    """The detection settings the worker needs, as sent in every command."""
    return {
        "config_version": cfg.config_version,
        "conf_threshold": cfg.conf_threshold,
        "uncertain_min": cfg.uncertain_min,
        "fps": cfg.fps,
        "window_seconds": cfg.window_seconds,
        "frames_required": cfg.frames_required,
        "cooldown_seconds": cfg.cooldown_seconds,
        "zone": [cfg.zone_x1, cfg.zone_y1, cfg.zone_x2, cfg.zone_y2],
        "visibility_min_luma": cfg.visibility_min_luma,
        "visibility_min_variance": cfg.visibility_min_variance,
    }


def effective_state(db: DBSession, cfg: GuardConfig, now: float | None = None) -> dict:
    """What the operator should be shown — reconciling intent against reality.

    The rules that matter:
      * desired OFF -> OFF. Nothing else can contradict that.
      * desired ARMED but the worker is not answering -> **UNAVAILABLE**, never ARMED. This
        is the one guarantee the whole liveness design exists for.
      * otherwise the worker's own reported state wins, since it knows whether it is in
        ALARM or RECORDING.
    """
    now = now if now is not None else time.time()
    reported = liveness.reported(cfg.camera_id)
    alive = liveness.is_alive(cfg.camera_id, now)
    seen = liveness.seen_at(cfg.camera_id)

    if cfg.desired_state == STATE_OFF:
        state = STATE_OFF
        reason = None
    elif cfg.desired_state == STATE_SUSPENDED_CPU:
        state = STATE_SUSPENDED_CPU
        reason = cfg.suspended_reason
    elif not alive:
        state = STATE_UNAVAILABLE
        reason = (
            "the guard worker is not responding"
            + (f" (last seen {int(now - seen)}s ago)" if seen else " (never seen)")
        )
    else:
        state = reported.get("state") or STATE_ARMING
        reason = reported.get("reason")

    return {
        "camera_id": cfg.camera_id,
        "pedestal_id": cfg.pedestal_id,
        "berth_id": cfg.berth_id,
        "enabled": cfg.desired_state != STATE_OFF,
        "desired_state": cfg.desired_state,
        "state": state,
        "reason": reason,
        "flags": reported.get("flags", []),
        "config_version": cfg.config_version,
        "worker_config_version": reported.get("config_version"),
        "worker_alive": alive,
        "worker_seen_at": iso_z(datetime.utcfromtimestamp(seen)) if seen else None,
        "health": reported.get("health", {}),
    }


# ─── commands (backend → worker) ─────────────────────────────────────────────

def publish_command(db: DBSession, cfg: GuardConfig, cmd: str,
                    *, actor: str | None = None) -> str:
    """Publish arm/disarm/rearm and register the ack we expect. Returns the req_id."""
    from ..services.mqtt_client import mqtt_service

    req_id = str(uuid.uuid4())
    payload = {
        "cmd": cmd,
        "req_id": req_id,
        "camera_id": cfg.camera_id,
        "pedestal_id": cfg.pedestal_id,
        "config": config_payload(cfg),
        "actor": actor,
        "ts": now_iso(),
    }
    # NOT retained — see the module docstring.
    mqtt_service.publish(topic_cmd(cfg.camera_id), json.dumps(payload), qos=1)
    liveness.expect_ack(req_id, cfg.camera_id)
    logger.info("[Guard] cmd=%s camera=%d req_id=%s actor=%s config_version=%d",
                cmd, cfg.camera_id, req_id, actor, cfg.config_version)
    return req_id


# ─── inbound handlers (worker → backend). The ONLY DB writers. ───────────────

async def handle_guard_message(topic: str, payload: str, *, retained: bool = False) -> None:
    """Entry point from `mqtt_handlers.handle_message`."""
    parsed = parse_topic(topic)
    if parsed is None:
        return
    camera_id, leaf = parsed
    try:
        data = json.loads(payload) if payload.strip() else {}
    except json.JSONDecodeError as exc:
        logger.warning("[Guard] bad JSON on %s: %s", topic, exc)
        return

    handler = {
        "ack": _on_ack,
        "state": _on_state,
        "health": _on_health,
        "alarm": _on_alarm,
        "detection": _on_detection,
        "recording": _on_recording,
        "retention": _on_retention,
    }.get(leaf)
    if handler is None:
        return
    try:
        await handler(camera_id, data, retained)
    except Exception:
        logger.exception("[Guard] handler failed for %s", topic)


async def _on_ack(camera_id: int, data: dict, retained: bool) -> None:
    req_id = data.get("req_id", "")
    liveness.ack_received(req_id)
    liveness.mark_seen(camera_id)
    logger.info("[Guard] ack camera=%d req_id=%s accepted=%s state=%s",
                camera_id, req_id, data.get("accepted"), data.get("state"))
    await _broadcast_state(camera_id)


async def _on_state(camera_id: int, data: dict, retained: bool) -> None:
    """The worker's own state. Retained messages update LAST KNOWN, never liveness.

    A retained `state` is exactly the case that made a dead cabinet look online in v3.40, so
    it is recorded for display but `mark_seen` is not called — only live traffic proves the
    worker is there.
    """
    liveness.set_reported(camera_id, {
        "state": data.get("state"),
        "flags": data.get("flags", []),
        "reason": data.get("reason"),
        "config_version": data.get("config_version"),
        "health": liveness.reported(camera_id).get("health", {}),
    })
    if not retained:
        liveness.mark_seen(camera_id)
    else:
        logger.info("[Guard] camera=%d RETAINED state replay (%s) — not treated as liveness",
                    camera_id, data.get("state"))

    # A worker reporting SUSPENDED_CPU must survive a backend restart as suspended, never as
    # silently armed, so the fact is persisted on the config row.
    if data.get("state") == STATE_SUSPENDED_CPU and not retained:
        from ..database import SessionLocal
        db = SessionLocal()
        try:
            cfg = db.get(GuardConfig, camera_id)
            if cfg is not None and cfg.desired_state == STATE_ARMED:
                cfg.desired_state = STATE_SUSPENDED_CPU
                cfg.suspended_reason = data.get("reason") or "CPU limit exceeded"
                cfg.suspended_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
    await _broadcast_state(camera_id)


async def _on_health(camera_id: int, data: dict, retained: bool) -> None:
    if retained:
        return
    liveness.mark_seen(camera_id)
    current = liveness.reported(camera_id)
    current["health"] = data
    liveness.set_reported(camera_id, current)
    await _broadcast_state(camera_id, health_only=True)


async def _on_alarm(camera_id: int, data: dict, retained: bool) -> None:
    """Persist one alarm. Idempotent on `event_uuid` — MQTT QoS 1 is at-least-once."""
    from ..database import SessionLocal
    from ..services.websocket_manager import ws_manager

    event_uuid = data.get("event_uuid")
    if not event_uuid:
        logger.warning("[Guard] alarm without event_uuid on camera %d — ignored", camera_id)
        return

    liveness.mark_seen(camera_id)
    db = SessionLocal()
    try:
        existing = db.query(GuardEvent).filter(GuardEvent.event_uuid == event_uuid).first()
        if existing is not None:
            logger.info("[Guard] duplicate alarm %s ignored (at-least-once delivery)",
                        event_uuid)
            return
        ev = GuardEvent(
            event_uuid=event_uuid,
            camera_id=camera_id,
            pedestal_id=data.get("pedestal_id"),
            berth_id=data.get("berth_id"),
            detected_at_utc=_parse_dt(data.get("detected_at_utc")) or datetime.utcnow(),
            detected_at_local=data.get("detected_at_local"),
            confidence=float(data.get("confidence") or 0.0),
            px_height=data.get("px_height"),
            bbox=json.dumps(data.get("bbox")) if data.get("bbox") is not None else None,
            trigger=data.get("trigger"),
            limited_visibility=bool(data.get("limited_visibility")),
            frame_path=data.get("frame_path"),
            video_path=data.get("video_path"),
            video_skipped=bool(data.get("video_skipped")),
            video_skip_reason=data.get("video_skip_reason"),
        )
        db.add(ev)
        db.commit()
        db.refresh(ev)
        logger.warning("[Guard] ALARM camera=%d conf=%.2f px=%s video=%s uuid=%s",
                       camera_id, ev.confidence, ev.px_height,
                       ev.video_path or ("SKIPPED: " + (ev.video_skip_reason or "?")),
                       event_uuid)
        payload = _event_payload(ev)
    finally:
        db.close()

    await ws_manager.broadcast({"event": "guard_alarm", "data": payload})


async def _on_detection(camera_id: int, data: dict, retained: bool) -> None:
    """Batch-insert detections in ONE transaction.

    The worker batches every ~5 s precisely so per-frame inserts never contend with the
    marina's session writes.
    """
    from ..database import SessionLocal

    rows = data.get("detections") or []
    if not rows:
        return
    liveness.mark_seen(camera_id)
    db = SessionLocal()
    try:
        for r in rows:
            db.add(GuardDetection(
                camera_id=camera_id,
                detected_at=_parse_dt(r.get("ts")) or datetime.utcnow(),
                confidence=float(r.get("confidence") or 0.0),
                px_height=r.get("px_height"),
                bbox=json.dumps(r.get("bbox")) if r.get("bbox") is not None else None,
                band=r.get("band") or "uncertain",
                frame_path=r.get("frame_path"),
                limited_visibility=bool(r.get("limited_visibility")),
                event_uuid=r.get("event_uuid"),
            ))
        db.commit()
        logger.debug("[Guard] stored %d detection(s) for camera %d", len(rows), camera_id)
    finally:
        db.close()


async def _on_recording(camera_id: int, data: dict, retained: bool) -> None:
    from ..database import SessionLocal
    from ..services.websocket_manager import ws_manager

    file_path = data.get("file_path")
    if not file_path:
        return
    liveness.mark_seen(camera_id)
    db = SessionLocal()
    try:
        existing = db.query(GuardRecording).filter(
            GuardRecording.file_path == file_path).first()
        if existing is not None:
            return
        rec = GuardRecording(
            event_uuid=data.get("event_uuid"),
            camera_id=camera_id,
            started_at=_parse_dt(data.get("started_at")) or datetime.utcnow(),
            duration_s=data.get("duration_s"),
            file_path=file_path,
            file_size=data.get("file_size"),
            confidence=data.get("confidence"),
        )
        db.add(rec)
        # Link it onto the event so one read serves the dashboard row.
        if rec.event_uuid:
            ev = db.query(GuardEvent).filter(
                GuardEvent.event_uuid == rec.event_uuid).first()
            if ev is not None:
                ev.video_path = file_path
                ev.video_skipped = False
        db.commit()
        logger.info("[Guard] recording stored camera=%d %s (%s bytes)",
                    camera_id, file_path, data.get("file_size"))
    finally:
        db.close()
    await ws_manager.broadcast({
        "event": "guard_recording_ready",
        "data": {"camera_id": camera_id, "event_uuid": data.get("event_uuid"),
                 "file_path": file_path},
    })


async def _on_retention(camera_id: int, data: dict, retained: bool) -> None:
    """Mark deleted files and audit every one. Never silent — the operator has to know when
    training data is being lost."""
    from ..database import SessionLocal
    from ..services.error_log_service import log_warning
    from ..services.websocket_manager import ws_manager

    deleted = data.get("deleted") or []
    liveness.mark_seen(camera_id)
    if deleted:
        db = SessionLocal()
        try:
            for entry in deleted:
                path = entry.get("file_path")
                if not path:
                    continue
                rec = db.query(GuardRecording).filter(
                    GuardRecording.file_path == path).first()
                if rec is not None and rec.deleted_at is None:
                    rec.deleted_at = datetime.utcnow()
                    rec.delete_reason = entry.get("reason")
                log_warning(
                    "guard", "retention",
                    f"deleted {path} ({entry.get('reason')}, {entry.get('bytes')} bytes"
                    + (", LABELLED" if entry.get("labelled") else "") + ")",
                )
            db.commit()
        finally:
            db.close()

    await ws_manager.broadcast({
        "event": "guard_retention_state_changed",
        "data": {
            "camera_id": camera_id,
            "frames_evicting": data.get("frames_evicting", False),
            "frames_cap_exhausted": data.get("frames_cap_exhausted", False),
            "frames_gb_used": data.get("frames_gb_used"),
            "recordings_gb_used": data.get("recordings_gb_used"),
            "deleted_count": len(deleted),
            "labelled_evicted": data.get("labelled_evicted", 0),
        },
    })


# ─── helpers ─────────────────────────────────────────────────────────────────

def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    txt = value[:-1] if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(txt)
    except ValueError:
        return None


def _event_payload(ev: GuardEvent) -> dict:
    return {
        "id": ev.id,
        "event_uuid": ev.event_uuid,
        "camera_id": ev.camera_id,
        "pedestal_id": ev.pedestal_id,
        "berth_id": ev.berth_id,
        "detected_at_utc": iso_z(ev.detected_at_utc),
        "detected_at_local": ev.detected_at_local,
        "confidence": ev.confidence,
        "px_height": ev.px_height,
        "bbox": json.loads(ev.bbox) if ev.bbox else None,
        "trigger": ev.trigger,
        "limited_visibility": ev.limited_visibility,
        "has_frame": bool(ev.frame_path),
        "has_video": bool(ev.video_path),
        "video_skipped": ev.video_skipped,
        "video_skip_reason": ev.video_skip_reason,
        "label": ev.label,
        "label_note": ev.label_note,
        "labelled_at": iso_z(ev.labelled_at),
        "labelled_by": ev.labelled_by,
    }


async def _broadcast_state(camera_id: int, *, health_only: bool = False) -> None:
    from ..database import SessionLocal
    from ..services.websocket_manager import ws_manager

    db = SessionLocal()
    try:
        cfg = db.get(GuardConfig, camera_id)
        if cfg is None:
            return
        payload = effective_state(db, cfg)
    finally:
        db.close()
    # Two explicit literals rather than a ternary: `test_ws_event_catalog.py` scans for
    # `"event": "<literal>"` to prove every backend event has a frontend handler, and a
    # ternary hides the name from it. An event the drift guard cannot see is an event that
    # can drift.
    if health_only:
        await ws_manager.broadcast({"event": "guard_health", "data": payload})
    else:
        await ws_manager.broadcast({"event": "guard_state_changed", "data": payload})


async def check_overdue_acks() -> None:
    """Turn silence into "Guard unavailable" rather than a false ARMED.

    Called from the guard watchdog loop in main.py. The desired state is left alone: the
    operator asked for ARMED, so guard arms when the worker returns — what changes is only
    what the UI is told is true right now.
    """
    overdue = liveness.overdue_acks()
    for req_id, camera_id in overdue:
        liveness.ack_received(req_id)      # stop re-reporting the same one
        logger.warning(
            "[Guard] camera=%d did not acknowledge req_id=%s within %.0fs — reporting "
            "UNAVAILABLE (desired state unchanged)",
            camera_id, req_id, settings.guard_ack_timeout_s,
        )
        await _broadcast_state(camera_id)
