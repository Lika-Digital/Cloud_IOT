"""
YOLOv8 multi-class decode + NMS (Guard Stage A.5, v3.41)
========================================================

`yolo_openvino.py` was rewritten to support person detection (multi-class decode,
per-class thresholds, NMS, letterbox). The berth-occupancy path calls it with no
new arguments and MUST be bit-for-bit unaffected — that is the hard constraint on
this change, so TC-YMC-01 re-implements the PRE-REWRITE loop verbatim and asserts
the new code agrees with it exactly on random tensors.

These tests exercise only the pure post-processing helpers, so they run on the
32-bit dev box where the openvino wheel cannot be installed. Nothing here loads a
model; NUC-side proof of real detection is `scripts/guard_detect_probe.py`.

  TC-YMC-01  legacy defaults reproduce the pre-rewrite decode EXACTLY (fuzzed)
  TC-YMC-02  legacy default class set is boat-only
  TC-YMC-03  per_class finds a detection that argmax structurally cannot
  TC-YMC-04  per-class thresholds are honoured independently
  TC-YMC-05  NMS drops overlapping duplicates, keeps the highest confidence
  TC-YMC-06  NMS never changes max confidence  (why it is safe for the boat path)
  TC-YMC-07  NMS is class-aware — a person never suppresses a boat
  TC-YMC-08  iou_xyxy: identical / disjoint / half-overlap
  TC-YMC-09  letterbox meta maps a centred box back to the original frame
  TC-YMC-10  letterbox_image pads to square and preserves aspect ratio
  TC-YMC-11  class map parsed from metadata.yaml (flow + block style)
  TC-YMC-12  class map falls back to COCO-80 when metadata.yaml is absent
  TC-YMC-13  transposed and non-transposed raw layouts decode identically
  TC-YMC-14  empty / degenerate input is handled without raising
  TC-YMC-15  unknown select mode raises rather than silently returning nothing
"""
from __future__ import annotations

import numpy as np
import pytest

from app.services.yolo_openvino import (
    COCO_BOAT_CLASS_ID,
    COCO_PERSON_CLASS_ID,
    decode_output,
    iou_xyxy,
    letterbox_image,
    load_class_names,
    non_max_suppression,
)

NUM_CLASSES = 80
INPUT_SIZE = 640


# ─── reference implementation: the code as it was BEFORE the rewrite ─────────

def _legacy_decode(result: np.ndarray, conf_threshold: float) -> list[dict]:
    """Verbatim re-implementation of the pre-v3.41 `detect()` inner loop
    (yolo_openvino.py:96-118 at commit a0a1405). Do not 'improve' this — its
    whole purpose is to be the old behaviour."""
    _BOAT_CLASS_ID = 8
    if result.ndim == 3 and result.shape[1] == 84:
        result = result.transpose(0, 2, 1)

    detections = []
    if result.ndim == 3:
        rows = result[0]
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
    return detections


def _raw(anchors: int = 200, seed: int = 0, num_classes: int = NUM_CLASSES) -> np.ndarray:
    """Random YOLOv8-shaped output: [1, 4+nc, anchors]."""
    rng = np.random.default_rng(seed)
    boxes = rng.uniform(0, INPUT_SIZE, size=(4, anchors)).astype(np.float32)
    scores = rng.uniform(0, 1, size=(num_classes, anchors)).astype(np.float32)
    return np.concatenate([boxes, scores], axis=0)[np.newaxis, ...]


def _det(class_id: int, conf: float, xyxy: list[float]) -> dict:
    x1, y1, x2, y2 = xyxy
    return {
        "class_id": class_id, "class_name": str(class_id), "confidence": conf,
        "bbox": {"x_c": (x1 + x2) / 2, "y_c": (y1 + y2) / 2, "w": x2 - x1, "h": y2 - y1},
        "bbox_xyxy": xyxy,
    }


# ═══════════════════════════════════════════════════════════════════════════
# TC-YMC-01..02 — the berth path must not move
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("seed", [0, 1, 2, 7, 42, 1234])
@pytest.mark.parametrize("conf", [0.05, 0.3, 0.9])
def test_tc_ymc_01_legacy_defaults_match_pre_rewrite_exactly(seed, conf):
    """Fuzzed equivalence. If this ever fails, berth occupancy has regressed."""
    raw = _raw(anchors=300, seed=seed)

    legacy = _legacy_decode(raw, conf)
    # Exactly what detect() passes on a legacy call: boat class, argmax, no NMS.
    new = decode_output(raw, classes={COCO_BOAT_CLASS_ID}, default_conf=conf)

    assert len(new) == len(legacy), f"detection count changed ({len(new)} vs {len(legacy)})"
    for got, want in zip(new, legacy):
        assert got["class_id"] == want["class_id"]
        assert got["confidence"] == pytest.approx(want["confidence"], abs=0.0)
        for k in ("x_c", "y_c", "w", "h"):
            assert got["bbox"][k] == pytest.approx(want["bbox"][k], abs=0.0), f"bbox.{k} moved"

    # The two values berths.py actually consumes.
    legacy_occupied = bool(legacy)
    legacy_conf = max((d["confidence"] for d in legacy), default=0.0)
    assert bool(new) == legacy_occupied
    assert max((d["confidence"] for d in new), default=0.0) == pytest.approx(legacy_conf, abs=0.0)


