"""
Guard INTEGRATION — the backend and the worker on a real broker (v3.42)
======================================================================

Why this file exists. Until now the two halves of guard had never exchanged a message. The
smoke suite drives the real worker against a **fake broker**; the API suite drives the real
backend against a **fake worker**. Each half was verified against a stand-in for the other,
so every field name that matched did so because I read it, not because a broker carried it.
That is the same shape of gap as the missing entrypoint: components green, assembly
unproven.

So here both halves run for real:

  * a **real mosquitto** — the same broker software the NUC runs in compose;
  * the **real backend MQTT client** (`MQTTService`, its real `TOPICS`, its real
    `_on_message` → `handle_message` → guard handlers → SQLAlchemy);
  * the **real worker as a separate OS process** (`_guard_worker_harness.py`), which is the
    only way a Last Will can be observed at all — a will is published by the broker when a
    connection drops without DISCONNECT, so the worker has to be killable.

Substituted: the detector (no 32-bit OpenVINO wheel) and the camera (a pre-encoded H.264
file replayed at wallclock rate). Nothing else.

  TC-GINT-01  the worker announces itself and the backend sees it, retained, as OFF
  TC-GINT-02  a real command crosses the wire, is parsed, and is acked inside the timeout
  TC-GINT-03  arm -> frames -> alarm -> persisted event -> clip -> labelled, end to end
  TC-GINT-04  detections persist as a batch and link to the event that fired
  TC-GINT-05  the worker is KILLED: the broker's Last Will makes the backend say UNAVAILABLE
  TC-GINT-06  a command sent while the worker is down is never acked and goes overdue
  TC-GINT-07  an ack that never arrives does not leave a false ARMED behind
  TC-GINT-08  the refusal mechanism: a skip says it is not a pass, and
              GUARD_INTEGRATION_REQUIRED=1 makes it fatal

Running this on the NUC: the compose broker on :1883 is used automatically. See
`docs/guard_deploy_runbook.md` §2.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from conftest import TestSession as _S  # noqa: E402
from guard_worker.capture import resolve_ffmpeg  # noqa: E402

HARNESS = Path(__file__).parent / "_guard_worker_harness.py"

# A camera id used by no other test module, so liveness and DB rows cannot collide.
CAM = 11

# Set GUARD_INTEGRATION_REQUIRED=1 on the NUC. See _unanswered() below.
INTEGRATION_REQUIRED = os.environ.get("GUARD_INTEGRATION_REQUIRED") == "1"


def _unanswered(reason: str, remedy: str) -> None:
    """Refuse to answer — loudly, and fatally where an answer was required.

    The two things that can stop this suite (no broker, no ffmpeg) are both real deployment
    conditions on the NUC, and both look like success in a pytest summary line. So the message
    says what a skip means here, at the point of skipping, because the person running it on a
    pier has not read the runbook.

    With GUARD_INTEGRATION_REQUIRED=1 it does not skip at all — it fails. That is how the
    runbook invokes it, so a missing broker cannot be mistaken for a green deployment.
    """
    verdict = (
        "INTEGRATION NOT RUN — this is a FAILURE TO REPORT, not a pass. "
        "The backend and the worker were never shown to exchange a message."
    )
    if INTEGRATION_REQUIRED:
        pytest.fail(f"{verdict}\n  Reason: {reason}\n  Fix: {remedy}")
    pytest.skip(
        f"{reason} — {verdict} Fix: {remedy}. "
        f"Set GUARD_INTEGRATION_REQUIRED=1 to make this a hard failure (the NUC does)."
    )

pytestmark = pytest.mark.asyncio


# ─── broker ──────────────────────────────────────────────────────────────────

def _reachable(host: str, port: int, timeout: float = 1.0) -> bool:
    with closing(socket.socket()) as s:
        s.settimeout(timeout)
        try:
            s.connect((host, port))
            return True
        except OSError:
            return False


def _free_port() -> int:
    with closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _mosquitto_bin() -> str | None:
    """Resolve the mosquitto binary, override first — same pattern as GUARD_FFMPEG."""
    override = os.environ.get("MOSQUITTO_BIN")
    if override and (Path(override).is_file() or shutil.which(override)):
        return override
    found = shutil.which("mosquitto")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\mosquitto\mosquitto.exe",
        "/usr/sbin/mosquitto",
        "/usr/bin/mosquitto",
        "/usr/local/sbin/mosquitto",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


@pytest.fixture(scope="module")
def broker(tmp_path_factory) -> dict:
    """A real broker.

    Preference order, and the reason for it:

    1. **An already-running broker** at GUARD_TEST_BROKER_HOST/PORT, default localhost:1883.
       That is the NUC case — compose already runs `eclipse-mosquitto:2.0` there, and the
       whole point of this suite is that it runs where it matters.
    2. **A private mosquitto** on an ephemeral port. That is the dev-box case, and it keeps
       the suite from touching a broker that carries real cabinet traffic.

    Skipping is the last resort and is reported, never silent: a skipped integration test is
    the unanswered question this file was written to answer.
    """
    host = os.environ.get("GUARD_TEST_BROKER_HOST", "localhost")
    port = int(os.environ.get("GUARD_TEST_BROKER_PORT", "1883"))

    if _reachable(host, port):
        yield {"host": host, "port": port, "own": False}
        return

    exe = _mosquitto_bin()
    if exe is None:
        _unanswered(
            f"no broker: nothing is listening on {host}:{port} and no mosquitto binary "
            f"was found",
            "start the compose broker with `sudo docker compose up -d mosquitto`, "
            "or set MOSQUITTO_BIN to a mosquitto executable",
        )

    tmp = tmp_path_factory.mktemp("mosquitto")
    own_port = _free_port()
    conf = tmp / "mosquitto.conf"
    # allow_anonymous matches the production broker's configuration; this suite is not the
    # place to test broker auth, and pretending otherwise would test the fixture.
    conf.write_text(f"listener {own_port}\nallow_anonymous true\n")
    log = open(tmp / "mosquitto.log", "w")
    proc = subprocess.Popen([exe, "-c", str(conf), "-v"], stdout=log, stderr=log)

    deadline = time.time() + 15
    while time.time() < deadline:
        if _reachable("127.0.0.1", own_port):
            break
        if proc.poll() is not None:
            log.close()
            pytest.fail(f"mosquitto exited: {(tmp / 'mosquitto.log').read_text()[-2000:]}")
        time.sleep(0.1)
    else:
        proc.kill()
        log.close()
        pytest.fail("mosquitto did not start within 15s")

    yield {"host": "127.0.0.1", "port": own_port, "own": True}

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    log.close()


# ─── the backend half, on the real broker ────────────────────────────────────

@pytest_asyncio.fixture
async def backend(broker):
    """The REAL backend MQTT client, subscribed to the real broker.

    Two details that are easy to get wrong:

    * `MQTTService.start(mqtt_service, loop)` is called through the CLASS on purpose.
      conftest's session-scoped `client` fixture patches `mqtt_service.start` on the
      instance, and calling the class function bypasses that shadowing so the real code
      runs. Using the singleton matters because `publish_command` publishes through it.
    * `app.database.SessionLocal` is patched for the whole fixture, because the guard
      handlers open their own sessions on paho's thread. `unittest.mock.patch` replaces a
      module attribute process-wide, so the patch holds across threads.
    """
    from app.config import settings
    from app.guard.service import liveness
    from app.services.mqtt_client import MQTTService, mqtt_service

    async def _noop_broadcast(*_a, **_kw):
        return None

    _clean_db()
    liveness.forget(CAM)
    liveness._pending_acks.clear()
    _clear_retained_state(broker, settings.marina_id)

    with patch.object(settings, "mqtt_broker_host", broker["host"]), \
         patch.object(settings, "mqtt_broker_port", broker["port"]), \
         patch("app.database.SessionLocal", _S), \
         patch("app.guard.service.SessionLocal", _S, create=True), \
         patch("app.services.websocket_manager.ws_manager.broadcast",
               new=_noop_broadcast):

        MQTTService.start(mqtt_service, asyncio.get_running_loop())
        try:
            await _await(lambda: mqtt_service.is_connected,
                         what="the backend MQTT client to connect")
            # Subscriptions are issued in _on_connect; give the SUBACKs a moment so a
            # command published immediately is not missed by our own subscription.
            await asyncio.sleep(0.3)
            yield {"marina": settings.marina_id, **broker}
        finally:
            MQTTService.stop(mqtt_service)
            liveness.forget(CAM)
            liveness._pending_acks.clear()
            # Leave no will behind for the next test to be fooled by.
            _clear_retained_state(broker, settings.marina_id)


def _clear_retained_state(broker_info: dict, marina: str) -> None:
    """Wipe the retained `guard/state` for this camera before a test.

    Without this, a Last Will left on the broker by an earlier test is replayed to every new
    subscriber — and that is not hypothetical: it fooled this very suite. The retained
    UNAVAILABLE satisfied a "the worker is up" predicate, so a command went out while the
    worker was still booting and unsubscribed, and QoS 1 with no matching subscription drops
    the message silently. The v3.40 bug, reproduced inside its own regression test.

    A zero-length payload with retain set is the MQTT way to clear a retained message.
    `mqtt_service.publish()` cannot do it — it takes no `retain` argument, deliberately — so
    this uses its own short-lived client rather than widening production code for a test.
    """
    import paho.mqtt.client as mqtt

    topic = f"marina/{marina}/camera/{CAM}/guard/state"
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"int-clear-{CAM}")
    c.connect(broker_info["host"], broker_info["port"], 30)
    c.loop_start()
    try:
        c.publish(topic, b"", qos=1, retain=True).wait_for_publish(timeout=10)
    finally:
        c.loop_stop()
        c.disconnect()


async def _worker_up(worker: "Worker") -> None:
    """Wait until the worker has proved it is LIVE, not merely that a state exists.

    `liveness.is_alive` is the right predicate because `mark_seen` is called only for
    non-retained messages, so a replayed will cannot satisfy it. Waiting on
    `reported(CAM)["state"] is not None` — the obvious version — is satisfied by a retained
    replay from a worker that is already dead.
    """
    from app.guard.service import liveness

    await _await(lambda: liveness.is_alive(CAM)
                 and liveness.reported(CAM).get("state") == "OFF",
                 timeout=30, what="the worker to announce itself with LIVE traffic",
                 diagnose=worker.output)


def _clean_db() -> None:
    from app.guard.models import GuardConfig, GuardDetection, GuardEvent, GuardRecording

    db = _S()
    try:
        for model in (GuardDetection, GuardRecording, GuardEvent):
            db.query(model).filter(model.camera_id == CAM).delete()
        db.query(GuardConfig).filter(GuardConfig.camera_id == CAM).delete()
        db.commit()
    finally:
        db.close()


async def _await(predicate, timeout: float = 20.0, what: str = "condition",
                 diagnose=None) -> None:
    """Wait on a condition without blocking the event loop the handlers run on.

    `diagnose` is a CALLABLE, not a string, and that is the point: an f-string argument is
    evaluated before the wait begins, so it captures the worker log as it was at t=0 —
    always empty, which is exactly how I spent three runs blind to a worker that was dying
    on startup. Read the evidence at failure time or do not read it.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    extra = f"\n{diagnose()}" if diagnose is not None else ""
    raise AssertionError(f"timed out after {timeout}s waiting for {what}{extra}")


