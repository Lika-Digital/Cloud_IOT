# Guard Phase 1 — Stage A Assessment (read-only)

**Date:** 2026-09-26 · **Scope:** feasibility of dashboard-toggled person detection +
alarm + short recording on the marina NUC. **No implementation code written.**

> **Evidence status.** Everything in §1–§4 marked **[CODE]** is verified against the
> files cited. Items marked **[NUC-PENDING]** can only come from the box — I have no
> SSH access from the dev machine, so §5 is a command block to run and paste back.
> Two verdicts in §4 depend on those numbers and are stated conditionally.
>
> **Read §6 first if you are short on time: three premises in the Stage B spec do not
> match the code as it exists today.**

---

## 1. MODEL

### 1.1 Which model is loaded at runtime

**Nothing, by default.** [CODE]

`settings.use_ml_models` defaults to **`False`** (`backend/app/config.py:88`). The
comment above it is explicit: *"Default is false: uses fast Laplacian+histogram
fallback."* `cv_services.py:42` only constructs a real detector when that flag is on:

```python
yolo_detector = YoloOVDetector(_model_dir) if _ml_enabled else YoloOVDetector.__new__(YoloOVDetector)
```

The `else` branch bypasses `__init__` entirely and `cv_services.py:47` sets
`available = False`, so `detect()` returns `{"occupied": None, ...}`
(`yolo_openvino.py:78-79`) and every caller falls through to the classical path.

**So the berth-occupancy "vision pipeline" in production is not a neural network at
all.** It is:

| Stage | Method | File |
|---|---|---|
| Presence | Laplacian edge-density variance on centre 60 % crop, threshold 300 | `berth_analyzer.py:132-157` |
| Identity | 64-bin RGB colour histogram cosine similarity, threshold 0.75 | `berth_analyzer.py:162-204` |

Supporting evidence that the ML path is not installed:

- `openvino` appears **nowhere** in `backend/requirements.txt`.
- `ultralytics` and `opencv-python-headless` are present but **commented out**
  (`backend/requirements.txt:30-31`).
- `nuc_image/ubuntu-install.sh:213-223` installs no CV packages and **no `ffmpeg`**.
- `docker ps` on the NUC (2026-09-20) showed **one** container,
  `pedestal-mqtt-broker`. The `ml_worker` service in `docker-compose.yml:14` — the
  RT-DETR + DINOv2 ONNX path — **is not running.**

Enabling it requires three manual steps that are documented but not automated:
`pip install openvino ultralytics torch`, run `backend/setup_openvino_models.py`,
set `USE_ML_MODELS=true`.

### 1.2 Stock COCO or fine-tuned?

**Stock COCO YOLOv8n. Never retrained. The person class is intact.** [CODE]

`backend/setup_openvino_models.py:58`:

```python
model = YOLO("yolov8n.pt")  # auto-downloads weights
export_path = model.export(format="openvino", dynamic=False, half=False)
```

That string is the Ultralytics pretrained-weights alias — it downloads the official
80-class COCO checkpoint from the Ultralytics release assets. There is **no training
call, no `data=` YAML, no fine-tune step anywhere in the repo**, so the class map is
COCO-80 with `0: person` and `8: boat` in their standard positions. Nothing dropped
the person class, and `model.export()` copies `names` into the IR's `metadata.yaml`,
so the IR class map is identical to the `.pt` by construction.

> `docs/firmware_requirements.md`-style proof of the *actual on-disk* class map still
> needs the §5 command — the argument above is from the export code, and I would rather
> you see the printed map than take the inference. Same for the IR/`.pt` equality check.

**The person class is not the problem. The application code is:** `yolo_openvino.py:15`

```python
_BOAT_CLASS_ID = 8
```

and `yolo_openvino.py:106-108`:

```python
class_id = int(np.argmax(class_scores))
confidence = float(class_scores[class_id])
if class_id == _BOAT_CLASS_ID and confidence >= conf_threshold:
```

