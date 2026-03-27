#!/usr/bin/env bash
# ============================================================================
# Cloud IoT NUC v2.0 — Ubuntu Server 24.04 LTS Installer
# Run from the cloned repo: sudo bash nuc_image/ubuntu-install.sh
# Internet (ethernet) required during install.
# ============================================================================
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="/opt/cloud-iot"
LOG_FILE="/var/log/cloud-iot-install.log"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; WHITE='\033[1;37m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${GREEN}[✔]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✘]${NC} $*"; exit 1; }
phase() { echo -e "\n${CYAN}${BOLD}══ $* ══${NC}"; }

[[ $EUID -ne 0 ]] && error "Run with sudo: sudo bash nuc_image/ubuntu-install.sh"

exec > >(tee -a "$LOG_FILE") 2>&1

# ── Welcome ───────────────────────────────────────────────────────────────────
clear
echo -e "${BLUE}${BOLD}"
cat << 'BANNER'
  ╔══════════════════════════════════════════════════════════════════╗
  ║        Cloud IoT — Marina Pedestal Management System            ║
  ║               Ubuntu Server 24.04 LTS Installer                 ║
  ╚══════════════════════════════════════════════════════════════════╝
BANNER
echo -e "${NC}"
echo -e "  Repo: ${WHITE}${REPO_DIR}${NC}"
echo -e "  Log:  ${WHITE}${LOG_FILE}${NC}"
echo ""
echo "  Internet connection (ethernet) required. Takes ~10 minutes."
echo "  Press ENTER to begin..."
read -r

# ── Helper functions ──────────────────────────────────────────────────────────
ask() {
  local prompt="$1" default="${2:-}" result
  if [ -n "$default" ]; then
    read -r -p "$(echo -e "  ${CYAN}${prompt}${NC} [${WHITE}${default}${NC}]: ")" result
    echo "${result:-$default}"
  else
    while true; do
      read -r -p "$(echo -e "  ${CYAN}${prompt}${NC}: ")" result
      [ -n "$result" ] && break
      echo -e "  ${RED}Required.${NC}"
    done
    echo "$result"
  fi
}

ask_password() {
  local prompt="$1" pass1 pass2
  while true; do
    read -r -s -p "$(echo -e "  ${CYAN}${prompt} (min 8 chars)${NC}: ")" pass1; echo
    [ "${#pass1}" -ge 8 ] || { echo -e "  ${RED}Too short.${NC}"; continue; }
    read -r -s -p "$(echo -e "  ${CYAN}Confirm${NC}: ")" pass2; echo
    [ "$pass1" = "$pass2" ] && break
    echo -e "  ${RED}Mismatch. Try again.${NC}"
  done
  echo "$pass1"
}

ask_yn() {
  local prompt="$1" default="${2:-n}" answer
  read -r -p "$(echo -e "  ${CYAN}${prompt}${NC} [y/N]: ")" answer
  [[ "${answer:-$default}" =~ ^[Yy] ]]
}

validate_ip() {
  [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  IFS='.' read -ra o <<< "$1"
  for x in "${o[@]}"; do [[ "$x" -le 255 ]] || return 1; done
}

ask_ip() {
  local prompt="$1" default="${2:-}" ip
  while true; do
    ip=$(ask "$prompt" "$default")
    validate_ip "$ip" && { echo "$ip"; return; }
    echo -e "  ${RED}Invalid IP address.${NC}"
  done
}

# ── Detect current network ────────────────────────────────────────────────────
CURRENT_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "192.168.1.100")
CURRENT_GW=$(ip route | awk '/default/{print $3}' | head -1 2>/dev/null || echo "192.168.1.1")
IFACE=$(ip route | awk '/default/{print $5}' | head -1 2>/dev/null || echo "eth0")

# ═══════════════════════════════════════════════════════════════════════════════
# WIZARD — collect all settings before installing
# ═══════════════════════════════════════════════════════════════════════════════

