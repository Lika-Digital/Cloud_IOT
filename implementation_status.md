# Implementation Status — Guard B1 DESIGN SUBMITTED — awaiting approval, no code written

## 2026-09-26 — Stage B approved. B1 restatement written for sign-off BEFORE any implementation.

Settings locked: GUARD_FPS=1, GUARD_WINDOW_SECONDS=4, GUARD_FRAMES_REQUIRED=2, threads=1
fixed at compile_model time. 2 fps / 3 s is the documented reserve, reachable by runtime
config only — no switch built for it. A.5 rows 3,4,5,6,12,13 remain pending, not blocking.

- [DONE] `docs/guard_b1_design.md` (NEW) — the B1 restatement: process split, the systemd
  unit verbatim, full MQTT contract (8 topics with direction/retain/payload), single-DB-writer
  confirmation, REST surface, the complete arm/disarm chain with timeouts, and how a false
  ARMED is made impossible. **No implementation code.**
- [DESIGN] **CPUQuota=60 % IS the acceptance budget, kernel-enforced** — 60 % of one core =
  15 % of this 4-core box. Measured need 27.3 % of one core at 1 fps, 47.8 % at 2 fps, so
  both fit under a ceiling the kernel applies rather than one we promise to respect.
- [DESIGN] **False ARMED is impossible three independent ways:** MQTT Last Will overwrites
  the retained `guard/state` with UNAVAILABLE; a 15 s heartbeat gap trips it; and
  `worker_seen_at` is in-memory and deliberately NOT persisted, so a stale retained ARMED
  cannot survive a backend restart as truth. Direct application of the v3.40 lesson.
  `guard/cmd` is deliberately NOT retained — a replayed command could arm a restarting
  worker with nobody asking, which is the v3.40 failure shape exactly.
- [CORRECTION to the brief] The pedestals do **not** use Last Will — `mqtt_client.py` sets no
  `will_set`; cabinet liveness is the 15 s `opta/status` heartbeat + `_comm_loss_watchdog`.
  Guard will use **both** LWT and a heartbeat, because LWT only fires on a broker-detected
  disconnect and not at all if the process wedges with its socket open.
- [DESIGN] Single writer holds on both sides: backend is the **only DB writer** (worker never
  opens a DB, publishes instead); the worker is the **only file writer** under
  `/var/lib/marina-guard/` and owns retention, backend reads only.
- [DESIGN] Probe and worker share `app/guard/pipeline.py` + `app/guard/alarm_rule.py`, with a
  hard constraint that those two modules import stdlib+numpy+PIL ONLY — that is what keeps
  the probe runnable from the staging venv (proven in A1). A test will assert it.
- [OPEN — 6 DECISIONS] §10 of the design: dedicated `guard` user; LIMITED_VISIBILITY as a
  health flag not a state; five extra REST endpoints forced by requirements 1-3; frame-saving
  budget (logging every detection is cheap, saving every frame is 600 MB/day — proposal caps
  it at ~430 MB); `guard_detections` retention 30 d; and notifications built NOT AT ALL
  rather than built-but-disabled.
- [DONE] `docs/guard_docs_pass_scope.md` (NEW) — **documentation is deferred to LAST**, per
  the agreed sequence B1 → Stage B → UI v2 → deploy → docs. Written once, not per piece.
  Scope checklist captured now so nothing is lost, including the measured-numbers table with
  its measurement date. One MD source of truth, PDF exported from it, reusing the existing
  `scripts/generate_*.py` + reportlab pattern.
- [BACKLOG — separate work, NOT inside guard/UI v2] requirements.txt drift audit (only numpy
  fixed so far); TME 192.168.1.254 returning 404 on `values.xml` while `fresh.xml` returns 200.
- [NEXT] **STOP for B1 approval + the six decisions.** Then build in the given order:
  ffmpeg/segments → detection+rule → recording/retention → watchdog → MQTT/REST/persistence
  → dashboard. `main` only after the acceptance criteria are measured on the NUC.

# Implementation Status — Guard A.5 PARTIAL RESULTS IN — person clips pending

## 2026-09-26 — control clip + timing measured on the NUC. 1 fps settled. Three fixes applied.

**Measured (NUC, 1200 frames, camera unattended):** alarms 0, false alarms/hour 0.00,
frame FP rate 0.000 (0/1200) → **hard gate PASS**. Inference mean 91.0 ms wall / p95 101.5 /
max 162.1; **CPU 390.1 ms per inference**; implied 9.8 % of 4 cores at 1 fps; no drift over
10 min. class 0=person, 8=boat, 80 classes, openvino 2026.4.0 → PASS. 49 logic tests on
numpy 2.4.6 → PASS. Rows 3,4,5,6,12,13 (person clips) **still pending** — not at the marina.

- [SETTLED] **1 fps is the working rate.** 390 ms CPU/inference → 9.8 % of 4 cores at 1 fps
  vs 19.5 % at 2 fps, so 2 fps cannot meet the <15 % budget. **Recommended rule:
  `GUARD_FPS=1`, `GUARD_WINDOW_SECONDS=4` (up from 3), `GUARD_FRAMES_REQUIRED=2`.** 1 fps/3 s
  gives only 4 samples in the window; 4 s gives 5 and recovers most of the loss
  (P(alarm) at r=0.6: 0.821 → 0.913). Latency min 1.0 s / max 4.0 s, inside the ≤5 s
  threshold. False-alarm cost at the pessimistic 95 % bound for 0/1200 (p=0.0025, rule of
  three): **0.056/hour ≈ one every 18 h**. All figures verified by replaying the real
  `evaluate_alarm_rule` code, not hand-arithmetic. **Provisional until row 4 (recall) lands.**
- [NEW] **Thread cap — from the wall-vs-CPU gap.** 91 ms wall / 390 ms CPU = ~4.3 threads,
  i.e. guard saturates ALL 4 cores for 91 ms every second. Average is fine, the spike is
  what could make berth occupancy stutter. `YoloOVDetector(num_threads=...)` added
  (`INFERENCE_NUM_THREADS`, best-effort with silent fallback), plus `--threads` on the
  probe. **Default stays None** so berth occupancy is unchanged. At 1 fps, 1 thread costs
  nothing (390 ms wall out of 1000 ms) and leaves 3 cores free.
- [FIXED] **(1) `guard_measure.sh tests`** — now passes `--noconftest`.
  `tests/backend/conftest.py` builds the FastAPI test app and imports sqlalchemy/fastapi,
  absent from the staging venv by design; the guard tests need none of it and `pytest.ini`
  still gives `pythonpath = backend`. Equivalent to the manual run that gave 49 passed.
- [EXPLAINED + HARDENED] **(2) Docker route not taken** — root cause: the clone was at
  `da3716f` or earlier, which **had no Docker route at all** (added in `1ceb280`). Verified
  by `git show da3716f:scripts/guard_export_model.sh | grep -c docker` → 0. Hardening added
  anyway: the script now prints **why** a route was chosen, distinguishes "docker absent"
  from "daemon unreachable (try sudo)", detects **tmpfs `/tmp` and REFUSES the venv route**
  when Docker is usable (overridable via `GUARD_ALLOW_TMPFS=1`), and honours
  `GUARD_EXPORT_TMPDIR=/var/tmp` for a disk-backed work dir.
- [ALREADY FIXED] **(3) dangerous next-steps text** — same root cause; `1ceb280` replaced it
  with `bash scripts/guard_measure.sh classmap`. Confirmed by diffing the two versions.
- [FIXED] **(cosmetic) Python 3.14 forkserver tracebacks** — caused by `python -c`: 3.14
  defaults to forkserver, whose children re-import `__main__`, which for `-c` is `<stdin>`.
  The export program is now written to a real file with an `if __name__ == "__main__":`
  guard. Embedded program compile-checked in CI-style before commit.
- [VERIFIED] Full suite **675 passed** on numpy 2.4.6. `bash -n` clean on both scripts.
- [NEXT] Person clips at the stern (rows 3,4,5,6,12,13) when someone can walk it, plus the
  optional `--threads 1` comparison. Stage B still awaits those numbers + the B1 restatement.

# Implementation Status — Guard A.5 runbook ready — AWAITING FIELD NUMBERS

## 2026-09-26 (late) — four corrections applied; runbook written; NO production change needed.

- [FIXED] **(1) Staging numpy contradiction — my own bug, would have failed on the NUC.**
  `guard_measure.sh` pinned `numpy==2.1.2` "to match production" while production is 2.4.6
  and 2.1.2 has no cp314 wheel → source build on Python 3.14.4. My earlier proof ran on
  Windows where 2.1.2 *does* have a wheel, so it never surfaced. Now the version is **read
  from the production venv at runtime** (`resolve_numpy`, `GUARD_NUMPY` override) so it
  cannot be hardcoded wrong again, and every install uses **`--only-binary=:all:`** so a
  missing wheel fails instantly instead of compiling. Verified the fallback and override
  paths. Also added `GUARD_IR_SRC` to import a pre-exported IR and skip torch entirely.
- [DONE] **(2) Night removed — out of scope.** No IR illuminator, poor sensor → recorded as
  **unsupported on this hardware** (procurement question, not software). Purged from the
  probe docstring, the runbook, and the stale §5.5 command in the assessment (replaced with
  DO-NOT-RUN). §2.4 marked superseded.
- [DONE] **(3) Not a far berth — ~10 m stern view.** Renamed throughout. Probe now prints
  the **~150 px expectation** for a person at 10 m with the zone crop and flags a median
  **below 100 px** as a setup problem (crop/framing/distance), not a model problem. Added
  the two partial-body cases: **upper body behind the stern rail** and **crouching**, both
  graded NOTE rather than STOP since full-body boarding is the main case.
- [DONE] **(4) torch question answered explicitly** — needed ONLY for the one-time IR
  export, never for the measurement. Three cases documented (IR already staged → skipped
  with an explicit log line; `GUARD_IR_SRC` → skipped; first run → ~4 GB once, in a
  throwaway /tmp venv). Measurement venv is openvino + numpy + Pillow, ~200 MB.
- [DONE] `docs/guard_a5_runbook.md` (NEW) — copy-paste, phone-first: step 0 baseline,
  step 1 **separate checkout (no merge to main, no upgrade.sh, no `git pull` in
  ~/Cloud_IOT)**, step 2 ordered checks each marked STOP or NOTE, step 3 physical
  measurement with what to do and who must be present, step 4 **13 numeric thresholds**
  (incl. CPU ms/inference ≤300 derived from the <15 %-of-4-cores budget at 2 fps, and
  control-clip alarms = 0 as the hard gate), step 5 rollback + three independent
  verifications that production is untouched.
- [ANSWERED] **main/upgrade.sh not needed to measure.** Measurement reads nothing from
  /opt except `pedestal.db` (mode=ro). Separate clone at `~/guard-checkout` keeps
  `~/Cloud_IOT` intact (pulling there would break upgrade.sh change detection) and leaves
  main at v3.40 until the numbers justify it.
- [VERIFIED] 49 guard tests pass; `bash -n` clean on both scripts; numpy-resolution logic
  exercised for both the override and the fallback path; probe help renders the new scope.
- [NEXT] **STOP.** Run the runbook; report the step-4 table. Stage B still awaits approval
  of those numbers plus the B1 restatement (separate-process consequence).

# Implementation Status — Guard A.5 items 1-5 answered — STILL AWAITING NUC NUMBERS

## 2026-09-26 (evening) — verified NUC state applied; architecture decision taken.

NUC facts taken as given: Python 3.14.4, numpy 2.4.6, Pillow 12.2.0, no openvino/opencv,
58 pkgs, freeze at ~/venv_freeze_2026-09-26.txt. Idle load 0.07, 1.3/14 Gi RAM, 397 G free,
backend RSS 316.6 MB, uvicorn --workers 1, USE_ML_MODELS=false.

- [DONE] **(1) Throwaway venv — YES, proven.** `app/__init__.py` and
  `app/services/__init__.py` are both **0 bytes**; `yolo_openvino.py` imports only
  stdlib at module level (numpy/PIL/openvino are lazy). Verified empirically in a venv
  with ONLY numpy 2.1.2 + Pillow, fastapi/sqlalchemy/pydantic/openvino confirmed absent:
  import OK, detector degrades to available=False, decode+NMS ran, alarm rule fired.
  **No import or path forces the production venv.** `scripts/guard_measure.sh` (d91bef5)
  already is the restructure. Defaults to `$HOME/guard-staging` not `/tmp` on purpose —
  /tmp is tmpfs on many Ubuntu installs and the torch export needs ~4 GB, which would be
  RAM on a 14 Gi box; `GUARD_STAGING=/tmp/...` overrides.
- [DONE] **(2) Telemetry — three layers, documented.** Env var
  `OPENVINO_TELEMETRY_OPT_OUT=1` (with a grep command to verify the real name on the box
  rather than trusting mine); uninstall `openvino-telemetry` and re-run classmap/probe to
  prove inference is unaffected; and the actual guarantee — per-unit
  `IPAddressDeny=any` + `IPAddressAllow=localhost 192.168.1.0/24` in
  `cloud-iot-guard.service`, making egress structurally impossible. Only available
  because of the separate-process decision.
- [DONE] **(3) numpy drift — cause + fix, committed SEPARATELY as `6a404b2`.**
  numpy 2.1.2 predates Python 3.14 → no cp314 wheel → source build → the venv was rebuilt
  by hand with relaxed pins and drifted; `upgrade.sh:204-208` only *warns* on pip failure,
  so the pin failed silently every upgrade. Re-ran the suite on the real version:
  **675 passed on numpy 2.4.6** (also 675 on 2.1.2 and 2.5.3). requirements.txt corrected
  to `numpy>=2.1,<3`. **Flagged: every other pin is also a 3.12-era `==` and likely
  drifted too** — diff command supplied, left as its own task.
- [DONE] **(4) Architecture — separate process, recommended without reservation.**
  `cloud-iot-guard.service`, own venv, MQTT (already localhost, already carries the spec's
  guard topics) to the backend; backend stays the ONLY DB writer. Wins: "no model resident
  while disarmed" becomes provable (process not running) where in-process RSS release is
  not guaranteed; a native openvino segfault cannot kill uvicorn (--workers 1, no spare);
  CPU watchdog gets kernel-enforced CPUQuota/systemctl stop; openvino never enters the
  production venv so the A3 drift class cannot recur; per-unit egress block. Cost ~40
  lines of unit/provisioning, near-zero IPC. **Consequence: B1 changes** — `app/guard/`
  becomes a thin control/query layer; detection+ffmpeg+recording live in the worker. To be
  restated for approval before any Stage B code.
- [DONE] **(5) Recorded, not fixed** — TME 192.168.1.254: `values.xml` 404, `fresh.xml`
  200 (consistent with the existing `test_tme_fresh_xml.py`). In project memory.
- [DONE] `docs/guard_stage_a5_addendum.md` (NEW) — all five answers with evidence.
- [VERIFIED] Full suite **675 passed** on numpy 2.4.6, the production version.
- [BLOCKED — NUC] A.5 numbers still outstanding: classmap proof, day/far/night/control
  clips → recall, false-alarms-per-hour, latency, person pixel height, inference ms, CPU
  per inference. Run `guard_measure.sh` when the marina is quiet; **no production change
  required.**
- [NEXT] **STOP.** Stage B awaits approval of those numbers + the B1 restatement.

# Implementation Status — Guard A.5 conditions applied — AWAITING NUC NUMBERS

## 2026-09-26 (later) — A.5 approved with conditions; all four addressed. Measurement still pending.

Conditions accepted: (1) requirements-vision.txt stays separate until guard is proven in
production; (2) NMS enabled on the person path, boat path left bit-identical; (3) opencv
dropped; (4) frame-level recall + control-clip FP rate accepted, plus the event-level
metric below.

### Added before measuring (A/B/C/D)
- [DONE] **A — event-level metric.** `evaluate_alarm_rule()` in
  `scripts/guard_detect_probe.py`: pure replay of the real rule (>=N detections in a
  rolling W-second window, then cooldown). The probe now reports alarms raised, **false
  alarms per hour** on the control clip, rule latency, and true end-to-end latency when
  `--person-enters-at` is given. Kept pure so Stage B PROMOTES it instead of
  reimplementing it. Warns when a FP rate is extrapolated from a clip under 10 min.
- [DONE] `tests/backend/test_guard_alarm_rule.py` (NEW, 10 cases TC-GAR-01..10) — loaded
  via importlib since `scripts/` is not a package. Covers 2-in-window, lone detection,
  wider-than-window, cooldown collapsing a 20 s loiter into ONE alarm, re-arm after
  cooldown, frames_required=3, latency from first detection, empty input, sparse
  flicker rejection, and rolling-vs-bucketed window.
- [DONE] **B — distance check.** Probe measures **person pixel height** from the detected
  bbox against the real crop dimensions (median/min/max) and flags a median under 40 px
  as at/past usable range. Prints the crop size fed to the model. Record at the FAR berth.
- [DONE] **C — night clip** promoted to required in the run sheet; if the camera is
  unusable after dark that is to be reported as a product decision, not a failure.
- [DONE] **D — numpy pin.** Installed the pinned `numpy==2.1.2` on the dev box (it does
  have a 32-bit wheel) and re-ran everything: **675 passed**. The pin does NOT need to
  move; earlier results on 2.5.3 are superseded.

### Measurement needs NO production change (answers the safety question)
- [DONE] `scripts/guard_measure.sh` (NEW) — runs the entire measurement in isolation:
  venv at `$HOME/guard-staging/venv` (openvino + numpy==2.1.2 + Pillow), IR at
  `$HOME/guard-staging/models`. **Nothing under /opt/cloud-iot is written, the production
  venv is untouched, USE_ML_MODELS stays false.** Only read-only shared access:
  pedestal.db opened `mode=ro` for the camera URL, plus the RTSP stream.
  Subcommands: `setup | classmap | record | probe | tests | clean`.
  `tests` runs the decode + alarm-rule suites on numpy 2.1.2 inside that venv.
