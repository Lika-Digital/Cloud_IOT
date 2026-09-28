"""
Guard worker SMOKE tests — does the assembled thing actually start and run?

Why this file exists at all is the point of it. 803 unit tests were green while
`guard_worker/__main__.py` did not exist: every component was verified in isolation and
nothing verified that they compose into a process that boots. A component suite that passes
while the app cannot start is not a passing suite, it is a suite testing the wrong scope.

So these tests exercise the real `GuardWorker.run()` loop and the real `python -m
guard_worker` module entry. Two things are substituted, and only two:

  * the MQTT broker, by a recording fake — otherwise the test needs a live mosquitto;
  * the detector, by a fake — OpenVINO has no 32-bit wheel, so a real one would confine the
    armed path to the NUC, which is the isolation that caused this gap.

Everything else is production code: the config parsing, the command handling, the state
machine, the watchdog tick, the publish contract, the signal path and the shutdown.

Test IDs:
  TC-GSMOKE-01  the loop starts, announces itself, and exits 0 when asked to stop
  TC-GSMOKE-02  the first published state is OFF and retained — never a stale ARMED
  TC-GSMOKE-03  `python -m guard_worker` really executes as a module
  TC-GSMOKE-04  a real graceful signal to a real subprocess shuts it down cleanly
  TC-GSMOKE-05  arm -> frames -> alarm -> clip, driven through the real loop (needs ffmpeg)
  TC-GSMOKE-06  arm is acked as REFUSED, not crashed, when the detector is unavailable
  TC-GSMOKE-07  disarm releases the model and the capture process
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from guard_worker.__main__ import GuardWorker, WorkerConfig  # noqa: E402

# A tiny valid JPEG is not enough — the pipeline crops and measures it — so the fixture
# builds a real one with Pillow, which the dev venv has.
pytest.importorskip("PIL", reason="Pillow is needed to synthesise frames")


def _ffmpeg() -> str | None:
    """Resolve ffmpeg the same way CameraCapture does, including the explicit override.

    GUARD_FFMPEG exists because the unit runs with ProtectSystem=strict and must not depend
    on the caller's PATH; on this dev box the winget shim is also not on PATH, so the
    override is how the ffmpeg-gated test becomes runnable locally at all.
    """
    return os.environ.get("GUARD_FFMPEG") or shutil.which("ffmpeg")


def _synthetic_h264(tmp_path: Path, seconds: int = 10) -> tuple[str, list[str]]:
    """Build a pre-encoded H.264 source, and the input flags to replay it as a camera.

    It has to be H.264, not lavfi straight into the capture command. Output 1 of that
    command is `-c:v copy`, and copying lavfi's rawvideo into mpegts produces nothing usable
    — that is precisely how an earlier capture test passed while being satisfied by a
    0-byte file. So the codec the ring copies must be the codec the camera actually sends.

    `-stream_loop -1` makes it endless and `-re` makes it play at wallclock rate, so the
    segment ring rolls at the same pace it would from the camera. Without `-re` ffmpeg
    consumes the file as fast as it can, which is how a 4-second clip once measured 393
    seconds long.
    """
    src = tmp_path / "synthetic.ts"
    subprocess.run(
        [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=15:duration={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
         "-pix_fmt", "yuv420p", "-g", "15", "-an", "-f", "mpegts", str(src)],
        check=True, capture_output=True,
    )
    assert src.stat().st_size > 0, "failed to build the synthetic source"
    return str(src), ["-stream_loop", "-1", "-re",
                      "-use_wallclock_as_timestamps", "1", "-fflags", "+genpts"]


def _jpeg(width: int = 320, height: int = 240, colour: int = 128) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    # Noise, not flat grey: a flat image has ~zero variance and the pipeline would
    # correctly call it limited_visibility, which is not what these tests are about.
    img = Image.new("RGB", (width, height), (colour, colour, colour))
    px = img.load()
    for y in range(0, height, 3):
        for x in range(0, width, 3):
            px[x, y] = (255, 255, 255)
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


class FakeClient:
    """A recording stand-in for paho's client.

    It implements only what the worker uses, and it records rather than asserts, so each
    test can ask its own question of the same captured traffic.
    """

    def __init__(self) -> None:
        self.published: list[tuple[str, dict, bool]] = []
        # When each message was published, so a test can assert on ORDER IN TIME — e.g.
        # that a clip arrived after the post-roll rather than inferring it from duration,
        # which at short segment lengths is dominated by ffmpeg startup jitter.
        self.at: list[float] = []
        self.subscribed: list[str] = []
        self.will: tuple[str, dict, bool] | None = None
        self.connected = False
        self.loop_running = False
        self.disconnected = False
        self.on_connect = None
        self.on_message = None

    # ── the paho surface the worker touches ──

    def will_set(self, topic, payload, qos=0, retain=False):
        self.will = (topic, json.loads(payload), retain)

    def reconnect_delay_set(self, **_kw):
        pass

    def connect(self, host, port, keepalive=60):
        self.connected = True
        if self.on_connect is not None:
            self.on_connect(self, None, {}, 0, None)

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, json.loads(payload), retain))
        self.at.append(time.monotonic())

    def loop_start(self):
        self.loop_running = True

    def loop_stop(self):
        self.loop_running = False

    def disconnect(self):
        self.disconnected = True

    # ── test helpers ──

    def deliver(self, topic: str, payload: dict) -> None:
        """Simulate the broker delivering a command, on the caller's thread."""
        class _Msg:
            pass

        msg = _Msg()
        msg.topic = topic
        msg.payload = json.dumps(payload).encode()
        msg.retain = False
        self.on_message(self, None, msg)

    def messages(self, leaf: str) -> list[dict]:
        return [p for t, p, _ in self.published if t.endswith(f"/guard/{leaf}")]

    def last(self, leaf: str) -> dict | None:
        msgs = self.messages(leaf)
        return msgs[-1] if msgs else None

    def first_time(self, leaf: str) -> float:
        """Monotonic time of the first message on `leaf`."""
        for (topic, _p, _r), at in zip(self.published, self.at):
            if topic.endswith(f"/guard/{leaf}"):
                return at
        raise AssertionError(f"nothing was ever published on {leaf}")


