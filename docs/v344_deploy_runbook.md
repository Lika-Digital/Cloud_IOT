# v3.45 — UI v2, meter fix and Guard: deploy and acceptance runbook

**Date:** 2026-10-10 · **Target:** the Krk cabinet, `MAR_KRK_ORM_01` · **Deployed from:**
`main`, after the merge

Same shape as `docs/guard_a5_runbook.md`: numbered steps, each ending in **STOP** (do not
continue) or **NOTE** (record and carry on). Phone first — several checks must be done on a
phone standing at the pedestal, not at a desk, because that is where this UI is used.

---

## Read this before step 0

### We merge to `main` first. The cabinet then upgrades the way it always has.

```bash
sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh          # no argument. The standard command.
```

**Changed 2026-10-10.** An earlier draft of this runbook had the cabinet deploy `develop`
using a new branch argument. That route is withdrawn, for a reason worth recording:

> **The cabinet's own copy of `upgrade.sh` is the one from `773bca6`, which has no branch
> argument.** Lines 57-61 of that version force `git checkout main`, and every fetch and pull
> is hardcoded `origin main`. So `upgrade.sh develop` on the cabinet today would deploy
> **main** while printing `Branch: main` — a silently wrong result. Getting the branch
> argument onto the cabinet requires checking out `develop` there first, which is a
> chicken-and-egg that buys nothing.

The branch argument stays in the code. It works, it is tested, and it becomes usable once
`main` carries it. **This runbook does not depend on it.**

### Rollback is git, not a backup

`773bca6` is what the cabinet runs now and it stays reachable forever. Rolling the code back
is checking it out and re-running the upgrade. There is no snapshot to take.

### Back up the data — or decide not to, and say why

**This is a decision, not a step to skip by default.** Whether a backup is needed is a
property of the CABINET, not of this procedure. A runbook with no backup step will one day be
followed on a cabinet where sessions are billed, by someone who does not know a decision was
ever made.

| This cabinet is… | Do this |
|---|---|
| **A test cabinet, data disposable** — Krk, `MAR_KRK_ORM_01`, as of 2026-10-10: everything in it is test data, nothing is billed, and the three open standalone sessions do not matter | **Skip the backup, and write in the log that you skipped it and why.** |
| **Carrying real billing data** | **Back up before anything else**, in this order: `pedestal.db`, the auth database under `data/`, and `.env`. |

For a cabinet with real data, use the online-backup endpoint rather than `cp` — the databases
run in WAL mode and a file copy of a WAL database is not consistent:

```bash
curl -fsS -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/api/admin/backup/database -o ~/backup-pedestal-$(date +%F).db
cp /opt/cloud-iot/backend/.env ~/backup-env-$(date +%F)
```

The code rollback does not need this. The backup covers the one thing a rollback cannot undo:
migrations add columns, and reverting the code leaves both the columns and anything written
through them in place.

### Which steps are irreversible

| Step | Reversible? |
|---|---|
| **Merging `develop` to `main`** | **THE IRREVERSIBLE ONE.** After this, this cabinet and every future cabinet updates to it. |
| Running `upgrade.sh` on the cabinet | **Yes** — check out `773bca6` and re-run |
| Acceptance areas 1–3 | **Yes** — read-only, or a control the operator can undo |
| Area 4 — provisioning an NFC tag | **Yes** — a tag can be un-pointed, and the removal is recorded |
| Area 4 — a real customer session | **Partly** — the session and its ledger rows are a record of something that happened. Use a test customer. |
| Area 5 — water events reaching the ERP | **NO** once it is wired. Not reachable today — see below. |

### Nothing leaves this cabinet today

Measured on the live `external_api_config` row, 2026-10-10:

```
webhook_url    = None
allowed_events = ["heartbeat", "temperature_reading"]
active         = 1
```

**Two independent reasons nothing is pushed out:** no webhook URL, and `session_ended` is not
an allowed event. The three open standalone sessions cannot reach myMarina on close.

The attribution filter added in v3.45 (`erp_webhook.is_erp_reportable`) is therefore not a
precondition for this deploy. It stays because it is the defence that does not depend on
today's configuration — a session attributed to nobody does not leave, whatever the next bad
field turns out to be.

