"""
Guard REST API (step 5) — the COMPLETE contract.

Step 6 (the guard admin screen) is cancelled and merges into UI v2, so this surface must
already carry everything a UI will need: the annotated frame, correct/false-alarm labelling,
the detections list, re-arm, and runtime config. Nothing here waits for a screen.

**Guard must be fully operable from a terminal.** Every endpoint is usable with curl alone —
that is the requirement for the watching week, and the exact commands are in
`docs/guard_operator_runbook.md`. If any of this needed a UI to be usable, step 5 would not
be finished.

Roles:
  * read        -> `require_any_role`  (a monitor watching the dashboard should see guard)
  * label       -> `require_any_role`  (the person spotting a gull is exactly who should mark it)
  * arm/disarm/rearm/config -> `require_control`
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from ..auth.dependencies import require_any_role, require_control
from ..auth.models import User
from ..config import settings
from ..database import get_db
from ..time_utils import iso_z
from . import service
from .models import (
    LABEL_CORRECT,
    LABEL_FALSE_ALARM,
    STATE_ARMED,
    STATE_ARMING,
    STATE_OFF,
    STATE_SUSPENDED_CPU,
    GuardConfig,
    GuardDetection,
    GuardEvent,
    GuardRecording,
)

router = APIRouter(prefix="/api/guard", tags=["guard"])


# ─── bodies ──────────────────────────────────────────────────────────────────

class LabelBody(BaseModel):
    """The operator's verdict on an alarm. This is the labelled dataset from day one."""
    label: str = Field(..., pattern=f"^({LABEL_CORRECT}|{LABEL_FALSE_ALARM})$")
    note: str | None = Field(None, max_length=2000)


class ConfigBody(BaseModel):
    """Runtime thresholds. Every field optional — PATCH semantics, so tuning one value
    during the watching week does not require restating the rest."""
    conf_threshold: float | None = Field(None, gt=0, le=1)
    uncertain_min: float | None = Field(None, gt=0, le=1)
    fps: float | None = Field(None, gt=0, le=10)
    window_seconds: float | None = Field(None, gt=0, le=60)
    frames_required: int | None = Field(None, ge=1, le=20)
    cooldown_seconds: float | None = Field(None, ge=0, le=3600)
    zone: list[float] | None = Field(None, min_length=4, max_length=4)
    visibility_min_luma: float | None = Field(None, ge=0, le=255)
    visibility_min_variance: float | None = Field(None, ge=0)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _cfg_or_404(db: DBSession, camera_id: int) -> GuardConfig:
    cfg = db.get(GuardConfig, camera_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"No guard configured for camera {camera_id}")
    return cfg


def _event_or_404(db: DBSession, event_id: int) -> GuardEvent:
    ev = db.get(GuardEvent, event_id)
    if ev is None:
        # 404 means "never existed" — deliberately distinct from the 410 below.
        raise HTTPException(status_code=404, detail=f"No guard event {event_id}")
    return ev


def _serve_file(path_str: str | None, media_type: str, kind: str,
                deleted_at=None, delete_reason=None) -> FileResponse:
    """Serve a worker-written file, distinguishing "gone" from "never existed".

    410 Gone rather than 404: the client learns this existed and retention took it, which is
    a different fact and is what lets the dashboard render "video expired" instead of a
    broken link. The ENOENT branch closes the window between the worker unlinking a file and
    its `retention` message arriving, and also covers out-of-band deletion.
    """
    if deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"reason": delete_reason or "deleted", "deleted_at": iso_z(deleted_at),
                    "kind": kind},
        )
    if not path_str:
        raise HTTPException(status_code=404, detail=f"No {kind} recorded for this event")
    path = Path(path_str)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"reason": "missing_on_disk", "kind": kind,
                    "hint": "the file is gone from disk; retention or an out-of-band "
                            "deletion removed it"},
        )
    return FileResponse(str(path), media_type=media_type, filename=path.name)


# ─── status ──────────────────────────────────────────────────────────────────