class FakeDetector:
    """Stands in for YoloOVDetector, returning its real dict shape with a fixed answer.

    The shape matters: `process_frame` distinguishes `occupied is None` (inference
    unavailable) from `occupied is False` (nothing there), and collapsing those would make
    a blind guard look like a quiet one. A fake that returned a bare list passed nothing —
    it raised, which is how this contract got checked at all.

    `unload()` sets `unloaded`, which is how TC-GSMOKE-07 checks the model is genuinely
    released on disarm rather than just flagged as released.
    """

    def __init__(self, *, confidence: float = 0.9, available: bool = True):
        self.available = available
        self.confidence = confidence
        self.unloaded = False
        self.calls = 0

    def detect_persons(self, jpeg, conf_threshold=0.2, **_kw) -> dict:
        self.calls += 1
        if not self.available:
            return {"occupied": None, "detections": [], "confidence": 0.0}
        if self.confidence < conf_threshold:
            return {"occupied": False, "detections": [], "confidence": 0.0,
                    "inference_ms": 1.0}
        return {
            "occupied": True,
            "confidence": self.confidence,
            "inference_ms": 1.0,
            "detections": [{
                "class_id": 0, "class_name": "person", "confidence": self.confidence,
                "bbox": {"x_c": 0.5, "y_c": 0.5, "w": 0.2, "h": 0.6},
                "bbox_xyxy": [0.4, 0.2, 0.6, 0.8],
            }],
        }

    def unload(self):
        self.unloaded = True
        self.available = False


