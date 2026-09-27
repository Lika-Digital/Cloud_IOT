# Camera capabilities and future options

**Status: DISCOVERY ONLY. Not a task, not part of Stage B.** Recorded so nobody has to
rediscover it. Carry this into the final documentation pass under "Camera capabilities and
future options".

Investigated 2026-09-27 on the live marina camera.

---

## Device

| | |
|---|---|
| Model | **DVC DCN-TF2283AI-DL**, firmware **5.2.3** |
| Address | 192.168.1.191 |
| RTSP `profile1` | h264 High, **1920×1080, 25 fps** |
| Also on the stream | pcm_alaw audio + a `Data: none` stream — **both discarded** (audio by policy, see the guard capture module) |
| Packet timestamps | **absent** — this is the accepted ffmpeg deprecation, already documented under known limitations |
| Open ports | 80 (HTTP + ONVIF), 554 (RTSP), 8080 (vendor protocol) |

## ONVIF — confirmed working

| | |
|---|---|
| Device service | `http://192.168.1.191:80/onvif/device_service` |
| Discovery | WS-Discovery |
| Auth | **WS-Security required.** Plain `curl` with digest auth does **not** work. |
| Client used | `onvif-zeep` from a `python:3.12` container — it has no cp314 wheel, so the same containerised pattern as the model export applies |
| Profiles | Streaming, **Profile T**, **Profile M**, plus PTZ |
| Events | `http://192.168.1.191:80/onvif/Events` — `WSSubscriptionPolicySupport: True`, `WSPullPointSupport: True` |
| Analytics | `http://192.168.1.191:80/onvif/Analytics` — `RuleSupport: True`, `AnalyticsModuleSupport: True` |

### Topics the camera publishes (the useful ones)

| Topic | Meaning |
|---|---|
| `RuleEngine/FieldDetector/ObjectsInside` | objects inside a defined zone |
| `RuleEngine/LineDetector/Crossed` | line crossing |
| `RuleEngine/CellMotionDetector/Motion` | cell motion |
| `VideoSource/MotionAlarm` | coarse motion |
| `VideoSource/GlobalSceneChange`, `ImageTooBlurry` | possible tamper / visibility signals |

### What it does **not** publish

**No person or object classification topic.** The camera *does* run its own AI person
detection, but that is exposed only through the **vendor protocol on port 8080**, which
answers every path with the same `ipc.com` XML and is undocumented.

Over ONVIF the camera says *"something moved in the zone"* — never *"this is a person"*.

---

## Why Phase 1 does not use it

`ObjectsInside` would be a **trigger, not a detection**: our model would still have to
decide whether the moving thing is a person. So the saving is real but smaller than it
first looks, and there are three concrete reasons to leave it out now:

1. **Guard is not always armed.** It runs when a berth holder leaves the boat, and during
   that window the expectation is that nobody is there. The cost being optimised away is
   therefore intermittent.
2. **The steady-state cost is already inside budget.** At 1 fps with one thread, measured
   6.8 % of 4 cores. There is no pressure to reduce it.
3. **Response time is already adequate.** The alarm rule needs 2 detections within 4 s, so
   alarms land within seconds.

And the decisive one: **adding a trigger now would confound the first production
measurements.** If guard under-detects, we could not tell whether the model or the trigger
was at fault. Accuracy is the unproven part; nothing should be layered on top of it until
it has been measured on its own.

## When to revisit

After a week of production data, if **either** becomes true:

- guard is left armed for long periods and the CPU cost starts to matter
- we want faster response, **or a second independent signal** to cross-check the
  correct/false-alarm labelling

### Design sketch for that day — not to be built now

- Keep the **segment ring running continuously** regardless. Pre-roll has to exist *before*
  an alarm, so the ring can never be gated on a trigger.
- Run detection **slowly in the background**, and let an ONVIF event **raise the rate
  briefly**.
- **Trigger as an accelerator, never as a precondition.** If a missed camera event could
  mean guard never looks, the trigger has become a single point of failure in front of the
  thing it was meant to help.

## The one property to keep true in the code now

> The detection step must be **callable on demand**, not only from a polling loop.

Nothing else: **no ONVIF integration, no configuration for it, no speculative design.**

This is already satisfied — `app/guard/pipeline.process_frame(detector, jpeg, cfg)` is a
module-level function over a single frame with no loop and no internal state, and
`AlarmState.observe()` is likewise a single-shot call. `TC-GPL-15` pins that property so a
future refactor cannot quietly bury it inside a capture loop and make the later change
large. That test is the entire cost of keeping this option open.

---

## For whoever replaces this camera

Spec items worth checking **before purchase**, all learned the hard way here:

| Requirement | Why |
|---|---|
| **Packet timestamping** | Its absence is the accepted ffmpeg deprecation, and a future ffmpeg enforcing it would stop segmenting |
| **AI classification exposed over ONVIF** | This camera has person detection but only over an undocumented vendor protocol, which makes it unusable |
| **IR illuminator** | Night is unsupported on the current camera (no IR, poor sensor) |
| Concurrent RTSP sessions | Guard and berth occupancy each open one; this camera serves two, verified |