Two things happen here, and the second is easy to miss:

1. Only class 8 survives the filter — persons are discarded.
2. `argmax` keeps **one** class per anchor. Even after adding class 0 to the filter, a
   person standing on a boat whose anchor scores `boat` higher than `person` is
   dropped. For multi-class detection this must become a per-class threshold sweep,
   not `argmax`.

### 1.3 Current inference settings [CODE]

| Setting | Value | Evidence |
|---|---|---|
| `imgsz` | **640×640, hard-coded** | `yolo_openvino.py:88` `img.resize((640, 640))` |
| Letterbox | **None — aspect ratio is distorted** | plain `resize()`; Ultralytics normally letterboxes |
| Confidence | caller-supplied, default **0.3** | `berths.py:471`, `berth_models.py:30` |
| **NMS** | **NONE — not implemented at all** | no NMS anywhere in `detect()` (`yolo_openvino.py:100-123`) |
| Device | `"CPU"`, hard-coded | `yolo_openvino.py:55` `core.compile_model(ov_model, "CPU")` |
| Precision | FP32 (`half=False`) | `setup_openvino_models.py:59` |
| Normalisation | `/255.0`, NCHW | `yolo_openvino.py:89-90` |

The missing NMS is tolerable for the current boolean "is a boat there?" question, but
Phase 1 logs a **bbox** per alarm (B2.1), so duplicate overlapping boxes would be
recorded. NMS needs adding — a ~15-line IoU suppression, no new dependency.

---

## 2. GAPS FOR PERSON DETECTION

### 2.1 The MOG2 pre-filter does not exist [CODE]

The spec asks whether MOG2 gating "would miss or delay a slow-moving person". It cannot,
because **there is no MOG2, no background subtractor, and no frame differencing anywhere
in the repository.** Verified by repo-wide grep over all `*.py`:

```
pattern: MOG2|BackgroundSubtractor|absdiff  →  No matches found
```

`Berth.background_image` (`berth_models.py:26-28`) is commented as *"Used by the ML
worker pre-screening step to skip RT-DETR on unchanged scenes"* — but that pre-screen
lives in the `ml_worker` container, which is not running, and the column is unused by
the backend.

So MOG2 is **new work**, not an existing component to reuse. Once written, the
slow-mover risk is real and must be designed against: MOG2 adapts, so a person moving
slower than the learning rate gets absorbed into the background model and stops
generating foreground. Mitigations for Stage B: low `learningRate` (≈0.001–0.005)
while armed, `detectShadows=False`, a minimum-blob-area gate instead of a raw pixel
count, plus a **periodic unconditional inference every N seconds** (e.g. 10 s) so a
stationary or slow person is caught even with zero motion. That heartbeat inference is
the one reliable defence and I recommend it be mandatory.

### 2.2 The frame source is 0.1 fps — this is the biggest gap [CODE]

`frame_buffer.py` is the only continuous frame source, and:

- it refreshes **every 10 seconds** (`frame_buffer.py:35` `await asyncio.sleep(10)`);
- each refresh calls `grab_snapshot()` (`frame_buffer.py:76`), which spawns a **new
  `ffmpeg` subprocess** that opens a **new RTSP connection**, pulls `-vframes 1`, and
  exits (`berth_analyzer.py:92-103`);
- `run_berth_analysis()` is a no-op that sleeps hourly (`berth_analyzer.py:278-286`).

**Effective frame rate: 0.1 fps. There is no persistent capture thread and no
decoder held open.** Consequences for the spec as written:

- "2 of 3 consecutive processed frames" (B2) at 0.1 fps means a person must remain in
  view for **20–30 s** to raise an alarm. For an intruder that is far too slow.
- A 60-second recording (B3) cannot be produced from a 0.1 fps JPEG source. At best it
  would be a 6-frame slideshow.
