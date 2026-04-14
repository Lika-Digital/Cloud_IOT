# Smart Pedestal IoT Management — Cloud_IOT

Full-stack IoT monitoring, session management, and customer billing platform for a smart marina pedestal with 4 electricity sockets and 1 water meter.

Deployed on an **Intel Atom x7425E NUC** running Ubuntu 24.04. Managed remotely via Cloudflare Tunnel / Tailscale.

---

## Architecture

```
Arduino OPTA (MQTT client)       IP Camera (RTSP/ONVIF)    SNMP Sensor (UDP :1620)
        │ MQTT                            │                         │
        ▼                                 │                         │
Mosquitto Broker (:1883)                  │                         │
        │                                 │                         │
        └──────────── FastAPI Backend (:8000) ────────────────────────
                              │
                    ┌─────────┴──────────┐
                    │   SQLite DBs        │
                    │  pedestal.db        │  ← IoT data, alarms, error logs
                    │  data/users.db      │  ← auth, customers, billing
                    └─────────────────────┘
                              │ WebSocket + REST
                              ▼
                    React Dashboard (:5173 / Nginx)
                              │
                    Expo Mobile App (iOS/Android)
```

---

## Feature Summary

### Dashboard
- Live socket status (connected / disconnected) per pedestal
- Real-time power readings (watts, kWh) via WebSocket
- Water flow meter (LPM, total litres)
- Temperature and moisture sensor alarms (SNMP trap receiver)
- Allow / Deny / Stop session controls
- Marina cabinet door state indicator
- Pending session approval cards with customer name
- **Control Center tab** (per pedestal, admin only) — see below

### Session Management
- State machine: `pending → active → completed / denied`
- Pilot mode: operator must approve before power is enabled
- Customer-initiated sessions from mobile app
- Socket plug-in enforcement — socket must be physically connected before session can start
- Auto-timeout for stale pending sessions (configurable, default 15s)
- Session history with energy (kWh) and water (litres) totals

### Authentication
- Admin and Monitor roles (Monitor = read-only, no controls)
- Two-factor login: POST /login → OTP email → POST /verify-otp → JWT (8h)
- Customer registration / login (JWT role=customer, 30-day expiry)
- PBKDF2-HMAC-SHA256 password hashing (stdlib, no bcrypt dependency)
- Brute-force protection: 5 failures in 5 min → security alarm

### Customer App (Mobile — Expo 54 / expo-router 6)
- Customer registration, login, profile (name, ship name)
- Start / stop electricity or water session from phone
- Live session status via WebSocket
- Invoice list with mock payment
- Contract signing with signature pad
- Service orders
- Push notifications (Expo) for session allow / deny
- `mobile/.env` — set `EXPO_PUBLIC_API_URL` and `EXPO_PUBLIC_WS_URL` to LAN IP

### Billing & Invoices
- Configurable kWh and litre pricing
- Auto-generated invoices on session completion
- Spending reports (per-customer, per-session breakdown)
- Admin billing dashboard with accordion session detail

### Chat
- Customer ↔ operator messaging
- Unread message badge in admin navigation
- Real-time delivery via WebSocket

### Contracts & Service Orders
- Admin creates contract templates
- Customers receive pending contract on registration
- In-app signature capture (react-native-signature-canvas)
- PDF generation (ReportLab) for contracts and invoices
- Service order workflow (customer request → admin fulfil)

### Berth Occupancy (Computer Vision)
- Per-berth analysis: canvas zone selector, reference frame, occupancy detection
- **Laplacian + histogram fallback** (default, no ML required, works on 32-bit dev)
- **OpenVINO ML inference** (opt-in via `USE_ML_MODELS=true` in `.env`):
  - YOLOv8n — boat detection (COCO class 8), INT8/FP32 OpenVINO IR
  - MobileNetV2 Re-ID — 128-dim L2-normalised ship identity embeddings
  - Logs `inference_ms` on every call to measure latency on target hardware
