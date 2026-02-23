# ML Worker — RT-DETR + DINOv2 Inference Service

Runs as a Docker container alongside the main backend.
Exposes `http://localhost:8001` for berth occupancy analysis.

## Model Setup (one-time)

Place ONNX model files in `backend/models/` (mounted as `/models` inside the container):

```
backend/models/
  rtdetr.onnx    ← RT-DETR COCO-pretrained
  dinov2.onnx    ← DINOv2 ViT-S/14 or ViT-B/14
```

### Option A — Export with a 64-bit Python environment (recommended)

```bash
# Create a separate 64-bit Python environment
python -m venv ml_env
ml_env/Scripts/activate

pip install optimum[exporters] torch onnx

# RT-DETR (ResNet-18 backbone, ~45 MB)
optimum-cli export onnx \
  --model PekingU/rtdetr_r18vd \
  --task object-detection \
  --opset 17 \
  backend/models/rtdetr_export/
cp backend/models/rtdetr_export/model.onnx backend/models/rtdetr.onnx

# DINOv2-small (ViT-S/14, ~85 MB)
optimum-cli export onnx \
  --model facebook/dinov2-small \
  --task image-classification \
  --opset 17 \
  backend/models/dinov2_export/
cp backend/models/dinov2_export/model.onnx backend/models/dinov2.onnx
```

### Option B — Ultralytics RT-DETR export

```bash
pip install ultralytics
# export rt-detr-l (larger, more accurate)
yolo export model=rtdetr-l.pt format=onnx imgsz=640
cp rtdetr-l.onnx backend/models/rtdetr.onnx
```

> The worker auto-detects whether the model uses HuggingFace format
> (`logits` + `pred_boxes` outputs) or Ultralytics format (`[1, 84, 8400]`).

## Expected Input / Output Formats

### RT-DETR
| | HuggingFace/optimum | Ultralytics |
|---|---|---|
| Input | `pixel_values [1,3,640,640]` float32, ImageNet-norm | same |
| Output | `logits [1,N,C]` + `pred_boxes [1,N,4]` cx/cy/w/h in [0,1] | `[1,84,8400]` |

### DINOv2
| | Format |
|---|---|
| Input | `pixel_values [1,3,224,224]` float32, ImageNet-norm |
| Output | `last_hidden_state [1,197,384]` (CLS token at index 0) |

## Pilot Assets

```
frontend/src/assets/
  Berth Full.mp4    ← occupied test video for berth 1
  Berth empty.mp4   ← free test video for berth 2
  Full_Berth.jpg    ← reference ship sample for berth 1
```

## Pilot Expected Results

| Video | Reference | occupied_bit | match_ok_bit | state_code | alarm |
|---|---|---|---|---|---|
| Berth Full.mp4 | Full_Berth.jpg | 1 | 0 | 2 | 1 |
| Berth empty.mp4 | — | 0 | 0 | 0 | 0 |
| (no video) | — | 0 | 0 | 0 | 0 |

`state_code = 2` (OCCUPIED_WRONG) + `alarm = 1` because a vessel is detected
but it does **not** match the stored contracted-ship sample.
