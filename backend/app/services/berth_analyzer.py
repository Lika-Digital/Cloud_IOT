"""
Berth occupancy analyzer — lightweight, on-demand, no ML worker required.

Analysis flow:
  1. Grab a single snapshot from the pedestal's live RTSP stream via ffmpeg.
  2. Detect ship presence by measuring edge density (Laplacian variance) in the
     centre 60 % of the image.  High variance → ship present; low → berth empty.
  3. If reference images are configured for the berth, compare the snapshot with
     each reference using a normalised colour-histogram cosine similarity score.
     Max score across all references → match_score.
  4. Classify:
       occupied_bit=0                        → FREE          (state_code 0)
       occupied_bit=1, no refs               → OCCUPIED      (state_code 1, no alarm)
       occupied_bit=1, score ≥ threshold     → CORRECT SHIP  (state_code 1, no alarm)
       occupied_bit=1, score < threshold     → WRONG SHIP    (state_code 2, alarm=1)

State codes:
  0 = FREE
  1 = OCCUPIED_CORRECT  (or occupied with no reference configured)
  2 = OCCUPIED_WRONG    (vessel detected, does not match reference) → alarm = 1

Reference images are stored under:
  backgrounds/berth_{id}/   (relative to the backend/ directory)
"""
import asyncio
import io
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Base directory for per-berth reference images  (backend/backgrounds/berth_{id}/)
REFS_BASE = Path(__file__).parent.parent.parent / "backgrounds"


# ─── Reference-image helpers ──────────────────────────────────────────────────

def _refs_dir(berth_id: int) -> Path:
    d = REFS_BASE / f"berth_{berth_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_reference_images(berth_id: int) -> list[str]:
    """Return sorted list of reference image filenames for this berth."""
    d = _refs_dir(berth_id)
    return sorted(
        p.name for p in d.iterdir()
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )


def delete_reference_image(berth_id: int, filename: str) -> bool:
    """Delete one reference image.  Returns True if deleted, False if not found."""
    # Refuse path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return False
    p = _refs_dir(berth_id) / filename
    if p.exists() and p.is_file():
        p.unlink()
        return True
    return False


def save_reference_image(berth_id: int, filename: str, data: bytes) -> str:
    """Persist an uploaded reference image.  Returns the sanitised filename."""
    stem = re.sub(r"[^a-zA-Z0-9_\-]", "_", Path(filename).stem)
    suffix = Path(filename).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    safe_name = f"{stem}_{int(time.time())}{suffix}"
    (_refs_dir(berth_id) / safe_name).write_bytes(data)
    return safe_name


# ─── RTSP snapshot via ffmpeg ─────────────────────────────────────────────────

async def grab_snapshot(stream_url: str, username: str = "", password: str = "") -> bytes:
    """
    Grab a single JPEG frame from an RTSP or HTTP stream using ffmpeg.
    Returns raw JPEG bytes.  Raises RuntimeError on failure.
    """
    url = stream_url
    if username and password and "://" in url:
        scheme, rest = url.split("://", 1)
        # Inject credentials only if not already present
        if "@" not in rest.split("/")[0]:
            url = f"{scheme}://{username}:{password}@{rest}"

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-rtsp_transport", "tcp",
        "-i", url,
        "-vframes", "1",
        "-q:v", "2",
        "-f", "image2",
        "-vcodec", "mjpeg",
        "pipe:1",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError("ffmpeg snapshot timed out after 15 s")

    if not stdout:
        raise RuntimeError(
            "ffmpeg returned empty output — check stream URL and credentials"
        )
    return stdout


# ─── Ship detection (Laplacian edge-density) ─────────────────────────────────

def _open_rgb(data: bytes):
    """Open image bytes as an RGB Pillow Image."""
    from PIL import Image  # lazy import — Pillow not needed at module load time
    return Image.open(io.BytesIO(data)).convert("RGB")


def _center_crop(img, frac: float = 0.6):
    w, h = img.size
    mx = int(w * (1 - frac) / 2)
    my = int(h * (1 - frac) / 2)
    return img.crop((mx, my, w - mx, h - my))


def detect_ship(img_data: bytes, threshold: float = 300.0) -> bool:
    """
    Return True if ship-like content is present in the centre of the image.

    Method: Laplacian variance of the greyscale centre crop.
    Ships have dense edges (hull, rigging, superstructure); open water/sky is
    nearly featureless and produces low variance.

    `threshold` is tunable per berth via `detect_conf_threshold` in the DB
    (default 300; increase to reduce false positives in choppy water).
    """
    import numpy as np  # lazy import

    img = _open_rgb(img_data)
    center = _center_crop(img, 0.6)
    gray = np.array(center.convert("L"), dtype=np.float32)

    # Discrete Laplacian via array slicing (no scipy needed)
    lap = (
        gray[:-2, 1:-1] + gray[2:, 1:-1]
        + gray[1:-1, :-2] + gray[1:-1, 2:]
        - 4 * gray[1:-1, 1:-1]
    )
    variance = float(np.var(lap))
    logger.debug("Ship detection — Laplacian variance: %.1f (threshold=%.1f)", variance, threshold)
    return variance > threshold