- On-demand RTSP snapshot via ffmpeg (no continuous stream)
- Operator training data loop: save crop → confirm / reject
- Training storage monitor: WebSocket alarm at 80% capacity
- Berth count auto-synced to pedestal count
- **Sector management** (v3.1):
  - **+ Add Sector** button in Berth Occupancy table — create new berths directly without going to Settings
  - Each sector has a user-assigned **berth number** (e.g. #1, #2) shown as a badge in the table
  - Creating a sector immediately opens the zone config + sample image upload in one flow
  - Berth number editable inside ⚙ Sectors modal alongside detection zone config
  - Sample ship image upload per sector for Re-ID Match procedure

### Pedestal Settings — Camera Configuration (v3.1)
- **Stream URL auto-build**: entering FQDN + username + password and clicking *"Build URL from FQDN + credentials"* constructs the full `rtsp://user:pass@host/path` URL
- **Credential injection on save**: when username / password are saved, the backend automatically embeds them into the stored `camera_stream_url` (URL-encoded) so the camera worker always has a complete, authenticated URL — no manual URL editing needed
- Credentials are always masked (`***`) in API responses

### SNMP Trap Receiver
- Listens on UDP :1620 (configurable)
- Decodes BER-encoded SNMP v1/v2c traps (pure Python, no external library)
- Maps OIDs to pedestal sensors; triggers temperature alarm >50°C / moisture >90%
- Configurable per-OID mapping in Settings

### Pedestal Control Center (v3.2)

Accessible via the **Control Center** tab when a pedestal is open in the Dashboard. Requires admin role.

**Live monitoring (real-time from MQTT via WebSocket):**
- Cabinet Status: cabinet ID, heartbeat sequence, uptime, OPTA connected indicator
- Door state: open / closed with visual alarm
- Sockets Q1–Q4: state badge (`idle / active / fault / blocked`), `hw_status`, session context
- Water Valves V1–V2: state badge, `hw_status`, total litres, session litres
- Event Log: rolling last 30 entries from `opta/events` (expandable)
- Command ACK Log: rolling last 30 entries from `opta/acks` with status (expandable)

**Commands (admin only — publish directly to OPTA via MQTT):**
- Sockets Q1–Q4: `Activate` / `Stop` / `Maintenance` → `opta/cmd/socket/Q{n}` with `{"action":"activate|stop|maintenance"}`
- Water Valves V1–V2: `Activate` / `Stop` / `Maintenance` → `opta/cmd/water/V{n}`
- LED Control: color picker (`green / red / blue / yellow / off`) + state (`on / off / blink`) → `opta/cmd/led`
- Reset Device: double-click confirmation → `opta/cmd/reset` (interrupts all active sessions)

**New backend endpoints:**
| Method | Path | Description |
|---|---|---|
| POST | `/api/controls/pedestal/{id}/socket/{Q1..Q4}/cmd` | Direct socket command |
| POST | `/api/controls/pedestal/{id}/water/{V1..V2}/cmd` | Direct water valve command |
| POST | `/api/controls/pedestal/{id}/led` | LED color/state command |
| POST | `/api/controls/pedestal/{id}/reset` | Pedestal reset command |

**New WebSocket events (backend → frontend):**
| Event | When fired |
|---|---|
| `opta_socket_status` | `opta/sockets/Q*/status` received — full state, hw_status, session |
| `opta_water_status` | `opta/water/V*/status` received — state, hw_status, total_l, session_l |
| `opta_status` | Heartbeat — cabinet ID, seq, uptime_ms, door |
| `marina_ack` | Command ACK from OPTA — now includes `pedestal_id` |

### External API Gateway
- 14 documented endpoints + 11 webhook events (static catalog)
- API key with 10-year JWT (role=external\_api)
- Webhook delivery on any WebSocket broadcast event
- 30s config cache with invalidation on change
- Admin UI: catalog browser, config, verify, activate, copy key

### System Health (Admin)
- Error log dashboard: filter by category (system/hw), level, time window
- 7-day log retention with hourly auto-purge
- Active alarm summary breakdown
- Security event counts (brute-force, unauthorised access)
- Real-time error badge in navigation

### Hardware Monitoring (NUC, admin only)
- `GET /api/system/hardware-stats` — all hardware parameters in one call (<500ms)
- Refreshes every 10s in dashboard; no background collection threads
- Gauges with 60% (warning) and 80% (critical) threshold markers
- **Alarm 1 (warning)**: yellow banner in System Health + pulsing dot in nav
- **Alarm 2 (critical)**: red banner + WebSocket `hardware_alarm` push to all clients
- **Auto-downgrade on Alarm 2**:
  - CPU ≥80%: `nice(10)` on highest cloud_iot process (protected list enforced)
  - Memory ≥80%: `gc.collect()`
  - Temperature ≥72°C: RTSP frame grab suspended 60s (thermal protection)
  - Disk ≥80%: display-only, no automatic action
- Protected processes never adjusted: `uvicorn nginx cloudflared tailscaled mosquitto sshd`
- Automatic actions log (newest-first, max 100 entries) visible in System Health
- Network interfaces panel: link status, IP, speed, bytes sent/recv
- Thresholds configurable in `.env` (`hw_cpu_warning`, `hw_cpu_critical`, etc.)
- psutil required on NUC: `/opt/cloud-iot/backend/.venv/bin/pip install psutil`

---

## Monitored Parameters

| Parameter | Warning | Critical | Auto-action |
|---|---|---|---|
| CPU usage | 60% | 80% | nice() on top cloud_iot process |
| Memory usage | 60% | 80% | gc.collect() |
| Disk usage | 60% | 80% | display-only |
| CPU temperature | 54°C (60% of 90) | 72°C (80% of 90) | Suspend RTSP grab 60s |

---

## Quick Start (Development)

### Prerequisites
- Docker & Docker Compose
- Python 3.12+ (64-bit for OpenVINO; 32-bit dev works with Laplacian fallback)
- Node.js 18+

### 1. Start MQTT broker
```bash
docker compose up -d
```

### 2. Start backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env         # set JWT_SECRET and DEFAULT_ADMIN_PASSWORD
uvicorn app.main:app --reload
```

### 3. Start frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

Default admin: set `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` in `backend/.env`.
OTP prints to the backend console (SMTP not configured by default).

---

## NUC Deployment

The production system runs at `/opt/cloud-iot/` on Ubuntu 24.04.

> **IMPORTANT — Two directories exist on the NUC. Never confuse them:**
>
> | Path | Purpose | Managed by |
> |---|---|---|
> | `/opt/cloud-iot/` | **Production app** — what is actually running | systemd + Docker |
> | `~/Cloud_IOT/` | Git repo — source of truth for updates | git |
>
> The git repo is NOT the running app. Do NOT run uvicorn from `~/Cloud_IOT/`.
> Do NOT install packages into `~/Cloud_IOT/backend/.venv-nuc` for production purposes.

### NUC Services

| Service | Type | What it runs | Check status |
|---|---|---|---|
| `cloud-iot-backend` | systemd | Uvicorn (FastAPI) on :8000 | `systemctl status cloud-iot-backend` |
| `cloud-iot-compose` | systemd (starts Docker) | Docker Compose for MQTT broker | `systemctl status cloud-iot-compose` |
| `pedestal-mqtt-broker` | Docker container | Eclipse Mosquitto 2.0 on :1883 | `docker ps \| grep mosquitto` |
| `nginx` | systemd | Reverse proxy + static frontend | `systemctl status nginx` |
| `cloudflared` | systemd | Cloudflare Tunnel | `systemctl status cloudflared` |
| `tailscaled` | systemd | Tailscale VPN | `systemctl status tailscaled` |

> **Mosquitto runs in Docker, NOT as a systemd service.** The `cloud-iot-compose` systemd unit
> starts Docker Compose which in turn starts the `pedestal-mqtt-broker` container.
> `systemctl status mosquitto` will show "not found" — this is expected.
> To check MQTT broker status, use `docker ps | grep mosquitto`.

---

### ⚠ WARNING — NUC Troubleshooting Rules (Do NOT Repeat These Mistakes)

**When the site is down:**
1. Check if the NUC is physically alive first: `tailscale status` from Windows
2. If NUC shows offline in Tailscale → hardware issue, physical access required
3. If NUC shows online → check services: `sudo cloud-iot status`
4. **Never run uvicorn manually** — `cloud-iot-backend.service` uses `Restart=always`. Running uvicorn manually will conflict on port 8000 and cause confusion.
5. **Never install packages into `~/Cloud_IOT/backend/.venv-nuc`** — production venv is `/opt/cloud-iot/backend/.venv`
6. **Never create a new systemd service** — `cloud-iot-backend`, `cloud-iot-compose`, `nginx`, `cloudflared`, `tailscaled` are all already configured and enabled on boot

**All services auto-start on reboot.** If the NUC reboots cleanly, wait 30–60s and the site will come back on its own. Do not intervene unless a service has `failed` status.

**Quick status check:**
```bash
sudo cloud-iot status        # shows all service states
sudo cloud-iot logs backend  # live backend logs
```

---

### First-time setup (ISO install)

The NUC is provisioned from a pre-built ISO (`nuc_image/cloud-iot-nuc-v2.0.iso`).
The install script handles everything: Python venv, systemd services, nginx, Docker/MQTT.
Do NOT run setup steps manually on an already-provisioned NUC.

```bash
# Optional: Enable ML inference (Laplacian fallback works without it)
echo "USE_ML_MODELS=true" | sudo tee -a /opt/cloud-iot/backend/.env

# Export OpenVINO models (once, takes 5-10 min)
cd /opt/cloud-iot/backend
.venv/bin/python3 ~/Cloud_IOT/backend/setup_openvino_models.py
```

---

### Updating the NUC — Correct Procedure

**The ONLY correct way to update production code on the NUC:**

```bash
# SSH into the NUC (via Tailscale or Cloudflare)
ssh cloud_iot@marina-iot

# Run the upgrade script
sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh
```

**What the script does (step by step):**
1. Shows current version (`git rev-parse --short HEAD` in `~/Cloud_IOT`)
2. `git fetch origin main` — checks GitHub for new commits
3. If already up to date → exits
4. Shows list of commits to apply + which areas changed (backend / frontend)
5. Asks for confirmation (`Apply upgrade? [y/N]`)
6. `git pull origin main` — pulls latest code into `~/Cloud_IOT`
7. **Venv health check** — if `/opt/cloud-iot/backend/.venv/bin/pip` is missing, recreates the entire venv and installs all packages
8. If frontend changed → `npm install` + `npm run build` → copies `dist/` to `/opt/cloud-iot/frontend/dist/` → reloads nginx
9. If `requirements.txt` changed → `pip install -r requirements.txt`
10. Copies `~/Cloud_IOT/backend/app/` → `/opt/cloud-iot/backend/app/`
11. `systemctl restart cloud-iot-backend` → waits up to 15s for it to come up
12. Shows summary: previous version, new version, service status
13. Logs everything to `/var/log/cloud-iot/upgrade.log`

**What it preserves (never touched):**
- `/opt/cloud-iot/backend/.env` — all configuration
- `/opt/cloud-iot/backend/pedestal.db` — IoT data
- `/opt/cloud-iot/backend/data/users.db` — auth/customers
- Docker MQTT broker — not restarted unless Docker config changes

**Never do this instead:**
```bash
# WRONG — do not git pull manually before running upgrade.sh
cd ~/Cloud_IOT && git pull origin main
```
If you `git pull` manually first, `upgrade.sh` will see "already up to date" and skip copying files to `/opt/cloud-iot/`. The production code will remain outdated.

**If you accidentally git-pulled already**, run the copy steps manually:
```bash
sudo cp -r ~/Cloud_IOT/backend/app /opt/cloud-iot/backend/
sudo chown -R cloud_iot:cloud_iot /opt/cloud-iot/backend/app
sudo /opt/cloud-iot/backend/.venv/bin/pip install -r ~/Cloud_IOT/backend/requirements.txt -q
sudo systemctl restart cloud-iot-backend
```

---

### Remote Access to NUC

The NUC has no static IP (behind 5G router). Access is only via:

| Method | When to use |
|---|---|
| Tailscale SSH: `ssh cloud_iot@marina-iot` | Primary remote access |
| Cloudflare Tunnel: `marina.lika.solutions` | Web UI access |
| Physical keyboard/monitor | Last resort — NUC is unreachable remotely |

If both Tailscale and Cloudflare are down → **the NUC is physically offline** (power loss or hardware crash). Do not attempt to reconfigure services remotely. Get physical access.

> **Known fix (applied 2026-04-10):** Tailscale was configured to start before DHCP completed (`network-pre.target`). Fixed via systemd override to `network-online.target`. Also fixed `systemd-networkd-wait-online` with `--any` flag so it doesn't hang waiting for offline interfaces (`enp1s0`, `wlp4s0`). Both fixes are now in `install-cloud-iot.sh` for future ISO builds.

Check NUC connectivity from Windows:
```powershell
tailscale status   # shows if marina-iot is online/offline and last seen time
```

---

### Check logs
```bash
sudo cloud-iot logs backend   # live backend logs
sudo cloud-iot logs nginx     # nginx errors
sudo cloud-iot logs mqtt      # MQTT broker
sudo journalctl -u cloud-iot-backend -n 50 --no-pager  # last 50 lines
```

---

## MQTT Topic Map

### Legacy schema (`pedestal/{id}/...`)
| Topic | Direction | Payload |
|---|---|---|
| `pedestal/{id}/socket/{1-4}/status` | Device → Backend | `"connected"` \| `"disconnected"` |
| `pedestal/{id}/socket/{1-4}/power` | Device → Backend | `{"watts": float, "kwh_total": float}` |
| `pedestal/{id}/socket/{1-4}/control` | Backend → Device | `"allow"` \| `"deny"` \| `"stop"` |
| `pedestal/{id}/water/flow` | Device → Backend | `{"lpm": float, "total_liters": float}` |
| `pedestal/{id}/heartbeat` | Device → Backend | `{"timestamp": str, "online": bool}` |
| `pedestal/{id}/register` | Device → Backend | `{"client_id": str}` |
| `pedestal/{id}/sensors/temperature` | Device → Backend | `{"value": float}` |
| `pedestal/{id}/sensors/moisture` | Device → Backend | `{"value": float}` |

### Marina cabinet schema (`marina/cabinet/{id}/...`)
| Topic | Direction | Payload |
|---|---|---|
| `marina/cabinet/{id}/status` | Device → Backend | `{"cabinetId":"...","seq":N,"uptime_ms":N,"door":"closed"}` |
| `marina/cabinet/{id}/sockets/{n}/state` | Device → Backend | `{"id":"PWR-1","state":"idle\|active","hw_status":"on\|off","ts":N}` |
| `marina/cabinet/{id}/water/{n}/state` | Device → Backend | `{"id":"WTR-1","state":"idle","total_l":N,"session_l":N,"ts":N}` |
| `marina/cabinet/{id}/door/state` | Device → Backend | `{"door":"open\|closed","ts":"..."}` |
| `marina/cabinet/{id}/events` | Device → Backend | `{"eventId":"...","eventType":"TelemetryUpdate\|AlarmRaised\|SessionEnded"}` |
| `marina/cabinet/{id}/acks` | Device → Backend | `{"cmd_topic":"...","status":"ok\|err","ts":N}` |
| `marina/cabinet/{id}/cmd/socket/{n}` | Backend → Device | `{"cmd":"enable\|disable"}` |
| `marina/cabinet/{id}/outlet/PWR-{n}/cmd/stop` | Backend → Device | `{"cmd":"stop"}` |

### OPTA schema (`opta/...`) — cabinetId resolution
> **Important:** Only `opta/status` and `opta/door/status` carry `cabinetId` at the top level.
> Socket, water, power, event, and ack payloads do **NOT** include `cabinetId`.
> The backend caches `cabinetId` from the periodic `opta/status` heartbeat (every ~60s)
> and uses it as a fallback. Events carry `cabinetId` nested under `device.cabinetId`.
> Backend → Device commands always include `cabinetId` in the payload.

| Topic | Direction | Payload |
|---|---|---|
| `opta/status` | Device → Backend | `{"cabinetId":"...","seq":N,"uptime_ms":N,"door":"closed"}` |
| `opta/sockets/Q{1-4}/status` | Device → Backend | `{"id":"Q1","state":"idle\|active\|fault\|blocked","hw_status":"on\|off","session":{...},"ts":N}` *(no cabinetId)* |
| `opta/sockets/Q{1-4}/power` | Device → Backend | `{"id":"Q1","watts":N,"kwh_total":N,"ts":N}` *(no cabinetId)* |
| `opta/water/V{1-2}/status` | Device → Backend | `{"id":"V1","state":"idle\|active","hw_status":"on\|off","total_l":N,"session_l":N,"ts":N}` *(no cabinetId)* |
| `opta/door/status` | Device → Backend | `{"cabinetId":"...","door":"open\|closed","ts":"..."}` |
| `opta/events` | Device → Backend | `{"eventId":"...","eventType":"...","device":{"cabinetId":"...","outletId":"Q2",...},...}` *(cabinetId nested in device)* |
| `opta/acks` | Device → Backend | `{"cmd_topic":"...","status":"ok\|err","ts":N}` *(no cabinetId)* |
| `opta/cmd/socket/Q{1-4}` | Backend → Device | `{"msgId":"...","cabinetId":"...","action":"activate\|stop\|maintenance"}` |
| `opta/cmd/water/V{1-2}` | Backend → Device | `{"msgId":"...","cabinetId":"...","action":"activate\|stop\|maintenance"}` |
| `opta/cmd/led` | Backend → Device | `{"cabinetId":"...","color":"green\|red\|blue\|yellow\|off","state":"on\|off\|blink"}` |
| `opta/cmd/reset` | Backend → Device | `{"cabinetId":"...","cmd":"reset"}` |

---

## WebSocket Events (Backend → Client)

| Event type | When fired |
|---|---|
| `session_created` | New pending or active session |
| `session_updated` | Status change (allow/deny/stop) |
| `session_completed` | Session ended (stop or device disconnect) |
| `power_reading` | Real-time socket power data |
| `water_reading` | Real-time water flow |
| `temperature_reading` | Temperature sensor update |
| `moisture_reading` | Moisture sensor update |
| `heartbeat` | Pedestal online/offline |
| `socket_pending` | Device plugged in — operator approval needed |
| `socket_rejected` | Operator rejected socket connection |
| `error_logged` | New entry in error log |
| `pedestal_health_updated` | Camera or OPTA reachability change |
| `pedestal_reset_sent` | Reset command dispatched |
| `berth_occupancy_updated` | Berth analysis result |
| `hardware_alarm` | CPU/memory/disk/temperature Alarm 2 |
| `marina_door` | Cabinet door open/close |
| `marina_event` | Generic event from cabinet firmware |
| `marina_ack` | Command ACK from cabinet (includes `pedestal_id`) |
| `direct_cmd_sent` | Direct socket/water/LED/reset command dispatched |
| `opta_socket_status` | `opta/sockets/Q*/status` — state, hw_status, session |
| `opta_water_status` | `opta/water/V*/status` — state, hw_status, total_l, session_l |
| `opta_status` | `opta/status` — cabinet ID, seq, uptime_ms, door |

---

## Environment Variables (backend/.env)

| Variable | Default | Description |
|---|---|---|
| `JWT_SECRET` | (random) | **Set in production.** Sessions invalidated on restart if unset. |
| `DEFAULT_ADMIN_EMAIL` | `admin@iot-dashboard.local` | Seeded on first run |
| `DEFAULT_ADMIN_PASSWORD` | — | Required for first-run seed |
| `MQTT_BROKER_HOST` | `localhost` | Mosquitto host |
| `MQTT_BROKER_PORT` | `1883` | Mosquitto port |
| `USE_ML_MODELS` | `false` | Enable OpenVINO inference for Berth Occupancy |
| `HW_CPU_WARNING` | `60.0` | CPU % → Alarm 1 |
| `HW_CPU_CRITICAL` | `80.0` | CPU % → Alarm 2 + auto nice() |
| `HW_MEM_WARNING` | `60.0` | Memory % → Alarm 1 |
| `HW_MEM_CRITICAL` | `80.0` | Memory % → Alarm 2 + gc.collect() |
| `HW_DISK_WARNING` | `60.0` | Disk % → Alarm 1 |
| `HW_DISK_CRITICAL` | `80.0` | Disk % → Alarm 2 (display only) |
| `HW_TEMP_MAX` | `90.0` | Maximum safe CPU temperature (°C) |
| `HW_TEMP_WARNING_PCT` | `60.0` | 60% of max → Alarm 1 (54°C) |
| `HW_TEMP_CRITICAL_PCT` | `80.0` | 80% of max → Alarm 2 (72°C) + RTSP suspend |
| `SMTP_HOST` | — | Leave empty to print OTP to console |
| `PENDING_TIMEOUT_SECONDS` | `15` | Auto-deny stale pending sessions |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn, SQLAlchemy 2.0 |
| Database | SQLite (pedestal.db + data/users.db) |
| MQTT | paho-mqtt 2.x, Eclipse Mosquitto 2.0 (Docker) |
| Auth | PyJWT, PBKDF2-HMAC-SHA256, smtplib OTP |
| Computer Vision | OpenVINO 2026, YOLOv8n, MobileNetV2, Pillow, psutil |
| PDF | ReportLab |
| Frontend | React 18, TypeScript, Vite, Zustand, Recharts, Tailwind CSS |
| Mobile | Expo 54, expo-router 6, React Native |
| Push Notifications | Expo Push API (httpx fire-and-forget) |
| Hardware | Intel Atom x7425E NUC, Ubuntu 24.04 |

---

## Test Suite

```bash
cd Cloud_IOT
backend/.venv/Scripts/python -m pytest tests/backend/ -q
```

**212 tests** covering:
- Session lifecycle and MQTT integration
- Operator approval flow and timeouts
- Customer auth and billing
- Chat, contracts, service orders
- Berth occupancy / computer vision
- Hardware stats endpoint and all alarm thresholds
- Downgrade actions (CPU nice, memory GC, temperature suspension, disk display-only)
- Protected process list enforcement
- External API gateway
- Security (brute-force, SQL injection patterns)
- SNMP BER decoder
- **Direct device controls** (socket Q1–Q4, water V1–V2, LED, reset, auth enforcement)
- **MQTT Control Center broadcasts** (`opta_socket_status`, `opta_water_status`, `opta_status`, `marina_ack` pedestal_id)

Pre-commit and pre-push hooks run the full suite automatically. Pushes to `main` require `CLOUD_IOT_RELEASE=1` and a merged `develop` branch.
