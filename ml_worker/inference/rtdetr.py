"""
RT-DETR ONNX inference session.

Supported output formats:
  A) HuggingFace transformers / optimum export:
       logits    [1, N, C]   — raw class logits (pre-sigmoid)
       pred_boxes [1, N, 4]  — cx, cy, w, h in [0, 1]
  B) Ultralytics export:
       single output [1, 84, 8400] where rows = [cx, cy, w, h, c0…c79]

COCO class 8 = "boat".  For pilot, any class above threshold is accepted as
a vessel (handles fine-tuned models where vessel = class 0).
"""
from pathlib import Path
from typing import List, Tuple

import numpy as np
import onnxruntime as ort
from PIL import Image

_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# COCO class ids considered "vessel"; empty set = accept all classes
VESSEL_CLASSES: set = {8}   # 8 = boat in COCO-80


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -500.0, 500.0)))


class RTDETRSession:
    def __init__(self, model_path: Path) -> None:
        self.session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        shape = inp.shape
        # Shape is typically [batch, 3, H, W]; fall back to 640 if dynamic
        self.input_h = int(shape[2]) if isinstance(shape[2], int) and shape[2] > 0 else 640
        self.input_w = int(shape[3]) if isinstance(shape[3], int) and shape[3] > 0 else 640
        self.output_names = [o.name for o in self.session.get_outputs()]

    def _preprocess(self, image: Image.Image) -> np.ndarray:
        img = image.convert("RGB").resize((self.input_w, self.input_h), Image.BILINEAR)
        arr = np.array(img, dtype=np.float32) / 255.0
        arr = (arr - _IMAGENET_MEAN) / _IMAGENET_STD
        return arr.transpose(2, 0, 1)[np.newaxis].astype(np.float32)   # [1,3,H,W]

    def detect(
        self,
        image: Image.Image,
        conf_threshold: float = 0.30,
    ) -> List[Tuple[float, float, float, float, float, int]]:
        """
        Returns list of (x1, y1, x2, y2, score, class_id) in image pixel coords.
        """
        img_w, img_h = image.size
        tensor = self._preprocess(image)
        raw = self.session.run(None, {self.input_name: tensor})
        out = {n: v for n, v in zip(self.output_names, raw)}

        dets: List[Tuple] = []

        # ── Format A: transformers/optimum ───────────────────────────────────
        if "logits" in out and "pred_boxes" in out:
            logits = _sigmoid(out["logits"][0])   # [N, C]
            boxes  = out["pred_boxes"][0]          # [N, 4] cx,cy,w,h in [0,1]
            for i in range(logits.shape[0]):
                cls_id = int(np.argmax(logits[i]))
                score  = float(logits[i, cls_id])
                if score < conf_threshold:
                    continue
                cx, cy, bw, bh = boxes[i].tolist()
                dets.append((
                    (cx - bw / 2) * img_w,
                    (cy - bh / 2) * img_h,
                    (cx + bw / 2) * img_w,
                    (cy + bh / 2) * img_h,
                    score, cls_id,
                ))

        # ── Format B: ultralytics ────────────────────────────────────────────
        elif len(raw) == 1 and raw[0].ndim == 3:
            pred = raw[0][0].T          # [8400, 84]
            box_raw    = pred[:, :4]    # cx, cy, w, h  (pixel-scale)
            cls_scores = pred[:, 4:]    # [8400, 80]
            for i in range(pred.shape[0]):
                cls_id = int(np.argmax(cls_scores[i]))
                score  = float(cls_scores[i, cls_id])
                if score < conf_threshold:
                    continue
                cx, cy, bw, bh = box_raw[i].tolist()
                dets.append((
                    (cx - bw / 2) / self.input_w * img_w,
                    (cy - bh / 2) / self.input_h * img_h,
                    (cx + bw / 2) / self.input_w * img_w,
                    (cy + bh / 2) / self.input_h * img_h,
                    score, cls_id,
                ))

        return dets
