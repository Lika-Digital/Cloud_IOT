"""
cv_services.py — module-level singletons for OpenVINO inference.

Import from here:
    from app.services.cv_services import yolo_detector, reid_matcher

Both singletons set `.available = False` if OpenVINO is not installed,
model files are absent, OR USE_ML_MODELS=false in config (the default).

To enable OpenVINO inference on the NUC:
  1. Run backend/setup_openvino_models.py once to export models
  2. Set USE_ML_MODELS=true in backend/.env
  3. Restart the backend service
  4. Check logs for "inference_ms" to measure latency on your hardware
"""
import logging

from .model_paths import get_model_dir
from .yolo_openvino import YoloOVDetector
from .reid_openvino import ReidOVMatcher

logger = logging.getLogger(__name__)

# Read config here to avoid circular imports
try:
    from app.config import settings as _settings
    _ml_enabled = _settings.use_ml_models
except Exception:
    _ml_enabled = False

if not _ml_enabled:
    logger.info(
        "cv_services: USE_ML_MODELS=false — OpenVINO inference disabled. "
        "Using Laplacian+histogram fallback. "
        "Set USE_ML_MODELS=true in .env to enable ML inference."
    )

_model_dir = get_model_dir()
logger.debug("cv_services: model_dir = %s", _model_dir)

# Only attempt to load models if explicitly enabled
yolo_detector = YoloOVDetector(_model_dir) if _ml_enabled else YoloOVDetector.__new__(YoloOVDetector)
reid_matcher  = ReidOVMatcher(_model_dir)  if _ml_enabled else ReidOVMatcher.__new__(ReidOVMatcher)

if not _ml_enabled:
    # Mark both as unavailable without touching model files
    yolo_detector.available = False
    reid_matcher.available  = False
