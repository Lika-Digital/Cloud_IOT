#!/usr/bin/env bash
# ============================================================================
# Cloud IoT NUC v2.0 — OFFLINE Application Installer
# All assets are read from the installer ISO (mounted at /cdrom).
# No internet required.
# ============================================================================
set -euo pipefail

LOG_FILE="/var/log/cloud-iot-setup.log"
APP_DIR="/opt/cloud-iot"
SETUP_DIR="/opt/cloud-iot-setup"

# Assets were copied from the ISO to disk by copy-assets.sh during preseed.
# The ISO is NO LONGER mounted at first boot — use the on-disk copy.
ASSETS_BASE="/opt/cloud-iot-assets"
[ -d "$ASSETS_BASE" ] || { echo "ERROR: Assets not found at ${ASSETS_BASE}. Was copy-assets.sh run?"; exit 1; }

ISO_APP="${ASSETS_BASE}/cloud-iot-app"
ISO_PYTHON="${ASSETS_BASE}/cloud-iot-python"
ISO_DOCKER="${ASSETS_BASE}/cloud-iot-docker"
ISO_POOL="${ASSETS_BASE}/cloud-iot-pool"

exec > >(tee -a "$LOG_FILE") 2>&1

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'
info()  { echo -e "${GREEN}  [✔]${NC} $*"; }
warn()  { echo -e "${YELLOW}  [!]${NC} $*"; }
error() { echo -e "${RED}  [✘]${NC} $*"; exit 1; }
phase() { echo -e "\n${CYAN}${BOLD}  ▶ $*${NC}"; }

# Load configuration
CONFIG_FILE="${1:-}"
[ -z "$CONFIG_FILE" ] || [ ! -f "$CONFIG_FILE" ] && error "Usage: $0 <config-file>"
# shellcheck source=/dev/null
source "$CONFIG_FILE"

TOTAL=8; S=0
step_start() { S=$((S+1)); phase "Step ${S}/${TOTAL}: $*"; }

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Configure local apt pool + install system packages
# ═══════════════════════════════════════════════════════════════════════════════
step_start "Installing system packages (offline)"

# Register local apt pool from ISO
APT_SOURCES_DIR="/etc/apt/sources.list.d"
cat > "${APT_SOURCES_DIR}/cloud-iot-local.list" << EOF
# Cloud IoT offline package pool — sourced from installation ISO
deb [trusted=yes] file://${ISO_POOL} local main
EOF

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq 2>&1 | grep -v 'warning' || true

# Install from local pool (no internet)
apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv python3-dev \
  python3-setuptools python3-wheel \
  nginx \
  sqlite3 \
  openssl libssl-dev libffi-dev \
  build-essential \
  net-tools ifupdown iproute2 \
  ca-certificates gnupg \
  vim htop unzip \
  logrotate \
  watchdog \
  mosquitto-clients \
  2>/dev/null || warn "Some packages may not have installed — continuing"

info "System packages done"

# ── Install Docker CE from local pool ────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  # Install from local ISO pool (packages were downloaded by build_iso.sh)
  DOCKER_DEBS=$(find "${ISO_POOL}/packages/" \
    -name "docker-ce_*.deb" -o -name "docker-ce-cli_*.deb" \
    -o -name "containerd.io_*.deb" -o -name "docker-compose-plugin_*.deb" \
    2>/dev/null | sort)
  if [ -n "$DOCKER_DEBS" ]; then
    # shellcheck disable=SC2086
    dpkg -i $DOCKER_DEBS 2>/dev/null || apt-get install -f -y --no-install-recommends 2>/dev/null || true
  else
    warn "Docker .deb packages not found in ISO pool — trying apt (may need internet)"
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin || true
  fi
fi

if command -v docker &>/dev/null; then
  systemctl enable docker
  systemctl start docker
  usermod -aG docker cloud-iot 2>/dev/null || true
  info "Docker $(docker --version | cut -d' ' -f3 | tr -d ',')"
else
  warn "Docker not installed — MQTT broker will not start"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Load Docker images from ISO (offline, no docker pull)
# ═══════════════════════════════════════════════════════════════════════════════
step_start "Loading Docker images from ISO"