# ─── the worker half, as a real process ──────────────────────────────────────

class Worker:
    def __init__(self, proc: subprocess.Popen, log: Path):
        self.proc = proc
        self.log = log

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def output(self) -> str:
        """Everything known about the worker, for a failure message.

        Includes the exit code: a worker that died on startup is the single most likely
        cause of any timeout here, and without the code it looks identical to a worker that
        is running but silent.
        """
        try:
            log = self.log.read_text(errors="replace")[-4000:]
        except OSError as exc:
            log = f"<could not read {self.log}: {exc}>"
        rc = self.proc.poll()
        state = "running" if rc is None else f"EXITED with code {rc}"
        return f"--- worker ({state}, pid {self.proc.pid}) ---\n{log or '<no output>'}"

    def kill_hard(self) -> None:
        """SIGKILL equivalent — no handler runs, no DISCONNECT is sent.

        This is what makes the broker publish the Last Will, and it is why the worker has to
        be a separate process: `terminate()` would let the worker shut down cleanly and
        publish its own OFF instead, which tests the opposite property.
        """
        self.proc.kill()
        self.proc.wait(timeout=15)

    def stop_clean(self) -> None:
        if self.alive:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)


def _start_worker(backend_info: dict, tmp_path: Path, *, source: str = "",
                  detector: str = "available", confidence: float = 0.95) -> Worker:
    log_path = tmp_path / "worker.log"
    log = open(log_path, "w")
    cmd = [
        # -u matters: the harness logs to stderr, and stderr redirected to a file is
        # block-buffered, so without it a failing test reports an empty worker log and the
        # diagnosis has to be guessed at.
        sys.executable, "-u", str(HARNESS),
        "--broker-host", backend_info["host"],
        "--broker-port", str(backend_info["port"]),
        "--marina", backend_info["marina"],
        "--camera", str(CAM),
        "--storage", str(tmp_path / "recordings"),
        "--detector", detector,
        "--confidence", str(confidence),
    ]
    if source:
        cmd += ["--source", source]
    ff = resolve_ffmpeg()
    if ff:
        cmd += ["--ffmpeg", ff]
    proc = subprocess.Popen(cmd, cwd=str(REPO), stdout=log, stderr=subprocess.STDOUT)
    return Worker(proc, log_path)


