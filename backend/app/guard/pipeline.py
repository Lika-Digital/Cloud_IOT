"""
Guard per-frame pipeline — the ONE code path shared by the worker and the probe.

Build order step 2. Given a JPEG frame it crops to the detection zone, measures
visibility, runs person detection, and classifies the result into a band. It does not
decide alarms (that is `alarm_rule.py`) and it does not touch MQTT, the database or
ffmpeg — so replaying a recorded clip through it produces the same result as live
operation, which is the "probe and worker share one code path" requirement.

Import-time dependencies are stdlib + numpy + PIL ONLY. No FastAPI, no SQLAlchemy, no
openvino at module level. That is what keeps the probe runnable from the staging venv
(proved in the Stage A.5 addendum §A1), and `test_guard_import_isolation.py` asserts it so
a future import cannot quietly break the measurement flow.

Phase 2 hooks, designed in from the start (not built):

  * a frame result carries **confidence and a frame reference, never a boolean**
  * `band` distinguishes `uncertain` from `none` — "we are not sure" is a different fact
    from "nothing there", and only the former is worth storing and escalating later
  * the alarm decision is a separate module, so escalating an uncertain frame to a central
    GPU before deciding touches one place
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Bands. `none` deliberately writes no row: absence must never be confused with a weak hit.
BAND_NONE = "none"
BAND_UNCERTAIN = "uncertain"
BAND_ALARM = "alarm"


@dataclass(frozen=True)
class PipelineConfig:
    """Runtime-tunable detection settings.

    Every field here is changeable without a redeploy via
    `PATCH /api/guard/{camera_id}/config` and is pushed to the worker in the next command;
    accuracy is unproven, so it has to be tunable in production. The thread count is NOT
    here because OpenVINO fixes it at `compile_model` time — it is read once at worker
    start instead.
    """
    conf_threshold: float = 0.50        # at/above this, a detection can raise an alarm
    uncertain_min: float = 0.20         # at/above this but below threshold -> "uncertain"
    zone: tuple[float, float, float, float] | None = (0.20, 0.20, 0.80, 0.80)
    iou_threshold: float = 0.45
    # Visibility. Not a state — a flag, because detection keeps running while flagged and
    # every event raised during it is stamped, which is what makes a weak detection
    # explainable later rather than mysterious.
    visibility_min_luma: float = 30.0
    visibility_min_variance: float = 15.0

    def __post_init__(self) -> None:
        if not 0.0 < self.conf_threshold <= 1.0:
            raise ValueError("conf_threshold must be in (0, 1]")
        if not 0.0 < self.uncertain_min <= self.conf_threshold:
            raise ValueError("uncertain_min must be in (0, conf_threshold]")
        if self.zone is not None:
            x1, y1, x2, y2 = self.zone
            if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
                raise ValueError(f"zone {self.zone} must be fractional with x1<x2, y1<y2")


@dataclass
class FrameResult:
    """What one processed frame yields.

    `detected` exists only as a convenience for the alarm rule; the persisted record is
    the detections themselves plus confidence, pixel height and the frame reference.
    """
    band: str
    detections: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    px_height: float = 0.0
    inference_ms: float | None = None
    crop_size: tuple[int, int] | None = None
    luma: float | None = None
    variance: float | None = None
    limited_visibility: bool = False
    # Set by the worker once it has written the frame out; None when no frame was kept.
    frame_path: str | None = None
    error: str | None = None

    @property
    def detected(self) -> bool:
        """True only in the alarm band. An uncertain frame must NOT raise an alarm — that
        is the whole point of having a band between 'nothing' and 'sure'."""
        return self.band == BAND_ALARM

    @property
    def worth_storing(self) -> bool:
        """Uncertain and alarm frames are stored; `none` writes nothing at all."""
        return self.band in (BAND_UNCERTAIN, BAND_ALARM)


def crop_to_zone(
    jpeg: bytes,
    zone: tuple[float, float, float, float] | None,
    *,
    quality: int = 90,
) -> tuple[bytes, tuple[int, int]]:
    """Crop to a fractional zone, returning (jpeg, (width, height)).

    The crop is MANDATORY for person detection and is not a cost-saving measure: because
    it happens BEFORE the 640 resize it acts as a free digital zoom. Measured geometry at
    the stern (~10 m): a person is ~79 px tall through the crop versus ~47 px full-frame,
    which moves the usable range from ~15 m to ~25-30 m.
    """
    import io
    from PIL import Image

    img = Image.open(io.BytesIO(jpeg)).convert("RGB")
    if zone is None:
        return jpeg, img.size

    w, h = img.size
    x1, y1, x2, y2 = zone
    box = (int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h))
    cropped = img.crop(box)
    buf = io.BytesIO()
    cropped.save(buf, format="JPEG", quality=quality)
    return buf.getvalue(), cropped.size


def measure_visibility(jpeg: bytes) -> tuple[float, float]:
    """Return (mean_luma, laplacian_variance) for the frame.

    Cheap, because we already hold the decoded frame. Low luma means dusk or night; low
    variance means a covered lens, fog or a featureless view. Together they are how the
    system SAYS it cannot see, rather than silently failing to detect — which matters
    because night is out of scope on this camera (no IR illuminator, poor sensor) and the
    honest behaviour is to report the condition, not to pretend nothing is there.

    Laplacian via array slicing, matching `berth_analyzer.detect_ship` so there is one
    convention in the codebase and no scipy dependency.
    """
    import io

    import numpy as np
    from PIL import Image

    gray = np.asarray(
        Image.open(io.BytesIO(jpeg)).convert("L"), dtype=np.float32,
    )
    if gray.size == 0:
        return 0.0, 0.0
    luma = float(gray.mean())
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return luma, 0.0
    lap = (
        gray[:-2, 1:-1] + gray[2:, 1:-1]
        + gray[1:-1, :-2] + gray[1:-1, 2:]
        - 4 * gray[1:-1, 1:-1]
    )
    return luma, float(np.var(lap))


def classify_band(confidence: float, cfg: PipelineConfig) -> str:
    """Map a confidence to a band.

    Three outcomes, not two: `none` writes no row at all (absence is absence), `uncertain`
    is stored and is the Phase 2 escalation/training candidate, `alarm` can fire the rule.
    """
    if confidence >= cfg.conf_threshold:
        return BAND_ALARM
    if confidence >= cfg.uncertain_min:
        return BAND_UNCERTAIN
    return BAND_NONE


def process_frame(detector: Any, jpeg: bytes, cfg: PipelineConfig) -> FrameResult:
    """Crop -> visibility -> detect -> classify. The single per-frame code path.

    `detector` is a `YoloOVDetector` built via `YoloOVDetector.for_guard()`, which fixes
    single-threaded inference. It is injected rather than constructed here so this module
    stays free of an openvino import and remains usable from the staging venv.

    Detection runs at `uncertain_min`, NOT at `conf_threshold`: every detection above the
    logging floor is returned so below-threshold ones can be recorded. Those rows are the
    missing A.5 accuracy numbers and the Phase 2 training index, and they cannot be
    recovered after the fact.
    """
    try:
        crop, crop_size = crop_to_zone(jpeg, cfg.zone)
    except Exception as exc:
        logger.warning("Guard pipeline: crop failed: %s", exc)
        return FrameResult(band=BAND_NONE, error=f"crop failed: {exc}")

    luma = variance = None
    try:
        luma, variance = measure_visibility(crop)
    except Exception as exc:
        # Visibility is diagnostic; losing it must not lose the detection.
        logger.debug("Guard pipeline: visibility measurement failed: %s", exc)

    limited = bool(
        luma is not None and variance is not None
        and (luma < cfg.visibility_min_luma or variance < cfg.visibility_min_variance)
    )

    result = detector.detect_persons(
        crop, conf_threshold=cfg.uncertain_min, iou_threshold=cfg.iou_threshold,
    )

    if result.get("occupied") is None:
        # Unavailable is NOT "nothing there" — say so, rather than reporting a clean frame.
        return FrameResult(
            band=BAND_NONE, crop_size=crop_size, luma=luma, variance=variance,
            limited_visibility=limited, error="detector unavailable",
        )

    detections = result.get("detections") or []
    confidence = float(result.get("confidence") or 0.0)
    px_height = 0.0
    if detections and crop_size:
        px_height = max(
            (d["bbox_xyxy"][3] - d["bbox_xyxy"][1]) * crop_size[1] for d in detections
        )

    band = classify_band(confidence, cfg)
    # Keep only detections at or above the logging floor; below that is noise, not data.
    kept = [d for d in detections if d["confidence"] >= cfg.uncertain_min]

    return FrameResult(
        band=band,
        detections=kept if band != BAND_NONE else [],
        confidence=confidence if band != BAND_NONE else 0.0,
        px_height=px_height if band != BAND_NONE else 0.0,
        inference_ms=result.get("inference_ms"),
        crop_size=crop_size,
        luma=luma,
        variance=variance,
        limited_visibility=limited,
    )
