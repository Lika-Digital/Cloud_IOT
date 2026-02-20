"""Camera service — YOLOv8 ship detection on video, MJPEG proxy for real cameras."""
import logging
import math
import random
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)

# Path to the synthetic demo video (in frontend/public)
VIDEO_PATH = Path(__file__).parent.parent.parent.parent / "frontend" / "public" / "Video.mp4"

# In-memory cache: pedestal_id → list of frame detection dicts
_detection_cache: dict[int, list[dict]] = {}


# ─── YOLO detection on video ──────────────────────────────────────────────────

def get_video_detections(pedestal_id: int) -> list[dict]:
    """
    Return per-second ship detections for the demo video.
    Results are cached in memory — video is only processed once.

    Each entry: {time_s: float, detections: [{label, confidence, x1, y1, x2, y2}]}
    """
    if pedestal_id in _detection_cache:
        return _detection_cache[pedestal_id]

    detections = _run_yolo_on_video()
    _detection_cache[pedestal_id] = detections
    return detections


def _run_yolo_on_video() -> list[dict]:
    """Try YOLO; fall back to mock detections if ultralytics/opencv not available."""
    if not VIDEO_PATH.exists():
        logger.warning(f"Video file not found at {VIDEO_PATH}, using mock detections")
        return _mock_detections(duration_s=30)

    try:
        import cv2
        from ultralytics import YOLO

        model = YOLO("yolov8n.pt")
        cap = cv2.VideoCapture(str(VIDEO_PATH))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration_s = total_frames / fps

        results_list = []
        sample_every = int(fps)  # one sample per second

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % sample_every == 0:
                time_s = frame_idx / fps
                # Run YOLO — class 8 = boat in COCO
                results = model(frame, classes=[8], verbose=False)
                boxes = []
                for r in results:
                    for box in r.boxes:
                        x1, y1, x2, y2 = box.xyxy[0].tolist()
                        conf = float(box.conf[0])
                        boxes.append({
                            "label": "boat",
                            "confidence": round(conf, 3),
                            "x1": int(x1), "y1": int(y1),
                            "x2": int(x2), "y2": int(y2),
                        })
                results_list.append({"time_s": round(time_s, 2), "detections": boxes})

            frame_idx += 1

        cap.release()
        logger.info(f"YOLO processed {frame_idx} frames, {len(results_list)} samples")
        return results_list

    except ImportError:
        logger.info("ultralytics/opencv not available — using mock ship detections")
        return _mock_detections()
    except Exception as e:
        logger.warning(f"YOLO processing failed: {e} — using mock detections")
        return _mock_detections()


def _mock_detections(duration_s: int = 60) -> list[dict]:
    """
    Generate plausible ship detection data without running YOLO.
    Ship moves slowly from right to left across the frame, with slight drift.
    Assumes ~1280×720 video.
    """
    W, H = 1280, 720
    ship_w, ship_h = 260, 90
    random.seed(42)
    frames = []

    for t in range(0, duration_s + 1):
        # Ship X: start off right edge, move left slowly
        x1 = int(W - 80 - (t / duration_s) * (W * 0.7))
        # Ship Y: gentle wave
        y1 = int(H * 0.45 + 40 * math.sin(t * 0.25))
        x2 = x1 + ship_w
        y2 = y1 + ship_h

        # Ship disappears occasionally (simulates obstruction)
        if (t // 8) % 5 == 0:
            frames.append({"time_s": float(t), "detections": []})
        else:
            conf = round(random.uniform(0.72, 0.94), 3)
            frames.append({
                "time_s": float(t),
                "detections": [{"label": "boat", "confidence": conf,
                                 "x1": x1, "y1": y1, "x2": x2, "y2": y2}],
            })

    return frames


# ─── MJPEG proxy for real IP camera ─────────────────────────────────────────

def stream_ip_camera(camera_ip: str) -> Generator[bytes, None, None]:
    """
    Proxy an IP camera MJPEG stream.
    Expects camera to expose its stream at http://{camera_ip}/video or /mjpeg.
    """
    try:
        import requests

        urls_to_try = [
            f"http://{camera_ip}/video",
            f"http://{camera_ip}/mjpeg",
            f"http://{camera_ip}:8080/video",
        ]

        for url in urls_to_try:
            try:
                response = requests.get(url, stream=True, timeout=5)
                if response.status_code == 200:
                    logger.info(f"Proxying camera stream from {url}")
                    for chunk in response.iter_content(chunk_size=4096):
                        yield chunk
                    return
            except Exception:
                continue

        logger.warning(f"Could not reach camera at {camera_ip}")
        yield b""

    except ImportError:
        logger.error("requests library not available for camera proxy")
        yield b""
