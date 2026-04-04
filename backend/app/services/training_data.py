"""
Training Data Pipeline — save annotated crop images for future model training.

Directory layout:
    training_data/
        occupied/
            confirmed/
            rejected/
        empty/
            confirmed/
            rejected/
        match_samples/

Each saved crop has a companion .json metadata file with the same stem.
"""
import json
import logging
import os
import shutil
import sys
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── Base directory ────────────────────────────────────────────────────────────

if sys.platform == "win32":
    # Dev machine: place alongside backend/
    _BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    TRAINING_DATA_DIR: str = os.environ.get(
        "TRAINING_DATA_DIR",
        os.path.join(_BACKEND_DIR, "training_data"),
    )
else:
    TRAINING_DATA_DIR = os.environ.get(
        "TRAINING_DATA_DIR",
        "/opt/cloud-iot/backend/training_data",
    )

# Maximum training-data storage in GB (also readable by storage_monitor)
TRAINING_DATA_MAX_GB: float = float(os.environ.get("TRAINING_DATA_MAX_GB", "10"))

_SUBDIRS = [
    "occupied/confirmed",
    "occupied/rejected",
    "empty/confirmed",
    "empty/rejected",
    "match_samples",
]


def _ensure_dirs():
    for sub in _SUBDIRS:
        os.makedirs(os.path.join(TRAINING_DATA_DIR, sub), exist_ok=True)


def _subdir_for(result: str) -> str:
    """Return the base subdirectory path for a given result label."""
    if result == "occupied":
        return os.path.join(TRAINING_DATA_DIR, "occupied")
    elif result == "empty":
        return os.path.join(TRAINING_DATA_DIR, "empty")
    elif result == "match":
        return os.path.join(TRAINING_DATA_DIR, "match_samples")
    else:
        # Fallback — store in occupied/
        logger.warning("training_data: unknown result '%s', using 'occupied'", result)
        return os.path.join(TRAINING_DATA_DIR, "occupied")


def save_crop(
    berth_id: int,
    camera_id: str,
    crop_bytes: bytes,
    result: str,
    confidence: float,
    rect: dict,
) -> tuple[str, str]:
    """
    Persist a crop image and companion JSON metadata.

    Args:
        berth_id:   berth identifier
        camera_id:  camera/pedestal identifier string
        crop_bytes: JPEG image bytes of the cropped region
        result:     "occupied" | "empty" | "match"
        confidence: detection confidence score (0–1)
        rect:       bounding rect as fractions {x1, y1, x2, y2}

    Returns:
        (image_path, json_path) — absolute paths to the saved files.
    """
    _ensure_dirs()

    timestamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    stem = f"berth{berth_id:02d}_{camera_id}_{timestamp}"
    img_name  = f"{stem}.jpg"
    json_name = f"{stem}.json"

    base_dir = _subdir_for(result)
    # For occupied/empty, new crops land in the root of that category (no confirmed/rejected yet)
    # confirmed/ and rejected/ are populated by confirm_crop()
    img_path  = os.path.join(base_dir, img_name)
    json_path = os.path.join(base_dir, json_name)

    # Avoid overwriting — add a counter suffix if file already exists
    idx = 0
    while os.path.exists(img_path):
        idx += 1
        img_path  = os.path.join(base_dir, f"{stem}_{idx}.jpg")
        json_path = os.path.join(base_dir, f"{stem}_{idx}.json")

    try:
        with open(img_path, "wb") as fh:
            fh.write(crop_bytes)
    except Exception as exc:
        logger.error("training_data: failed to save image %s: %s", img_path, exc)
        raise

    meta = {
        "berth_id":  berth_id,
        "camera_id": camera_id,
        "timestamp": datetime.utcnow().isoformat(),
        "result":    result,
        "confidence": round(float(confidence), 4),
        "rect":      rect,
    }
    try:
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
    except Exception as exc:
        logger.warning("training_data: failed to save metadata %s: %s", json_path, exc)

    logger.debug("training_data: saved %s + %s", img_path, json_path)
    return img_path, json_path


def confirm_crop(image_path: str, confirmed: bool) -> str:
    """
    Move a crop image (and its .json sibling) to confirmed/ or rejected/ subfolder.

    Args:
        image_path: absolute path to the .jpg crop file
        confirmed:  True → confirmed/, False → rejected/

    Returns:
        The new absolute path of the moved image.
    """
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Crop image not found: {image_path}")

    parent_dir = os.path.dirname(image_path)
    target_subdir = "confirmed" if confirmed else "rejected"
    target_dir = os.path.join(parent_dir, target_subdir)
    os.makedirs(target_dir, exist_ok=True)

    filename = os.path.basename(image_path)
    new_img_path = os.path.join(target_dir, filename)

    # Avoid collisions
    if os.path.exists(new_img_path):
        stem, ext = os.path.splitext(filename)
        import time
        new_img_path = os.path.join(target_dir, f"{stem}_{int(time.time())}{ext}")

    shutil.move(image_path, new_img_path)
    logger.info("training_data: moved %s → %s", image_path, new_img_path)

    # Move companion JSON
    json_path = os.path.splitext(image_path)[0] + ".json"
    if os.path.isfile(json_path):
        new_json_path = os.path.splitext(new_img_path)[0] + ".json"
        try:
            shutil.move(json_path, new_json_path)
        except Exception as exc:
            logger.warning("training_data: could not move JSON %s: %s", json_path, exc)

    return new_img_path
