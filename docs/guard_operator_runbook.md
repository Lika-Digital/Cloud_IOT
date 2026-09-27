# Guard operator runbook — the watching week

**Guard is fully operable from a terminal. No screen is required.** That is a step-5
requirement, not a convenience: the guard admin screen (step 6) was cancelled and merged
into UI v2, so during the watching week you arm guard, read state, list events and label
alarms with `curl` and `mosquitto_sub` alone.

Every command below is copy-paste. Set these once per shell:

```bash
export API=http://localhost:8000
export TOKEN='<paste a JWT from the dashboard, or see "Getting a token" below>'
export CAM=1                     # camera id == pedestal id (no camera entity yet)
export M=KRK                     # MARINA_ID from backend/.env
export H="Authorization: Bearer $TOKEN"
```

> **Notifications are OFF and there is no notification path at all in Phase 1** — not
> built-and-disabled. The dashboard, this API and MQTT are the only outputs, so nothing can
> reach the marina by accident during the watching week.

---

## Getting a token

Guard uses the normal operator JWT. Easiest is to copy it from a logged-in browser
(DevTools → Application → Local Storage → the auth store). From the terminal, the 2FA flow
means a scripted login needs the OTP from the backend log:

```bash
curl -s -X POST $API/api/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"..."}'
sudo journalctl -u cloud-iot-backend -n 20 | grep -i otp     # the code is logged
curl -s -X POST $API/api/auth/verify-otp -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","otp":"123456"}'
```

Roles: reading and **labelling** need any operator role; **arming, re-arming and config**
need admin or monitor_control.

---

## 1. Arm, disarm, and read state

**Arm:**
```bash
curl -s -X POST $API/api/guard/$CAM/enable -H "$H" | jq
```
Returns `202` with `state: "ARMING"` and a `req_id`. **It does not say ARMED** — that comes
only from the worker's acknowledgement.

**Read state:**
```bash
curl -s $API/api/guard/status -H "$H" | jq '.cameras[] | {camera_id, state, reason, flags, worker_alive, worker_seen_at, config_version, worker_config_version}'
```

What the states mean:

| `state` | Meaning |
|---|---|
| `OFF` | disarmed |
| `ARMING` | command sent, worker has not confirmed yet |
| `ARMED` | running |
| `ALARM` / `RECORDING` | an alarm is in progress |
| `SUSPENDED_CPU` | the watchdog shed guard; needs `rearm` after ~2 auto-resumes |
| `UNAVAILABLE` | **the worker is not answering.** Never shown as ARMED — see below |

**If you see `UNAVAILABLE`:** the backend asked for ARMED and nothing replied within
5 seconds, or the heartbeat stopped for 15. `reason` says which, and `worker_seen_at` says
when it was last heard from. Check the worker:

```bash
systemctl status cloud-iot-guard --no-pager
sudo journalctl -u cloud-iot-guard -n 50 --no-pager
```

**Disarm:**
```bash
curl -s -X POST $API/api/guard/$CAM/disable -H "$H" | jq
```

**Re-arm after a CPU suspension** (deliberately separate from `enable`: it means *a human
looked*, and it resets the auto-resume budget):
```bash
curl -s -X POST $API/api/guard/$CAM/rearm -H "$H" | jq
```

---

## 2. Watch it live over MQTT

The whole contract, as it happens:

```bash
sudo docker exec -it pedestal-mqtt-broker \
  mosquitto_sub -t "marina/$M/camera/+/guard/#" -v
```

Just alarms:
```bash
sudo docker exec -it pedestal-mqtt-broker \
  mosquitto_sub -t "marina/$M/camera/+/guard/alarm" -v
```

Health heartbeat (every 5 s — CPU, RAM, disk, visibility):
```bash
sudo docker exec -it pedestal-mqtt-broker \
  mosquitto_sub -t "marina/$M/camera/+/guard/health" -v
```

