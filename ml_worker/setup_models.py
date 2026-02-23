"""
One-time model setup script.

Exports RT-DETR and DINOv2 as ONNX files into /models/ using
torch.onnx.export directly (no optimum-cli dependency).

Run with the ml_export_env (64-bit Python 3.11):

    # Create + fill env once:
    py -3.11 -m venv C:/temp/ml_export_env
    C:/temp/ml_export_env/Scripts/pip install torch transformers onnxruntime

    # Export:
    C:/temp/ml_export_env/Scripts/python ml_worker/setup_models.py

Models written to backend/models/ on the host:
    rtdetr.onnx   ~70 MB   RT-DETR ResNet-18 backbone, COCO-pretrained
    dinov2.onnx   ~85 MB   DINOv2 ViT-S/14, image embeddings

Total disk usage: ~155 MB
"""

import os
import sys
from pathlib import Path

# Inside Docker: /models is the volume mount.
# On Windows directly: use backend/models/ relative to project root.
_docker_path = Path("/models")
_native_path = Path(__file__).parent.parent / "backend" / "models"
MODELS_DIR = _docker_path if _docker_path.exists() else _native_path
MODELS_DIR.mkdir(parents=True, exist_ok=True)

RTDETR_OUT = MODELS_DIR / "rtdetr.onnx"
DINOV2_OUT = MODELS_DIR / "dinov2.onnx"

# Suppress symlink warning from huggingface_hub on Windows without Developer Mode
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def _check_deps():
    missing = []
    for pkg in ("torch", "transformers", "onnxruntime"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"\n[ERROR] Missing packages: {', '.join(missing)}")
        print("Install with:")
        print("  C:/temp/ml_export_env/Scripts/pip install torch transformers onnxruntime")
        sys.exit(1)


def _export_rtdetr():
    if RTDETR_OUT.exists():
        print(f"[SKIP] RT-DETR already exists at {RTDETR_OUT}")
        return

    print(f"\n{'='*60}")
    print("[RT-DETR] Downloading PekingU/rtdetr_r18vd from HuggingFace ...")
    print(f"  output : {RTDETR_OUT}")
    print(f"{'='*60}")

    import torch
    from transformers import RTDetrForObjectDetection

    model = RTDetrForObjectDetection.from_pretrained("PekingU/rtdetr_r18vd")
    model.eval()

    # Wrapper so torch.onnx.export gets plain tensor I/O
    class _Wrapper(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, pixel_values):
            out = self.m(pixel_values=pixel_values)
            return out.logits, out.pred_boxes

    wrapper = _Wrapper(model)
    dummy = torch.zeros(1, 3, 640, 640, dtype=torch.float32)

    print("[RT-DETR] Exporting to ONNX (opset 17, legacy exporter) ...")
    with torch.no_grad():
        torch.onnx.export(
            wrapper,
            (dummy,),
            str(RTDETR_OUT),
            input_names=["pixel_values"],
            output_names=["logits", "pred_boxes"],
            opset_version=17,
            dynamo=False,
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "logits":       {0: "batch"},
                "pred_boxes":   {0: "batch"},
            },
        )

    size_mb = RTDETR_OUT.stat().st_size / (1024 * 1024)
    print(f"\n[OK] RT-DETR -> {RTDETR_OUT}  ({size_mb:.1f} MB)")


def _export_dinov2():
    if DINOV2_OUT.exists():
        print(f"[SKIP] DINOv2 already exists at {DINOV2_OUT}")
        return

    print(f"\n{'='*60}")
    print("[DINOv2] Downloading facebook/dinov2-small from HuggingFace ...")
    print(f"  output : {DINOV2_OUT}")
    print(f"{'='*60}")

    import torch
    from transformers import AutoModel

    model = AutoModel.from_pretrained("facebook/dinov2-small")
    model.eval()

    class _Wrapper(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, pixel_values):
            out = self.m(pixel_values=pixel_values)
            return out.last_hidden_state  # [1, seq, 384]

    wrapper = _Wrapper(model)
    dummy = torch.zeros(1, 3, 224, 224, dtype=torch.float32)

    print("[DINOv2] Exporting to ONNX (opset 17, legacy exporter) ...")
    with torch.no_grad():
        torch.onnx.export(
            wrapper,
            (dummy,),
            str(DINOV2_OUT),
            input_names=["pixel_values"],
            output_names=["last_hidden_state"],
            opset_version=17,
            dynamo=False,
            dynamic_axes={
                "pixel_values":     {0: "batch"},
                "last_hidden_state": {0: "batch"},
            },
        )

    size_mb = DINOV2_OUT.stat().st_size / (1024 * 1024)
    print(f"\n[OK] DINOv2 -> {DINOV2_OUT}  ({size_mb:.1f} MB)")


def _verify(label: str, path: Path):
    print(f"\n[Verify] Loading {label} with onnxruntime ...")
    import onnxruntime as ort
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    inputs  = [i.name for i in sess.get_inputs()]
    outputs = [o.name for o in sess.get_outputs()]
    print(f"  inputs : {inputs}")
    print(f"  outputs: {outputs}")
    print(f"  [OK] {label} passes onnxruntime load check")


def main():
    _check_deps()
    _export_rtdetr()
    _export_dinov2()

    # ── Verification ──────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Verifying exported models ...")
    _verify("RT-DETR", RTDETR_OUT)
    _verify("DINOv2",  DINOV2_OUT)

    print(f"\n{'='*60}")
    print("All models ready.")
    print(f"  {RTDETR_OUT}  ({RTDETR_OUT.stat().st_size // (1024*1024)} MB)")
    print(f"  {DINOV2_OUT}  ({DINOV2_OUT.stat().st_size // (1024*1024)} MB)")
    print("\nYou can now start the ML Worker:")
    print("  docker compose up -d ml_worker")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
