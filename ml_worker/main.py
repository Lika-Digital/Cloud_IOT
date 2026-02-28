"""
ML Worker — RT-DETR + DINOv2 inference microservice.

POST /analyze/berth
  Body: { video_source, reference_image, detect_conf_threshold, match_threshold,
          use_detection_zone, zone_x1, zone_y1, zone_x2, zone_y2, num_frames }
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

Detection pipeline:
  1. Sample N evenly-spaced frames from the video (default 4)
  2. Run RT-DETR on each frame with progressive confidence fallback
     (tries configured threshold, then 50% of it, then 0.08 minimum)
  3. If use_detection_zone=True, only count detections whose bbox centre
     falls within the configured zone (default: central 70% of the frame)
  4. Best detection across all frames → occupied_bit
  5. If occupied: crop vessel region, run DINOv2 → match against reference

Pilot expectations:
  Berth Full.mp4  + Full_Berth.jpg → occupied_bit=1, match_ok_bit=0, state_code=2, alarm=1
  Berth empty.mp4 (zone-based)     → occupied_bit=0, state_code=0, alarm=0
"""

import logging
from pathlib import Path
from typing import Optional, List, Tuple

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
MODELS_DIR      = Path("/models")      if Path("/models").exists()      else _root / "backend" / "models"
ASSETS_DIR      = Path("/assets")      if Path("/assets").exists()      else _root / "frontend" / "src" / "assets"
BACKGROUNDS_DIR = Path("/backgrounds") if Path("/backgrounds").exists()  else _root / "backend" / "backgrounds"
BACKGROUNDS_DIR.mkdir(parents=True, exist_ok=True)

RTDETR_PATH = MODELS_DIR / "rtdetr.onnx"
DINOV2_PATH = MODELS_DIR / "dinov2.onnx"

# Pre-screening: mean-absolute-difference threshold (0–255).
# Frames whose MAD vs. the background image stays below this value
# are considered "no change" and the berth is returned as FREE without
# running the expensive RT-DETR detector.
PRESCREEN_MAD_THRESHOLD = 18.0

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

def _extract_frames(video_path: Path, n: int = 4) -> List[Image.Image]:
    """
    Extract N evenly-spaced frames from a video file via PyAV.

    Collects all keyframes first, then samples N of them spread across the
    full duration.  This ensures we cover the entire video — important when
    the first keyframe does not show the vessel clearly.
    """
    container = av.open(str(video_path))
    keyframes: List[Image.Image] = []
    try:
        stream = container.streams.video[0]
        stream.codec_context.skip_frame = "NONKEY"
        for packet in container.demux(stream):
            for frame in packet.decode():
                if hasattr(frame, "to_image"):
                    keyframes.append(frame.to_image().convert("RGB"))
    finally:
        container.close()

    if not keyframes:
        raise RuntimeError(f"No decodeable frames in {video_path}")

    # Sample n evenly-spaced indices across available keyframes
    count = len(keyframes)
    if count <= n:
        return keyframes
    indices = [int(round(i * (count - 1) / (n - 1))) for i in range(n)]
    return [keyframes[i] for i in sorted(set(indices))]


def _progressive_thresholds(base: float) -> List[float]:
    """
    Return a list of thresholds to try in order (highest first).
    Falls back progressively so marina vessels with lower model confidence
    are still caught.
    """
    candidates = [base, base * 0.5, 0.08]
    seen = set()
    result = []
    for t in candidates:
        t = round(max(t, 0.03), 3)   # never go below 0.03 (too noisy)
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def _filter_by_zone(
    detections: List[Tuple],
    img_w: int,
    img_h: int,
    x1f: float,
    y1f: float,
    x2f: float,
    y2f: float,
) -> List[Tuple]:
    """
    Keep only detections whose bounding-box centre falls within the
    specified zone (fractions of image dimensions).
    """
    zx1 = x1f * img_w
    zy1 = y1f * img_h
    zx2 = x2f * img_w
    zy2 = y2f * img_h
    result = []
    for det in detections:
        dx1, dy1, dx2, dy2, score, cls = det
        cx = (dx1 + dx2) / 2.0
        cy = (dy1 + dy2) / 2.0
        if zx1 <= cx <= zx2 and zy1 <= cy <= zy2:
            result.append(det)
    return result


