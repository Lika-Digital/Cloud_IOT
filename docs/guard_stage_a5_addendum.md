# Guard Stage A.5 — Addendum: answers against the verified NUC state

**Date:** 2026-09-26 · Companion to `guard_phase1_assessment.md`.

Using the NUC facts as given (not re-inferred): Python 3.14.4, numpy 2.4.6, Pillow
12.2.0, no openvino, no opencv, 58 packages, freeze at `~/venv_freeze_2026-09-26.txt`.
Idle load 0.07, 1.3 Gi of 14 Gi RAM used, 397 G free on `/`, backend 316.6 MB RSS
(peak 421.3), `uvicorn --workers 1`, `USE_ML_MODELS=false`.

---

## A1. Can the probe run from a throwaway venv? **YES — proven, not argued**

The import chain is clean. `guard_detect_probe.py` puts `<repo>/backend` on `sys.path`
and imports `app.services.yolo_openvino`, which pulls in:

| What | Result |
|---|---|
| `backend/app/__init__.py` | **0 bytes** — empty |
| `backend/app/services/__init__.py` | **0 bytes** — empty |
| `yolo_openvino.py` module-level imports | `io`, `logging`, `os`, `time`, `typing` — **stdlib only** |
| `numpy`, `PIL`, `openvino` | all **lazy**, inside function bodies |

Nothing drags in fastapi, sqlalchemy or pydantic. Verified empirically in a venv
containing *only* numpy 2.1.2 + Pillow, with the others confirmed absent:

```
confirmed absent: fastapi, sqlalchemy, pydantic, openvino
import of app.services.yolo_openvino: OK
YoloOVDetector(available) = False
detect_persons on unavailable detector -> None
decode+NMS: 1 person det, conf=0.91
probe module imports; alarm rule fired 1 alarm(s)
```

**No import or path forces the production venv.** `scripts/guard_measure.sh` (committed
`d91bef5`) already is that restructure — its own venv, its own IR copy, nothing written
under `/opt/cloud-iot`.

One deliberate deviation from "a `/tmp` venv": it defaults to `$HOME/guard-staging`.
Ubuntu mounts `/tmp` as tmpfs on many installs, and the export step needs ~4 GB for
torch — on a 14 Gi box that would be 4 GB of **RAM**. `/` has 397 G free, so `$HOME` is
safer. Override with `GUARD_STAGING=/tmp/guard-staging` if you want the reboot-clean
behaviour.

Given A4, the production install does not move to Stage B — it disappears.

---

## A2. openvino-telemetry: do not trust an env var — make egress impossible

Three layers, weakest to strongest.

**1. Env var.** `OPENVINO_TELEMETRY_OPT_OUT=1` is the documented opt-out, but I will not
have a marina depend on a variable name I have not verified on your box. Confirm what
the installed package actually reads:

```bash
SP=$(ls -d ~/guard-staging/venv/lib/python3.14/site-packages)
grep -rn "environ\|getenv\|OPT_OUT\|opt_out\|consent" "$SP"/openvino_telemetry/*.py | head -20
```

**2. Remove the package.** Telemetry serves the *tools* (`ovc`, model converter), not
`Core().compile_model()` inference. Test that claim directly rather than assuming it:

```bash
~/guard-staging/venv/bin/pip uninstall -y openvino-telemetry
bash scripts/guard_measure.sh classmap     # must still load the IR and print the map
bash scripts/guard_measure.sh probe --clip /tmp/day.mp4 --expect person
```

If `openvino/__init__.py` imports it unconditionally, the import fails loudly — which is
exactly the outcome we want to discover in a staging venv rather than in production.

**3. Block egress at the unit — the actual guarantee.** The guard worker needs localhost
(MQTT) and the camera, nothing else. In `cloud-iot-guard.service`:

```ini
Environment=OPENVINO_TELEMETRY_OPT_OUT=1
IPAddressDeny=any
IPAddressAllow=localhost 192.168.1.0/24
```

This makes phoning home structurally impossible regardless of any library's defaults, or
a future version changing them. Verify with `journalctl -u cloud-iot-guard | grep -i
denied` plus a deliberate outbound test.

Layer 3 is the one I would defend in a review. Layers 1 and 2 are hygiene. Note this
per-unit block is only available because of A4 — it cannot be applied to the backend,
which legitimately needs the tunnel and ERP webhooks.

---

## A3. numpy drift — cause, test, recommendation

