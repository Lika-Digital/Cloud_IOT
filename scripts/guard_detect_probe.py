#!/usr/bin/env python3
"""
guard_detect_probe.py — Guard Stage A.5 proof + benchmark. NUC-side, read-only.

Proves person detection works with the stock COCO YOLOv8n IR at the real camera
angle, and measures what it costs. Touches no application state: it loads the IR
directly, never imports the FastAPI app, and never writes to the databases.

Dependencies: openvino, numpy, Pillow (all already required), plus `ffmpeg` on
PATH for clip/record modes. No OpenCV, no ultralytics, no torch.

MODES
  --classmap
        Print the IR's real class map + tensor shapes. This is the on-disk proof
        that class 0 is `person` (Stage A §1.2 left it inferred from the export
        code).

  --record SECONDS
        Record a clip from the configured camera with `-c copy` (no re-encode,
        ~0 % CPU) so you have a real-angle sample to test against. Daylight only.

  --image PATH
        Run detection on one still image.

  --clip PATH
        Decode a clip at --fps and run detection on every sampled frame.

  --zone x1,y1,x2,y2
        Crop to this fraction of the frame before inference (default matches the
        berth default 0.2,0.2,0.8,0.8). Stage A found the crop is what gives
        usable range — a person at 20 m is ~79 px cropped vs ~47 px full-frame —
        so it is on by default. Pass --no-zone to measure the difference.

  --expect person|none
        Ground truth for the whole sample, enabling frame-level recall / false
        positive rate. NOTE: this is FRAME-level, not box-level — real precision
        needs per-frame box annotation, which this script does not invent.

SCOPE
  DAYLIGHT ONLY. Night operation is out of scope for Phase 1: this camera has no
  IR illuminator and the sensor is poor, so after dark it is recorded as
  unsupported on this hardware rather than measured and reported as a failure.

  The camera views the STERN at ~10 m, where boarding happens — not a distant
  berth. Geometry predicts ~150 px person height with the zone crop; the probe
  flags a median far below that as a setup problem, not a model problem.

EXAMPLES
    python3 scripts/guard_detect_probe.py --classmap
    python3 scripts/guard_detect_probe.py --record 30 --out /tmp/stern.mp4
    python3 scripts/guard_detect_probe.py --clip /tmp/stern.mp4 --expect person
    python3 scripts/guard_detect_probe.py --clip /tmp/empty.mp4 --expect none
    python3 scripts/guard_detect_probe.py --clip /tmp/stern.mp4 --no-zone  # compare
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

# Import the real detector so we benchmark exactly what production will run.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "backend"))

DEFAULT_MODEL_DIR = (
    "/opt/cloud-iot/backend/models"
    if os.path.isdir("/opt/cloud-iot/backend/models")
    else os.path.join(os.path.dirname(_HERE), "backend", "models")
)


# ─── helpers ─────────────────────────────────────────────────────────────────

def _fail(msg: str) -> "None":
    print(f"\n[FAIL] {msg}\n", file=sys.stderr)
    sys.exit(1)


def _require_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        _fail("ffmpeg not on PATH. `sudo apt install -y ffmpeg` "
              "(it is missing from the NUC installer — see the Stage A assessment).")


def camera_url_from_db() -> str | None:
    """Read the configured RTSP URL straight out of pedestal.db (read-only)."""
    import sqlite3
    for db_path in ("/opt/cloud-iot/backend/pedestal.db",
                    os.path.join(os.path.dirname(_HERE), "backend", "pedestal.db")):
        if not os.path.exists(db_path):
            continue
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            row = con.execute(
                "SELECT camera_stream_url, camera_username, camera_password "
                "FROM pedestal_configs WHERE camera_stream_url IS NOT NULL "
                "AND camera_stream_url != '' LIMIT 1"
            ).fetchone()
            con.close()
        except Exception as exc:
            print(f"[warn] could not read {db_path}: {exc}")
            continue
        if not row:
            continue
        url, user, pw = row[0], row[1] or "", row[2] or ""
        if user and pw and "://" in url and "@" not in url.split("://", 1)[1].split("/")[0]:
            scheme, rest = url.split("://", 1)
            url = f"{scheme}://{user}:{pw}@{rest}"
        return url
    return None


def _redact(url: str) -> str:
    """Hide the password so the report can be pasted into a chat safely."""
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest.split("/")[0] and ":" in rest.split("@")[0]:
        user = rest.split(":", 1)[0]
        host = rest.split("@", 1)[1]
        return f"{scheme}://{user}:***@{host}"
    return url


# ─── the alarm rule now lives in the backend, shared with the worker ─────────
#
# Promoted to app/guard/alarm_rule.py in step 2. The probe imports it rather than
# carrying its own copy, so replaying a clip and running live use provably the same
# decision code — the "probe and worker share ONE code path" requirement applied to the
# alarm decision as well as to detection. Re-exported here so existing callers and tests
# keep working.
from app.guard.alarm_rule import evaluate_alarm_rule  # noqa: E402  (after sys.path setup)

def crop_jpeg(data: bytes, zone: tuple[float, float, float, float] | None) -> bytes:
    """Crop to a fractional zone. Mirrors berths.py:445-460 so the probe measures
    the same geometry production will feed the model."""
    if zone is None:
        return data
    import io
    from PIL import Image
    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    x1, y1, x2, y2 = zone
    box = (int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h))
    buf = io.BytesIO()
    img.crop(box).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


# ─── modes ───────────────────────────────────────────────────────────────────

def show_classmap(model_dir: str) -> int:
    """On-disk proof of the class map + IR tensor shapes."""
    from app.services.yolo_openvino import load_class_names

    ir_dir = os.path.join(model_dir, "yolov8n_openvino")
    print(f"IR directory : {ir_dir}")
    if not os.path.isdir(ir_dir):
        _fail(f"{ir_dir} not found — run scripts/guard_export_model.sh first.")

    xmls = glob.glob(os.path.join(ir_dir, "*.xml"))
    bins = glob.glob(os.path.join(ir_dir, "*.bin"))
    for p in sorted(xmls + bins):
        print(f"  {os.path.basename(p):28s} {os.path.getsize(p):>12,} bytes")

    names = load_class_names(ir_dir)
    src = "metadata.yaml" if os.path.exists(os.path.join(ir_dir, "metadata.yaml")) \
          else "COCO-80 FALLBACK (metadata.yaml absent!)"
    print(f"\nClass map source : {src}")
    print(f"Class count      : {len(names)}")
    print(f"  class 0 = {names.get(0)!r}")
    print(f"  class 8 = {names.get(8)!r}")

    ok = names.get(0) == "person" and names.get(8) == "boat"
    print("\nFull map:")
    for i in sorted(names):
        print(f"  {i:3d}: {names[i]}")

    try:
        import openvino as ov
        print(f"\nopenvino version : {ov.__version__}")
        model = ov.Core().read_model(xmls[0])
        print(f"input  {model.input(0).any_name}: {model.input(0).partial_shape}")
        print(f"output {model.output(0).any_name}: {model.output(0).partial_shape}")
    except ImportError:
        print("\n[warn] openvino not importable — install requirements-vision.txt")
    except Exception as exc:
        print(f"\n[warn] could not read IR shapes: {exc}")

    print("\nVERDICT:", "PASS — person class present" if ok else "FAIL — unexpected class map")
    return 0 if ok else 1


def record_clip(seconds: int, out_path: str, url: str | None) -> int:
    _require_ffmpeg()
    url = url or camera_url_from_db()
    if not url:
        _fail("no camera URL found in pedestal.db — pass --url rtsp://...")
    print(f"Recording {seconds}s from {_redact(url)} → {out_path}")
    print("Using -c copy (stream copy, no re-encode) so this costs ~0 % CPU.")
    t0 = time.time()
    proc = subprocess.run(
        ["ffmpeg", "-y", "-rtsp_transport", "tcp", "-i", url,
         "-t", str(seconds), "-c", "copy", "-an", out_path],
        capture_output=True, text=True, timeout=seconds + 60,
    )
    if proc.returncode != 0 or not os.path.exists(out_path):
        _fail(f"ffmpeg failed:\n{proc.stderr[-1500:]}")
    size = os.path.getsize(out_path)
    print(f"Wrote {size:,} bytes in {time.time() - t0:.1f}s "
          f"(~{size / max(1, seconds) / 1024:.0f} KB/s → "
          f"a 60 s alarm clip ≈ {size / max(1, seconds) * 60 / 1e6:.1f} MB)")
    return 0


def _frames_from_clip(clip: str, fps: float, tmpdir: str) -> list[str]:
    _require_ffmpeg()
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", clip,
         "-vf", f"fps={fps}", "-q:v", "2", os.path.join(tmpdir, "f_%05d.jpg")],
        capture_output=True, text=True, timeout=600,
    )
    frames = sorted(glob.glob(os.path.join(tmpdir, "f_*.jpg")))
    if not frames:
        _fail(f"no frames extracted from {clip}:\n{proc.stderr[-1000:]}")
    return frames


def run_detection(
    model_dir: str,
    frame_paths: list[str],
    zone: tuple[float, float, float, float] | None,
    conf: float,
    expect: str | None,
    save_annotated: str | None,
    *,
    fps: float = 2.0,
    num_threads: int | None = None,
    frames_required: int = 2,
    window_seconds: float = 3.0,
    cooldown_seconds: float = 60.0,
    person_enters_at: float | None = None,
) -> int:
    from app.services.yolo_openvino import YoloOVDetector

    det = YoloOVDetector(model_dir, num_threads=num_threads)
    if not det.available:
        _fail(f"detector unavailable for model_dir={model_dir}. Check that "
              "requirements-vision.txt is installed and the IR exists.")
    print(f"Model      : {det.model_path}")
    print(f"Classes    : {len(det.class_names)} (0={det.class_names.get(0)!r})")
    print(f"Zone crop  : {zone if zone else 'DISABLED (full frame)'}")
    print(f"Confidence : {conf}")
    print(f"Threads    : {num_threads if num_threads else 'openvino default (all cores)'}"
          f"{'  <- Guard production setting' if num_threads == 1 else ''}")
    print(f"Frames     : {len(frame_paths)}\n")

    latencies: list[float] = []
    hits = 0
    per_frame: list[dict] = []
    samples: list[tuple[float, bool]] = []
    person_px_heights: list[float] = []
    crop_dims: tuple[int, int] | None = None
    cpu_t0, wall_t0 = time.process_time(), time.perf_counter()

    for idx, path in enumerate(frame_paths):
        with open(path, "rb") as fh:
            raw = fh.read()
        crop = crop_jpeg(raw, zone)
        if crop_dims is None:
            import io as _io
            from PIL import Image as _Image
            crop_dims = _Image.open(_io.BytesIO(crop)).size
            print(f"  (crop fed to the model: {crop_dims[0]}x{crop_dims[1]} px)")
        res = det.detect_persons(crop, conf_threshold=conf)

        if res["occupied"] is None:
            _fail("inference returned None — model became unavailable mid-run")
        if res["inference_ms"] is not None:
            latencies.append(res["inference_ms"])
        found = bool(res["detections"])
        hits += int(found)
        t_frame = idx / fps if fps > 0 else float(idx)
        samples.append((t_frame, found))

        # Person pixel height in the ACTUAL crop — the distance-check number.
        # bbox_xyxy is normalised to the crop, so multiply by the crop height.
        px_h = 0.0
        if found and crop_dims:
            px_h = max(
                (d["bbox_xyxy"][3] - d["bbox_xyxy"][1]) * crop_dims[1]
                for d in res["detections"]
            )
            person_px_heights.append(px_h)

        per_frame.append({
            "frame": os.path.basename(path),
            "t_s": round(t_frame, 3),
            "persons": len(res["detections"]),
            "max_conf": round(res["confidence"], 4),
            "px_height": round(px_h, 1),
            "inference_ms": round(res["inference_ms"] or 0.0, 1),
            "boxes": [
                {"conf": round(d["confidence"], 3),
                 "xyxy": [round(v, 4) for v in d["bbox_xyxy"]]}
                for d in res["detections"]
            ],
        })
        mark = "PERSON" if found else "      "
        print(f"  [{idx + 1:4d}/{len(frame_paths)}] t={t_frame:6.1f}s {mark} "
              f"n={len(res['detections'])} conf={res['confidence']:.3f} "
              f"h={px_h:5.0f}px {res['inference_ms']:.0f} ms")

        if save_annotated and found:
            _annotate(crop, res["detections"], os.path.join(save_annotated, os.path.basename(path)))

    cpu_used = time.process_time() - cpu_t0
    wall = time.perf_counter() - wall_t0

    print("\n" + "=" * 68)
    print("RESULTS")
    print("=" * 68)
    n = len(frame_paths)
    print(f"Frames processed        : {n}")
    print(f"Frames with a person    : {hits}  ({100.0 * hits / n:.1f} %)")
    if latencies:
        lat = sorted(latencies)
        print(f"Inference ms  mean      : {statistics.fmean(lat):.1f}")
        print(f"              median    : {statistics.median(lat):.1f}")
        print(f"              min / max : {lat[0]:.1f} / {lat[-1]:.1f}")
        if len(lat) >= 20:
            print(f"              p95       : {lat[int(0.95 * len(lat)) - 1]:.1f}")
        print(f"Max sustainable fps     : {1000.0 / statistics.fmean(lat):.2f} "
              f"(one core, inference only)")
    # CPU cost per inference: process CPU time is the honest figure — it excludes
    # the ffmpeg decode that ran in a separate process before this loop.
    print(f"\nProcess CPU time        : {cpu_used:.2f} s over {wall:.2f} s wall")
    print(f"CPU per inference       : {1000.0 * cpu_used / n:.1f} ms CPU/frame")
    try:
        ncpu = os.cpu_count() or 1
        print(f"Implied load @1 fps     : {100.0 * cpu_used / n:.1f} % of one core "
              f"= {100.0 * cpu_used / n / ncpu:.1f} % of {ncpu} cores")
    except Exception:
        pass

    # ── B: distance check — measured, not estimated ──────────────────────────
    if person_px_heights:
        ph = sorted(person_px_heights)
        print(f"\nPERSON PIXEL HEIGHT (in the {crop_dims[0]}x{crop_dims[1]} crop)")
        print(f"  median                : {statistics.median(ph):.0f} px")
        print(f"  min / max             : {ph[0]:.0f} / {ph[-1]:.0f} px")
        print("  reference             : >=50 px reliable, 20-40 px marginal, "
              "<20 px effectively blind")
        med = statistics.median(ph)
        # This camera views the stern at ~10 m, where geometry predicts ~150 px
        # with the zone crop. A median far below that means the crop, the zoom or
        # the camera position is not what we think — a setup problem, not a model
        # problem, so say so rather than quietly reporting a low number.
        print("  expected here         : ~150 px (person at ~10 m, stern view, "
              "with the zone crop)")
        if med < 100:
            print(f"  [!] median {med:.0f} px is FAR below the ~150 px expected at 10 m.")
            print("      Suspect the crop/zone, camera framing or that the subject was")
            print("      much further than 10 m — verify before trusting these numbers.")
        elif med < 40:
            print("  [!] median below 40 px — at or past usable range")
    elif expect == "person":
        print("\nPERSON PIXEL HEIGHT     : no detections, so no height measured")

    # ── A: event-level metric — what the marina actually feels ───────────────
    duration_s = (n / fps) if fps > 0 else float(n)
    alarms = evaluate_alarm_rule(
        samples, frames_required=frames_required,
        window_seconds=window_seconds, cooldown_seconds=cooldown_seconds,
    )
    print(f"\nALARM RULE  (>= {frames_required} detections within {window_seconds:g} s "
          f"at {fps:g} fps, {cooldown_seconds:g} s cooldown)")
    print(f"  clip duration         : {duration_s:.1f} s")
    print(f"  alarms raised         : {len(alarms)}")
    for i, a in enumerate(alarms, 1):
        print(f"    #{i}: fired at t={a['t']:.1f}s "
              f"(first detection t={a['first_positive_t']:.1f}s, "
              f"rule latency {a['latency_s']:.1f}s, "
              f"{a['positives_in_window']} in window)")

    exit_code = 0
    if expect == "person":
        recall = hits / n
        print(f"\nGround truth            : person present in all {n} frames")
        print(f"Frame-level RECALL      : {recall:.3f}  ({hits}/{n})")
        print("Frame-level PRECISION   : not computable — needs per-frame box "
              "annotation, which this script does not fabricate.")

        # End-to-end latency needs to know when the person actually walked in.
        if alarms:
            if person_enters_at is not None:
                e2e = alarms[0]["t"] - person_enters_at
                print(f"\nEND-TO-END LATENCY      : {e2e:.1f} s "
                      f"(person entered t={person_enters_at:.1f}s → "
                      f"alarm t={alarms[0]['t']:.1f}s)")
                if e2e < 0:
                    print("  [!] negative — alarm fired BEFORE the stated entry time; "
                          "check --person-enters-at or suspect a false positive")
            else:
                print(f"\nRULE LATENCY            : {alarms[0]['latency_s']:.1f} s "
                      "(first detection → alarm)")
                print("  End-to-end latency needs --person-enters-at SECONDS "
                      "(when the person actually entered frame).")

        alarm_ok = len(alarms) == 1
        print(f"\nVERDICT: recall {'PASS' if recall >= 0.80 else 'REVIEW'} "
              f"(>=0.80 suggested) · alarms {'PASS' if alarm_ok else 'REVIEW'} "
              f"(expected exactly 1, got {len(alarms)})")
        if len(alarms) > 1:
            print("  [!] more than one alarm on a single-intrusion clip — the cooldown "
                  "is too short or the person left and re-entered the zone.")
        exit_code = 0 if (recall >= 0.80 and alarm_ok) else 2

    elif expect == "none":
        fpr = hits / n
        per_hour = len(alarms) * 3600.0 / duration_s if duration_s > 0 else 0.0
        print(f"\nGround truth            : NO person in any of {n} frames")
        print(f"Frame-level FP rate     : {fpr:.3f}  ({hits}/{n})")
        print(f"FALSE ALARMS            : {len(alarms)} in {duration_s:.1f} s")
        print(f"FALSE ALARMS PER HOUR   : {per_hour:.2f}   <-- the number that matters")
        if duration_s < 600:
            print(f"  [!] extrapolated from only {duration_s:.0f} s. One false alarm in a "
                  f"short clip reads as {per_hour:.1f}/h; record >=10 min for a "
                  "trustworthy rate.")
        ok = len(alarms) == 0 and fpr <= 0.05
        print(f"\nVERDICT: {'PASS' if ok else 'REVIEW'} "
              f"(expected 0 alarms and <=0.05 frame FP rate)")
        exit_code = 0 if ok else 2
    else:
        print("\n(no --expect given → no recall / false-alarm rate computed)")

    out_json = "/tmp/guard_probe_results.json"
    try:
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump({
                "model": det.model_path,
                "zone": zone, "conf": conf, "fps": fps, "frames": n,
                "crop_px": list(crop_dims) if crop_dims else None,
                "frames_with_person": hits,
                "duration_s": duration_s,
                "inference_ms_mean": statistics.fmean(latencies) if latencies else None,
                "cpu_ms_per_frame": 1000.0 * cpu_used / n,
                "person_px_height_median": (
                    statistics.median(person_px_heights) if person_px_heights else None
                ),
                "alarm_rule": {
                    "frames_required": frames_required,
                    "window_seconds": window_seconds,
                    "cooldown_seconds": cooldown_seconds,
                },
                "alarms": alarms,
                "per_frame": per_frame,
            }, fh, indent=2)
        print(f"\nDetail written to {out_json}")
    except OSError as exc:
        print(f"[warn] could not write {out_json}: {exc}")

    det.unload()
    return exit_code


def _annotate(jpeg: bytes, detections: list[dict], out_path: str) -> None:
    """Draw boxes so the detections can be eyeballed, not just trusted."""
    import io
    from PIL import Image, ImageDraw
    try:
        img = Image.open(io.BytesIO(jpeg)).convert("RGB")
        draw = ImageDraw.Draw(img)
        w, h = img.size
        for d in detections:
            x1, y1, x2, y2 = d["bbox_xyxy"]
            draw.rectangle([x1 * w, y1 * h, x2 * w, y2 * h], outline=(255, 0, 0), width=3)
            draw.text((x1 * w + 4, max(0, y1 * h - 12)),
                      f"{d['class_name']} {d['confidence']:.2f}", fill=(255, 0, 0))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        img.save(out_path, quality=90)
    except Exception as exc:
        print(f"[warn] annotate failed for {out_path}: {exc}")


# ─── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Guard Stage A.5 person-detection proof + benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__,
    )
    ap.add_argument("--classmap", action="store_true", help="print the IR class map and exit")
    ap.add_argument("--record", type=int, metavar="SECONDS", help="record a clip from the camera")
    ap.add_argument("--out", default="/tmp/guard_clip.mp4", help="output path for --record")
    ap.add_argument("--url", help="RTSP URL (default: read from pedestal.db)")
    ap.add_argument("--image", help="run detection on a single still image")
    ap.add_argument("--clip", help="run detection on a video clip")
    ap.add_argument("--fps", type=float, default=2.0, help="sampling fps for --clip (default 2)")
    ap.add_argument("--zone", default="0.2,0.2,0.8,0.8",
                    help="fractional crop x1,y1,x2,y2 (default matches the berth default)")
    ap.add_argument("--no-zone", action="store_true", help="disable the crop (full frame)")
    ap.add_argument("--conf", type=float, default=0.5, help="confidence threshold (default 0.5)")
    ap.add_argument("--expect", choices=["person", "none"], help="ground truth for the sample")
    ap.add_argument("--frames-required", type=int, default=2,
                    help="detections needed inside the window to alarm (default 2)")
    ap.add_argument("--window-seconds", type=float, default=3.0,
                    help="rolling alarm window in seconds (default 3)")
    ap.add_argument("--cooldown-seconds", type=float, default=60.0,
                    help="suppress further alarms this long after one fires (default 60)")
    ap.add_argument("--person-enters-at", type=float, metavar="SECONDS",
                    help="clip time the person actually entered frame, for TRUE "
                         "end-to-end latency (without it only rule latency is reported)")
    ap.add_argument("--save-annotated", metavar="DIR", help="write boxed JPEGs of positive frames")
    ap.add_argument("--threads", type=int, metavar="N", default=1,
                    help="OpenVINO CPU threads. DEFAULT 1, matching the Guard worker. "
                         "Measured on the NUC: 1 thread costs 273.3 ms CPU per inference "
                         "vs 390.1 ms with OpenVINO's default ~4 threads - single "
                         "threading REDUCES total CPU by 30%% (TBB spin-wait) and occupies "
                         "exactly one core (CPU/wall = 1.00), leaving three for the "
                         "backend. Pass --threads 0 to measure OpenVINO's default instead.")
    ap.add_argument("--model-dir", default=DEFAULT_MODEL_DIR)
    args = ap.parse_args()

    # 0 means "let OpenVINO decide"; the detector treats None that way.
    threads = None if (args.threads is not None and args.threads <= 0) else args.threads

    if args.classmap:
        return show_classmap(args.model_dir)
    if args.record:
        return record_clip(args.record, args.out, args.url)

    zone = None
    if not args.no_zone:
        try:
            parts = tuple(float(v) for v in args.zone.split(","))
            if len(parts) != 4 or not all(0.0 <= v <= 1.0 for v in parts) \
               or parts[0] >= parts[2] or parts[1] >= parts[3]:
                raise ValueError
            zone = parts
        except ValueError:
            _fail(f"bad --zone {args.zone!r}; expected x1,y1,x2,y2 in 0..1 with x1<x2, y1<y2")

    if args.image:
        if not os.path.exists(args.image):
            _fail(f"{args.image} not found")
        return run_detection(args.model_dir, [args.image], zone, args.conf,
                            args.expect, args.save_annotated, fps=args.fps,
                            num_threads=threads,
                            frames_required=args.frames_required,
                            window_seconds=args.window_seconds,
                            cooldown_seconds=args.cooldown_seconds,
                            person_enters_at=args.person_enters_at)

    if args.clip:
        if not os.path.exists(args.clip):
            _fail(f"{args.clip} not found")
        tmpdir = tempfile.mkdtemp(prefix="guard_probe_")
        try:
            frames = _frames_from_clip(args.clip, args.fps, tmpdir)
            print(f"Extracted {len(frames)} frames at {args.fps} fps from {args.clip}\n")
            return run_detection(args.model_dir, frames, zone, args.conf,
                                args.expect, args.save_annotated, fps=args.fps,
                                num_threads=threads,
                                frames_required=args.frames_required,
                                window_seconds=args.window_seconds,
                                cooldown_seconds=args.cooldown_seconds,
                                person_enters_at=args.person_enters_at)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
