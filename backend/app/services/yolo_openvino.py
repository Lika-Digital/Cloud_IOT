"""
YOLOv8n OpenVINO inference — multi-class, per-class thresholds, NMS.

Falls back gracefully to returning None results if OpenVINO is not available
(e.g. on the 32-bit dev machine where the wheels cannot be installed).

v3.41 (Guard Stage A.5) — rewritten for person detection.

BACKWARD COMPATIBILITY IS LOAD-BEARING HERE. The berth-occupancy path
(`routers/berths.py`) calls `detect(crop, conf_threshold=...)` with no new
arguments, and that call must behave EXACTLY as it did before this rewrite.
The defaults below therefore reproduce the legacy pipeline bit-for-bit:

    classes={8} (boat) · select="argmax" · apply_nms=False · letterbox=False

Guard opts into the new behaviour explicitly:

    classes={0} (person) · select="per_class" · apply_nms=True · letterbox=True

Why the legacy defaults are not simply "the new way for everyone":

  * `select="per_class"` can find detections that `argmax` misses (an anchor
    whose top class is `boat` but which also scores `person` above threshold, or
    vice-versa). For the boat path that could raise `confidence` or flip
    `occupied` False→True in edge cases — a real behaviour change on a live
    marina install, so it stays opt-in until the boat path is re-validated.
  * `letterbox=True` changes the geometry fed to the network, so it changes
    detections. Better for accuracy (no aspect distortion), but again a change.
  * NMS provably CANNOT change `occupied` or `confidence` — it only drops
    lower-confidence overlapping duplicates, and the max-confidence box always
    survives. It is left off by default anyway so that `detections` list length
    is also unchanged for the existing caller.

The decode/NMS helpers are deliberately pure functions over numpy arrays with no
OpenVINO dependency, so they are unit-testable on the 32-bit dev box where the
openvino wheel cannot be installed.
"""
import io
import logging
import os
import time
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

# COCO-80 class ids. The stock Ultralytics `yolov8n.pt` checkpoint is trained on
# COCO and was never fine-tuned in this repo (see backend/setup_openvino_models.py),
# so these indices are the standard ones.
COCO_PERSON_CLASS_ID = 0
COCO_BOAT_CLASS_ID = 8

# Legacy alias — kept so any external import of the old private name still works.
_BOAT_CLASS_ID = COCO_BOAT_CLASS_ID

_DEFAULT_INPUT_SIZE = 640
_DEFAULT_IOU_THRESHOLD = 0.45

# Fallback names, used ONLY if the IR ships no metadata.yaml. The authoritative
# source is the model's own metadata — see `load_class_names()`.
_COCO80_FALLBACK_NAMES: tuple[str, ...] = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck",
    "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench",
    "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup",
    "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
)