def test_tc_ymc_02_decode_keeps_all_classes_when_unfiltered():
    """`decode_output` is the low-level primitive: classes=None means keep every
    class. The boat-only default lives one level up in `detect()` — locked by
    TC-YMC-16 so the berth caller cannot drift."""
    raw = _raw(anchors=400, seed=5)
    got = decode_output(raw, default_conf=0.01)
    assert got, "expected some detections at a permissive threshold"
    assert len({d["class_id"] for d in got}) > 1, "unfiltered decode should span classes"


# ═══════════════════════════════════════════════════════════════════════════
# TC-YMC-03..04 — multi-class decode
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ymc_03_per_class_finds_what_argmax_cannot():
    """The structural gap from the Stage A assessment: a person standing on a boat
    whose anchor scores `boat` highest is invisible to argmax selection."""
    raw = np.zeros((1, 4 + NUM_CLASSES, 1), dtype=np.float32)   # channels-first, 1 anchor
    raw[0, :4, 0] = [320, 320, 64, 160]
    raw[0, 4 + COCO_BOAT_CLASS_ID, 0] = 0.90     # top class
    raw[0, 4 + COCO_PERSON_CLASS_ID, 0] = 0.75   # present, but not the max

    argmax_hit = decode_output(raw, classes={COCO_PERSON_CLASS_ID}, default_conf=0.5,
                               select="argmax", layout="channels_first")
    assert argmax_hit == [], "argmax should miss the non-top-scoring person"

    per_class_hit = decode_output(raw, classes={COCO_PERSON_CLASS_ID}, default_conf=0.5,
                                 select="per_class", layout="channels_first")
    assert len(per_class_hit) == 1
    assert per_class_hit[0]["class_id"] == COCO_PERSON_CLASS_ID
    assert per_class_hit[0]["confidence"] == pytest.approx(0.75, abs=1e-6)


def test_tc_ymc_04_per_class_thresholds_are_independent():
    raw = np.zeros((1, 4 + NUM_CLASSES, 2), dtype=np.float32)
    raw[0, :4, 0] = [100, 100, 40, 80]
    raw[0, 4 + COCO_PERSON_CLASS_ID, 0] = 0.55
    raw[0, :4, 1] = [400, 400, 120, 60]
    raw[0, 4 + COCO_BOAT_CLASS_ID, 1] = 0.35

    got = decode_output(
        raw,
        classes={COCO_PERSON_CLASS_ID, COCO_BOAT_CLASS_ID},
        class_thresholds={COCO_PERSON_CLASS_ID: 0.50, COCO_BOAT_CLASS_ID: 0.30},
        select="per_class", layout="channels_first",
    )
    assert {d["class_id"] for d in got} == {COCO_PERSON_CLASS_ID, COCO_BOAT_CLASS_ID}

    # Raise only the person threshold — the boat must survive untouched.
    got2 = decode_output(
        raw,
        classes={COCO_PERSON_CLASS_ID, COCO_BOAT_CLASS_ID},
        class_thresholds={COCO_PERSON_CLASS_ID: 0.60, COCO_BOAT_CLASS_ID: 0.30},
        select="per_class", layout="channels_first",
    )
    assert {d["class_id"] for d in got2} == {COCO_BOAT_CLASS_ID}


# ═══════════════════════════════════════════════════════════════════════════
# TC-YMC-05..08 — NMS
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ymc_05_nms_drops_duplicates_keeps_best():
    dets = [
        _det(0, 0.90, [0.10, 0.10, 0.30, 0.50]),
        _det(0, 0.85, [0.11, 0.11, 0.31, 0.51]),   # ~same box
        _det(0, 0.80, [0.60, 0.10, 0.80, 0.50]),   # far away — must survive
    ]
    kept = non_max_suppression(dets, iou_threshold=0.45)
    assert len(kept) == 2
    assert kept[0]["confidence"] == pytest.approx(0.90)
    assert {round(d["confidence"], 2) for d in kept} == {0.90, 0.80}


