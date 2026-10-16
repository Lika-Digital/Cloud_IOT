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

**STEP 0 — the very first thing:** open BOTH ways into the cabinet — SSH over **Tailscale**
and SSH over **Cloudflare** (`ssh2.lika.solutions`) — and keep both open to the end, so losing one
never closes access.

---

## P1. What is where (2026-10-16 work)

| Item | In `main` `1554bcf` (goes to the cabinet) | Only on `develop` (does not go) | Only in the spec — no code |
|---|---|---|---|
| Guard UI: S1–S5, row on the worker's announce, re-arm after restart, missed ack, admin only (API + page), the alarm from guard events, "Not measured", playback and labels | ✔ `3ab0cc6` | | |
| S6 "Guard recording although switched off" + Q4b | ✔ `5ec542e` | | |
| Worker: the automatic resume really resumes; the budget in health | ✔ `e6b207a` — reaches the cabinet only with the guard install (§12) | | |
| The camera ban (`camera.*` refused to the ERP) | ✔ `36228c2` | | |
| `scripts/fix_gateway_allowed_endpoints.py` (17d) | ✔ | | |
| The /api/ext filter: camera password and `customer_name` | ✔ `69fa715` | | |
| Smart mode: diagnostics out of the gate; TC-SM-01..05 | ✔ `78bcc62` | | |
| The live camera route demands a login | ✔ `1554bcf` | | |
| The marina line limit 2 758; the vite proxy fix; the flaky-test fix | ✔ | | |
| Spec through D32 plan + continued, D32-Q1, R4 closed, latency | ✔ (docs) | | |
| Spec: rule H, E.13–E.15, the measured A1 table | | ✔ `f9571f0` (docs) | |
| This session file; F; K | | ✔ (docs, today) | |
| D32 live view (TC-LV-01..12), masks, blur M11, viewing log | | | ✔ |
| Rule H in code (TC-MC-TUN-01..03), the 403 through the tunnel | | | ✔ |
| `ERP_API_KEY` per cabinet, rotation | | | ✔ (E.15 only EMPTIES it today) |
| Closing `/api/customer/*`, `/api/mobile/*`, QR | | | ✔ |
| SM-Q6: no command "Sent" until the Opta confirms | | | ✔ |
| K (a live health creates the row; "Not measured" after a restart) | | | ✔ |
| F (one reference photo per berth, replaced) | | | ✔ |
| R22–R26 (webhook, R26 upload) · R27–R30 (wait for the ERP) | | | ✔ |
| Findings A and B, the analyze 500 | | | ✔ |
| The weekly PDF | | | ✔ |

**"Described but not built" — the spec check of 2026-10-16, by name** (spec §0.2):
1. §5.4 alarms filterable **by pedestal and by berth** (the page filters active / all only);
2. §5.3 the **reference photo and "camera now" as pictures** on berth detail (it shows sentences);
3. §3 **TC-UIR-02** — "every rendered condition has a string-table entry" (no test carries it);
4. §9 **TC-UIS-01** — a stale cabinet reads grey (never written);
5. §9 **TC-UIR-05, TC-UIR-06, TC-UIR-07** (never written);
6. §9 **the tap count** (not measured);
7. §1 **BLOCK-1** — the real berths at Krk (open);
8. §1.3 **Card 5** — the water toggle.

## P2. The order of execution — final

| # | Step | Who | Section |
|---|---|---|---|
| 0 | Both SSH paths open (Tailscale + Cloudflare) | owner, cabinet | top |
| 1 | E.11 before | owner, cabinet | §1 |
| 2 | C — the rollback copies | owner, cabinet | §2 |
| 3 | Readings 0.6, 0.7, 0.8, E.14, E.12 (G.0 done 2026-10-17) | owner, cabinet | §3, §6 |
| 4 | Manual `git pull` | owner, cabinet | §4 |
| 5 | U.0 `pip --dry-run` | owner, cabinet | §5 |
| 6 | `upgrade.sh` | owner, cabinet | §7 |
| 7 | 13.3 access, E.1, E.11 after | owner, cabinet | §8 |
| 8 | E.15 — `ERP_API_KEY` emptied | owner, cabinet | §8 |
| 9 | 17b → 17d dry → 17d `--apply` → 17b | owner, cabinet | §9 |
| 10 | A.1 the ERP account, then 17e with its token | owner, cabinet | §10, §9 |
| 11 | A.2 both webhooks off; E.13 the switch tried off and on | owner, cabinet | §10 |
| 12 | E.2–E.10, S.1, S.2; M6, M10 (read-only) | owner, cabinet | §11 |
| 13 | **Guard — last** | owner, cabinet | §12 |
| 14 | Read every output, record it in spec §13, report | me, repo | — |

## P3. When I stop