def _synthetic_h264(tmp_path: Path, seconds: int = 8) -> str:
    """A pre-encoded H.264 file standing in for the camera.

    H.264 and not lavfi: the capture ring's first output is `-c:v copy`, and copying
    rawvideo into mpegts produces nothing usable — which is how an earlier capture test came
    to be satisfied by a 0-byte file. The codec the ring copies must be the codec the camera
    actually sends.
    """
    src = tmp_path / "camera.ts"
    subprocess.run(
        [resolve_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"testsrc=size=320x240:rate=15:duration={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
         "-pix_fmt", "yuv420p", "-g", "15", "-an", "-f", "mpegts", str(src)],
        check=True, capture_output=True, timeout=180,
    )
    return str(src)


def _status() -> dict:
    """What `/api/guard/status` would report for this camera."""
    from app.guard.service import effective_state, get_or_create_config

    db = _S()
    try:
        cfg = get_or_create_config(db, CAM, pedestal_id=CAM)
        return effective_state(db, cfg)
    finally:
        db.close()


def _command(cmd: str) -> str:
    from app.guard.service import get_or_create_config, publish_command

    db = _S()
    try:
        cfg = get_or_create_config(db, CAM, pedestal_id=CAM)
        if cmd in ("arm", "rearm"):
            cfg.desired_state = "ARMED"
        elif cmd == "disarm":
            cfg.desired_state = "OFF"
        db.commit()
        return publish_command(db, cfg, cmd, actor="integration-test")
    finally:
        db.close()