@pytest.mark.parametrize("seed", [0, 3, 11, 99])
def test_tc_ymc_06_nms_never_changes_max_confidence(seed):
    """Why enabling NMS is safe for `occupied`/`confidence`: NMS only removes
    lower-confidence overlaps and never the global maximum."""
    rng = np.random.default_rng(seed)
    dets = []
    for _ in range(40):
        x1, y1 = rng.uniform(0, 0.8, 2)
        w, h = rng.uniform(0.05, 0.2, 2)
        dets.append(_det(int(rng.integers(0, 3)), float(rng.uniform(0, 1)),
                         [float(x1), float(y1), float(x1 + w), float(y1 + h)]))

    before = max(d["confidence"] for d in dets)
    kept = non_max_suppression(dets, 0.45)
    assert kept, "NMS emptied a non-empty set"
    assert max(d["confidence"] for d in kept) == pytest.approx(before, abs=0.0)
    assert bool(kept) == bool(dets)
    assert len(kept) <= len(dets)


def test_tc_ymc_07_nms_is_class_aware():
    """A person overlapping a boat must not suppress it — both are real."""
    box = [0.20, 0.20, 0.60, 0.70]
    dets = [
        _det(COCO_BOAT_CLASS_ID, 0.95, box),
        _det(COCO_PERSON_CLASS_ID, 0.60, [0.21, 0.21, 0.61, 0.71]),
    ]
    kept = non_max_suppression(dets, 0.45)
    assert len(kept) == 2
    assert {d["class_id"] for d in kept} == {COCO_BOAT_CLASS_ID, COCO_PERSON_CLASS_ID}


def test_tc_ymc_08_iou_basic_cases():
    assert iou_xyxy([0, 0, 1, 1], [0, 0, 1, 1]) == pytest.approx(1.0)
    assert iou_xyxy([0, 0, 1, 1], [2, 2, 3, 3]) == pytest.approx(0.0)
    assert iou_xyxy([0, 0, 1, 1], [5, 5, 6, 6]) == pytest.approx(0.0)
    # Half-overlap in x: intersection 0.5, union 1.5 → 1/3
    assert iou_xyxy([0, 0, 1, 1], [0.5, 0, 1.5, 1]) == pytest.approx(1 / 3, abs=1e-6)
    # Degenerate (zero-area) boxes must not divide by zero
    assert iou_xyxy([0, 0, 0, 0], [0, 0, 0, 0]) == pytest.approx(0.0)


# ═══════════════════════════════════════════════════════════════════════════
# TC-YMC-09..10 — letterbox
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ymc_09_letterbox_meta_maps_box_back_to_original():
    """A 1280×640 frame letterboxes to 640×320 with 160 px bands top and bottom.
    A detection at the canvas centre must map to the frame centre."""
    meta = {"scale": 0.5, "pad_x": 0.0, "pad_y": 160.0, "orig_w": 1280.0, "orig_h": 640.0}
    raw = np.zeros((1, 4 + NUM_CLASSES, 1), dtype=np.float32)   # channels-first, 1 anchor
    raw[0, :4, 0] = [320, 320, 100, 50]          # centre of the 640 canvas
    raw[0, 4 + COCO_PERSON_CLASS_ID, 0] = 0.9

    got = decode_output(raw, classes={COCO_PERSON_CLASS_ID}, default_conf=0.5,
                        select="per_class", letterbox_meta=meta, layout="channels_first")
    assert len(got) == 1
    b = got[0]["bbox"]
    assert b["x_c"] == pytest.approx(0.5, abs=1e-6)
    assert b["y_c"] == pytest.approx(0.5, abs=1e-6)
    # 100 px at scale 0.5 → 200 px of 1280 = 0.15625
    assert b["w"] == pytest.approx(200 / 1280, abs=1e-6)
    assert b["h"] == pytest.approx(100 / 640, abs=1e-6)

    # Without meta the same tensor normalises by the input edge instead (legacy).
    legacy = decode_output(raw, classes={COCO_PERSON_CLASS_ID}, default_conf=0.5,
                           select="per_class", layout="channels_first")
    assert legacy[0]["bbox"]["w"] == pytest.approx(100 / 640, abs=1e-6)