@pytest.fixture
def cfg(tmp_path: Path) -> WorkerConfig:
    return WorkerConfig(
        marina_id="TST",
        camera_id=7,
        pedestal_id=7,
        # lavfi is the "synthetic source, not the camera" the smoke test requires. Only
        # TC-GSMOKE-05 actually starts ffmpeg; the rest just need a non-empty URL so run()
        # does not exit 2.
        stream_url="synthetic",
        storage_path=str(tmp_path / "recordings"),
        model_dir=str(tmp_path / "models"),
        segment_seconds=1,
        segment_ring=8,
        record_seconds=2,
        preroll_seconds=1,
        ffmpeg=_ffmpeg(),
    )


def _run_in_thread(worker: GuardWorker) -> tuple[threading.Thread, list[int]]:
    rc: list[int] = []
    t = threading.Thread(target=lambda: rc.append(worker.run()), daemon=True)
    t.start()
    return t, rc


def _wait(predicate, timeout: float = 10.0, what: str = "condition") -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


# ─── TC-GSMOKE-01 ────────────────────────────────────────────────────────────

def test_worker_starts_announces_and_stops_cleanly(cfg: WorkerConfig) -> None:
    """The whole assembly boots, talks to the broker, and stops on request.

    This is the test whose absence let a worker with no entrypoint pass CI. It asserts the
    four things the user named: it reaches a running state, it connects, it publishes its
    first status, and it shuts down cleanly.
    """
    client = FakeClient()
    worker = GuardWorker(cfg, client=client, detector_factory=FakeDetector)
    thread, rc = _run_in_thread(worker)

    _wait(lambda: worker.ready, what="the worker to report ready")
    assert client.connected, "the worker never connected to the broker"
    assert client.loop_running, "the MQTT network loop was never started"
    assert client.subscribed == ["marina/TST/camera/7/guard/cmd"], \
        f"expected exactly the cmd subscription, got {client.subscribed}"
    assert client.messages("state"), "the worker published no status at all"

    # Last Will must be registered BEFORE connecting, or a crash in the first seconds of a
    # run leaves no UNAVAILABLE behind.
    assert client.will is not None, "no Last Will was registered"
    will_topic, will_payload, will_retain = client.will
    assert will_topic == "marina/TST/camera/7/guard/state"
    assert will_payload["state"] == "UNAVAILABLE"
    assert will_retain is True, "a non-retained will teaches a late subscriber nothing"

    worker.stop()                       # exactly what the SIGTERM handler does
    thread.join(timeout=10)
    assert not thread.is_alive(), "the worker did not exit after being asked to stop"
    assert rc == [0], f"expected a clean exit code 0, got {rc}"
    assert client.disconnected, "the worker exited without disconnecting from the broker"
    assert not client.loop_running, "the MQTT network loop was left running"

    final = client.last("state")
    assert final["state"] == "OFF", \
        f"a stopped worker must not leave {final['state']!r} behind as its last word"
    assert final["reason"] == "worker stopped", \
        "a clean stop must be distinguishable from the LWT crash path"


# ─── TC-GSMOKE-02 ────────────────────────────────────────────────────────────

def test_first_published_state_is_off_and_retained(cfg: WorkerConfig) -> None:
    """A restarting worker must never announce itself as ARMED.

    Desired state lives in the backend. If the worker came up ARMED because it was ARMED
    before, a guard the watchdog had suspended would rearm itself just by restarting — and a
    retained ARMED would then be read by every late subscriber as the truth. This is the
    v3.40 retained-liveness lesson applied to guard.
    """
    client = FakeClient()
    worker = GuardWorker(cfg, client=client, detector_factory=FakeDetector)
    thread, _ = _run_in_thread(worker)
    _wait(lambda: worker.ready, what="the worker to report ready")

    first_topic, first_payload, first_retain = next(
        (t, p, r) for t, p, r in client.published if t.endswith("/guard/state"))
    assert first_payload["state"] == "OFF", \
        f"first announced state was {first_payload['state']!r}, must be OFF"
    assert first_retain is True, "state must be retained; it is the one topic that is"

    # And every other topic must NOT be retained — a retained alarm would replay an old
    # intrusion to the next subscriber as though it were happening now.
    for topic, _payload, retain in client.published:
        if not topic.endswith("/guard/state"):
            assert retain is False, f"{topic} was published retained; only state may be"

    worker.stop()
    thread.join(timeout=10)


