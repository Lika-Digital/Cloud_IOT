"""
cv_services.py — module-level singletons for OpenVINO inference.

Import from here:
    from app.services.cv_services import yolo_detector, reid_matcher

Both singletons set `.available = False` if OpenVINO is not installed or
model files are absent, so callers can check before using them.
"""
import logging

from .model_paths import get_model_dir
from .yolo_openvino import YoloOVDetector
from .reid_openvino import ReidOVMatcher

logger = logging.getLogger(__name__)

_model_dir = get_model_dir()
logger.debug("cv_services: model_dir = %s", _model_dir)

yolo_detector = YoloOVDetector(_model_dir)
reid_matcher  = ReidOVMatcher(_model_dir)