def _need_ffmpeg() -> None:
    """Called inside the test, not as a skipif marker.

    A marker can only ever skip; this routes through `_unanswered`, so on the NUC — where
    ffmpeg is genuinely missing from the installer — the absence fails the run instead of
    quietly shrinking it.
    """
    if resolve_ffmpeg() is None:
        _unanswered(
            "no ffmpeg, so there is no synthetic camera and no frames",
            "`sudo apt install -y ffmpeg` (it is absent from the NUC installer), "
            "or set GUARD_FFMPEG to the binary",
        )


# ═══ TC-GINT-01 ══════════════════════════════════════════════════════════════

async def test_worker_announces_itself_over_a_real_broker(backend, tmp_path):
    """The worker comes up, the backend hears it, and what it hears is OFF.

    This is the first time these two processes have exchanged anything. It also pins the
    property that matters on every restart: the worker announces OFF and waits, so a guard
    the watchdog suspended cannot rearm itself by restarting.
    """
    worker = _start_worker(backend, tmp_path)
    try:
        from app.guard.service import liveness

        await _worker_up(worker)

        reported = liveness.reported(CAM)
        assert reported["state"] == "OFF", \
            f"a restarting worker must announce OFF, not {reported['state']!r}"
        assert liveness.is_alive(CAM), "live traffic did not mark the worker as alive"

        status = _status()
        assert status["state"] == "OFF"
        assert status["worker_alive"] is True
        assert status["worker_seen_at"] is not None
    finally:
        worker.stop_clean()


