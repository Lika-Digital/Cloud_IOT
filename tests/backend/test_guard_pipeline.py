"""
Guard per-frame pipeline (step 2, v3.42)
========================================

`app/guard/pipeline.py` is the ONE code path shared by the worker and the probe: crop ->
visibility -> detect -> band. Replaying a clip must produce the same result as live
operation, so the pipeline knows nothing about ffmpeg, MQTT or the database.

The detector is injected, so these tests drive the real `process_frame` through a fake
detector — no openvino needed, and the fake lets us assert what the pipeline ASKS the
detector for, which is where two subtle requirements live:

  * detection must run at `uncertain_min`, not `conf_threshold`, or below-threshold
    detections are lost forever — and those rows are the missing A.5 accuracy numbers
    and the Phase 2 training index
  * an unavailable detector must be distinguishable from "nothing there"

  TC-GPL-01  three bands: none / uncertain / alarm
  TC-GPL-02  `none` stores nothing — absence is not a weak detection
  TC-GPL-03  only the alarm band sets `detected`; uncertain must NOT raise an alarm
  TC-GPL-04  detection runs at uncertain_min, so sub-threshold hits are still returned
  TC-GPL-05  an unavailable detector reports an error, not a clean frame
  TC-GPL-06  crop applies the zone and reports the crop size
  TC-GPL-07  zone=None passes the frame through untouched
  TC-GPL-08  pixel height is measured against the CROP, not the full frame
  TC-GPL-09  visibility: bright/detailed frame is not flagged
  TC-GPL-10  visibility: dark frame IS flagged, and detection still runs
  TC-GPL-11  visibility: featureless frame IS flagged
  TC-GPL-12  a crop failure degrades to a band-none result instead of raising
  TC-GPL-13  config validation rejects impossible thresholds and zones
  TC-GPL-14  the pipeline feeds the alarm rule correctly end to end
"""
from __future__ import annotations

import io

import pytest

from app.guard.alarm_rule import AlarmState
from app.guard.pipeline import (
    BAND_ALARM,
    BAND_NONE,
    BAND_UNCERTAIN,
    FrameResult,
    PipelineConfig,
    classify_band,
    crop_to_zone,
    measure_visibility,
    process_frame,
)


def _jpeg(w: int = 1920, h: int = 1080, colour=(90, 110, 130), noise: bool = True) -> bytes:
    """A JPEG of the given size. `noise=True` gives it detail so Laplacian variance is
    high, i.e. 'visible'; noise=False gives a flat frame, i.e. featureless."""
    import numpy as np
    from PIL import Image

    if noise:
        rng = np.random.default_rng(7)
        arr = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    else:
        arr = np.zeros((h, w, 3), dtype=np.uint8)
        arr[:, :] = colour
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


class FakeDetector:
    """Stands in for YoloOVDetector. Records the arguments it was called with."""

    def __init__(self, confidence: float | None = None, *, box_h_frac: float = 0.3,
                 unavailable: bool = False, n: int = 1):
        self.confidence = confidence
        self.box_h_frac = box_h_frac
        self.unavailable = unavailable
        self.n = n
        self.calls: list[dict] = []

    def detect_persons(self, jpeg: bytes, *, conf_threshold: float, iou_threshold: float):
        self.calls.append({
            "bytes": len(jpeg), "conf_threshold": conf_threshold,
            "iou_threshold": iou_threshold,
        })
        if self.unavailable:
            return {"occupied": None, "confidence": 0.0, "detections": [],
                    "inference_ms": None}
        if self.confidence is None or self.confidence < conf_threshold:
            return {"occupied": False, "confidence": 0.0, "detections": [],
                    "inference_ms": 250.0}
        dets = [{
            "class_id": 0, "class_name": "person", "confidence": self.confidence,
            "bbox": {"x_c": 0.5, "y_c": 0.5, "w": 0.1, "h": self.box_h_frac},
            "bbox_xyxy": [0.45, 0.5 - self.box_h_frac / 2, 0.55,
                          0.5 + self.box_h_frac / 2],
        } for _ in range(self.n)]
        return {"occupied": True, "confidence": self.confidence, "detections": dets,
                "inference_ms": 273.3}


# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("conf,expected", [
    (0.0, BAND_NONE), (0.05, BAND_NONE), (0.19, BAND_NONE),
    (0.20, BAND_UNCERTAIN), (0.35, BAND_UNCERTAIN), (0.49, BAND_UNCERTAIN),
    (0.50, BAND_ALARM), (0.9, BAND_ALARM), (1.0, BAND_ALARM),
])
def test_tc_gpl_01_three_bands(conf, expected):
    assert classify_band(conf, PipelineConfig()) == expected


def test_tc_gpl_02_none_band_stores_nothing():
    """A frame with nothing in it writes NO row. Absence must never be recorded as a weak
    detection, or the Phase 2 training set fills with noise."""
    r = process_frame(FakeDetector(0.10), _jpeg(640, 480), PipelineConfig())
    assert r.band == BAND_NONE
    assert r.worth_storing is False
    assert r.detections == []
    assert r.confidence == 0.0
    assert r.px_height == 0.0


def test_tc_gpl_03_only_alarm_band_counts_as_detected():
    cfg = PipelineConfig()
    uncertain = process_frame(FakeDetector(0.35), _jpeg(640, 480), cfg)
    assert uncertain.band == BAND_UNCERTAIN
    assert uncertain.detected is False, "an uncertain frame must NOT raise an alarm"
    assert uncertain.worth_storing is True, "but it MUST be stored"

    alarm = process_frame(FakeDetector(0.80), _jpeg(640, 480), cfg)
    assert alarm.band == BAND_ALARM
    assert alarm.detected is True
    assert alarm.worth_storing is True


def test_tc_gpl_04_detection_runs_at_uncertain_min_not_threshold():
    """If the pipeline asked the detector for conf_threshold, every sub-threshold detection
    would be lost — and those are exactly the rows that become the missing A.5 numbers and
    the Phase 2 training index. They cannot be recovered afterwards."""
    det = FakeDetector(0.35)
    cfg = PipelineConfig(conf_threshold=0.5, uncertain_min=0.2)
    r = process_frame(det, _jpeg(640, 480), cfg)

    assert det.calls[0]["conf_threshold"] == pytest.approx(0.2), (
        "the detector must be queried at uncertain_min, not conf_threshold"
    )
    assert det.calls[0]["iou_threshold"] == pytest.approx(cfg.iou_threshold)
    assert r.band == BAND_UNCERTAIN
    assert r.detections and r.detections[0]["confidence"] == pytest.approx(0.35)


def test_tc_gpl_05_unavailable_detector_is_not_a_clean_frame():
    """'Model unavailable' and 'nothing there' must never look the same — otherwise a
    broken detector reads as a quiet marina."""
    r = process_frame(FakeDetector(unavailable=True), _jpeg(640, 480), PipelineConfig())
    assert r.band == BAND_NONE
    assert r.error == "detector unavailable"
    assert r.detected is False
    assert r.worth_storing is False


def test_tc_gpl_06_crop_applies_zone_and_reports_size():
    jpeg = _jpeg(1920, 1080)
    cropped, size = crop_to_zone(jpeg, (0.2, 0.2, 0.8, 0.8))
    assert size == (1152, 648), "0.2-0.8 of 1920x1080"
    assert len(cropped) < len(jpeg)

    det = FakeDetector(0.8)
    r = process_frame(det, jpeg, PipelineConfig(zone=(0.2, 0.2, 0.8, 0.8)))
    assert r.crop_size == (1152, 648)
    assert det.calls[0]["bytes"] < len(jpeg), "the detector must receive the CROP"


def test_tc_gpl_07_zone_none_passes_through():
    jpeg = _jpeg(640, 480)
    out, size = crop_to_zone(jpeg, None)
    assert out is jpeg
    assert size == (640, 480)
    r = process_frame(FakeDetector(0.8), jpeg, PipelineConfig(zone=None))
    assert r.crop_size == (640, 480)


def test_tc_gpl_08_pixel_height_is_measured_against_the_crop():
    """The distance check depends on this. A box occupying 30 % of a 648 px crop is ~194 px;
    measuring against the full 1080 would report ~324 and overstate the range."""
    r = process_frame(
        FakeDetector(0.8, box_h_frac=0.3), _jpeg(1920, 1080),
        PipelineConfig(zone=(0.2, 0.2, 0.8, 0.8)),
    )
    assert r.crop_size == (1152, 648)
    assert r.px_height == pytest.approx(0.3 * 648, rel=0.01)


