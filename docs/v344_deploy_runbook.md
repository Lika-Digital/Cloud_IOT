# v3.44 — UI v2 + Guard: deploy and acceptance runbook

**Date:** 2026-10-03 · **Target:** the Krk cabinet, `MAR_KRK_ORM_01` · **Branch under test:**
`develop`

Same shape as `docs/guard_a5_runbook.md`: numbered steps, each ending in **STOP** (do not
continue) or **NOTE** (record and carry on). Phone first — several checks must be done on a
phone standing at the pedestal, not at a desk, because that is where this UI is used.

---

## Read this before step 0

### We deploy from `develop`. `main` is not touched until everything passes.

```bash
sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh develop     # the test deployment
sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh             # back to main — the rollback
```

The branch argument is new in v3.44. **The default is still `main`**, so every existing
instruction and habit keeps working.

### The rollback is that `main` was never touched

There is no snapshot to take and no backup step, because nothing is being overwritten:
`main` still points at **v3.40**, the last release the cabinet ran. While the NUC is on
`develop`, that commit is sitting on the remote untouched, and returning to it is one command
with no argument.

This is stated plainly because a rollback plan nobody has read is not a rollback plan. It is
**verified in STEP 1**, not assumed.

### Which steps are irreversible

| Step | Reversible? |
|---|---|
| Deploying `develop` to the NUC | **Yes** — re-run `upgrade.sh` with no argument |
| Everything in acceptance areas 1–3 | **Yes** — read-only, or a control the operator can undo |
| Area 4 — provisioning an NFC tag | **Yes** — a tag can be un-pointed from the dashboard, and the removal is recorded |
| Area 4 — a real customer session | **Partly** — the session and its ledger rows are a record of something that happened and are not deleted. That is correct; use a test customer. |
| Area 5 — water events reaching the ERP | **NO.** Once myMarina receives a water session it has it. See area 5. |
| **Merging `develop` to `main`** | **THE IRREVERSIBLE ONE.** After this the cabinet, and every future cabinet, updates to it. Do not do it until all five areas pass. |

### One area needs someone else

**Area 5 needs a person on the myMarina side.** It cannot be completed alone, and it is the
only step with an external dependency. Arrange it before starting, or expect to stop at area 4
and wait.

---

## STEP 0 — Baseline, before anything changes (5 min)

Record what the cabinet is running now, so "it broke" can be told from "it was already like
that".

```bash
cd ~/Cloud_IOT && git rev-parse --abbrev-ref HEAD && git rev-parse --short HEAD
systemctl is-active cloud-iot cloud-iot-guard mosquitto
curl -s localhost:8000/api/pedestals | head -c 200
df -h / | tail -1
```

**STOP if** the repo is not on `main`, or `cloud-iot` is not `active`. Something is already
wrong and this is not the moment to add a deployment to it.

**NOTE** the commit hash. That is the rollback target, and STEP 1 checks you can reach it.

---

## STEP 1 — Verify the rollback BEFORE relying on it (3 min)

Do this now, while everything still works. A rollback tested for the first time during an
incident is a hope, not a plan.

```bash
cd ~/Cloud_IOT
git fetch origin main
git rev-parse --short origin/main        # expect the v3.40 commit from STEP 0
git log origin/main -1 --format='%h %ci %s'
```

**STOP if** `origin/main` is not the commit you recorded in STEP 0. It means `main` has moved
and the rollback target is not what you think it is.

**NOTE:** this is the whole rollback. `main` is a commit on the remote that nothing in this
procedure writes to.

---

## STEP 2 — Deploy `develop` (10 min)

```bash
sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh develop
```

The script prints a warning that it is not deploying `main`. That warning is deliberate: a NUC
left on a test branch silently stops receiving releases.

```bash
systemctl is-active cloud-iot cloud-iot-guard
journalctl -u cloud-iot -n 40 --no-pager | grep -iE "error|traceback" || echo "clean"
curl -s localhost:8000/api/marina/berths -H "Authorization: Bearer $TOKEN" | head -c 300
```