Retained state only — what a late subscriber learns:
```bash
sudo docker exec -it pedestal-mqtt-broker \
  mosquitto_sub -t "marina/$M/camera/$CAM/guard/state" -v -C 1
```

> **First message on `state` may be a retained replay** from before the worker's last
> restart. The backend deliberately treats retained state as *last known* and never as
> liveness, so it cannot resurrect a dead worker as ARMED. Read `worker_alive` in
> `/api/guard/status` for the truth.

The full topic set (`{M}` = MARINA_ID, `{cam}` = camera id):

| Topic | Direction | Retained |
|---|---|---|
| `marina/{M}/camera/{cam}/guard/cmd` | backend → worker | no |
| `…/guard/ack` | worker → backend | no |
| `…/guard/state` | worker → backend | **yes** |
| `…/guard/health` | worker → backend | no |
| `…/guard/alarm` | worker → backend | no |
| `…/guard/detection` | worker → backend | no |
| `…/guard/recording` | worker → backend | no |
| `…/guard/retention` | worker → backend | no |

---

## 3. Review alarms, and label them

**The review queue — unlabelled alarms, newest first:**
```bash
curl -s "$API/api/guard/events?label=unlabelled&limit=20" -H "$H" \
  | jq '.unlabelled, (.events[] | {id, detected_at_local, confidence, px_height, has_frame, has_video, video_skipped, limited_visibility})'
```

**Look at the annotated frame** — this is the important one. If the boxes are on gulls,
fenders or reflections rather than people, the numbers are meaningless:
```bash
curl -s $API/api/guard/events/42/frame -H "$H" -o /tmp/alarm42.jpg && xdg-open /tmp/alarm42.jpg
```

**Watch the recording:**
```bash
curl -s $API/api/guard/events/42/video -H "$H" -o /tmp/alarm42.mp4 && xdg-open /tmp/alarm42.mp4
```
- `410 Gone` → it existed and retention deleted it; the reason and time are in the body.
- `404` with a `reason` → no clip was made (e.g. `no_disk`); **the alarm itself is still real**.

**Label it — this is the dataset from day one:**
```bash
curl -s -X POST $API/api/guard/events/42/label -H "$H" -H 'Content-Type: application/json' \
  -d '{"label":"false_alarm","note":"gull on the stern rail"}' | jq '.event | {id,label,labelled_by}'
```
`label` is `correct` or `false_alarm`. Re-labelling is allowed — a second look is legitimate.

**Count your week:**
```bash
curl -s "$API/api/guard/events?limit=500" -H "$H" \
  | jq '{total, unlabelled, correct: [.events[]|select(.label=="correct")]|length, false_alarms: [.events[]|select(.label=="false_alarm")]|length}'
```

---

## 4. The accuracy evidence — below-threshold detections

These are the A.5 rows the person-clip run could not produce, and the Phase 2 training
index. **A frame with nothing in it writes no row**, so absence here means absence.

```bash
curl -s "$API/api/guard/detections?since=2026-09-27T00:00:00Z&camera_id=$CAM" -H "$H" \
  | jq '{total, bands: ([.detections[].band]|group_by(.)|map({(.[0]): length})|add)}'
```

Near-misses — things that nearly alarmed, which is where a threshold tune comes from:
```bash
curl -s "$API/api/guard/detections?band=uncertain&min_confidence=0.35&limit=50" -H "$H" \
  | jq '.detections[] | {detected_at, confidence, px_height, has_frame}'
```

A frame behind an uncertain detection (often absent — uncertain frames are rate-limited and
evicted before alarm frames, which is the budget working, not an error):
```bash
curl -s $API/api/guard/detections/123/frame -H "$H" -o /tmp/uncertain123.jpg
```

**Person pixel height** matters: geometry predicts ~150 px at the ~10 m stern view. Much
lower means the crop or framing is not what we think.
```bash
curl -s "$API/api/guard/detections?band=alarm&limit=200" -H "$H" \
  | jq '[.detections[].px_height]|{n:length, min:min, max:max, median:(sort|.[length/2|floor])}'
```

---

