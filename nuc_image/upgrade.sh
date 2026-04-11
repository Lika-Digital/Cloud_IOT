#!/usr/bin/env bash
# ============================================================================
# Cloud IoT NUC — In-place Upgrade Script
#
# Pulls the latest main branch from GitHub into ~/Cloud_IOT (the git repo),
# copies changed files to /opt/cloud-iot (the running app), rebuilds the
# frontend if needed, and restarts only the affected services.
# The .env file and databases are never touched.
#
# Usage (on the NUC):
#   sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh
#
# Requirements:
#   - NUC must have internet access (GitHub reachable)
#   - Git repo at /home/cloud_iot/Cloud_IOT
#   - Application running at /opt/cloud-iot
# ============================================================================
set -euo pipefail

REPO_DIR="/home/cloud_iot/Cloud_IOT"
APP_DIR="/opt/cloud-iot"
LOG_FILE="/var/log/cloud-iot/upgrade.log"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${GREEN}  [✔]${NC} $*" | tee -a "$LOG_FILE"; }
warn()  { echo -e "${YELLOW}  [!]${NC} $*" | tee -a "$LOG_FILE"; }
error() { echo -e "${RED}  [✘]${NC} $*" | tee -a "$LOG_FILE"; exit 1; }
phase() { echo -e "\n${CYAN}${BOLD}  ▶ $*${NC}" | tee -a "$LOG_FILE"; }

# ── Guards ────────────────────────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || error "Run as root: sudo bash $0"
[ -d "${REPO_DIR}/.git" ] || error "Git repo not found at ${REPO_DIR} — run: git clone https://github.com/Lika-Digital/Cloud_IOT.git ${REPO_DIR}"
[ -d "$APP_DIR" ]         || error "App not found at ${APP_DIR} — is Cloud IoT installed?"

mkdir -p /var/log/cloud-iot
echo "" >> "$LOG_FILE"
echo "════════════════════════════════════════════════" >> "$LOG_FILE"
echo "  Upgrade started: $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> "$LOG_FILE"
echo "════════════════════════════════════════════════" >> "$LOG_FILE"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║         Cloud IoT NUC — Upgrade Script              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Show current version ──────────────────────────────────────────────────────
phase "Current version"
cd "$REPO_DIR"
CURRENT_COMMIT=$(git rev-parse --short HEAD)
CURRENT_DESCR=$(git log -1 --pretty="%s" 2>/dev/null || echo "unknown")
info "Running: ${CURRENT_COMMIT} — ${CURRENT_DESCR}"
info "Branch:  $(git rev-parse --abbrev-ref HEAD)"

# ── Fetch latest ──────────────────────────────────────────────────────────────
phase "Fetching latest from GitHub"
git fetch origin main 2>&1 | tee -a "$LOG_FILE" || error "git fetch failed — check internet connection"

REMOTE_COMMIT=$(git rev-parse --short origin/main)
if [ "$CURRENT_COMMIT" = "$REMOTE_COMMIT" ]; then
  info "Already up to date (${CURRENT_COMMIT}). Nothing to do."
  echo ""
  exit 0
fi

# Show what will be applied
echo ""
echo -e "  ${BOLD}Commits to apply:${NC}"
git log HEAD..origin/main --oneline | sed 's/^/    /' | tee -a "$LOG_FILE"
echo ""

# Detect changed files before pull
CHANGED_FILES=$(git diff HEAD..origin/main --name-only)
BACKEND_CHANGED=false
FRONTEND_CHANGED=false

echo "$CHANGED_FILES" | grep -q "^backend/" && BACKEND_CHANGED=true
echo "$CHANGED_FILES" | grep -qE "^frontend/" && FRONTEND_CHANGED=true

echo -e "  ${BOLD}Changes detected:${NC}"
$BACKEND_CHANGED  && echo -e "    ${YELLOW}● Backend${NC}" || echo -e "    · Backend (no changes)"
$FRONTEND_CHANGED && echo -e "    ${YELLOW}● Frontend${NC}" || echo -e "    · Frontend (no changes)"
echo ""

# Confirm
read -r -p "  Apply upgrade? [y/N]: " CONFIRM
[[ "${CONFIRM,,}" =~ ^(y|yes)$ ]] || { echo "  Aborted."; exit 0; }
echo ""

# ── Pull ──────────────────────────────────────────────────────────────────────
phase "Pulling latest code"
git pull origin main 2>&1 | tee -a "$LOG_FILE" || error "git pull failed"
NEW_COMMIT=$(git rev-parse --short HEAD)
info "Updated to: ${NEW_COMMIT}"