### One area needs someone else, and is blocked

**Area 5 cannot be completed now.** Beyond needing a person at myMarina, two findings from the
2026-08-21 verification on that same config row block it outright — see **D17** and **D18** in
`docs/ui_v2_spec.md`. Do areas 1–4, record area 5 as blocked, and do not treat the deploy as
unfinished because of it.

---

## STEP 0 — Baseline, before anything changes (5 min)

Record what the cabinet runs now, so "it broke" can be told from "it was already like that".

```bash
cd ~/Cloud_IOT && git rev-parse --abbrev-ref HEAD && git rev-parse --short HEAD
systemctl is-active cloud-iot-backend cloud-iot-guard mosquitto
df -h / | tail -1
```

**STOP if** the repo is not on `main`, or `cloud-iot-backend` is not `active`. Something is already
wrong and this is not the moment to add a deployment to it.

**NOTE** the commit hash. It should read `773bca6`. That is the rollback target.

---

## STEP 1 — Confirm `origin/main` actually moved (2 min)

**Do this before running the upgrade, not after.** The upgrade pulls `main`; if the merge did
not land, it will cheerfully redeploy what is already there and report success.

```bash
cd ~/Cloud_IOT
git fetch origin main
git log origin/main -1 --format='%h %ci %s'
```

**STOP unless** this shows the v3.45 merge commit and a timestamp from today. If it still
shows `a0a1405` or `773bca6`, the push did not land — stop and go back to the development
machine.

---

## STEP 2 — Upgrade (10 min)

```bash
sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh
```

No argument. The standard command.

```bash
systemctl is-active cloud-iot-backend cloud-iot-guard
# The unit is cloud-iot-backend. `journalctl -u cloud-iot` names nothing, prints nothing,
# and the `|| echo "clean"` below would then report clean having read no logs at all.
journalctl -u cloud-iot-backend -n 40 --no-pager | grep -iE "error|traceback" || echo "clean"
```

**STOP if** `cloud-iot-backend` is not active, or the log shows a traceback. Roll back: check out
`773bca6` and re-run the upgrade.

**NOTE:** the first start applies the new migrations — `berth_assignments`, the valve state
columns, the session register columns. All additive and idempotent; note the startup line
that confirms it.

**NOTE:** `pip install -r requirements.txt` runs **only when the upgrade can see that
`requirements.txt` changed, or when it cannot tell what changed at all** (v3.46 — see step
2b). `numpy` moved from a hard `==2.1.2` pin to `>=2.1,<3`; the loosened range is safer on
this machine's Python 3.14, but this is the step most likely to fail. If it does, the log
names the package.

---

## STEP 2b — Exercise the sync-only path ON PURPOSE (10 min)

**Do not skip this because step 2 passed. Step 2 does not test what this tests.**

### Why this step exists

`upgrade.sh` reaches the deploy by two routes, and they take different code:

| route | when | changed files |
|---|---|---|
| `NEEDS_PULL` | new commits on `origin/main` | exact, from `git diff HEAD..origin/main` |
| `NEEDS_SYNC` | git already current, `/opt` stale | **unknowable** — no commit range |

The second route is reached only when someone runs `git pull` by hand before the script.
On 2026-10-10 that happened for the first time, and it failed: `CHANGED_FILES` was assigned
only on the first route but read on both, so under `set -u` the two dependency guards
errored and — because they sit inside `if` conditions — evaluated as FALSE. **Both
`npm install` and `pip install` were silently skipped while the upgrade reported success.**
It did no damage only because the single requirements change that day was a numpy pin the
machine already satisfied.

A normal upgrade takes the `NEEDS_PULL` route, so **it never exercises the route that was
repaired.** Shipping a fix that is never run on its own path is how this codebase
accumulated the backlog in `docs/engineering_notes.md`. So reproduce the condition
deliberately, every time this script changes.

### Do it

```bash
cd ~/Cloud_IOT

# 1. Put git ahead of /opt by hand. This is the condition under test.
git pull origin main
git log --oneline -1          # note the hash; git is now CURRENT

# 2. Now run the upgrade. Because git is current, it MUST take the sync-only route.
sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh 2>&1 | tee /tmp/sync_only_upgrade.log
```

### What you must see