- Pre-roll from an in-memory ring buffer of these JPEGs would hold ~10 s per 1–2
  frames — useless as video.

This is the single change that decides whether Phase 1 is a real product feature or a
demo. See §6.1 for the proposed fix.

### 2.3 Person pixel height at the current camera position

Camera is confirmed: **D-Link DCS-TF2283AI-DL @ 192.168.1.191**,
`rtsp://admin:***@192.168.1.191:554/profile1` = **H.264 1920×1080 25 fps** (ffprobe,
2026-06-13). It answered ARP as `REACHABLE` on 2026-09-20, so it is alive and on the
LAN *now* — unlike the Opta.

Pixel height of a standing person:

```
h_px = (1.7 m / (2 · d · tan(VFOV/2))) · 1080
```

| Distance | VFOV 45° | VFOV 60° | VFOV 75° |
|---|---|---|---|
| 5 m | 443 px | 318 px | 239 px |
| 10 m | 222 px | 159 px | 120 px |
| 15 m | 148 px | 106 px | 80 px |
| 20 m | 111 px | **80 px** | 60 px |
| 30 m | 74 px | **53 px** | 40 px |

Now the part that matters, and it is **good news that runs against the spec's
assumption that crops may be "too small"**. The detection zone crop is not a
downgrade — it is a free digital zoom, because the resize to 640 happens *after* the
crop:

| Path | Vertical scale into the network | Person @ 20 m, VFOV 60° |
|---|---|---|
| Full frame → `resize(640,640)` | 640/1080 = **0.59** | 80 → **47 px** |
| Zone crop (default 0.2–0.8 = 648 px tall) → `resize(640,640)` | 640/648 = **0.99** | 80 → **79 px** |

Default zone is `zone_y1=0.20, zone_y2=0.80` (`berth_models.py:36-39`), i.e. 648 px of
the 1080, which lands almost exactly on the 640 network input. Cropping therefore
**preserves ~full sensor resolution** for the subject.

Against a rough YOLOv8n floor — reliable ≳40–50 px person height, marginal 20–40 px,
effectively blind below 20 px — that gives:

- **with the zone crop: reliable to ~25–30 m** at VFOV 60°;
- **full-frame path: reliable only to ~15 m.**

So the crop is mandatory for person detection, not optional. **The unknowns are the
lens VFOV and the actual camera-to-boat distance** — both need measuring (§5.6);
everything above is parametric until then.

### 2.4 Night performance [NUC-PENDING]

I will not assert this model's IR specification from memory. The DCS-TF2283AI-DL is an
outdoor camera and D-Link's outdoor DCS line generally ships IR LEDs, but range and
whether IR cut-filter switching actually engages at this mounting position must be
measured, not assumed. §5.5 grabs a snapshot after dark to settle it.

What is already known and matters: at night an IR-illuminated scene is **monochrome**,
and the identity half of the current pipeline is a **colour histogram**
(`berth_analyzer.py:162-176`) — it will degrade badly at night. That affects berth
matching, not person detection, but it is worth knowing before anyone trusts night
results. COCO YOLOv8n does contain IR/low-light persons in its training distribution
only incidentally; expect a real accuracy drop and plan to lower
`GUARD_CONF_THRESHOLD` at night or accept reduced range.

### 2.5 Main vs sub stream [NUC-PENDING, partly known]

`profile1` is confirmed **main: 1080p25**. D-Link ONVIF cameras normally expose
`profile2`/`profile3` sub-streams (typically D1/VGA ~15 fps), but this has not been
verified on this unit — §5.4 enumerates them.

This matters for CPU (§4.3): continuous 1080p25 software H.264 decode is the dominant
cost, and a sub-stream would cut it by ~5–10×. But a sub-stream also destroys the
resolution advantage from §2.3 — a person at 20 m in a 480-line sub-stream is ~35 px,
i.e. marginal. **Recommendation: decode the main stream with hardware acceleration
(the x7425E has QuickSync/VAAPI) rather than dropping to the sub-stream.** Confirm
VAAPI in §5.3.