@router.get("/status")
def guard_status(db: DBSession = Depends(get_db), _: User = Depends(require_any_role)):
    """Per camera: enabled, state, flags, last alarm, live cpu/mem/disk, retention.

    The state here is the RECONCILED one: desired ARMED with a silent worker reports
    UNAVAILABLE, never ARMED.
    """
    out = []
    for cfg in db.query(GuardConfig).order_by(GuardConfig.camera_id).all():
        state = service.effective_state(db, cfg)
        last = (
            db.query(GuardEvent)
            .filter(GuardEvent.camera_id == cfg.camera_id)
            .order_by(GuardEvent.detected_at_utc.desc())
            .first()
        )
        state["last_alarm"] = service._event_payload(last) if last else None
        state["config"] = service.config_payload(cfg)
        state["notifications_enabled"] = settings.guard_notify_enabled
        out.append(state)
    return {"marina_id": settings.marina_id, "cameras": out}


# ─── control ─────────────────────────────────────────────────────────────────

@router.post("/{camera_id}/enable", status_code=status.HTTP_202_ACCEPTED)
def guard_enable(camera_id: int, db: DBSession = Depends(get_db),
                 user: User = Depends(require_control)):
    """Arm guard. 202 + req_id: the worker confirms asynchronously.

    State goes ARMING, and becomes ARMED only on the worker's ack — so the UI never shows
    ARMED on the strength of the backend's own intent.
    """
    cfg = service.get_or_create_config(db, camera_id)
    cfg.desired_state = STATE_ARMED
    cfg.suspended_reason = None
    cfg.suspended_at = None
    db.commit()
    req_id = service.publish_command(db, cfg, service.CMD_ARM, actor=user.email)
    return {"status": "accepted", "req_id": req_id, "camera_id": camera_id,
            "state": STATE_ARMING,
            "note": "ARMED is reported only once the worker acknowledges; if it does not "
                    f"within {settings.guard_ack_timeout_s:.0f}s the state reads UNAVAILABLE"}


@router.post("/{camera_id}/disable", status_code=status.HTTP_202_ACCEPTED)
def guard_disable(camera_id: int, db: DBSession = Depends(get_db),
                  user: User = Depends(require_control)):
    cfg = _cfg_or_404(db, camera_id)
    cfg.desired_state = STATE_OFF
    cfg.suspended_reason = None
    cfg.suspended_at = None
    db.commit()
    req_id = service.publish_command(db, cfg, service.CMD_DISARM, actor=user.email)
    return {"status": "accepted", "req_id": req_id, "camera_id": camera_id,
            "state": STATE_OFF}


@router.post("/{camera_id}/rearm", status_code=status.HTTP_202_ACCEPTED)
def guard_rearm(camera_id: int, db: DBSession = Depends(get_db),
                user: User = Depends(require_control)):
    """Re-arm after a watchdog suspension.

    Distinct from `enable` on purpose: this is a human saying "I have looked at it", which
    resets the auto-resume budget. Rolling it into `enable` would let a script clear that
    budget repeatedly and hide a box that is persistently overloaded.
    """
    cfg = _cfg_or_404(db, camera_id)
    was = cfg.desired_state
    cfg.desired_state = STATE_ARMED
    cfg.suspended_reason = None
    cfg.suspended_at = None
    db.commit()
    req_id = service.publish_command(db, cfg, service.CMD_REARM, actor=user.email)
    return {"status": "accepted", "req_id": req_id, "camera_id": camera_id,
            "previous_state": was, "state": STATE_ARMING}