# ─── TC-GSMOKE-03 ────────────────────────────────────────────────────────────

def _stub_paho_dir(tmp_path: Path, log_path: Path) -> Path:
    """Write a stub `paho.mqtt.client` that logs publishes to a file.

    This lets a REAL subprocess run the real module — imports, config parsing, main(),
    signal registration and the loop — with no broker anywhere. Without it the module-entry
    tests would need a live mosquitto, which is exactly the kind of dependency that gets a
    test skipped and then quietly stops covering anything.
    """
    pkg = tmp_path / "stub" / "paho" / "mqtt"
    pkg.mkdir(parents=True)
    (tmp_path / "stub" / "paho" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "client.py").write_text(textwrap.dedent(f"""
        import enum, json

        LOG = open(r"{log_path}", "a", encoding="utf-8", buffering=1)

        class CallbackAPIVersion(enum.Enum):
            VERSION2 = 2

        class Client:
            def __init__(self, *a, **kw):
                self.on_connect = None
                self.on_message = None
            def will_set(self, topic, payload, qos=0, retain=False):
                LOG.write(json.dumps({{"kind": "will", "topic": topic,
                                       "payload": json.loads(payload)}}) + "\\n")
            def reconnect_delay_set(self, **kw): pass
            def connect(self, host, port, keepalive=60):
                LOG.write(json.dumps({{"kind": "connect", "host": host,
                                       "port": port}}) + "\\n")
                if self.on_connect: self.on_connect(self, None, {{}}, 0, None)
            def subscribe(self, topic, qos=0):
                LOG.write(json.dumps({{"kind": "subscribe", "topic": topic}}) + "\\n")
            def publish(self, topic, payload, qos=0, retain=False):
                LOG.write(json.dumps({{"kind": "publish", "topic": topic, "retain": retain,
                                       "payload": json.loads(payload)}}) + "\\n")
            def loop_start(self): pass
            def loop_stop(self): pass
            def disconnect(self):
                LOG.write(json.dumps({{"kind": "disconnect"}}) + "\\n")
    """))
    return tmp_path / "stub"


def _module_env(tmp_path: Path, stub: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(stub), str(REPO), str(REPO / "backend")])
    env.update({
        "MARINA_ID": "TST",
        "GUARD_CAMERA_ID": "7",
        "GUARD_STREAM_URL": "synthetic",
        "GUARD_STORAGE_PATH": str(tmp_path / "recordings"),
        "GUARD_MODEL_DIR": str(tmp_path / "models"),
        "GUARD_LOG_LEVEL": "INFO",
    })
    env.pop("PYTHONWARNINGS", None)
    return env


