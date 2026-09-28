# Guard — Deployment Runbook

**Written for a phone on a pier.** Short blocks, copy-paste, one thing per step.
**Date:** 2026-09-28 · **Deploys:** the guard worker + backend guard contract (v3.42).

> **Scope note.** The single deployment now covers guard **and** UI v2 together. This
> document is the **guard half**; it will be extended with the UI half before the trip, and
> the acceptance in §4 must pass either way. Nothing here has run on the NUC yet.

**The hard constraint of the whole phase, restated because it governs every STOP below:**
the NUC currently runs fine and must stay that way. Guard must never degrade berth
occupancy, MQTT, the tunnel or the backend.

---

## Read these three things first

> ### 1. Exactly one step in this runbook is irreversible: **pushing `main`** (§3.1).
>
> Everything after it is a `systemctl disable` and a directory removal. So the order is not
> negotiable: **§2 and §4 must both pass before §3.1**, because that is the last point at
> which stopping costs nothing.

> ### 2. None of the five acceptance criteria is proven by CI.
>
> CI proves the **mechanism** behind three of them. It proves **not one of the five
> numbers.** A green test run is not clearance to deploy — §4 is. Do not let a green suite,
> here or on the dev box, stand in for a measurement on this hardware.

> ### 3. A SKIPPED test on the NUC is a failure to report, not a pass.
>
> Skips here mean the question was never asked — no broker, or no ffmpeg. Both are real
> deployment conditions, and both look like success in a summary line. §2 runs the suite in a
> mode where a skip is an outright failure, so this cannot be missed by accident.

---

## 0. Which steps are irreversible

Read this before starting. Everything else can be undone in under a minute.

| Step | Reversible? | Why |
|---|---|---|
| §1 baseline capture | yes — read-only | writes only to your home dir |
| §2 integration suite | yes | uses its own camera id and its own tables |
| §3.1 `git merge` to main, push | **NO — history is public once pushed** | a revert commit is possible, but the push cannot be unmade |
| §3.2 `upgrade.sh` | yes — §5 restores the previous release | |
| §3.3 guard venv install | yes — it is a separate directory you can delete | openvino never enters the backend venv |
| §3.4 `systemctl enable --now cloud-iot-guard` | yes — disable and delete the unit | |
| §3.5 first `arm` | yes | but it starts writing video to disk; see §3.5 |
| §4 acceptance measurement | yes — read-only | |

Only **one** step is genuinely irreversible: pushing `main`. Everything after it is a
`systemctl disable` and a directory removal.

**Do not push `main` until §2 and §4 have both passed on this box.** That is the same rule as
A.5: the numbers come before the merge, not after.

---

## 1. Baseline first (5 min, before touching anything)

```bash
cd ~/Cloud_IOT && git fetch origin && git checkout develop && git pull
sudo bash scripts/guard_baseline.sh before
/opt/cloud-iot/backend/.venv/bin/pip freeze | sort > ~/venv_freeze_$(date +%F).txt
```

**NOTE** the three numbers it prints — `cpu_avg_pct`, `backend_rss_mb`, disk free. §4 and §5
both compare against them. Without this step there is nothing to compare to and "unchanged"
becomes an opinion.

---

## 2. Run the integration suite ON THE NUC (10 min)

This is the suite that proves the worker and the backend actually talk to each other. It ran
green on the dev box; the NUC is where it matters, because that is where ffmpeg is 8.0.1 and
Python is 3.14.

### 2.1 The broker — yes, it needs docker compose

The suite needs a **real MQTT broker**. It finds one in this order:

1. anything already listening on `localhost:1883` — **on the NUC this is the compose broker,
   and it is what you want**;
2. otherwise a private `mosquitto` binary on an ephemeral port (the dev-box path);
3. otherwise it **skips and says so**.

So confirm compose is up first:

```bash
sudo docker ps --format '{{.Names}}\t{{.Status}}' | grep mqtt
```

Expect `pedestal-mqtt-broker   Up ...`. If it is not running:

```bash
cd ~/Cloud_IOT && sudo docker compose up -d mosquitto
```

> The suite publishes only under `marina/$MARINA_ID/camera/11/guard/#` and uses camera id
> **11**, which no cabinet uses. It does not touch pedestal or cabinet topics. Running it
> against the live broker is safe, and is deliberate — a private broker would not prove the
> real one works.

### 2.2 Run it

```bash
cd ~/Cloud_IOT
GUARD_INTEGRATION_REQUIRED=1 GUARD_FFMPEG=$(command -v ffmpeg) \
  ./backend/.venv/bin/python -m pytest tests/backend/test_guard_integration.py -v -rs
```