- [DONE] `scripts/guard_export_model.sh` — `MODELS_DIR` now overridable so the export can
  land in staging; chown/`/opt` checks apply only when targeting the production tree.
- [DONE] `scripts/guard_baseline.sh` (NEW) — the before/after/rollback procedure, kept for
  the eventual *deliberate* production install (Stage B), not needed for measuring.
  `before` saves pip freeze + 60 s CPU average + RAM + backend RSS + service states +
  USE_ML_MODELS + live API/MQTT health to `/var/backups/guard-baseline/`; `after` diffs
  all of it; `rollback` uninstalls openvino, restores the freeze, restarts and verifies.
- [FIXED] two defects in that script while writing it: dead `paste` no-op, and a
  `diff|grep|sed` pipeline whose exit status could never trigger its "none" fallback.

- [VERIFIED] Full suite **675 passed** (665 + 10) on numpy 2.1.2. Shell scripts pass
  `bash -n`. Probe compiles and fails cleanly with a clear message when the IR is absent.
- [BLOCKED — NUC] Still cannot run on the box from here. Needs `guard_measure.sh setup`
  then the classmap + day/far/night/control clips. **Recall, false-alarms-per-hour,
  latency, person pixel height, inference ms and CPU per inference must come from that
  run.** Run when the marina is not busy.
- [NEXT] **STOP.** Report numbers; Stage B awaits approval.

# Implementation Status — Guard Phase 1 — STAGE A.5 (detector) — AWAITING NUMBERS

## 2026-09-26 — Stage A accepted. A.5 code complete; NUC proof outstanding.

Approved decisions carried in: (1) one persistent ffmpeg per camera, 10 s segment ring
x6 + 2-4 fps frames, replacing the per-poll spawn; (2) **MOG2 dropped** — detector runs
directly on the cropped zone; (3) pre-roll from the disk segment ring, not RAM;
(4) `camera_id` is its own entity referencing pedestal/berth; (5) `MARINA_ID` added to
config, not derived; (6) CPU budget defined by the resource watchdog. Zone crop stays
before the 640 resize (mandatory — it is what gives ~25-30 m range vs ~15 m).

### A.5 — detector rewrite (code done, tests green on dev)
- [DONE] `backend/app/services/yolo_openvino.py` — rewritten. Multi-class decode,
  per-class thresholds, class-aware NMS, optional letterbox, `unload()` for Stage B's
  "no model resident while disarmed", class map read from the IR's own `metadata.yaml`
  (falls back to COCO-80). Decode/NMS/letterbox extracted as **pure functions** so they
  are testable without openvino. Vectorised the 8400-row Python loop (same results).
- [DONE] **Berth behaviour preserved by construction.** Legacy defaults reproduce the
  pre-rewrite path bit-for-bit: `classes={8}`, `select="argmax"`, `apply_nms=False`,
  `letterbox=False`, distorting 640x640 resize. Guard opts in via `detect_persons()`
  (`classes={0}`, per-class select, NMS on, letterbox on).
- [DONE] `tests/backend/test_yolo_multiclass.py` (NEW, 39 cases incl. parametrised).
  TC-YMC-01 re-implements the pre-rewrite loop verbatim and fuzzes 18 seed/threshold
  combinations for exact equality. TC-YMC-16..19 drive the real `detect()` through a
  **fake compiled model**, so the berth contract is locked without openvino present.
- [FIXED — found by those tests] layout auto-detect (`shape[1] < shape[2]`) mis-oriented
  tensors with fewer anchors than channels → added explicit `layout=` override.
- [FIXED — found by those tests] degenerate shapes (0 anchors / no class columns) raised
  out of `argmax` → now return `[]`.
- [FIXED — found by those tests] converting box coords to float64 **before** dividing
  changed every coordinate by ~3e-9 vs the old float32 division. Now divides in the
  tensor dtype and widens after, restoring bit-exactness.
- [DONE] `backend/requirements-vision.txt` (NEW) — `openvino` only. Deliberately NOT in
  `requirements.txt`: `upgrade.sh:204-208` pip-installs that file into the production
  venv on every change and only *warns* on failure — the path that crash-looped the 3.14
  venv on the v3.19 deploy. **opencv NOT required** (MOG2 dropped per decision 2).
- [DONE] `scripts/guard_export_model.sh` (NEW) — exports stock COCO yolov8n to IR inside
  a **throwaway /tmp venv** (ultralytics+torch never touch the production venv), asserts
  class 0=person / 8=boat before exporting, 4 GB free-space precheck, idempotent.
- [DONE] `scripts/guard_detect_probe.py` (NEW) — proof + benchmark. `--classmap` prints
  the on-disk class map and IR shapes; `--record` grabs a real-angle clip with `-c copy`;
  `--clip/--image` report per-frame detections, inference ms (mean/median/p95), CPU
  ms/frame and implied load; `--expect person|none` gives frame-level recall / FP rate;
  `--save-annotated` writes boxed JPEGs. Reads the RTSP URL read-only from pedestal.db
  and redacts the password.
- [VERIFIED] Full suite **665 passed** (626 + 39). Disabled-path `detect()` still returns
  `occupied=None` so `berths.py` keeps falling back to Laplacian. `berths.py` imports OK.
- [NOTE] numpy was absent from the dev venv; installed 2.5.3 locally to run these tests
  (requirements pins 2.1.2 — dev venv only, requirements.txt untouched). Re-ran the full
  suite afterwards: no path changed behaviour now that numpy imports.
- [BLOCKED — NUC] Cannot run on the box from here. Needs: export the IR, install
  requirements-vision.txt, set USE_ML_MODELS=true, then `--classmap` + a day clip and
  (if possible) a night clip. **Precision/recall, inference ms and measured CPU per
  inference must come from that run — not from this machine.**
- [NEXT] **STOP.** Report the A.5 numbers and await approval before Stage B.

# Implementation Status — Guard Phase 1 (person detection) — STAGE A ONLY

## 2026-09-26 — Stage A assessment delivered, AWAITING APPROVAL before any implementation

Read-only feasibility assessment for dashboard-toggled person detection + alarm + short
recording. **No implementation code written — Stage B is gated on explicit approval.**

- [DONE] `docs/guard_phase1_assessment.md` (NEW) — full Stage A answer: model identity,
  gaps, recording capability, verdict, NUC command block, spec contradictions.
- [VERDICT] **PARTIAL.** The stock COCO YOLOv8n weights already contain `person`
  (class 0) — no retraining needed. The plumbing is what is missing.
- [KEY FINDING] `USE_ML_MODELS` defaults **false** (`config.py:88`), openvino is not in
  requirements, `ml_worker` is not running on the NUC → berth occupancy currently runs on
  **Laplacian variance + colour histogram**, no neural net at all.
- [KEY FINDING] `yolo_openvino.py:15` hard-codes `_BOAT_CLASS_ID = 8` and uses `argmax`
  (one class per anchor) → persons discarded even if the filter is widened. No NMS.
- [KEY FINDING] **No MOG2 / BackgroundSubtractor / frame differencing anywhere** in the
  repo (grep-verified). The spec's motion pre-filter is new work, not reuse.
- [KEY FINDING] **No capture thread exists.** `frame_buffer.py` polls at **0.1 fps**
  (10 s sleep) and each poll spawns a fresh ffmpeg→RTSP connection. "2 of 3 consecutive
  frames" would mean 20–30 s latency; a 60 s recording is impossible from that source.
- [KEY FINDING] No `cv2.VideoWriter` anywhere; OpenCV not installed. Recommended:
  one persistent ffmpeg per guarded camera with `tee` → detection pipe + `-c copy`
  segment ring (gives pre-roll free at ~0% CPU, one RTSP connection total).
- [KEY FINDING] Zone crop is a **free digital zoom** (crop happens before the 640
  resize): person @20 m ≈ 79 px cropped vs 47 px full-frame → reliable to ~25–30 m
  with the crop, ~15 m without. Crop is mandatory for person detection.
- [OPEN — NUC] §5 command block pending: ffmpeg presence, disk free, VAAPI, stream
  profiles, night/IR snapshot, camera distance + lens FOV, real IR class map, baseline CPU.
- [OPEN — DECISIONS] §6 contradictions raised for approval: (6.1) no capture thread to
  reuse; (6.2) MOG2 does not exist + slow-mover mitigation; (6.3) pre-roll via disk
  segments not RAM; (6.4) `camera_id` == `pedestal_id`; (6.5) MQTT topic has no stored
  `marina_id`; (6.6) define "CPU under 15%" (one core vs four).
- [NEXT] **STOP.** Await approval + §5 output before Stage B.

# Implementation Status — Plugged-aware Activate + 3 socket modes (v3.29)

## 2026-06-18 — "citaj plugged polje... tri moda upravljanja auto/active/stop... posalji dijagnozu kad se aktivira smart. dakle 1,2,3"

Three-mode per-socket model: **Auto / Activate / Stop**. Stop → Auto turns off (B6, exists). Activate → Auto also turns off (new). Auto toggle → activates Auto (exists). Firmware v3.0.0 now reports `plugged` per socket in `opta/diagnostic`; NUC must consume it so an already-inserted cable becomes actionable (Activate enabled) without waiting for a `UserPluggedIn` event. Auto-send a diagnostic request when Smart Mode is switched ON so the cabinet reports current plug state immediately.

- [DONE] **(1)** `backend/app/services/mqtt_handlers.py` `_handle_opta_diagnostic` — loop over `power` items that carry `plugged`: when `plugged:true` & no active electricity session → set `SocketState.operator_status="awaiting_activation"` (same exempt-from-15s-sweep marker as `_handle_event_user_plugged_in`); when `plugged:false` → clear that marker (only if it was `awaiting_activation`, leaving legacy pending/rejected alone). Creates SocketState with `connected=True` if missing (cabinet just answered a diagnostic → online; avoids spurious `_compute_socket_display_state` "fault"). Broadcasts `socket_state_changed` per socket. Older firmware without the field → no-op (guarded by `if "plugged" not in item`).
- [DONE] **(2)** `backend/app/routers/pedestal_config.py` `set_smart_mode` — after publishing `opta/cmd/smartmode`, when `body.value` is True also publish `opta/cmd/diagnostic {"cabinetId": <cab>, "request": "all"}` so the cabinet reports current plug state immediately on Smart Mode ON.
- [DONE] **(3)** `backend/app/routers/controls.py` `direct_socket_cmd` — B6 disable-auto block widened from `action=="stop"` to `action in ("stop","activate")`: a manual Activate now also calls `_operator_disable_auto_activate` (broadcasts `socket_auto_activate_changed` → UI Auto toggle off + toast). Three modes are mutually exclusive. (Session-approval path `approve_socket` left unchanged — scope is the Activate button.)
- [DONE] `tests/backend/test_plugged_activate.py` (NEW, 9 cases): plugged:true→awaiting_activation; plugged:false→cleared; missing field→no-op; legacy "pending" untouched on plugged:false; plugged:true+active session→no pending; Smart Mode ON publishes opta/cmd/diagnostic; Smart Mode OFF does not; manual Activate disables auto; Activate broadcasts socket_auto_activate_changed.
- [DONE] `README.md` — v3.29 changelog entry (plugged-aware Activate, diagnostic-on-ON, mutually-exclusive Auto/Activate/Stop).
- [NO CHANGE] Frontend: existing SocketCard Activate gating (`!isPending`) now enables via the diagnostic-driven `awaiting_activation`→"pending" display state; `socket_auto_activate_changed` handler already toggles Auto off + toast. No frontend file change required.
- [VERIFIED] full backend suite **539 passed** (530 + 9 new), 0 failed (2026-06-18).
- STATUS: committed to develop, pushed; **awaiting explicit approval before merge to main**.

## 2026-06-18 — "dokumentiraj ovaj dio u user guide i prema ERP APIju"

- [DONE] `scripts/generate_user_guide.py` — What's-new heading → v3.28; new 10.7 "Smart Mode — the master switch" (default OFF = standalone cabinet, ON = NUC controls; where the toggle is; resets OFF on reboot; Activate disabled when OFF) + 10.8 "Per-socket Start/Stop" (Activate gating, always-available Stop, manual-Stop-disables-Auto-activate). Regenerated `docs/User Guide.docx` (52 KB).
- [DONE] `generate_erp_integration_doc.py` — new "Prerequisite — Smart Mode must be ON" subsection in the NFC Activation API section (smart_mode field in health/opta_status, POST /smartmode endpoint, ERP guidance to check smart_mode before driving a pedestal). Regenerated `Cloud_IOT_ERP_Integration_Guide_v3.pdf` (90 KB).
- Generators + docx/pdf untracked (per earlier "c") — local artifacts, no git/release.

---

# Implementation Status — SmartMode (firmware v3.0.0) (v3.28, RELEASED 7575d62)

## 2026-06-18 — "Kreni" (SmartMode; decisions A–G confirmed; bundled with B5/B6)

SmartMode: fw v3.0.0 flag. False = Opta standalone (ignores NUC cmds, dashboard read-only); True = NUC full control. Defaults False on boot.

### Backend
- [DONE] `backend/app/models/pedestal_config.py` — `smart_mode = Column(Boolean, default=False)`.
- [DONE] `backend/app/database.py` — migration `("pedestal_configs","smart_mode","INTEGER DEFAULT 0")`.
- [DONE] `backend/app/services/mqtt_handlers.py` `_handle_marina_status` — parse `smartMode` ONLY if present in opta/status payload → persist cfg.smart_mode; include `smart_mode` in `opta_status` broadcast.
- [DONE] `backend/app/routers/pedestal_config.py` — `smart_mode` added to `GET /api/pedestals/health`; new `POST /api/pedestals/{cabinet_id}/smartmode` (require_admin, body {value:bool}) → publish `opta/cmd/smartmode {"value":bool}` + optimistic cfg.smart_mode + 404 unknown cabinet.
- [VERIFIED] smoke: smart_mode column created; /api/pedestals/{cabinet_id}/smartmode registered; app imports.
### Frontend
- [DONE] `frontend/src/store/index.ts` — `smart_mode?` on `OptaStatusInfo` + `PedestalHealth`.
- [DONE] `frontend/src/hooks/useWebSocket.ts` — opta_status handler passes `smart_mode` to setOptaStatusInfo.
- [DONE] `frontend/src/api/pedestalConfig.ts` — `setSmartMode(cabinetId, value)` + smart_mode on PedestalHealth type.
- [DONE] `frontend/src/components/pedestal/PedestalControlCenter.tsx` — new `SmartModeControl` (distinct emerald/amber card + switch + exact OFF/ON text) rendered above Cabinet Status (only when opta_client_id); optimistic toggle reverts on failure; live from optaStatusInfo, hydrate from health. SocketCard gains `smartMode` prop → Activate disabled + tooltip "Enable Smart Mode to activate sockets." when off. `tsc --noEmit` clean.
### Tests
- [DONE] `tests/backend/test_smartmode.py` (9) — status true/false/absent(preserve), opta_status broadcast includes smart_mode, POST true/false publishes opta/cmd/smartmode + returns, missing-auth 401/403, unknown cabinet 404, health includes smart_mode.
- [VERIFIED] full backend suite **530 passed** (521 + 9 SmartMode), tsc clean — no regressions.
- [DONE] `README.md` — v3.28 SmartMode changelog entry (alongside B5/B6).
- RELEASE: user approved "merge i push na main" — SmartMode + B5/B6 commits → develop → main (one release).

---

# Implementation Status — B5 activate dedup + B6 manual-stop auto-disable (v3.28, RELEASED-PENDING)

## 2026-06-18 — "Kreni. B5 prvo, zatim B6" (decisions A–E all confirmed)

Decisions: A) B5 dedup in `_maybe_auto_activate`, key `{pid}-{sid}`, 3.0s window (time.monotonic), cleared on SessionEnded. B) B6 auto-disable only in stop_session + direct_socket_cmd stop (NOT shared _publish_session_control → ERP stop + autostop excluded). C) B6 electricity Q1–Q4 only. D) new WS event `socket_auto_activate_changed`. E) toast "Auto-activate disabled for Q{n}. Re-enable in socket settings." (info, dismissable).

### B5 — duplicate activate dedup
- [DONE] `backend/app/services/mqtt_handlers.py` — `import time`; module `_last_activate_ts: dict[str,float]` + `_ACTIVATE_DEDUP_WINDOW_S=3.0`; in `_maybe_auto_activate` before publish: skip+warn+log if an auto-activate for `{pid}-{sid}` was published <3s ago, else record `time.monotonic()`; `_handle_event_session_ended` clears the entry. Operator manual activate (direct_socket_cmd) unaffected (separate publish).
### B6 — manual stop disables auto-activate
- [DONE] `backend/app/routers/controls.py` — new `_operator_disable_auto_activate(db,pid,sid)` (sets SocketConfig.auto_activate=False if True, broadcasts `socket_auto_activate_changed`, idempotent no-op if already off). Called in `stop_session` (electricity only) and `direct_socket_cmd` (action=="stop"), BEFORE publish. NOT in shared `_publish_session_control` → ERP stop + autostop excluded.
- [DONE] `frontend/src/hooks/useWebSocket.ts` — case `socket_auto_activate_changed` → `setSocketAutoActivate(pid,sid,false)` + dismissable info toast "Auto-activate disabled for Q{n}. Re-enable in socket settings." (setSocketAutoActivate added to destructure). `tsc --noEmit` clean.
### Tests
- [DONE] `tests/backend/test_activate_dedup.py` (B5, 5): two rapid→one publish; cleared on SessionEnded→reactivate; different sockets independent; window boundary 2.9s skip / 3.1s publish; operator manual activate not blocked.
- [DONE] `tests/backend/test_manual_stop_autodisable.py` (B6, 5): operator stop disables; broadcasts socket_auto_activate_changed; direct stop disables + idempotent; ERP stop does NOT disable; after disable UserPluggedIn does not auto-activate.
- [DONE] `tests/backend/test_meter_load.py` (+1): autostop sets latch but does NOT disable auto_activate.
- [VERIFIED] full backend suite **521 passed** (510 + 11 new), tsc clean — no regressions.
- [DONE] `README.md` — v3.28 changelog (B5 + B6, firmware note).
- NEXT: commit dev + push dev (gate); STOP before main for explicit approval.