# ═══ TC-GINT-02 ══════════════════════════════════════════════════════════════

async def test_command_crosses_the_wire_and_is_acked_in_time(backend, tmp_path):
    """The backend's cmd payload is one the worker actually parses, and the ack comes back.

    Unproven until now: every field name in `config_payload()` was matched to the worker's
    reader by reading both. `disarm` is used rather than `arm` so this holds with no camera
    and no ffmpeg — the question here is the contract, not the capture.

    The ack timing is asserted against the real `guard_ack_timeout_s`, because that timeout
    is what stops the UI sitting on ARMING forever.
    """
    from app.config import settings
    from app.guard.service import liveness

    worker = _start_worker(backend, tmp_path)
    try:
        await _worker_up(worker)

        sent_at = time.time()
        req_id = _command("disarm")
        assert any(r == req_id for r, _c in liveness.overdue_acks(sent_at + 10_000)), \
            "publish_command did not register an expected ack"

        await _await(lambda: not any(r == req_id for r, _c
                                     in liveness.overdue_acks(time.time() + 10_000)),
                     timeout=15,
                     what=f"an ack for {req_id}", diagnose=worker.output)
        elapsed = time.time() - sent_at

        assert elapsed < settings.guard_ack_timeout_s, (
            f"the ack took {elapsed:.1f}s, over the {settings.guard_ack_timeout_s}s timeout "
            f"the ack watchdog uses — the UI would have been told UNAVAILABLE first"
        )
        # And the worker's own view came back with it.
        assert liveness.reported(CAM)["state"] == "OFF"
    finally:
        worker.stop_clean()


# ═══ TC-GINT-03 ══════════════════════════════════════════════════════════════