if command -v docker &>/dev/null; then
  if [ -f "${ISO_DOCKER}/manifest.txt" ]; then
    while IFS='|' read -r image_tag filename; do
      tar_path="${ISO_DOCKER}/${filename}"
      if [ -f "$tar_path" ]; then
        info "Loading ${image_tag} from ${filename}..."
        # Handle gzip-compressed tars
        if [[ "$filename" == *.gz ]]; then
          gunzip -c "$tar_path" | docker load
        else
          docker load -i "$tar_path"
        fi
        info "Loaded: ${image_tag}"
      else
        warn "Image tar not found: ${tar_path}"
      fi
    done < "${ISO_DOCKER}/manifest.txt"
  else
    # Fallback: load all .tar and .tar.gz files
    for f in "${ISO_DOCKER}"/*.tar "${ISO_DOCKER}"/*.tar.gz; do
      [ -f "$f" ] || continue
      info "Loading $(basename $f)..."
      [[ "$f" == *.gz ]] && gunzip -c "$f" | docker load || docker load -i "$f"
    done
  fi
  info "Docker images loaded"
else
  warn "Skipping Docker image load (Docker not available)"
fi

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Copy application from ISO
# ═══════════════════════════════════════════════════════════════════════════════
step_start "Copying application from ISO"

[ -d "$ISO_APP" ] || error "App not found in ISO at: ${ISO_APP}"

rm -rf "$APP_DIR" 2>/dev/null || true
cp -r "$ISO_APP" "$APP_DIR"

# Ensure required directories exist
mkdir -p "${APP_DIR}/backend/data" \
         "${APP_DIR}/backend/models" \
         "${APP_DIR}/backend/backgrounds" \
         "/var/log/cloud-iot" \
         "/var/lib/cloud-iot/mosquitto"

info "Application copied to ${APP_DIR}"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Write .env configuration
# ═══════════════════════════════════════════════════════════════════════════════
step_start "Writing .env configuration"

ENV_FILE="${APP_DIR}/backend/.env"
cat > "$ENV_FILE" << EOF
# Cloud IoT NUC v2.0 — Generated $(date --utc +"%Y-%m-%dT%H:%M:%SZ")
# Edit: sudo cloud-iot config

JWT_SECRET=${JWT_SECRET}

DEFAULT_ADMIN_EMAIL=${ADMIN_EMAIL}
DEFAULT_ADMIN_PASSWORD=${ADMIN_PASSWORD}

SMTP_HOST=${SMTP_HOST}
SMTP_PORT=${SMTP_PORT}
SMTP_TLS=${SMTP_TLS}
SMTP_USER=${SMTP_USER}
SMTP_PASSWORD=${SMTP_PASS}
SMTP_FROM=${SMTP_FROM}

MQTT_BROKER_HOST=localhost
MQTT_BROKER_PORT=1883

ALLOWED_ORIGINS=http://${STATIC_IP},http://${STATIC_IP}:80

COMPANY_NAME=${COMPANY_NAME}
COMPANY_ADDRESS=${COMPANY_ADDRESS}
COMPANY_PHONE=${COMPANY_PHONE}
COMPANY_EMAIL=${COMPANY_EMAIL}
COMPANY_PORTAL_NAME=${PORTAL_NAME}
EOF
chmod 640 "$ENV_FILE"
info ".env written"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Install Python packages (offline, from ISO wheels)
# ═══════════════════════════════════════════════════════════════════════════════
step_start "Installing Python environment (offline wheels)"

[ -d "$ISO_PYTHON" ] || error "Python wheels not found in ISO at: ${ISO_PYTHON}"

# Find best Python 3.11+
PYTHON_BIN="python3"
for v in python3.13 python3.12 python3.11; do
  command -v "$v" &>/dev/null && PYTHON_BIN="$v" && break
done
info "Python: $($PYTHON_BIN --version)"

VENV="${APP_DIR}/backend/.venv"
[ -d "$VENV" ] || "$PYTHON_BIN" -m venv "$VENV"

# Upgrade pip/wheel offline first
"${VENV}/bin/pip" install --no-index \
  --find-links="$ISO_PYTHON" \
  pip setuptools wheel 2>/dev/null || \
"${VENV}/bin/pip" install --upgrade pip setuptools wheel -q

# Install all requirements offline
"${VENV}/bin/pip" install --no-index \
  --find-links="$ISO_PYTHON" \
  -r "${APP_DIR}/backend/requirements.txt" \
  || error "Offline pip install failed — wheels may be missing for this Python version"

info "Python packages installed (offline)"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Configure nginx
# ═══════════════════════════════════════════════════════════════════════════════
step_start "Configuring nginx"

cat > /etc/nginx/sites-available/cloud-iot << 'NGINXEOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    root /opt/cloud-iot/frontend/dist;
    index index.html;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    client_max_body_size 10M;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass         http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header   Host            $host;
        proxy_set_header   X-Real-IP       $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }

    location /ws {
        proxy_pass         http://127.0.0.1:8000/ws;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       $host;
        proxy_read_timeout 86400s;
    }
}
NGINXEOF

ln -sf /etc/nginx/sites-available/cloud-iot /etc/nginx/sites-enabled/cloud-iot
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
nginx -t && systemctl enable nginx
info "nginx configured"

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Configure systemd services + watchdog + logrotate
# ═══════════════════════════════════════════════════════════════════════════════
step_start "Configuring services, watchdog, and log rotation"

# ── Backend service ───────────────────────────────────────────────────────────
VENV_BIN="${APP_DIR}/backend/.venv/bin"
cat > /etc/systemd/system/cloud-iot-backend.service << EOF
[Unit]
Description=Cloud IoT FastAPI Backend
Documentation=https://github.com/Lika-Digital/Cloud_IOT
After=network.target docker.service cloud-iot-compose.service

[Service]
Type=simple
User=cloud-iot
Group=cloud-iot
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
ExecStartPre=/bin/bash -c '\
  for db in ${APP_DIR}/backend/pedestal.db ${APP_DIR}/backend/data/users.db; do \
    [ -f "\$db" ] && sqlite3 "\$db" \
      "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-32000;" \
      || true; \
  done'
ExecStart=${VENV_BIN}/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cloud-iot-backend

# Watchdog integration
WatchdogSec=120

[Install]
WantedBy=multi-user.target
EOF

# ── Docker compose service (MQTT broker) ─────────────────────────────────────
cat > /etc/systemd/system/cloud-iot-compose.service << EOF
[Unit]
Description=Cloud IoT Docker Services (MQTT broker)
Documentation=https://github.com/Lika-Digital/Cloud_IOT
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${APP_DIR}
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cloud-iot-compose

[Install]
WantedBy=multi-user.target
EOF

# ── MQTT watchdog service ─────────────────────────────────────────────────────
cp "${SETUP_DIR}/mqtt-watchdog.sh"      /usr/local/bin/cloud-iot-mqtt-watchdog
cp "${SETUP_DIR}/mqtt-watchdog.service" /etc/systemd/system/cloud-iot-mqtt-watchdog.service
chmod +x /usr/local/bin/cloud-iot-mqtt-watchdog

# ── Hardware watchdog configuration ──────────────────────────────────────────
# Try to load Intel NUC hardware watchdog, fall back to softdog
modprobe iTCO_wdt 2>/dev/null || modprobe softdog 2>/dev/null || true

# Ensure watchdog module loads on boot
cat > /etc/modules-load.d/cloud-iot-watchdog.conf << 'WDEOF'
# Cloud IoT NUC — hardware watchdog
# iTCO_wdt for Intel NUC; softdog as fallback
iTCO_wdt
WDEOF

# Configure watchdog daemon (/dev/watchdog)
cat > /etc/watchdog.conf << 'WDCONFEOF'
# Cloud IoT NUC — watchdog daemon configuration
watchdog-device     = /dev/watchdog
watchdog-timeout    = 60
interval            = 10
realtime            = yes
priority            = 1

# Log to journal
log-dir             = /var/log

# Reboot on failure (hard reboot via watchdog kernel driver)
repair-maximum      = 1
WDCONFEOF

systemctl enable watchdog 2>/dev/null || true

# ── Logrotate ─────────────────────────────────────────────────────────────────
cp "${SETUP_DIR}/logrotate-cloud-iot" /etc/logrotate.d/cloud-iot
info "Logrotate configured"

# ── Set file ownership ────────────────────────────────────────────────────────
chown -R cloud-iot:cloud-iot "$APP_DIR" 2>/dev/null || true
chown -R cloud-iot:cloud-iot /var/log/cloud-iot 2>/dev/null || true
chown -R cloud-iot:cloud-iot /var/lib/cloud-iot 2>/dev/null || true

# ── Management CLI ────────────────────────────────────────────────────────────
cat > /usr/local/bin/cloud-iot << 'CLIEOF'
#!/usr/bin/env bash
APP_DIR="/opt/cloud-iot"
case "${1:-}" in
  start)   systemctl start  cloud-iot-compose cloud-iot-backend nginx ;;
  stop)    systemctl stop   cloud-iot-backend cloud-iot-compose ;;
  restart) systemctl restart cloud-iot-compose cloud-iot-backend nginx ;;
  status)
    for svc in cloud-iot-compose cloud-iot-backend nginx cloud-iot-mqtt-watchdog watchdog; do
      echo "── $svc ──"
      systemctl status "$svc" --no-pager -l 2>/dev/null | head -6
      echo ""
    done ;;
  logs)
    case "${2:-backend}" in
      backend) journalctl -u cloud-iot-backend -f --no-pager ;;
      nginx)   tail -f /var/log/nginx/error.log ;;
      mqtt)    docker logs -f pedestal-mqtt-broker ;;
      watchdog) journalctl -u cloud-iot-mqtt-watchdog -f --no-pager ;;
      *) journalctl -u "cloud-iot-${2}" -f --no-pager ;;
    esac ;;
  config)  "${EDITOR:-vim}" "${APP_DIR}/backend/.env" && systemctl restart cloud-iot-backend ;;
  ip)      hostname -I | awk '{print $1}' ;;
  *)
    echo "Usage: sudo cloud-iot {start|stop|restart|status|logs [backend|nginx|mqtt|watchdog]|config|ip}"
    ;;
esac
CLIEOF
chmod +x /usr/local/bin/cloud-iot
info "Management CLI installed"

# ── Enable and start all services ────────────────────────────────────────────
systemctl daemon-reload
systemctl enable cloud-iot-compose cloud-iot-backend cloud-iot-mqtt-watchdog

# Start Docker / MQTT first
systemctl start cloud-iot-compose || warn "Docker compose start deferred"
sleep 4

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 8 — Start backend, enable WAL mode on databases
# ═══════════════════════════════════════════════════════════════════════════════
step_start "Starting backend and enabling SQLite WAL mode"

# Start backend to create databases on first run
systemctl start cloud-iot-backend || warn "Backend start issue — check logs"
sleep 10   # wait for SQLAlchemy to create DBs

# Enable WAL mode now that DBs exist
for db in "${APP_DIR}/backend/pedestal.db" \
          "${APP_DIR}/backend/data/users.db"; do
  if [ -f "$db" ]; then
    sqlite3 "$db" \
      "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-32000; PRAGMA wal_autocheckpoint=1000;"
    info "WAL mode enabled: $(basename $db)"
  else
    warn "DB not yet created: $db (WAL will be set on next restart via ExecStartPre)"
  fi
done

# Start remaining services
systemctl start nginx
systemctl start cloud-iot-mqtt-watchdog || true

info "All services started"
echo ""
info "Backend:   $(systemctl is-active cloud-iot-backend  2>/dev/null || echo 'starting')"
info "Compose:   $(systemctl is-active cloud-iot-compose  2>/dev/null || echo 'starting')"
info "nginx:     $(systemctl is-active nginx               2>/dev/null || echo 'starting')"
info "Watchdog:  $(systemctl is-active cloud-iot-mqtt-watchdog 2>/dev/null || echo 'starting')"

# ── Clean up offline assets (free several GB of disk space) ──────────────────
info "Removing offline asset cache (~${ASSETS_BASE})..."
rm -rf "$ASSETS_BASE" 2>/dev/null || warn "Could not remove ${ASSETS_BASE} — clean up manually"
info "Disk cleanup done"
echo ""
info "============================================================"
info "  Cloud IoT NUC v2.0 installation complete."
info "  Web UI: http://$(hostname -I | awk '{print $1}')"
info "  Manage: sudo cloud-iot status"
info "============================================================"