def load_class_names(model_dir: str) -> dict[int, str]:
    """Read the class map from the IR's `metadata.yaml`, which Ultralytics writes
    on export. Falls back to the COCO-80 table if the file is absent/unparseable.

    Parsed with a tiny line scanner rather than PyYAML so this works without an
    extra dependency. Ultralytics writes the names block as either
    `names: {0: person, 1: bicycle, ...}` (flow) or an indented block map.
    """
    path = os.path.join(model_dir, "metadata.yaml")
    names: dict[int, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return {i: n for i, n in enumerate(_COCO80_FALLBACK_NAMES)}

    # Flow style: names: {0: person, 1: bicycle, ...}
    start = text.find("names:")
    if start != -1:
        brace_open = text.find("{", start)
        brace_close = text.find("}", brace_open) if brace_open != -1 else -1
        if brace_open != -1 and brace_close != -1:
            body = text[brace_open + 1:brace_close]
            for part in body.split(","):
                if ":" not in part:
                    continue
                k, _, v = part.partition(":")
                try:
                    names[int(k.strip())] = v.strip().strip("'\"")
                except ValueError:
                    continue
        else:
            # Block style: indented "  0: person" lines after "names:"
            for line in text[start:].splitlines()[1:]:
                if line.strip() and not line[:1].isspace():
                    break   # dedented → end of the names block
                if ":" not in line:
                    continue
                k, _, v = line.strip().partition(":")
                try:
                    names[int(k.strip())] = v.strip().strip("'\"")
                except ValueError:
                    continue

    if not names:
        return {i: n for i, n in enumerate(_COCO80_FALLBACK_NAMES)}
    return names


# ─── Pure post-processing (no OpenVINO needed — unit-testable anywhere) ───────

def iou_xyxy(a: Sequence[float], b: Sequence[float]) -> float:
    """Intersection-over-union of two [x1, y1, x2, y2] boxes."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return float(inter / union) if union > 0 else 0.0


def non_max_suppression(
    detections: list[dict],
    iou_threshold: float = _DEFAULT_IOU_THRESHOLD,
) -> list[dict]:
    """Greedy per-class NMS over detections carrying `bbox_xyxy` + `confidence`.

    Class-aware: a person overlapping a boat never suppresses it. Returns a new
    list, highest confidence first. Note this can only REMOVE entries, and never
    the highest-confidence one — so `max(confidence)` is invariant under NMS.
    """
    if len(detections) < 2:
        return list(detections)

    kept: list[dict] = []
    by_class: dict[int, list[dict]] = {}
    for det in detections:
        by_class.setdefault(int(det["class_id"]), []).append(det)

    for _cls, group in by_class.items():
        group = sorted(group, key=lambda d: float(d["confidence"]), reverse=True)
        while group:
            best = group.pop(0)
            kept.append(best)
            group = [
                d for d in group
                if iou_xyxy(best["bbox_xyxy"], d["bbox_xyxy"]) < iou_threshold
            ]

    kept.sort(key=lambda d: float(d["confidence"]), reverse=True)
    return kept


def _normalise_raw(raw, layout: str = "auto"):
    """Return the [anchors, 4+num_classes] prediction matrix from a YOLOv8 output.

    YOLOv8 emits [1, 4+nc, anchors] (e.g. [1, 84, 8400]); some exports emit it
    already transposed to [1, anchors, 4+nc].

    `layout="auto"` infers the orientation by assuming anchors > channels, which
    holds for every real export (8400 anchors vs 84 channels) and matches the
    pre-v3.41 `shape[1] == 84` check. It is genuinely ambiguous for a tensor with
    fewer anchors than channels, so pass `layout="channels_first"` or
    `"anchors_first"` explicitly when constructing small tensors by hand.
    """
    if raw.ndim != 3:
        return None
    arr = raw
    if layout == "auto":
        transpose = arr.shape[1] < arr.shape[2]
    elif layout == "channels_first":
        transpose = True
    elif layout == "anchors_first":
        transpose = False
    else:
        raise ValueError(
            f"unknown layout {layout!r} (use 'auto', 'channels_first' or 'anchors_first')"
        )
    if transpose:
        arr = arr.transpose(0, 2, 1)
    return arr[0]


def decode_output(
    raw,
    *,
    classes: Iterable[int] | None = None,
    default_conf: float = 0.3,
    class_thresholds: dict[int, float] | None = None,
    select: str = "argmax",
    input_size: int = _DEFAULT_INPUT_SIZE,
    letterbox_meta: dict | None = None,
    class_names: dict[int, str] | None = None,
    layout: str = "auto",
) -> list[dict]:
    """Decode a raw YOLOv8 output tensor into detection dicts.

    Args:
        raw: model output, [1, 4+nc, anchors] or [1, anchors, 4+nc].
        classes: class ids to keep. None → keep every class.
        default_conf: threshold for classes absent from `class_thresholds`.
        class_thresholds: per-class confidence thresholds, e.g. {0: 0.5, 8: 0.3}.
        select: "argmax"  → one candidate per anchor (its top-scoring class).
                             Legacy behaviour; what the berth path uses.
                "per_class" → every (anchor, wanted class) pair above threshold.
                             Needed for reliable multi-class detection.
        input_size: network input edge in pixels (square).
        letterbox_meta: {"scale", "pad_x", "pad_y", "orig_w", "orig_h"} when the
            frame was letterboxed, so boxes map back to the ORIGINAL image.
            None → boxes are normalised by `input_size` (legacy).
        class_names: id → name, for a human-readable `class_name` field.

    Returns:
        List of {class_id, class_name, confidence, bbox, bbox_xyxy}, where
        `bbox` is the legacy normalised {x_c, y_c, w, h} and `bbox_xyxy` is
        normalised [x1, y1, x2, y2]. Both are relative to the image fed in
        (i.e. to the crop, when a crop was passed).
    """
    import numpy as np  # lazy — keeps module import cheap and 32-bit safe

    if select not in ("argmax", "per_class"):
        raise ValueError(f"unknown select mode {select!r} (use 'argmax' or 'per_class')")

    rows = _normalise_raw(raw, layout)
    # Degenerate shapes (no anchors, or no class columns) must yield no detections
    # rather than raising out of argmax — a truncated/odd export must not take the
    # caller down.
    if rows is None or rows.shape[0] == 0 or rows.shape[1] <= 4:
        return []

    wanted: set[int] | None = set(int(c) for c in classes) if classes is not None else None
    thresholds = dict(class_thresholds or {})

    boxes = rows[:, :4]
    scores = rows[:, 4:]

    if select == "argmax":
        # One candidate per anchor: its single best class. np.argmax ties resolve
        # to the lowest index, matching the previous per-row Python loop exactly.
        cls_ids = np.argmax(scores, axis=1)
        confs = scores[np.arange(scores.shape[0]), cls_ids]
        pairs = zip(cls_ids.tolist(), confs.tolist(), range(rows.shape[0]))
    elif select == "per_class":
        # Every (anchor, wanted class) pair. Restrict columns first so we never
        # materialise an 8400 × 80 boolean mask when one class is wanted.
        col_ids = sorted(wanted) if wanted is not None else list(range(scores.shape[1]))
        col_ids = [c for c in col_ids if 0 <= c < scores.shape[1]]
        if not col_ids:
            return []
        sub = scores[:, col_ids]
        # Per-column threshold vector so one comparison covers all wanted classes.
        thr_vec = np.array(
            [thresholds.get(c, default_conf) for c in col_ids], dtype=sub.dtype,
        )
        anchor_idx, col_idx = np.nonzero(sub >= thr_vec)
        pairs = (
            (col_ids[c], float(sub[a, c]), int(a))
            for a, c in zip(anchor_idx.tolist(), col_idx.tolist())
        )
    else:   # pragma: no cover — validated at function entry
        raise ValueError(f"unknown select mode {select!r}")

    names = class_names or {}
    out: list[dict] = []

    for class_id, confidence, row_i in pairs:
        class_id = int(class_id)
        if wanted is not None and class_id not in wanted:
            continue
        if confidence < thresholds.get(class_id, default_conf):
            continue

        box = boxes[row_i]

        if letterbox_meta:
            x_c, y_c, w, h = (float(v) for v in box)
            scale = letterbox_meta["scale"]
            ow, oh = letterbox_meta["orig_w"], letterbox_meta["orig_h"]
            # Undo padding, then scaling, then normalise by the original size.
            x_c_n = ((x_c - letterbox_meta["pad_x"]) / scale) / ow
            y_c_n = ((y_c - letterbox_meta["pad_y"]) / scale) / oh
            w_n = (w / scale) / ow
            h_n = (h / scale) / oh
        else:
            # Divide in the tensor's own dtype and widen afterwards — i.e.
            # `float(x_c / 640)` on an np.float32 scalar, which is exactly what the
            # pre-v3.41 loop did. Widening to float64 first would change the last
            # ~3e-9 of every coordinate and break bit-for-bit equivalence with the
            # berth-occupancy behaviour (TC-YMC-01 fuzzes this).
            x_c_n, y_c_n = float(box[0] / input_size), float(box[1] / input_size)
            w_n, h_n = float(box[2] / input_size), float(box[3] / input_size)

        out.append({
            "class_id": class_id,
            "class_name": names.get(class_id, str(class_id)),
            "confidence": float(confidence),
            # Legacy key + shape, unchanged.
            "bbox": {"x_c": x_c_n, "y_c": y_c_n, "w": w_n, "h": h_n},
            "bbox_xyxy": [
                x_c_n - w_n / 2.0, y_c_n - h_n / 2.0,
                x_c_n + w_n / 2.0, y_c_n + h_n / 2.0,
            ],
        })

    return out


def letterbox_image(img, input_size: int = _DEFAULT_INPUT_SIZE):
    """Resize preserving aspect ratio, pad to square with grey (114,114,114).

    Returns (padded_image, meta) where meta feeds `decode_output`.
    Ultralytics letterboxes at inference time; the pre-v3.41 code used a plain
    distorting `resize((640, 640))`, which costs accuracy on non-square crops.
    """
    from PIL import Image

    ow, oh = img.size
    scale = min(input_size / ow, input_size / oh)
    nw, nh = max(1, int(round(ow * scale))), max(1, int(round(oh * scale)))
    resized = img.resize((nw, nh))
    canvas = Image.new("RGB", (input_size, input_size), (114, 114, 114))
    pad_x, pad_y = (input_size - nw) // 2, (input_size - nh) // 2
    canvas.paste(resized, (pad_x, pad_y))
    return canvas, {
        "scale": scale, "pad_x": float(pad_x), "pad_y": float(pad_y),
        "orig_w": float(ow), "orig_h": float(oh),
    }


# ─── Detector ────────────────────────────────────────────────────────────────

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
        self.class_names: dict[int, str] = {}
        self.model_path: str | None = None
        self.last_inference_ms: float | None = None

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
            self.class_names = load_class_names(model_path)
            self.model_path = xml_file
            self.available = True
            logger.info(
                "YoloOVDetector: loaded %s (%d classes; class 0=%r, class 8=%r)",
                xml_file, len(self.class_names),
                self.class_names.get(0), self.class_names.get(8),
            )
        except ImportError:
            logger.debug("YoloOVDetector: openvino not available — inference disabled")
        except Exception as exc:
            logger.warning("YoloOVDetector: failed to load model: %s", exc)

    def unload(self) -> None:
        """Release the compiled model so its memory can be reclaimed.

        Guard must hold no model while disarmed (Stage B), so it needs an
        explicit teardown. Safe to call when never loaded or already unloaded.
        """
        self._compiled_model = None
        self._input_layer = None
        self._output_layer = None
        self.available = False
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        logger.info("YoloOVDetector: model unloaded (%s)", self.model_path or "no model")

    def detect(
        self,
        frame_bytes: bytes,
        conf_threshold: float = 0.3,
        *,
        classes: Iterable[int] | None = None,
        class_thresholds: dict[int, float] | None = None,
        select: str = "argmax",
        apply_nms: bool = False,
        iou_threshold: float = _DEFAULT_IOU_THRESHOLD,
        letterbox: bool = False,
    ) -> dict:
        """
        Run YOLOv8n detection on a JPEG frame.

        Defaults reproduce the pre-v3.41 berth-occupancy behaviour exactly:
        boat class only, argmax selection, no NMS, distorting 640×640 resize.

        Returns:
            {
                "occupied": bool | None,      # None → inference unavailable
                "confidence": float,          # max confidence over detections
                "detections": list[dict],
                "inference_ms": float | None,
            }
        """
        if not self.available:
            return {"occupied": None, "confidence": 0.0, "detections": [], "inference_ms": None}

        if classes is None:
            classes = {COCO_BOAT_CLASS_ID}

        try:
            import numpy as np  # lazy import
            from PIL import Image  # lazy import

            img = Image.open(io.BytesIO(frame_bytes)).convert("RGB")

            if letterbox:
                prepared, meta = letterbox_image(img, _DEFAULT_INPUT_SIZE)
            else:
                # Legacy path: plain resize, aspect ratio distorted.
                prepared, meta = img.resize((_DEFAULT_INPUT_SIZE, _DEFAULT_INPUT_SIZE)), None

            arr = np.array(prepared, dtype=np.float32) / 255.0   # HWC
            inp = arr.transpose(2, 0, 1)[np.newaxis, ...]        # NCHW

            t0 = time.perf_counter()
            result = self._compiled_model([inp])[self._output_layer]
            inference_ms = (time.perf_counter() - t0) * 1000
            self.last_inference_ms = inference_ms
            logger.info("YoloOVDetector: inference_ms=%.1f", inference_ms)

            detections = decode_output(
                result,
                classes=classes,
                default_conf=conf_threshold,
                class_thresholds=class_thresholds,
                select=select,
                input_size=_DEFAULT_INPUT_SIZE,
                letterbox_meta=meta,
                class_names=self.class_names,
            )

            if apply_nms:
                detections = non_max_suppression(detections, iou_threshold)

            if detections:
                max_conf = max(d["confidence"] for d in detections)
                return {
                    "occupied": True, "confidence": max_conf,
                    "detections": detections, "inference_ms": inference_ms,
                }
            return {
                "occupied": False, "confidence": 0.0,
                "detections": [], "inference_ms": inference_ms,
            }

        except Exception as exc:
            logger.warning("YoloOVDetector.detect() error: %s", exc)
            return {"occupied": None, "confidence": 0.0, "detections": [], "inference_ms": None}

    def detect_persons(
        self,
        frame_bytes: bytes,
        conf_threshold: float = 0.5,
        *,
        iou_threshold: float = _DEFAULT_IOU_THRESHOLD,
    ) -> dict:
        """Person-only detection with the accuracy-oriented settings Guard uses:
        per-class selection, NMS on, letterboxed input. Thin wrapper over
        `detect()` so Guard never has to remember the flag combination."""
        return self.detect(
            frame_bytes,
            conf_threshold=conf_threshold,
            classes={COCO_PERSON_CLASS_ID},
            select="per_class",
            apply_nms=True,
            iou_threshold=iou_threshold,
            letterbox=True,
        )
