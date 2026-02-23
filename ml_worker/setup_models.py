"""
One-time model setup script.

Downloads and exports RT-DETR and DINOv2 as ONNX files into /models/.

Run inside the ml_worker Docker container:

    # Step 1 – install export dependencies (one-time, temporary in container)
    docker compose run --rm ml_worker pip install -r requirements-setup.txt

    # Step 2 – export the models
    docker compose run --rm ml_worker python setup_models.py

Models written to /models/ (mounted from backend/models/ on the host):
    rtdetr.onnx   ~70 MB   RT-DETR ResNet-18 backbone, COCO-pretrained
    dinov2.onnx   ~85 MB   DINOv2 ViT-S/14, image embeddings

Total disk usage: ~155 MB
"""

import shutil
import subprocess
import sys
from pathlib import Path

MODELS_DIR = Path("/models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)

RTDETR_OUT  = MODELS_DIR / "rtdetr.onnx"
DINOV2_OUT  = MODELS_DIR / "dinov2.onnx"

# Temporary export directories (deleted after copying final .onnx)
RTDETR_EXPORT = MODELS_DIR / "_rtdetr_export"
DINOV2_EXPORT = MODELS_DIR / "_dinov2_export"


def _check_optimum():
    try:
        import optimum  # noqa: F401
    except ImportError:
        print("\n[ERROR] 'optimum' is not installed in this container.")
        print("Run first:\n  docker compose run --rm ml_worker pip install -r requirements-setup.txt\n")
        sys.exit(1)


def _export(model_id: str, task: str, export_dir: Path, out_file: Path, label: str):
    if out_file.exists():
        print(f"[SKIP] {label} already exists at {out_file}")
        return

    print(f"\n{'='*60}")
    print(f"[{label}] Downloading and exporting from HuggingFace ...")
    print(f"  model  : {model_id}")
    print(f"  task   : {task}")
    print(f"  output : {out_file}")
    print(f"{'='*60}")

    # Clean up any previous partial export
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True)

    cmd = [
        "optimum-cli", "export", "onnx",
        "--model",  model_id,
        "--task",   task,
        "--opset",  "17",
        "--device", "cpu",
        str(export_dir),
    ]

    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"\n[ERROR] optimum-cli export failed for {label}.")
        sys.exit(1)

    # optimum writes model.onnx (sometimes model_quantized.onnx too)
    candidate = export_dir / "model.onnx"
    if not candidate.exists():
        # Some tasks produce decoder_model.onnx etc. — take the main one
        candidates = sorted(export_dir.glob("*.onnx"))
        if not candidates:
            print(f"[ERROR] No .onnx file found in {export_dir}")
            sys.exit(1)
        candidate = candidates[0]

    shutil.copy(candidate, out_file)
    shutil.rmtree(export_dir)  # clean up temp files
    size_mb = out_file.stat().st_size / (1024 * 1024)
    print(f"\n[OK] {label} → {out_file}  ({size_mb:.1f} MB)")


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
    _check_optimum()

    # ── RT-DETR (ResNet-18, COCO object-detection) ────────────────────────────
    _export(
        model_id   = "PekingU/rtdetr_r18vd",
        task       = "object-detection",
        export_dir = RTDETR_EXPORT,
        out_file   = RTDETR_OUT,
        label      = "RT-DETR",
    )

    # ── DINOv2-small (ViT-S/14, image feature extraction) ────────────────────
    _export(
        model_id   = "facebook/dinov2-small",
        task       = "feature-extraction",
        export_dir = DINOV2_EXPORT,
        out_file   = DINOV2_OUT,
        label      = "DINOv2",
    )

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