def test_tc_gpl_09_visible_frame_is_not_flagged():
    cfg = PipelineConfig()
    luma, var = measure_visibility(_jpeg(320, 240, noise=True))
    assert luma > cfg.visibility_min_luma
    assert var > cfg.visibility_min_variance
    r = process_frame(FakeDetector(0.8), _jpeg(320, 240, noise=True), cfg)
    assert r.limited_visibility is False
    assert r.luma is not None and r.variance is not None


def test_tc_gpl_10_dark_frame_is_flagged_but_detection_continues():
    """LIMITED_VISIBILITY is a flag, not a state: detection keeps running and the event is
    stamped, which is what makes a weak detection explainable later rather than mysterious.
    It is also how the system SAYS it cannot see, instead of silently finding nothing —
    night being out of scope on this camera."""
    dark = _jpeg(320, 240, colour=(5, 5, 5), noise=False)
    r = process_frame(FakeDetector(0.8), dark, PipelineConfig())
    assert r.limited_visibility is True
    assert r.band == BAND_ALARM, "detection must still run while visibility is poor"
    assert r.detected is True


def test_tc_gpl_11_featureless_frame_is_flagged():
    """A covered lens or heavy fog: bright enough, but no detail."""
    flat = _jpeg(320, 240, colour=(200, 200, 200), noise=False)
    luma, var = measure_visibility(flat)
    assert luma > 30, "flat grey is bright"
    assert var < 15, "but has no detail"
    r = process_frame(FakeDetector(None), flat, PipelineConfig())
    assert r.limited_visibility is True


def test_tc_gpl_12_crop_failure_degrades_instead_of_raising():
    """A corrupt frame must not take the worker down — one bad frame is not an outage."""
    r = process_frame(FakeDetector(0.8), b"not-a-jpeg-at-all", PipelineConfig())
    assert r.band == BAND_NONE
    assert r.error is not None and "crop failed" in r.error


def test_tc_gpl_13_config_validation():
    PipelineConfig()                                  # defaults are valid
    PipelineConfig(zone=None)
    with pytest.raises(ValueError):
        PipelineConfig(conf_threshold=0)
    with pytest.raises(ValueError):
        PipelineConfig(conf_threshold=1.5)
    with pytest.raises(ValueError):
        # uncertain_min above the alarm threshold would make the uncertain band empty
        PipelineConfig(conf_threshold=0.5, uncertain_min=0.6)
    with pytest.raises(ValueError):
        PipelineConfig(zone=(0.8, 0.2, 0.2, 0.8))     # x1 >= x2
    with pytest.raises(ValueError):
        PipelineConfig(zone=(0.0, 0.0, 1.5, 1.0))     # outside the frame


def test_tc_gpl_14_pipeline_feeds_the_alarm_rule():
    """End to end at the settled settings: 1 fps, 2 detections inside a 4 s window.

    Note the uncertain frame in the middle contributes NOTHING to the alarm, which is the
    band distinction doing its job.
    """
    cfg = PipelineConfig()
    state = AlarmState()
    frame = _jpeg(640, 480)

    script = [
        (0.0, FakeDetector(None)),      # nothing
        (1.0, FakeDetector(0.30)),      # uncertain — stored, but must not count
        (2.0, FakeDetector(0.70)),      # alarm band, 1st positive
        (3.0, FakeDetector(0.65)),      # alarm band, 2nd positive -> fires
    ]
    fired = []
    stored = 0
    for t, det in script:
        r = process_frame(det, frame, cfg)
        if r.worth_storing:
            stored += 1
        hit = state.observe(t, r.detected)
        if hit:
            fired.append((t, hit))

    assert stored == 3, "uncertain and both alarm frames are stored; the empty one is not"
    assert len(fired) == 1, "exactly one alarm"
    assert fired[0][0] == 3.0
    assert fired[0][1]["latency_s"] == pytest.approx(1.0), "from the first ALARM-band frame"