`GUARD_INTEGRATION_REQUIRED=1` is what makes this trustworthy: **with it set, the suite cannot
skip.** A missing broker or missing ffmpeg becomes an outright failure saying
*"INTEGRATION NOT RUN — this is a FAILURE TO REPORT, not a pass"*, rather than a green summary
line with a quietly smaller test count. Both of those conditions are real on this box (ffmpeg
is absent from the installer — `sudo apt install -y ffmpeg`), which is exactly why they must
not be skippable here.

**STOP if anything fails.**

Expect **7 passed**:

| Test | Proves |
|---|---|
| TC-GINT-01 | the worker announces itself, live, as OFF |
| TC-GINT-02 | a real command is parsed and acked inside the timeout |
| TC-GINT-03 | arm → alarm → persisted event → clip → labelled |
| TC-GINT-04 | detections persist as a batch and link to their event |
| TC-GINT-05 | a killed worker becomes UNAVAILABLE via the broker's Last Will |
| TC-GINT-06 | a command sent while the worker is down goes overdue |
| TC-GINT-07 | an unacked command leaves no false ARMED |

### 2.3 And the rest of the suite

```bash
GUARD_FFMPEG=$(command -v ffmpeg) ./backend/.venv/bin/python -m pytest -q -rs
```

Expect **823 passed** and **at most 1 skipped** — the real-camera ring test, which needs
`GUARD_TEST_RTSP_URL`. Since you are on the marina LAN, answer it too:

```bash
GUARD_FFMPEG=$(command -v ffmpeg) \
GUARD_TEST_RTSP_URL='rtsp://admin:PASS@192.168.1.191:554/profile1' \
  ./backend/.venv/bin/python -m pytest tests/backend/test_guard_capture.py -q -rs
```

That should take the skip count to **0**. Report the number either way.

---

## 3. Deploy

### 3.1 Merge to main — THE IRREVERSIBLE STEP

**Do not do this until §2 passed and §4's measurements are in hand.**

```bash
cd ~/Cloud_IOT
git checkout main && git merge develop
CLOUD_IOT_RELEASE=1 git push origin main
```

### 3.2 Upgrade (reversible — §5 restores)

```bash
sudo /opt/cloud-iot/upgrade.sh
```

Never run uvicorn by hand; `upgrade.sh` is the only correct update path.

**STOP** and check the marina still works before going further:

```bash
systemctl status cloud-iot-backend --no-pager | head -5
curl -sf localhost:8000/api/pedestals >/dev/null && echo "API OK" || echo "API DOWN"
```

At this point guard's **backend half** is live and will report `UNAVAILABLE` — correct, there
is no worker yet.

### 3.3 The guard venv (reversible — it is one directory)

openvino must never enter the backend venv. This is a separate venv for a separate service.

```bash
sudo mkdir -p /opt/cloud-iot/guard && sudo chown guard:cloud-iot /opt/cloud-iot/guard
sudo -u guard python3 -m venv /opt/cloud-iot/guard/.venv
sudo -u guard /opt/cloud-iot/guard/.venv/bin/pip install --upgrade pip
sudo -u guard /opt/cloud-iot/guard/.venv/bin/pip install --only-binary=:all: \
    -r /opt/cloud-iot/guard_worker/requirements.txt
```

`--only-binary=:all:` is not optional. A source build of numpy or openvino on this box takes
tens of minutes and can fail halfway, leaving a venv that imports but does not work.

**Check it before continuing:**

```bash
sudo -u guard /opt/cloud-iot/guard/.venv/bin/python -c \
  "import paho.mqtt.client, numpy, PIL, openvino; print('guard venv OK')"
sudo -u guard /opt/cloud-iot/guard/.venv/bin/pip list | grep -i telemetry
```

Second command **must print nothing** — a pedestal in a marina does not phone home.

And confirm the entrypoint the unit will run actually exists:

```bash
cd /opt/cloud-iot && sudo -u guard /opt/cloud-iot/guard/.venv/bin/python -c \
  "import guard_worker.__main__; print('entrypoint OK')"
```

> This check exists because the entrypoint was missing once, while 803 tests were green.

### 3.4 Model + storage + unit (reversible)

```bash
sudo mkdir -p /opt/cloud-iot/guard/models /var/lib/marina-guard/recordings
sudo chown -R guard:cloud-iot /opt/cloud-iot/guard/models /var/lib/marina-guard
sudo chmod 2750 /var/lib/marina-guard/recordings
# copy the exported OpenVINO IR (see scripts/guard_export_model.sh) into models/
sudo -u guard ls -la /opt/cloud-iot/guard/models
```

