"""Guard smoke test — can THIS venv load the model and run one inference? (2026-10-15)

    /opt/cloud-iot/guard/.venv/bin/python nuc_image/guard_smoke.py MODEL_DIR APP_DIR

Run by install-guard.sh, step 9, to decide whether openvino-telemetry can be removed: the
addendum (guard_stage_a5_addendum.md A2) CLAIMED telemetry serves the tools (ovc), not
inference. This measures that claim on the cabinet instead of trusting it — it runs the
worker's own loading path (`YoloOVDetector.for_guard`, one thread), not a look-alike.

It must be able to fail, and it does: a missing or unreadable IR, an openvino that will not
compile it, or an inference that throws all exit 1 with one line saying which.

Exit: 0 = loaded and ran one inference on an empty frame; 1 = it did not. Prints one
`SMOKE OK` / `SMOKE FAIL` line, and whether openvino-telemetry is present.
"""
from __future__ import annotations

import importlib.util
import io
import logging
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: guard_smoke.py MODEL_DIR APP_DIR", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")      # the lines carry "—"; a cp1252 console mangles it
    model_dir, app_dir = argv[1], Path(argv[2])
    # The worker's own imports: the repo root and backend/ (guard_worker/__main__.py).
    sys.path[:0] = [str(app_dir), str(app_dir / "backend")]
    # The detector reports WHY a model did not load as a warning; let it through.
    logging.basicConfig(level=logging.WARNING, format="  detector: %(message)s")

    telemetry = "present" if importlib.util.find_spec("openvino_telemetry") else "ABSENT"
    ir = Path(model_dir) / "yolov8n_openvino"
    if not list(ir.glob("*.xml")):
        # The detector says this only at DEBUG; say it here, or the failure has no reason.
        print(f"SMOKE FAIL: no .xml in {ir} — the model is not where the worker looks")
        return 1
    try:
        from app.services.yolo_openvino import YoloOVDetector
        from PIL import Image
    except Exception as exc:                       # noqa: BLE001 — the line says what failed
        print(f"SMOKE FAIL: cannot import the detector: {exc!r}")
        return 1

    det = YoloOVDetector.for_guard(model_dir, num_threads=1)
    if not det.available:
        print(f"SMOKE FAIL: no model loaded from {model_dir}/yolov8n_openvino "
              f"(openvino-telemetry {telemetry}) — the detector line above says why")
        return 1

    buf = io.BytesIO()
    Image.new("RGB", (640, 480)).save(buf, "JPEG")
    result = det.detect_persons(buf.getvalue())
    if result.get("inference_ms") is None:
        print(f"SMOKE FAIL: {det.model_path} loaded but one inference on an empty frame "
              f"failed (openvino-telemetry {telemetry})")
        return 1
    print(f"SMOKE OK: {det.model_path} loaded and ran one inference in "
          f"{result['inference_ms']:.0f} ms; openvino-telemetry {telemetry}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