**STOP if** `cloud-iot` is not active, or the log shows a traceback, or `/api/marina/berths`
404s. Roll back (`upgrade.sh` with no argument) and report what the log said.

**NOTE:** the first start applies the new migrations (`berth_assignments`, valve state
columns). They are additive and idempotent, but note the startup line that confirms it.

---

# ACCEPTANCE — five areas, in this order

Do them in order. Each builds on the one before.

---

## AREA 1 — UI v2, all six screens, phone AND desktop (45 min)

Open each on a **desktop browser** and on a **phone**, on the marina wifi, signed in as a
`monitor` (not admin — that is the role staff use).

| # | Screen | What must be true |
|---|---|---|
| 1.1 | `/marina` | One row per berth. Status is **colour + icon + word**, never colour alone. One figure per row. A berth with no reading shows **—**, never `0`. |
| 1.2 | `/marina/berth/<id>` | Socket name, **rating and phase count** — Q1 must read 32 A three phase and Q3/Q4 16 A. Month-to-date carries its provenance ("meter reading"). |
| 1.3 | `/marina/water` | Two outlets, by outlet. No berth column. A free outlet reads **Free**, a silent one **Not known** — and those must look different. |
| 1.4 | `/marina/alarms` | Plain sentences. **No error codes, no identifiers** such as `meter_power_implausible`. |
| 1.5 | `/marina/guard` | Four words only. If the guard worker is stopped it must read **"Guard unavailable"** and never "Guard off". |
| 1.6 | `/marina/setup/<pid>` | Step 2 lists the four berths with their sockets, pre-filled. Ratings shown. No water column. **No smart-mode control anywhere.** |

**STOP if** any screen shows a raw error code, a `0` where a figure is unknown, or a
greyed-out control instead of a sentence.

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

**This step cannot be done alone.** Arrange a person on the myMarina side before starting.

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

## STEP 3 — Merge to `main` (the irreversible step)

**Only after all five areas pass.**

```bash
# On the development machine, not the NUC
git checkout main
git merge develop
CLOUD_IOT_RELEASE=1 git push origin main
```

The pre-push hook on `main` requires confirmation. That prompt is the last point at which this
is reversible.

Then, on the NUC:

```bash
sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh      # no argument — back on main, now at v3.44
cd ~/Cloud_IOT && git rev-parse --abbrev-ref HEAD    # must print: main
```

**STOP if** the NUC is left on `develop`. It will stop receiving releases and nobody will
notice for weeks.

---

## If something fails

| Symptom | Do this |
|---|---|
| Any STOP in STEP 2 | `sudo bash upgrade.sh` (no argument). The cabinet returns to v3.40. |
| A screen is wrong but the cabinet works | Record it with a screenshot and continue. A UI defect is not a reason to roll back a working cabinet. |
| Guard fails area 2 | Stop guard (`sudo systemctl stop cloud-iot-guard`) and continue with areas 3–5. Guard is a separate service and does not block the UI. |
| Readings wrong in area 3 | **Stop.** This is consumption, and a wrong figure reaches the ERP. Roll back. |
| Area 4 switches the wrong outlet | **Stop immediately and roll back.** A customer is paying for someone else's socket. |
| Area 5 rejected by myMarina | Turn the water toggle off. Do not roll back — everything else is working, and the history is kept. |

**In every case, record what the log said before acting.** `journalctl -u cloud-iot -n 200`
written to a file beats a remembered summary.

---

## What this runbook does NOT cover

- **The 23 pre-existing Playwright failures** (deferred D16, 2026-10-02). They were never
  running — the e2e runner skipped on a backend check that mocked specs never needed. Not in
  scope here and not a reason to delay.
- **Notifications.** There is no notification path, not even disabled. By instruction.
- **QR.** Dormant since 2026-09-30.