| Condition | The command that shows it | What I do |
|---|---|---|
| `pip --dry-run` fails | §5 — an error in the last 15 lines | STOP before `upgrade.sh`; nothing is deployed; send the lines |
| `git pull` fails or leaves a dirty tree | §4 — not fast-forward, or `git -C $R status --short` not empty, or HEAD ≠ `1554bcf…` | STOP; nothing is deployed |
| No loopback-check line in the log | `sudo grep -c "Checking the backend listens on loopback only" /var/log/cloud-iot/upgrade.log` (0 new) | ROLLBACK §13 |
| pip fails inside `upgrade.sh` | "pip install FAILED — upgrade stopped before any code was copied" | ROLLBACK §13 now (the new frontend is already in) |
| The backend does not come up | `systemctl is-active cloud-iot-backend`; `sudo journalctl -u cloud-iot-backend -n 50 --no-pager` | **ONE repair attempt, then ROLLBACK §13** (rule below) |
| :8000 on `0.0.0.0` or `[::]` | `ss -ltn 'sport = :8000'` | ROLLBACK §13 |
| 17b after the script is not 17, or the camera line not `[]` | §9 17b | Do NOT enable the ERP; restore from 17d's `--backup` (§13 D); report |
| Any 17e line not 403 | §9 17e | E.13 switch OFF at once (`active=0`); report; the ERP gets nothing |
| E.11 after the upgrade not 401/403 | §8 E.11 | STOP; check E.1 (the old code may be running); report |
| The guard install exits 1 or 3 | `echo "exit $?"` after `install-guard.sh` | Do not enable guard; record the install log; nothing else rolled back (§12) |

**THE RULE (owner, 2026-10-17): if the backend does not come up, I get ONE attempt at a repair,
then I roll back. No debugging on a live cabinet alone on a Saturday.**

## P4. What we do NOT do in this session

Key rotation (a NEW key — E.15 only empties the old one) · closing the customer routes · the 403
through the tunnel · any limit on the service token · D32 code · findings A and B · R22–R26.
**The session is: the upgrade, the gateway list, the measurements, then guard.**

## P5. What we go in NOT knowing

| Unknown | Measured by |
|---|---|
| does `reportlab 4.2.5` install on Python 3.14 | §5 U.0 |
| does the NEW or the OLD copy of `upgrade.sh` run | settled by §4 (pulled first = the new copy runs); proven by the loopback line in §7 |
| does the Opta ignore commands with smart mode off | S.2 (§11) |
| `JWT_EXPIRE_MINUTES` | E.14 (§3) |
| is there a lower camera sub-stream | M6 (§11) |
| is there an iGPU | M10 (§11) |
| does nginx set the source address | E.12 (§3) |
| will guard install on this Python, will OpenVINO load the model | §12 — the install's own SMOKE line (G.8) and its exit code |

## P6. What you send me back, in the order you get it

1. E.11 before (code, bytes) · 2. the `ls -la` / `du` of the copies and `['ok','ok']` · 3. 0.6,
0.7, 0.8, E.14, E.12 · 4. `git rev-parse HEAD` after the pull · 5. the last 15 lines of
`pip --dry-run` · 6. the `upgrade.sh` output (or `tail -60 /var/log/cloud-iot/upgrade.log`) ·
7. 13.3, E.1, E.11 after · 8. E.15 (`503`) · 9. 17b before, the 17d dry run, the 17d `--apply`
output, 17b after · 10. A.1 (`api_client`), 17e's three lines · 11. A.2, E.13 · 12. E.2–E.10,
S.1, S.2, M6, M10 · 13. guard: the `ls` of G.1, the install's exit code and its last 20 log
lines, G.8, F.5.


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
| G.0 | done by the owner on 2026-10-17 — §6 | not installed (recorded) |

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

## 6. G.0 — the guard worker: MEASURED by the owner on 2026-10-17

| Reading | Result |
|---|---|
| `systemctl list-unit-files \| grep -i guard` | nothing |
| `systemctl is-active cloud-iot-guard` | `inactive` |
| `/opt/cloud-iot/guard/` | does not exist |
| `ps -ef \| grep guard` | no process |
| `guard_config`, `guard_events`, `guard_detections`, `guard_recordings` in `pedestal.db` | exist, all empty |
| guard tables in `users.db` | none (correct: they belong in `pedestal.db`) |

**Guard is not installed — confirmed.** **The schema is already there, so the guard INSTALL
adds only the worker** (its venv, unit, directories, `guard.env`, `/opt/cloud-iot/guard_worker`)
and **touches no database** — the worker never opens one; the backend is the only writer
(`backend/app/guard/models.py:4-9`). One table is new with this upgrade, and the BACKEND creates
it, not the guard install: `guard_state_events` (pauses and automatic resumes, §5.5.1), created by
`Base.metadata.create_all` when the new backend starts (`backend/app/database.py:85, 95`) — empty,
nothing migrated, ignored by the old code if it is ever rolled back.

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
| `pip install FAILED — upgrade stopped before any code was copied` | the NEW frontend is already in place on the OLD backend → **ROLLBACK, §13, now** |
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

17d's own `--backup` is a third database copy; exit 4 from it = restore that copy (§13 D).
**Before the ERP gets anything: compare the ERP's list with these 17 — do not assume they match.**