Four things, and the absence of a fifth:

```bash
# a) it took the route under test
grep -c "out of sync" /tmp/sync_only_upgrade.log            # expect >= 1

# b) it SAYS it cannot tell what changed
grep "cannot determine what changed" /tmp/sync_only_upgrade.log

# c) npm install actually fired
grep "Installing frontend dependencies" /tmp/sync_only_upgrade.log

# d) pip install actually fired
grep "Installing backend dependencies" /tmp/sync_only_upgrade.log

# e) the bug is gone
grep -c "unbound variable" /tmp/sync_only_upgrade.log       # expect 0
```

**STOP if** (e) is non-zero, or if (c) or (d) print nothing. (c) and (d) printing nothing is
the exact failure this step exists to catch, and it is invisible in the upgrade's own
success banner.

**NOTE:** on this route the installs run even when nothing needed them. That is deliberate —
a wasted minute against a backend that starts `active` and fails later on a lazily-imported
package. `systemctl is-active` cannot tell you a package is missing.

### The same check, without a cabinet

Both routes are covered in the gate, so a regression fails before it reaches here:

```bash
pytest tests/backend/test_upgrade_script_deps.py -v
```

Those tests execute the real decision block out of the real `upgrade.sh`. To confirm they
can still fail — a test never seen red is not evidence:

```bash
git show 773bca6:nuc_image/upgrade.sh > /tmp/old_upgrade.sh
UPGRADE_SH_PATH=/tmp/old_upgrade.sh pytest tests/backend/test_upgrade_script_deps.py -q
# expect 5 failed, including: bash: line NN: CHANGED_FILES: unbound variable
```


# ACCEPTANCE — five areas, in this order

Do them in order. Each builds on the one before.

---

## AREA 1 — UI v2, all six screens, phone AND desktop (45 min)

Open each on a **desktop browser** and on a **phone**, on the marina wifi, signed in as a
`monitor` (not admin — that is the role staff use).

| # | Screen | What must be true |
|---|---|---|
| 1.1 | `/marina` | One row per berth. Status is **colour + icon + word**, never colour alone. One figure per row, **in AMPS** — v3.45 stopped displaying watts because the single-phase meters report `powerKw` ~100x high. A berth with no reading shows **—**, never `0`. |
| 1.2 | `/marina/berth/<id>` | Socket name, **rating and phase count** — Q1 must read 32 A three phase and Q3/Q4 16 A. Live figure in amps. Month-to-date in **kWh from the register**, carrying its provenance ("meter reading"). |
| 1.3 | `/marina/water` | Two outlets, by outlet. No berth column. A free outlet reads **Free**, a silent one **Not known** — and those must look different. |
| 1.4 | `/marina/alarms` | Plain sentences. **No error codes, no identifiers** such as `meter_power_implausible`. |
| 1.5 | `/marina/guard` | Four words only. If the guard worker is stopped it must read **"Guard unavailable"** and never "Guard off". |
| 1.6 | `/marina/setup/<pid>` | Step 2 lists the four berths with their sockets, pre-filled. Ratings shown. No water column. **No smart-mode control anywhere.** |

**STOP if** any screen shows a raw error code, a `0` where a figure is unknown, or a
greyed-out control instead of a sentence.

### 1.6b — The meter fix, verified on the cabinet (v3.45)

The reason this release exists. Three standalone sessions were open on this cabinet holding
56 kWh that never happened, because the gate trusted `powerKw`.

```bash
# No standalone session should be open on an idle socket.
sqlite3 /opt/cloud-iot/backend/pedestal.db   "SELECT id, socket_id, origin, started_at, energy_kwh FROM sessions
   WHERE status='active' AND origin='standalone';"
```

**STOP unless** this returns nothing, once the pre-existing three are closed. A NEW standalone
session appearing on an idle socket means the gate is still trusting power.

**NOTE** the `meter_power_implausible` alarms. With the detector live, each single-phase
socket reporting an impossible figure raises one. Seeing them is CORRECT — it is the fault
becoming visible, not a new fault. Record how many and on which sockets.

**STOP if** Q1 raises one. Q1 is the three-phase meter that has never lied; an alarm there
means the invariant is wrong, not the meter.

---

