"""
ML Worker — RT-DETR + DINOv2 inference microservice.

POST /analyze/berth
  Body: { video_source, reference_image, detect_conf_threshold, match_threshold }
  Returns: { occupied_bit, match_ok_bit, state_code, alarm, match_score, error }

POST /embed/image
  Body: { image_path }
  Returns: { embedding: List[float] }

GET /health
  Returns: { status, rtdetr_loaded, dinov2_loaded }

Models (ONNX) are mounted at /models:
  /models/rtdetr.onnx
  /models/dinov2.onnx

Assets are mounted at /assets:
  /assets/Berth Full.mp4     — occupied test video (berth 1)
  /assets/Berth empty.mp4   — free test video (berth 2)
  /assets/Full_Berth.jpg    — reference ship image for berth 1

State codes:
  0 = FREE
  1 = OCCUPIED_CORRECT   (vessel detected, matches stored sample)
  2 = OCCUPIED_WRONG     (vessel detected, does NOT match stored sample) → alarm = 1

Pilot expectation:
  Berth Full.mp4  + Full_Berth.jpg → occupied_bit=1, match_ok_bit=0, state_code=2, alarm=1
  Berth empty.mp4                  → occupied_bit=0, state_code=0, alarm=0
"""

import logging
from pathlib import Path
from typing import Optional

import av
import numpy as np
from fastapi import FastAPI
from PIL import Image
from pydantic import BaseModel

from inference.rtdetr import RTDETRSession, VESSEL_CLASSES
from inference.dinov2 import DINOv2Session

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Docker paths take priority; fall back to native Windows paths
_root = Path(__file__).parent.parent
MODELS_DIR = Path("/models") if Path("/models").exists() else _root / "backend" / "models"
ASSETS_DIR = Path("/assets") if Path("/assets").exists() else _root / "frontend" / "src" / "assets"

RTDETR_PATH = MODELS_DIR / "rtdetr.onnx"
DINOV2_PATH = MODELS_DIR / "dinov2.onnx"

app = FastAPI(title="ML Worker", version="1.0.0")


# ── Singleton sessions ────────────────────────────────────────────────────────

_rtdetr: Optional[RTDETRSession] = None
_dinov2: Optional[DINOv2Session] = None
_ref_cache: dict[str, np.ndarray] = {}


def _get_rtdetr() -> Optional[RTDETRSession]:
    global _rtdetr
    if _rtdetr is None and RTDETR_PATH.exists():
        try:
            _rtdetr = RTDETRSession(RTDETR_PATH)
            logger.info("RT-DETR loaded from %s", RTDETR_PATH)
        except Exception as e:
            logger.error("RT-DETR load failed: %s", e)
    return _rtdetr


def _get_dinov2() -> Optional[DINOv2Session]:
    global _dinov2
    if _dinov2 is None and DINOV2_PATH.exists():
        try:
            _dinov2 = DINOv2Session(DINOV2_PATH)
            logger.info("DINOv2 loaded from %s", DINOV2_PATH)
        except Exception as e:
            logger.error("DINOv2 load failed: %s", e)
    return _dinov2


def _reference_embedding(ref_path: Path) -> np.ndarray:
    """Compute (and cache) the L2-normalised DINOv2 embedding for a reference image."""
    key = str(ref_path)
    if key not in _ref_cache:
        dinov2 = _get_dinov2()
        if dinov2 is None:
            raise RuntimeError("DINOv2 model not available")
        img = Image.open(ref_path).convert("RGB")
        _ref_cache[key] = dinov2.embed(img)
        logger.info("Cached reference embedding for %s  dim=%d", ref_path.name, len(_ref_cache[key]))
    return _ref_cache[key]


# ── Video frame extraction ────────────────────────────────────────────────────

def _extract_frame(video_path: Path) -> Image.Image:
    """Extract first decodeable keyframe from a video file via PyAV."""
    container = av.open(str(video_path))
    try:
        stream = container.streams.video[0]
        stream.codec_context.skip_frame = "NONKEY"
        for packet in container.demux(stream):
            for frame in packet.decode():
                if hasattr(frame, "to_image"):
                    return frame.to_image().convert("RGB")
    finally:
        container.close()
    raise RuntimeError(f"No decodeable frame in {video_path}")


# ── Request / response schemas ────────────────────────────────────────────────

class BerthAnalysisRequest(BaseModel):
    video_source: Optional[str] = None          # filename relative to /assets
    reference_image: Optional[str] = None       # filename relative to /assets
    detect_conf_threshold: float = 0.30
    match_threshold: float = 0.50


class BerthAnalysisResponse(BaseModel):
    occupied_bit: int                            # 1 if vessel detected
    match_ok_bit: int                            # 1 if vessel matches reference
    state_code: int                              # 0=FREE 1=OK 2=WRONG
    alarm: int                                   # 1 when state_code == 2
    match_score: Optional[float]                 # cosine similarity (None if not computed)
    detection_score: Optional[float]             # highest RT-DETR confidence
    error: Optional[str]


class EmbedRequest(BaseModel):
    image_path: str                              # absolute path or relative to /assets


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    rtdetr_ok = RTDETR_PATH.exists()
    dinov2_ok = DINOV2_PATH.exists()
    return {
        "status": "ok",
        "rtdetr_model_present": rtdetr_ok,
        "dinov2_model_present": dinov2_ok,
        "rtdetr_loaded": _rtdetr is not None,
        "dinov2_loaded": _dinov2 is not None,
        "assets_dir": str(ASSETS_DIR),
        "models_dir": str(MODELS_DIR),
    }


