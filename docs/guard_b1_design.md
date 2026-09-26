# Guard Phase 1 — B1 Design, for approval before any code

**Date:** 2026-09-26 · **Status:** awaiting approval. **No implementation code written.**

Settings fixed: `GUARD_FPS=1`, `GUARD_WINDOW_SECONDS=4`, `GUARD_FRAMES_REQUIRED=2`,
threads=1. 2 fps / 3 s is the documented reserve, reachable by changing runtime config
only — no switch built for it.

Six things in this document need a yes. They are marked **[DECIDE]** and collected in §10.

---

## 1. Process split

| | `cloud-iot-backend.service` (exists) | `cloud-iot-guard.service` (new) |
|---|---|---|
| Runs as | `cloud-iot` | **`guard`**, group `cloud-iot` |
| Venv | `/opt/cloud-iot/backend/.venv` — **openvino never enters it** | `/opt/cloud-iot/guard/.venv` |
| Owns | all DB writes, REST, WebSocket, desired guard state | ffmpeg, inference, alarm decision, recording files, retention |
| Network | tunnel, ERP webhooks, MQTT | **MQTT + camera only** (egress blocked) |

`app/guard/` inside the backend is control and query only:

```
backend/app/guard/
  __init__.py
  models.py      # SQLAlchemy: guard_config, guard_events, guard_detections, guard_recordings
  router.py      # REST endpoints (§6)
  service.py     # desired-state logic, worker liveness, MQTT publish/subscribe handlers
  pipeline.py    # SHARED per-frame pipeline — imported by the worker AND the probe (§8)
  alarm_rule.py  # evaluate_alarm_rule(), promoted from scripts/guard_detect_probe.py
```

The worker lives outside the backend package so it never imports FastAPI:

```
guard_worker/
  __main__.py    # entrypoint; reads config at start, connects MQTT, waits for desired state
  capture.py     # the single persistent ffmpeg + segment ring
  recorder.py    # clip assembly from segments, retention
  watchdog.py    # CPU / disk / visibility sampling
  (imports app.guard.pipeline and app.guard.alarm_rule from the repo)
```

**[DECIDE 1]** dedicated `guard` user with shared group `cloud-iot`, rather than running
the worker as `cloud-iot`. Costs a few installer lines; buys real privilege separation
for the component that runs a large C++ library and talks to the camera. Recordings dir
`guard:cloud-iot`, mode `2750` (setgid) so the backend can read but not write.

## 2. The systemd unit