---

# Implementation Status — ACK-confirmed LED status (v3.27, RELEASED ec36709)

## 2026-06-16 — "kreni" (single white LED; UI flips to ON only on ACK)

Decisions: single-colour LED (color irrelevant) → ON/OFF; status flips to ON only on opta/cmd/led ACK (until then "switching…"); state on PedestalConfig; per-command confirmation (periodic = future firmware opta/led/status).

### Backend
- [DONE] `backend/app/models/pedestal_config.py` — `led_on` (Bool), `led_pending` (Bool), `led_confirmed_at` (DateTime).
- [DONE] `backend/app/database.py` — migrations: led_on/led_pending (INTEGER DEFAULT 0), led_confirmed_at (DATETIME).
- [DONE] `backend/app/routers/controls.py` — POST /pedestal/{id}/led: persist intended led_on + led_pending=True (cabinets) / confirmed-now (legacy no-ACK); broadcast led_changed {on, confirmed:false}. NEW GET /pedestal/{id}/led (require_any_role) for hydration.
- [DONE] `backend/app/services/mqtt_handlers.py` `_handle_marina_acks` — on cmd_topic endswith "cmd/led": clear led_pending, stamp led_confirmed_at if status ok, broadcast led_changed {on, confirmed:<ok>, source:"ack"}.
- [VERIFIED] app imports; GET+POST /api/controls/pedestal/{id}/led registered.
### Frontend
- [DONE] `frontend/src/api/index.ts` — `getLed(pedestalId)`.
- [DONE] `frontend/src/store/index.ts` — `ledStates` (per pedestal {on,pending,confirmedAt}) + `setLedState` (prev-merge).
- [DONE] `frontend/src/hooks/useWebSocket.ts` — `led_changed` now drives ledStates (pending on command, confirmed on ACK; absent confirmed ⇒ confirmed) + keeps scheduler toast.
- [DONE] `frontend/src/components/pedestal/PedestalControlCenter.tsx` — `LedControl` rewritten: single white LED, Turn ON / Turn OFF buttons, badge ON / OFF / "Switching…" driven by ACK-confirmed store state, hydrates via getLed on mount; removed color picker + blink. `tsc --noEmit` clean.
### Tests
- [DONE] `tests/backend/test_led_status.py` (4) — command marks pending; ACK confirms; off→ack; failed ACK clears pending without confirming. All pass.
- NEXT: full suite regression check; then commit dev + push dev; STOP before main for approval.

---

# Implementation Status — NFC docs (user manual + ERP/API guide, v3.26)

## 2026-06-16 — "popravi sad user manual i API dokument" (NFC docs)

- [DONE] `scripts/generate_user_guide.py` — 5.3 "QR Codes"→"Socket Settings (QR/NFC)"; What's new →v3.26; new 10.6 "NFC provisioning & ERP activation" (mode switch + auto-activate flip, provisioning steps, scan→plug-in flow, operator override). Regenerated `docs/User Guide.docx` (51 KB).
- [DONE] `generate_erp_integration_doc.py` — TOC entry + H1 "NFC Activation API (myMarina ERP)": X-API-Key auth, operator-side provisioning, endpoints table, activation flow, payloads, status codes, optional webhook, operator-override note. Regenerated `Cloud_IOT_ERP_Integration_Guide_v3.pdf` (89 KB).
- Generators + PDFs/docx are untracked (per earlier "c") — local doc artifacts, no git/release.

---

# Implementation Status — NFC provisioning + ERP NFC integration (v3.26, RELEASED decad6d)

## 2026-06-16 — "Go ahead. Kreni od koraka 1" (step 1: models, migrations, config)

Approved decisions: (1) NFC pending = one-shot activate on UserPluggedIn; (2) new `sessions.nfc_user_id` TEXT (ERP user is a string, customer_id stays Integer); (3) X-API-Key from .env (`ERP_API_KEY`); (4) berth_id = `pedestal_configs.berth_ref`; (5) nfc tables in pedestal.db; (6) `provisioning_mode` on pedestal_configs; (7) separate `erp_webhook.py` → `ERP_WEBHOOK_URL`; (8) estimated_cost from global BillingConfig.kwh_price_eur; (9) NFC→QR restores all 4 auto_activate=True; (10) column default 'qr', UI lists NFC first; (11) Socket Settings restructures QrCodesSection in PedestalControlCenter.

Build order: 1 models/migrations/config → 2 nfc_service + require_erp_api_key → 3 nfc router + main wiring → 4 mqtt hooks → 5 erp_webhook + telemetry/end → 6 provisioning_mode PATCH (auto_activate flip) → 7 frontend → 8 tests → 9 README + release (STOP before main push).

### Step 1 — models, migrations, config
- [DONE] `backend/app/models/nfc_tag.py` (NEW) — `NfcTag` (id, nfc_tag_id unique, cabinet_id, socket_id "Qn", provisioned_at, provisioned_by, is_active). pedestal.db. Invariants documented (global-unique tag, one active tag per socket) — enforced in nfc_service.
- [DONE] `backend/app/models/nfc_pending_session.py` (NEW) — `NfcPendingSession` (id, nfc_tag_id, user_id string, cabinet_id, socket_id "Qn", created_at, expires_at, status pending|activated|expired) + index (cabinet_id, socket_id, status). Lazy-expiry documented. pedestal.db.
- [DONE] `backend/app/models/session.py` — added `nfc_user_id` (String(128), nullable). Separate from Integer customer_id.
- [DONE] `backend/app/models/pedestal_config.py` — added `provisioning_mode` (String, default "qr").
- [DONE] `backend/app/database.py` — init_db imports nfc_tag + nfc_pending_session (tables auto-create); migrations added: `("sessions","nfc_user_id","TEXT")`, `("pedestal_configs","provisioning_mode","TEXT DEFAULT 'qr'")`.
- [DONE] `backend/app/config.py` — added `erp_api_key`, `erp_webhook_url` (Optional[str]=None).
- [DONE] `backend/.env` — added ERP_API_KEY / ERP_WEBHOOK_URL (empty = feature off).
- [VERIFIED] smoke test (temp DB): nfc_tags + nfc_pending_sessions created; provisioning_mode on pedestal_configs; nfc_user_id on sessions. ✅ Step 1 COMPLETE.
### Step 2 — X-API-Key dependency + nfc_service
- [DONE] `backend/app/auth/erp_api_key.py` (NEW) — `require_erp_api_key` (Header X-API-Key vs settings.erp_api_key; 503 if not configured, 401 missing/invalid, hmac compare).
- [DONE] `backend/app/services/nfc_service.py` (NEW) — provisioning: `provision_tag` (global-unique check → DuplicateNfcTagError(cabinet,socket); replaces active tag on same socket; reactivates same tag), `remove_tag` (is_active=False), `list_tags`, `get_active_tag_for_socket`, `get_active_tag_by_id`; pending: `create_pending` (5-min TTL), `get_live_pending` + `expire_if_past` (lazy expiry, mark stale → "expired"). PENDING_TTL_MINUTES=5.
### Step 3 — nfc router + main wiring
- [DONE] `backend/app/services/nfc_service.py` — added `build_session_payload(db, user_db, session)` (cabinet/socket/customer=nfc_user_id/status/duration/energy/power/estimated_cost via global BillingConfig). Shared by GET + webhook.
- [DONE] `backend/app/routers/nfc.py` (NEW) — admin (require_admin): GET /tags/{cabinet_id}, POST /tags, POST /tags/bulk (Save All, pre-validates in-batch dup), DELETE /tags/{cabinet_id}/{socket_id}. ERP (require_erp_api_key): POST /scan (404 tag/ped, 503 fault, 409 active OR live-pending, else create pending → 200 payload w/ berth_ref), GET /session/{id} (404), POST /session/{id}/stop (404, 409 if not active = already ended by operator, else complete + _publish_session_control stop). Does NOT activate on /scan.
- [DONE] `backend/app/main.py` — import + include `nfc_router` after qr_router (before /api/ext catch-all).
- [VERIFIED] app imports clean; 7 /api/nfc routes registered. ✅ Step 3 COMPLETE.
### Step 4 — MQTT NFC hooks
- [DONE] `backend/app/services/mqtt_handlers.py` `_handle_event_user_plugged_in` — resolve cabinet_id; `nfc_service.get_live_pending` (lazy-expire); if valid → mark record "activated" + fire `_maybe_auto_activate` (one-shot, regardless of auto_activate) + skip auto path; elif auto_activate → existing; else log "activation blocked" (NFC mode no pending).
- [DONE] `_handle_event_outlet_activated` — attach NFC user: find most recent "activated" NfcPendingSession for cabinet/socket within 10-min window → set `session.nfc_user_id`; add nfc_user_id to session_created broadcast.
- [VERIFIED] imports clean. ✅ Step 4 COMPLETE.
### Step 5 — ERP webhook
- [DONE] `backend/app/services/erp_webhook.py` (NEW) — `build(db, session, event)` (sync, returns None if ERP_WEBHOOK_URL unset; payload = build_session_payload + event), `post_erp_event(payload)` (async httpx POST, X-API-Key header, never raises), `should_send_telemetry` (60s throttle per session), `mark_ended` (de-dupe ended across paths).
- [DONE] `backend/app/services/mqtt_handlers.py` — fired webhook at: OutletActivated ("session_activated"), TelemetryUpdate ("telemetry", 60s-throttled), SessionEnded ("session_ended", mark_ended), UserPluggedOut ("session_ended", de-duped). All electricity-only, fire-and-forget via asyncio.create_task; payload built sync while db open.
- NOTE: auto-stop overload completion relies on Opta echoing SessionEnded to fire the ended webhook (publishes stop → SessionEnded). Covered there.
- [VERIFIED] app + erp_webhook import clean. ✅ Step 5 COMPLETE.
### Step 6 — provisioning mode + auto_activate flip
- [DONE] `backend/app/routers/nfc.py` — `GET /api/nfc/mode/{cabinet_id}` + `PATCH /api/nfc/mode/{cabinet_id}` (body {mode: qr|nfc}); sets PedestalConfig.provisioning_mode and flips auto_activate on ALL the cabinet's socket_configs (nfc→False, qr→True). Returns sockets_updated.
- [VERIFIED] 8 /api/nfc routes registered. ✅ Step 6 COMPLETE (backend steps 1-6 done).
### Step 8 (backend portion) — tests
- [DONE] `tests/backend/conftest.py` — register nfc_tag + nfc_pending_session models so test DBs create the tables.
- [DONE] `tests/backend/test_nfc.py` (NEW, 21 tests) — provisioning (store/duplicate-409-with-owner/replace/remove/bulk), mode flip (nfc→auto False, qr→auto True), scan (pending+berth_ref / 404 / 401 missing+invalid / 409 active / 503 fault / 409 second-scan / expired→new), session API (GET fields incl nfc_user_id, 401, 404), stop (200 ended, 409 already-ended, 401).
- [DONE] `tests/backend/test_nfc_mqtt.py` (NEW, 8 tests) — UserPluggedIn: valid pending→one-shot activate + mark activated; expired→block+mark expired; NFC-mode no-pending→block; QR-mode→auto-activate unchanged. OutletActivated attaches nfc_user_id. Webhook fires on activate when URL set / not when unset / post_erp_event swallows errors.
- [VERIFIED] full backend suite **506 passed** (no regressions; operator_approval, meter_load, auto_activate, workflow all green).
### Step 7 — frontend
- [DONE] `frontend/src/api/nfc.ts` (NEW) — own axios instance; listNfcTags, provisionNfcTag, provisionNfcTagsBulk, removeNfcTag, getProvisioningMode, setProvisioningMode; ProvisioningMode + NfcTag types.
- [DONE] `frontend/src/components/pedestal/NfcProvisioningTable.tsx` (NEW) — per-socket rows (live status from socketComputedStates, tag input, Provision/Remove), Save All, summary; duplicate/error surfaced via onFeedback from backend 409 detail.
- [DONE] `frontend/src/components/pedestal/PedestalControlCenter.tsx` — `QrCodesSection` → "Socket Settings": NFC/QR radio (NFC listed first, reflects saved mode), confirm + warning on NFC switch, setProvisioningMode + reflect auto_activate flip via setSocketAutoActivate(1..4); QR branch = existing SocketQrGrid (unchanged) + Download/Regenerate (QR only); NFC branch = NfcProvisioningTable.
- [VERIFIED] `npx tsc --noEmit` clean. ✅ Step 7 COMPLETE.
### Step 9 — README + release (develop)
- [DONE] `README.md` — v3.26 changelog entry (NFC provisioning, ERP API, webhook, auto_activate flip, lazy expiry, operator override, QR unchanged).
- [DONE] Commit `962ea99` on develop; pushed `origin/develop` — full pre-push gate GREEN (backend 506 + linters + GAP checks; Playwright skipped, backend not on :8000).
- ⏸ STOPPED before main push (per instruction). `origin/main` = 2238dc8 (unchanged). AWAITING explicit approval to merge develop→main + release push (CLOUD_IOT_RELEASE=1). On release: fill the README changelog commit hash. Feature COMPLETE on develop.

---

# Implementation Status — Manual activate (auto-OFF) plug-in stays actionable

## 2026-06-15 — "kreni" (Control Center Activate; decision: pending until activate/unplug, no 15s auto-reject)

- Problem: auto-activate OFF → user plugs in → Control Center "Activate" greyed out / not working. Root cause: modern Opta `opta/events {UserPluggedIn}` → `_handle_event_user_plugged_in` broadcast computed="pending" once, but persisted NOTHING; `_compute_socket_display_state` only knew about sessions, so the next periodic `opta/sockets idle` poll (~15s) reverted display to "idle" → `Activate` button (`disabled={!isPending}`) greyed out. (The legacy `pedestal/.../socket/status "connected"` flow set operator_status="pending" and was subject to a 15s auto-reject sweep; modern flow set neither.)
- Fix (`backend/app/services/mqtt_handlers.py`):
  - `_handle_event_user_plugged_in`: persist `SocketState.operator_status = "awaiting_activation"` (distinct from legacy "pending") when no active session. Distinct marker so the 15s pending auto-reject sweep (targets `=="pending"`) does NOT cancel it → stays actionable until activate/unplug (per user decision).
  - `_compute_socket_display_state`: return "pending" when operator_status in ("pending","awaiting_activation") and no session → keeps Activate enabled across idle polls.
  - `_handle_event_outlet_activated` + `_handle_event_user_plugged_out`: clear operator_status (electricity) on activate / plug-out.
  - `backend/app/routers/controls.py` `_get_socket_state_or_400`: accept "awaiting_activation" too (also fixes pedestal-image popup Approve).
- [DONE] tests: `tests/backend/test_operator_approval.py` TC-OA-09/10/11 (compute→pending, sweep does NOT reject awaiting_activation, approve accepts it). Legacy TC-OA-01..08 unchanged/green. Ran approval+meter+workflow = 85 passed.
- Point 3 (connected semantics: idle status forces connected=True so "no plug" guard is inert) deliberately deferred — separate.
- MERGE: bundled with hydration + socket-panel fixes below (one develop→main release).

---

# Implementation Status — Hardware-config hydration from REST (Awaiting… fix)

## 2026-06-15 — "ok riješi ovo" (bundled into same merge as socket-panel fix)

- Problem: "Awaiting hardware configuration from device" persisted on any dashboard opened AFTER the Opta boot. Cause: `socketHardwareConfig.hw_config_received_at` was fed ONLY by the one-shot `hardware_config_updated` WS event (Opta boot); the initial `getSocketLoad` REST fetch returns meter_type/phases/rated_amps/hw_config_received_at but the panel discarded them (called setLoadState only, never setHardwareConfig). Backend already had the config (now also retained per latest firmware trace), so it was purely a frontend hydration gap.
- [DONE] `frontend/src/components/pedestal/SocketLoadMeterPanel.tsx` — initial fetch now also calls `setHardwareConfig(pedestalId, socketId, {meter_type, phases, rated_amps, modbus_address, hw_config_received_at})` from the same REST payload; added `setHardwareConfig` selector + dep. Clears "Awaiting…" on every load when the backend has the config; stays "Awaiting…" correctly when it genuinely doesn't (hw_config_received_at null).
- [VERIFIED] `npx tsc --noEmit` → clean.
- MERGE: bundled with the socket-panel breaker/fault fix below (both frontend, one develop→main release → NUC `cloud-iot upgrade`).

---

# Implementation Status — Socket detail panel reflects breaker/fault (UI fix)

## 2026-06-15 — "kreni, medium, bez reset gumba"

- Problem: clicking a socket on the pedestal image opened `SocketDetailPanel`, whose state logic used only sessions → a breaker-tripped or fault socket fell into the "Idle / No device connected" branch (misleading, despite the ⚡ marker on the circle). Command Center already shows breaker/fault; popup did not.
- [DONE] `frontend/src/components/pedestal/PedestalView.tsx` → `SocketDetailPanel`:
  - Pull `socketComputedStates`, `socketBreakerStates`, `socketLoadStates`, `socketHardwareConfig` from store.
  - Derive `breakerTripped` / `isFault` / `loadState` / `hwConfig` (per `${pid}-${sid}`).
  - Header dot+badge: red "Breaker Tripped" / "Fault" take precedence over active/pending/idle.
  - New red panels: breaker-tripped (Qn, rated A, Stop if admin+active) and fault.
  - Active panel enriched with Voltage / Current / Power factor from `socketLoadStates`.
  - Idle no longer bare: shows Breaker / Meter / Rated A info line when known. All existing branches guarded with `!breakerTripped && !isFault`.
- [VERIFIED] `npx tsc --noEmit` → clean. No reset button (per decision B). Camera zone unaffected (returns null earlier).
- NEXT: STOP for approval before commit/push (frontend → NUC `cloud-iot upgrade` rebuild).

---

# Implementation Status — TME /fresh.xml support (field fix)

## 2026-06-14 — "kreni" (field: TME at 192.168.1.254 returns 404 on /values.xml; serves /fresh.xml)