### 1.7 — The needs-attention filter, with a cabinet that goes quiet

**This is the check that justifies the area.** Do it last and do it physically.

1. Confirm `/marina` shows all four berths under **All**, and the attention filter shows only
   what is genuinely wrong.
2. **Pull the cabinet's network cable**, or stop the broker: `sudo systemctl stop mosquitto`.
3. Wait 90 seconds (the comm-loss threshold is 60 s).
4. Reload `/marina` on the phone, with the **Needs attention** filter selected.

**STOP unless** the berths appear in the needs-attention view reading **"No contact with this
pedestal"**. An empty dashboard here is the exact defect this profile exists to prevent —
staff looking at a clean screen while nothing can be seen.

5. Restore the cable / `sudo systemctl start mosquitto`. Within ~30 s the rows return to normal.

**NOTE** how long the recovery took.

### 1.8 — Phone layout

On the phone, at every one of the six screens:

**STOP if** the page scrolls sideways, or any **status sentence is cut off** with an ellipsis.
The sentence is the most important text on the row.

---

## AREA 2 — Guard: detection, camera, and the five measured criteria (90 min)

### 2.1 — The flow (physical, needs two people)

1. Arm guard for the cabinet.
2. One person walks into frame, stops, stays ~10 s.
3. On the marina guard screen and in the admin guard view, confirm:

| Check | |
|---|---|
| Alarm raised | within ~5 s of the person being in frame |
| Clip recorded | the file exists and **plays**, and is longer than one segment |
| Annotated frame | visible, with the person boxed |
| Correct / false labelling | both buttons work and the choice sticks after a reload |

**STOP if** the clip exists but will not play, or is exactly one segment long — that was a
real defect once (assembly running before the post-roll completed) and it reports success.

### 2.2 — The five criteria, MEASURED

Numbers, not assertions. Record each one.

| # | Criterion | How to measure | Record |
|---|---|---|---|
| a | CPU, guard **off** | `top -bn3 \| grep "Cpu(s)"` — take the 3rd sample, 3 times, 1 min apart | ___ % |
| b | CPU, guard **on and armed** | same, while armed and idle | ___ % |
| c | Berth occupancy unchanged | note the occupancy/match state of all four berths **before arming**, then after arm → alarm → suspend → re-arm. It must be **identical** | pass / fail |
| d | Forced CPU overload suspends within 60 s | `stress-ng --cpu $(nproc) --timeout 120s` (or `yes > /dev/null &` per core). Time from load start to guard reporting **paused** | ___ s |
| e | Forced low disk disables **recording only** | fill the clip partition to under the threshold (`fallocate -l <size> /var/lib/cloud-iot/guard/_filler`). Guard must stop RECORDING and keep DETECTING | pass / fail |

**STOP if** (d) exceeds 60 s, or (e) stops detection as well as recording, or (c) shows any
change in berth occupancy.

**Delete the filler file afterwards.** `rm /var/lib/cloud-iot/guard/_filler`

**NOTE:** (a) and (b) are the pair that matters — the difference is guard's cost, and it is
the number to quote.

---

## AREA 3 — Meter and valve readings, smart mode ON and OFF (40 min)

### 3.1 — Smart mode ON

With a real load on one socket and water running on one valve:

**STOP unless** `/marina` shows a changing watts figure on the right berth, `/marina/water`
shows L/min on the right outlet, and the berth-detail month-to-date rises and is labelled
**"meter reading"**.

### 3.2 — Smart mode OFF — the important half

Turn smart mode off (admin only; the marina profile cannot).

**STOP unless ALL of these are true:**

1. Readings **still arrive and still display** — watts and litres keep updating. Monitoring
   does not stop.
2. **No control is rendered.** Not greyed, not disabled — **absent**. Inspect the page if
   unsure: there must be no `<button>` for power or water.
3. Each affected row reads **"this pedestal is running on its own, monitoring only"**.
4. The berth status is **"Not known"**, not "Needs attention" — the Opta is working and
   nothing is wrong at the berth.

Turn smart mode back on and confirm controls return.

---

## AREA 4 — NFC end to end, smart mode ON (40 min)

Use a **test customer**, not a real one: the session and its ledger rows are a permanent
record.

### 4.1 — One electricity tag