---

## 3. RECORDING CAPABILITY

### 3.1 Can video be written from the existing capture thread?

**No, on both halves of the question.** [CODE]

- There is no capture thread to write from (§2.2).
- `cv2.VideoWriter` appears **nowhere** in the repo (verified by grep); the only
  `cv2.VideoCapture` is `camera_service.py:45`, which reads a **local demo file**
  (`frontend/public/Video.mp4`), not RTSP.
- OpenCV itself is **not installed** (`requirements.txt:31`, commented out). So
  `VideoWriter` codec availability is not even a question yet — and
  `opencv-python-headless` wheels ship without H.264 encode for licensing reasons, so
  it would be the wrong tool regardless.
- `ffmpeg` **is** on the box (installed manually 2026-06-13 to fix the camera) but is
  **not in the installer**, so a re-imaged NUC regresses. §5.1 re-confirms; the
  one-line installer fix should ride along with Stage B.

**Recommended approach — and it solves three spec requirements at once:** one
persistent `ffmpeg` per guarded camera, using the `tee` muxer to fan one RTSP
connection into two outputs:

1. a low-rate, low-res raw/MJPEG pipe → MOG2 + YOLO (detection);
2. `-c copy` **segmented** MP4 (e.g. 2 s segments, ring of ~15) → recording.

Because output 2 is **stream copy, not re-encode**, it costs ~0 % CPU, and because
segments are already on disk, **pre-roll comes free** — on alarm, concatenate the last
N segments plus the following ones up to the 60 s cap. That satisfies B2.3's pre-roll
*without* an in-memory ring buffer, and B2's "do not open a second RTSP session" with
one connection total.

### 3.2 Disk space and storage path

Free space: **[NUC-PENDING]** — §5.2.

Sizing from the confirmed stream (1080p25 H.264; D-Link default ~4 Mbps):

| Item | Estimate |
|---|---|
| 60 s recording, stream-copy | **~30 MB** |
| 10 alarms/day | ~300 MB/day → ~9 GB/month |
| 50 alarms/day | ~1.5 GB/day → ~45 GB/month |

Proposed path: **`/var/lib/marina-guard/recordings/{camera_id}/`** — matches the
spec default and is correct for this deployment specifically because it is **outside
`/opt/cloud-iot/`**, which `upgrade.sh` overwrites (`README.md:1705`). Must be created
with `cloud-iot` ownership by the installer, and added to `nuc_uninstall.sh` cleanup.

`GUARD_MAX_GB` should default conservatively (I suggest **5 GB**) until §5.2 comes
back; retention must enforce **both** `max_days` and `max_total_gb`, as specified.

Note an existing interaction: `hw_disk_warning` = 60 % and `hw_disk_critical` = 80 %
raise hardware alarms (`config.py:78-79`), and 80 % also **suspends RTSP grabs**
(`hardware_monitor.py:37-44`). Guard recordings filling the disk would trip the guard's
own frame source. Retention must keep total usage well under those thresholds, and
`is_rtsp_suspended()` must be honoured by the guard capture loop.

---

## 4. VERDICT

### 4.1 Can Phase 1 person detection work with the CURRENT model as-is?

## PARTIAL — the *weights* are fine, the *plumbing* is not.

- **Model: YES.** Stock COCO YOLOv8n already contains `person` (class 0) at full
  accuracy. **No retraining, no second model, no new weights needed** — this is the
  one part of the spec that needs nothing.
- **Runtime: NO.** The model is not loaded (`USE_ML_MODELS=false`), OpenVINO is not
  installed, class 0 is filtered out, there is no motion stage, no NMS, the frame
  source runs at 0.1 fps, and nothing can write video.

### 4.2 Minimum change needed

In dependency order. Items 1–3 are the load-bearing ones.