```ini
[Unit]
Description=Cloud IoT Guard — camera person detection worker
Documentation=https://github.com/Lika-Digital/Cloud_IOT
# Ordering only, NOT a hard dependency: guard must boot whether or not the backend
# is healthy, and must survive the backend restarting under it.
After=network-online.target docker.service cloud-iot-compose.service
Wants=network-online.target cloud-iot-compose.service

[Service]
Type=simple
User=guard
Group=cloud-iot
WorkingDirectory=/opt/cloud-iot/guard
EnvironmentFile=/opt/cloud-iot/guard/guard.env
ExecStart=/opt/cloud-iot/guard/.venv/bin/python -m guard_worker

Restart=on-failure
RestartSec=5
# Do not thrash if it is crash-looping — let it stay down and be visible as UNAVAILABLE.
StartLimitIntervalSec=300
StartLimitBurst=5

# ── Resource ceiling: this IS the <15 %-of-4-cores acceptance budget, kernel-enforced.
#    CPUQuota is % of ONE cpu. 60 % of one core = 15 % of this 4-core box.
#    Measured need: 27.3 % of one core at 1 fps, 47.8 % at 2 fps — both fit.
CPUQuota=60%
MemoryMax=1G
Nice=10
IOSchedulingClass=idle

# ── Egress: localhost (MQTT) and the camera LAN only. Makes phoning home impossible
#    regardless of any library's telemetry defaults, now or in a future version.
IPAddressDeny=any
IPAddressAllow=localhost 192.168.1.0/24
Environment=OPENVINO_TELEMETRY_OPT_OUT=1

# ── Filesystem: writes exactly one place.
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/marina-guard
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Deliberate choices: `Restart=on-failure` not `always`, so a clean exit on disarm is not
fought; `StartLimitBurst` so a crash-loop settles into a visible UNAVAILABLE rather than
hammering the box; no `Requires=` on the backend, per "boot-start independent".

`guard.env` holds `GUARD_NUM_THREADS` — read at worker start, so changing it is a config
edit plus a worker restart, never a code change.

## 3. States

One state, plus independent health flags.

| State | Meaning | Detection running? |
|---|---|---|
| `OFF` | disarmed | no — ffmpeg stopped, model unloaded |
| `ARMING` | command sent, worker has not confirmed | no |
| `ARMED` | running, nothing detected | yes |
| `ALARM` | alarm rule fired | yes |
| `RECORDING` | clip being assembled | yes |
| `SUSPENDED_CPU` | watchdog shed guard | no — model released |
| `NO_DISK` | below disk floor | **yes** — detection and alarms continue, recording only is disabled |
| `UNAVAILABLE` | worker not answering | unknown — **never rendered as ARMED** |

**[DECIDE 2]** `LIMITED_VISIBILITY` as a **health flag, not a state.** The guard can be
armed *and* have poor visibility, so making it a state would force a false choice against
`ARMED`. As a flag it appears as an amber chip beside the badge, in `guard/health`, and in
`/api/guard/status`. Detection keeps running and every event raised during it is stamped
`limited_visibility=true`, so a weak detection is explainable rather than mysterious.
Detected from the frames we already decode: mean luma below `GUARD_VISIBILITY_MIN_LUMA`
(default 30/255) or Laplacian variance below `GUARD_VISIBILITY_MIN_VARIANCE` (default 15)
for `GUARD_VISIBILITY_GRACE_S` (default 60). That covers dusk, a covered lens and heavy
fog — and it is how the system *says* it is in the unsupported night condition instead of
silently failing to detect.

## 4. MQTT contract

`{M}` = `MARINA_ID` from config (not derived). `{cam}` = `camera_id`.
QoS 1 throughout. Client id `guard-worker-{cam}`, keepalive 30 s.

| Topic | Dir | Retained | Payload |
|---|---|---|---|
| `marina/{M}/camera/{cam}/guard/cmd` | backend → worker | **NO** | `{"cmd":"arm"\|"disarm"\|"rearm", "req_id":"uuid", "config":{...}, "ts":"…Z"}` |
| `marina/{M}/camera/{cam}/guard/ack` | worker → backend | no | `{"req_id":"uuid", "accepted":true, "state":"ARMED", "reason":null, "ts":"…Z"}` |
| `marina/{M}/camera/{cam}/guard/state` | worker → backend | **YES** | `{"state":"ARMED", "since":"…Z", "flags":["limited_visibility"], "config_version":7, "ts":"…Z"}` |
| `marina/{M}/camera/{cam}/guard/health` | worker → backend | no | `{"cpu_pct_60s":6.8, "proc_cpu_pct":27.3, "rss_mb":410, "disk_free_gb":381, "disk_free_pct":87, "visibility":{"luma":112,"variance":240}, "inference_ms_p95":101, "ts":"…Z"}` every 5 s |
| `marina/{M}/camera/{cam}/guard/alarm` | worker → backend | no | `{"event_uuid":"…", "camera_id":1, "berth_id":3, "confidence":0.81, "px_height":152, "bbox":[…], "detected_at_utc":"…Z", "detected_at_local":"…", "trigger":"2_in_4s", "frame_path":"…", "video_path":"…"\|null, "video_skipped":false, "limited_visibility":false}` |
| `marina/{M}/camera/{cam}/guard/detection` | worker → backend | no | batched: `{"detections":[{"ts":"…Z","confidence":0.31,"px_height":88,"bbox":[…],"band":"uncertain","frame_path":"…"\|null}]}` |
| `marina/{M}/camera/{cam}/guard/recording` | worker → backend | no | `{"event_uuid":"…", "file_path":"…", "started_at":"…Z", "duration_s":42.0, "file_size":31457280}` |
| `marina/{M}/camera/{cam}/guard/retention` | worker → backend | no | `{"deleted":[{"file_path":"…","reason":"max_days"\|"max_gb","bytes":…}]}` |

**Retained, deliberately, and only on `state`.** v3.40 taught us retained ≠ alive, so:

- **Last Will** is set on `guard/state`, retained, payload
  `{"state":"UNAVAILABLE","reason":"lwt","ts":null}`. If the worker dies, the broker
  overwrites the retained state with the truth, so a late subscriber can never read a
  stale `ARMED`.
- `guard/cmd` is **not** retained. A retained command would be replayed to a restarting
  worker and could arm it with nobody having asked — precisely the v3.40 failure shape.
- The backend also treats retained `state` as *last known*, never as liveness; liveness
  comes from §7.

**Correction to the brief:** the pedestals do **not** use Last Will — `mqtt_client.py` sets
no `will_set`, and cabinet liveness is the 15 s `opta/status` heartbeat plus
`_comm_loss_watchdog`. For guard I am proposing **both**: LWT for near-instant detection,
and a heartbeat because LWT only fires on a broker-detected disconnect (up to a keepalive
interval, and not at all if the process wedges while its socket stays open).

## 5. The backend is the only DB writer — confirmed

The worker never opens a database. It publishes; `app/guard/service.py` subscribes and
writes. Rules:

- `guard/alarm` → insert `guard_events`
- `guard/recording` → insert `guard_recordings`, link to event
- `guard/detection` → batch-insert `guard_detections` in **one transaction per batch**
  (worker batches every 5 s) so the marina's session writes are not contended per frame
- `guard/retention` → mark rows deleted + write an `error_logs` audit line per file
- `guard/state`, `guard/ack`, `guard/health` → update in-memory state, persist only
  `guard_config.desired_state` changes

**Files are the one exception, and the split is clean:** the worker *owns*
`/var/lib/marina-guard/` — it writes recordings, annotated frames, and performs retention
deletion. The backend only **reads** them to serve. So there is a single writer for the
DB and a single writer for the files, and they are different processes with no overlap.

## 6. REST surface

Approved list, plus three additions the new requirements force:

| Method | Path | Notes |
|---|---|---|
| GET | `/api/guard/status` | per camera: enabled, state, flags, last_alarm, live cpu/mem/disk, worker_seen_at |
| POST | `/api/guard/{camera_id}/enable` | 202 + `req_id`; state goes `ARMING` |
| POST | `/api/guard/{camera_id}/disable` | 202 + `req_id` |
| GET | `/api/guard/events?limit=&offset=` | + `label` and `video_skipped` per row |
| GET | `/api/guard/events/{id}/video` | serves the recording |
| **GET** | **`/api/guard/events/{id}/frame`** | **NEW** — the annotated JPEG with the box drawn. Requirement 3 needs it visible in the dashboard. |
| **POST** | **`/api/guard/events/{id}/label`** | **NEW** — `{"label":"correct"\|"false_alarm","note":"…"}`. This is the labelled dataset from day one. |
| **POST** | **`/api/guard/{camera_id}/rearm`** | **NEW** — manual re-arm after a watchdog suspension, per B4's "stays suspended until a human re-enables it". Distinct from `enable` so the auto-resume counter is reset deliberately. |
| **GET** | **`/api/guard/detections?since=&min_confidence=`** | **NEW** — the below-threshold log. These are the missing A.5 rows and the Phase 2 training set. |
| **PATCH** | **`/api/guard/{camera_id}/config`** | **NEW** — runtime thresholds without redeploy (requirement 1): confidence, fps, window, frames_required, crop zone. Persisted, version-stamped, pushed to the worker in the next `cmd`. |

Roles: reads `require_any_role`; enable/disable/rearm/config `require_control`; labelling
`require_any_role` (a monitor watching the dashboard is exactly who should mark a gull).

## 7. Arm / disarm chain, and how a false ARMED is impossible

```
UI toggle ON
  → POST /api/guard/1/enable
      backend: guard_config.desired_state = ARMED, config_version += 1
               publish guard/cmd {cmd:arm, req_id, config}
               state := ARMING, push WebSocket guard_state_changed
      → 202 {req_id, state:"ARMING"}            UI badge: ARMING (spinner)

  worker: receives cmd → starts ffmpeg → loads model (for_guard, threads=1)
        → publish guard/ack {req_id, accepted:true, state:"ARMED"}
        → publish guard/state {state:"ARMED"} (retained)

  backend: on ack → state := ARMED, push WebSocket    UI badge: ARMED