1. Provision a tag to a socket (admin, `/api-gateway` or the NFC table).
2. Customer scans → ERP authorises → **we switch the outlet**.
3. Plug in a load.

| Check | |
|---|---|
| Outlet switched on | physically, and on `/marina` |
| Consumption recorded | berth detail rises |
| `consumption_source` | **`register`**, not `integrated_legacy` or `unknown` |
| Session reported to ERP | `session_activated`, then `session_ended` |

### 4.2 — One water tag

Same with a valve tag (`V1` or `V2`).

**STOP if** the water session is reported as outlet `Q…` rather than `V…`, or carries an
`energy_kwh` figure. Water must report `water_liters` and `session_type: "water"`.

**NOTE:** a water tag can only be provisioned if the site allows it. Krk is MODE 1 (ERP
present), so it is allowed; a MODE 2 site refuses until the app ships.

---

## AREA 5 — ERP integration ⚠ NEEDS SOMEONE AT myMarina

**This step cannot be done alone, and as of 2026-10-10 it is BLOCKED.** Two findings from the
2026-08-21 verification of the live `external_api_config` row:

* **D17** — the whole `/api/ext/` family returned **401**: `pedestals/{id}/status`,
  `pedestals/{id}/water`, `marinas/{id}/load/alarms`, `marinas/{id}/breaker/alarms`. Those are
  exactly the routes the ERP uses. Only the older `/api/...` routes passed.
* **D18** — `allowed_events` contains `["heartbeat", "temperature_reading"]` and **none of the
  session events** the ERP integration document describes.

Neither blocks this deploy. Both block this area. Record it as blocked and move on; do not
treat the deployment as unfinished because of it.

Arrange a person on the myMarina side before attempting it.

**Irreversible:** once myMarina receives a water session, it has it. If their side is not
ready, turn water reporting **off** first — `/api-gateway`, "What this ERP receives" — and
turn it on with them watching.

| Check | |
|---|---|
| The figures we send are what they expect | per-session consumption, tied to the scanning customer |
| They can bill from them | confirmed by them, not inferred by us |
| **Water sessions arrive and are handled** | new in v3.44 — the guard that excluded them is removed |
| Cumulative per-outlet matches | our register totals against their record |

**STOP if** water events are rejected or mis-posted. Turn the toggle off, which stops reporting
without stopping recording — the history stays intact for when they are ready.

---

## STEP 3 — After acceptance

The merge to `main` happened BEFORE the cabinet upgrade, so there is no "switch the cabinet
back" step and no cabinet left on a test branch. That was the point of the change.

```bash
cd ~/Cloud_IOT && git rev-parse --abbrev-ref HEAD      # must print: main
```

**Do not run `upgrade.sh` on the second cabinet until this one is accepted.** It pulls from
`main` too, so the merge has already reached it the moment it is upgraded.

---

## If something fails

| Symptom | Do this |
|---|---|
| Any STOP in STEP 2 | `cd ~/Cloud_IOT && git checkout 773bca6` then re-run `upgrade.sh`. That commit is what the cabinet ran before and stays reachable forever. |
| A screen is wrong but the cabinet works | Record it with a screenshot and continue. A UI defect is not a reason to roll back a working cabinet. |
| Guard fails area 2 | Stop guard (`sudo systemctl stop cloud-iot-guard`) and continue with areas 3–5. Guard is a separate service and does not block the UI. |
| Readings wrong in area 3 | **Stop.** This is consumption, and a wrong figure reaches the ERP. Roll back. |
| Area 4 switches the wrong outlet | **Stop immediately and roll back.** A customer is paying for someone else's socket. |
| Area 5 rejected by myMarina | Turn the water toggle off. Do not roll back — everything else is working, and the history is kept. |

**In every case, record what the log said before acting.** `journalctl -u cloud-iot-backend -n 200`
written to a file beats a remembered summary.

---

## What this runbook does NOT cover

- **The 23 pre-existing Playwright failures** (deferred D16, 2026-10-02). They were never
  running — the e2e runner skipped on a backend check that mocked specs never needed. Not in
  scope here and not a reason to delay.
- **Notifications.** There is no notification path, not even disabled. By instruction.
- **QR.** Dormant since 2026-09-30.