## 10. A — the ERP's read access (configuration)

| # | Step | Check |
|---|---|---|
| A.1 | Admin screen → Settings → "ERP User": `erp@lika.solutions`, role `api_client` (not the script — it takes the password on its command line) | `read -s P; printf '{"email":"erp@lika.solutions","password":"%s"}' "$P" \| curl -s -X POST http://localhost/api/auth/service-token -H 'Content-Type: application/json' -d @- \| python3 -c "import sys,json;print(json.load(sys.stdin).get('role'))"` → `api_client` |
| A.2 | The webhook to the ERP OFF — both of them | `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;print(sqlite3.connect('file:/opt/cloud-iot/backend/pedestal.db?mode=ro',uri=True).execute('SELECT webhook_url, allowed_events, active FROM external_api_config WHERE id=1').fetchone())"` → `(None or '', '[]', 1)`; `sudo grep -c '^ERP_WEBHOOK_URL=.\+' /opt/cloud-iot/backend/.env` → `0` |
| E.13 | The one-step switch, tried once: OFF `sudo -u cloud-iot /opt/cloud-iot/backend/.venv/bin/python3 -c "import sqlite3;c=sqlite3.connect('/opt/cloud-iot/backend/pedestal.db');c.execute('UPDATE external_api_config SET active=0 WHERE id=1');c.commit();print(c.execute('SELECT active FROM external_api_config WHERE id=1').fetchone())"`, a call with the ERP token, then the same with `active=1` | `(0,)` → 403/503; `(1,)` → 200. Disabling the account or changing its password is NOT the switch (spec §13.14) |

## 11. The rest of the readings

E.2–E.10, then S.1 and S.2 — the commands are rows E.2–E.10, S.1, S.2 in spec §13.14.
Then two read-only D32 measurements (spec §16.5):
- **M10 — an iGPU:** `ls -l /dev/dri/; ffmpeg -hide_banner -hwaccels; vainfo 2>&1 | grep -E "Driver|H264"` → RECORD.
- **M6 — sub-streams** (guard is not installed yet, so the camera URL is typed into a hidden
  variable, never shown): `read -s CAMURL` (e.g. `rtsp://user:pass@192.168.1.191:554`, no profile),
  then `for p in profile1 profile2 profile3; do echo "== $p"; timeout 15 ffprobe -v error -rtsp_transport tcp -select_streams v:0 -show_entries stream=codec_name,profile,width,height,r_frame_rate,bit_rate -of default=nw=1 "$CAMURL/$p" 2>&1 | sed -E "s#rtsp://[^ ]*#<url>#g" | head -8; done; unset CAMURL`
  → RECORD per profile.
**R1 (§13.10) and §13.7 rows 13/13a do NOT run today** — they need `ERP_API_KEY`, which E.15
emptied; they run in the NFC e2e session with the new per-cabinet key.

## 12. GUARD — the LAST step of the session (owner, 2026-10-17)

**Only after everything above, 17e included.** If guard blocks, it must not spoil the upgrade's
checks or the gateway list: those are done and recorded before this section starts. Guard is its
own service — a failure here stops GUARD ONLY and never rolls back the cabinet.

**G.1 — the model, BEFORE installing.** The installer looks for
`${GUARD_MODEL_DIR}/yolov8n_openvino/*.xml` with its `.bin`, `GUARD_MODEL_DIR` defaulting to
`/opt/cloud-iot/backend/models` (`nuc_image/install-guard.sh:49, 206-213`). So the exact path is
**`/opt/cloud-iot/backend/models/yolov8n_openvino/yolov8n.xml`** and **`…/yolov8n.bin`**. The files
measured on 2026-10-11 ARE these: spec §13.6c G.6 records them in that directory, measured
2026-10-15 — `yolov8n.xml` 228 077 B, `yolov8n.bin` 12 708 664 B, dated 2026-10-11 17:56. No
inconsistency: `yolov8n.xml/.bin` are the file names, `yolov8n_openvino/` is their directory.
Check:
```
ls -la /opt/cloud-iot/backend/models/yolov8n_openvino/
```
Expect both files with those sizes. **If they are somewhere else:** `sudo find / -xdev -name 'yolov8n*.xml' 2>/dev/null`
→ RECORD where, and tell me before moving anything (the owner's rule of 2026-10-15: one copy, one
path — G.6 then points `GUARD_MODEL_DIR` at the directory that CONTAINS `yolov8n_openvino/`).
Without the model the install ends with exit 3 = NOT READY.

**On `/marina/guard`, the sentence you should see:**
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


**Stop rule for this section:** install exit **1** (something not installed, or openvino cannot
load and run the model — the line is in `/var/log/cloud-iot/guard-install.log`) or exit **3**
(the model missing) → do NOT enable the service; RECORD the last 20 lines of the install log;
nothing else is rolled back. The install never starts the worker by itself.

## 13. ROLLBACK — from the copies of step 2 only

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
