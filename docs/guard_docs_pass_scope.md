# Deferred: documentation pass scope (do NOT write yet)

**Status: NOT STARTED, deliberately.** Agreed sequence:

> **B1 approval → Stage B → UI v2 → deploy & activate → THEN documentation.**

Documentation is written **once**, after guard and UI v2 are both running and proven — not
incrementally after each piece, because that means writing it twice. This file is the
scope so nothing is forgotten in the meantime. It is a checklist, not content.

## Output format

- **One source of truth in the repo: Markdown.**
- **PDF exported from that Markdown**, never hand-maintained in parallel.
- Existing precedent to reuse: `scripts/generate_*.py` + reportlab (already a dependency),
  which is how `Cloud_IOT_ERP_Integration_Guide_v3.pdf` and `Pedestal_User_Guide_v1.1.pdf`
  are produced. Add a generator rather than inventing a second mechanism.

## Coverage required

### README
- The guard worker as a **separate service**: what it is, why it is separate.
- Start / stop / check: `systemctl {start,stop,status} cloud-iot-guard`, where its logs go.
- All new config variables (see `guard_b1_design.md` §11), split runtime-changeable vs
  start-time-only.
- The **two-process architecture and why**: fault isolation, provable model release,
  kernel-enforced CPU ceiling, openvino kept out of the production venv.

### Installation guide
- `cloud-iot-guard.service` setup.
- **Staging vs production venv** distinction and why it exists.
- openvino install (`requirements-vision.txt`, explicitly not `requirements.txt`).
- Model IR placement and how to produce it (`guard_export_model.sh`, Docker route).
- **What `upgrade.sh` does and does not install** — this is where people will get caught.
- First-run checks.

### ERP / API guide
- Guard MQTT topics and REST endpoints.
- The **CORE vs EXTENDED split** agreed for the UI work, documented **in that order**.

### Operations
- Watchdog states: `SUSPENDED_CPU`, `NO_DISK`, `LIMITED_VISIBILITY` — what each means and
  **what the operator actually does** about it.
- Retention and disk policy.

### Known limitations, stated plainly
- **Night is unsupported on the current camera** (no IR illuminator, poor sensor), with the
  hardware requirement to fix it — i.e. an IR or low-light camera, a procurement decision.
- **Guard is not a certified fire or intrusion alarm system.**
- Detection accuracy figures **with the date they were measured**.

### The measured numbers, so future-me knows what was true when
Measured 2026-09-26 on marina-iot (Atom x7425E, 4 cores, Python 3.14.4, openvino 2026.4.0):

| Metric | Value |
|---|---|
| CPU per inference, 1 thread | **273.3 ms** |
| CPU per inference, OpenVINO default (~4 threads) | 390.1 ms |
| Wall per inference, 1 thread | 239.1 ms |
| CPU time / wall time, 1 thread | 1.00 cores (exactly one core) |
| Load at 1 fps, 1 thread | **6.8 % of 4 cores** |
| False alarms, 600 s unattended control clip | **0** (0.00/hour) |
| Frame false-positive rate | 0.000 (0/1200) |
| Inference wall, 4-thread run | mean 91.0 ms, p95 101.5, max 162.1 |
| Drift over 10 minutes | none |
| Class map | class 0 = person, class 8 = boat, 80 classes |
| Person-clip rows (recall, px height, latency, partial/crouch) | **PENDING — fill in when measured** |

**Environment versions to state (dev and production diverged once already):**

| Component | Version |
|---|---|
| ffmpeg on marina-iot | **8.0.1-3ubuntu2** (observed 2026-09-26) |
| openvino | 2026.4.0 |
| Python | 3.14.4 |
| numpy | 2.4.6 |

The ffmpeg version matters: TC-GCAP-14 behaved differently on the NUC than on the dev box,
because ffmpeg handles SIGTERM gracefully and writes a valid MP4 trailer. The ring is
mpegts to survive **SIGKILL and power loss**, not SIGTERM — state that correctly in the
docs, and state that guard records **no audio, by policy** (pontoon conversations are a
separate legal question from video), enforced by `-map 0:v:0 -an -dn -sn` on every output.

### Known limitation to document: the accepted ffmpeg timestamp deprecation

**What the notice is.** On every copy-mux from this camera, ffmpeg 8.0.1 emits:

```
[segment @ 0x...] Timestamps are unset in a packet for stream 0.
This is deprecated and will stop working in the future.
```