def _compute_mad(frame: Image.Image, background: Image.Image) -> float:
    """
    Mean absolute difference (MAD) between a video frame and a stored background
    reference image.  Both images are resized to a common small resolution
    (320×240) before comparison so the result is independent of resolution.

    Returns a value in [0, 255].  Values below PRESCREEN_MAD_THRESHOLD indicate
    "no significant change from the empty-berth reference → FREE".
    """
    size = (320, 240)
    f = np.array(frame.resize(size, Image.BILINEAR).convert("RGB"), dtype=np.float32)
    b = np.array(background.resize(size, Image.BILINEAR).convert("RGB"), dtype=np.float32)
    return float(np.mean(np.abs(f - b)))


# ── Request / response schemas ────────────────────────────────────────────────

class BerthAnalysisRequest(BaseModel):
    video_source: Optional[str] = None          # filename relative to /assets
    reference_image: Optional[str] = None       # filename relative to /assets
    background_image: Optional[str] = None      # filename relative to /backgrounds (empty-berth snapshot)
    detect_conf_threshold: float = 0.30
    match_threshold: float = 0.50

    # Multi-frame sampling — number of frames to extract and test
    num_frames: int = 4

    # Zone-based detection — restrict detections to a rectangular region
    # expressed as fractions of frame dimensions (0.0 – 1.0)
    use_detection_zone: bool = True
    zone_x1: float = 0.20                       # left edge   (default: 20% from left)
    zone_y1: float = 0.20                       # top edge    (default: 20% from top)
    zone_x2: float = 0.80                       # right edge  (default: 80% from left)
    zone_y2: float = 0.80                       # bottom edge (default: 80% from top)