# STEP 1: Network
clear
echo -e "${BLUE}${BOLD}"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   STEP 1 / 5  —  NETWORK"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${NC}"
echo -e "  Current IP : ${WHITE}${CURRENT_IP}${NC}  (via ${IFACE})"
echo -e "  Current GW : ${WHITE}${CURRENT_GW}${NC}"
echo ""

HOSTNAME=$(ask "Hostname" "marina-iot")

USE_STATIC=false
STATIC_IP="$CURRENT_IP"
GATEWAY="$CURRENT_GW"
DNS="8.8.8.8 8.8.4.4"

echo ""
echo -e "  ${YELLOW}Do you want a static IP (recommended for production)?${NC}"
echo -e "  If you say No, the NUC keeps DHCP — your router assigns the IP."
echo -e "  ${YELLOW}Tip: you can always add a static IP later.${NC}"
echo ""
if ask_yn "Configure static IP?" "n"; then
  USE_STATIC=true
  echo ""
  echo -e "  ${YELLOW}Choose an IP outside your router's DHCP range.${NC}"
  STATIC_IP=$(ask_ip "Static IP for NUC" "$CURRENT_IP")
  GATEWAY=$(ask_ip   "Default gateway"   "$CURRENT_GW")
  DNS=$(ask          "DNS servers (space-sep)" "8.8.8.8 8.8.4.4")
fi

# STEP 2: Admin account
clear
echo -e "${BLUE}${BOLD}"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   STEP 2 / 5  —  ADMIN ACCOUNT"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${NC}"
echo "  This is the Cloud IoT web dashboard admin login."
echo ""
ADMIN_EMAIL=$(ask "Admin email" "admin@marina.local")
ADMIN_PASSWORD=$(ask_password "Admin password")

# STEP 3: Marina info
clear
echo -e "${BLUE}${BOLD}"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   STEP 3 / 5  —  MARINA INFORMATION"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${NC}"
COMPANY_NAME=$(ask    "Marina / company name"   "Marina")
COMPANY_ADDRESS=$(ask "Address"                 "")
COMPANY_PHONE=$(ask   "Phone"                   "")
COMPANY_EMAIL=$(ask   "Contact email"           "$ADMIN_EMAIL")
PORTAL_NAME=$(ask     "Portal name"             "${COMPANY_NAME} IoT Portal")

# STEP 4: SMTP
clear
echo -e "${BLUE}${BOLD}"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   STEP 4 / 5  —  EMAIL / SMTP  (optional)"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${NC}"
echo "  Used for 2FA login OTP emails."
echo "  If skipped: OTP codes print to log — sudo journalctl -u cloud-iot-backend -f"
echo ""
SMTP_HOST="" SMTP_PORT="587" SMTP_TLS="true"
SMTP_USER="" SMTP_PASS="" SMTP_FROM="noreply@marina.local"
if ask_yn "Configure SMTP?" "n"; then
  SMTP_HOST=$(ask  "SMTP host"         "smtp.gmail.com")
  SMTP_PORT=$(ask  "SMTP port"         "587")
  SMTP_TLS=$(ask   "TLS (true/false)"  "true")
  SMTP_FROM=$(ask  "From address"      "noreply@${ADMIN_EMAIL##*@}")
  SMTP_USER=$(ask  "SMTP username"     "$SMTP_FROM")
  SMTP_PASS=$(ask_password "SMTP password")
fi

# STEP 5: Confirm
clear
echo -e "${BLUE}${BOLD}"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   STEP 5 / 5  —  CONFIRM & INSTALL"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${NC}"
echo -e "  ${GREEN}Summary:${NC}"
echo -e "    Hostname   : ${WHITE}${HOSTNAME}${NC}"
if $USE_STATIC; then
  echo -e "    IP         : ${WHITE}${STATIC_IP}${NC}  static  (gateway: ${GATEWAY})"
else
  echo -e "    IP         : ${WHITE}${CURRENT_IP}${NC}  DHCP (may change — check router)"