async def test_arm_to_alarm_to_persisted_event_to_labelled(backend, tmp_path):
    """The whole round trip, both processes, one broker.

    arm -> ffmpeg -> pipeline -> alarm rule -> MQTT -> backend persists a GuardEvent ->
    the clip arrives after the post-roll and is backfilled onto that event -> it is labelled.

    This is the test that proves the payloads, not just the topics. Every assertion below is
    a field that was previously matched by reading a file rather than by carrying it over a
    wire.
    """
    _need_ffmpeg()
    from app.guard.models import GuardEvent, GuardRecording

    source = _synthetic_h264(tmp_path)
    worker = _start_worker(backend, tmp_path, source=source)
    try:
        from app.guard.service import liveness

        await _worker_up(worker)
        _command("arm")

        await _await(lambda: liveness.reported(CAM).get("state") in ("ARMED", "RECORDING"),
                     timeout=30,
                     what="the worker to report ARMED", diagnose=worker.output)

        # ── the alarm is persisted ──
        def _event():
            db = _S()
            try:
                return db.query(GuardEvent).filter(GuardEvent.camera_id == CAM).first()
            finally:
                db.close()

        await _await(lambda: _event() is not None, timeout=60,
                     what="an alarm to be persisted", diagnose=worker.output)

        ev = _event()
        assert ev.event_uuid, "no event_uuid crossed the wire — idempotency would be broken"
        assert ev.pedestal_id == CAM
        assert ev.confidence == pytest.approx(0.95, abs=0.01)
        assert ev.px_height and ev.px_height > 0, \
            "px_height did not survive the wire; the distance check depends on it"
        assert json.loads(ev.bbox) == [0.4, 0.2, 0.6, 0.8], \
            "bbox is stored as JSON by the backend; it did not round-trip"
        assert ev.trigger == "2_in_4s"
        assert ev.detected_at_utc is not None
        assert ev.detected_at_local, "the local timestamp is what the operator reads"
        assert ev.video_skipped is False, \
            "a clip was coming, so the event must not claim the video was skipped"

        # ── the clip follows, and is linked back onto the event ──
        event_uuid = ev.event_uuid

        def _recording():
            db = _S()
            try:
                return db.query(GuardRecording).filter(
                    GuardRecording.event_uuid == event_uuid).first()
            finally:
                db.close()

        await _await(lambda: _recording() is not None, timeout=90,
                     what="the clip to be assembled and persisted.",
                     diagnose=worker.output)

        rec = _recording()
        assert rec.file_size and rec.file_size > 0, "a zero-byte clip is not a clip"
        assert Path(rec.file_path).exists(), \
            f"the persisted path does not exist on disk: {rec.file_path}"
        assert not rec.file_path.endswith(".part"), \
            "a .part path was persisted — the atomic rename did not happen"

        db = _S()
        try:
            ev2 = db.query(GuardEvent).filter(GuardEvent.event_uuid == event_uuid).first()
            assert ev2.video_path == rec.file_path, \
                "the recording did not backfill onto its event, so the dashboard row has no link"
            assert ev2.video_skipped is False
        finally:
            db.close()

        # ── and it can be labelled, which is the point of the whole watching week ──
        db = _S()
        try:
            ev3 = db.query(GuardEvent).filter(GuardEvent.event_uuid == event_uuid).first()
            ev3.label = "false_alarm"
            ev3.label_note = "integration test"
            ev3.labelled_by = "integration@test"
            db.commit()
            assert db.query(GuardEvent).filter(
                GuardEvent.event_uuid == event_uuid).first().label == "false_alarm"
        finally:
            db.close()
    finally:
        worker.stop_clean()


# ═══ TC-GINT-04 ══════════════════════════════════════════════════════════════

async def test_detections_persist_as_a_batch_and_link_to_their_event(backend, tmp_path):
    """Below-threshold evidence survives the wire, and links to the alarm it fed.

    These rows are the accuracy numbers the A.5 run could not produce and the Phase 2
    training index. They are batch-published, so this also proves the batch shape — a list
    under `detections`, not one message per frame.
    """
    _need_ffmpeg()
    from app.guard.models import GuardDetection, GuardEvent

    source = _synthetic_h264(tmp_path)
    worker = _start_worker(backend, tmp_path, source=source)
    try:
        from app.guard.service import liveness

        await _worker_up(worker)
        _command("arm")

        def _rows():
            db = _S()
            try:
                return db.query(GuardDetection).filter(
                    GuardDetection.camera_id == CAM).all()
            finally:
                db.close()

        await _await(lambda: len(_rows()) >= 2, timeout=60,
                     what="detection rows to be persisted", diagnose=worker.output)

        rows = _rows()
        assert all(r.band in ("uncertain", "alarm") for r in rows), \
            "a `none` frame wrote a row; absence must stay absence"
        assert any(r.band == "alarm" for r in rows)
        assert all(r.confidence > 0 for r in rows)

        db = _S()
        try:
            ev = db.query(GuardEvent).filter(GuardEvent.camera_id == CAM).first()
        finally:
            db.close()
        if ev is not None:
            assert any(r.event_uuid == ev.event_uuid for r in rows), (
                "no detection row links to the event that fired, so the training index "
                "cannot be filtered to what the rule actually acted on"
            )
    finally:
        worker.stop_clean()