@router.patch("/{camera_id}/config")
def guard_patch_config(camera_id: int, body: ConfigBody,
                       db: DBSession = Depends(get_db),
                       user: User = Depends(require_control)):
    """Change detection thresholds at runtime. No redeploy, no restart.

    Guard's accuracy is unproven, so every threshold has to be tunable in production. The
    version is bumped and pushed to the worker immediately, and `worker_config_version` in
    `/status` shows which version is actually running — a silent mismatch between backend and
    worker would make tuning results meaningless.
    """
    cfg = service.get_or_create_config(db, camera_id)
    changes: dict[str, object] = {}

    for field in ("conf_threshold", "uncertain_min", "fps", "window_seconds",
                  "frames_required", "cooldown_seconds", "visibility_min_luma",
                  "visibility_min_variance"):
        value = getattr(body, field)
        if value is not None:
            changes[field] = value
            setattr(cfg, field, value)

    if body.zone is not None:
        x1, y1, x2, y2 = body.zone
        if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
            raise HTTPException(
                status_code=400,
                detail="zone must be [x1,y1,x2,y2] fractions with x1<x2 and y1<y2",
            )
        cfg.zone_x1, cfg.zone_y1, cfg.zone_x2, cfg.zone_y2 = x1, y1, x2, y2
        changes["zone"] = body.zone

    # An empty uncertain band would silently stop below-threshold logging, which is the
    # accuracy evidence we cannot reconstruct later.
    if cfg.uncertain_min > cfg.conf_threshold:
        raise HTTPException(
            status_code=400,
            detail=f"uncertain_min ({cfg.uncertain_min}) must be <= conf_threshold "
                   f"({cfg.conf_threshold}), or the uncertain band is empty and "
                   f"below-threshold detections stop being recorded",
        )

    if not changes:
        raise HTTPException(status_code=400, detail="no fields to update")

    cfg.config_version += 1
    cfg.updated_at = datetime.utcnow()
    cfg.updated_by = user.email
    db.commit()
    db.refresh(cfg)

    # Push immediately, but only if guard is meant to be running.
    if cfg.desired_state == STATE_ARMED:
        service.publish_command(db, cfg, service.CMD_ARM, actor=user.email)

    return {"status": "updated", "camera_id": camera_id,
            "config_version": cfg.config_version, "changed": changes,
            "config": service.config_payload(cfg),
            "pushed_to_worker": cfg.desired_state == STATE_ARMED}


# ─── events ──────────────────────────────────────────────────────────────────