fi
echo -e "    Interface  : ${WHITE}${IFACE}${NC}"
echo -e "    Admin      : ${WHITE}${ADMIN_EMAIL}${NC}"
echo -e "    Marina     : ${WHITE}${COMPANY_NAME}${NC}"
[ -n "$SMTP_HOST" ] && \
  echo -e "    SMTP       : ${WHITE}${SMTP_HOST}:${SMTP_PORT}${NC}" || \
  echo -e "    SMTP       : ${YELLOW}not configured (OTP to log)${NC}"
echo ""
ask_yn "Proceed with installation?" "y" || error "Cancelled by user."

JWT_SECRET=$(openssl rand -hex 32)
# Strip any stray newlines/carriage-returns from collected values
ADMIN_EMAIL=$(echo "$ADMIN_EMAIL" | tr -d '\n\r')
ADMIN_PASSWORD=$(echo "$ADMIN_PASSWORD" | tr -d '\n\r')

# ═══════════════════════════════════════════════════════════════════════════════
# INSTALLATION
# ═══════════════════════════════════════════════════════════════════════════════

phase "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv python3-dev \
  python3-setuptools python3-wheel \
  nginx \
  openssl libssl-dev libffi-dev build-essential \
  iproute2 net-tools curl wget \
  ca-certificates gnupg apt-transport-https \
  vim nano htop unzip git \
  logrotate \
  mosquitto-clients \
  nodejs npm
info "System packages installed"

phase "Installing Docker CE"
if ! command -v docker &>/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu noble stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y \
    docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
systemctl enable docker
systemctl start docker
# Add the cloud-iot OS user to docker group (created during Ubuntu install)
REAL_USER="${SUDO_USER:-cloud-iot}"
usermod -aG docker "$REAL_USER" 2>/dev/null || true
info "Docker $(docker --version | cut -d' ' -f3 | tr -d ',')"

phase "Pulling Docker images"
docker pull eclipse-mosquitto:2.0
info "Mosquitto image ready"

phase "Copying application from repo"
rm -rf "$APP_DIR" 2>/dev/null || true
mkdir -p "$APP_DIR"
for d in backend frontend mosquitto; do
  [ -d "${REPO_DIR}/${d}" ] && cp -r "${REPO_DIR}/${d}" "${APP_DIR}/${d}"
done
[ -f "${REPO_DIR}/docker-compose.yml" ] && \
  cp "${REPO_DIR}/docker-compose.yml" "${APP_DIR}/"

# Clean dev artifacts
rm -rf "${APP_DIR}/backend/.venv" \
       "${APP_DIR}/backend/pedestal.db" \
       "${APP_DIR}/backend/data/users.db" \
       "${APP_DIR}/frontend/node_modules" 2>/dev/null || true
find "${APP_DIR}/backend" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

mkdir -p "${APP_DIR}/backend/data" \
         "${APP_DIR}/backend/backgrounds" \
         "/var/log/cloud-iot" \
         "/var/lib/cloud-iot"

# Stub PDF service (reportlab not needed on NUC)
cat > "${APP_DIR}/backend/app/services/pdf_service.py" << 'PDFEOF'
"""PDF generation disabled on NUC deployment."""
from fastapi import HTTPException
def make_contract_pdf(*a, **kw):
    raise HTTPException(status_code=501, detail="PDF not available on NUC.")
def make_invoice_pdf(*a, **kw):
    raise HTTPException(status_code=501, detail="PDF not available on NUC.")
PDFEOF
sed -i '/reportlab/d' "${APP_DIR}/backend/requirements.txt"

# Stub out simulator (not used on NUC)
cat > "${APP_DIR}/backend/app/services/simulator_manager.py" << 'SIMEOF'
"""Simulator disabled on NUC deployment."""
class _Stub:
    is_running = False
    def stop(self): pass
simulator_manager = _Stub()
SIMEOF

info "Application copied to ${APP_DIR}"

phase "Building React frontend"
cd "${APP_DIR}/frontend"
npm ci --prefer-offline --no-audit --no-fund
npm run build
rm -rf node_modules
cd /
info "Frontend built: ${APP_DIR}/frontend/dist/"

phase "Creating Python virtual environment"
PYTHON_BIN="python3"
for v in python3.13 python3.12 python3.11; do
  command -v "$v" &>/dev/null && PYTHON_BIN="$v" && break