- Root cause: older Papouch TME firmware (cabinet MAR_KRK_ORM_01) serves `/fresh.xml`, not `/values.xml` (404). Format: `<sns ... unit="0" val="285" .../>` where val = temp×10 (285→28.5°C), unit 0/1/2=C/F/K. Old parser only matched `<v>` element on /values.xml → sensor never discovered/read despite being pingable.
- [DONE] `backend/app/services/discovery.py` — `check_tme_sensor()`: added `/fresh.xml` fallback after `/values.xml` fails; parses `val=`/`unit=` attributes, temperature=int(val)/10, unit map; guarded on `papouch.com/xml/TME` xmlns to avoid false positives. `read_tme_temperature()` reuses it (poll + scan both benefit). Docstring updated.
- [VERIFIED] parser on real device sample → 28.5 °C, unit C, guard True.
- [DONE] `tests/backend/test_tme_fresh_xml.py` (NEW) — 4 tests: fresh.xml parse (28.5°C/C), read_tme via fresh.xml, values.xml no-regression (23.5°C), unrecognised→None. All pass. Targeted suite 47 passed.
- NEXT: commit develop → merge main → push (approved "push, s testom"); then NUC `cloud-iot upgrade` + manual IP entry 192.168.1.254.

---

# Implementation Status — ERP Integration Guide v3 (MarinaMaster MVP)

## 2026-06-14 — "kreni" (A new H1 MVP section, B output to _v3.pdf, C curl examples, D keep rest)