**Cause.** numpy 2.1.2 (Oct 2024) predates Python 3.14 (Oct 2025), so it ships no cp314
wheel and can only source-build on your box. That is why the 3.14 venv was rebuilt by
hand with relaxed pins, and pip then resolved numpy to 2.4.6. `upgrade.sh:204-208` runs
`pip install -r requirements.txt` but only **warns** on failure, so the unsatisfiable pin
failed silently on every upgrade while 2.4.6 stayed in place. Nothing was broken by this
— the pin was simply fiction.

**Tested on the version you actually run: 675 passed on numpy 2.4.6.** Also 675 on 2.1.2
and on 2.5.3, so the code is not sensitive to the difference.

**Recommendation, applied in commit `6a404b2`:** `numpy>=2.1,<3`. A range makes the file
match reality, so pip does nothing instead of failing every upgrade — strictly less risky
than the status quo.

**Wider issue worth knowing:** numpy is almost certainly not the only drifted package.
*Every* other entry in `requirements.txt` is a `==` pin from the 3.12 era —
`scikit-learn==1.5.2`, `pydantic==2.9.2`, `fastapi==0.115.0` — and the no-cp314-wheel
argument applies to several of them. One command shows the true extent:

```bash
diff <(sed 's/#.*//;/^[[:space:]]*$/d' /opt/cloud-iot/backend/requirements.txt | sort) \
     <(sort ~/venv_freeze_2026-09-26.txt)
```

I did not widen the change to cover that; it deserves its own task.

---

## A4. Separate process vs production venv — **recommendation: separate process**

I agree, and for stronger reasons than the RAM headroom alone. Run the detector as its
own systemd service, `cloud-iot-guard.service`, own venv at `/opt/cloud-iot/guard/.venv`,
talking to the backend over the **MQTT broker already running on localhost**, which
already carries the guard topics the Stage B spec defines.

**Why:**

1. **Two Stage B requirements come free.** "No model resident while disarmed" and
   "release within 5 s" become "the process is not running" — verifiable with
   `systemctl is-active` and `ps`. In-process this is genuinely hard to *prove*: freeing
   an OpenVINO compiled model does not reliably return RSS to the OS, so a correct
   `unload()` can still look like a leak.
2. **A native segfault cannot take down the marina.** openvino is a large C++ library.
   In-process, a crash in it kills uvicorn and with it MQTT ingest, sessions and the
   dashboard — and `--workers 1` means there is no second worker to absorb it.
3. **The CPU watchdog becomes trustworthy.** Per-process CPU is measured directly rather
   than inferred, and "shed guard first, never berth occupancy" becomes `systemctl stop`
   plus `CPUQuota=`/`Nice=` — enforced by the kernel, not by our own good behaviour.
4. **The hard constraint becomes structural.** openvino never enters the production venv,
   so `requirements.txt` and `upgrade.sh` stay untouched and the A3 class of drift cannot
   recur through guard.
5. **Egress can be blocked per-unit** (A2 layer 3) without constraining the backend.

**What it costs:**

| Cost | Assessment |
|---|---|
| Second systemd unit + venv provisioning | ~40 lines, one-time |
| IPC | **Near zero** — MQTT is already running, already localhost, and the spec already mandates guard topics. No new transport. |
| DB writes | Guard publishes; **the backend stays the only DB writer** and persists recording rows from the MQTT event. Avoids two SQLite writers. |
| Extra RSS | ~30–50 MB armed-idle, **0 when disarmed** (process exits). Against 12 Gi free, noise. |
| Debugging | Two log streams; mitigated by journald under its own unit. |
| Video serving | `GET /api/guard/events/{id}/video` stays in the backend reading the shared recordings path — no IPC on that path. |

**Net:** the IPC cost that normally makes people avoid this design is already paid, because
MQTT is running and the spec already wants those topics. That makes the separate process
cheaper than usual *and* strictly safer. Recommended without reservation.

**Consequence for B1:** `app/guard/` becomes a thin control/query layer (REST, DB,
WebSocket push) while detection, ffmpeg and recording live in the worker. To be restated
precisely for approval before any Stage B code.

---

## A5. Recorded, not fixed

TME sensor `192.168.1.254`: `values.xml` → HTTP 404, `fresh.xml` → 200. Recorded in
project memory, no change made. Consistent with `tests/backend/test_tme_fresh_xml.py`
already existing, i.e. `fresh.xml` is the supported path.