1. **Replace the frame source** (§2.2) — one persistent `ffmpeg`/`tee` per guarded
   camera at 2–5 fps for detection + `-c copy` segments for recording. Runs **only
   while that camera's guard is enabled**, so disabled guard costs exactly zero and
   berth occupancy is untouched. *Without this, nothing else in Phase 1 is meaningful.*
2. **Install + enable the ML path** — add `openvino` (and `opencv-python-headless` for
   MOG2) to requirements, run `setup_openvino_models.py`, set `USE_ML_MODELS=true`.
   Keep the **stock COCO weights** — §1.2.
3. **Generalise the detector** — `yolo_openvino.py` currently hard-codes class 8 and
   uses `argmax`. Add a `classes: set[int]` parameter, replace `argmax` with a
   per-class threshold sweep, and add NMS. **Additive and default-compatible:** default
   `classes={8}` so berth occupancy behaviour is bit-for-bit unchanged (acceptance
   criterion 4), guard passes `classes={0}`.
4. **Keep the zone crop** and fix the resize to **letterbox** instead of distorting
   aspect (§2.3). Optionally raise guard `imgsz` to 960 if §5.7 shows CPU headroom.
5. **Add MOG2** with a low learning rate **plus a mandatory periodic unconditional
   inference** (~every 10 s) so a slow or stationary person cannot be gated out (§2.1).
6. **Add `ffmpeg` to both installers** — pre-existing latent bug, cheap to fix here.

### 4.3 Estimated extra CPU load when guard is active

Hardware: **Intel Atom x7425E** (Alder Lake-N, 4 cores, no AVX-512) per
`config.py:86`. Measured YOLOv8n OpenVINO latency on this box is documented as
**500–2000 ms per inference** (`config.py:86-87`) — call it ~800 ms typical at 640².

| Component | Cost (of one core) | Cost (of 4 cores) |
|---|---|---|
| H.264 1080p25 decode, **software** | 30–50 % | 8–13 % |
| H.264 1080p25 decode, **VAAPI** | ~5 % | ~1 % |
| Recording, `-c copy` (no re-encode) | ~0 % | ~0 % |
| MOG2 on 648×1152 crop @ 5 fps | 5–10 % | 1–3 % |
| **YOLO @ 1 fps** (motion active) | **~80 %** | **~20 %** |
| **YOLO @ 2 fps** (motion active) | **~160 %** | **~40 %** |

**Conclusion: the 15 % acceptance target is achievable in steady state, but only with
all three of** — hardware-accelerated decode, motion gating that keeps inference near
zero on a quiet scene, and an inference rate cap of **≤1 fps**.

Realistic numbers for one guarded camera:

- **Armed, quiet scene:** ~3–6 % of total CPU (decode + MOG2 + the 10 s heartbeat
  inference). **Meets the target.**
- **Motion present / alarm:** **25–45 %** of total CPU while inference runs.
  **Exceeds 15 %** — unavoidable with a 0.8 s/frame detector on an Atom.

Criterion 5 says *"in steady state"*, which I read as the armed-quiet case, so this
passes as written — but I want the peak stated explicitly rather than discovered during
acceptance. **Two cameras armed simultaneously would not fit**; guard should be
single-camera at a time, or inference serialised behind one global lock. Only 1 pedestal
(hence 1 camera) exists today, so this is a design guard-rail, not a present limit.

All of the above are **estimates from the documented 500–2000 ms figure** — §5.7
measures it for real, and I would not sign up to criterion 5 before those numbers land.

---

## 5. NUC COMMANDS NEEDED TO CLOSE THIS ASSESSMENT

I cannot reach the box from here. Please run this block and paste the output; I will
fold the results into §1–§4 and mark the `[NUC-PENDING]` items resolved.

