#!/usr/bin/env bash
# ============================================================================
# Cloud IoT NUC — Complete Uninstall Script
#
# Removes ALL Cloud IoT software from the NUC, leaving Ubuntu clean.
# Use this before a fresh v3.0 install (Situation C).
#
# What is removed:
#   - systemd services (backend, compose)
#   - nginx site config + reverse proxy
#   - /opt/cloud-iot/ (all app files, databases, venv)
#   - Docker MQTT broker container + image
#   - cloud-iot CLI (/usr/local/bin/cloud-iot)
#   - ~/Cloud_IOT git repo clone
#   - Log file /var/log/cloud-iot-install.log
#
# What is NOT removed:
#   - Ubuntu OS, Docker engine, Node.js, nginx, Python
#     (base packages — leave them, installer needs them)
#
# Usage:
#   sudo bash nuc_image/nuc_uninstall.sh
# ============================================================================
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${GREEN}[✔]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
step()  { echo -e "\n${CYAN}${BOLD}── $* ──${NC}"; }

[[ $EUID -ne 0 ]] && { echo -e "${RED}Run with sudo: sudo bash nuc_image/nuc_uninstall.sh${NC}"; exit 1; }

clear
echo -e "${RED}${BOLD}"
cat << 'BANNER'
  ╔══════════════════════════════════════════════════════════════════╗
  ║        Cloud IoT NUC — Complete Uninstall                       ║
  ║        This removes ALL Cloud IoT software from this NUC.       ║
  ╚══════════════════════════════════════════════════════════════════╝
BANNER
echo -e "${NC}"
echo "  The following will be permanently removed:"
echo "    • systemd services (cloud-iot-backend, cloud-iot-compose)"
echo "    • /opt/cloud-iot/  (app code, databases, Python venv)"
echo "    • nginx Cloud IoT site config"
echo "    • Docker MQTT broker (pedestal-mqtt-broker)"
echo "    • /usr/local/bin/cloud-iot  (CLI)"
echo "    • ~/Cloud_IOT  (git repo)"
echo "    • /var/log/cloud-iot-install.log"
echo ""
echo -e "${YELLOW}  Base system packages (Docker, Node, nginx, Python) are kept.${NC}"
echo ""
read -r -p "  Type 'uninstall' to confirm: " CONFIRM
if [[ "$CONFIRM" != "uninstall" ]]; then
    echo ""
    echo "  Aborted."
    exit 0
fi
echo ""

# ── 1. Stop and disable systemd services ─────────────────────────────────────
step "1/7  Stopping services"

for svc in cloud-iot-backend cloud-iot-compose; do
    if systemctl is-active --quiet "$svc" 2>/dev/null; then
        systemctl stop "$svc"
        info "Stopped $svc"
    fi
    if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
        systemctl disable "$svc"
        info "Disabled $svc"
    fi
done

# Remove service unit files
for f in /etc/systemd/system/cloud-iot-backend.service \
          /etc/systemd/system/cloud-iot-compose.service; do
    [ -f "$f" ] && rm -f "$f" && info "Removed $f"
done
systemctl daemon-reload

# ── 2. Remove nginx site config ───────────────────────────────────────────────
step "2/7  Removing nginx config"

for f in /etc/nginx/sites-enabled/cloud-iot \
          /etc/nginx/sites-available/cloud-iot; do
    [ -f "$f" ] && rm -f "$f" && info "Removed $f"
done

# Restart nginx (falls back to default site or stops if nothing left)
if systemctl is-active --quiet nginx 2>/dev/null; then
    nginx -t 2>/dev/null && systemctl reload nginx && info "nginx reloaded" \
        || warn "nginx config invalid after removal — check manually"
fi

# ── 3. Remove Docker MQTT broker ──────────────────────────────────────────────
step "3/7  Removing Docker MQTT broker"

if command -v docker &>/dev/null; then
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "pedestal-mqtt-broker"; then
        docker stop pedestal-mqtt-broker 2>/dev/null || true
        docker rm   pedestal-mqtt-broker 2>/dev/null || true
        info "Removed container: pedestal-mqtt-broker"
    fi

    if docker images --format '{{.Repository}}' 2>/dev/null | grep -q "eclipse-mosquitto"; then
        docker rmi eclipse-mosquitto 2>/dev/null || true
        info "Removed image: eclipse-mosquitto"
    fi

    # Remove docker-compose project if it exists
    COMPOSE_DIR=""
    for candidate in ~/Cloud_IOT /opt/cloud-iot /home/*/Cloud_IOT; do
        [ -f "$candidate/docker-compose.yml" ] && COMPOSE_DIR="$candidate" && break
    done
    if [ -n "$COMPOSE_DIR" ]; then
        cd "$COMPOSE_DIR"
        docker compose down --remove-orphans 2>/dev/null || true
        info "docker compose down completed"
        cd /
    fi
else
    warn "Docker not found — skipping container cleanup"
fi

# ── 4. Remove /opt/cloud-iot ─────────────────────────────────────────────────
step "4/7  Removing /opt/cloud-iot"

if [ -d /opt/cloud-iot ]; then
    rm -rf /opt/cloud-iot
    info "Removed /opt/cloud-iot"
else
    warn "/opt/cloud-iot not found — already removed"
fi

# ── 5. Remove cloud-iot CLI ───────────────────────────────────────────────────
step "5/7  Removing cloud-iot CLI"

[ -f /usr/local/bin/cloud-iot ] && rm -f /usr/local/bin/cloud-iot && info "Removed /usr/local/bin/cloud-iot"

# ── 6. Remove git repo clone ──────────────────────────────────────────────────
step "6/7  Removing git repo"

for candidate in ~/Cloud_IOT /home/*/Cloud_IOT /root/Cloud_IOT; do
    if [ -d "$candidate/.git" ]; then
        rm -rf "$candidate"
        info "Removed $candidate"
    fi
done

# ── 7. Remove log file ────────────────────────────────────────────────────────
step "7/7  Removing log file"

[ -f /var/log/cloud-iot-install.log ] && rm -f /var/log/cloud-iot-install.log && info "Removed install log"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════"
echo -e "${GREEN}${BOLD}  Cloud IoT completely removed.${NC}"
echo ""
echo "  Ready for a fresh install:"
echo ""
echo "    git clone https://github.com/Lika-Digital/Cloud_IOT.git"
echo "    cd Cloud_IOT"
echo "    git checkout tags/v3.0"
echo "    sudo bash nuc_image/ubuntu-install.sh"
echo ""
echo "══════════════════════════════════════════════════════════"
