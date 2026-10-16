"""TC-GW — the automatic resume after a CPU suspension really resumes (spec §5.5.1 item 3, owner
2026-10-16).

Found 2026-10-16: the watchdog decided to resume (`resumed_cpu`), counted it against the 24 h
budget and set ITS state ARMED — but the worker acted only on `suspended_cpu`, so capture stayed
stopped and the worker kept publishing SUSPENDED_CPU. A counter that claimed something happened
when it had not. The owner's two rules:

  TC-GW-01  on a due resume the worker really restarts capture and publishes ARMED
  TC-GW-02  the budget is spent only once capture has really started — the first frame after
            the resume — and the worker has published ARMED; not when the watchdog decided
  TC-GW-03  a resume that fails to arm spends nothing, stays SUSPENDED_CPU and says why

All three fail on the worker before the fix. Real worker, real watchdog; the camera, the CPU
reading and the detector are the substitutes (no ffmpeg, no OpenVINO on the dev box).
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import guard_worker.__main__ as wm  # noqa: E402
from guard_worker.__main__ import GuardWorker, WorkerConfig  # noqa: E402
from guard_worker.watchdog import Watchdog, WatchdogConfig  # noqa: E402
from test_guard_worker_smoke import FakeClient, FakeDetector  # noqa: E402

INST = "resume-instance"


def _jpeg() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (40, 60, 80)).save(buf, format="JPEG")
    return buf.getvalue()


class FakeSupervisor:
    """Stands in for CaptureSupervisor: frames() yields what the test queues."""
    started = 0

    def __init__(self, make_capture, on_event=None):
        FakeSupervisor.started += 1
        self.capture = None
        self.restart_count = 0
        self.queue: list[bytes] = []

    def frames(self):
        while True:
            yield self.queue.pop(0) if self.queue else None

    def stop(self):
        pass


class FakeCpu:
    def __init__(self):
        self.value = 10.0

    def sample(self):
        return self.value


@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.setattr(wm, "CaptureSupervisor", FakeSupervisor)
    FakeSupervisor.started = 0
    cfg = WorkerConfig(marina_id="TST", camera_id=7, pedestal_id=7, instance_id=INST,
                       stream_url="synthetic", storage_path=str(tmp_path / "rec"),
                       model_dir=str(tmp_path / "models"), segment_seconds=1, segment_ring=8,
                       record_seconds=2, preroll_seconds=1, ffmpeg=None)
    detectors = {"available": True}
    w = GuardWorker(cfg, client=FakeClient(),
                    detector_factory=lambda: FakeDetector(available=detectors["available"],
                                                          confidence=0.0))
    w.watchdog = Watchdog(WatchdogConfig(window_s=10.0, resume_after_s=20.0, max_auto_resumes=2))
    w.cpu = FakeCpu()
    w.apply_command({"instance": INST, "cmd": "arm", "req_id": "arm-1",
                     "config": {"config_version": 1}})
    assert w.state == "ARMED", "precondition: armed"
    w._detectors = detectors
    return w


def _suspend_then_quiet(w, *, quiet_s: float = 40.0) -> float:
    t = 1000.0
    w.cpu.value = 97.0
    for _ in range(6):
        w._run_watchdog(t)
        t += 5.0
    assert w.state == "SUSPENDED_CPU", "precondition: the overload suspended guard"
    assert w.supervisor is None, "precondition: capture was stopped"
    w.cpu.value = 5.0
    end = t + quiet_s
    while t <= end:
        w._run_watchdog(t)
        t += 5.0
    return t


def _last_state(w) -> dict:
    return w.client.last("state")


def test_tc_gw_01_a_due_resume_really_restarts_capture(worker):
    started_before = FakeSupervisor.started
    _suspend_then_quiet(worker)
    assert worker.state == "ARMED", f"the worker stayed {worker.state}"
    assert worker.supervisor is not None and FakeSupervisor.started == started_before + 1, \
        "capture was not restarted"
    assert _last_state(worker)["state"] == "ARMED"


def test_tc_gw_02_the_budget_is_spent_only_when_capture_has_really_started(worker):
    t = _suspend_then_quiet(worker)
    assert worker.watchdog.auto_resumes_used(t) == 0, \
        "the budget was spent before a single frame arrived"
    worker.supervisor.queue.append(_jpeg())
    worker.step()
    assert worker.watchdog.auto_resumes_used(t) == 1
    # and only once: more frames spend nothing more
    worker.supervisor.queue.append(_jpeg())
    worker.step()
    assert worker.watchdog.auto_resumes_used(t) == 1


def test_tc_gw_03_a_resume_that_cannot_arm_spends_nothing_and_says_why(worker):
    worker._detectors["available"] = False           # the model went missing meanwhile
    t = _suspend_then_quiet(worker)
    assert worker.state == "SUSPENDED_CPU"
    assert worker.watchdog.auto_resumes_used(t) == 0
    reason = _last_state(worker).get("reason") or ""
    assert "automatic resume failed" in reason, reason