class BerthAnalysisResponse(BaseModel):
    occupied_bit: int                            # 1 if vessel detected
    match_ok_bit: int                            # 1 if vessel matches reference
    state_code: int                              # 0=FREE 1=OK 2=WRONG
    alarm: int                                   # 1 when state_code == 2
    match_score: Optional[float]                 # cosine similarity (None if not computed)
    detection_score: Optional[float]             # highest RT-DETR confidence
    prescreened_free: bool = False               # True when pre-screening short-circuited RT-DETR
    prescreen_mad: Optional[float] = None        # MAD value from pre-screening (debug)
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
    RT-DETR → DINOv2 pipeline for one berth with multi-frame sampling,
    progressive confidence fallback, and optional zone-based filtering.

    Pipeline:
      1. Extract N evenly-spaced frames from video_source
      2. For each frame, run RT-DETR with progressive confidence fallback
         (base threshold → base/2 → 0.08) until a detection is found
      3. If use_detection_zone=True, discard detections outside the zone
      4. Track the highest-confidence detection across all frames
      5. If occupied: crop vessel region, run DINOv2 → match against reference
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

    # No video → Transit / unmonitored berth → always FREE
    if not req.video_source:
        return result

    video_path = ASSETS_DIR / req.video_source
    if not video_path.exists():
        result.error = f"Video not found: {video_path}"
        logger.warning(result.error)
        return result

    # ── Step 1: Extract multiple frames ──────────────────────────────────────
    try:
        frames = _extract_frames(video_path, n=req.num_frames)
    except Exception as e:
        result.error = f"Frame extraction failed: {e}"
        logger.error(result.error)
        return result

    logger.info("Extracted %d frame(s) from %s", len(frames), req.video_source)

    # ── Step 1b: Background pre-screening (cheap pixel diff) ─────────────────
    # If a stored empty-berth reference is configured, compare each frame against
    # it using mean absolute difference (MAD).  When all frames look similar to
    # the empty state (MAD < threshold) we skip the expensive RT-DETR step and
    # return FREE immediately.  This eliminates false positives from water
    # reflections, distant boats, and lighting changes.
    if req.background_image:
        bg_path = BACKGROUNDS_DIR / req.background_image
        if bg_path.exists():
            try:
                background = Image.open(bg_path).convert("RGB")
                mads = [_compute_mad(f, background) for f in frames]
                max_mad = max(mads)
                logger.info(
                    "Pre-screening MAD: max=%.1f  threshold=%.1f  background=%s",
                    max_mad, PRESCREEN_MAD_THRESHOLD, req.background_image,
                )
                if max_mad < PRESCREEN_MAD_THRESHOLD:
                    logger.info("Pre-screening: scene matches empty background → FREE (skipping RT-DETR)")
                    result.prescreened_free = True
                    result.prescreen_mad = round(max_mad, 2)
                    return result
                result.prescreen_mad = round(max_mad, 2)
            except Exception as exc:
                logger.warning("Pre-screening failed (continuing to RT-DETR): %s", exc)
        else:
            logger.warning("Background image not found: %s — skipping pre-screening", bg_path)

    # ── Step 2: RT-DETR vessel detection across all frames ───────────────────
    rtdetr = _get_rtdetr()
    if rtdetr is None:
        result.error = "rtdetr.onnx not found in /models — see README for model download"
        logger.warning(result.error)
        return result

    # best_det: (x1, y1, x2, y2, score, cls), best_frame: Image
    best_det: Optional[Tuple] = None
    best_frame: Optional[Image.Image] = None
    thresholds = _progressive_thresholds(req.detect_conf_threshold)

    # Minimum bbox area as a fraction of frame area — rejects noise/tiny blobs
    MIN_AREA_FRACTION = 0.005   # vessel must cover at least 0.5 % of the frame

    for frame in frames:
        img_w, img_h = frame.size
        frame_area = img_w * img_h
        for threshold in thresholds:
            try:
                detections = rtdetr.detect(frame, conf_threshold=threshold)
            except Exception as e:
                result.error = f"RT-DETR inference failed: {e}"
                logger.error(result.error)
                return result

            # Reject detections whose bbox is too small (noise / distant objects)
            detections = [
                d for d in detections
                if (d[2] - d[0]) * (d[3] - d[1]) >= MIN_AREA_FRACTION * frame_area
            ]

            # Prefer vessel-class detections.
            # Any-class fallback is allowed only at the base (configured) threshold;
            # at reduced thresholds the noise floor makes non-vessel hits unreliable.
            vessel_dets = [d for d in detections if d[5] in VESSEL_CLASSES]
            if not vessel_dets and threshold >= thresholds[0]:
                vessel_dets = detections

            # Apply zone filter if requested
            if req.use_detection_zone and vessel_dets:
                vessel_dets = _filter_by_zone(
                    vessel_dets, img_w, img_h,
                    req.zone_x1, req.zone_y1, req.zone_x2, req.zone_y2,
                )

            if not vessel_dets:
                continue  # nothing at this threshold; try lower

            candidate = max(vessel_dets, key=lambda d: d[4])
            if best_det is None or candidate[4] > best_det[4]:
                best_det = candidate
                best_frame = frame

            logger.info(
                "RT-DETR: frame hit — threshold=%.2f  detections=%d  best_score=%.3f  cls=%d  zone=%s",
                threshold, len(vessel_dets), candidate[4], candidate[5],
                "on" if req.use_detection_zone else "off",
            )
            break  # found at this threshold for this frame; move to next frame

    if best_det is None:
        # Nothing detected in any frame at any threshold → FREE
        logger.info(
            "RT-DETR: no vessel detected in %d frame(s) — thresholds tried: %s",
            len(frames), thresholds,
        )
        result.state_code = 0
        return result

    # Occupied
    x1, y1, x2, y2, det_score, _cls = best_det
    result.occupied_bit = 1
    result.detection_score = round(float(det_score), 4)
    logger.info(
        "RT-DETR: OCCUPIED — best_score=%.3f cls=%d  video=%s",
        det_score, _cls, req.video_source,
    )

    # ── Step 3: DINOv2 identity matching ─────────────────────────────────────
    if not req.reference_image:
        # No reference → OCCUPIED but identity unknown → WRONG (alarm)
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

    # Crop the detected vessel region from the best frame
    frame = best_frame  # type: ignore[assignment]
    img_w, img_h = frame.size
    cx1 = max(0, int(x1))
    cy1 = max(0, int(y1))
    cx2 = min(img_w, int(x2))
    cy2 = min(img_h, int(y2))
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


class CaptureBackgroundRequest(BaseModel):
    video_source: str       # filename relative to /assets
    output_name: str        # output JPEG filename saved under /backgrounds


@app.post("/capture/background")
def capture_background(req: CaptureBackgroundRequest):
    """
    Extract the middle frame from a video and save it as a JPEG background
    reference image under /backgrounds.  Call this once when the berth is
    known to be empty so the pre-screening has a clean baseline.
    """
    video_path = ASSETS_DIR / req.video_source
    if not video_path.exists():
        return {"error": f"Video not found: {video_path}"}

    try:
        frames = _extract_frames(video_path, n=5)
    except Exception as exc:
        return {"error": f"Frame extraction failed: {exc}"}

    # Use the middle frame as the most representative static background
    bg_frame = frames[len(frames) // 2]

    out_path = BACKGROUNDS_DIR / req.output_name
    bg_frame.save(str(out_path), "JPEG", quality=90)
    logger.info("Background captured: %s  (%dx%d)", out_path, *bg_frame.size)
    return {
        "saved": req.output_name,
        "width": bg_frame.size[0],
        "height": bg_frame.size[1],
        "path": str(out_path),
    }