Install `guard.env` and the unit from `docs/guard_b1_design.md §2`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cloud-iot-guard
sudo systemctl status cloud-iot-guard --no-pager | head -12
sudo journalctl -u cloud-iot-guard -n 30 --no-pager
```

Expect `guard worker running: camera=... state=OFF`. It comes up **OFF and waits** — that is
deliberate, so a suspended guard cannot rearm itself by restarting.

Confirm the backend now sees it:

```bash
curl -s localhost:8000/api/guard/status -H "$H" | jq '.cameras[] | {state, worker_alive}'
```
Expect `state: "OFF"`, `worker_alive: true`.

### 3.5 First arm

```bash
curl -s -X POST localhost:8000/api/guard/1/enable -H "$H" | jq
```

**This starts writing video to disk.** Reversible (`/disable`, and retention caps the space),
but it is the first step with a physical footprint. Check disk before and after:

```bash
df -h /var | tail -1
```

---

## 4. Acceptance — measured on this box, not asserted

**None of the five criteria is fully proven by CI.** CI proves the *mechanism* behind three
of them; every number has to come from this hardware. Stated plainly so nobody reads a green
test run as clearance:

| # | Criterion | Proven in CI? | Must be measured here? |
|---|---|---|---|
| 1 | guard OFF leaves CPU and RSS at baseline, no model resident | **Mechanism yes** — TC-GSMOKE-07 kills the ffmpeg pid and asserts the model object is released | **Yes** — CPU and RSS are numbers, and only this box has the real workload |
| 2 | guard ON under 15 % of 4 cores | **No** — the dev box is a different CPU, 32-bit Python, and a fake detector | **Yes.** The only real measurement of the five |
| 3 | berth occupancy unchanged through arm, alarm, suspend, re-arm | **No** — needs the real ML workload and real cabinets | **Yes** |
| 4 | forced CPU overload suspends within 60 s | **Logic yes** — TC-GWD-02/03/04 with injected time | **Yes** — that the logic fires under genuine load |
| 5 | forced low disk disables recording only | **Logic yes** — TC-GWD-10/11/12 | **Yes** — that detection genuinely continues |

### 4.1 Guard OFF costs nothing

```bash
curl -s -X POST localhost:8000/api/guard/1/disable -H "$H" >/dev/null; sleep 5
pgrep -a ffmpeg ; echo "--- ffmpeg count: $(pgrep -c ffmpeg || echo 0)"
ps -o rss=,pcpu=,comm= -p $(pgrep -f 'guard_worker') 2>/dev/null
```

**Required:** no ffmpeg owned by guard, worker RSS back near its idle figure, CPU ~0 %.
Record both numbers.

### 4.2 Guard ON under 15 % of 4 cores

```bash
curl -s -X POST localhost:8000/api/guard/1/enable -H "$H" >/dev/null
sleep 180   # let the rolling window fill; it reports nothing until it is full
curl -s localhost:8000/api/guard/status -H "$H" \
  | jq '.cameras[] | .health | {cpu_pct_60s, cpu_pct_now, disk_free_gb}'
```

**Required:** `cpu_pct_60s` **< 15** (percent of all 4 cores). Cross-check independently,
because the number should not come only from the thing being measured:

```bash
top -b -n 2 -d 5 | grep -E 'guard|ffmpeg' | tail -5
systemd-cgtop -1 -n 2 --order=cpu | head -12
```

A.5 measured 6.8 % of 4 cores at 1 fps with `--threads 1`, using the probe rather than the
worker. If this reads much above that, stop and say so before the watching week.

### 4.3 Berth occupancy unchanged

Before arming, and again after an alarm and a suspend/re-arm cycle:

```bash
curl -s localhost:8000/api/berths -H "$H" | jq -r '.[] | "\(.name) \(.status) \(.match_score)"'
```

**Required:** the same berths, the same statuses, and analysis still completing. Also confirm
the ML worker is not starved:

```bash
sudo docker logs --tail 20 pedestal-ml-worker
```

### 4.4 Forced CPU overload suspends within 60 s

```bash
nproc
stress-ng --cpu 4 --timeout 120s &   # or: for i in $(seq 4); do yes >/dev/null & done
sleep 75
curl -s localhost:8000/api/guard/status -H "$H" | jq '.cameras[] | {state, reason, flags}'
```

**Required:** `SUSPENDED_CPU` within ~60 s of the window filling, and **no ffmpeg left
running**:

```bash
pgrep -c ffmpeg    # expect 0
kill %1 2>/dev/null; pkill yes 2>/dev/null
```

Then confirm the recovery path is a human decision:

```bash
curl -s -X POST localhost:8000/api/guard/1/rearm -H "$H" | jq
```

### 4.5 Forced low disk disables recording ONLY

```bash
df -h /var | tail -1
# fill to just under the floor (GUARD_DISK_MIN_GB, default 5G). Adjust the count.
sudo fallocate -l 100G /var/lib/marina-guard/BALLAST || \
  sudo dd if=/dev/zero of=/var/lib/marina-guard/BALLAST bs=1M count=100000
