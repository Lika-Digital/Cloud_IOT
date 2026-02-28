# Cloud IoT — DEB Package

Single-command installation of the entire Cloud IoT marina pedestal system on Ubuntu 22.04+.

## What gets installed

| Component | How |
|---|---|
| FastAPI backend | systemd service (`cloud-iot-backend`) |
| React frontend | nginx (pre-built during install) |
| MQTT broker (Mosquitto) | Docker container |
| ML worker (RT-DETR + DINOv2) | Docker container |
| nginx | Reverse proxy on port 80 |
| Docker CE | Auto-installed if missing |
| Node.js 20 | Auto-installed if missing |
| Python 3.11+ | Auto-installed if missing |

---

## Build the .deb (from Linux / WSL)

```bash
# Prerequisites
sudo apt-get install -y dpkg-dev rsync

# Build
cd DEB_Pack
chmod +x build_deb.sh
./build_deb.sh
# Output: DEB_Pack/cloud-iot_1.0.0_amd64.deb
```

> **Windows users:** Run from WSL (Windows Subsystem for Linux), not PowerShell.

---

## Deploy to Ubuntu server

```bash
# Copy package to server
scp cloud-iot_1.0.0_amd64.deb user@server:~/

# Install (requires sudo)
ssh user@server
sudo dpkg -i cloud-iot_1.0.0_amd64.deb
```

Installation takes 3–5 minutes (downloads dependencies, builds frontend, starts services).

---

## After installation

```bash
# Open the web interface
http://<server-ip>

# Default login
Email:    admin@marina.local
Password: ChangeMe123!

# Download ML models for berth detection (~155 MB)
sudo cloud-iot download-models

# Check service status
sudo cloud-iot status

# Edit configuration
sudo cloud-iot config
```

---

## Management commands

```bash
sudo cloud-iot start              # Start all services
sudo cloud-iot stop               # Stop all services
sudo cloud-iot restart            # Restart all services
sudo cloud-iot status             # Show status of all components
sudo cloud-iot logs backend       # Tail backend logs
sudo cloud-iot logs mqtt          # Tail MQTT broker logs
sudo cloud-iot logs ml            # Tail ML worker logs
sudo cloud-iot logs nginx         # Tail nginx logs
sudo cloud-iot download-models    # Download RT-DETR + DINOv2 ONNX models
sudo cloud-iot update             # Pull latest code, rebuild, restart
sudo cloud-iot config             # Edit /opt/cloud-iot/backend/.env
```

---

## Uninstall

```bash
# Remove package (keeps data)
sudo dpkg -r cloud-iot

# Full purge including data
sudo dpkg --purge cloud-iot
```

---

## Directory layout (after install)

```
/opt/cloud-iot/
├── backend/
│   ├── app/          — FastAPI application
│   ├── .venv/        — Python virtual environment
│   ├── .env          — Configuration (edit with: cloud-iot config)
│   ├── data/         — SQLite user database (users.db)
│   ├── models/       — ONNX model files (rtdetr.onnx, dinov2.onnx)
│   └── backgrounds/  — Berth background reference images
├── frontend/
│   ├── dist/         — Compiled React app (served by nginx)
│   └── src/          — Source (for rebuilding)
├── ml_worker/        — ML worker Docker source
├── mosquitto/        — MQTT broker config
└── docker-compose.yml
```

Config files:
```
/etc/nginx/sites-available/cloud-iot   — nginx site config
/etc/systemd/system/cloud-iot-backend.service
/etc/systemd/system/cloud-iot-compose.service
```