done
info "Using: $($PYTHON_BIN --version)"

VENV="${APP_DIR}/backend/.venv"
"$PYTHON_BIN" -m venv "$VENV"
"${VENV}/bin/pip" install --upgrade pip setuptools wheel -q
"${VENV}/bin/pip" install \
  -r "${APP_DIR}/backend/requirements.txt" \
  -q
info "Python packages installed"

phase "Writing .env configuration"
cat > "${APP_DIR}/backend/.env" << EOF
# Cloud IoT NUC — generated $(date -u +"%Y-%m-%dT%H:%M:%SZ")
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
ALLOWED_ORIGINS=$( $USE_STATIC && echo "http://${STATIC_IP},http://${STATIC_IP}:80" || echo "*" )
COMPANY_NAME=${COMPANY_NAME}
COMPANY_ADDRESS=${COMPANY_ADDRESS}
COMPANY_PHONE=${COMPANY_PHONE}
COMPANY_EMAIL=${COMPANY_EMAIL}
COMPANY_PORTAL_NAME=${PORTAL_NAME}
EOF
chmod 640 "${APP_DIR}/backend/.env"
info ".env written"

phase "Configuring Mosquitto (Docker)"
mkdir -p "${APP_DIR}/mosquitto/config"
cat > "${APP_DIR}/mosquitto/config/mosquitto.conf" << 'MQTTEOF'
listener 1883 0.0.0.0
allow_anonymous true
persistence true
persistence_location /mosquitto/data/
log_dest stdout
MQTTEOF
cat > "${APP_DIR}/docker-compose.yml" << 'DCEOF'
services:
  mosquitto:
    image: eclipse-mosquitto:2.0
    container_name: pedestal-mqtt-broker
    ports:
      - "1883:1883"
    volumes:
      - ./mosquitto/config:/mosquitto/config:ro
      - mosquitto-data:/mosquitto/data
    restart: unless-stopped
volumes:
  mosquitto-data:
DCEOF
info "Mosquitto configured"

phase "Configuring nginx"
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
nginx -t
systemctl enable nginx
info "nginx configured"

phase "Configuring systemd services"
VENV_BIN="${APP_DIR}/backend/.venv/bin"

cat > /etc/systemd/system/cloud-iot-backend.service << EOF
[Unit]
Description=Cloud IoT FastAPI Backend
Documentation=https://github.com/Lika-Digital/Cloud_IOT
After=network.target docker.service cloud-iot-compose.service

[Service]
Type=simple
User=${REAL_USER}
Group=${REAL_USER}
WorkingDirectory=${APP_DIR}/backend
EnvironmentFile=${APP_DIR}/backend/.env
ExecStart=${VENV_BIN}/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=cloud-iot-backend

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/cloud-iot-compose.service << EOF
[Unit]
Description=Cloud IoT Docker Services (MQTT)
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

# Management CLI
cat > /usr/local/bin/cloud-iot << 'CLIEOF'
#!/usr/bin/env bash
case "${1:-}" in
  start)   systemctl start  cloud-iot-compose cloud-iot-backend nginx ;;
  stop)    systemctl stop   cloud-iot-backend cloud-iot-compose ;;
  restart) systemctl restart cloud-iot-compose cloud-iot-backend nginx ;;
  status)
    for svc in cloud-iot-compose cloud-iot-backend nginx; do
      echo "── $svc ──"
      systemctl status "$svc" --no-pager -l 2>/dev/null | head -6
      echo ""
    done ;;
  logs)
    case "${2:-backend}" in
      backend)  journalctl -u cloud-iot-backend -f --no-pager ;;
      nginx)    tail -f /var/log/nginx/error.log ;;
      mqtt)     docker logs -f pedestal-mqtt-broker ;;
      *)        journalctl -u "cloud-iot-${2}" -f --no-pager ;;
    esac ;;
  config)   "${EDITOR:-nano}" /opt/cloud-iot/backend/.env \
              && systemctl restart cloud-iot-backend ;;
  ip)       hostname -I | awk '{print $1}' ;;
  update)   systemctl restart cloud-iot-compose cloud-iot-backend nginx ;;
  *)        echo "Usage: sudo cloud-iot {start|stop|restart|status|logs [backend|nginx|mqtt]|config|ip|update}" ;;
