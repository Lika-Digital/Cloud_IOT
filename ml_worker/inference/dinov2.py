"""
DINOv2 ONNX inference session.

Supported ONNX output layouts:
  A) last_hidden_state [1, seq_len, hidden_dim]  → use CLS token [0, 0, :]
  B) pooler_output     [1, hidden_dim]           → use as-is
  C) Any 2-D output    [1, hidden_dim]           → use row 0

Returns an L2-normalised embedding vector. Cosine similarity is then a
simple dot product of two normalised vectors.

Typical hidden_dim values:
  DINOv2-small (ViT-S/14): 384
  DINOv2-base  (ViT-B/14): 768
  DINOv2-large (ViT-L/14): 1024
"""
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD  = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class DINOv2Session:
    def __init__(self, model_path: Path) -> None:
        self.session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]

    def _preprocess(self, image: Image.Image) -> np.ndarray:
        img = image.convert("RGB").resize((224, 224), Image.BICUBIC)
        arr = np.array(img, dtype=np.float32) / 255.0
        arr = (arr - _IMAGENET_MEAN) / _IMAGENET_STD
        return arr.transpose(2, 0, 1)[np.newaxis].astype(np.float32)   # [1,3,224,224]

    def embed(self, image: Image.Image) -> np.ndarray:
        """Return L2-normalised embedding vector."""
        tensor = self._preprocess(image)
        raw = self.session.run(None, {self.input_name: tensor})

        vec: np.ndarray | None = None
        out_map = {n: v for n, v in zip(self.output_names, raw)}

        # Prefer named outputs
        if "last_hidden_state" in out_map:
            vec = out_map["last_hidden_state"][0, 0, :]   # CLS token
        elif "pooler_output" in out_map:
            vec = out_map["pooler_output"][0]
        else:
            # Infer from shape
            for arr in raw:
                if arr.ndim == 3:
                    vec = arr[0, 0, :]
                    break
                elif arr.ndim == 2:
                    vec = arr[0]
                    break
            if vec is None:
                vec = raw[0].flatten()

        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 1e-8 else vec