```bash
# ── 5.1 ffmpeg present? (whole frame source depends on it) ───────────────────
which ffmpeg ffprobe; ffmpeg -version 2>/dev/null | head -2

# ── 5.2 disk space + proposed storage path ──────────────────────────────────
df -h / /var; echo "---"; du -sh /opt/cloud-iot 2>/dev/null

# ── 5.3 hardware H.264 decode (VAAPI) available? ────────────────────────────
ls -l /dev/dri/ 2>/dev/null; ffmpeg -hide_banner -hwaccels 2>/dev/null
lscpu | grep -E "Model name|^CPU\(s\)|Thread|Core"

# ── 5.4 stream profiles: main + any sub-stream ──────────────────────────────
for p in profile1 profile2 profile3; do
  echo "=== $p ==="
  timeout 15 ffprobe -v error -rtsp_transport tcp \
    -select_streams v:0 -show_entries stream=width,height,r_frame_rate,codec_name,bit_rate \
    -of default=noprint_wrappers=1 \
    "rtsp://admin:PASSWORD@192.168.1.191:554/$p" 2>&1 | head -6
done

# ── 5.5 night usability (run after dark; is it IR/monochrome and usable?) ───
timeout 20 ffmpeg -y -rtsp_transport tcp -i "rtsp://admin:PASSWORD@192.168.1.191:554/profile1" \
  -vframes 1 /tmp/night_test.jpg 2>/dev/null && ls -l /tmp/night_test.jpg
#   then view it: does it show IR illumination, and is a person-sized object visible?

# ── 5.6 geometry for the §2.3 estimate ─────────────────────────────────────
#   Not a command — two measurements, please:
#     a) camera → moored boat distance, in metres (tape or a rough pace count)
#     b) lens FOV from the camera's web UI / label, or: photograph a 1 m ruler at a
#        known distance and report its pixel width

# ── 5.7 is the ML path installed, and what is the REAL class map + latency? ──
cd /opt/cloud-iot/backend
grep -i "USE_ML_MODELS" .env || echo "USE_ML_MODELS not set (defaults false)"
ls -la models/ 2>/dev/null
.venv/bin/python -c "import openvino; print('openvino', openvino.__version__)" 2>&1 | tail -1
.venv/bin/python -c "import cv2; print('opencv', cv2.__version__)" 2>&1 | tail -1

#   If models/yolov8n_openvino exists, print the ACTUAL class map from the IR:
cat models/yolov8n_openvino/metadata.yaml 2>/dev/null | head -20
#   ... and confirm class 0 is 'person' + class 8 is 'boat':
.venv/bin/python - <<'PY' 2>&1 | tail -5
import glob, openvino as ov
xml = (glob.glob('/opt/cloud-iot/backend/models/yolov8n_openvino/*.xml') or [None])[0]
print('IR:', xml)
if xml:
    m = ov.Core().read_model(xml)
    print('input:', m.input(0).partial_shape, 'output:', m.output(0).partial_shape)
PY

# ── 5.8 baseline CPU, so "extra load" has something to be extra TO ──────────
uptime; top -bn2 | grep "Cpu(s)" | tail -1
systemctl is-active cloud-iot-backend nginx docker
```

If §5.7 shows the ML path is absent (most likely), the class-map proof requires
installing it first — that is Stage B item 2, so I would note the class map as
"verified from export code, on-disk proof deferred to first Stage B step" rather than
block Stage A on it. Your call.

---

## 6. WHERE STAGE A CONTRADICTS THE STAGE B SPEC

Per your PROCESS instruction — flagging rather than silently adapting. Three real
mismatches and three smaller ones.

### 6.1 "Reuse the EXISTING capture thread / frame source" (B2) — no such thing exists

There is no capture thread and no persistent RTSP session. There is a **0.1 fps
snapshot poller** that opens a fresh `ffmpeg`/RTSP connection every 10 s, per camera
(§2.2). Taken literally, the spec would have the guard run at 0.1 fps, making
"2 of 3 consecutive frames" a 20–30 s detection latency and a 60 s recording
impossible.