@router.get("/events")
def guard_events(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    camera_id: int | None = None,
    label: str | None = Query(None, pattern=f"^({LABEL_CORRECT}|{LABEL_FALSE_ALARM}|unlabelled)$"),
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    """Alarm log, newest first. `label=unlabelled` is the review queue for the week."""
    q = db.query(GuardEvent)
    if camera_id is not None:
        q = q.filter(GuardEvent.camera_id == camera_id)
    if label == "unlabelled":
        q = q.filter(GuardEvent.label.is_(None))
    elif label:
        q = q.filter(GuardEvent.label == label)
    total = q.count()
    rows = q.order_by(GuardEvent.detected_at_utc.desc()).offset(offset).limit(limit).all()
    return {
        "total": total, "limit": limit, "offset": offset,
        "unlabelled": db.query(GuardEvent).filter(GuardEvent.label.is_(None)).count(),
        "events": [service._event_payload(e) for e in rows],
    }


@router.get("/events/{event_id}/video")
def guard_event_video(event_id: int, db: DBSession = Depends(get_db),
                      _: User = Depends(require_any_role)):
    ev = _event_or_404(db, event_id)
    rec = None
    if ev.event_uuid:
        rec = db.query(GuardRecording).filter(
            GuardRecording.event_uuid == ev.event_uuid).first()
    if rec is not None and rec.deleted_at is not None:
        return _serve_file(None, "video/mp4", "video",
                           deleted_at=rec.deleted_at, delete_reason=rec.delete_reason)
    if ev.video_skipped and not ev.video_path:
        raise HTTPException(
            status_code=404,
            detail={"reason": ev.video_skip_reason or "video_skipped",
                    "hint": "the alarm was recorded but no clip was made; detection "
                            "continues when recording is disabled"},
        )
    try:
        return _serve_file(ev.video_path, "video/mp4", "video")
    except HTTPException as exc:
        # Self-correct so the list view stops offering a link that cannot work.
        if exc.status_code == status.HTTP_410_GONE and rec is not None and rec.deleted_at is None:
            rec.deleted_at = datetime.utcnow()
            rec.delete_reason = "missing_on_disk"
            db.commit()
        raise


@router.get("/events/{event_id}/frame")
def guard_event_frame(event_id: int, db: DBSession = Depends(get_db),
                      _: User = Depends(require_any_role)):
    """The ANNOTATED frame, with the detection box drawn.

    Required by the dashboard from day one: if the first alarms are boxes on gulls, that has
    to be visible immediately rather than inferred from a confidence number.
    """
    ev = _event_or_404(db, event_id)
    return _serve_file(ev.frame_path, "image/jpeg", "frame")


@router.post("/events/{event_id}/label")
def guard_label_event(event_id: int, body: LabelBody,
                      db: DBSession = Depends(get_db),
                      user: User = Depends(require_any_role)):
    """Mark an alarm correct or a false alarm. Labelled data from day one.

    Deliberately `require_any_role`: a monitor watching the dashboard is exactly the person
    who spots a gull, and making them fetch an admin would cost the labels.

    Re-labelling is allowed — a second look is legitimate — and overwrites with the new actor
    and time rather than accumulating history, because the current verdict is what the
    training set needs.
    """
    ev = _event_or_404(db, event_id)
    ev.label = body.label
    ev.label_note = body.note
    ev.labelled_at = datetime.utcnow()
    ev.labelled_by = user.email
    db.commit()
    db.refresh(ev)
    return {"status": "labelled", "event": service._event_payload(ev)}


# ─── detections (the accuracy evidence) ──────────────────────────────────────

@router.get("/detections")
def guard_detections(
    since: str | None = Query(None, description="ISO-8601; default 24 h ago"),
    min_confidence: float = Query(0.0, ge=0, le=1),
    band: str | None = Query(None, pattern="^(uncertain|alarm)$"),
    camera_id: int | None = None,
    limit: int = Query(200, ge=1, le=2000),
    db: DBSession = Depends(get_db),
    _: User = Depends(require_any_role),
):
    """Every logged detection, including below-threshold ones.

    These are the A.5 accuracy rows the person-clip run could not produce, and the Phase 2
    training index. A frame with nothing in it writes no row at all, so absence in this list
    means absence — not a weak detection that was rounded away.
    """
    start = service._parse_dt(since) if since else datetime.utcnow() - timedelta(days=1)
    q = db.query(GuardDetection).filter(GuardDetection.detected_at >= start)
    if camera_id is not None:
        q = q.filter(GuardDetection.camera_id == camera_id)
    if band:
        q = q.filter(GuardDetection.band == band)
    if min_confidence > 0:
        q = q.filter(GuardDetection.confidence >= min_confidence)
    total = q.count()
    rows = q.order_by(GuardDetection.detected_at.desc()).limit(limit).all()
    return {
        "since": iso_z(start), "total": total, "limit": limit,
        "detections": [{
            "id": d.id, "camera_id": d.camera_id,
            "detected_at": iso_z(d.detected_at),
            "confidence": d.confidence, "px_height": d.px_height,
            "bbox": json.loads(d.bbox) if d.bbox else None,
            "band": d.band, "has_frame": bool(d.frame_path),
            "limited_visibility": d.limited_visibility,
            "event_uuid": d.event_uuid,
        } for d in rows],
    }


@router.get("/detections/{detection_id}/frame")
def guard_detection_frame(detection_id: int, db: DBSession = Depends(get_db),
                          _: User = Depends(require_any_role)):
    """The frame behind an UNCERTAIN detection — the Phase 2 escalation candidate.

    Uncertain frames are rate-limited and evicted before alarm frames, so this legitimately
    404s for many rows; that is the frame budget working, not an error.
    """
    det = db.get(GuardDetection, detection_id)
    if det is None:
        raise HTTPException(status_code=404, detail=f"No detection {detection_id}")
    return _serve_file(det.frame_path, "image/jpeg", "frame")
