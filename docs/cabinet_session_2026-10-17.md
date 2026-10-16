# Cabinet 1 (MAR_KRK_ORM_01) — the upgrade session, 2026-10-17

One file, in order. For every step: the command, what you expect, what you do if you do not see
it. The rows refer to `docs/ui_v2_spec.md` §13 (on `develop`); this file is the order of play.
**Target: `main` = `1554bcfb04f25f550a64e57d08dfb8f2d3d74074`.** Today the cabinet runs `aa1f74f`.

Rules for the whole session:
- No secret on a command line or in this file's outputs: the camera URL, `ERP_API_KEY`, passwords
  are read with `read -s` or edited with `sudoedit`, never typed after a command.
- Anything not as expected → STOP and report; never improvise on the cabinet.
- `R=~/Cloud_IOT` below = the clone you upgrade from (the one `upgrade.sh` lives in).
- `B=/root/rollback-20261017` = where every rollback copy goes (step 2).

---

## 0. Before anything

| # | Command | Expect | If not |
|---|---|---|---|
| 0.1 | Open TWO sessions — one via `ssh2.lika.solutions`, one via Tailscale — and keep both open to the end | both live | STOP |
| 0.2 | `df -h / /root /opt` | room for the venv + app + dist + two databases (a few GB) | STOP — free space first |
| 0.3 | `git -C $R status --short; git -C $R rev-parse --short HEAD` | empty status; `aa1f74f` | a dirty clone: STOP, report what is changed |

## 1. E.11 — the camera route, BEFORE (for the record)

```
curl -s -m 5 -o /tmp/s.bin -w '%{http_code}\n' http://localhost/api/camera/1/stream; wc -c < /tmp/s.bin; rm -f /tmp/s.bin
```
RECORD the code and the byte count. 200 with more than 0 bytes = the camera was open until now.
Nothing to do about it here — the upgrade closes it.

## 2. C — the manual rollback copies (do not rely on `upgrade.sh`)

```
sudo mkdir -p /root/rollback-20261017 && B=/root/rollback-20261017
git -C $R rev-parse HEAD | sudo tee $B/commit
U=$(systemctl show -p FragmentPath --value cloud-iot-backend.service); echo "$U" | sudo tee $B/unit.path
sudo cp -a "$U" $B/cloud-iot-backend.service
sudo cp -a /opt/cloud-iot/backend/.venv  $B/venv
sudo cp -a /opt/cloud-iot/backend/app    $B/app
sudo cp -a /opt/cloud-iot/frontend/dist  $B/dist
sudo cp -a /etc/nginx/sites-enabled      $B/nginx-sites-enabled
sudo python3 -c "import sqlite3;[sqlite3.connect(s).backup(sqlite3.connect(d)) for s,d in (('/opt/cloud-iot/backend/pedestal.db','$B/pedestal.db'),('/opt/cloud-iot/backend/data/users.db','$B/users.db'))]"
sudo python3 -c "import sqlite3;print([sqlite3.connect(f).execute('PRAGMA integrity_check').fetchone()[0] for f in ('$B/pedestal.db','$B/users.db')])"
stat -c '%U:%G' /opt/cloud-iot/backend/pedestal.db | sudo tee $B/db.owner
sudo ls -la $B; sudo du -sh $B
```
| Expect | If not |
|---|---|
| `commit` = the full hash of `aa1f74f…`; `unit.path` a real path; `venv`, `app`, `dist`, `nginx-sites-enabled` present; `['ok', 'ok']`; an owner such as `cloud-iot:cloud-iot` | STOP — no upgrade without every copy |

**Why the app and the frontend too:** `upgrade.sh` copies `backend/app` and the built frontend
over `/opt` — and on the path used below it rebuilds and swaps the FRONTEND before it installs
the backend's dependencies (`upgrade.sh:287` "Rebuilding frontend" runs before `:340` "Deploying backend" and its pip at `:358`). If pip fails there, the new
UI runs on the old backend. Rolling back the code means putting these two back.
Both databases use the SQLite backup API — never `cp` on a live WAL database.

