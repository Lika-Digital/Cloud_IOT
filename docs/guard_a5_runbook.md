# Guard A.5 — Measurement Runbook

**For:** operator on the pier, phone in hand. **Duration:** ~35 min, of which 10 min is
an unattended control recording. **Daylight only.**

**Nothing is installed into production. Nothing is merged to `main`. Nothing is written
under `/opt/cloud-iot`.** If any step asks you to, stop — it is wrong.

| | |
|---|---|
| Camera | D-Link DCS-TF2283AI-DL, 192.168.1.191, `profile1` = H.264 1080p25 |
| View | **stern of the moored boat at ~10 m**, where boarding happens |
| Out of scope | **night** (no IR, poor sensor — recorded as unsupported, not measured) |
| People needed | **minimum 1** (you). **Recommended 2**: one at the terminal, one as subject |

**Safety:** you will be walking a pier while watching a phone. Do not lean over the stern
rail for the partial-body shot — frame it by standing behind the rail, not over water.
Daylight only, which the night exclusion already enforces.

---

## Answer to your question first: no, you do not need `main` or `upgrade.sh`

The measurement reads nothing from `/opt/cloud-iot` except `pedestal.db` (opened
read-only, to find the camera URL). So:

- **Do not merge to `main`.** Correct instinct — leave it at v3.40 until the numbers earn it.
- **Do not run `upgrade.sh`.** It would deploy the detector rewrite to production, which
  is inert but pointless before the numbers exist.
- **Do not `git pull` in `~/Cloud_IOT`.** That is the tree `upgrade.sh` reads, and pulling
  by hand breaks its change detection (README: "do not git pull manually").

Use a **separate throwaway clone** instead. `upgrade.sh` and `main` stay untouched.

---

## STEP 0 — Get the code, then baseline (7 min, before anything else)

The clone comes first because `guard_baseline.sh` ships with this work — it does not
exist in whatever `~/Cloud_IOT` is currently checked out at.

```bash
git clone --branch develop --single-branch \
  https://github.com/Lika-Digital/Cloud_IOT.git ~/guard-checkout
```

```bash
cd ~/guard-checkout && git log --oneline -1
```

**STOP if:** the clone fails, or the commit is older than `1ceb280`.

Now the baseline, run from the fresh checkout:

```bash
sudo bash ~/guard-checkout/scripts/guard_baseline.sh before
```

Takes ~70 s (it samples CPU for 60 s). Saves pip freeze, CPU average, RAM, backend RSS,
service states, `USE_ML_MODELS` and live API/MQTT health to `/var/backups/guard-baseline/`.

Write these three down — you will compare them at the end:

```
cpu_avg_pct = ______    mem_used_mb = ______    backend_rss_mb = ______
```

**STOP if:** `use_ml_models` is anything other than false/unset, or any service is not
`active`. Something is already wrong; do not add guard work on top of it.

---

## STEP 1 — Confirm what you did NOT do (30 s)

The checkout happened in step 0. This step is the deliberate absence of a deploy.

```bash
cd ~/Cloud_IOT && git status --short --untracked-files=no && git log --oneline -1
```

**STOP if** `~/Cloud_IOT` shows unexpected modifications — it must be exactly as
`upgrade.sh` left it. You have not pulled it, not merged to `main`, and not run
`upgrade.sh`. Everything below runs from `~/guard-checkout`.

```bash
cd ~/guard-checkout
```

---

## STEP 2 — Verification, in order

Run these one at a time. Each says STOP (do not continue) or NOTE (record and continue).

**2.1 — ffmpeg present**

```bash
which ffmpeg ffprobe
```
**STOP if** either is missing → `sudo apt install -y ffmpeg`, then re-check.

**2.2 — camera is reachable right now**

```bash
ip neigh | grep 192.168.1.191
```
**STOP if** absent or `FAILED`/`INCOMPLETE` → the camera is off the LAN, nothing to measure.
Expect `REACHABLE` or `STALE`.

**2.3 — disk headroom for a 10-minute 1080p clip (~300 MB)**

```bash
df -h / | tail -1
```
**STOP if** available < 5 G.

**2.4 — staging setup (this is the step that installs openvino — into STAGING, not production)**

```bash
cd ~/guard-checkout
bash scripts/guard_measure.sh setup
```

It auto-detects numpy from the production venv and pins staging to match. Watch for:

```
[ ok ] numpy 2.4.6 detected from the production venv — staging will match
[ ok ] staging numpy matches production (2.4.6)
```

**STOP if** the install fails naming numpy — it means no wheel for this interpreter.
The error tells you to re-run with `GUARD_NUMPY=<version>`. **Do not remove
`--only-binary`** — a numpy source build on this box is exactly what we are avoiding.

**NOTE:** first run must produce the model IR. It now prefers a **Docker** export
(`python:3.12-slim` container, nothing installed on the host) because the NUC runs
Python 3.14 and torch may have no cp314 wheel. Expect a few minutes and ~2 GB of
container layers, all removed with `--rm`. See the FAQ to skip it entirely.