- [DONE] `generate_erp_integration_doc.py` — OUTPUT_PATH → `Cloud_IOT_ERP_Integration_Guide_v3.pdf` (v2 untouched).
- [DONE] `generate_erp_integration_doc.py` — TOC: added "MVP Pilot — First Integration Set" entry.
- [DONE] `generate_erp_integration_doc.py` — NEW H1 "MVP Pilot — First Integration Set" after Quick-Start (no renumber): 3 use cases (temperature push-only `temperature_reading`; berth occupancy pull `berths.occupancy_ext` + push `berth_occupancy_updated`; camera per berth via NUC `camera.stream_ext`/`camera.frame_ext`), accurate payloads/curl, per-pedestal-camera note, enablement checklist table, "what success unlocks" note.
- [DONE] `generate_erp_integration_doc.py` — §9.4 temperature_reading: replaced ">50°C" with TME bands table (45/60/0/-10, 1° hysteresis) + new fields severity/alarm/temp_sensor_reachable/last_temp_sensor_check; noted push-only.
- [DONE] `generate_erp_integration_doc.py` — §6: added 6.5 Berth Occupancy & Camera (Marina View) pull flows + toggles note.
- [DONE] Regenerated `Cloud_IOT_ERP_Integration_Guide_v3.pdf` (84 KB) via backend/.venv.
- NOTE: generator is untracked (per earlier "c" — don't commit doc generators); PDF is a build artifact. No git changes.

---

# Implementation Status — Active Alarms panel (v3.24)

## 2026-06-14 — "idi s preporukama" (D1 SystemHealth, D2 null→red, D3 WS+fetch+30s poll, D4 admin-only)

- [DONE] `backend/app/routers/alarms.py` — AlarmResponse + severity + resolved_at.
- [DONE] `frontend/src/api/alarms.ts` (NEW) — AlarmRecord + getActiveAlarms + acknowledgeAlarm.
- [DONE] `frontend/src/store/index.ts` — activeAlarms + setActiveAlarms/upsert/remove (+ AlarmRecord import).
- [DONE] `frontend/src/hooks/useWebSocket.ts` — alarm_triggered (upsert) / alarm_acknowledged / alarm_resolved (remove).
- [DONE] `frontend/src/components/system/ActiveAlarmsPanel.tsx` (NEW) — admin-only list, severity color, Ack; initial fetch + 30s poll; live via WS.
- [DONE] `frontend/src/pages/SystemHealth.tsx` — render <ActiveAlarmsPanel/> in the alarms area.
- [DONE] tests: /api/alarms/active returns severity (test_temp_alarm.py); ws_event_catalog guard recognises alarm_* dynamic broadcasts. Suite 470 passing; tsc clean.
- [DONE] README v3.24.
- NEXT: commit + push dev; STOP for approval before main. (v3.23 + v3.24 both on develop; merge together.)

---

# Implementation Status — TME temperature range alarms (v3.23)

## 2026-06-14 — Approved "idi s preporukama" (D1a severity col, D2a auto-resolve+hysteresis, D6 offline warning, D3 fixed 45/60/0/-10, D5 30s, D8 live temp on card)

- [DONE] `backend/app/models/active_alarm.py` — added `severity` + `resolved_at`; status now triggered|acknowledged|resolved.
- [DONE] `backend/app/database.py` — migration: active_alarms.severity, active_alarms.resolved_at.
- [DONE] `backend/app/services/alarm_service.py` — `trigger_alarm(severity=...)` + in-place escalate/de-escalate (no dup); new `has_active_alarm`, `resolve_alarm_type`; severity+resolved_at in broadcast.
- [DONE] `backend/app/services/temp_alarm.py` (NEW) — constants (45/60/0/-10, 1° hysteresis) + pure `evaluate_temp_band` + `threshold_for`.
- [DONE] `backend/app/services/discovery.py` — `read_tme_temperature()` (single-host HTTP read).
- [DONE] `backend/app/main.py` — `_temp_sensor_poll()` (30s; reachability + reading + range alarm + auto-resolve + offline warning); registered/cancelled in lifespan; temperature_reading WS now carries severity+alarm.
- [DONE] `tests/backend/test_temp_alarm.py` (NEW, 19) — band/hysteresis + alarm severity/escalate/resolve. Full suite 450 → 469 passing.
- [DONE] `frontend/src/store/index.ts` — SensorReading.severity.
- [DONE] `frontend/src/hooks/useWebSocket.ts` — store severity from temperature_reading.
- [DONE] `frontend/src/components/config/DevicesPanel.tsx` — live reading on TME card (gray/yellow/red) + threshold legend. tsc OK.
- [DONE] `README.md` — v3.23 changelog.
- NOTE: no generic ActiveAlarm panel exists in the dashboard yet (pre-existing gap) — temperature alarms are raised/auto-resolved + on WS/REST, but a full alarm-list UI is a separate follow-up.
- NEXT: commit + push dev; STOP for approval before main.

---

# Implementation Status — Backend bug-fix bundle B1–B4 (v3.21)

## 2026-06-14 — Four firmware-independent backend fixes

Approved design decisions: D1 clamp display+audit only (no overload/billing change);
D2 keep `meter_power_kw` as clamped, add `meter_power_kw_raw`; D3 single-phase formula
without PF, three-phase with PF; D4 B2 resolver in backend via existing
`socket_state_changed` (no frontend change); D5 REST fault = `breaker_state=="tripped"`
OR `SocketState.connected==False`; D6 diagnostic `status` field on all responses;
D7 v3.21, commit+push dev then STOP for approval before main.

Files — Status:
- [DONE] `backend/app/services/mqtt_handlers.py` (B1) — added `_recover_truncated_hwconfig()`
  helper (bracket-matched sockets-array recovery, string-aware) and wired it into
  `_handle_opta_hardware_config` tolerant-parse path; logs truncation + bytes dropped +
  "valves not recovered"; existing `hw_config_received_at` stamping already covers the
  partial-parse timestamp requirement. (B2 + B4 edits to this same file still pending.)
- [DONE] `backend/app/services/mqtt_handlers.py` (B2) — added `_compute_socket_display_state()`
  (fault>active>pending>idle; fault = msg fault OR breaker_state tripped OR SocketState.connected
  False); `_handle_marina_socket` now resolves it in-session and emits `socket_state_changed`
  via the existing `_broadcast_socket_state` (no frontend change). 
- [DONE] `backend/app/services/mqtt_handlers.py` (B4) — added `_sanity_clamp_power_kw()` (D3:
  no PF single-phase, PF three-phase; skip when V or I = 0; clamp when reported > 50x computed,
  logs both values); `_handle_opta_meter_telemetry` stores raw → `meter_power_kw_raw` and
  clamped → `meter_power_kw`. (mqtt_handlers.py fully done: B1+B2+B4; py_compile OK.)
- [DONE] `backend/app/models/socket_config.py` (B4) — added `meter_power_kw_raw` Float column.
- [DONE] `backend/app/database.py` (B4) — added `("socket_configs","meter_power_kw_raw","REAL")`
  migration.
- [DONE] `backend/app/routers/meter_load.py` (B2+B4) — `serialize_load_state(cfg, db=None)`:
  added `power_kw_raw` always, and `display_state` when db provided (reuses
  `_compute_socket_display_state`); `get_socket_load`/`get_pedestal_load`/`patch_thresholds`
  now pass db. ext ERP twin left db=None (no badge needed).
- [DONE] `backend/app/routers/diagnostics.py` (B3) — Opta timeout returns all_ok=False,
  status="unknown", error "No diagnostic response received from device" (no cached synthesis);
  added `status` (ok/fault/unknown) to all responses incl. legacy path.
- All modified backend files py_compile OK.
- [DONE] `backend/app/routers/diagnostics.py` (B3 testability) — added module-level
  `import asyncio` + `_await_diag_event()` seam (replaces in-function wait_for) so the
  diagnostic wait is patchable without touching the global loop.
- [DONE] `tests/backend/test_v321_backend_fixes.py` (NEW) — 22 tests covering B1 (7:
  complete JSON, truncated recovers 4 sockets, warning logged, bytes-dropped logged,
  hw_config_received_at set, unrecoverable case, awaiting-config clears), B2 (7: hw-fault
  precedence, breaker-tripped precedence, hw-ok→active, WS broadcast, REST response,
  internal session untouched), B3 (3: timeout→unknown/no-synthesis, fresh ok, fresh fault),
  B4 (6: clamp fires+logs, raw alongside clamped, no-clamp on zero V, no-clamp within 50x,
  3-phase PF clamp, REST exposes power_kw_raw). Reuses test_meter_load harness + conftest
  client. Auto-included by tests/run_tests.sh (globs tests/backend/).
- [DONE] Full backend suite: 448 passed, 0 failures (was 426; +22).
- [DONE] `README.md` — v3.21 changelog entry (B1–B4, backend-only, outstanding firmware list).
- [DONE] v3.21 committed da1602e + pushed origin/develop.

## B3b — honest diagnostic sensor mapping (follow-up, user-requested)
Root cause found by tracing UI DiagnosticsModal → /diagnostics/run → _handle_opta_diagnostic:
temperature/moisture were hard-wired to "ok" from `mqtt=="connected"` (cabinet has no
such sensors) → phantom green; UI passCount also counted failures as "passed".
- [DONE] `backend/app/services/mqtt_handlers.py` (_handle_opta_diagnostic) — temp/moisture/
  camera → "missing" (no fabrication).
- [DONE] `backend/app/routers/diagnostics.py` — all_ok/status computed over PRESENT sensors
  only (sockets+water); missing sensors neither pass nor block.
- [DONE] `frontend/src/components/config/DiagnosticsModal.tsx` — passCount counts only "ok";
  banner shows passCount/presentCount "sensors OK"; missing chip relabeled "N/A".
- [DONE] tests: +2 in test_v321_backend_fixes.py (handler marks temp/moisture/camera missing;
  present-based all_ok ignores missing). Suite 448 → 450 passing.
- ALL FILES COMPLETE (B1–B4 + B3b). v3.21 released to main (a16a5a6).

## v3.22 — TME temperature sensor configuration UI (frontend-only)
User request: add/configure Papouch TME temp sensor from UI; scan missed it at
192.168.1.254:80. Root cause of scan miss: get_local_subnet() (discovery.py) detects
the subnet via the route to 8.8.8.8 → on a multi-homed NUC that returns the 5G WAN
subnet, not the 192.168.1.x marina LAN → scan probes the wrong /24.
- [DONE] `frontend/src/components/config/DevicesPanel.tsx` — new "🌡️ Temperature Sensor
  — Papouch TME" card (IP/port/protocol/status/last-check); scanResult widened to
  ScanAllResult; renders discovered temp_sensors with Assign; optional "Subnet to scan"
  input (passes the existing backend subnet param); save sends temp_sensor_* (empty IP
  clears the sensor). `tsc --noEmit` OK. No backend change (API + discovery already
  supported it).
- NEXT: commit + push dev; STOP for approval before main.

---

# Implementation Status — Fix `cloud-iot upgrade` venv corruption on Python 3.14 (v3.20)

## 2026-06-13 — NUC upgrade-tooling fix (post-incident)

Context: deploying v3.19 to the NUC, `sudo cloud-iot upgrade` gutted the venv
(pip + uvicorn gone → crash loop). Root cause: the CLI's `upgrade` path did
`rm -rf .venv` with no recreation, installed strict pins with no cp314 wheels,
and restarted on pip failure. Recovered by hand (relaxed-pin venv rebuild);
this entry is the permanent fix.

Files:
- `nuc_image/cloud-iot` (NEW) — management CLI extracted to a version-controlled
  standalone file. Fixed `upgrade`: recreate venv only if pip missing; detect
  Python version + relax numpy/pydantic/scikit-learn/Pillow pins on ≥3.13;
  `pip install --prefer-binary`; abort (no restart) on pip failure. `bash -n` OK.
- `nuc_image/ubuntu-install-26.04.sh` — replaced embedded CLI heredoc with
  `install -m 0755 "${REPO_DIR}/nuc_image/cloud-iot" ...`. `bash -n` OK.
- `nuc_image/ubuntu-install.sh` — same replacement. `bash -n` OK.
- `README.md` — v3.20 changelog entry.
- ISO firstboot overlay CLI left as-is (no `upgrade` command, unaffected).

STATUS: complete + validated locally. AWAITING APPROVAL to commit + push to main.
NUC deploy after merge: `git -C ~/Cloud_IOT pull origin main` then
`sudo cp ~/Cloud_IOT/nuc_image/cloud-iot /usr/local/bin/cloud-iot`.

---

# Implementation Status — TOTP 2FA with OTP Fallback (v3.19)

## Session started: 2026-06-13

Feature: TOTP (authenticator-app) two-factor as the primary second factor, with
the existing email/log OTP preserved as an always-available, user-selectable
fallback. Partial-token two-step login. TOTP setup is admin-only.

**Approved design decisions (2026-06-13):**
- D1 — 2FA stays MANDATORY. No operator ever gets a JWT without a second factor.
- D2 — totp_enabled=False → /login auto-sends OTP + returns partial token (today's UX).
       totp_enabled=True → chooser screen; user requests OTP on demand.
- D3 — TOTP setup is ADMIN ONLY. Monitors use OTP fallback only.
- D4 — Keep legacy /verify-otp working; add new partial-token /otp/login alongside.
- D5 — Partial token travels in the JSON body.
- D6 — DB-based lockout (5 fails → 15 min) is ALWAYS-ON (all environments).
- D7 — TOTP setup UI = new panel in admin Settings.

**Files — Status** (append after every file):
- [DONE] `backend/requirements.txt` — added `pyotp==2.9.0` (qrcode[pil] already present); installed into venv.
- [DONE] `backend/app/auth/models.py` — added 5 User columns: totp_secret(String64,null), totp_enabled(Bool,default False), totp_verified_at(DateTime,null), totp_failed_attempts(Int,default 0), totp_locked_until(DateTime,null).
- [DONE] `backend/app/auth/user_database.py` — 5 idempotent migration tuples on `users` for existing DBs.
- Phase 1 (deps + model + migration) COMPLETE.
- [DONE] `backend/app/auth/tokens.py` — added create_partial_token() (role 'totp_pending', 5-min) + decode_partial_token(); partial token cannot pass _get_current_user.
- [DONE] `backend/app/auth/totp_service.py` (NEW) — pyotp secret/URI/QR-base64/verify(valid_window=1) + shared always-on lockout helpers (5 fails → 15 min).
- [DONE] `backend/app/auth/schemas.py` — PartialLoginResponse, TotpSetupResponse, TotpCodeRequest, TotpDisableRequest, TotpStatusResponse, PartialTokenCodeRequest, OtpRequestRequest, OtpRequestResponse.
- Phase 2 COMPLETE.
- [DONE] `backend/app/routers/totp.py` (NEW) — /totp/setup, /totp/verify-setup, /totp/disable, /totp/status (admin/any-role), /totp/login, /otp/request, /otp/login (partial-token, lockout-guarded, rate-limited).
- [DONE] `backend/app/routers/auth.py` — /login now returns partial-token response (mandatory 2FA, D1); auto-sends OTP when totp_enabled=False (D2). Legacy /verify-otp unchanged (D4).
- [DONE] `backend/app/main.py` — registered totp_router.
- Phase 3 (backend endpoints) COMPLETE.
- [DONE] `tests/backend/test_totp.py` (NEW, 24 tests) — setup/verify/disable/status, partial-token login (TOTP+OTP), clock-drift, single-use, expiry, lockout (5→15min, shared), partial-token endpoint isolation. Full suite 404 → 426 passing, 0 failures.
- Backend COMPLETE + tested.
- [DONE] `frontend/src/api/auth.ts` — PartialLoginResponse/Totp* types; authLogin returns partial; added authTotpLogin, authOtpRequest, authOtpLogin, totpSetup, totpVerifySetup, totpDisable, totpStatus. Legacy authVerifyOtp kept.
- [DONE] `frontend/src/pages/LoginPage.tsx` — multi-step: credentials → second-factor (TOTP auto-submit on 6 digits + "Use backup code instead" → OTP) with method message + 5-min note + back. Partial token in component state only.
- [DONE] `frontend/src/pages/Settings.tsx` — new TwoFactorPanel (admin): status, Setup (QR+secret+verify-enable), Disable (password+code), offline note. tsc clean.
- Frontend COMPLETE (tsc clean).
- [DONE] `docs/totp-setup-guide.md` (NEW) — options, compatible apps, setup, OTP fallback, SMTP, recovery (DB reset snippet), disable, troubleshooting.
- [DONE] `README.md` — v3.19 changelog entry (endpoints, columns, screens, OTP-always-available, offline TOTP).
- ALL FILES COMPLETE. Backend suite 426 passing, frontend tsc clean.
- **STATUS: AWAITING EXPLICIT USER APPROVAL TO COMMIT + PUSH (develop → main).** Per the rule, do NOT push to main without confirmation.

---

# Implementation Status — 90% Auto-Stop Overload Protection (v3.12)

## Session started: 2026-04-30

Feature scope: extends the v3.11 load monitoring with a third threshold tier
at 90% of `rated_amps` that triggers an **automatic socket stop** without
operator action. When meter telemetry crosses 90%, the backend ends the
active session with `end_reason="auto_stop_overload"`, publishes a stop
command on `opta/cmd/socket/Q{n}`, raises a persistent alarm in
`meter_load_alarms` with `alarm_type="auto_stop"`, sets a new
`SocketConfig.auto_stop_pending_ack` latch that blocks all re-activation
paths (manual + auto), and broadcasts `meter_load_auto_stop`. The latch
only clears when an admin calls a new socket-scoped acknowledge endpoint
(internal + ERP variants). 60% / 80% behaviour is untouched.

**Approved design decisions (2026-04-30):**
- D1 — auto-stop is **terminal**. `meter_load_status` stays `auto_stop`
  until the acknowledge endpoint is called. Load dropping below 90%
  does NOT auto-clear.
- D2 — dedicated 90% branch at the **top** of the threshold logic in
  `_handle_opta_meter_telemetry`. Existing 60%/80% state machine
  completely untouched. When `prev_status == "auto_stop"` the handler
  is a no-op for that tick.
- D3 — reuse `meter_load_alarms` table; new `alarm_type="auto_stop"`.
- D4 — socket-scoped acknowledge endpoint:
  `POST /api/pedestals/{pedestal_id}/sockets/{socket_id}/load/auto-stop/acknowledge`.
  Looks up the latest unack'd auto-stop alarm row internally.
- D5 — acknowledge is one atomic transaction: clears
  `auto_stop_pending_ack` AND acks the alarm row.
- D7 — ERP path records `acknowledged_by="erp-service"` (literal string).
- D8 — `_maybe_auto_activate` in mqtt_handlers also guards on
  `auto_stop_pending_ack`; logs `"Auto-activation skipped: overload
  alarm pending acknowledgment"`.
- D9 — extend `LoadStatus` union with `'auto_stop'`. TypeScript compile
  errors force every render path to handle it explicitly.
- D10 — no pre-push hook changes; existing `tests/run_tests.sh`
  auto-discovers new cases.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `backend/app/models/socket_config.py` | COMPLETE | Added `auto_stop_pending_ack: Boolean(nullable=False, default=False)` after `load_critical_threshold_pct`. New latch gates re-activation until admin acknowledges 90%-threshold auto-stop. Cleared only by ack endpoint, never by load dropping below 90%. |
| 2 | `backend/app/database.py` | COMPLETE | Appended migration entry `("socket_configs", "auto_stop_pending_ack", "INTEGER NOT NULL DEFAULT 0")` to `_migrate_schema()`. Idempotent ALTER TABLE for existing pedestal.db installations. |
| 3 | `backend/app/services/mqtt_handlers.py` | COMPLETE | (a) `_auto_activate_precondition_check` got 6th check returning `"overload alarm pending acknowledgment"` when `SocketConfig.auto_stop_pending_ack` is True (D8). (b) `_handle_opta_meter_telemetry` restructured around prev_status: terminal `auto_stop` short-circuit + new top-level `load_pct >= 90` branch executing Steps 1-7 atomically. Existing 60%/80% state machine moved into `else` branch — bytes-equal to the v3.11 version. New broadcast loop branches handle `session_completed` (pre-built dict) and `meter_load_auto_stop` (severity=AUTO_STOP + session_id). Also resolves any open warning/critical alarm rows with reason="auto-stop-supersedes" to keep alarm history consistent. |
| 3a | `tests/backend/test_meter_load.py` | COMPLETE | Added test_seed_active_session helper, _capture_mqtt_publishes helper, plus 10 new cases (TC-ML-31..40 + auto-stop-supersedes). Updated `_reset_state` autouse fixture to also wipe leftover sessions and clear `auto_stop_pending_ack` between tests. |
| 3b | `tests/backend/test_ws_event_catalog.py` | TEMP-EDIT | `meter_load_auto_stop` and `meter_load_auto_stop_acknowledged` added to INTERNAL_EVENTS with a comment marking them as "in-progress wire-up — remove in Step 7". Test guard otherwise blocks broadcast-without-handler. |
| 4 | `backend/app/routers/controls.py` | COMPLETE | Two guards added: `approve_socket` (admin approve flow) and `direct_socket_cmd` (admin direct activate). Both raise 409 with "Socket was automatically stopped due to overload. Acknowledge the alarm before re-activating." Stop action in direct_socket_cmd intentionally NOT guarded — operator can always stop a socket. Tests TC-ML-41..45 added (5 cases) covering both endpoints + the D8 auto-activate path. |
| 5 | `backend/app/routers/meter_load.py` | COMPLETE | Added `POST /{pedestal_id}/sockets/{socket_id}/load/auto-stop/acknowledge`. Helper `perform_auto_stop_acknowledge(db, pedestal_id, socket_id, actor_label)` shared with the ERP router (Step 5). Atomic transaction (D5): clears `auto_stop_pending_ack`, marks the most recent open auto-stop alarm row acknowledged (with admin email), reclassifies `meter_load_status` from current load_pct (treats prev_status as "unknown" — no hysteresis carryover so the operator's ack is a clean restart). Returns 409 when no auto-stop is pending. Broadcasts `meter_load_auto_stop_acknowledged` with payload {pedestal_id, socket_id, alarm_id, acknowledged_by, acknowledged_at, load_status, timestamp}. Returns `{"status": "acknowledged", "socket_id": socket_id}`. ws_manager moved to module-level import. Tests TC-ML-46..50 added (5 cases). |
| 6 | `backend/app/routers/ext_meter_load_endpoints.py` | COMPLETE | Added `POST /api/ext/pedestals/{pedestal_id}/sockets/{socket_id}/load/auto-stop/acknowledge`. Reuses `perform_auto_stop_acknowledge` helper from meter_load.py. Records `acknowledged_by="erp-service"` per D7. Same broadcast event as internal endpoint so dashboards update in real time regardless of channel. New `_EP_AUTO_STOP_ACK = "load.auto_stop_ack_ext"` constant + per-endpoint toggle. Module-level ws_manager import. Tests TC-ML-51..53 (3 cases) for ack-records-erp-service, 503 when toggle disabled, 401 missing auth. |
| 7 | `backend/app/services/api_catalog.py` | COMPLETE | Added `load.auto_stop_ack_ext` ENDPOINT_CATALOG entry (POST, allow_bidirectional=True, category="Load Monitoring") + 2 EVENT_CATALOG entries (`meter_load_auto_stop`, `meter_load_auto_stop_acknowledged`, both category="Load Monitoring"). Drift-guard tests TC-ML-54/55 (2 cases) confirm registration. Catalog AST drift guard in test_ws_event_catalog.py automatically picks up the events because backend now broadcasts them and frontend now handles them. |
| 8 | `frontend/src/api/meterLoad.ts` | COMPLETE | LoadStatus union extended to `'normal' \| 'warning' \| 'critical' \| 'auto_stop' \| 'unknown'` per D9. MeterLoadAlarm.alarm_type union extended with `'auto_stop'`. New `acknowledgeAutoStop(pedestalId, socketId)` axios helper hitting the internal endpoint. |
| 9 | `frontend/src/store/index.ts` | COMPLETE | LoadStatus union extended in socketLoadStates type. New `autoStopPendingAck: Record<string, boolean>` + `pendingAutoStopAlarms: Array<{key, pedestal_id, socket_id, current_amps, rated_amps, load_pct, session_id, triggered_at}>`. Actions: setAutoStopPendingAck, addAutoStopAlarm (also strips superseded warning/critical alarm keys), acknowledgeAutoStopAlarm (drops from pending list + clears latch). |
| 10 | `frontend/src/hooks/useWebSocket.ts` | COMPLETE | New cases `meter_load_auto_stop` (calls addAutoStopAlarm + admin Browser Notification with ⚡ emoji) and `meter_load_auto_stop_acknowledged` (calls acknowledgeAutoStopAlarm). Destructured both new actions from useStore. |
| 10a | `frontend/src/components/pedestal/SocketLoadMeterPanel.tsx` | PARTIAL (Step 7) | Added `auto_stop` entries to STATUS_BAR_COLOR / STATUS_TEXT / STATUS_BADGE_CLASS so the type-strict Record satisfies the new union member. Banner + Acknowledge UI to be added in Step 8. |
| 10b | `tests/backend/test_ws_event_catalog.py` | COMPLETE (revert) | Removed the temporary INTERNAL_EVENTS marker for the two auto-stop events now that frontend has real `case` handlers. Drift guard back to its v3.11 strict semantics. |
| 11 | `frontend/src/components/pedestal/SocketLoadMeterPanel.tsx` | COMPLETE | Reads `autoStopPendingAck[key]` and `pendingAutoStopAlarms` from store. New banner block (rendered when latch=true) with "⚡ AUTO-STOP — OVERLOAD PROTECTION ACTIVATED" headline, current/rated amps + load_pct text, "Investigate the load before re-activating." reminder, and admin-only "Acknowledge & Enable Re-activation" button. Click triggers a window.confirm with the spec's exact safety copy ("Are you sure you want to acknowledge this overload alarm? Ensure the boat has reduced its power consumption before re-activating the socket."), then POSTs to the acknowledge endpoint and optimistically calls acknowledgeAutoStopAlarm in the store. STATUS_BAR_COLOR/STATUS_TEXT/STATUS_BADGE_CLASS already extended in Step 7; the badge now also shows ⚡ icon when status === 'auto_stop'. |
| 12 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | Activate button discovered here (D6 resolved). Reads `autoStopPendingAck[${pedestalId}-${socketId}]` from store. `disabled` extended to `!isPending \|\| loading \|\| autoStopPending`. Tooltip prefers "Acknowledge the overload alarm first" over the existing plug-state tooltips when latch is set. Stop button intentionally untouched — operator can always stop. |
| 13 | `frontend/src/pages/SystemHealth.tsx` | COMPLETE | Added "AUTO-STOP ALARMS" card above all other alarm cards (red border-2, distinct visual weight). Each row shows severity dot, AUTO-STOP label, pedestal+socket id, current/rated amps, load_pct, optional session id (overlaid from pendingAutoStopAlarms when WS payload was captured), timestamp, status text ("Pending acknowledgment" red bold vs "Acknowledged" grey), and admin Acknowledge button (with same window.confirm safety copy as the panel). Existing v3.11 Meter Load Alarms card filters out auto_stop entries to avoid duplication. loadHw merge logic extended to treat any pendingAutoStopAlarms entry as the highest severity, promoting nav badge to 'auto_stop'. Re-merge useEffect dep list extended so badge updates instantly on WS event. |
| 13a | `frontend/src/store/index.ts` | COMPLETE (Step 9 follow-up) | hwAlarmLevel union extended from `'none' \| 'warning' \| 'critical'` to include `'auto_stop'`. |
| 13b | `frontend/src/components/layout/Layout.tsx` | COMPLETE | NavItem.hwAlarm union extended; auto_stop badge rendered as red dot with red-300 ring and distinct tooltip "Socket auto-stopped — overload alarm pending acknowledgment". |
| 14 | `tests/backend/test_meter_load.py` | COMPLETE | 25 new TC-ML-31..55 cases (Steps 2/3/4/5/6 tests merged into a single file in step order). New helpers: `_seed_active_session`, `_capture_mqtt_publishes`, `_seed_socket_state`, `_set_auto_stop_latch`, `_trigger_auto_stop`. Existing `_reset_state` autouse fixture extended to wipe leftover sessions and clear auto_stop_pending_ack between tests. |
| 15 | `README.md` | COMPLETE | v3.12 changelog entry inserted at the top of "## Changelog", newest-first per project convention. Documents all backend + frontend touchpoints, design decisions D1/D7/D8/D9 in plain operator-readable terms, the 25-test delta (339 → 364), and explicitly notes the no-hardcoded-rated_amps invariant. |

### Section currently being worked on: DONE
### Final test counts: 364/364 backend pytest passing. TypeScript clean.
### Release status:
- ✅ Commit `dbd859b` on develop → pre-commit + pre-push gates green → pushed to `origin/develop`.
- ✅ User approved merge with "go merge to main".
- ✅ `main` fast-forwarded to `dbd859b` (also picked up the 26.04 NUC installer + README guard commits that were previously develop-only — those land on main too as a side effect).
- ✅ Pushed to `origin/main` with `CLOUD_IOT_RELEASE=1` — full pre-push gate green.
- ✅ Final state: `main` and `develop` both at `dbd859b`, in sync with origin.

---

---

# Implementation Status — Live Socket Meter Telemetry + Load Monitoring (v3.11)

## Session started: 2026-04-28

Feature scope: Arduino reports the per-cabinet hardware configuration on
`opta/config/hardware` (meter type, phases, ratedAmps, modbusAddress per
socket) and live meter readings on `opta/meters/+/telemetry` every 5 s.
Backend stores everything dynamically — no hardcoded values for cabinet,
meter type, phase count, rated current, or socket count anywhere. Load
percentage is computed from the live current vs the stored rated_amps;
warning/critical thresholds are operator-configurable per socket. Alarm
state machine writes to a new `meter_load_alarms` table with auto-resolve
on return-to-normal and 2 % hysteresis to prevent threshold-edge chatter.
Control Center socket card gets a new `SocketLoadMeterPanel` (sibling to
v3.8 SocketBreakerPanel) with read-only Hardware Info, phase-aware load
bars (single bar for 1Φ, three stacked bars for 3Φ), and admin threshold
editor. System Health page gains a third alarm card for open meter load
alarms with Acknowledge / Resolve actions. ERP gets 5 new
`/api/ext/.../load*` endpoints under category "Load Monitoring".

**Approved design decisions (2026-04-28):**
- D1 (b): new `SocketLoadMeterPanel.tsx` — clean separation from breaker panel.
- D2 (b): 3-phase load uses `max(L1,L2,L3) / rated_amps × 100` (electrically
  correct — bottleneck phase). Single-phase = `currentAmps / rated_amps × 100`.
  This intentionally **diverges from the spec** which had a flawed total/rated
  formula.
- D3 (b): 2 % hysteresis on resolve. Only resolve warning when load drops to
  `warning_threshold − 2`, same gap on critical.
- D4: alarm state machine — `normal→warning` insert+broadcast,
  `warning→critical` auto-resolve warning (resolved_by="auto-upgrade") +
  insert critical, `critical→warning` auto-resolve critical
  (resolved_by="auto-downgrade") + insert warning, `*→normal` resolve all
  open rows (resolved_by="auto-resolve") + broadcast `meter_load_resolved`.
- D5: live meter fields stored as received even before hardware config
  arrives. Only `load_pct` / `load_status` / alarm pipeline are skipped.
- D6: `routers/meter_load.py` (internal admin) + `routers/ext_meter_load_endpoints.py`
  (ERP). Mirrors v3.8 split.
- D7: third "Meter Load Alarms" card on SystemHealth page; existing hardware
  alarm banners untouched.
- D8 (a): merge load alarm severity into existing `hwAlarmLevel` — single
  unified hardware-severity badge.
- D9: Acknowledge flips DB column (alarm visible but dimmed, badge ignores).
  Resolve is admin-only manual close. Auto-resolve uses `resolved_by="auto-resolve"`.
- D10 (b): three stacked horizontal bars per phase for 3Φ; one bar for 1Φ.
  Bottleneck phase still drives `load_pct` and alarm thresholds.
- D11: defaults — warning 60 %, critical 80 %.
- D12: hardware config dedup mirrors v3.8 breaker-metadata rule — only
  update fields present in payload, never overwrite existing with null.
- D13: `docs/firmware_requirements.md` gains v3.11 section documenting both
  contracts. Note dormant pattern same as v3.8 breakers.
- D14: ~30 tests using `_simulate(topic, payload)` pattern from v3.8 suite.
- D15: mobile out of scope.
- Out of scope: Arduino sketch changes (firmware team), Modbus polling code,
  per-meter serial-number lookup table.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `backend/app/models/socket_config.py` | COMPLETE | 21 new columns: 5 hw-config + 6 single-phase live + 6 per-phase live + 3 derived load + 2 thresholds. All nullable except meter_load_status (default "unknown") and the two threshold defaults (60/80) |
| 2 | `backend/app/models/meter_load_alarm.py` | COMPLETE | One row per threshold crossing; resolved_at distinguishes open/historical; resolved_by encodes operator/auto-* origin; acknowledged column is separate from resolved |
| 3 | `backend/app/database.py` | COMPLETE | Imported meter_load_alarm; added 21 ALTER TABLE entries to _migrate_schema() in the v3.11 block |
| 4 | `backend/app/services/mqtt_client.py` | COMPLETE | Added `opta/config/hardware` + `opta/meters/+/telemetry` to TOPICS |
| 5 | `backend/app/services/mqtt_handlers.py` | COMPLETE | 2 regex (OPTA_HW_CONFIG_RE, OPTA_METER_RE) + dispatch branches; `_handle_opta_hardware_config` (no-overwrite-with-null per D12, broadcasts `hardware_config_updated`); `_handle_opta_meter_telemetry` (parses 1Φ/3Φ generically, stores live data even when rated_amps null per D5, computes load_pct via max(L1..L3)/rated for 3Φ per D2, runs `_classify_load` state machine with 2% hysteresis per D3, transitions per D4 with auto-upgrade/auto-downgrade/auto-resolve audit, broadcasts `meter_load_warning`/`meter_load_critical`/`meter_load_resolved` plus a per-tick `meter_telemetry_received`) |
| 6 | `backend/app/routers/meter_load.py` | COMPLETE | 5 admin endpoints + ack/resolve. Shared `serialize_load_state` / `serialize_alarm` re-exported to ERP file. PATCH validates `warning < critical` |
| 7 | `backend/app/routers/ext_meter_load_endpoints.py` | COMPLETE | 5 ERP routes mirroring v3.8 ext_breaker pattern. Reuses serialize_* helpers from meter_load.py. Marina endpoint LIKE-matches `MAR_{marina_id}_%` |
| 8 | `backend/app/main.py` | COMPLETE | imports + include_router for both meter_load_router and ext_meter_load_router (latter before gateway catch-all) |
| 9 | `backend/app/services/api_catalog.py` | COMPLETE | 5 ENDPOINT_CATALOG entries (load.*_ext, all category="Load Monitoring") + 4 EVENT_CATALOG entries (hardware_config_updated, meter_load_{warning,critical,resolved}) |
| 10 | `frontend/src/store/index.ts` | COMPLETE | `socketHardwareConfig` (patch-merge, key=`${pid}-${sid}`), `socketLoadStates` with default thresholds + load_status='unknown', `activeCriticalLoadAlarms` / `activeWarningLoadAlarms` with auto-promote/demote across severity in addLoadAlarm |
| 11 | `frontend/src/api/meterLoad.ts` | COMPLETE | Typed client: getSocketLoad, getPedestalLoad, patchLoadThresholds, getPedestalLoadAlarms, getSocketLoadHistory, acknowledgeLoadAlarm, resolveLoadAlarm |
| 12 | `frontend/src/components/pedestal/SocketLoadMeterPanel.tsx` | COMPLETE | Hardware Info read-only with "Awaiting hardware configuration from device" amber state; load bar(s) phase-aware (3 stacked for 3Φ, single for 1Φ); status badge/animation green/yellow/red; admin threshold editor with frontend validation matching backend |
| 13 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` + `useWebSocket.ts` | COMPLETE | SocketLoadMeterPanel mounted as sibling after SocketBreakerPanel; 5 WS cases (hardware_config_updated, meter_telemetry_received, meter_load_warning, meter_load_critical, meter_load_resolved) — admin gets Browser Notification on critical |
| 14 | `frontend/src/pages/SystemHealth.tsx` | COMPLETE | Imports meterLoad client; new "Meter Load Alarms" card (per D7) listing open rows with Acknowledge + Resolve buttons; loadHw() merges hardware + load severity into single hwAlarmLevel (D8); loadLoadAlarms iterates visible pedestals every 15 s; useEffect on alarm-list lengths re-triggers merge |
| 15 | `tests/backend/test_meter_load.py` | COMPLETE | 30 tests covering hw config writes/updates/no-overwrite-with-null, broadcast event, telemetry phase detection, single-phase + 3-phase load formula (max(L1..L3) per D2), all 4 alarm state transitions, hysteresis, no-duplicate-on-same-status, threshold validation, GET endpoints, ack/resolve, ERP endpoints, drift guard. **30/30 green** |
| 16 | `tests/backend/conftest.py` | COMPLETE | Imports meter_load_alarm so create_all picks up the new table |
| 17 | `docs/firmware_requirements.md` | COMPLETE | New v3.11 section: opta/config/hardware contract + opta/meters/+/telemetry single/3-phase payload contracts + dormant-pattern note + bottleneck-phase formula explanation |
| 18 | `README.md` | COMPLETE | Newest-first v3.11 changelog with full feature description, 339-test count, Wire: list |

## Test run result: 339 passed, 0 failed (2026-04-28) — 313 prior + 26 new (30 in test_meter_load.py - 4 that overlap with existing in same module). TypeScript: clean.

## Pending before release
- ✅ pytest 339/339; ✅ TS clean; ✅ docs updated.
- Stage v3.11 files, commit on develop, push develop with full pre-push gate.
- PAUSE for explicit user approval before merging to main.
- After main merge: regenerate `docs/User Guide.docx` with v3.10 + v3.11 sections.

---

---

# Implementation Status — Configurable Daily LED Schedule (v3.10)

## Session started: 2026-04-28

Feature scope: per-pedestal daily LED on/off schedule (HH:MM, color, days-of-week).
Backend scheduler ticks every minute, compares marina-local time against
configured `on_time` / `off_time`, publishes `opta/cmd/led` with the
operator-chosen color/state. New `led_schedules` table (one row per pedestal).
4 admin endpoints for CRUD + immediate test. New `LedScheduleSection` in the
Control Center with on/off time pickers, color selector, day-of-week
checkboxes, Save/Test/Delete buttons, and a forward-looking "Next on / Next
off" preview that re-renders every minute. WebSocket `led_changed` event fires
on both scheduled and manual LED commands so the dashboard reflects state in
real time.

**Approved design decisions (2026-04-28):**
- D1 (b): single global `MARINA_TIMEZONE` env var (default `UTC`, on-site set
  to `Europe/Zagreb`). Per-pedestal TZ deferred.
- D2: endpoints co-located in `pedestal_config.py` (mirrors v3.9 valves).
- D3: color enum `{green, blue, red, yellow}` only — `white` deferred until
  firmware confirms support; flagged in `docs/firmware_requirements.md`.
- D4 (a): scheduler `await asyncio.sleep(60)` with HH:MM dedup.
- D5: in-memory `_led_schedule_last_fired: dict[int, dict[str, str]]` keyed
  by pedestal_id, slots `on` and `off` holding `YYYY-MM-DD HH:MM`. Restart
  duplicates absorbed by Opta's 16-entry msgId idempotency cache.
- D6: days-of-week stored as comma-separated `0..6` string (Mon=0, Sun=6).
  Validated unique + in-range on PUT.
- D7 (a): 5-minute grace window — fire missed on/off if backend was down for
  less than 5 min, otherwise log warning + skip.
- D8 (a): new `led_changed` WebSocket event broadcast on BOTH scheduled fires
  AND the existing manual `setLed` endpoint (retroactive consistency). Added
  to `EVENT_CATALOG`.
- D9 (a): `POST /led-schedule/test` returns 404 when no schedule exists.
- D10: 7 raw day checkboxes, no presets.
- D11: "Next on / Next off" preview computed on the frontend, re-rendered
  via `setInterval(60_000)` on mount.
- Out of scope: multiple windows per day, sunset/sunrise, mobile, ERP webhook
  for `led_changed` (operator can opt in via API Gateway page later).

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `backend/app/models/led_schedule.py` | COMPLETE | One row per pedestal; HH:MM strings, comma-sep days 0..6, color default green |
| 2 | `backend/app/database.py` | COMPLETE | init_db imports led_schedule so create_all picks up `led_schedules` |
| 3 | `backend/app/config.py` | COMPLETE | New `marina_timezone: str = "UTC"` setting; production .env sets `Europe/Zagreb` |
| 4 | `backend/app/services/led_scheduler.py` | COMPLETE | `_marina_now()` (zoneinfo), `_parse_days`, `_should_fire` (grace window), `_publish_led` shared helper, `tick_once(db, now_utc=None)` testable, `run_scheduler()` lifespan loop. Module-level `_led_schedule_last_fired` dict |
| 5 | `backend/app/routers/controls.py` | COMPLETE | `set_pedestal_led` now broadcasts `led_changed` with `source="manual"` after publish |
| 6 | `backend/app/routers/pedestal_config.py` | COMPLETE | 4 endpoints (GET/PUT/DELETE/POST-test). Validators for HH:MM, color enum, unique-sorted days. PUT/DELETE clear the per-pedestal dedup slot so a fresh save fires inside the grace window |
| 7 | `backend/app/main.py` | COMPLETE | `led_scheduler_task = asyncio.create_task(_run_led_scheduler())` + cancellation in shutdown |
| 8 | `backend/app/services/api_catalog.py` | COMPLETE | 4 ENDPOINT_CATALOG entries (led_schedule.{get,upsert,delete,test}) + 1 EVENT_CATALOG entry (led_changed) |
| 9 | `frontend/src/api/ledSchedule.ts` | COMPLETE | get/upsert/delete/test typed client + LedSchedule and LedScheduleBody types |
| 10 | `frontend/src/components/pedestal/LedScheduleSection.tsx` | COMPLETE | Auto LED toggle + on/off time inputs + 4-color swatches + 7-day checkboxes + live Next On / Next Off preview (60 s setInterval) + Save/Test/Delete buttons. Validators mirror backend. 404 from Test prompts to Save first |
| 11 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` + `useWebSocket.ts` | COMPLETE | LedScheduleSection mounted between LED Control and Danger Zone; useWebSocket adds `led_changed` case that toasts admin-only when source=scheduler (manual fires already self-feedback) |
| 12 | `tests/backend/test_led_schedule.py` | COMPLETE | 13 tests (TC-LS-01..10 + 4 parametrised invalid HH:MM cases). Tests directly call `tick_once(db, now_utc=...)` for time-deterministic scheduler verification |
| 13 | `tests/backend/conftest.py` | COMPLETE | imports led_schedule model |
| 14 | `backend/requirements.txt` | COMPLETE | added `tzdata>=2024.1` for Windows zoneinfo lookups |
| 15 | `docs/firmware_requirements.md` | COMPLETE | New v3.10 section flagging that `white` is not firmware-validated |
| 16 | `README.md` | COMPLETE | Newest-first v3.10 entry — full feature description + 13 new tests + tzdata note + Wire: list |

## Test run result: 313 passed, 0 failed (2026-04-28) — 299 prior + 14 new (13 LED + 1 from re-running breakers/valves catalog drift). TypeScript: clean.

## Pending before release
- ✅ pytest 313/313; ✅ TS clean; ✅ docs updated.
- Stage v3.10 files, commit on develop, push develop with full pre-push gate.
- PAUSE for explicit user approval before merging to main.

---

---

# Implementation Status — Per-Valve Auto-Activation + Post-Diagnostic Auto-Open (v3.9)

## Session started: 2026-04-24

Feature scope: add a per-valve `auto_activate` flag (mirrors v3.5 socket flag but
for V1/V2) with default `True`. When `opta/diagnostic` returns and the per-valve
sensor reports `ok`, backend publishes `{"action":"activate"}` on
`opta/cmd/water/V{n}` for every valve whose `auto_activate=True` — unless
(a) an active water session already exists on that valve, or (b) an operator
manually stopped the valve in the last 10 minutes. The auto-fire creates a
`customer_id=NULL` "unattributed" water session so incoming flow readings are
still attributable to a row (even though no invoice is produced). 30 s after
each auto-open, a fire-and-forget watchdog checks the latest flow reading and
broadcasts `valve_flow_warning` if flow is still 0 — informational only, the
valve stays open.

**Approved design decisions (2026-04-24):**
- Default `auto_activate=True` for new valves (opposite of sockets). Hardware
  valve is normally-closed; flow meter provides immediate operator visibility.
- D1 option (b): create `customer_id=NULL` session when auto-activation fires
  without a customer. Flow is tracked via the existing `_handle_water_flow`
  pipeline; no invoice is produced.
- D2 option (b): per-valve sensor ok gates auto-open. Diagnostic response
  parser must be extended to expose per-valve `water_v1_ok` / `water_v2_ok`.
- D3 option (b): 10-minute cooldown after an operator-initiated manual stop.
  Prevents diagnostic from becoming an accidental water-on button.
- D4: no-op if an active water session already exists on that valve.
- D5: sockets entirely unchanged — still require `UserPluggedIn`.
- D6: v3.7 auto-discovery pattern — create ValveConfig row once with default
  `auto_activate=True`, never overwrite operator toggles afterwards.
- D7 option (a): new `valve_config` table (not generalised SocketConfig).
- D8: separate module-level dicts in mqtt_handlers — rename the existing
  `last_diagnostic_at` to `last_diagnostic_lockout_at` for socket auto-activate
  clarity, and add `last_diagnostic_ok_at` as the valve auto-open enabler.
- D9: five mandatory tests cover happy path, auto_activate=False skip,
  active-session skip, per-valve sensor filter, and orphan-session flow
  attribution.
- Additional guard: 30-second zero-flow watchdog after each auto-open. Logs a
  warning + broadcasts `valve_flow_warning` WebSocket event when flow stays 0.
  Non-destructive — valve remains open; operator sees banner + Browser Notification.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `backend/app/models/valve_config.py` | COMPLETE | New `valve_configs` table; auto_activate default True per design D |
| 2 | `backend/app/database.py` | COMPLETE | init_db imports valve_config so create_all creates `valve_configs` |
| 3 | `backend/app/services/mqtt_handlers.py` | COMPLETE | Renamed `last_diagnostic_at` → `last_diagnostic_lockout_at` with back-compat alias; added `last_diagnostic_ok_at` + `last_valve_manual_stop_at` dicts; new `_auto_discover_valve_config` helper; `_handle_marina_water` now auto-discovers valve config; extended `_handle_opta_diagnostic` with per-valve `water_v{n}` keys and post-diag `_maybe_auto_open_valve` tasks per valve whose sensor is ok; new `_maybe_auto_open_valve` coroutine (4 guards: auto_activate flag, active session, 10-min cooldown, cabinet_id present) + `_check_valve_flow_after_30s` zero-flow watchdog that broadcasts `valve_flow_warning` |
| 4 | `backend/app/services/session_service.py` | SKIPPED | No change needed — firmware emits OutletActivated with customer_id=None in response to auto-open activate command; existing `_handle_event_outlet_activated` path handles unattributed sessions natively |
| 5 | `backend/app/routers/diagnostics.py` | SKIPPED | No change needed — auto-open is driven by MQTT response handler, not the HTTP endpoint. The existing `last_diagnostic_at` reference still works via back-compat alias |
| 6 | `backend/app/routers/controls.py` | COMPLETE | Stamp `last_valve_manual_stop_at[(pid, vid)]` both in `_publish_session_control` water stop branch AND in `direct_water_cmd` stop branch so any operator-initiated stop triggers the 10-min cooldown |
| 7 | `backend/app/routers/pedestal_config.py` | COMPLETE | Added ValveConfigUpdate body + `GET /api/pedestals/{pid}/valves/config` + `PATCH /api/pedestals/{pid}/valves/{vid}/config` (admin only). Default-true fallback returned for never-configured valves. Co-located with sibling socket config endpoints |
| 8 | `backend/app/main.py` | SKIPPED | No change — endpoints piggyback on existing `pedestal_config_router` already registered |
| 9 | `backend/app/services/api_catalog.py` | COMPLETE | Added 2 ENDPOINT_CATALOG entries (valves.config_list / valves.config_patch) + 1 EVENT_CATALOG entry (valve_flow_warning) |
| 10 | `frontend/src/store/index.ts` | COMPLETE | `valveAutoActivate` Record + setter mirroring socketAutoActivate; `valveFlowWarnings` list + add/clear. Keyed `${pedestal_id}-${valve_id}` |
| 11 | `frontend/src/api/valveConfig.ts` | COMPLETE | getValveConfigs, setValveConfig typed client |
| 12 | `frontend/src/hooks/useWebSocket.ts` | COMPLETE | Destructured `addValveFlowWarning`; new case `valve_flow_warning` writes to store + fires admin Browser Notification |
| 13 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | WaterCard extended: AUTO toggle mirroring SocketCard, green AUTO / amber UNATTRIBUTED badges, zero-flow amber banner when valveFlowWarnings contains the key. ControlCenter loads `getValveConfigs` on mount; `onValveAutoActivateChange` optimistic PATCH with rollback |
| 14 | `tests/backend/test_valve_auto_activate.py` | COMPLETE | 7 tests (TC-VA-01..07) — all five mandatory cases per D9 + auto-discovery default + GET/PATCH endpoints. Autouse fixture wipes manual-stop dict + active water sessions on the test cabinet between tests |
| 15 | `tests/backend/conftest.py` | COMPLETE | Added valve_config import so create_all picks up the new table |
| 16 | `frontend/src/hooks/useWebSocket.ts` (touched again) | COMPLETE | Tightened body type for valve_flow_warning Notification (TS strict mode) |
| 17 | `README.md` | COMPLETE | Newest-first v3.9 entry — flag default, post-diag flow + 3 guards, unattributed sessions, zero-flow watchdog, 7 new tests, Wire: list |

## Pending before release
- ✅ pytest 299/299; ✅ TS clean.
- Commit on develop, push develop with full test gate.
- PAUSE for explicit user approval before merging to main.

## Test run result: 299 passed, 0 failed (2026-04-25) — 292 prior + 7 new TC-VA cases. TypeScript: clean.

---

---

# Implementation Status — Smart Circuit Breaker Monitoring + Remote Reset (v3.8)

## Session started: 2026-04-24

Feature scope: subscribe to `opta/breakers/+/status` and handle new `BreakerTripped`
event on `opta/events`; persist breaker state + metadata on `SocketConfig`; log every
trip/reset into new `breaker_events` table; stop active power session on trip with
`end_reason="breaker_trip"`; expose internal admin endpoints and a parallel ERP
external API for breaker status, history, reset, and marina-wide active alarms;
Control Center gains a red alarm banner + per-socket SocketBreakerPanel with Hardware
Info, Reset button (with confirmation + 15 s timeout), and history modal; PedestalView
gains a ⚡ overlay on tripped circles; `breaker_alarm` is webhookable to ERP.

**Approved design decisions (2026-04-24):**
- URL params use numeric `{socket_id}` (1–4); internal conversion to `Q{n}` for MQTT.
- New breaker UI extracted to `SocketBreakerPanel.tsx` to keep SocketCard bounded.
- Alarm banner state: Zustand in-memory; acknowledgements kept in `sessionStorage`.
- Metadata merge: only write keys present in the payload — never overwrite with null.
- BreakerTripped affects power sessions only. Water sessions never touched.
- Breaker history modal uses a new `GET /api/pedestals/{pid}/sockets/{sid}/breaker/history?limit=10`.
- Reset button 15 s watchdog on the frontend; error toast if still tripped after timeout.
- Lightning bolt on socket circle uses emoji `⚡` (matches existing `📷` convention).
- Browser Notification on `breaker_alarm` for admin role only (mirrors `session_created`).
- `breaker_trip_count` is cumulative forever — never auto-reset.
- ERP routes follow v3.3 pattern — direct FastAPI routes registered in `main.py`
  before the `ext_api_gateway_router` catch-all.
- Socket id taken from MQTT topic path on `opta/breakers/{socket_id}/status`;
  payload `socketId` is only a sanity check.
- New `docs/firmware_requirements.md` captures the retained-MQTT recommendation
  for breaker status so the Arduino team publishes with retain flag.
- API Gateway UI groups the 5 new endpoints automatically via
  `category: "Breaker Management"` on each catalog entry. No hand-written JSX.
- Release flow: push develop with normal test gate, pause for explicit user
  approval, then merge and push main with `CLOUD_IOT_RELEASE=1`.
- `breaker_alarm` registered with `webhook: True` so ERP gets push on trip.
- `breaker_reset_sent` event dropped from EVENT_CATALOG — the state transition
  to `resetting` already broadcasts `breaker_state_changed`, so a separate
  event would be redundant and trip the drift guard.
- No SNMP trap. No mobile app changes.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `backend/app/models/socket_config.py` | COMPLETE | Added 9 breaker columns: breaker_state, breaker_last_trip_at, breaker_trip_cause, breaker_trip_count, breaker_type, breaker_rating, breaker_poles, breaker_rcd, breaker_rcd_sensitivity |
| 2 | `backend/app/models/breaker_event.py` | COMPLETE | New model + table; indexed on (pedestal_id, socket_id, timestamp) |
| 3 | `backend/app/models/session.py` | COMPLETE | Added `end_reason: Mapped[str]` nullable 64-char column |
| 4 | `backend/app/database.py` | COMPLETE | Added breaker_event import + 10 migration entries (9 socket_configs + 1 sessions.end_reason) |
| 5 | `backend/app/services/mqtt_client.py` | COMPLETE | Added `opta/breakers/+/status` to TOPICS |
| 6 | `backend/app/services/session_service.py` | COMPLETE | `complete()` accepts optional `end_reason` kwarg; writes to `Session.end_reason` |
| 7 | `backend/app/services/mqtt_handlers.py` | COMPLETE | OPTA_BREAKER_RE + dispatch branch; `_handle_opta_breaker_status` (upsert SocketConfig, increment trip_count on fresh trip, metadata merge preserving nulls, broadcast `breaker_state_changed`); `_handle_event_breaker_tripped` (breaker_events log, stop power session with end_reason="breaker_trip", broadcast `session_completed` + `breaker_alarm`) |
| 8 | `backend/app/routers/breakers.py` | COMPLETE | New router: POST /reset (admin), GET status + socket history (default 10) + pedestal history (50). Shared helpers `get_cabinet_id`, `publish_breaker_reset`, `serialize_breaker_status`, `serialize_event`, `perform_breaker_reset`, `broadcast_resetting` reused by ERP router |
| 9 | `backend/app/routers/ext_breaker_endpoints.py` | COMPLETE | 5 ERP routes: breakers list, single-socket + 5 events, POST reset (initiated_by="erp-service"), pedestal history, marina_id alarm aggregator. Reuses shared helpers from breakers.py |
| 10 | `backend/app/main.py` | COMPLETE | Imports + include_router for breakers_router and ext_breaker_router (the latter before ext_api_gateway_router catch-all) |
| 11 | `backend/app/services/api_catalog.py` | COMPLETE | Added 5 ENDPOINT_CATALOG entries (all `category: "Breaker Management"`) + 3 EVENT_CATALOG entries (breaker_state_changed, breaker_alarm, breaker_reset_sent). Events flow through existing dispatch_webhook hook — no additional wiring required |
| 12 | `frontend/src/store/index.ts` | COMPLETE | Added `socketBreakerStates` + `setBreakerState` (partial-patch merge, never overwrites with null); `activeBreakerAlarms` list + `addBreakerAlarm` / `clearBreakerAlarm` / `acknowledgeBreakerAlarm`. Acknowledgements persist to `sessionStorage['ackedBreakerAlarms']` per D3 |
| 13 | `frontend/src/hooks/useWebSocket.ts` | COMPLETE | Destructured `setBreakerState`, `addBreakerAlarm`; added `breaker_state_changed` case (partial-patch update + auto-clear banner on `closed`) and `breaker_alarm` case (adds key + admin-only Notification) |
| 14 | `frontend/src/api/breakers.ts` | COMPLETE | Typed client: BreakerStatus + BreakerEvent types; `getSocketBreakerStatus`, `getSocketBreakerHistory` (limit default 10), `getPedestalBreakerHistory`, `postBreakerReset` |
| 15 | `frontend/src/components/pedestal/SocketBreakerPanel.tsx` | COMPLETE | New component: status dot + label, Hardware Info block (type, rating, poles, RCD, sensitivity, trips, cause — all fallback to "Not reported"), admin-only Reset with inline confirm dialog + 15 s timeout watchdog, History button opens modal. 409 surfaces "Breaker is not in tripped state" toast |
| 16 | `frontend/src/components/pedestal/BreakerHistoryModal.tsx` | COMPLETE | Modal fetches /api/pedestals/{pid}/sockets/{sid}/breaker/history?limit=10, renders event list with colour-coded event_type, shows trip_cause + current_at_trip + operator/erp-service badge |
| 17 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | Import SocketBreakerPanel; mount inside SocketCard (after autoSkipReason, before admin controls); destructure activeBreakerAlarms + acknowledgeBreakerAlarm; red alarm banner at top (after feedback toasts) lists tripped `Q{n}` sockets on THIS pedestal, Acknowledge button dismisses via sessionStorage |
| 18 | `frontend/src/components/pedestal/PedestalView.tsx` | COMPLETE | Destructure `socketBreakerStates`; compute `breakerTripped` for electricity sockets; render red ⚡ overlay top-right of the button when tripped. Existing ring/bg colour logic untouched |
| 19 | `tests/backend/test_breaker_monitoring.py` | COMPLETE | 21 tests (TC-BR-01..21) covering MQTT parse + no-null-overwrite + trip-count + BreakerTripped session stop + WS broadcasts + internal 409/publish/audit + ERP 409/publish/audit + invalid token + list / socket 5 events / history 50 / marina alarms / catalog registration |
| 20 | `tests/backend/conftest.py` | COMPLETE | Added breaker_event model import so tables are created in the test DB |
| 21 | `frontend/e2e/breaker.spec.ts` | COMPLETE | Playwright — Hardware Info "Not reported" default; Reset button hidden for monitor, visible for admin only when tripped, hidden when closed; alarm banner shows Q{n} label when socket is tripped. Store seeding via `window.__APP_STORE__` (see note for wiring) |
| 22 | `docs/firmware_requirements.md` | COMPLETE | New doc captures the v3.8 retain-flag recommendation for `opta/breakers/+/status` per D13; lists every currently-contracted topic with retain flag for cross-team reference |
| 23 | `frontend/src/store/index.ts` (touched again) | COMPLETE | Exposed `useStore` as `window.__APP_STORE__` at module end so Playwright can seed breaker state without waiting for the mocked WebSocket |
| 24 | `README.md` | COMPLETE | Newest-first v3.8 changelog entry — MQTT topic, internal endpoints, 5 ERP endpoints, WS events, UI features, test delta 275 → 292, Wire: list |

## Test run result: 292 passed, 0 failed (2026-04-24) — 271 pre-existing + 21 new breaker cases (test counts include TC-BR-01..21)

## Release status

- ✅ Commit `716f6b3` on develop.
- ✅ Pre-commit + pre-push gates green (pytest 292/292, bandit, semgrep, gap 1-4, detect-secrets, pip-audit).
- ⚠️ Playwright e2e **skipped** in the pre-push hook because the backend was not running on :8000. The spec itself is committed and will run automatically the next time the hook fires with a live backend (e.g. `bash tests/playwright_e2e.sh` with `uvicorn` up).
- ✅ `716f6b3` pushed to `origin/develop` (`2f9af0e..716f6b3`).
- ✅ User approved merge. `main` fast-forwarded to `6e8ab32`.
- ✅ Pushed to `origin/main` with `CLOUD_IOT_RELEASE=1` — all pre-push gates green; Playwright skipped (no backend on :8000 at push time, same as develop push).
- Final state: `main` and `develop` both at `6e8ab32`, synced with `origin`.

---

---

# Implementation Status — External Pedestal API Endpoints (v3.3)

## Session started: 2026-04-11
## Previous feature (CV Extension) — all sections complete. See git log for details.

---

## Current Feature: Three New External API Endpoints + Gateway Health Indicators

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `backend/app/services/api_catalog.py` | COMPLETE | Added 3 catalog entries |
| 2 | `backend/app/routers/ext_pedestal_endpoints.py` | COMPLETE | New file — 3 direct ext routes |
| 3 | `backend/app/routers/pedestal_config.py` | COMPLETE | Extended health endpoint + UserSessionLocal module-level import |
| 4 | `backend/app/main.py` | COMPLETE | ext_pedestal_router included before gateway catch-all |
| 5 | `frontend/src/api/externalApi.ts` | COMPLETE | ExtPedestalHealth type + getExtPedestalHealth() added |
| 6 | `frontend/src/pages/ApiGateway.tsx` | COMPLETE | Health dots + "not enabled" labels + health state |
| 7 | `tests/backend/test_ext_pedestal_endpoints.py` | COMPLETE | 17 tests (TC-EP-01..11 + auth + grab_failure) — 212/212 total |

## Test run result: 212 passed, 0 failed (2026-04-11)

---

## Design Decisions

- New endpoints live at `/api/ext/pedestals/{pedestal_id}/...` as **direct FastAPI routes**
  (NOT proxied through gateway catch-all `ANY /api/ext/{path:path}`).
- Router included in `main.py` BEFORE `ext_api_gateway_router` so specific routes win.
- `pedestal_id` param accepts numeric PK string or opta_client_id string.
- Per-endpoint enable/disable reuses existing `allowed_endpoints` JSON in ExternalApiConfig.
- Returns 503 (not 403) for disabled/unavailable feature per spec.
- Auth failures: 401/403. Gateway globally inactive: 503 "Not enabled".
- Health endpoint extended: each pedestal entry gets `ext_berths_occupancy`,
  `ext_camera_frame`, `ext_camera_stream` with `enabled`, `available`, `reason`.
- Frame grab reuses `berth_analyzer.grab_snapshot()`.
- Catalog IDs: `berths.occupancy_ext`, `camera.frame_ext`, `camera.stream_ext`

---
---

# Implementation Status — Socket Plug State Machine (v3.4)

## Session started: 2026-04-21

Feature scope: extend the socket state flow with a `pending` state driven by
firmware `UserPluggedIn` / `UserPluggedOut` events; broadcast a unified
`socket_state_changed` WebSocket event; reject operator `activate` commands
when no plug is inserted; render yellow pending indicators + pending tooltip
in Control Center and the pedestal picture overlay.

**Approved design decisions (2026-04-21):**
- NO new DB column — state is computed from `SocketState.connected` + active-session lookup and broadcast only.
- `socket_state_changed` is additive; existing `user_plugged_in`, `session_*` events kept for backwards compat.
- Activate rejection uses HTTP 409 + detail `"Socket has no plug inserted"`.
- Water valves out of scope (sockets Q1–Q4 only).
- Pending colour: Tailwind `yellow-400`.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `implementation_status.md` | IN PROGRESS | Feature header + per-file log |
| 2 | `backend/app/services/mqtt_handlers.py` | COMPLETE | helper `_broadcast_socket_state`, `_set_socket_connected`, new `_handle_event_user_plugged_out`, `UserPluggedOut` dispatcher case, `socket_state_changed` broadcasts from UserPluggedIn/Out, OutletActivated (→active), SessionEnded (→pending|idle) |
| 3 | `backend/app/routers/controls.py` | COMPLETE | `direct_socket_cmd` returns HTTP 409 "Socket has no plug inserted" when `SocketState.connected=False` on activate; imports `status`; de-duplicated `_socket_name_to_id` call |
| 4 | `backend/app/services/api_catalog.py` | COMPLETE | Added `socket_state_changed` entry to EVENT_CATALOG |
| 5 | `frontend/src/store/index.ts` | COMPLETE | Added `socketComputedStates` record + `setSocketComputedState(pedestal_id, socket_id, state)` setter |
| 6 | `frontend/src/hooks/useWebSocket.ts` | COMPLETE | Added `setSocketComputedState` destructure; added `case 'socket_state_changed':` that writes to computed state and syncs pendingSockets |
| 7 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | yellow `pending` StateBadge variant; SocketCard prefers `socketComputedStates`; Stop replaces Activate when `active`; Activate disabled unless `pending` with "No plug inserted" tooltip on idle + "Plug inserted — awaiting activation" on pending; CmdButton accepts `title` |
| 8 | `frontend/src/components/pedestal/PedestalView.tsx` | COMPLETE | ZoneButton consumes `socketComputedStates` for electricity sockets; pending ring/bg switched from amber to yellow; tooltip text "Plug inserted — awaiting activation" when pending |
| 9 | `tests/backend/test_socket_plug_state_machine.py` | COMPLETE | 8 test cases (TC-SP-01..07 + extra `activate rejected when no SocketState row` guard) — all green |
| 10 | `tests/backend/test_direct_controls.py` | COMPLETE | Seed SocketState.connected=True before TC-DC-01/02 activate path so activate guard is satisfied |
| 11 | `implementation_status.md` | IN PROGRESS | This file — final entry after release push |

## Test run result: 238 passed, 0 failed (2026-04-21) — 230 existing + 8 new state-machine cases

## Key design outcomes

- Computed state lives in broadcasts + frontend cache only; no new DB column.
- `socket_state_changed` broadcast from: `_handle_event_user_plugged_in` (→pending or active), `_handle_event_user_plugged_out` (→idle), `_handle_event_outlet_activated` (→active), `_handle_event_session_ended` (→pending if connected, else idle).
- Existing `user_plugged_in` / `session_*` events preserved; old clients still work.
- Frontend `pendingSockets` store kept in sync with `socketComputedStates` so legacy `ZoneButton` amber path is still correct until all consumers migrate.
- Activate guard is server-side enforcement: `HTTP 409 "Socket has no plug inserted"`. UI already blocks the click before the request is sent.
- Water valves untouched; spec explicitly scoped to electricity sockets Q1–Q4.
- Pending colour: `yellow-400` (Tailwind `#facc15`).

## WS event catalog drift guard

`tests/backend/test_ws_event_catalog.py` was already configured — `socket_state_changed` added to `EVENT_CATALOG` and also broadcast from code, so the AST drift check passes automatically.

---
---

# Implementation Status — Per-Socket Auto-Activation (v3.5)

## Session started: 2026-04-21

Feature scope: on top of the v3.4 plug state machine, allow operators to flip
a per-socket `auto_activate` toggle. When true, the backend fires the
`activate` command automatically after `UserPluggedIn`, gated by 5 safety
preconditions and a 2-second stabilisation delay. When false, everything
behaves exactly as today (manual Activate click in Control Center).

**Approved design decisions (2026-04-21):**
- Door state persisted as `PedestalConfig.door_state` (string, default `"unknown"`). `unknown` treated same as `open` for auto-activate — safe after restart until firmware confirms `closed`.
- Fault state tracked in a module-level dict inside `mqtt_handlers.py`; no DB column.
- `last_diagnostic_at` also module-level dict, written by the diagnostics router, read by auto-activate check. 60 s window.
- 2-second `asyncio.sleep` before publishing; re-check computed state after sleep — abort if socket is no longer pending (operator manually activated / plug yanked).
- `AutoActivationLog` rows accumulate; no rotation yet.
- No global feature flag; per-socket only.
- Colours: green `AUTO` badge (`text-green-400`), amber skip warning (`text-amber-300 bg-amber-900/30`).

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `implementation_status.md` | IN PROGRESS | This file — header + per-file log |
| 2 | `backend/app/models/pedestal_config.py` | COMPLETE | Added `door_state: Column(String, default="unknown")` — values `open / closed / unknown` |
| 3 | `backend/app/models/socket_config.py` | COMPLETE (NEW) | SocketConfig(id, pedestal_id, socket_id, auto_activate, created_at, updated_at) + UNIQUE(pedestal_id, socket_id) |
| 4 | `backend/app/models/auto_activation_log.py` | COMPLETE (NEW) | AutoActivationLog(id, pedestal_id, socket_id, timestamp, result=success|skipped, reason, session_id) + index on (pedestal_id, socket_id, timestamp) |
| 5 | `backend/app/database.py` | COMPLETE | Register `socket_config` + `auto_activation_log` in `init_db`; add `pedestal_configs.door_state TEXT DEFAULT 'unknown'` to the migration list |
| 6 | `backend/app/services/mqtt_handlers.py` | COMPLETE | Module-level `socket_fault_state` + `last_diagnostic_at` dicts; door_state persisted in `_handle_marina_door`; fault tracking in `_handle_opta_socket`; new `_log_auto_activation`, `_broadcast_auto_activate_skipped`, `_auto_activate_precondition_check`, `_maybe_auto_activate` (all 5 checks + 2s sleep + post-sleep re-check); `_handle_event_user_plugged_in` kicks off the coroutine when SocketConfig.auto_activate is True and computed state is pending; `asyncio` import added |
| 7 | `backend/app/routers/diagnostics.py` | COMPLETE | Writes `last_diagnostic_at[pedestal_id] = utcnow()` immediately before publishing `opta/cmd/diagnostic` — gives auto-activate a 60 s lockout window |
| 8 | `backend/app/routers/pedestal_config.py` | COMPLETE | 3 new endpoints appended — GET `/api/pedestals/{pid}/sockets/config` returns all 4 sockets with default `auto_activate=false`; PATCH `/sockets/{sid}/config` admin-only; GET `/sockets/{sid}/auto-activate-log` returns last 20 newest-first |
| 9 | `backend/app/services/api_catalog.py` | COMPLETE | 3 endpoints (sockets.config_list / config_patch / auto_log) + 1 event (socket_auto_activate_skipped) — keeps AST drift guards green |
| 10 | `frontend/src/api/index.ts` | COMPLETE | `SocketAutoActivateConfig`, `AutoActivateLogEntry` types + `getSocketConfigs`, `setSocketConfig`, `getAutoActivateLog` wrappers |
| 11 | `frontend/src/store/index.ts` | COMPLETE | `socketAutoActivate` + `setSocketAutoActivate`; `socketAutoSkipReasons` + `setSocketAutoSkipReason` + `clearSocketAutoSkipReason` |
| 12 | `frontend/src/hooks/useWebSocket.ts` | COMPLETE | Added `setSocketAutoSkipReason` / `clearSocketAutoSkipReason` destructures; new `case 'socket_auto_activate_skipped':` sets reason + schedules 30 s auto-clear via setTimeout; `case 'socket_state_changed':` now also clears the reason on any transition away from pending |
| 13 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | `useEffect` loads `getSocketConfigs` on open; optimistic `onAutoActivateChange` via `setSocketConfig` with rollback; SocketCard gains `autoActivate` / `autoSkipReason` / `onAutoActivateChange` props; green `AUTO` badge next to socket id; auto-activate toggle with loading guard and ✓ indicator; amber skip-reason banner below status block; pending tooltip switches to "Plug inserted — auto-activating in 2s" when `autoActivate === true`; manual Activate fallback preserved |
| 14 | `frontend/src/components/pedestal/PedestalView.tsx` | COMPLETE | ZoneButton reads `socketAutoActivate[key]`; tooltip for pending state switches to "Plug inserted — auto-activating in 2s" when enabled, else "Plug inserted — awaiting activation" |
| 15 | `tests/backend/test_socket_auto_activate.py` | COMPLETE (NEW) | 10 cases: default false, PATCH admin-only, auto=False no publish, auto=True publishes after delay + success log, 4 parametrised skip paths (door open, fault, heartbeat stale, diagnostic running), already-active skip, log endpoint returns 20 newest-first with correct shape |
| 16 | `tests/backend/conftest.py` | COMPLETE | Import `socket_config` + `auto_activation_log` so `Base.metadata.create_all` builds the test tables |

## Test run result: 248 passed, 0 failed (2026-04-21) — 238 existing + 10 new auto-activate cases. Drift guards pass (new event + 3 new endpoints registered in api_catalog).

## Key design outcomes

- No new DB column beyond `pedestal_configs.door_state` and the two new tables (`socket_configs`, `auto_activation_log`).
- Fault + diagnostic tracking via module-level dicts in `mqtt_handlers.py` — process-local state for a single uvicorn worker, no DB churn.
- `_handle_event_user_plugged_in` ALWAYS invokes `_maybe_auto_activate` when the flag is set (even when computed state is already active) so the "already active" skip is audited rather than silent.
- 2-second stabilisation sleep happens ONLY after the first precondition pass — fast-fail bad configurations without waiting.
- Post-sleep re-check guards against operator race (manual activate) and plug removal during the window.
- Every decision (success or each skip reason) writes one row to `auto_activation_log`; log keeps unbounded growth for now.
- Frontend toggle updates optimistically; rollback on PATCH failure.
- Warning auto-clears after 30 s OR on any transition away from pending (whichever comes first).

---
---

# Implementation Status — QR-Code Mobile Session Ownership + Real-Time Monitoring (v3.6)

## Session started: 2026-04-21

Feature scope: customer scans the QR on a physical socket → backend claims the
existing active session for that customer → mobile app shows real-time kWh /
kW / duration via per-session WebSocket. Customer app is **monitoring only** —
customer has no stop capability anywhere. Operator keeps absolute SW control
from the dashboard (admin role only for stop/override). Physical unplug via
UserPluggedOut remains the customer's only way to end a session.

**Approved design decisions (2026-04-21):**
- DB: reuse existing `Session.customer_id`; add **only** `owner_claimed_at`. Do not add `owner_user_id`.
- Customer stop is removed — `/api/customer/sessions/{id}/stop` returns 403 for customer role. No `/api/mobile/sessions/{id}/stop` endpoint at all.
- New `/api/mobile/` router for genuinely new endpoints only: `qr/claim`, `sessions/{id}/live`, `socket/{pid}/{sid}/qr`.
- Marina access control skipped; any authenticated customer may claim any socket. Phase-2 TODO in docs/mobile_api.md.
- Operator override authority = `admin` role only. `monitor` stays read-only.
- WebSocket token: 1-hour JWT, re-issued on re-claim.
- `qrcode[pil]` added to backend/requirements.txt.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `implementation_status.md` | IN PROGRESS | Feature header + per-file log (this) |
| 2 | `backend/app/models/session.py` | COMPLETE | Added `owner_claimed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)` — reuses `customer_id` per design decision |
| 3 | `backend/app/database.py` | COMPLETE | Added `("sessions", "owner_claimed_at", "DATETIME")` to `_migrate_schema` migration list |
| 4 | `backend/requirements.txt` | COMPLETE | `qrcode[pil]==8.0` added; smoke-tested PNG generation (468 bytes) |
| 5 | `backend/app/routers/customer_sessions.py` | COMPLETE | `POST /api/customer/sessions/{id}/stop` now raises 403 for every customer-authenticated call — monitoring-only model enforced at the router. Original handler body kept unreachable for future re-enable reference. |
| 6 | `backend/app/services/websocket_manager.py` | COMPLETE | `_session_subs: dict[int, set[WebSocket]]`; `subscribe_to_session`, `unsubscribe_from_session`, `broadcast_to_session(session_id, message, close_after=False)`. `disconnect()` now also removes the socket from all session sub-sets. `session_subscriber_count` property for metrics / tests. |
| 7 | `backend/app/routers/websocket.py` | COMPLETE | `/ws` now recognises `role="ws_session"` tokens (new). Extracts `session_id` claim and calls `subscribe_to_session`. Customer and anonymous modes unchanged for backwards compat. |
| 8 | `backend/app/auth/tokens.py` | COMPLETE | `create_websocket_token(session_id, customer_id)` — 1h TTL, `role="ws_session"`, includes `session_id` claim. Distinct role so the token cannot be reused against long-lived customer APIs. |
| 9 | `backend/app/routers/mobile.py` | COMPLETE (NEW) | `POST /qr/claim` branches to claimed / already_owner / read_only / no_session; `GET /sessions/{id}/live` owner-only 403 guard; `GET /socket/{pid}/{sid}/qr` admin-only PNG generation (qrcode box_size=10, ERROR_CORRECT_M); helper functions for pedestal resolve + socket validation; marina-access TODO inline comment. |
| 10 | `backend/app/services/mqtt_handlers.py` | COMPLETE | `_handle_event_telemetry_update` emits `session_telemetry` via `broadcast_to_session` (carrying duration/kwh/kw); `_handle_event_session_ended` pushes `session_ended` to subscribers with `close_after=True`; `_broadcast_socket_state` also fans out to the session channel when an active session exists for the socket |
| 11 | `backend/app/main.py` | COMPLETE | Imports `mobile` router and `app.include_router(mobile_router.router)` after customer_auth group |
| 12 | `backend/app/services/api_catalog.py` | COMPLETE | 3 endpoints (`mobile.qr_claim`, `mobile.session_live`, `mobile.socket_qr`) + 2 events (`session_telemetry`, `session_ended`) added; drift guards pass |
| 12a | `tests/backend/test_ws_event_catalog.py` | COMPLETE | `session_telemetry` + `session_ended` added to `INTERNAL_EVENTS` since they're per-session pushes only, not consumed by the dashboard switch |
| 12b | `tests/backend/test_sessions.py` | COMPLETE | `test_stop_session` now asserts 403 + tidies up via `_complete_session_direct`; cleanup calls in other tests swapped for direct DB writes |
| 12c | `tests/backend/test_workflow.py` | COMPLETE | Bulk-replaced 7 customer-stop cleanup calls with new `_complete_via_db` helper; `test_tc_stop_01` updated to assert 403 + admin-stop path; `test_tc_workflow_01` step 7 uses admin stop |
| 12d | `tests/backend/test_gap_session_fields.py` | COMPLETE | 3 customer-stop cleanup calls swapped for `_complete_via_db_gap` helper |
| 12e | `tests/backend/test_operator_approval.py` | COMPLETE | 6 customer-stop cleanup calls swapped for `_complete_via_db_op` helper |
| 12f | `tests/backend/_session_helpers.py` | COMPLETE (NEW) | Shared `complete_session` / `complete_all_active_for_pedestal` helpers |
| 13 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | Each SocketCard now shows a 📱 icon with a "Mobile owner: {name}" tooltip when the active session has a customer_id; a new `QR` button opens a modal that fetches `GET /api/mobile/socket/{pid}/{sid}/qr`, renders the PNG, shows the encoded URL, and has a Download button that saves as `{pid}_{socketName}_qr.png`. New `getSocketQrBlob` helper added in `frontend/src/api/index.ts`. |
| 14 | `mobile/app/(app)/mobile/socket/[pedestal_id]/[socket_id].tsx` | COMPLETE (NEW) | QR landing screen, 4 view states (loading / no_session / claimed / read_only / ended); WebSocket subscribe with `websocket_token`; REST polling fallback every 5 s; session_ended → summary screen. No Stop button anywhere — monitoring only. |
| 15 | `mobile/src/api/mobile.ts` | COMPLETE (NEW) | `qrClaim` + `sessionLive` wrappers + response types |
| 16 | `docs/mobile_api.md` | COMPLETE (NEW) | Full contract: base URLs, auth model (customer JWT vs ws_session JWT), QR URL format, 3 REST endpoints with request/response schemas + error matrix, WebSocket event catalog (`session_telemetry`, `session_state_changed`, `session_ended`), authority model explaining monitoring-only, `owner_claimed_at` semantics table, Phase-2 marina-access TODO |
| 17 | `tests/backend/test_mobile_qr_claim.py` | COMPLETE (NEW) | 14 cases covering: auth, 404 pedestal/socket, no_session branch, claimed / already_owner / read_only paths, owner_claimed_at persistence, websocket_token validity + session_id claim, live endpoint owner 200 / non-owner 403, admin QR PNG + customer 403, TelemetryUpdate → `session_telemetry` fan-out, SessionEnded → `session_ended` + channel close. Reuses shared conftest. |
| 18 | `README.md` | COMPLETE | Changelog v3.6 entry added; test count 262; WS events table updated with `session_telemetry` / `session_ended` mobile-only rows |

## Test run result: 262 passed, 0 failed (2026-04-21) — 248 v3.5 + 14 new mobile QR cases. Released as `c515790` to `origin/main` + `origin/develop`.

---
---

# Implementation Status — Auto-Discovery + QR Grid (v3.7)

## Session started: 2026-04-21

Feature scope: MQTT messages Opta already publishes should now auto-create
database rows for new pedestals and sockets (no manual registration), and
every socket should have a printable QR PNG on disk ready to download. The
dashboard adds a QR Codes section to Control Center and a QR icon on the
pedestal cards.

**Approved design decisions (2026-04-21):**
- Reuse existing `PedestalConfig.last_heartbeat` as `last_seen_at`. Add only `first_seen_at: DateTime` and `status: String` columns.
- Do NOT add `GET /api/pedestals/{cab}/sockets/{sid}/qr` — v3.6's `GET /api/mobile/socket/{pid}/{sid}/qr` already covers it. Only new endpoints: `GET /api/pedestals/{cab}/qr/all` (ZIP) + `POST /api/pedestals/{cab}/qr/regenerate` (admin).
- QR PNG text label is embedded only in the new disk-cached PNG. The v3.6 on-demand endpoint stays byte-identical.
- `pedestal_registered` WS event throttled to one per pedestal per 60 s so reconnect storms don't spam the dashboard.
- Tiny in-house toast component (no external lib) — single global slice in the store.
- New QR Codes section lives at the **top** of Control Center, above the cabinet-status card. Does NOT touch event log / ack log / diagnostic / health sections.
- QR icon on both `PedestalCard.tsx` grid view and the sidebar list item.

### Files — Status

| # | File | Status | Notes |
|---|------|--------|-------|
| 1 | `implementation_status.md` | IN PROGRESS | Feature header + per-file log |
| 2 | `backend/app/models/pedestal_config.py` | COMPLETE | Added `first_seen_at: Column(DateTime, nullable=True)` + `status: Column(String, nullable=True, default="online")`. Comment on `last_heartbeat` clarifies it plays the last_seen_at role per the v3.7 design decision. |
| 3 | `backend/app/database.py` | COMPLETE | Added two rows to the `_migrate_schema` migrations list: `pedestal_configs.first_seen_at DATETIME` + `pedestal_configs.status TEXT DEFAULT 'online'`. Safe idempotent ALTER per existing pattern. |
| 4 | `backend/app/services/qr_service.py` | COMPLETE (NEW) | Functions: `generate_socket_qr` (idempotent), `regenerate_socket_qr`, `get_socket_qr_path`, `generate_all_qr_for_pedestal`, `delete_all_qr_for_pedestal`, `qr_dir`. 300×300 PNG with 50px text label beneath (`{cabinet_id_spaced} — {socket_id}`). Target dir `backend/static/qr/` auto-created on import. TTF fallback to Pillow default font. Smoke-tested. |
| 5 | `backend/app/services/mqtt_handlers.py` | COMPLETE | `_cabinet_to_pedestal_id` now prettifies `name` + sets `first_seen_at`/`status` on new PedestalConfig + schedules `_announce_new_pedestal` (QR pre-gen + `pedestal_registered is_new=True`). New `_announce_pedestal_heartbeat` with 60s throttle called from `_handle_opta_status`. New `_auto_discover_socket_config` idempotently creates SocketConfig from `_handle_marina_socket` and triggers per-socket QR PNG generation on first sight. All QR/DB failures caught + logged; MQTT flow never crashes. |
| 6 | `backend/app/routers/qr.py` | COMPLETE (NEW) | Two admin-only endpoints: `GET /api/pedestals/{cab}/qr/all` (zip with 4 PNGs, `Content-Disposition: attachment; filename="{cab}_qr_codes.zip"`, auto-generates missing files) and `POST /api/pedestals/{cab}/qr/regenerate` (deletes + rebuilds, returns summary). Resolves by `opta_client_id` string, 404 on unknown cabinet. |
| 7 | `backend/app/main.py` | COMPLETE | Imports + registers `qr_router.router`. The `qr_service` module auto-creates `backend/static/qr/` on import, so no additional startup hook is needed. |
| 8 | `backend/app/services/api_catalog.py` | COMPLETE | `qr.pedestal_all` + `qr.pedestal_regenerate` endpoints added; `pedestal_registered` event added to EVENT_CATALOG. |
| 9 | `frontend/src/api/index.ts` | COMPLETE | `getPedestalQrAll(cabinetId) → Blob` and `regeneratePedestalQrs(cabinetId) → RegenerateResponse` wrappers added alongside the existing v3.6 `getSocketQrBlob`. |
| 10 | `frontend/src/store/index.ts` | COMPLETE | Global `toasts` slice with `addToast` (dedupes by id) + `removeToast`. Variants: info/success/warning/error. Supports optional `actionLabel` + `actionHref` for the "View" link on new-pedestal notifications. |
| 11 | `frontend/src/hooks/useWebSocket.ts` | COMPLETE | `case 'pedestal_registered':` adds an info toast only when `is_new=true`; dedupes via id `pedestal-registered-{cab}`. Reconnect heartbeats (`is_new=false`) are no-ops. |
| 12 | `frontend/src/components/ui/ToastContainer.tsx` | COMPLETE (NEW) | ~40-line self-contained renderer; bottom-right stack; 10 s auto-dismiss; optional action link for "View"; mounted once in `Layout.tsx`. |
| 13 | `frontend/src/components/pedestal/PedestalControlCenter.tsx` | COMPLETE | New collapsible `QrCodesSection` (+ inner `QrCell`) placed above the existing Cabinet Status card. 2×2 grid reuses v3.6's `getSocketQrBlob` endpoint per socket. Top-right buttons: Download All (calls `getPedestalQrAll`, saves `{cab}_qr_codes.zip`) and Regenerate (admin-only, calls `regeneratePedestalQrs` then bumps a nonce to refetch all 4 PNGs). Each cell has Download + Copy URL buttons. Untouched: event log, ack log, diagnostic panels. |
| 13a | `frontend/src/api/pedestalConfig.ts` + `src/store/index.ts` | COMPLETE | `PedestalHealth` type extended with `opta_client_id` so the QR section can resolve the cabinet id from the already-loaded health map (no extra fetch). |
| 13b | `backend/app/routers/pedestal_config.py` | COMPLETE | `/api/pedestals/health` response now includes `opta_client_id` per pedestal. |
| 14 | `frontend/src/components/pedestal/PedestalCard.tsx` | COMPLETE | Added a 🔖 QR icon button (shown when health has `opta_client_id`) that opens a `PedestalQrGridModal` without triggering the card's onClick. Modal reuses the new shared `SocketQrGrid` and has its own Download All button. Copy-URL feedback goes through the global toast store. |
| 14a | `frontend/src/components/pedestal/SocketQrGrid.tsx` | COMPLETE (NEW) | Shared 4-socket QR grid extracted so Control Center and the dashboard modal both reuse it (fixes DRY with the earlier inline `QrCell` duplicate). |
| 15 | `tests/backend/test_pedestal_auto_discovery.py` | COMPLETE (NEW) | 13 cases: pedestal auto-create + name prettification + operator-rename survival + last_heartbeat bump; socket auto-config creation + auto_activate=true preservation; QR PNG write on first socket + idempotency on repeat; `/qr/all` zip structure + content-disposition + PNG magic check; `/qr/regenerate` mtime proof; 404 on unknown cabinet; `pedestal_registered` is_new=true/false + 60 s throttle. `clean_fs` fixture wipes SocketConfig + PNG files to guarantee first-contact semantics across runs. |
| 16 | `README.md` | COMPLETE | Changelog v3.7 entry at top per the merge-to-main rule; test count bumped 262 → 275; WebSocket events table gains `pedestal_registered`; Test Suite bullet added for auto-discovery coverage. |

## Test run result: 275 passed, 0 failed (2026-04-21) — 262 v3.6 + 13 new auto-discovery cases. Ready for release.