## 3. Readings before the upgrade (read-only)

| # | Command | Expect / record |
|---|---|---|
| 0.6 | `systemctl list-unit-files 'ssh*' --no-legend`; then `for u in cloudflared tailscaled docker nginx ssh; do echo "$u $(systemctl show -p NeedDaemonReload --value $u)"; done` | every line ends in `no` — else STOP: someone changed a unit and our `daemon-reload` would activate it |
| 0.7 | `ss -ltn 'sport = :8000'` | `0.0.0.0:8000` (the old state) |
| 0.8 | `sudo grep -c '^ERP_API_KEY=.\+' /opt/cloud-iot/backend/.env` | RECORD (`1` = set; E.15 empties it later) |
| E.14 | `sudo grep -E '^JWT_EXPIRE_MINUTES=' /opt/cloud-iot/backend/.env \|\| echo "not set — the default, 120 min (config.py:21)"` | RECORD — how long a leaked token lives |
| E.12 | `grep -n "X-Real-IP\|proxy_pass\|listen" /etc/nginx/sites-enabled/*; sudo grep -n "service:\|hostname:" /etc/cloudflared/*.yml 2>/dev/null` | RECORD: `X-Real-IP $remote_addr` in the `/api/` location; the local port each tunnel hostname targets |
| G.0 | §6 below, "before" | RECORD |

## 4. The manual `git pull` — BEFORE `upgrade.sh` (owner's order) — and why it is safe

```
sudo -u "$(stat -c %U $R)" git -C $R pull --ff-only origin main
git -C $R rev-parse HEAD
```
Expect `1554bcfb04f25f550a64e57d08dfb8f2d3d74074`. Not that, or "not possible to fast-forward":
STOP (nothing is deployed yet — `/opt` is untouched).

