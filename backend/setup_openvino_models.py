#!/usr/bin/env python3
"""
setup_openvino_models.py — NUC-only one-time model setup script.

Run once on the Ubuntu 24.04 NUC after installing all ML packages:
    cd /opt/cloud-iot/backend
    python setup_openvino_models.py

This script is IDEMPOTENT — running it a second time is safe and does nothing
if the model directories already exist.

Dependencies (NUC only, 64-bit Python):
    pip install ultralytics openvino torch torchvision
"""
import os
import sys
import shutil
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

# ─── Paths ─────────────────────────────────────────────────────────────────────

if sys.platform == "linux" and os.path.exists("/opt/cloud-iot"):
    MODELS_DIR = "/opt/cloud-iot/backend/models"
else:
    # Dev fallback (should normally not be run on dev)
    MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

YOLO_OUT_DIR = os.path.join(MODELS_DIR, "yolov8n_openvino")
REID_OUT_DIR = os.path.join(MODELS_DIR, "mobilenetv2_reid_openvino")


def _ensure_models_dir():
    os.makedirs(MODELS_DIR, exist_ok=True)
    log.info("Models directory: %s", MODELS_DIR)


# ─── Step 1: YOLOv8n → OpenVINO IR ────────────────────────────────────────────

def export_yolo():
    """Export YOLOv8n to OpenVINO IR format and move to models dir."""
    if os.path.isdir(YOLO_OUT_DIR) and os.listdir(YOLO_OUT_DIR):
        log.info("YOLOv8n OpenVINO model already exists at %s — skipping", YOLO_OUT_DIR)
        return

    log.info("Exporting YOLOv8n to OpenVINO IR …")
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError as exc:
        log.error("ultralytics not installed: %s", exc)
        log.error("Install with: pip install ultralytics")
        sys.exit(1)

    try:
        model = YOLO("yolov8n.pt")  # auto-downloads weights
        # Export returns the path to the exported directory/file
        export_path = model.export(format="openvino", dynamic=False, half=False)
        log.info("Export finished: %s", export_path)

        # ultralytics places the output at: <cwd>/yolov8n_openvino_model/
        # or a path returned by export().  Move it to our models dir.
        candidate_dirs = [
            str(export_path) if export_path else None,
            os.path.join(os.getcwd(), "yolov8n_openvino_model"),
            os.path.join(os.getcwd(), "yolov8n_openvino"),
        ]
        src = None
        for d in candidate_dirs:
            if d and os.path.isdir(d):
                src = d
                break

        if src is None:
            log.error("Could not find ultralytics export output directory.")
            sys.exit(1)

        os.makedirs(YOLO_OUT_DIR, exist_ok=True)
        if os.path.abspath(src) != os.path.abspath(YOLO_OUT_DIR):
            log.info("Moving %s → %s", src, YOLO_OUT_DIR)
            shutil.copytree(src, YOLO_OUT_DIR, dirs_exist_ok=True)
            shutil.rmtree(src, ignore_errors=True)
        log.info("YOLOv8n OpenVINO model saved to: %s", YOLO_OUT_DIR)
    except Exception as exc:
        log.error("YOLOv8n export failed: %s", exc)
        raise


# ─── Step 2: MobileNetV3-Small Re-ID → OpenVINO IR ────────────────────────────

def export_reid():
    """
    Build a MobileNetV2 backbone with 128-dim projection head,
    export to ONNX, then convert to OpenVINO IR.
    MobileNetV2 is lighter than V3 — better suited for Intel Atom x7425E.
    """
    if os.path.isdir(REID_OUT_DIR) and os.listdir(REID_OUT_DIR):
        log.info("MobileNetV2 Re-ID model already exists at %s — skipping", REID_OUT_DIR)
        return

    log.info("Building MobileNetV2 Re-ID model …")

    try:
        import torch  # type: ignore
        import torch.nn as nn  # type: ignore
        import torchvision.models as tv_models  # type: ignore
    except ImportError as exc:
        log.error("torch/torchvision not installed: %s", exc)
        log.error("Install with: pip install torch torchvision")
        sys.exit(1)

    # Build model: MobileNetV2 backbone + L2-normalised 128-dim head
    # MobileNetV2 chosen over V3 for better performance on Intel Atom x7425E (no AVX2)
    class ReidModel(nn.Module):
        def __init__(self):
            super().__init__()
            # Load pretrained backbone
            backbone = tv_models.mobilenet_v2(weights=tv_models.MobileNet_V2_Weights.DEFAULT)
            # Keep feature extractor; drop classifier
            self.features = backbone.features
            self.avgpool = nn.AdaptiveAvgPool2d((1, 1))
            # MobileNetV2 last conv output: 1280 channels
            self.proj = nn.Sequential(
                nn.Linear(1280, 256),
                nn.ReLU(inplace=True),
                nn.Linear(256, 128),
            )

        def forward(self, x):
            x = self.features(x)
            x = self.avgpool(x)
            x = torch.flatten(x, 1)
            x = self.proj(x)
            # L2 normalise
            x = nn.functional.normalize(x, p=2, dim=1)
            return x

    model = ReidModel().eval()
    dummy_input = torch.zeros(1, 3, 224, 224)

    # Export to ONNX first
    onnx_path = os.path.join(MODELS_DIR, "mobilenetv3_reid.onnx")
    os.makedirs(MODELS_DIR, exist_ok=True)
    log.info("Exporting to ONNX: %s", onnx_path)
    try:
        torch.onnx.export(
            model,
            dummy_input,
            onnx_path,
            opset_version=13,
            input_names=["input"],
            output_names=["embedding"],
            dynamic_axes={"input": {0: "batch_size"}, "embedding": {0: "batch_size"}},
        )
        log.info("ONNX export complete: %s", onnx_path)
    except Exception as exc:
        log.error("ONNX export failed: %s", exc)
        raise

    # Convert ONNX → OpenVINO IR
    log.info("Converting ONNX to OpenVINO IR …")
    try:
        import openvino as ov  # type: ignore
        ov_model = ov.convert_model(onnx_path)
        os.makedirs(REID_OUT_DIR, exist_ok=True)
        xml_out = os.path.join(REID_OUT_DIR, "mobilenetv3_reid.xml")
        ov.save_model(ov_model, xml_out)
        log.info("OpenVINO IR saved to: %s", REID_OUT_DIR)
    except ImportError as exc:
        log.error("openvino not installed: %s", exc)
        log.error("Install with: pip install openvino")
        sys.exit(1)
    except Exception as exc:
        log.error("OpenVINO conversion failed: %s", exc)
        raise

    # Cleanup intermediate ONNX
    try:
        os.remove(onnx_path)
    except Exception:
        pass

    log.info("MobileNetV2 Re-ID OpenVINO model saved to: %s", REID_OUT_DIR)


# ─── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=== Cloud-IoT OpenVINO model setup (NUC) ===")
    log.info("Platform: %s", sys.platform)
    log.info("Python:   %s  %s", sys.version, "64-bit" if sys.maxsize > 2**32 else "32-bit")

    if sys.maxsize <= 2**32:
        log.warning("This script should be run on 64-bit Python (NUC). "
                    "Continuing anyway, but ML imports may fail.")

    _ensure_models_dir()
    export_yolo()
    export_reid()
    log.info("=== Model setup complete ===")