# ═══ TC-GINT-05 ══════════════════════════════════════════════════════════════

async def test_killed_worker_becomes_unavailable_via_a_real_last_will(backend, tmp_path):
    """The Last Will, proven by the broker rather than by `will_set` having been called.

    This is the assertion the fake broker could never make. The worker is SIGKILLed, so no
    handler runs and no DISCONNECT is sent; the broker then publishes the will on
    `guard/state`.

    The subtle part, and the reason this test found a defect: **MQTT delivers a live will to
    an already-subscribed client with RETAIN=0** (MQTT-3.3.1-9 — the retain flag is only set
    when a message is delivered in response to a new subscription). So the backend cannot
    recognise the will by its retain flag, and a handler that marks the worker "seen" on any
    non-retained state message would mark a dead worker as alive at the exact moment it
    died. `worker_alive` must be false here.

    Guard is ARMED first, deliberately. With `desired_state = OFF` the backend reports OFF
    for a dead worker and that is CORRECT — desired OFF wins over anything the worker says
    or fails to say, by design. The false-ARMED risk this test exists for only arises when
    an operator has asked for ARMED, so that is the state it sets up. (My first version of
    this test asserted UNAVAILABLE with desired OFF and failed against correct behaviour.)
    """
    from app.guard.service import liveness

    worker = _start_worker(backend, tmp_path)
    try:
        await _worker_up(worker)
        assert liveness.is_alive(CAM)

        _command("arm")
        await _await(lambda: liveness.reported(CAM).get("state") == "ARMED", timeout=30,
                     what="the worker to confirm ARMED before being killed",
                     diagnose=worker.output)
        assert _status()["state"] == "ARMED", "precondition: guard must be armed"

        worker.kill_hard()

        await _await(lambda: liveness.reported(CAM).get("state") == "UNAVAILABLE",
                     timeout=30,
                     what="the broker to deliver the worker's Last Will")

        reported = liveness.reported(CAM)
        assert "LWT" in (reported.get("reason") or ""), (
            f"the will arrived but not as the worker registered it: {reported}"
        )

        status = _status()
        assert status["state"] == "UNAVAILABLE", \
            f"a killed worker must read UNAVAILABLE, got {status['state']!r}"
        assert status["worker_alive"] is False, (
            "worker_alive is True for a process that no longer exists. A live Last Will "
            "arrives with RETAIN=0, so treating every non-retained state message as proof "
            "of life marks a dead worker as just-seen."
        )
    finally:
        worker.stop_clean()


# ═══ TC-GINT-06 ══════════════════════════════════════════════════════════════

async def test_command_sent_while_the_worker_is_down_goes_overdue(backend, tmp_path):
    """Nobody is listening: the command is published, never acked, and says so.

    The failure this prevents is the UI sitting on ARMING for ever. `cmd` is deliberately
    not retained, so the command is simply lost — which is correct, because a retained
    command would arm a worker that restarts later with nobody having asked.
    """
    from app.config import settings
    from app.guard.service import check_overdue_acks, liveness

    # No worker at all — nothing has ever connected for this camera.
    req_id = _command("arm")

    assert any(r == req_id for r, _c in liveness.overdue_acks(time.time() + 10_000))

    # Not overdue yet, before the timeout.
    assert not liveness.overdue_acks(time.time()), \
        "an ack was declared overdue before the timeout elapsed"

    await asyncio.sleep(settings.guard_ack_timeout_s + 0.5)
    overdue = liveness.overdue_acks()
    assert any(r == req_id for r, _c in overdue), \
        f"the unacked command never went overdue: {overdue}"

    await check_overdue_acks()

    status = _status()
    assert status["desired_state"] == "ARMED", \
        "the operator asked for ARMED; the desired state must not be silently changed"
    assert status["state"] == "UNAVAILABLE", (
        f"desired ARMED with a worker that never answered must read UNAVAILABLE, "
        f"got {status['state']!r}"
    )
    assert status["worker_alive"] is False
    assert status["worker_seen_at"] is None, "a worker never seen must not have a seen time"