# ─── Ship matching (histogram cosine similarity) ──────────────────────────────

def _histogram_vector(img, bins: int = 64):
    """
    Normalised colour histogram over a 128×128 resize.
    Returns a 1-D numpy array of shape (3*bins,) with unit L2 norm.
    """
    import numpy as np

    arr = np.array(img.resize((128, 128)), dtype=np.float32)
    hists = [
        np.histogram(arr[:, :, c], bins=bins, range=(0, 256))[0].astype(np.float32)
        for c in range(3)
    ]
    vec = np.concatenate(hists)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def compute_match_score(snapshot_data: bytes, berth_id: int) -> float | None:
    """
    Compare snapshot against all reference images for the berth.
    Returns the maximum cosine similarity (0 – 1), or None if no references.
    """
    import numpy as np
    from PIL import Image

    refs = list_reference_images(berth_id)
    if not refs:
        return None

    snap_img = _center_crop(_open_rgb(snapshot_data), 0.8)
    snap_vec = _histogram_vector(snap_img)

    scores = []
    for fname in refs:
        try:
            ref_path = _refs_dir(berth_id) / fname
            ref_img = _center_crop(Image.open(ref_path).convert("RGB"), 0.8)
            ref_vec = _histogram_vector(ref_img)
            scores.append(float(np.dot(snap_vec, ref_vec)))
        except Exception as exc:
            logger.warning("Could not load reference image %s: %s", fname, exc)

    return max(scores) if scores else None


# ─── On-demand analysis entry point ──────────────────────────────────────────

async def analyze_berth_now(
    berth_id: int,
    stream_url: str,
    camera_username: str = "",
    camera_password: str = "",
    detect_threshold: float = 300.0,
    match_threshold: float = 0.75,
) -> dict:
    """
    On-demand berth analysis:
      1. Grab snapshot from the live RTSP stream.
      2. Detect ship presence via edge-density.
      3. Compare against reference images (if any) via histogram similarity.
      4. Return a result dict with: occupied_bit, match_ok_bit, state_code,
         alarm, match_score, error.
    """
    # Thermal protection: skip RTSP grab while CPU temperature suspension is active
    try:
        from .hardware_monitor import is_rtsp_suspended
        if is_rtsp_suspended():
            return {
                "occupied_bit": 0, "match_ok_bit": 0,
                "state_code": 0, "alarm": 0, "match_score": None,
                "error": "RTSP grab suspended (thermal protection active)",
            }
    except ImportError:
        pass

    try:
        snapshot = await grab_snapshot(stream_url, camera_username, camera_password)
    except Exception as exc:
        logger.warning("Berth %d snapshot failed: %s", berth_id, exc)
        return {
            "occupied_bit": 0, "match_ok_bit": 0,
            "state_code": 0, "alarm": 0, "match_score": None,
            "error": f"Snapshot failed: {exc}",
        }

    occupied = detect_ship(snapshot, threshold=detect_threshold)

    if not occupied:
        return {
            "occupied_bit": 0, "match_ok_bit": 0,
            "state_code": 0, "alarm": 0, "match_score": None, "error": None,
        }

    # Ship detected — compare with reference images
    score = compute_match_score(snapshot, berth_id)

    if score is None:
        # No reference images configured — occupied, no match classification
        return {
            "occupied_bit": 1, "match_ok_bit": 0,
            "state_code": 1, "alarm": 0, "match_score": None, "error": None,
        }

    match_ok = score >= match_threshold
    return {
        "occupied_bit": 1,
        "match_ok_bit": 1 if match_ok else 0,
        "state_code": 1 if match_ok else 2,
        "alarm": 0 if match_ok else 1,
        "match_score": round(score, 4),
        "error": None,
    }


# ─── Background task (no-op — analysis is now on-demand only) ─────────────────

async def run_berth_analysis():
    """
    Retained for compatibility with main.py.
    Continuous background analysis has been replaced by on-demand analysis
    triggered from the admin UI per berth.
    """
    logger.info("Berth analysis: on-demand mode — continuous background loop is disabled")
    while True:
        await asyncio.sleep(3600)   # idle; wakes up hourly but does nothing