**2.5 — production genuinely untouched**

```bash
/opt/cloud-iot/backend/.venv/bin/pip list 2>/dev/null | grep -i openvino
```
**STOP if** this prints anything. openvino must NOT be in the production venv.

```bash
grep -c USE_ML_MODELS /opt/cloud-iot/backend/.env
systemctl is-active cloud-iot-backend
```
**STOP if** the service is not `active`.

**2.6 — class map proof (this is the on-disk proof class 0 is `person`)**

```bash
bash scripts/guard_measure.sh classmap
```
**STOP unless** the last line reads `VERDICT: PASS — person class present`.
Record: `class 0 = ______`  `class 8 = ______`  `openvino version = ______`

**2.7 — logic tests on production's numpy**

```bash
bash scripts/guard_measure.sh tests
```
**STOP unless** `49 passed`.

---

## STEP 3 — Measurement (physical)

For every clip: **start the command, then walk.** The recorder runs for the stated
seconds and exits on its own. Note the **second you entered frame** — you need it for
`--person-enters-at`.

### 3.1 Main case — stern approach (30 s)

```bash
bash scripts/guard_measure.sh record 30 /tmp/stern.mp4
```
Physically: wait ~5 s out of frame → walk into the stern boarding area → stand still
3–5 s → walk out. Note your entry second (about 5).

```bash
bash scripts/guard_measure.sh probe --clip /tmp/stern.mp4 \
  --expect person --person-enters-at 5 --save-annotated /tmp/boxes_stern
```

### 3.2 Partial body — upper body only behind the stern rail (20 s)

```bash
bash scripts/guard_measure.sh record 20 /tmp/partial.mp4
```
Physically: stand **behind** the stern rail so roughly only your upper body is visible.
Hold ~10 s. Do not lean over the water.

```bash
bash scripts/guard_measure.sh probe --clip /tmp/partial.mp4 \
  --expect person --person-enters-at 3
```

### 3.3 Crouching on the stern deck (20 s)

```bash
bash scripts/guard_measure.sh record 20 /tmp/crouch.mp4
```
Physically: crouch on the stern deck as someone would handling a line. Hold ~10 s.

```bash
bash scripts/guard_measure.sh probe --clip /tmp/crouch.mp4 \
  --expect person --person-enters-at 3
```

### 3.4 Control — nobody in view (10 min, unattended)

**Before starting, confirm nobody will walk through the camera's view for 10 minutes** —
including you. This is the false-alarm number; one person wandering past invalidates it.

```bash
bash scripts/guard_measure.sh record 600 /tmp/empty.mp4
```

```bash
bash scripts/guard_measure.sh probe --clip /tmp/empty.mp4 --expect none
```

### 3.5 Crop comparison (no recording needed)

```bash
bash scripts/guard_measure.sh probe --clip /tmp/stern.mp4 --expect person --no-zone
```
Confirms whether the zone crop is actually buying the range Stage A predicted.

### 3.6 Look at the pictures

```bash
ls /tmp/boxes_stern/
```
Open two or three. **If the boxes are on gulls, fenders or reflections rather than on
you, the numbers are lying** — say so and stop. This check matters more than any figure
below.

**NOTE:** during each probe the NUC CPU will spike; berth occupancy polls every 10 s and
may lag slightly. Expected and temporary.

---

## STEP 4 — Pass / fail, as numbers

Fill this in and send it back. Thresholds, not adjectives.

| # | Metric | Source | PASS | INVESTIGATE | FAIL | Yours |
|---|---|---|---|---|---|---|
| 1 | class 0 name | 2.6 | `person` | — | anything else | |
| 2 | logic tests | 2.7 | 49 passed | — | any failure | |
| 3 | person px height, median | 3.1 | ≥ 100 px | 40–99 px | < 40 px | |
| 4 | frame recall, stern | 3.1 | ≥ 0.80 | 0.50–0.79 | < 0.50 | |
| 5 | alarms, stern clip | 3.1 | exactly 1 | ≥ 2 | 0 | |
| 6 | end-to-end latency | 3.1 | ≤ 5.0 s | 5.1–10 s | > 10 s | |
| 7 | **alarms, control clip** | 3.4 | **0** | — | ≥ 1 | |
| 8 | false alarms/hour | 3.4 | 0.00 | — | > 0 | |
| 9 | frame FP rate, control | 3.4 | ≤ 0.05 | 0.06–0.15 | > 0.15 | |
| 10 | **CPU ms per inference** | 3.1 | ≤ 300 ms | 301–600 ms | > 600 ms | |
| 11 | inference ms (wall), mean | 3.1 | ≤ 500 ms | 501–1000 ms | > 1000 ms | |
| 12 | partial body alarms | 3.2 | 1 | 0 | — | |
| 13 | crouching alarms | 3.3 | 1 | 0 | — | |

**Where the numbers come from:**

- **#3 = 150 px expected.** Geometry for a 1.7 m person at 10 m with the zone crop. The
  probe prints this expectation and flags below 100 px. Far below means the crop, framing
  or distance is not what we think — a setup problem, not a model problem.