def _read_log(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    return [json.loads(line) for line in
            log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_module_entry_actually_executes(tmp_path: Path) -> None:
    """`python -m guard_worker` runs. Nothing else in the suite asserted this.

    The value here is mostly the boring half: a missing `__main__.py`, an import that only
    resolves under pytest's sys.path, a typo in `main()` — all of which pass unit tests and
    fail at `systemctl start`.
    """
    log = tmp_path / "mqtt.jsonl"
    stub = _stub_paho_dir(tmp_path, log)

    proc = subprocess.Popen(
        [sys.executable, "-m", "guard_worker"],
        cwd=str(REPO), env=_module_env(tmp_path, stub),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        _wait(lambda: any(e["kind"] == "publish" for e in _read_log(log)),
              timeout=30, what="the module to publish its first state")
    finally:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()

    events = _read_log(log)
    kinds = [e["kind"] for e in events]
    assert "connect" in kinds, f"the module never tried to connect. Output:\n{out}"
    assert "will" in kinds, "the module connected without registering a Last Will"
    assert "subscribe" in kinds, "the module never subscribed to its command topic"

    subs = [e["topic"] for e in events if e["kind"] == "subscribe"]
    assert subs == ["marina/TST/camera/7/guard/cmd"], \
        f"env-driven topics are wrong: {subs}"

    states = [e for e in events if e["kind"] == "publish"
              and e["topic"].endswith("/guard/state")]
    assert states, f"no state was published. Output:\n{out}"
    assert states[0]["payload"]["state"] == "OFF"
    assert states[0]["retain"] is True


# ─── TC-GSMOKE-04 ────────────────────────────────────────────────────────────

def _graceful_signal(proc: subprocess.Popen) -> None:
    if os.name == "nt":
        proc.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        proc.send_signal(signal.SIGTERM)


def test_real_signal_shuts_the_subprocess_down_cleanly(tmp_path: Path) -> None:
    """A real graceful signal to a real process: exit 0, and a final OFF on the way out.

    systemd stops the unit with SIGTERM. If the handler deadlocked or the loop ignored it,
    every `systemctl restart` would take the 90 s TimeoutStopSec and then get SIGKILL — and
    a SIGKILLed worker leaves the LWT behind, so guard would read UNAVAILABLE after every
    ordinary restart. On Windows the equivalent graceful signal is CTRL_BREAK, which is why
    the worker registers SIGBREAK as well.
    """
    log = tmp_path / "mqtt.jsonl"
    stub = _stub_paho_dir(tmp_path, log)
    creation = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0

    proc = subprocess.Popen(
        [sys.executable, "-m", "guard_worker"],
        cwd=str(REPO), env=_module_env(tmp_path, stub),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        creationflags=creation,
    )
    try:
        _wait(lambda: any(e["kind"] == "publish" for e in _read_log(log)),
              timeout=30, what="the worker to come up before signalling it")
        _graceful_signal(proc)
        rc = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        raise AssertionError(
            "the worker ignored a graceful signal and had to be killed — under systemd "
            f"every restart would hit TimeoutStopSec. Output:\n{out}"
        )
    out, _ = proc.communicate()

    assert rc == 0, f"graceful signal gave exit code {rc}, expected 0. Output:\n{out}"

    events = _read_log(log)
    assert any(e["kind"] == "disconnect" for e in events), \
        f"the worker exited without a clean MQTT disconnect. Output:\n{out}"
    states = [e["payload"] for e in events if e["kind"] == "publish"
              and e["topic"].endswith("/guard/state")]
    assert states[-1]["state"] == "OFF"
    assert states[-1]["reason"] == "worker stopped", (
        "the last state before a clean exit must say it was a stop, not leave the reader "
        f"guessing: {states[-1]}"
    )


# ─── TC-GSMOKE-05 ────────────────────────────────────────────────────────────

@pytest.mark.skipif(_ffmpeg() is None,
                    reason="needs ffmpeg (set GUARD_FFMPEG to the binary)")
def test_arm_to_alarm_to_clip_through_the_real_loop(cfg: WorkerConfig) -> None:
    """The full armed path, driven by the real loop against a synthetic video source.

    lavfi generates the frames, so no camera and no marina LAN is involved, but everything
    downstream is production code: ffmpeg segmenting, the JPEG pipe, crop, visibility,
    banding, the alarm rule, pinning, deferred assembly, and the publish contract.

    The assertions that matter most are the last two. Clip assembly is deferred because
    `select_segments` spans `alarm_at + record_seconds` and that footage does not exist yet
    when the alarm fires; an immediate assembly would produce a pre-roll-only clip and still
    look like a success. So this checks the deferral DIRECTLY — the recording message arrives
    at least `record_seconds` after the alarm — rather than inferring it from clip duration,
    which at one-second segments is dominated by ffmpeg startup jitter and would make the
    test flaky while appearing to check the right thing.
    """
    client = FakeClient()
    detector = FakeDetector(confidence=0.95)
    # Roomier than the fixture default so the clip spans several segments; the tight
    # defaults make duration a measure of startup jitter, not of what was recorded.
    cfg.record_seconds, cfg.preroll_seconds, cfg.segment_seconds = 4, 2, 1
    cfg.stream_url, cfg.input_args = _synthetic_h264(Path(cfg.storage_path).parent)
    worker = GuardWorker(cfg, client=client, detector_factory=lambda: detector)
    thread, rc = _run_in_thread(worker)
    _wait(lambda: worker.ready, what="the worker to come up")

    client.deliver("marina/TST/camera/7/guard/cmd", {
        "cmd": "arm", "req_id": "smoke-1",
        "config": {"config_version": 4, "conf_threshold": 0.5, "uncertain_min": 0.2,
                   "fps": 4, "window_seconds": 4, "frames_required": 2,
                   "cooldown_seconds": 1, "zone": [0.0, 0.0, 1.0, 1.0],
                   "visibility_min_luma": 1.0, "visibility_min_variance": 0.1},
    })

    try:
        _wait(lambda: client.messages("ack"), what="an ack for the arm command")
        ack = client.last("ack")
        assert ack["accepted"] is True, f"arm was refused: {ack}"
        assert ack["config_version"] == 4

        _wait(lambda: worker.state == "ARMED", what="the worker to report ARMED")
        _wait(lambda: detector.calls >= 2, timeout=30,
              what="frames to reach the detector from ffmpeg")

        _wait(lambda: client.messages("alarm"), timeout=30, what="an alarm to be raised")
        alarm = client.messages("alarm")[0]
        assert alarm["confidence"] == pytest.approx(0.95)
        assert alarm["pedestal_id"] == 7
        assert alarm["bbox"] == [0.4, 0.2, 0.6, 0.8]
        assert alarm["trigger"] == "2_in_4s"
        # A clip is coming, so the event must not be marked as having no video.
        assert alarm["video_skipped"] is False, \
            "an alarm with a clip pending must not claim the video was skipped"
        assert alarm["video_path"] is None, \
            "the alarm cannot know the clip path yet — recording backfills it"

        _wait(lambda: client.messages("detection"), timeout=20,
              what="the detection batch to be published")
        det = client.messages("detection")[0]["detections"]
        assert det, "an alarm was raised but no detection rows were published"
        assert any(d["band"] == "alarm" for d in det)
        assert any(d.get("event_uuid") == alarm["event_uuid"] for d in det), \
            "the contributing detections were not linked to the event"

        _wait(lambda: client.messages("recording"), timeout=90,
              what="the clip to be assembled after the post-roll")
        rec = client.last("recording")
        assert rec["event_uuid"] == alarm["event_uuid"], \
            "the clip is not linked to the alarm, so the backend cannot backfill it"
        clip = Path(rec["file_path"])
        assert clip.exists(), f"the published clip path does not exist: {clip}"
        assert rec["file_size"] > 0, "a zero-byte clip is not a clip"
        assert clip.stat().st_size == rec["file_size"]
        assert not clip.name.endswith(".part"), \
            "a .part path was published — the atomic rename did not happen"

        # The deferral itself, measured rather than inferred.
        waited = client.first_time("recording") - client.first_time("alarm")
        assert waited >= cfg.record_seconds, (
            f"the clip was published {waited:.1f}s after the alarm, less than the "
            f"{cfg.record_seconds}s post-roll — it cannot contain post-alarm footage, so "
            f"assembly ran too early"
        )
        # And it is longer than one segment, so it is real footage either side of the alarm
        # rather than a single leftover segment that happened to be lying about.
        assert rec["duration_s"] is None or rec["duration_s"] > cfg.segment_seconds, (
            f"clip is {rec['duration_s']}s, no longer than a single "
            f"{cfg.segment_seconds}s segment"
        )
    finally:
        worker.stop()
        thread.join(timeout=30)

    assert rc == [0]
    assert detector.unloaded, "the model was not released on shutdown"


# ─── TC-GSMOKE-06 ────────────────────────────────────────────────────────────

def test_arm_without_a_detector_is_refused_not_crashed(cfg: WorkerConfig) -> None:
    """No model on the box: the arm is acked as refused and the worker keeps running.

    This is the shape of a real first deployment where the IR export has not been copied
    across yet. If the worker died instead, the operator would see UNAVAILABLE with no
    reason and no process to ask.
    """
    client = FakeClient()
    worker = GuardWorker(cfg, client=client,
                         detector_factory=lambda: FakeDetector(available=False))
    thread, rc = _run_in_thread(worker)
    _wait(lambda: worker.ready, what="the worker to come up")

    client.deliver("marina/TST/camera/7/guard/cmd", {
        "cmd": "arm", "req_id": "no-model", "config": {"config_version": 1},
    })
    _wait(lambda: client.messages("ack"), what="an ack for the refused arm")

    ack = client.last("ack")
    assert ack["accepted"] is False, "arming without a model must not be acked as accepted"
    assert ack["req_id"] == "no-model"
    assert "detector unavailable" in (ack["reason"] or ""), \
        f"the refusal must say why: {ack}"
    assert worker.state != "ARMED"
    assert thread.is_alive(), "a refused arm killed the worker"

    worker.stop()
    thread.join(timeout=10)
    assert rc == [0], "the worker did not exit cleanly after refusing an arm"


# ─── TC-GSMOKE-07 ────────────────────────────────────────────────────────────

@pytest.mark.skipif(_ffmpeg() is None,
                    reason="needs ffmpeg (set GUARD_FFMPEG to the binary)")
def test_disarm_releases_the_model_and_the_capture_process(cfg: WorkerConfig) -> None:
    """Disarmed means nothing is running — checkable, not asserted by a flag.

    "Guard OFF costs nothing" is the promise the whole phase rests on, so the test looks at
    the ffmpeg process and the detector object, not at `worker.state`.
    """
    client = FakeClient()
    detector = FakeDetector()
    cfg.stream_url, cfg.input_args = _synthetic_h264(
        Path(cfg.storage_path).parent, seconds=5)
    worker = GuardWorker(cfg, client=client, detector_factory=lambda: detector)
    thread, rc = _run_in_thread(worker)
    _wait(lambda: worker.ready, what="the worker to come up")

    client.deliver("marina/TST/camera/7/guard/cmd", {
        "cmd": "arm", "req_id": "a1",
        "config": {"config_version": 1, "conf_threshold": 0.5, "uncertain_min": 0.2,
                   "fps": 2, "zone": [0.0, 0.0, 1.0, 1.0],
                   "visibility_min_luma": 1.0, "visibility_min_variance": 0.1},
    })
    _wait(lambda: worker.state == "ARMED", what="ARMED")
    _wait(lambda: worker.supervisor is not None
          and worker.supervisor.capture is not None
          and worker.supervisor.capture.is_running,
          timeout=30, what="ffmpeg to be running")
    ffmpeg_pid = worker.supervisor.capture.pid
    assert ffmpeg_pid is not None

    client.deliver("marina/TST/camera/7/guard/cmd",
                   {"cmd": "disarm", "req_id": "d1", "config": {}})
    _wait(lambda: worker.state == "OFF", timeout=30, what="the worker to report OFF")

    assert detector.unloaded, "the model was not released on disarm"
    assert worker.detector is None, "a disarmed worker still holds a detector reference"
    assert worker.supervisor is None, "a disarmed worker still holds a capture supervisor"
    assert worker.frames is None, "the frame generator was left open"

    # And the ffmpeg process itself is gone, not merely dereferenced.
    _wait(lambda: not _pid_alive(ffmpeg_pid), timeout=20,
          what=f"ffmpeg pid {ffmpeg_pid} to exit")

    worker.stop()
    thread.join(timeout=20)
    assert rc == [0]


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True,
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