**Proposed change:** build one new capture path used *only while guard is enabled* —
a single persistent `ffmpeg` per guarded camera with a `tee` muxer (§3.1) giving both
the detection frames (2–5 fps) and stream-copy segments for recording. This *honours
the spirit* of the constraint — **one** RTSP connection, not two — while making the
timing requirements physically achievable. The existing 10 s frame buffer keeps running
untouched for berth occupancy, so acceptance criterion 4 holds by construction.

### 6.2 "motion (MOG2) → if motion, run detector" (B2) — MOG2 does not exist

Repo-wide grep: no `MOG2`, no `BackgroundSubtractor`, no frame differencing (§2.1).
This is new work, and it needs OpenCV installed (currently commented out of
requirements). It also needs the slow-mover mitigation from §2.1 — **I propose making
the periodic unconditional inference (~10 s) mandatory**, because pure motion gating
will silently miss a person who stops moving, which is exactly the intruder case.

### 6.3 Pre-roll (B2.3) — feasible, but not from an in-memory ring buffer

The spec says in-memory "if Stage A says it is feasible". In-memory ring buffering of
*decoded* 1080p frames is expensive (~6 MB/frame raw; 5 s at 5 fps ≈ 150 MB). The
`ffmpeg` segment ring in §3.1 gives pre-roll on disk at **~0 % CPU and no re-encode**,
which is strictly better. **Proposed change: implement pre-roll via the segment ring
rather than RAM.** Default ~6 s pre-roll (3 × 2 s segments), configurable.

### 6.4 `camera_id` (B1) — no camera entity exists

Cameras are columns on `pedestal_configs` (`camera_stream_url`, `camera_username`,
`camera_password`, `camera_fqdn`, `camera_reachable` — `pedestal_config.py:25-45`),
one per pedestal. There is no camera table and no camera id.
**Proposal: `camera_id` == `pedestal_id`** throughout the guard API, documented
plainly, with no new entity in Phase 1. Say the word if you would rather have a real
`cameras` table — it is a bigger change and I would not slip it in quietly.

### 6.5 MQTT topic `marina/{marina_id}/camera/{camera_id}/guard/state` (B1) — no `marina_id` is stored

`marina_id` exists only as a *derived substring* of the cabinet id (pattern
`MAR_{marina_id}_...`, e.g. `MAR_KRK_ORM_01` → `KRK`), used by the ERP endpoints
(`ext_meter_load_endpoints.py:156-164`). Live topics are `opta/...` and
`marina/cabinet/{cabinetId}/...`.

Two options: **(a)** derive `marina_id` from the cabinet id the same way the ERP
endpoints do; **(b)** follow the existing convention —
`marina/cabinet/{cabinet_id}/camera/{camera_id}/guard/{state,alarm}`. **I recommend
(b)** for consistency with every other live topic. Also note: **retained** guard state
is the right choice here *and* is now safe — v3.40 (`a0a1405`) taught the backend to
distinguish retained replays from live messages, so a retained guard state will not be
mistaken for liveness evidence on restart.

### 6.6 Acceptance criterion 5 needs a definition

"Extra CPU load under 15 %" — of **one core** or of **all four**? My §4.3 numbers say
armed-and-quiet passes either way, but an active alarm is ~25–45 % of total CPU and
would fail a strict reading. I have assumed *"steady state" = armed, no motion*, and
that peaks during an alarm are acceptable. **Please confirm.**

---

## 7. RECOMMENDATION

Phase 1 is **feasible on this hardware with the stock model**, and the model is the
part that needs no work at all. The real work is a proper capture path (§6.1), the
motion stage (§6.2), and making the detector multi-class (§4.2 item 3).

Before Stage B I need: **the §5 output**, and a decision on **§6.1, §6.3, §6.5 and
§6.6**. §6.2 and §6.4 I will proceed with as proposed unless you object.

I have **not written any implementation code** and will not until you approve.
