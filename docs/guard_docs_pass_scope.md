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

## Carry-forward tasks — separate work, NOT inside guard or UI v2

1. **`requirements.txt` drift audit.** Only numpy was fixed (`6a404b2`,
   `numpy>=2.1,<3`). Every other entry is still a `==` pin from the Python 3.12 era
   (`scikit-learn==1.5.2`, `pydantic==2.9.2`, `fastapi==0.115.0`, …) and the
   no-cp314-wheel argument applies to several. Full diff:
   ```bash
   diff <(sed 's/#.*//;/^[[:space:]]*$/d' /opt/cloud-iot/backend/requirements.txt | sort) \
        <(sort ~/venv_freeze_2026-09-26.txt)
   ```
2. **TME sensor 404.** `192.168.1.254` returns HTTP 404 on `values.xml` while `fresh.xml`
   returns 200. Consistent with `tests/backend/test_tme_fresh_xml.py` (fresh.xml is the
   supported path), so likely a dead code path or a stale fallback URL to remove. Observed
   2026-09-26, not investigated.