df -h /var | tail -1
sleep 20
curl -s localhost:8000/api/guard/status -H "$H" | jq '.cameras[] | {state, flags, health}'
```

**Required:** flag `no_disk` present, `recording_enabled: false`, and **state still ARMED** —
detection must keep running. An alarm you know about with no video beats no alarm.

```bash
curl -s "localhost:8000/api/guard/detections?limit=5" -H "$H" | jq '.total'
```
**Required:** still growing.

**Then remove the ballast immediately:**

```bash
sudo rm -f /var/lib/marina-guard/BALLAST && df -h /var | tail -1
```

### 4.6 Record the numbers

Fill this in and keep it with the release:

| Measurement | Baseline (§1) | Guard OFF | Guard ON |
|---|---|---|---|
| CPU % (4 cores) | | | |
| Backend RSS MB | | | |
| Worker RSS MB | n/a | | |
| ffmpeg processes | 0 | | |
| Disk free | | | |

Six A.5 person-clip rows stay open — there are still no person clips. That is accepted: the
event list with correct/false labelling is how those get filled from real traffic.

---

## 5. Rollback, verified — not assumed

Guard is a separate service writing to one directory, so rollback is a stop and a delete.

```bash
sudo systemctl disable --now cloud-iot-guard
sudo rm -f /etc/systemd/system/cloud-iot-guard.service
sudo systemctl daemon-reload
sudo rm -rf /opt/cloud-iot/guard          # venv + models
# recordings: KEEP unless you are sure. This is the only data loss in the whole rollback.
# sudo rm -rf /var/lib/marina-guard
```

To go back a release as well:

```bash
cd ~/Cloud_IOT && git checkout main && git log --oneline -3
git revert --no-edit <the merge commit>
CLOUD_IOT_RELEASE=1 git push origin main
sudo /opt/cloud-iot/upgrade.sh
```

### Three independent proofs production is untouched

Same three as A.5, because the point is that no single check can be trusted alone — each
would pass for a different wrong reason.

**Proof 1 — openvino never reached the backend venv:**
```bash
/opt/cloud-iot/backend/.venv/bin/pip list | grep -ci openvino
```
**must print `0`**

**Proof 2 — the backend venv is byte-identical to the baseline:**
```bash
diff <(sort ~/venv_freeze_*.txt | tail -n +1) \
     <(/opt/cloud-iot/backend/.venv/bin/pip freeze | sort)
```
**must print nothing**

**Proof 3 — no guard process, unit or storage remains:**
```bash
pgrep -af guard_worker ; echo "workers: $(pgrep -cf guard_worker || echo 0)"
systemctl list-unit-files | grep -c cloud-iot-guard
ls /opt/cloud-iot/guard 2>&1
```
**expect** `0` workers, `0` unit files, and "No such file or directory".

**Then confirm the marina still works, by looking at it:**
```bash
sudo bash ~/Cloud_IOT/scripts/guard_baseline.sh after
```
CPU within a few points of §1, backend RSS within ~50 MB, `use_ml_models` still false. Open
the dashboard through the tunnel, load a pedestal, run one berth analyse.

If any of the three proofs disagrees with the others, believe the disagreement and stop.

---

## 6. If something looks wrong

Full symptom table is in `docs/guard_operator_runbook.md §6`. The three that matter during a
deployment:

| Symptom | Check |
|---|---|
| `UNAVAILABLE` right after §3.4 | `journalctl -u cloud-iot-guard -n 50`. Most likely the model is missing from `/opt/cloud-iot/guard/models`, which is acked as a refusal, not a crash |
| service restarts in a loop | `systemctl status`; after 5 starts in 300 s it stays down **on purpose** and shows as UNAVAILABLE rather than hammering the box |
| ffmpeg errors about timestamps | run `scripts/guard_diagnose_timestamps.py --url ... --verify`; exit 0 means capture still works. A future ffmpeg enforcing the accepted deprecation is the known risk here |

**Notifications to the marina stay OFF.** There is no notification path in Phase 1 at all —
not built-and-disabled — so nothing can reach the marina by accident during the watching
week.
