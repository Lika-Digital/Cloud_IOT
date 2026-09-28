"""
Guard worker entrypoint — `python -m guard_worker`, run by cloud-iot-guard.service.

This is the glue the other modules were built for. Steps 1-5 produced the pieces (capture,
pipeline, alarm rule, recorder, watchdog) and the backend half of the contract; nothing ran
them, so `python -m guard_worker` did not exist and the service could not start. This is that
module.

Shape, and why:

  * **One thread does the work.** Frames arrive at `fps` (1/s by default), so the loop has
    most of a second spare between them for the watchdog, health, retention, pruning and
    clip assembly. A single ordered loop is easier to reason about than threads sharing
    detector state, and there is no throughput problem to solve.
  * **MQTT runs on paho's own network thread**, and commands are queued rather than applied
    inside the callback. Arming from inside a network callback would start ffmpeg and load a
    model on paho's thread, which is how a client ends up wedged — still connected, no longer
    heartbeating.
  * **Nothing runs while disarmed.** No ffmpeg, no RTSP session, no model in memory. That is
    what makes "guard OFF costs nothing" checkable with `ps` rather than promised.
  * **Clip assembly is deferred, not immediate.** `ClipAssembler.select_segments` spans
    `alarm_at - preroll` through `alarm_at + record_seconds`, and the post-roll segments do
    not exist yet at the moment the alarm fires. Assembling straight away would silently
    produce pre-roll-only clips — technically a video, useless for deciding whether the
    detection was a person. So the alarm publishes immediately (it is the time-critical
    fact), the segments are pinned so the ring cannot delete them, and the clip is assembled
    and published on `guard/recording` once the footage exists. The backend already links
    the two by `event_uuid`, which is why recording is a separate topic from alarm.
  * **The worker never opens a database.** It publishes; the backend persists. It is the only
    writer of files under the recordings path.

Last Will is set on `state`, so if this process dies the broker publishes UNAVAILABLE and a
late subscriber can never read a stale ARMED. With the backend's heartbeat timeout and its
in-memory `worker_seen_at`, that is the three-way guarantee from B1 §7.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import signal
import socket
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# The repo root and backend/ are on sys.path via the unit's WorkingDirectory; make it
# explicit so a manual run from any directory behaves identically.
_REPO = Path(__file__).resolve().parent.parent
for _p in (str(_REPO), str(_REPO / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from guard_worker.capture import (  # noqa: E402
    CameraCapture,
    CaptureSupervisor,
    FfmpegNotAvailable,
    SegmentHealth,
)
from guard_worker.recorder import (  # noqa: E402
    ClipAssembler,
    FrameWriter,
    RecordingConfig,
    apply_retention,
    sweep_orphan_parts,
)
from guard_worker.watchdog import (  # noqa: E402
    STATE_ARMED,
    STATE_OFF,
    STATE_SUSPENDED_CPU,
    STATE_UNAVAILABLE,
    CpuSampler,
    Watchdog,
    WatchdogConfig,
    disk_reading,
)

logger = logging.getLogger("guard_worker")

STATE_RECORDING = "RECORDING"

HEALTH_INTERVAL_S = 5.0
WATCHDOG_INTERVAL_S = 5.0
DETECTION_FLUSH_S = 5.0
RETENTION_INTERVAL_S = 300.0
PRUNE_INTERVAL_S = 10.0
IDLE_SLEEP_S = 0.2


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_f(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, TypeError, ValueError):
        return default


def _env_i(name: str, default: int) -> int:
    try:
        return int(os.environ[name])
    except (KeyError, TypeError, ValueError):
        return default


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


@dataclass
class WorkerConfig:
    """Start-time settings only.

    Detection thresholds are deliberately NOT here: they arrive in the arm command from the
    backend, which owns them so they can be tuned at runtime without restarting anything.
    `num_threads` is start-time because OpenVINO fixes thread count at `compile_model` time.
    """
    marina_id: str = "KRK"
    camera_id: int = 1
    pedestal_id: int = 1
    stream_url: str = ""
    broker_host: str = "localhost"
    broker_port: int = 1883
    storage_path: str = "/var/lib/marina-guard/recordings"
    model_dir: str = "/opt/cloud-iot/guard/models"
    num_threads: int = 1
    segment_seconds: int = 10
    segment_ring: int = 6
    record_seconds: int = 60
    preroll_seconds: int = 6
    retention_days: int = 14
    max_gb: float = 20.0
    max_frames_gb: float = 2.0
    frame_min_interval_s: float = 10.0
    ffmpeg: str | None = None
    # Replaces the RTSP input flags. Not read from the environment on purpose: this is a
    # test and diagnostic seam for running the worker against a pre-encoded file, not
    # something an operator should be able to set on a deployed cabinet.
    input_args: list[str] | None = None

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        cam = _env_i("GUARD_CAMERA_ID", 1)
        return cls(
            marina_id=_env("MARINA_ID", "KRK"),
            camera_id=cam,
            # camera_id == pedestal_id today; separate so a real cameras table can arrive
            # later without this having to be rewritten.
            pedestal_id=_env_i("GUARD_PEDESTAL_ID", cam),
            stream_url=_env("GUARD_STREAM_URL", ""),
            broker_host=_env("MQTT_BROKER_HOST", "localhost"),
            broker_port=_env_i("MQTT_BROKER_PORT", 1883),
            storage_path=_env("GUARD_STORAGE_PATH", "/var/lib/marina-guard/recordings"),
            model_dir=_env("GUARD_MODEL_DIR", "/opt/cloud-iot/guard/models"),
            num_threads=_env_i("GUARD_NUM_THREADS", 1),
            segment_seconds=_env_i("GUARD_SEGMENT_SECONDS", 10),
            segment_ring=_env_i("GUARD_SEGMENT_RING", 6),
            record_seconds=_env_i("GUARD_RECORD_SECONDS", 60),
            preroll_seconds=_env_i("GUARD_PREROLL_SECONDS", 6),
            retention_days=_env_i("GUARD_RETENTION_DAYS", 14),
            max_gb=_env_f("GUARD_MAX_GB", 20.0),
            max_frames_gb=_env_f("GUARD_MAX_FRAMES_GB", 2.0),
            frame_min_interval_s=_env_f("GUARD_FRAME_MIN_INTERVAL_S", 10.0),
            ffmpeg=os.environ.get("GUARD_FFMPEG") or None,
        )

    def topic(self, leaf: str) -> str:
        return f"marina/{self.marina_id}/camera/{self.camera_id}/guard/{leaf}"


@dataclass
class PendingClip:
    """An alarm whose footage has not finished being written yet.

    `assemble_at` is when enough post-roll exists on disk. Until then the segments stay
    pinned so the capture ring cannot recycle them out from under the alarm.
    """
    event_uuid: str
    alarm_at_wall: float
    alarm_at_utc: datetime
    confidence: float
    assemble_at: float
    segments: list[Path] = field(default_factory=list)


class GuardWorker:
    def __init__(self, cfg: WorkerConfig, *, client=None, detector_factory=None):
        self.cfg = cfg
        # Two injection points, both for the same reason: the end-to-end smoke test must
        # drive the REAL loop, not a re-implementation of it. `client` replaces the broker,
        # `detector_factory` replaces OpenVINO — which has no 32-bit wheel, so without this
        # seam the armed path could only ever be tested on the NUC, and it was precisely the
        # untested assembly that left the worker with no entrypoint at all.
        self.client = client
        self._detector_factory = detector_factory
        self._commands: queue.Queue[dict] = queue.Queue()
        self._stopping = False
        self.ready = False

        self.state = STATE_OFF
        self.detection_config: dict = {}
        self.config_version = 0

        self.watchdog = Watchdog(WatchdogConfig(
            cpu_warn=_env_f("GUARD_CPU_WARN", 50.0),
            cpu_limit=_env_f("GUARD_CPU_LIMIT", 60.0),
            cpu_resume=_env_f("GUARD_CPU_RESUME", 45.0),
            resume_after_s=_env_f("GUARD_RESUME_AFTER", 300.0),
            max_auto_resumes=_env_i("GUARD_MAX_AUTO_RESUMES", 2),
            disk_min_gb=_env_f("GUARD_DISK_MIN_GB", 5.0),
            disk_min_percent=_env_f("GUARD_DISK_MIN_PERCENT", 10.0),
        ))
        # The worker starts OFF whatever the watchdog's own default is: it waits to be told
        # what to do by the backend, which is what holds desired state across a restart.
        self.watchdog.disarm()
        self.cpu = CpuSampler()
        self.recording_enabled = True

        self.rec_cfg = RecordingConfig(
            storage_path=Path(cfg.storage_path),
            record_seconds=cfg.record_seconds,
            segment_seconds=cfg.segment_seconds,
            preroll_seconds=cfg.preroll_seconds,
            max_days=cfg.retention_days,
            max_gb=cfg.max_gb,
            max_frames_gb=cfg.max_frames_gb,
            frame_min_interval_s=cfg.frame_min_interval_s,
            ffmpeg=cfg.ffmpeg,
        )
        self.segment_dir = self.rec_cfg.camera_dir(cfg.camera_id) / "segments"

        # Armed-only resources. All None while disarmed, which is the point.
        self.detector = None
        self.supervisor: CaptureSupervisor | None = None
        self.frames = None
        self.pipeline_config = None
        self.alarm_state = None
        self.assembler: ClipAssembler | None = None
        self.frame_writer: FrameWriter | None = None
        self.segment_health: SegmentHealth | None = None

        self._pending_detections: list[dict] = []
        self._pending_clips: list[PendingClip] = []
        self._last = {k: 0.0 for k in
                      ("health", "watchdog", "flush", "retention", "prune")}

    # ── MQTT ──

    def connect(self) -> None:
        if self.client is None:
            import paho.mqtt.client as mqtt

            cid = f"guard-worker-{self.cfg.camera_id}-{socket.gethostname()}"
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cid)
            self.client.reconnect_delay_set(min_delay=1, max_delay=30)

        # Last Will: if this process dies, the broker publishes UNAVAILABLE on the retained
        # state topic, so a late subscriber cannot read a stale ARMED.
        self.client.will_set(
            self.cfg.topic("state"),
            json.dumps({"state": STATE_UNAVAILABLE, "reason": "worker died (LWT)",
                        "camera_id": self.cfg.camera_id}),
            qos=1, retain=True,
        )
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect(self.cfg.broker_host, self.cfg.broker_port, keepalive=30)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            logger.error("MQTT connect refused: %s", reason_code)
            return
        client.subscribe(self.cfg.topic("cmd"), qos=1)
        logger.info("MQTT connected to %s:%d; subscribed to %s",
                    self.cfg.broker_host, self.cfg.broker_port, self.cfg.topic("cmd"))
        # Announce presence so the backend can push the desired state. The worker always
        # comes up OFF and waits: a guard the watchdog suspended must not rearm itself just
        # by restarting, and desired state lives in the backend, not here.
        self.publish_state("worker started")
        self.ready = True

    def _on_message(self, client, userdata, msg):
        """Queue the command; never act on paho's network thread."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            logger.warning("ignoring malformed command on %s: %s", msg.topic, exc)
            return
        self._commands.put(payload)

    def publish(self, leaf: str, data: dict, *, retain: bool = False) -> None:
        if self.client is None:
            return
        data.setdefault("camera_id", self.cfg.camera_id)
        data.setdefault("ts", _utc_iso())
        try:
            self.client.publish(self.cfg.topic(leaf), json.dumps(data),
                                qos=1, retain=retain)
        except Exception as exc:
            # A publish failure must not take the worker down; the backend's heartbeat
            # timeout is what turns a persistently mute worker into UNAVAILABLE.
            logger.warning("publish to %s failed: %s", leaf, exc)

    def publish_state(self, reason: str | None = None) -> None:
        self.publish("state", {
            "state": self.state,
            # current_flags reads the watchdog WITHOUT ticking it — a tick here would clear
            # segments_stalled and limited_visibility as a side effect of publishing.
            "flags": self.watchdog.current_flags,
            "reason": reason,
            "config_version": self.config_version,
            "recording_enabled": self.recording_enabled,
        }, retain=True)

    # ── arm / disarm ──

    def apply_command(self, cmd: dict) -> None:
        action = cmd.get("cmd")
        req_id = cmd.get("req_id", "")
        config = cmd.get("config") or {}
        logger.info("command=%s req_id=%s config_version=%s",
                    action, req_id, config.get("config_version"))

        accepted, reason = True, None
        try:
            if action in ("arm", "rearm"):
                self.detection_config = config
                self.config_version = int(config.get("config_version") or 0)
                if action == "rearm":
                    for t in self.watchdog.manual_rearm(time.time()):
                        logger.info("watchdog: %s — %s", t.event, t.reason)
                self._arm()
            elif action == "disarm":
                self._disarm()
            else:
                accepted, reason = False, f"unknown command {action!r}"
                logger.warning("rejecting unknown command %r", action)
        except FfmpegNotAvailable as exc:
            accepted, reason = False, str(exc)
            self.state = STATE_UNAVAILABLE
            logger.error("cannot arm: %s", exc)
        except Exception as exc:
            accepted, reason = False, str(exc)
            if self.state == STATE_OFF:
                self.state = STATE_UNAVAILABLE
            logger.exception("command %s failed", action)

        # Ack first: the backend's 5 s ack watchdog is what stops the UI sitting on ARMING
        # forever, and it needs the answer whether or not the command succeeded.
        self.publish("ack", {"req_id": req_id, "accepted": accepted,
                             "state": self.state, "reason": reason,
                             "config_version": self.config_version})
        self.publish_state(reason)

    def _arm(self) -> None:
        transitions = self.watchdog.arm()
        for t in transitions:
            logger.info("watchdog: %s — %s", t.event, t.reason)
        if any(t.event == "arm_refused" for t in transitions):
            # Not a crash: the machine is waiting for a human. Report it honestly rather
            # than arming and being suspended again within the minute.
            self.state = STATE_SUSPENDED_CPU
            raise RuntimeError(transitions[0].reason)

        if self.state in (STATE_ARMED, STATE_RECORDING) and self.supervisor is not None:
            # Already running: a config push re-applies thresholds in place rather than
            # restarting ffmpeg, so tuning does not interrupt the segment ring.
            logger.info("applying config_version=%d in place (capture keeps running)",
                        self.config_version)
            self._build_pipeline_objects()
            self.state = STATE_ARMED
            return

        self.segment_dir.mkdir(parents=True, exist_ok=True)
        orphans = sweep_orphan_parts(self.rec_cfg, self.cfg.camera_id)
        if orphans:
            logger.info("swept %d orphaned .part file(s) from a previous run", len(orphans))

        # Single-threaded by construction — see GUARD_NUM_THREADS and for_guard().
        self.detector = self._make_detector()
        if not self.detector.available:
            self.detector = None
            raise RuntimeError(
                f"detector unavailable: no usable OpenVINO IR under {self.cfg.model_dir} "
                f"(or openvino is missing from this venv)"
            )

        self._build_pipeline_objects()

        fps = float(self.detection_config.get("fps") or 1.0)
        self.supervisor = CaptureSupervisor(
            lambda: CameraCapture(
                self.cfg.stream_url, self.segment_dir,
                fps=fps, segment_seconds=self.cfg.segment_seconds,
                segment_ring=self.cfg.segment_ring, ffmpeg=self.cfg.ffmpeg,
                input_args=self.cfg.input_args,
            ),
            on_event=self._on_capture_event,
        )
        self.frames = self.supervisor.frames()
        self.segment_health = SegmentHealth(
            self.segment_dir, segment_seconds=self.cfg.segment_seconds)
        self.state = STATE_ARMED
        logger.info("ARMED camera=%d fps=%.1f threads=%d config_version=%d",
                    self.cfg.camera_id, fps, self.cfg.num_threads, self.config_version)

    def _make_detector(self):
        """Build the detector. Imported here, not at module scope, so the worker can be
        started and smoke-tested on a box with no openvino wheel."""
        if self._detector_factory is not None:
            return self._detector_factory()
        from app.services.yolo_openvino import YoloOVDetector

        return YoloOVDetector.for_guard(
            self.cfg.model_dir, num_threads=self.cfg.num_threads)

    def _on_capture_event(self, event: str, fields: dict) -> None:
        """Capture restarts surface in health, not only in the log.

        A camera that drops every 30 s and is silently restarted looks identical to a healthy
        one from the dashboard, which is precisely the failure the supervisor exists to make
        visible.
        """
        logger.warning("capture: %s %s", event, fields)
        self.publish("health", {"state": self.state, "capture_event": event, **fields})

    def _build_pipeline_objects(self) -> None:
        from app.guard.alarm_rule import AlarmState
        from app.guard.pipeline import PipelineConfig

        c = self.detection_config
        zone = c.get("zone") or [0.2, 0.2, 0.8, 0.8]
        self.pipeline_config = PipelineConfig(
            conf_threshold=float(c.get("conf_threshold") or 0.5),
            uncertain_min=float(c.get("uncertain_min") or 0.2),
            zone=tuple(zone),
            visibility_min_luma=float(c.get("visibility_min_luma") or 30.0),
            visibility_min_variance=float(c.get("visibility_min_variance") or 15.0),
        )
        self.alarm_state = AlarmState(
            frames_required=int(c.get("frames_required") or 2),
            window_seconds=float(c.get("window_seconds") or 4.0),
            cooldown_seconds=float(c.get("cooldown_seconds") or 60.0),
        )
        # Kept across re-arms on purpose: FrameWriter holds the alarm-frame names that
        # retention must never evict, and the assembler holds pins for clips in flight.
        if self.assembler is None:
            self.assembler = ClipAssembler(self.rec_cfg, self.segment_dir)
        if self.frame_writer is None:
            self.frame_writer = FrameWriter(self.rec_cfg, self.cfg.camera_id)

    def _disarm(self, *, state: str = STATE_OFF, reason: str | None = None) -> None:
        """Release everything within seconds: ffmpeg, the RTSP session, and the model.

        Verifiable from outside with `ps` and RSS, which is why the spec asks for it rather
        than trusting an internal flag.
        """
        if self.supervisor is not None:
            self.supervisor.stop()
            self.supervisor = None
        self.frames = None
        if self.detector is not None:
            self.detector.unload()
            self.detector = None
        if self.alarm_state is not None:
            # An old window must not contribute to the next arming session.
            self.alarm_state.reset()
        self.segment_health = None
        # Finish any clip whose footage already exists, then release the pins: an unfinished
        # assembly holding pins forever would stop the ring reclaiming space.
        self._drain_pending_clips(force=True)
        if self.assembler is not None:
            self.assembler.unpin_all()
        self._flush_detections()
        self.watchdog.disarm()
        self.state = state
        logger.info("%s camera=%d — capture stopped, model released%s",
                    state, self.cfg.camera_id, f" ({reason})" if reason else "")

    # ── the frame path ──

    def handle_frame(self, jpeg: bytes) -> None:
        from app.guard.pipeline import process_frame as run_pipeline

        result = run_pipeline(self.detector, jpeg, self.pipeline_config)
        now = time.time()
        when = datetime.now(timezone.utc).replace(tzinfo=None)

        frame_path = None
        if result.worth_storing and self.frame_writer is not None:
            saved = self.frame_writer.save(jpeg, result.band, when, now=now)
            frame_path = str(saved) if saved else None

        bbox = result.detections[0]["bbox_xyxy"] if result.detections else None

        if result.worth_storing:
            # Every detection above the logging floor is recorded — these rows are the
            # accuracy evidence and the Phase 2 training index, unrecoverable afterwards.
            self._pending_detections.append({
                "ts": when.isoformat() + "Z",
                "confidence": result.confidence,
                "px_height": result.px_height,
                "bbox": bbox,
                "band": result.band,
                "frame_path": frame_path,
                "limited_visibility": result.limited_visibility,
            })

        if self.alarm_state.observe(now, result.detected) is not None:
            self._raise_alarm(result, frame_path, bbox, now, when)

    def _raise_alarm(self, result, frame_path, bbox, now: float, when: datetime) -> None:
        """Publish the alarm NOW; the clip follows when its footage exists."""
        event_uuid = str(uuid.uuid4())

        # Tie the contributing detections to the event so the training index can be filtered
        # to "what the rule actually fired on".
        for d in self._pending_detections[-self.alarm_state.frames_required:]:
            d.setdefault("event_uuid", event_uuid)

        skipped, skip_reason = False, None
        if not self.recording_enabled:
            # Disk is below the floor. Detection and alarms continue: an alarm you know
            # about with no video beats no alarm at all.
            skipped, skip_reason = True, "no_disk"
        elif self.assembler is not None:
            segments = self.assembler.select_segments(now, now=now)
            self.assembler.pin(segments)
            self._pending_clips.append(PendingClip(
                event_uuid=event_uuid, alarm_at_wall=now, alarm_at_utc=when,
                confidence=result.confidence,
                # Wait for the post-roll plus one segment period, so the segment covering
                # the end of the window has been closed by ffmpeg and is readable.
                assemble_at=now + self.cfg.record_seconds + self.cfg.segment_seconds,
                segments=segments,
            ))

        self.publish("alarm", {
            "event_uuid": event_uuid,
            "pedestal_id": self.cfg.pedestal_id,
            "detected_at_utc": when.isoformat() + "Z",
            "detected_at_local": datetime.now().astimezone().isoformat(),
            "confidence": result.confidence,
            "px_height": result.px_height,
            "bbox": bbox,
            "trigger": f"{self.alarm_state.frames_required}_in_"
                       f"{self.alarm_state.window_seconds:g}s",
            "limited_visibility": result.limited_visibility,
            "frame_path": frame_path,
            # No video_path yet, and video_skipped stays False when a clip is coming: the
            # recording message backfills the path onto the event by event_uuid.
            "video_path": None,
            "video_skipped": skipped,
            "video_skip_reason": skip_reason,
        })
        logger.warning("ALARM conf=%.2f px=%.0f video=%s", result.confidence,
                       result.px_height or 0.0,
                       f"SKIPPED({skip_reason})" if skipped else "pending")
        self._flush_detections()
        self.publish_state("alarm raised")

    def _drain_pending_clips(self, *, force: bool = False,
                             now: float | None = None) -> None:
        """Assemble clips whose footage has finished being written."""
        if not self._pending_clips or self.assembler is None:
            return
        now = now if now is not None else time.time()
        still_waiting: list[PendingClip] = []

        for clip in self._pending_clips:
            if not force and now < clip.assemble_at:
                still_waiting.append(clip)
                continue
            was = self.state
            self.state = STATE_RECORDING
            self.publish_state("assembling clip")
            try:
                # Re-select: post-roll segments exist now that did not at alarm time.
                segments = self.assembler.select_segments(clip.alarm_at_wall, now=now)
                if not segments:
                    segments = clip.segments
                assembled = self.assembler.assemble(
                    self.cfg.camera_id, clip.alarm_at_utc, segments)
            except Exception as exc:
                logger.warning("clip assembly raised for %s: %s", clip.event_uuid, exc)
                assembled = None
            finally:
                self.state = STATE_ARMED if was == STATE_RECORDING else was

            if assembled is None:
                # The alarm and its annotated frame are already recorded; say the clip is
                # missing rather than leaving a row promising a link that cannot work.
                self.publish("alarm", {
                    "event_uuid": clip.event_uuid,
                    "pedestal_id": self.cfg.pedestal_id,
                    "detected_at_utc": clip.alarm_at_utc.isoformat() + "Z",
                    "confidence": clip.confidence,
                    "video_skipped": True,
                    "video_skip_reason": "assembly_failed",
                })
                logger.warning("no clip for %s — assembly failed", clip.event_uuid)
                continue

            self.publish("recording", {
                "event_uuid": clip.event_uuid,
                "file_path": str(assembled.path),
                "started_at": assembled.started_at.isoformat() + "Z",
                "duration_s": assembled.duration_s,
                "file_size": assembled.file_size,
                "confidence": clip.confidence,
                "truncated": assembled.truncated,
            })
            logger.info("clip ready for %s: %s (%.1fs, %d bytes)", clip.event_uuid,
                        assembled.path, assembled.duration_s or 0.0, assembled.file_size)

        drained = len(self._pending_clips) != len(still_waiting)
        self._pending_clips = still_waiting
        if not self._pending_clips:
            self.assembler.unpin_all()
        if drained:
            self.publish_state()

    def _flush_detections(self) -> None:
        if not self._pending_detections:
            return
        # One batch per flush: per-frame writes would contend with the marina's session
        # writes on the same SQLite file.
        self.publish("detection", {"detections": self._pending_detections})
        self._pending_detections = []

    # ── periodic work, done in the gaps between frames ──

    def periodic(self, now: float | None = None) -> None:
        now = now if now is not None else time.time()

        if now - self._last["watchdog"] >= WATCHDOG_INTERVAL_S:
            self._last["watchdog"] = now
            self._run_watchdog(now)

        if now - self._last["flush"] >= DETECTION_FLUSH_S:
            self._last["flush"] = now
            self._flush_detections()

        self._drain_pending_clips(now=now)

        if self.supervisor is not None and now - self._last["prune"] >= PRUNE_INTERVAL_S:
            self._last["prune"] = now
            cap = self.supervisor.capture
            if cap is not None:
                # Pinned segments belong to an alarm awaiting assembly and must survive.
                pinned = self.assembler.pinned_segments if self.assembler else frozenset()
                cap.prune(pinned=pinned)

        if now - self._last["retention"] >= RETENTION_INTERVAL_S:
            self._last["retention"] = now
            self._run_retention()

    def _run_watchdog(self, now: float) -> None:
        cpu = self.cpu.sample()
        disk = disk_reading(self.rec_cfg.camera_dir(self.cfg.camera_id))
        stalled, stall_reason = False, None
        if self.state in (STATE_ARMED, STATE_RECORDING) and self.segment_health is not None:
            self.segment_health.sample(now)
            stalled = self.segment_health.is_stalled(now)
            stall_reason = self.segment_health.stall_reason(now)

        verdict = self.watchdog.tick(
            now=now, cpu_pct=cpu,
            disk_free_gb=disk[0] if disk else None,
            disk_free_percent=disk[1] if disk else None,
            segments_stalled=stalled, stall_reason=stall_reason,
        )
        self.recording_enabled = verdict.recording_enabled

        for t in verdict.transitions:
            logger.warning("watchdog: %s — %s", t.event, t.reason)
            if t.event == "suspended_cpu":
                # Shed guard. It does not come back on its own beyond the budget the
                # watchdog itself allows — the backend re-arms explicitly.
                self._disarm(state=STATE_SUSPENDED_CPU, reason=t.reason)
            self.publish_state(t.reason)

        if now - self._last["health"] >= HEALTH_INTERVAL_S:
            self._last["health"] = now
            self.publish("health", {
                "state": self.state,
                "cpu_pct_60s": verdict.cpu_avg,
                "cpu_pct_now": cpu,
                "disk_free_gb": disk[0] if disk else None,
                "disk_free_percent": disk[1] if disk else None,
                "recording_enabled": verdict.recording_enabled,
                "flags": verdict.flags,
                "config_version": self.config_version,
                "capture_restarts": self.supervisor.restart_count if self.supervisor else 0,
                "clips_pending": len(self._pending_clips),
            })

    def _run_retention(self) -> None:
        try:
            report = apply_retention(
                self.rec_cfg, self.cfg.camera_id,
                # Labels live in the backend; until it republishes them the worker protects
                # nothing extra, and max_days is the only rule that consults this.
                labelled=frozenset(),
                alarm_frames=(self.frame_writer.alarm_frame_names
                              if self.frame_writer else frozenset()),
            )
        except Exception as exc:
            logger.warning("retention pass failed: %s", exc)
            return
        if report.anything_deleted or report.frames_evicting:
            self.publish("retention", {
                "deleted": report.deleted_recordings + report.deleted_frames,
                "frames_gb_used": report.frames_gb_used,
                "recordings_gb_used": report.recordings_gb_used,
                "frames_evicting": report.frames_evicting,
                "frames_cap_exhausted": report.frames_cap_exhausted,
                "labelled_evicted": report.labelled_evicted,
            })

    # ── main loop ──

    def stop(self, *_args) -> None:
        """SIGTERM/SIGINT handler. Sets a flag; the loop performs the shutdown.

        Deliberately not doing the teardown in the handler: it would run on whatever the
        process was doing mid-frame, and stopping ffmpeg from a signal handler while the
        frame reader is blocked on its pipe is how a shutdown hangs.
        """
        logger.info("stop requested — finishing the current iteration")
        self._stopping = True

    def drain_commands(self) -> None:
        while True:
            try:
                cmd = self._commands.get_nowait()
            except queue.Empty:
                return
            self.apply_command(cmd)

    def step(self) -> None:
        """One iteration: commands, then a frame if armed, then periodic work."""
        self.drain_commands()

        jpeg = None
        if self.state in (STATE_ARMED, STATE_RECORDING) and self.frames is not None:
            try:
                jpeg = next(self.frames)
            except StopIteration:
                logger.warning("frame stream ended; restarting it")
                self.frames = self.supervisor.frames() if self.supervisor else None
            except Exception:
                logger.exception("reading a frame failed")
                time.sleep(1.0)
            if jpeg is not None:
                try:
                    self.handle_frame(jpeg)
                except Exception:
                    # One bad frame must never take the worker down.
                    logger.exception("pipeline error on one frame — continuing")
        else:
            time.sleep(IDLE_SLEEP_S)

        self.periodic()

    def shutdown(self) -> None:
        self._disarm(reason="worker shutting down")
        # Publish the real state, not the LWT: a clean stop is not a crash, and the
        # difference matters when reading why guard went away.
        self.publish_state("worker stopped")
        if self.client is not None:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception as exc:
                logger.warning("MQTT shutdown: %s", exc)
        self.ready = False
        logger.info("guard worker stopped")

    def run(self) -> int:
        # SIGBREAK is registered where it exists (Windows) so the shutdown path can be
        # exercised by a real signal on the dev box too, rather than only on the NUC.
        for signame in ("SIGTERM", "SIGINT", "SIGBREAK"):
            sig = getattr(signal, signame, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, self.stop)
            except (ValueError, OSError):
                # Not the main thread (the in-process smoke test runs the loop in a
                # thread); the caller drives stop() directly instead.
                pass

        if not self.cfg.stream_url:
            logger.error("GUARD_STREAM_URL is not set — there is nothing to capture")
            return 2

        try:
            self.connect()
        except Exception as exc:
            logger.error("cannot reach the MQTT broker at %s:%d — %s",
                         self.cfg.broker_host, self.cfg.broker_port, exc)
            return 3

        logger.info("guard worker running: camera=%d marina=%s state=%s",
                    self.cfg.camera_id, self.cfg.marina_id, self.state)
        while not self._stopping:
            self.step()
        self.shutdown()
        return 0


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("GUARD_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = WorkerConfig.from_env()
    logger.info("config: camera=%d marina=%s broker=%s:%d threads=%d storage=%s",
                cfg.camera_id, cfg.marina_id, cfg.broker_host, cfg.broker_port,
                cfg.num_threads, cfg.storage_path)
    return GuardWorker(cfg).run()


if __name__ == "__main__":
    sys.exit(main())