**Why this order is safe — read from `upgrade.sh` on `main`:**
- After a manual pull, `upgrade.sh` finds git already current (`NEEDS_PULL=false`) but
  `/opt/cloud-iot/backend/app` different from the repo (`NEEDS_SYNC=true`, `:166-175`, comment at `:169` — the
  comment there: "This catches the case where someone ran git pull manually before the
  script"), and **re-deploys**. It does NOT stop at "Already up to date": that line needs both
  false (`:177-181`).
- On that path it cannot know which files changed, so it **installs both dependency sets**
  (`DEPS_UNKNOWN`, `:233`) — slower, never a skipped install.
- **It is the SAFER order:** pulling inside the running script means bash may keep executing the
  OLD copy of `upgrade.sh` (aa1f74f's, without the loopback rewrite and the bind check). Pulled
  first, the script you run IS `main`'s — the loopback rewrite (`:330`) and the bind check
  (`:382`) are certain to run.

## 5. U.0 — will pip succeed? (changes nothing)

```
sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/pip install --dry-run -r $R/backend/requirements.txt 2>&1 | tail -15
```
Expect a resolution with no error ("Would install …" or nothing to install). **Known risk:**
`requirements.txt` pins `reportlab==4.2.5` (`:135`), and README says it has no wheel for
Python 3.14 — the cabinet's venv may need it built from source. **An error here → STOP; do not
run `upgrade.sh`.** Nothing is deployed yet; report the last 15 lines.

## 6. G — is the guard worker running? (measure, do not assume)

**Before the upgrade (G.0):**
```
systemctl list-unit-files 'cloud-iot-guard*' --no-legend; systemctl is-active cloud-iot-guard 2>&1
ls -ld /opt/cloud-iot/guard /opt/cloud-iot/guard_worker /var/lib/marina-guard 2>&1
sudo journalctl -u cloud-iot-guard -n 5 --no-pager 2>&1 | tail -5
sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('file:/opt/cloud-iot/backend/pedestal.db?mode=ro',uri=True);print([ (t, c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]) for t in ('guard_config','guard_events','guard_detections','guard_recordings')])"
```
The LAST publication of a worker — the broker keeps the last `state` retained, `health` comes
every 5 s only from a LIVE worker:
```
B_SUB="mosquitto_sub"; command -v mosquitto_sub >/dev/null || B_SUB="docker exec pedestal-mqtt-broker mosquitto_sub"
timeout 6  $B_SUB -h 127.0.0.1 -t 'marina/+/camera/+/guard/state'  -v -W 5      # the last state (retained, may be old)
timeout 12 $B_SUB -h 127.0.0.1 -t 'marina/+/camera/+/guard/health' -v -C 1 -W 11 # a live heartbeat, or nothing
```
| Reading | Means |
|---|---|
| no unit, no directories, tables 0, no `state`, no `health` | **not installed** — what was confirmed on 2026-10-11 (below) |
| a unit, `active`, `health` within 11 s | running |
| a unit, not active / no `health`, a retained `state` | installed, not running now |

**After the upgrade, on `/marina/guard`, the sentence you should see:**
- not installed → **"No guard on this pedestal"** (S1 — no row, the worker never announced itself).
- running → after `sudo systemctl restart cloud-iot-guard` (a worker that was ALREADY connected
  announced itself before the new backend started; the row is created only from a LIVE state
  message, and the restart makes it announce again — *a gap found writing this file, see the
  end*) → **"Guard off"** (S4: it always comes up OFF and waits). Never "Guard on" without an
  Arm by an admin. Note: `upgrade.sh` does not update `/opt/cloud-iot/guard_worker` — an
  installed worker keeps its old code until `install-guard.sh` is run again (§13.6c G.1/G.3).

**If it is not installed — install and switch on (spec §13.6c, every row there, in order):**
1. The model exists first: `ls /opt/cloud-iot/backend/models/yolov8n_openvino/*.xml` — if not,
   `scripts/guard_export_model.sh` (G.6). Without it the install ends with exit 3 = NOT READY.
2. `sudo bash $R/nuc_image/install-guard.sh; echo "exit $?"` — installs, never starts (G.1–G.3).
   **It proves OpenVINO really runs:** it imports openvino in the guard venv and fails (exit 1)
   if the model cannot be loaded and run (`install-guard.sh:16, 132-133`); G.4 proves openvino is
   NOT in the backend venv.
3. Camera settings in `/opt/cloud-iot/guard/guard.env` with `sudoedit` (F.1), the instance id on
   both sides (G.5), then `sudo systemctl enable --now cloud-iot-guard` (F.4).
4. F.5: `/api/guard/status` lists the camera, `worker_alive: true`, `state: OFF`, sentence
   "Guard off".
5. **No silent fallback:** if the detector cannot load, the worker REFUSES the arm — the ack says
   `accepted: false` and "detector unavailable" (`guard_worker/__main__.py:424`, test
   TC-GSMOKE-06); it never arms on something else. After an Arm by an admin, `state: ARMED`
   appears only from the worker's acknowledgement.

**Switching guard off without touching the cabinet:**
```
sudo systemctl disable --now cloud-iot-guard
```
It is its own service: the backend, nginx, mosquitto and the Opta are not touched. After it, the
page says **"Guard not answering"** (the row exists, the worker is gone — a fault, by design). For
"Guard off" instead: Switch off on `/marina/guard` as admin first, wait for the confirmation,
then stop the service.

**What "not installed on cabinet 1" rested on:** your readings on the cabinet, 2026-10-11 —
`cloud-iot-guard.service` did not exist, `/opt/cloud-iot/guard/` did not exist, and
`guard_detections`, `guard_events`, `guard_recordings` had zero rows. Nothing measured since;
G.0 re-measures it.

## 7. The upgrade

```
sudo bash $R/nuc_image/upgrade.sh
```
Answer `y` to "Apply upgrade?". Expect, in this order:
`Git repo is up to date but /opt/cloud-iot/ is out of sync — will re-deploy.` →
"Rebuilding frontend" → "Binding the backend to loopback" → "Installing backend dependencies" →
"Copying backend/app" → "Backend is up" → **"Checking the backend listens on loopback only" →
"Backend bound to loopback only: 127.0.0.1:8000"** → `Upgrade complete.`

| Seen | Do |
|---|---|
| `pip install FAILED — upgrade stopped before any code was copied` | the NEW frontend is already in place on the OLD backend → **ROLLBACK, §11, now** |
| the loopback line missing, or "listens on a non-loopback address" | STOP, ROLLBACK |
| "Backend taking longer than expected" | `sudo journalctl -u cloud-iot-backend -n 50 --no-pager`; not up within 2 min → ROLLBACK |

## 8. Right after

| # | Command | Expect | If not |
|---|---|---|---|
| 13.3 | both sessions of 0.1 still work; open a NEW ssh session each way | all four work | ROLLBACK |
| E.1 | `git -C $R rev-parse --short HEAD origin/main; ss -ltn 'sport = :8000'; curl -s -o /dev/null -w '%{http_code}\n' http://localhost/api/sessions` | `1554bcf` twice; `127.0.0.1:8000`; `401` or `403` | `200` = the old code runs: STOP |
| E.11 | the command of step 1 again | `401` or `403`, `0` bytes | STOP, report |
| E.15 | `sudoedit /opt/cloud-iot/backend/.env` → `ERP_API_KEY=` (empty); `sudo systemctl restart cloud-iot-backend`; `curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost/api/nfc/scan -H 'X-API-Key: x'` | `503`. The admin UI's NFC screens keep working (measured on dev: the four operator routes do not use the key) | not 503: STOP |

## 9. The gateway: 17b → 17d → 17b → 17e

| # | Command | Expect |
|---|---|---|
| 17b | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3,json;c=sqlite3.connect('file:/opt/cloud-iot/backend/pedestal.db?mode=ro',uri=True);r=c.execute('SELECT allowed_endpoints FROM external_api_config WHERE id=1').fetchone();ids=sorted(e['id'] for e in json.loads(r[0] or '[]')) if r else [];print(len(ids));print(ids);print([i for i in ids if i.startswith('camera.')])"` | RECORD (23 measured on 2026-10-16, four `camera.*`) |
| 17d dry | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 $R/scripts/fix_gateway_allowed_endpoints.py --db /opt/cloud-iot/backend/pedestal.db` | NOW 23, the diff, "DRY RUN — nothing written" |
| 17d | the same with `--apply --backup /opt/cloud-iot/backend/pedestal.db.pre-gateway-$(date -u +%Y%m%dT%H%M%SZ)` | ends with `17b: 17`, the 17 ids, `17b: []` |
| 17b | again | `17`, the 17, `[]` |
| 17e | `read -s EXT_KEY` (the ERP's service token, once the account of §10 exists — else skip and do it after §10); `for p in pedestals/1/camera/frame pedestals/1/camera/stream camera/1/snapshot; do echo "$p $(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $EXT_KEY" http://localhost/api/ext/$p)"; done` | every line `403` |

17d's own `--backup` is a third database copy; exit 4 from it = restore that copy (§11 D).
**Before the ERP gets anything: compare the ERP's list with these 17 — do not assume they match.**

## 10. A — the ERP's read access (configuration)

| # | Step | Check |
|---|---|---|
| A.1 | Admin screen → Settings → "ERP User": `erp@lika.solutions`, role `api_client` (not the script — it takes the password on its command line) | `read -s P; printf '{"email":"erp@lika.solutions","password":"%s"}' "$P" \| curl -s -X POST http://localhost/api/auth/service-token -H 'Content-Type: application/json' -d @- \| python3 -c "import sys,json;print(json.load(sys.stdin).get('role'))"` → `api_client` |
| A.2 | The webhook to the ERP OFF — both of them | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;print(sqlite3.connect('file:/opt/cloud-iot/backend/pedestal.db?mode=ro',uri=True).execute('SELECT webhook_url, allowed_events, active FROM external_api_config WHERE id=1').fetchone())"` → `(None or '', '[]', 1)`; `sudo grep -c '^ERP_WEBHOOK_URL=.\+' /opt/cloud-iot/backend/.env` → `0` |
| E.13 | The one-step switch, tried once: OFF `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('/opt/cloud-iot/backend/pedestal.db');c.execute('UPDATE external_api_config SET active=0 WHERE id=1');c.commit();print(c.execute('SELECT active FROM external_api_config WHERE id=1').fetchone())"`, a call with the ERP token, then the same with `active=1` | `(0,)` → 403/503; `(1,)` → 200. Disabling the account or changing its password is NOT the switch (spec §13.14) |

## 11. The rest of the readings

E.2–E.10, then S.1 and S.2 — the commands are rows E.2–E.10, S.1, S.2 in spec §13.14.
**R1 (§13.10) and §13.7 rows 13/13a do NOT run today** — they need `ERP_API_KEY`, which E.15
emptied; they run in the NFC e2e session with the new per-cabinet key.

## 12. ROLLBACK — from the copies of step 2 only

Run as a block; every line names its path. `B=/root/rollback-20261017`.
```
B=/root/rollback-20261017
sudo systemctl stop cloud-iot-backend
sudo mv /opt/cloud-iot/backend/app  /opt/cloud-iot/backend/app.failed-$(date -u +%H%M%S)  && sudo cp -a $B/app  /opt/cloud-iot/backend/app
sudo mv /opt/cloud-iot/frontend/dist /opt/cloud-iot/frontend/dist.failed-$(date -u +%H%M%S) && sudo cp -a $B/dist /opt/cloud-iot/frontend/dist
sudo cp -a $B/cloud-iot-backend.service "$(sudo cat $B/unit.path)" && sudo systemctl daemon-reload
# only if pip ran (step 7 printed "Installing backend dependencies"):
sudo mv /opt/cloud-iot/backend/.venv /opt/cloud-iot/backend/.venv.failed-$(date -u +%H%M%S) && sudo cp -a $B/venv /opt/cloud-iot/backend/.venv
sudo systemctl start cloud-iot-backend && sudo nginx -s reload
```
Check: `ss -ltn 'sport = :8000'` → `0.0.0.0:8000` (the old unit); `systemctl is-active cloud-iot-backend` → `active`; `/marina` loads.

**D — the databases, ONLY if one is at fault** (not for a code rollback: the new code only ADDS a
table, `guard_state_events`, which the old code ignores):
```
sudo systemctl stop cloud-iot-backend
sudo cp $B/pedestal.db /opt/cloud-iot/backend/pedestal.db && sudo rm -f /opt/cloud-iot/backend/pedestal.db-wal /opt/cloud-iot/backend/pedestal.db-shm
sudo cp $B/users.db /opt/cloud-iot/backend/data/users.db && sudo rm -f /opt/cloud-iot/backend/data/users.db-wal /opt/cloud-iot/backend/data/users.db-shm
sudo chown "$(sudo cat $B/db.owner)" /opt/cloud-iot/backend/pedestal.db /opt/cloud-iot/backend/data/users.db
sudo systemctl start cloud-iot-backend
```
After a rollback the clone `$R` stays on `1554bcf`; the next `upgrade.sh` would find `/opt` out of
sync and re-deploy it — so do not run it until the cause is known. `ERP_API_KEY` (E.15) and the
gateway list (17d) are NOT undone by the code rollback; undo them only if asked.

---

**A gap found writing this file (for the spec, not built):** the guard row is created only by a
LIVE `state` message (§5.5.1), and a worker publishes `state` only when it connects or changes
state; its `health` every 5 s does not create a row. So a worker already running when the backend
restarts stays "No guard on this pedestal" until it reconnects or changes state — hence the
`restart cloud-iot-guard` in §6. Today cabinet 1 has no worker (2026-10-11), so it does not bite
this session.