## 5. Tune thresholds without a redeploy

Accuracy is unproven, so every threshold is runtime-changeable. `PATCH` semantics: send only
what you are changing.

**Too many false alarms** → raise the confidence threshold:
```bash
curl -s -X PATCH $API/api/guard/$CAM/config -H "$H" -H 'Content-Type: application/json' \
  -d '{"conf_threshold":0.6}' | jq '{config_version, changed, pushed_to_worker}'
```

**Missing real people** → lower it, or require fewer frames:
```bash
curl -s -X PATCH $API/api/guard/$CAM/config -H "$H" -H 'Content-Type: application/json' \
  -d '{"conf_threshold":0.4}' | jq
```

**The documented reserve, if recall is weak** — 2 fps with a 3 s window. Measured at 13.7 %
of 4 cores (vs 6.8 % at 1 fps), so it still fits the budget:
```bash
curl -s -X PATCH $API/api/guard/$CAM/config -H "$H" -H 'Content-Type: application/json' \
  -d '{"fps":2,"window_seconds":3}' | jq
```

**Adjust the detection zone** (fractions of the frame; the crop is what gives usable range,
so never remove it):
```bash
curl -s -X PATCH $API/api/guard/$CAM/config -H "$H" -H 'Content-Type: application/json' \
  -d '{"zone":[0.15,0.15,0.85,0.85]}' | jq
```

**Confirm the worker picked it up** — `config_version` and `worker_config_version` must
match. A mismatch means the worker is running stale thresholds and any tuning conclusion
would be meaningless:
```bash
curl -s $API/api/guard/status -H "$H" | jq '.cameras[] | {config_version, worker_config_version}'
```

Rejected on purpose: `uncertain_min` above `conf_threshold` (it would empty the uncertain
band and silently stop recording the accuracy evidence), and a zone with `x1 >= x2`.

---

## 6. When something looks wrong

| Symptom | Check |
|---|---|
| `UNAVAILABLE` | `systemctl status cloud-iot-guard`; `journalctl -u cloud-iot-guard -n 50` |
| `SUSPENDED_CPU` | `flags` and `health.cpu_pct_60s` in `/status`. After ~2 auto-resumes in 24 h it waits for `rearm` — deliberately, because endless auto-resumes would hide a persistently overloaded box |
| `no_disk` flag, alarms but no video | Disk is below the floor. **Detection continues** — an alarm you know about with no video beats no alarm. `df -h /var` |
| `segments_stalled` flag | The ring stopped producing files, so an alarm would have no video. Check ffmpeg is alive and the camera is reachable |
| `limited_visibility` flag | Too dark or too featureless to detect reliably. Night is **unsupported** on this camera (no IR) — expected after dark |
| Retention banner / `frames_cap_exhausted` | Frame storage is full. **Alarm frames are never deleted**; only uncertain ones, and then collection stops |
| Guard seems fine but no alarms at all | `mosquitto_sub` on `…/guard/health` — if heartbeats are flowing, arm state is real; then check `/api/guard/detections` for near-misses before assuming it is blind |

**After any system upgrade that touches ffmpeg**, run the post-upgrade check — a future
ffmpeg enforcing the accepted timestamp deprecation would stop segmenting, and then an alarm
would have no video:

```bash
python3 ~/Cloud_IOT/scripts/guard_diagnose_timestamps.py \
  --url 'rtsp://admin:PASS@192.168.1.191:554/profile1' --verify
```
Exit 0 = capture still works.

---

## 7. What guard does NOT record

Worth knowing, and stating to anyone who asks:

- **No audio, ever.** The camera streams `pcm_alaw` and it is discarded at four independent
  points in every ffmpeg command. This is a policy decision, not a codec workaround:
  recording conversations on a pontoon is a separate legal question from video.
- **No night coverage.** No IR illuminator and a poor sensor, so after dark guard reports
  `limited_visibility` rather than pretending to see. Fixing it needs different hardware.
- **Not a certified intrusion or fire alarm system.**
