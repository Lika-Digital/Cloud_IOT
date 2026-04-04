"""
YOLOv8n OpenVINO inference for berth occupancy detection.
Falls back gracefully to returning None results if OpenVINO is not available
(e.g. on 32-bit dev machine where the wheels cannot be installed).
"""
import io
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# YOLO class index for "boat" in the COCO dataset
_BOAT_CLASS_ID = 8


class YoloOVDetector:
    """
    Runs YOLOv8n in OpenVINO compiled-model mode.

    If the model files are missing or OpenVINO/numpy cannot be imported,
    `self.available` is set to False and `detect()` returns a safe no-op result.
    """

    def __init__(self, model_dir: str):
        self.available = False
        self._compiled_model: Any = None
        self._input_layer: Any = None
        self._output_layer: Any = None

        model_path = os.path.join(model_dir, "yolov8n_openvino")
        if not os.path.isdir(model_path):
            logger.debug("YoloOVDetector: model directory not found at %s — inference disabled", model_path)
            return

        # Find the XML file inside the directory
        xml_file = None
        try:
            for fname in os.listdir(model_path):
                if fname.endswith(".xml"):
                    xml_file = os.path.join(model_path, fname)
                    break
        except Exception:
            return

        if xml_file is None:
            logger.debug("YoloOVDetector: no .xml file in %s — inference disabled", model_path)
            return

        try:
            import openvino as ov  # type: ignore  # lazy import
            core = ov.Core()
            ov_model = core.read_model(xml_file)
            self._compiled_model = core.compile_model(ov_model, "CPU")
            self._input_layer = self._compiled_model.input(0)
            self._output_layer = self._compiled_model.output(0)
            self.available = True
            logger.info("YoloOVDetector: loaded model from %s", xml_file)
        except ImportError:
            logger.debug("YoloOVDetector: openvino not available — inference disabled")
        except Exception as exc:
            logger.warning("YoloOVDetector: failed to load model: %s", exc)

    def detect(self, frame_bytes: bytes, conf_threshold: float = 0.3) -> dict:
        """
        Run YOLOv8n detection on a JPEG frame.

        Returns:
            {
                "occupied": bool | None,
                "confidence": float,
                "detections": list[dict]   # each: {class_id, confidence, bbox}
            }

        If not available, returns occupied=None so callers can fall back to Laplacian.
        """
        if not self.available:
            return {"occupied": None, "confidence": 0.0, "detections": []}

        try:
            import numpy as np  # lazy import

            # Decode JPEG → numpy RGB
            from PIL import Image  # lazy import
            img = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
            orig_w, orig_h = img.size
            img_resized = img.resize((640, 640))
            arr = np.array(img_resized, dtype=np.float32) / 255.0  # HWC
            inp = arr.transpose(2, 0, 1)[np.newaxis, ...]           # NCHW

            result = self._compiled_model([inp])[self._output_layer]
            # YOLOv8 output shape: [1, 84, 8400] → transpose to [1, 8400, 84]
            if result.ndim == 3 and result.shape[1] == 84:
                result = result.transpose(0, 2, 1)

            detections = []
            if result.ndim == 3:
                rows = result[0]  # [8400, 84]
                for row in rows:
                    x_c, y_c, w, h = row[0], row[1], row[2], row[3]
                    class_scores = row[4:]
                    class_id = int(np.argmax(class_scores))
                    confidence = float(class_scores[class_id])
                    if class_id == _BOAT_CLASS_ID and confidence >= conf_threshold:
                        detections.append({
                            "class_id": class_id,
                            "confidence": confidence,
                            "bbox": {
                                "x_c": float(x_c / 640),
                                "y_c": float(y_c / 640),
                                "w": float(w / 640),
                                "h": float(h / 640),
                            },
                        })

            if detections:
                max_conf = max(d["confidence"] for d in detections)
                return {"occupied": True, "confidence": max_conf, "detections": detections}
            return {"occupied": False, "confidence": 0.0, "detections": []}

        except Exception as exc:
            logger.warning("YoloOVDetector.detect() error: %s", exc)
            return {"occupied": None, "confidence": 0.0, "detections": []}