```

**Timeouts — the thing that prevents a lie:**

| Condition | Threshold | UI result |
|---|---|---|
| No `ack` for a `req_id` | **5 s** | `UNAVAILABLE` + "Guard unavailable — worker did not acknowledge". Desired state stays ARMED so it arms when the worker returns. |
| No `health` heartbeat | **15 s** (3 missed at 5 s) | `UNAVAILABLE`, regardless of what retained `state` says |
| Broker sees worker drop | LWT, ≤ keepalive 30 s | retained `state` becomes `UNAVAILABLE` |
| Worker wedged, socket alive | heartbeat gap catches it | `UNAVAILABLE` |

**A worker that died while armed** is therefore caught three independent ways: LWT
overwrites the retained state; the heartbeat gap trips at 15 s; and on backend restart the
backend reads retained `state` but will not render `ARMED` unless a heartbeat has arrived
**since its own start** — `worker_seen_at` is in-memory and deliberately not persisted, so
a stale retained `ARMED` can never survive a restart as truth. That is the v3.40 lesson
applied directly.

`UNAVAILABLE` is never rendered as ARMED, and the UI shows the reason plus
`worker_seen_at`. Disarm mirrors the same flow; if the worker is unavailable the backend
records `desired_state=OFF` and the worker honours it on reconnect before arming anything.

On worker start: **always OFF.** It announces itself and waits for the backend to send
desired state. A guard suspended by the watchdog comes back `SUSPENDED_CPU` because the
backend holds that fact — never silently armed.

## 8. One code path for probe and worker

`app/guard/pipeline.py` holds the per-frame work — crop → letterbox → detect → per-frame
result — and `app/guard/alarm_rule.py` holds `evaluate_alarm_rule()` promoted from the
probe. Both the worker and `guard_detect_probe.py` import them. Replaying a clip and
running live differ only in where frames come from and in wall-clock timestamps.

**Hard constraint on those two modules: stdlib + numpy + PIL at import time only.** No
fastapi, no sqlalchemy. That is what keeps the probe runnable from the staging venv, which
we proved in A1 and which the measurement flow depends on. A test will assert it, so a
future import cannot quietly break the isolation.

## 9. Phase 2 hooks — designed, not built

| Requirement | How Phase 1 satisfies it |
|---|---|
| detections carry confidence + frame reference, not a boolean | `guard_detections` row = confidence, px_height, bbox, `frame_path`, `band`. No boolean anywhere. |
| uncertain distinguishable from "nothing there" | `band` ∈ `uncertain` (`GUARD_UNCERTAIN_MIN` ≤ c < threshold) / `alarm` (≥ threshold). A frame with no detection writes **no row** — absence is absence, never confused with a weak hit. |
| alarm decision separate and replaceable | `alarm_rule.py` consumes `(timestamp, detected)` and knows nothing about models. Swapping it — or escalating to a central GPU before deciding — touches one module. |
| frame retrievable for uncertain events | Frames saved for `uncertain` and `alarm` bands under the same retention budget, rate-limited (§10 DECIDE 4). |

No escalation client, no retraining loop, no central anything.

## 10. Decisions I need

1. **[DECIDE 1] Dedicated `guard` user** (group `cloud-iot`) rather than running as
   `cloud-iot`. Recommend yes — privilege separation for the component running a large
   native library, at the cost of a few installer lines.
2. **[DECIDE 2] `LIMITED_VISIBILITY` as a health flag, not a state** (§3). Recommend yes;
   as a state it would have to compete with `ARMED`, which is wrong because detection
   keeps running.
3. **[DECIDE 3] Four extra REST endpoints** (`/frame`, `/label`, `/rearm`,
   `/detections`, `PATCH /config` — five in total) beyond your list. All are forced by
   requirements 1–3; flagging rather than adding silently.
4. **[DECIDE 4] Frame-saving budget.** Logging every detection is cheap (~12 k rows/day
   worst case, ~2.4 MB); saving a frame for every one is not (~50 KB × 12 k = 600 MB/day).
   Proposal: save frames only for `uncertain` and `alarm` bands, **rate-limited to one
   frame per 10 s per camera**, inside the existing `GUARD_MAX_GB` with a sub-cap
   `GUARD_MAX_FRAMES_GB` (default 2 GB), oldest-first eviction. Bounds it at ~8.6 k
   frames/day worst case, ~430 MB, and still captures every alarm.
5. **[DECIDE 5] `guard_detections` retention.** `GUARD_DETECTION_RETENTION_DAYS`
   default 30, independent of recording retention, because the rows are the Phase 2
   training index and outlive the video. ~72 MB/month worst case in `pedestal.db`.
6. **[DECIDE 6] Notifications.** Requirement 4 says marina notifications stay off for a
   week. Proposal: `GUARD_NOTIFY_ENABLED=false` shipped, and Phase 1 **builds no
   notification path at all** — no push, no email, no ERP webhook. The dashboard and MQTT
   are the only outputs. Nothing to accidentally enable. Confirm that is what you want
   rather than a built-but-disabled channel.

## 11. Config (B6 plus what the new requirements need)

Runtime-changeable via `PATCH /api/guard/{cam}/config`, version-stamped, pushed to the
worker — **no redeploy**: `GUARD_CONF_THRESHOLD` (0.5), `GUARD_FPS` (1),
`GUARD_WINDOW_SECONDS` (4), `GUARD_FRAMES_REQUIRED` (2), crop zone, `GUARD_UNCERTAIN_MIN`
(0.2), `GUARD_LOG_MIN_CONFIDENCE` (0.2), `GUARD_COOLDOWN_SECONDS` (60),
`GUARD_VISIBILITY_MIN_LUMA` (30), `GUARD_VISIBILITY_MIN_VARIANCE` (15),
`GUARD_VISIBILITY_GRACE_S` (60).

Start-time only (worker restart to change): `MARINA_ID`, `GUARD_NUM_THREADS` (1),
`GUARD_STORAGE_PATH` (`/var/lib/marina-guard/recordings/{camera_id}/`),
`GUARD_RECORD_SECONDS` (60), `GUARD_SEGMENT_SECONDS` (10), `GUARD_SEGMENT_RING` (6),
`GUARD_RETENTION_DAYS`, `GUARD_MAX_GB`, `GUARD_MAX_FRAMES_GB` (2),
`GUARD_DETECTION_RETENTION_DAYS` (30), `GUARD_CPU_WARN` (50), `GUARD_CPU_LIMIT` (60),
`GUARD_CPU_RESUME` (45), `GUARD_RESUME_AFTER` (300), `GUARD_MAX_AUTO_RESUMES` (2),
`GUARD_DISK_MIN_GB` (5), `GUARD_DISK_MIN_PERCENT` (10), `GUARD_NOTIFY_ENABLED` (false).

---

## What I will build, in your order, once this is approved

1. persistent ffmpeg + 10 s segment ring (keep 6) + frames at `GUARD_FPS`
2. detection + alarm rule (shared pipeline, §8)
3. recording assembly from segments, timestamp filenames, retention
4. watchdog: CPU, disk, visibility
5. MQTT contract, REST, persistence
6. dashboard: event list, annotated frames, correct/false-alarm marking

Small commits on `develop`, `implementation_status.md` updated per step, and **`main` only
after the acceptance criteria are measured on the NUC.**