esac
CLIEOF
chmod +x /usr/local/bin/cloud-iot

chown -R "${REAL_USER}:${REAL_USER}" "$APP_DIR" 2>/dev/null || true
chown -R "${REAL_USER}:${REAL_USER}" /var/log/cloud-iot 2>/dev/null || true

systemctl daemon-reload
systemctl enable cloud-iot-compose cloud-iot-backend
info "Services configured"

phase "Starting services"
systemctl start cloud-iot-compose
sleep 5
systemctl start cloud-iot-backend
sleep 8
systemctl start nginx
info "All services started"

phase "Enabling SQLite WAL mode"
for db in "${APP_DIR}/backend/pedestal.db" \
          "${APP_DIR}/backend/data/users.db"; do
  if [ -f "$db" ]; then
    python3 -c "
import sqlite3
c = sqlite3.connect('${db}')
c.execute('PRAGMA journal_mode=WAL')
c.execute('PRAGMA synchronous=NORMAL')
c.execute('PRAGMA cache_size=-32000')
c.commit(); c.close()
"
    info "WAL mode: $(basename $db)"
  fi
done

phase "Network configuration"
if $USE_STATIC; then
  # Remove Ubuntu's default DHCP config
  rm -f /etc/netplan/00-installer-config.yaml \
        /etc/netplan/50-cloud-init.yaml 2>/dev/null || true

  # Build DNS list for netplan format: [8.8.8.8, 8.8.4.4]
  DNS_YAML="[$(echo "$DNS" | sed 's/ /, /g')]"

  cat > /etc/netplan/01-cloud-iot.yaml << EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    ${IFACE}:
      dhcp4: false
      addresses:
        - ${STATIC_IP}/24
      routes:
        - to: default
          via: ${GATEWAY}
      nameservers:
        addresses: ${DNS_YAML}
EOF
  chmod 600 /etc/netplan/01-cloud-iot.yaml
  netplan apply 2>/dev/null || warn "Netplan will apply on reboot"
  info "Static IP configured: ${STATIC_IP}"
else
  info "DHCP — keeping existing network config"
  STATIC_IP="$CURRENT_IP"
fi

phase "Setting hostname"
echo "$HOSTNAME" > /etc/hostname
hostname "$HOSTNAME"
if grep -q '127.0.1.1' /etc/hosts; then
  sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t${HOSTNAME}/" /etc/hosts
else
  echo "127.0.1.1    ${HOSTNAME}" >> /etc/hosts
fi
info "Hostname: ${HOSTNAME}"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
cat << 'DONE'
  ╔══════════════════════════════════════════════════════════════════╗
  ║           CLOUD IOT INSTALLATION COMPLETE!                      ║
  ╚══════════════════════════════════════════════════════════════════╝
DONE
echo -e "${NC}"
DISPLAY_IP=$(hostname -I | awk '{print $1}')
echo -e "  ${WHITE}Dashboard :${NC}  http://${DISPLAY_IP}"
echo -e "  ${WHITE}SSH       :${NC}  ssh ${REAL_USER}@${DISPLAY_IP}"
echo -e "  ${WHITE}MQTT      :${NC}  ${DISPLAY_IP}:1883  (Arduino Opta)"
$USE_STATIC || echo -e "  ${YELLOW}DHCP IP shown above — check your router if it changes after reboot.${NC}"
echo -e "  ${WHITE}Manage    :${NC}  sudo cloud-iot status"
echo ""
[ -z "$SMTP_HOST" ] && \
  echo -e "  ${YELLOW}OTP codes (2FA login):${NC} sudo journalctl -u cloud-iot-backend -f"
echo ""
echo -e "  ${GREEN}Rebooting in 10 seconds...${NC}"
sleep 10
reboot