@app.post("/analyze/berth", response_model=BerthAnalysisResponse)
def analyze_berth(req: BerthAnalysisRequest):
    """
    Full RT-DETR → DINOv2 pipeline for one berth.

    Pipeline:
      1. Extract representative frame from video_source
      2. Run RT-DETR on full frame → occupied_bit
      3. If occupied: crop best vessel bbox, run DINOv2 → match against reference
      4. Compute state_code and alarm

    Pilot expectations:
      "Berth Full.mp4"  → occupied_bit=1, match_ok_bit=0, state_code=2, alarm=1
      "Berth empty.mp4" → occupied_bit=0, state_code=0, alarm=0
    """
    result = BerthAnalysisResponse(
        occupied_bit=0,
        match_ok_bit=0,
        state_code=0,   # FREE
        alarm=0,
        match_score=None,
        detection_score=None,
        error=None,
    )

    # No video → berth is Transit / not monitored → always FREE
    if not req.video_source:
        return result

    video_path = ASSETS_DIR / req.video_source
    if not video_path.exists():
        result.error = f"Video not found: {video_path}"
        logger.warning(result.error)
        return result

    # ── Step 1: Extract frame ─────────────────────────────────────────────────
    try:
        frame = _extract_frame(video_path)
    except Exception as e:
        result.error = f"Frame extraction failed: {e}"
        logger.error(result.error)
        return result

    # ── Step 2: RT-DETR vessel detection ──────────────────────────────────────
    rtdetr = _get_rtdetr()
    if rtdetr is None:
        result.error = "rtdetr.onnx not found in /models — see README for model download"
        logger.warning(result.error)
        return result

    try:
        detections = rtdetr.detect(frame, conf_threshold=req.detect_conf_threshold)
    except Exception as e:
        result.error = f"RT-DETR inference failed: {e}"
        logger.error(result.error)
        return result

    # Accept vessel-class detections first; fall back to any detection
    vessel_dets = [d for d in detections if d[5] in VESSEL_CLASSES]
    if not vessel_dets:
        vessel_dets = detections   # fine-tuned model may use class 0 for vessels

    if not vessel_dets:
        # Nothing detected → FREE
        result.state_code = 0
        return result

    # Occupied
    result.occupied_bit = 1
    best = max(vessel_dets, key=lambda d: d[4])
    x1, y1, x2, y2, det_score, _cls = best
    result.detection_score = round(float(det_score), 4)
    logger.info(
        "RT-DETR: detected %d object(s), best score=%.3f cls=%d  video=%s",
        len(vessel_dets), det_score, _cls, req.video_source,
    )

    # ── Step 3: DINOv2 identity matching ──────────────────────────────────────
    if not req.reference_image:
        # No reference image → cannot verify → OCCUPIED_WRONG
        result.state_code = 2
        result.alarm = 1
        return result

    ref_path = ASSETS_DIR / req.reference_image
    if not ref_path.exists():
        result.error = f"Reference image not found: {ref_path}"
        result.state_code = 2
        result.alarm = 1
        return result

    dinov2 = _get_dinov2()
    if dinov2 is None:
        result.error = "dinov2.onnx not found in /models — see README for model download"
        result.state_code = 2
        result.alarm = 1
        return result

    # Crop the detected vessel region
    img_w, img_h = frame.size
    cx1 = max(0, int(x1));  cy1 = max(0, int(y1))
    cx2 = min(img_w, int(x2)); cy2 = min(img_h, int(y2))
    vessel_crop = frame.crop((cx1, cy1, cx2, cy2)) if cx2 > cx1 and cy2 > cy1 else frame

    try:
        e_live = dinov2.embed(vessel_crop)
        e_ref  = _reference_embedding(ref_path)
    except Exception as e:
        result.error = f"DINOv2 embedding failed: {e}"
        result.state_code = 2
        result.alarm = 1
        return result

    # Cosine similarity (both vectors are L2-normalised → dot product = cos θ)
    match_score = float(np.dot(e_live, e_ref))
    result.match_score = round(match_score, 4)

    logger.info(
        "DINOv2: match_score=%.4f  threshold=%.2f  ref=%s",
        match_score, req.match_threshold, req.reference_image,
    )

    if match_score >= req.match_threshold:
        result.match_ok_bit = 1
        result.state_code = 1   # OCCUPIED_CORRECT
    else:
        result.match_ok_bit = 0
        result.state_code = 2   # OCCUPIED_WRONG
        result.alarm = 1

    return result


@app.post("/embed/image")
def embed_image(req: EmbedRequest):
    """Compute DINOv2 embedding for a single image. Useful for pre-computing reference embeddings."""
    dinov2 = _get_dinov2()
    if dinov2 is None:
        return {"error": "DINOv2 model not loaded"}
    p = Path(req.image_path) if Path(req.image_path).is_absolute() else ASSETS_DIR / req.image_path
    if not p.exists():
        return {"error": f"Image not found: {p}"}
    img = Image.open(p).convert("RGB")
    vec = dinov2.embed(img)
    return {"embedding": vec.tolist(), "dim": len(vec)}