- **#10 = the Stage B CPU budget, worked backwards.** Target is < 15 % of 4 cores when
  armed = 600 ms CPU per wall-second. At 2 fps that is **300 ms CPU per inference**.
  301–600 ms means we run at **1 fps** instead (2 detections in 3 s still works: t=0,1,2).
  Over 600 ms means neither rate fits and we reduce `imgsz` or revisit the approach.
- **#7 is the hard gate.** A guard that cries wolf gets switched off and then protects
  nothing. One false alarm in 10 min extrapolates to 6/hour — the probe warns when a rate
  is extrapolated from a short clip, which is why the control clip is 10 min, not 30 s.
- **#12/#13 are NOTE, not STOP.** Full-body boarding is the main case. If partial and
  crouching both miss, that is a stated Phase 1 limitation to decide on, not a blocker.

**Overall:** any FAIL in 1, 2, 5, 7, 8, 10 → Stage B does not start; send the numbers and
we adjust. INVESTIGATE values are a conversation, not a stop.

---

## STEP 5 — Rollback and verify

Because nothing entered production, rollback is deletion.

```bash
cd ~/guard-checkout && bash scripts/guard_measure.sh clean
```
Run the verification below **before** deleting the checkout — the baseline script
lives inside it.

```bash
# rm -rf ~/guard-checkout   # <- do this LAST, after step 5 verification
rm -f /tmp/stern.mp4 /tmp/partial.mp4 /tmp/crouch.mp4 /tmp/empty.mp4
rm -rf /tmp/boxes_stern /tmp/guard_probe_results.json
```

**Keep `/tmp/guard_probe_results.json` if you have not sent me the numbers yet** — it has
the per-frame detail.

### Verify the rollback worked

```bash
sudo bash ~/guard-checkout/scripts/guard_baseline.sh after
```

Expect, in the BEFORE vs AFTER block:

| Check | Required |
|---|---|
| Packages added/removed | **`none — production venv unchanged`** |
| Services | **`identical to baseline`** |
| `use_ml_models` | unchanged (false/unset) |
| `cpu_avg_pct` | within a few points of Step 0 |
| `backend_rss_mb` | within ~50 MB of Step 0 |

Then three independent confirmations:

```bash
/opt/cloud-iot/backend/.venv/bin/pip list | grep -ci openvino
```
**must print `0`**

```bash
diff <(sort ~/venv_freeze_2026-09-26.txt) \
     <(/opt/cloud-iot/backend/.venv/bin/pip freeze | sort)
```
**must print nothing**

```bash
ls /opt/cloud-iot/backend/models 2>&1
df -h / | tail -1
```
models dir should be **absent** (or unchanged), and disk back to roughly Step 0.

**Finally, confirm the marina still works** — open the dashboard through the tunnel,
check a pedestal loads, and run one berth analyse. If anything looks off, say so
immediately; `~/guard-checkout/scripts/guard_baseline.sh rollback` exists but should not be needed, because
nothing was installed to roll back.

---

## FAQ

**Q: Does `setup` need torch for the measurement?**
**No — only for the one-time IR export.** The measurement venv needs just openvino +
numpy + Pillow (~200 MB). torch is used by `guard_export_model.sh` to convert
`yolov8n.pt` into an OpenVINO IR, in a throwaway `/tmp` venv that is deleted afterwards.
Three cases:

1. **IR already staged** → export skipped entirely, no torch. The script prints
   `export SKIPPED (no torch needed)`.
2. **You have an IR from elsewhere** → skip torch on the NUC completely:
   ```bash
   GUARD_IR_SRC=/path/to/yolov8n_openvino bash scripts/guard_measure.sh setup
   ```
   The IR is only ~12 MB, so exporting on any 64-bit machine and copying it over is the
   lightest path.
3. **First run, no IR** → the export runs, and by default **inside Docker**
   (`python:3.12-slim`), so nothing lands on the host and the Python-3.14 torch
   wheel question never arises. Add `--venv` to use a throwaway `/tmp` venv instead;
   that route now passes `--only-binary=:all:` so a missing wheel fails in seconds
   rather than starting a multi-hour torch source build on this CPU.

**Q: Why `$HOME/guard-staging` and not `/tmp`?**
Ubuntu mounts `/tmp` as tmpfs on many installs. The 4 GB export would then be 4 GB of
**RAM** on a 14 Gi box. `/` has 397 G free. Override with
`GUARD_STAGING=/tmp/guard-staging` if you know `/tmp` is disk-backed.

**Q: Night?**
Out of scope. No IR illuminator, poor sensor. Recorded as unsupported on this hardware —
a hardware limitation to state in the product, not a test to fail. If night coverage is
wanted later it needs an IR-illuminated or low-light camera, which is a procurement
decision, not a software one.

**Q: Something went wrong mid-measurement. Safe to stop anywhere?**
Yes. Every step is either read-only or confined to `~/guard-staging`, `~/guard-checkout`
and `/tmp`. Stop, run Step 5, and report where you got to.
