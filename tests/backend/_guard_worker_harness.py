"""
Guard worker harness for the integration suite — NOT a test module.

`test_guard_integration.py` needs a guard worker running as a **real, separate OS process**
against a **real broker**, because two of the properties under test cannot be observed any
other way:

  * **Last Will.** A will message is published by the broker only when a client's connection
    drops without a DISCONNECT. That means the worker must be killable — an in-process worker
    with a fake client can only ever prove that `will_set()` was called, never that the
    broker actually delivers the will.
  * **Real wire payloads.** The backend and the worker were each tested against a fake of the
    other, so every field name matched by reading is a guess until a broker carries it.

Two things are substituted, and only two — the same pair as the smoke suite:

  * **the detector**, because OpenVINO has no 32-bit wheel and the dev box is 32-bit Python;
  * **the camera**, by a pre-encoded H.264 file replayed at wallclock rate.

Everything else is production code: `GuardWorker.run()`, real paho, real ffmpeg, the real
capture ring, the real pipeline, the real alarm rule, the real recorder.

This is deliberately NOT `python -m guard_worker`, because the entrypoint needs the detector
and the synthetic source injected. The module entry is proven separately and for real by
TC-GSMOKE-03 and TC-GSMOKE-04; this harness proves the MQTT contract instead. Neither
substitutes for the other.

Named with a leading underscore so pytest does not collect it.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for _p in (str(REPO), str(REPO / "backend")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from guard_worker.__main__ import GuardWorker, WorkerConfig  # noqa: E402


class HarnessDetector:
    """Returns YoloOVDetector's real dict shape with a fixed answer.

    The shape matters: `process_frame` distinguishes `occupied is None` (inference
    unavailable) from `occupied is False` (nothing there). Collapsing those would make a
    blind guard look like a quiet one, so the fake keeps them apart.
    """

    def __init__(self, *, confidence: float, available: bool = True):
        self.available = available
        self.confidence = confidence

    def detect_persons(self, jpeg, conf_threshold=0.2, **_kw) -> dict:
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
        self.available = False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--broker-host", default="localhost")
    ap.add_argument("--broker-port", type=int, required=True)
    ap.add_argument("--marina", required=True)
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--storage", required=True)
    ap.add_argument("--source", default="",
                    help="pre-encoded H.264 file replayed as the camera; empty = no capture")
    ap.add_argument("--ffmpeg", default=None)
    ap.add_argument("--confidence", type=float, default=0.95)
    ap.add_argument("--detector", choices=("available", "unavailable"), default="available")
    ap.add_argument("--segment-seconds", type=int, default=1)
    ap.add_argument("--record-seconds", type=int, default=3)
    ap.add_argument("--preroll-seconds", type=int, default=1)
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args()

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s harness/%(name)s: %(message)s",
    )

    cfg = WorkerConfig(
        marina_id=args.marina,
        camera_id=args.camera,
        pedestal_id=args.camera,
        # A non-empty URL is required or run() exits 2 before connecting; the tests that do
        # not need frames pass a placeholder and never arm.
        stream_url=args.source or "no-capture",
        broker_host=args.broker_host,
        broker_port=args.broker_port,
        storage_path=args.storage,
        segment_seconds=args.segment_seconds,
        record_seconds=args.record_seconds,
        preroll_seconds=args.preroll_seconds,
        ffmpeg=args.ffmpeg,
        # Replay the file endlessly at wallclock rate, so the segment ring rolls at the pace
        # it would from the camera. Without -re, ffmpeg consumes the file as fast as it can.
        input_args=(["-stream_loop", "-1", "-re",
                     "-use_wallclock_as_timestamps", "1", "-fflags", "+genpts"]
                    if args.source else None),
    )

    detector = HarnessDetector(
        confidence=args.confidence, available=args.detector == "available")
    return GuardWorker(cfg, detector_factory=lambda: detector).run()


if __name__ == "__main__":
    sys.exit(main())