# ── Venv health check (always runs, independent of file changes) ──────────────
VENV_PIP="${APP_DIR}/backend/.venv/bin/pip"
if [ ! -f "$VENV_PIP" ]; then
  phase "Recreating Python virtual environment"
  warn "Virtual environment missing — recreating from scratch"
  PYTHON_BIN=""
  for v in python3.13 python3.12 python3.11 python3; do
    command -v "$v" &>/dev/null && { PYTHON_BIN="$v"; break; }
  done
  [ -n "$PYTHON_BIN" ] || error "No python3 found — cannot create venv"
  "$PYTHON_BIN" -m venv "${APP_DIR}/backend/.venv" \
    2>&1 | tee -a "$LOG_FILE" || error "venv creation failed"
  chown -R cloud_iot:cloud_iot "${APP_DIR}/backend/.venv" 2>/dev/null || true
  info "Venv created with $PYTHON_BIN"
  info "Installing Python dependencies..."
  "${APP_DIR}/backend/.venv/bin/pip" install --upgrade pip -q \
    2>&1 | tee -a "$LOG_FILE"
  "${APP_DIR}/backend/.venv/bin/pip" install -q \
    -r "${REPO_DIR}/backend/requirements.txt" \
    email-validator \
    2>&1 | tee -a "$LOG_FILE" || error "pip install failed"
  info "Python dependencies installed"
  # Force backend restart since venv was just recreated
  BACKEND_CHANGED=true
fi

# ── Frontend rebuild ──────────────────────────────────────────────────────────
if $FRONTEND_CHANGED; then
  phase "Rebuilding frontend"

  # Find node
  NODE_BIN=""
  for n in node nodejs; do
    command -v "$n" &>/dev/null && NODE_BIN="$n" && break
  done
  [ -n "$NODE_BIN" ] || error "node not found — install Node.js first"
  info "Node: $($NODE_BIN --version)"

  cd "${REPO_DIR}/frontend"

  # Install/update deps if needed
  if [ ! -d node_modules ] || echo "$CHANGED_FILES" | grep -q "^frontend/package"; then
    info "Installing frontend dependencies..."
    npm install --silent 2>&1 | tail -3 | tee -a "$LOG_FILE"
  fi

  npm run build 2>&1 | tee -a "$LOG_FILE" || error "Frontend build failed"
  info "Frontend built — copying to ${APP_DIR}/frontend/dist/"
  cp -r dist/* "${APP_DIR}/frontend/dist/"
  chown -R cloud_iot:cloud_iot "${APP_DIR}/frontend/dist" 2>/dev/null || true
  info "Frontend deployed"

  nginx -s reload 2>/dev/null && info "nginx reloaded" || warn "nginx reload failed — try: sudo systemctl restart nginx"

  cd "$REPO_DIR"
fi

# ── Backend copy + restart ────────────────────────────────────────────────────
if $BACKEND_CHANGED; then
  phase "Deploying backend"

  # Check for new Python dependencies
  if echo "$CHANGED_FILES" | grep -q "^backend/requirements.txt"; then
    info "requirements.txt changed — installing new packages"
    VENV_PIP="${APP_DIR}/backend/.venv/bin/pip"
    [ -f "$VENV_PIP" ] && "$VENV_PIP" install -r "${REPO_DIR}/backend/requirements.txt" -q \
      2>&1 | tee -a "$LOG_FILE" || warn "pip install had errors — check logs"
  fi

  info "Copying backend/app to ${APP_DIR}/backend/"
  cp -r "${REPO_DIR}/backend/app" "${APP_DIR}/backend/"
  chown -R cloud_iot:cloud_iot "${APP_DIR}/backend/app" 2>/dev/null || true

  phase "Restarting backend service"
  systemctl restart cloud-iot-backend.service
  info "Backend restarting..."

  # Wait up to 15s for it to come up
  for i in $(seq 1 15); do
    sleep 1
    if systemctl is-active --quiet cloud-iot-backend.service; then
      info "Backend is up (${i}s)"
      break
    fi
    [ "$i" -eq 15 ] && warn "Backend taking longer than expected — check: sudo journalctl -u cloud-iot-backend.service -n 30"
  done
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "──────────────────────────────────────────────────────"
echo -e "${GREEN}${BOLD}  Upgrade complete.${NC}"
echo ""
info "Previous: ${CURRENT_COMMIT} — ${CURRENT_DESCR}"
info "Now:      ${NEW_COMMIT} — $(git log -1 --pretty='%s')"
echo ""
echo -e "  ${BOLD}Service status:${NC}"
for svc in cloud-iot-backend mosquitto nginx; do
  STATE=$(systemctl is-active "$svc" 2>/dev/null || echo "not installed")
  if [ "$STATE" = "active" ]; then
    echo -e "    ${GREEN}●${NC} ${svc}: ${STATE}"
  else
    echo -e "    ${YELLOW}●${NC} ${svc}: ${STATE}"
  fi
done
echo ""
info "Log: ${LOG_FILE}"
echo ""