def test_tc_ymc_10_letterbox_pads_square_and_keeps_aspect():
    from PIL import Image
    img = Image.new("RGB", (1280, 640), (10, 20, 30))
    padded, meta = letterbox_image(img, 640)
    assert padded.size == (640, 640)
    assert meta["scale"] == pytest.approx(0.5)
    assert meta["pad_y"] == pytest.approx(160)
    assert meta["pad_x"] == pytest.approx(0)
    # Padding band is the neutral grey, image content is not
    assert padded.getpixel((320, 5)) == (114, 114, 114)
    assert padded.getpixel((320, 320)) == (10, 20, 30)

    # Square input needs no padding at all.
    sq, meta_sq = letterbox_image(Image.new("RGB", (400, 400)), 640)
    assert sq.size == (640, 640)
    assert meta_sq["pad_x"] == 0 and meta_sq["pad_y"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# TC-YMC-11..12 — class map
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ymc_11_class_names_parsed_from_metadata(tmp_path):
    # Flow style, as Ultralytics writes it
    (tmp_path / "metadata.yaml").write_text(
        "description: Ultralytics YOLOv8n\n"
        "task: detect\n"
        "names: {0: person, 1: bicycle, 8: boat}\n",
        encoding="utf-8",
    )
    names = load_class_names(str(tmp_path))
    assert names[0] == "person"
    assert names[8] == "boat"

    # Block style
    (tmp_path / "metadata.yaml").write_text(
        "task: detect\n"
        "names:\n"
        "  0: person\n"
        "  1: bicycle\n"
        "  8: boat\n"
        "imgsz: [640, 640]\n",
        encoding="utf-8",
    )
    names2 = load_class_names(str(tmp_path))
    assert names2[0] == "person"
    assert names2[8] == "boat"


def test_tc_ymc_12_class_names_fallback_is_coco80(tmp_path):
    names = load_class_names(str(tmp_path / "does-not-exist"))
    assert len(names) == 80
    assert names[COCO_PERSON_CLASS_ID] == "person"
    assert names[COCO_BOAT_CLASS_ID] == "boat"


# ═══════════════════════════════════════════════════════════════════════════
# TC-YMC-13..15 — robustness
# ═══════════════════════════════════════════════════════════════════════════

def test_tc_ymc_13_both_raw_layouts_decode_identically():
    raw = _raw(anchors=150, seed=21)              # [1, 84, 150]
    transposed = raw.transpose(0, 2, 1).copy()    # [1, 150, 84]
    a = decode_output(raw, default_conf=0.2)
    b = decode_output(transposed, default_conf=0.2)
    assert len(a) == len(b)
    for da, db in zip(a, b):
        assert da["class_id"] == db["class_id"]
        assert da["confidence"] == pytest.approx(db["confidence"], abs=0.0)


def test_tc_ymc_14_degenerate_inputs_do_not_raise():
    assert decode_output(np.zeros((1, 84, 0), dtype=np.float32)) == []
    assert decode_output(np.zeros((84, 100), dtype=np.float32)) == []   # wrong ndim
    assert non_max_suppression([]) == []
    assert len(non_max_suppression([_det(0, 0.5, [0, 0, 1, 1])])) == 1
    # No class survives the filter → empty, not an exception.
    # anchors must exceed the 84 channels or layout="auto" cannot tell them apart.
    raw = _raw(anchors=200, seed=4)
    assert decode_output(raw, classes=set(), select="per_class") == []
    assert decode_output(raw, default_conf=1.01) == []


def test_tc_ymc_15_unknown_select_mode_raises():
    with pytest.raises(ValueError, match="select"):
        decode_output(_raw(anchors=10), select="nonsense")
    with pytest.raises(ValueError, match="layout"):
        decode_output(_raw(anchors=10), layout="sideways")


# ═══════════════════════════════════════════════════════════════════════════
# TC-YMC-16..18 — detect() itself, via a fake compiled model
#
# The contract that actually matters to berth occupancy lives in detect(), not in
# decode_output. openvino cannot be installed on the 32-bit dev box, so we stub
# the compiled model and exercise the real detect() body: preprocessing choice,
# default class set, NMS toggle and teardown.
# ═══════════════════════════════════════════════════════════════════════════

class _FakeCompiledModel:
    """Mimics `ov.CompiledModel.__call__` → {output_layer: ndarray}."""

    OUTPUT_KEY = "out0"

    def __init__(self, raw: np.ndarray):
        self._raw = raw
        self.calls: list[tuple] = []

    def __call__(self, inputs):
        self.calls.append(np.asarray(inputs[0]).shape)
        return {self.OUTPUT_KEY: self._raw}


def _fake_detector(raw: np.ndarray):
    """A YoloOVDetector wired to a fake model, bypassing __init__/openvino."""
    from app.services.yolo_openvino import YoloOVDetector

    det = YoloOVDetector.__new__(YoloOVDetector)
    det.available = True
    det._compiled_model = _FakeCompiledModel(raw)
    det._input_layer = None
    det._output_layer = _FakeCompiledModel.OUTPUT_KEY
    det.class_names = {COCO_PERSON_CLASS_ID: "person", COCO_BOAT_CLASS_ID: "boat"}
    det.model_path = "fake.xml"
    det.last_inference_ms = None
    return det


def _jpeg(w: int = 1280, h: int = 648) -> bytes:
    """A JPEG of the given size — default mimics the berth zone crop (60 % of 1080p)."""
    import io as _io
    from PIL import Image
    buf = _io.BytesIO()
    Image.new("RGB", (w, h), (40, 80, 120)).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _tensor_with(class_id: int, conf: float, anchors: int = 200) -> np.ndarray:
    """Channels-first tensor with one strong detection of `class_id`, padded with
    enough empty anchors that layout auto-detection is unambiguous."""
    raw = np.zeros((1, 4 + NUM_CLASSES, anchors), dtype=np.float32)
    raw[0, :4, 0] = [320, 320, 80, 200]
    raw[0, 4 + class_id, 0] = conf
    return raw


def test_tc_ymc_16_detect_defaults_to_boat_only_no_nms_no_letterbox():
    """The berth-occupancy call signature. A person in frame must NOT register,
    and the input must be the legacy distorting 640×640 resize."""
    det = _fake_detector(_tensor_with(COCO_PERSON_CLASS_ID, 0.95))
    res = det.detect(_jpeg(), conf_threshold=0.3)     # exactly how berths.py calls it

    assert res["occupied"] is False, "a person must not satisfy the boat-only default"
    assert res["detections"] == []
    assert res["confidence"] == 0.0
    # Legacy preprocessing: square resize, so the tensor handed to the model is 640×640.
    assert det._compiled_model.calls == [(1, 3, 640, 640)]

    boat = _fake_detector(_tensor_with(COCO_BOAT_CLASS_ID, 0.77))
    res2 = boat.detect(_jpeg(), conf_threshold=0.3)
    assert res2["occupied"] is True
    assert res2["confidence"] == pytest.approx(0.77, abs=1e-6)
    assert res2["detections"][0]["class_name"] == "boat"


def test_tc_ymc_17_detect_persons_uses_person_class_nms_and_letterbox():
    det = _fake_detector(_tensor_with(COCO_PERSON_CLASS_ID, 0.82))
    res = det.detect_persons(_jpeg(), conf_threshold=0.5)

    assert res["occupied"] is True
    assert res["confidence"] == pytest.approx(0.82, abs=1e-6)
    assert [d["class_id"] for d in res["detections"]] == [COCO_PERSON_CLASS_ID]
    assert res["detections"][0]["class_name"] == "person"
    assert res["inference_ms"] is not None and res["inference_ms"] >= 0
    # Still a 640² tensor, but letterboxed — bbox maps back to the ORIGINAL 1280×648
    # crop, so a box at the canvas centre stays centred rather than being stretched.
    assert det._compiled_model.calls == [(1, 3, 640, 640)]
    b = res["detections"][0]["bbox"]
    assert b["x_c"] == pytest.approx(0.5, abs=0.02)
    assert b["y_c"] == pytest.approx(0.5, abs=0.02)

    # Below its threshold the same frame yields nothing.
    quiet = _fake_detector(_tensor_with(COCO_PERSON_CLASS_ID, 0.40))
    assert quiet.detect_persons(_jpeg(), conf_threshold=0.5)["occupied"] is False


def test_tc_ymc_18_unload_releases_model_and_disables_detect():
    """Guard must hold no model while disarmed — detect() has to go inert."""
    det = _fake_detector(_tensor_with(COCO_PERSON_CLASS_ID, 0.9))
    assert det.detect_persons(_jpeg())["occupied"] is True

    det.unload()
    assert det.available is False
    assert det._compiled_model is None
    # Inert, and reports "unavailable" (None) rather than a false negative.
    after = det.detect_persons(_jpeg())
    assert after["occupied"] is None
    assert after["detections"] == []
    det.unload()   # idempotent


def test_tc_ymc_19_detect_returns_none_when_unavailable():
    """Unavailable must stay distinguishable from 'nothing detected', because
    berths.py falls back to Laplacian on None and trusts False."""
    from app.services.yolo_openvino import YoloOVDetector

    det = YoloOVDetector.__new__(YoloOVDetector)
    det.available = False
    res = det.detect(_jpeg())
    assert res["occupied"] is None
    assert res["confidence"] == 0.0
    assert res["detections"] == []