**Why we accept it.** Diagnosed 2026-09-27 with `scripts/guard_diagnose_timestamps.py`
across 12 variants against the real stream: **eleven variants using `-c:v copy` emit it,
including one with no segment muxer at all.** So it is not the segment muxer and not
`-reset_timestamps` — this camera sends packets without timestamps, `-c:v copy` passes
them through untouched, and ffmpeg 8 reports it on every copy mux. No input option can fix
it, because copy never restamps. `-use_wallclock_as_timestamps` was tried and does not help.

The only thing that silences it is **re-encoding**, and re-encoding 1080p25 continuously
costs an order of magnitude more than the 273 ms per inference the detector was carefully
measured against — it would break the <15 %-of-4-cores target outright. **Trading the
entire CPU budget to silence a warning is the wrong trade.**

**What breaks if a future ffmpeg enforces it.** Segmenting stops, so the ring retains no
history and an alarm would have no video. This is why `SegmentHealth` exists and why step
4's watchdog reports `UNAVAILABLE` when segments stop being produced — the failure is loud,
not silent. Worth having anyway: a full disk, a permissions change or a camera that stops
delivering keyframes stall the ring identically.

**The fix at that point** is a camera that stamps its packets, or re-encoding with the CPU
cost accepted and the budget revisited.

**Re-check after ANY ffmpeg upgrade** — one command, exit 0 means capture still works:

```bash
python3 scripts/guard_diagnose_timestamps.py --url <rtsp> --verify
```

Add that to the post-upgrade checklist. Pinned version at time of decision:
**ffmpeg 8.0.1-3ubuntu2**.

**Camera-replacement spec item:** the demuxer reports video `start 0.074267`, so the camera
does have container-level timing — but the packets themselves arrive unstamped. If this
camera is ever replaced, **packet timestamping is a requirement to check**, along with an
IR illuminator for night coverage.

### REQUIRED: post-upgrade checklist, as a named operator task

This must appear in the Operations section as a **checklist item someone will read**, not
as a script that happens to exist. The person who runs `apt upgrade` is not going to be
reading `capture.py`.

> **After any system upgrade that touches ffmpeg, run:**
> ```bash
> python3 ~/Cloud_IOT/scripts/guard_diagnose_timestamps.py \
>     --url 'rtsp://admin:PASS@192.168.1.191:554/profile1' --verify
> ```
> **Exit 0 = guard capture still works. Non-zero = read the output before trusting guard.**

It checks four things against the real camera: segments are still being produced, a
completed segment still decodes, no audio reached disk, and no *new* deprecation appeared.

Why it matters: guard accepts a known ffmpeg deprecation (unstamped packets from this
camera — see the known-limitations section). If a future ffmpeg **enforces** it, segmenting
stops and the ring retains no history, so an alarm would have no video. The runtime
watchdog reports that as `UNAVAILABLE`, but this command catches it at upgrade time instead
of at alarm time.

Put it in the same list as any other post-upgrade verification, alongside
`systemctl status cloud-iot-guard`.

### Camera capabilities and future options

Carry `docs/guard_camera_capabilities.md` into the final docs under a heading of that
name. It records the ONVIF investigation of 2026-09-27: the camera exposes Events and
Analytics with working rule topics (`ObjectsInside`, `LineDetector/Crossed`,
`CellMotionDetector/Motion`, `MotionAlarm`, plus `GlobalSceneChange`/`ImageTooBlurry` as
possible tamper signals) but **no person/object classification topic** — its own AI
detection is only on an undocumented vendor protocol on port 8080.

Not used in Phase 1, deliberately: `ObjectsInside` would be a trigger rather than a
detection, guard is not always armed, 6.8 % of 4 cores is already inside budget, and a
trigger would confound the first accuracy measurements. Revisit after a week of production
data. The design sketch for that day is in the file — **trigger as accelerator, never as
precondition**, with the segment ring always running so pre-roll exists.

Also records camera-replacement spec items: packet timestamping, AI classification over
ONVIF, IR illuminator, concurrent RTSP sessions.

### Standing rule to write down (earned the hard way, four times)

**For anything touching the camera or ffmpeg: a dev-box run proves NOTHING. Only a NUC run
counts, and a step is not done until it is green there.**

And the sharper form, because it is the part that actually misled: **on the dev box these
tests SKIP, they do not pass.** There is no ffmpeg installed, so every ffmpeg-gated test
reports `skipped`. A summary line like *"760 passed, 6 skipped"* reads as reassuring while
saying nothing at all about the six that matter most — and those six are exactly the ones
that failed every time. **Count the skips and name them; a skip is an unanswered question,
not a pass.**

Four consecutive failures, all invisible on the dev box:

| # | What broke | Dev box | Real NUC / camera |
|---|---|---|---|
| 1 | `-reconnect` on an RTSP input | harmless on lavfi/file | **fatal** — ffmpeg 8.0.1 refuses to start; 0 frames, 0 segments, 0 bytes |
| 2 | rawvideo into `-c:v copy` | failed **silently**, left a 0-byte segment that satisfied a weak `file exists` assertion | n/a |
| 3 | mpegts + SIGKILL | 0 bytes — a tiny synthetic stream stayed inside ffmpeg's AVIO buffer | fine: a 1080p25 feed writes continuously |
| 4 | `.part` temporary + format inference | never exercised (test skipped) | **fatal** — "Unable to choose an output format for '...mp4.part'", no clip written |

**Update 2026-09-27: ffmpeg is now installed on the dev box, which closes half the gap —
but only half.** Local skips dropped from 6 to 1 (only the camera-gated `TC-GCAP-19`
remains unanswerable locally). Of the four failures above, a local ffmpeg would have caught
**#2 and #4** — both structural, neither needing a camera. **#1 and #3 still required the
real stream.**

**And there is now a VERSION SKEW to keep in mind:**

| Box | ffmpeg |
|---|---|
| dev | **9.0.2** (Gyan full build, via winget) |
| marina-iot NUC | **8.0.1-3ubuntu2** (apt) |

So a local pass can now disagree with the NUC in the *other* direction: ffmpeg 9 may have
changed a default or removed a behaviour 8 still has. The accepted timestamp deprecation is
exactly the kind of thing that could differ. **The NUC run stays a required gate** — local
ffmpeg catches structural mistakes early, it does not certify anything.

Consequences to state in the Testing/Operations section:

- **`TC-GCAP-19` (opt-in `GUARD_TEST_RTSP_URL`) and every `[ffmpeg]` test are REQUIRED
  gates**, not optional extras.
- Prefer **stating** things over letting ffmpeg infer them. Both #1 and #4 came from
  inference — protocol-option validity and format-from-extension. `-f mp4` is passed
  explicitly for exactly this reason, and an assertion pins it.
- When a synthetic test and the real camera disagree, **the camera is right** and the
  synthetic test is measuring the wrong thing.
### Earlier form of the same rule

**For anything touching the camera: a synthetic test proves the SHAPE, only the real
stream proves it WORKS.** Three consecutive failures on the capture module all came from
the same root — a synthetic source accepting what the real camera rejects:

| Symptom | Synthetic behaviour | Real-camera behaviour |
|---|---|---|
| `-reconnect` on the input | harmless on lavfi/file — every test passed | **fatal** on RTSP; ffmpeg 8.0.1 refuses to start, so 0 frames / 0 segments / 0 bytes |
| rawvideo into `-c:v copy` | failed **silently**, left a 0-byte segment | n/a — the weak assertion (`file exists`) was satisfied by the 0-byte file |
| mpegts + SIGKILL | 0 bytes: a tiny stream stayed in ffmpeg's AVIO buffer | fine: a 1080p25 feed writes continuously, completed segments always land |

So **TC-GCAP-19 (opt-in `GUARD_TEST_RTSP_URL`) is a REQUIRED gate, not an optional
extra** — the capture module is not 'done' without it, and the same rule applies to any
future camera-facing change. State this in the Operations/Testing section.

## Carry-forward tasks — separate work, NOT inside guard or UI v2

1. **`requirements.txt` drift audit.** Only numpy was fixed (`6a404b2`,
   `numpy>=2.1,<3`). Every other entry is still a `==` pin from the Python 3.12 era
   (`scikit-learn==1.5.2`, `pydantic==2.9.2`, `fastapi==0.115.0`, …) and the
   no-cp314-wheel argument applies to several. Full diff:
   ```bash
   diff <(sed 's/#.*//;/^[[:space:]]*$/d' /opt/cloud-iot/backend/requirements.txt | sort) \
        <(sort ~/venv_freeze_2026-09-26.txt)
   ```
2. **Split the pre-push gate — before retrying pushes becomes a habit.** The gate runs the
   full suite on every push and already brushes 10 minutes; one push appeared to fail while
   having actually succeeded, which is exactly the confusion to avoid. It will get worse as
   the suite grows. Proposal: fast tests on every push; full suite + the ffmpeg-gated and
   camera-gated tests on demand or before a merge to `main`. Not urgent, but note it now.

3. **TME sensor 404.** `192.168.1.254` returns HTTP 404 on `values.xml` while `fresh.xml`
   returns 200. Consistent with `tests/backend/test_tme_fresh_xml.py` (fresh.xml is the
   supported path), so likely a dead code path or a stale fallback URL to remove. Observed
   2026-09-26, not investigated.
