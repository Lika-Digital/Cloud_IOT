"""
MobileNetV2 Re-ID OpenVINO inference for ship identity matching.
Falls back to returning None if OpenVINO is not available (32-bit dev machine).
"""
import io
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ImageNet normalisation constants
_MEAN = (0.485, 0.456, 0.406)
_STD  = (0.229, 0.224, 0.225)


class ReidOVMatcher:
    """
    Extracts 128-dim L2-normalised Re-ID embeddings using MobileNetV2
    compiled to OpenVINO IR.

    If the model is missing or OpenVINO cannot be imported, `self.available`
    is False and `extract_embedding()` returns None so callers can fall back.
    """

    def __init__(self, model_dir: str):
        self.available = False
        self._compiled_model: Any = None
        self._input_layer: Any = None
        self._output_layer: Any = None

        model_path = os.path.join(model_dir, "mobilenetv2_reid_openvino")
        if not os.path.isdir(model_path):
            logger.debug("ReidOVMatcher: model directory not found at %s — Re-ID disabled", model_path)
            return

        xml_file = None
        try:
            for fname in os.listdir(model_path):
                if fname.endswith(".xml"):
                    xml_file = os.path.join(model_path, fname)
                    break
        except Exception:
            return

        if xml_file is None:
            logger.debug("ReidOVMatcher: no .xml file in %s — Re-ID disabled", model_path)
            return

        try:
            import openvino as ov  # type: ignore  # lazy import
            core = ov.Core()
            ov_model = core.read_model(xml_file)
            self._compiled_model = core.compile_model(ov_model, "CPU")
            self._input_layer = self._compiled_model.input(0)
            self._output_layer = self._compiled_model.output(0)
            self.available = True
            logger.info("ReidOVMatcher: loaded model from %s", xml_file)
        except ImportError:
            logger.debug("ReidOVMatcher: openvino not available — Re-ID disabled")
        except Exception as exc:
            logger.warning("ReidOVMatcher: failed to load model: %s", exc)

    def extract_embedding(self, frame_bytes: bytes):
        """
        Decode JPEG, preprocess to 224×224 with ImageNet normalisation,
        run OpenVINO inference, return L2-normalised 128-dim float32 array.

        Returns None if not available or on any error.
        """
        if not self.available:
            return None

        try:
            import numpy as np  # lazy import
            from PIL import Image  # lazy import

            img = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
            img = img.resize((224, 224))
            arr = np.array(img, dtype=np.float32) / 255.0  # HWC [0,1]

            # ImageNet normalisation
            mean = np.array(_MEAN, dtype=np.float32)
            std  = np.array(_STD,  dtype=np.float32)
            arr = (arr - mean) / std

            inp = arr.transpose(2, 0, 1)[np.newaxis, ...]  # NCHW [1,3,224,224]
            t0 = time.perf_counter()
            result = self._compiled_model([inp])[self._output_layer]
            inference_ms = (time.perf_counter() - t0) * 1000
            logger.info("ReidOVMatcher: inference_ms=%.1f", inference_ms)
            embedding = result.flatten().astype(np.float32)

            # L2 normalise
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            return embedding

        except Exception as exc:
            logger.warning("ReidOVMatcher.extract_embedding() error: %s", exc)
            return None

    def save_embedding(self, berth_id: int, embedding, storage_dir: str):
        """Save embedding to {storage_dir}/berth_{berth_id:02d}_reid.npy"""
        try:
            import numpy as np  # lazy import
            os.makedirs(storage_dir, exist_ok=True)
            path = os.path.join(storage_dir, f"berth_{berth_id:02d}_reid.npy")
            np.save(path, embedding)
            logger.info("ReidOVMatcher: saved embedding to %s", path)
            return path
        except Exception as exc:
            logger.warning("ReidOVMatcher.save_embedding() error: %s", exc)
            return None

    def load_embedding(self, berth_id: int, storage_dir: str):
        """Load embedding from {storage_dir}/berth_{berth_id:02d}_reid.npy, or None if missing."""
        try:
            import numpy as np  # lazy import
            path = os.path.join(storage_dir, f"berth_{berth_id:02d}_reid.npy")
            if not os.path.isfile(path):
                return None
            return np.load(path).astype(np.float32)
        except Exception as exc:
            logger.warning("ReidOVMatcher.load_embedding() error: %s", exc)
            return None

    def cosine_similarity(self, a, b) -> float:
        """Return cosine similarity between two numpy vectors (0–1 range)."""
        try:
            from scipy.spatial.distance import cosine  # lazy import
            return float(1.0 - cosine(a, b))
        except ImportError:
            # Fallback: pure numpy dot product (vectors are already L2-normalised)
            try:
                import numpy as np  # lazy import
                return float(np.dot(a, b))
            except Exception:
                return 0.0
        except Exception as exc:
            logger.warning("ReidOVMatcher.cosine_similarity() error: %s", exc)
            return 0.0