# ═══ TC-GINT-07 ══════════════════════════════════════════════════════════════

async def test_an_ack_that_never_arrives_leaves_no_false_armed(backend, tmp_path):
    """A worker that is present but stops answering must not read ARMED.

    This is the same guarantee as TC-GINT-06 from the other direction: there the worker was
    never there, here it was and then went away mid-command. The state the operator sees
    must never be ARMED on the strength of a request nobody confirmed.
    """
    from app.config import settings
    from app.guard.service import check_overdue_acks, liveness

    worker = _start_worker(backend, tmp_path)
    try:
        await _worker_up(worker)

        # Kill it, then command it. The command is published into the void.
        worker.kill_hard()
        await _await(lambda: liveness.reported(CAM).get("state") == "UNAVAILABLE",
                     timeout=30, what="the Last Will")

        req_id = _command("arm")
        await asyncio.sleep(settings.guard_ack_timeout_s + 0.5)
        assert any(r == req_id for r, _c in liveness.overdue_acks()), \
            "the command to a dead worker was not registered as overdue"
        await check_overdue_acks()

        status = _status()
        assert status["state"] != "ARMED", (
            "ARMED was reported for a command no worker acknowledged — this is the exact "
            "false-ARMED the whole liveness design exists to prevent"
        )
        assert status["state"] == "UNAVAILABLE"
        assert status["desired_state"] == "ARMED"
    finally:
        worker.stop_clean()


# ═══ TC-GINT-08 ══════════════════════════════════════════════════════════════

async def test_unanswered_refuses_loudly_and_fatally_when_required(monkeypatch):
    """The refusal mechanism itself, because it is what makes the other seven trustworthy.

    A suite that can quietly shrink to nothing reports success for a deployment it never
    checked. So `_unanswered` is the load-bearing part on the NUC, and it gets its own test:
    the message must carry the verdict, and GUARD_INTEGRATION_REQUIRED=1 must make it fatal
    rather than skippable.

    I tried to prove this by pointing the fixture at an unroutable broker with a bogus
    MOSQUITTO_BIN, and the suite passed anyway — the binary fallback list found the local
    mosquitto and started one, which is correct behaviour and a useless negative test.
    Testing the mechanism directly is the honest version.
    """
    module = sys.modules[__name__]

    # Default: a skip, but one that states what a skip means here.
    monkeypatch.setattr(module, "INTEGRATION_REQUIRED", False)
    with pytest.raises(pytest.skip.Exception) as skipped:
        _unanswered("no broker", "start compose")
    text = str(skipped.value)
    assert "FAILURE TO REPORT" in text, \
        f"a skip must say it is not a pass; got: {text}"
    assert "no broker" in text and "start compose" in text, \
        "the reason and the remedy must both reach the person running it"
    assert "GUARD_INTEGRATION_REQUIRED=1" in text, \
        "the message must say how to make this fatal"

    # Required: not skippable at all.
    monkeypatch.setattr(module, "INTEGRATION_REQUIRED", True)
    with pytest.raises(pytest.fail.Exception) as failed:
        _unanswered("no broker", "start compose")
    assert "INTEGRATION NOT RUN" in str(failed.value)
