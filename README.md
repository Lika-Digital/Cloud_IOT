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

### SNMP Trap Receiver
- Listens on UDP :1620 (configurable)
- Decodes BER-encoded SNMP v1/v2c traps (pure Python, no external library)
- Maps OIDs to pedestal sensors; triggers temperature alarm >50°C / moisture >90%
- Configurable per-OID mapping in Settings

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

### First-time setup
```bash
# Create Python venv
python3 -m venv /opt/cloud-iot/backend/.venv
/opt/cloud-iot/backend/.venv/bin/pip install -r /opt/cloud-iot/backend/requirements.txt
/opt/cloud-iot/backend/.venv/bin/pip install psutil openvino

# Export OpenVINO models (once, takes 5-10 min)
cd /opt/cloud-iot/backend
.venv/bin/python3 ~/Cloud_IOT/backend/setup_openvino_models.py

# Enable ML inference (optional — Laplacian fallback works without it)
echo "USE_ML_MODELS=true" | sudo tee -a /opt/cloud-iot/backend/.env
```

### Update from git
```bash
cd ~/Cloud_IOT && git pull origin main

# Copy backend app
sudo cp -r backend/app /opt/cloud-iot/backend/

# Build and deploy frontend
cd frontend && npm run build
sudo cp -r dist/* /opt/cloud-iot/frontend/dist/

# Restart
sudo systemctl restart cloud-iot-backend
```

### Check logs
```bash
sudo journalctl -u cloud-iot-backend -f
sudo journalctl -u cloud-iot-backend -f | grep inference_ms   # ML latency
sudo journalctl -u cloud-iot-backend -f | grep hardware_monitor  # HW alarms
```

---

## MQTT Topic Map

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
| `marina/cabinet/{id}/sockets/{n}/state` | Device → Backend | socket state |
| `marina/cabinet/{id}/door/state` | Device → Backend | `"open"` \| `"closed"` |

---

## WebSocket Events (Backend → Client)

| Event type | When fired |
|---|---|
| `session_created` | New pending or active session |
| `session_updated` | Status change (allow/deny/stop) |
| `power_reading` | Real-time socket power data |
| `water_reading` | Real-time water flow |
| `sensor_reading` | Temperature / moisture update |
| `alarm_triggered` | New active alarm |
| `alarm_acknowledged` | Alarm acknowledged by operator |
| `error_logged` | New entry in error log |
| `pedestal_health_updated` | Camera or OPTA reachability change |
| `berth_occupancy_updated` | Berth analysis result |
| `training_storage_alarm` | Training data disk >80% |
| `hardware_alarm` | CPU/memory/disk/temperature Alarm 2 |
| `marina_door` | Cabinet door open/close |

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

**170 tests** covering:
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

Pre-commit and pre-push hooks run the full suite automatically. Pushes to `main` require `CLOUD_IOT_RELEASE=1` and a merged `develop` branch.
