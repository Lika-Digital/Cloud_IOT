#!/usr/bin/env bash
# ============================================================================
# Cloud IoT NUC — In-place Upgrade Script
#
# Pulls a branch from GitHub into ~/Cloud_IOT (the git repo), copies changed
# files to /opt/cloud-iot (the running app), rebuilds the frontend if needed,
# and restarts only the affected services.
# The .env file and databases are never touched.
#
# Usage (on the NUC):
#   sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh              # main — normal
#   sudo bash ~/Cloud_IOT/nuc_image/upgrade.sh develop      # a test branch
#
# THE BRANCH ARGUMENT (v3.44). The default is and stays `main`, so every existing
# instruction, cron entry and habit keeps working unchanged — and so the rollback
# path is untouched by the existence of this argument.
#
# It exists so a release can be TESTED on the cabinet before `main` moves. While the
# NUC runs a test branch, `main` is still the last known-good release: rolling back
# is re-running this script with no argument, because nothing on `main` ever changed.
# That is the whole rollback plan, and it needs no snapshot and no backup step.
#
# Requirements:
#   - NUC must have internet access (GitHub reachable)
#   - A git clone of this repo anywhere; the script locates it from its own path
#   - Application running at /opt/cloud-iot
# ============================================================================
set -euo pipefail

# Branch to deploy. First positional argument; `main` when not given.
BRANCH="${1:-main}"

# ── Where the repo is, and who owns it — DERIVED, not hardcoded ─────────────────
#
# This said REPO_DIR="/home/cloud_iot/Cloud_IOT" with an UNDERSCORE, and the service
# account on at least one cabinet is `cloud-iot` with a HYPHEN. The script then refused
# to run with "Git repo not found", while standing inside the very repo it could not
# find — because `~` resolved to /home/cloud-iot and the script looked in /home/cloud_iot.
#
# The script knows where it is. `nuc_image/upgrade.sh` is always one directory below the
# repo root, so the root is derivable with no assumption about the username, the home
# directory, or even that the repo lives under /home at all. REPO_DIR= in the environment
# still overrides it for anything unusual.
#
# The same underscore was baked into `chown cloud_iot:cloud_iot` and `export HOME`. Both
# now read the actual owner of the checkout, which is the account git must run as.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(dirname "$SCRIPT_DIR")}"
APP_DIR="${APP_DIR:-/opt/cloud-iot}"
LOG_FILE="/var/log/cloud-iot/upgrade.log"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${GREEN}  [✔]${NC} $*" | tee -a "$LOG_FILE"; }
warn()  { echo -e "${YELLOW}  [!]${NC} $*" | tee -a "$LOG_FILE"; }
error() { echo -e "${RED}  [✘]${NC} $*" | tee -a "$LOG_FILE"; exit 1; }
phase() { echo -e "\n${CYAN}${BOLD}  ▶ $*${NC}" | tee -a "$LOG_FILE"; }

# ── Guards ────────────────────────────────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || error "Run as root: sudo bash $0"
[ -d "${REPO_DIR}/.git" ] || error "Git repo not found at ${REPO_DIR} — this script expects to live at <repo>/nuc_image/upgrade.sh. Run it from inside the clone, or set REPO_DIR=/path/to/Cloud_IOT."
[ -d "$APP_DIR" ]         || error "App not found at ${APP_DIR} — is Cloud IoT installed?"

# ── Who owns the checkout ───────────────────────────────────────────────────────
#
# Read from REPO_DIR ITSELF, not from .git. `.git` is frequently root-polluted by the
# time anyone looks — root runs git, leaves root-owned objects behind, and the next
# fetch dies with "insufficient permission for adding an object to repository database".
# Reading the owner of the thing that is already broken would return `root` and the chown
# would then CEMENT the bug rather than repair it. The top-level directory keeps the
# correct owner because git never rewrites it.
#
# $SUDO_USER is the fallback: it is the account that invoked sudo, which on both cabinets
# is the service account. Last resort is root, and if we get that far the verification
# below will say so rather than pretending.
REPO_USER="$(stat -c '%U' "$REPO_DIR" 2>/dev/null || true)"
if [ -z "$REPO_USER" ] || [ "$REPO_USER" = "root" ]; then
  REPO_USER="${SUDO_USER:-root}"
fi
REPO_GROUP="$(id -gn "$REPO_USER" 2>/dev/null || echo "$REPO_USER")"
REPO_HOME="$(getent passwd "$REPO_USER" | cut -d: -f6)"
[ -n "$REPO_HOME" ] || REPO_HOME="/root"
export HOME="$REPO_HOME"

# ── chown, and PROVE it worked ──────────────────────────────────────────────────
#
# Every chown in this script used to end `2>/dev/null || true`. On a cabinet whose
# account is spelled differently from the hardcoded name, all of them failed silently for
# months — which is exactly why git started dying on root-owned objects while the line
# that exists to prevent that reported nothing.
#
# A corrective action that cannot report its own failure is not a correction. These
# VERIFY afterwards and stop the run, because continuing past a failed ownership fix just
# moves the failure somewhere less obvious.
fix_owner() {
  local target="$1" label="$2"
  [ -e "$target" ] || return 0
  if ! chown -R "${REPO_USER}:${REPO_GROUP}" "$target" 2>>"$LOG_FILE"; then
    error "Could not set ownership of ${label} (${target}) to ${REPO_USER}:${REPO_GROUP}.\n      Does that account exist?  getent passwd ${REPO_USER}\n      This is not cosmetic: root-owned files here make the NEXT git fetch fail with\n      'insufficient permission for adding an object to repository database'."
  fi
  local actual
  actual="$(stat -c '%U' "$target" 2>/dev/null || echo "?")"
  if [ "$actual" != "$REPO_USER" ]; then
    error "Ownership of ${label} is still ${actual}, expected ${REPO_USER} — the chown\n      reported success but did not take effect."
  fi
}

fix_owner "${REPO_DIR}/.git" "the git metadata"

# git refuses to operate on a repo owned by another user unless told it is safe. As root
# on a checkout owned by the service account, that is exactly the situation.
git config --global --add safe.directory "$REPO_DIR" 2>/dev/null || true

mkdir -p /var/log/cloud-iot
echo "" >> "$LOG_FILE"
echo "════════════════════════════════════════════════" >> "$LOG_FILE"
echo "  Upgrade started: $(date -u '+%Y-%m-%d %H:%M:%S UTC')" >> "$LOG_FILE"
echo "  Branch: ${BRANCH}" >> "$LOG_FILE"
echo "  Repo:   ${REPO_DIR} (owner ${REPO_USER}:${REPO_GROUP})" >> "$LOG_FILE"
echo "════════════════════════════════════════════════" >> "$LOG_FILE"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║         Cloud IoT NUC — Upgrade Script              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""
echo "  Repo:   ${REPO_DIR}"
echo "  Owner:  ${REPO_USER}:${REPO_GROUP}"
echo ""
if [ "$BRANCH" != "main" ]; then
  # Said loudly, because a NUC left on a test branch silently stops receiving releases.
  echo -e "${YELLOW}${BOLD}  ⚠  Deploying branch '${BRANCH}', not main.${NC}"
  echo -e "${YELLOW}     This is a TEST deployment. main is untouched and remains the"
  echo -e "     rollback: re-run this script with no argument to return to it.${NC}"
  echo ""
fi

# ── Ensure we're on main ─────────────────────────────────────────────────────
phase "Current version"
cd "$REPO_DIR"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
  warn "Repo is on branch '${CURRENT_BRANCH}' — switching to ${BRANCH}"
  git stash -q 2>/dev/null || true
  git fetch origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE" \
    || error "Cannot fetch branch '${BRANCH}' — does it exist on origin?"
  git checkout "$BRANCH" 2>&1 | tee -a "$LOG_FILE" \
    || error "Failed to switch to ${BRANCH}"
fi
CURRENT_COMMIT=$(git rev-parse --short HEAD)
CURRENT_DESCR=$(git log -1 --pretty="%s" 2>/dev/null || echo "unknown")
info "Running: ${CURRENT_COMMIT} — ${CURRENT_DESCR}"
info "Branch:  main"

# ── Fetch latest ──────────────────────────────────────────────────────────────
phase "Fetching latest from GitHub"
git fetch origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE" || error "git fetch failed — check internet connection"

REMOTE_COMMIT=$(git rev-parse --short "origin/${BRANCH}")
NEEDS_PULL=false
NEEDS_SYNC=false

if [ "$CURRENT_COMMIT" != "$REMOTE_COMMIT" ]; then
  NEEDS_PULL=true
fi

# Check if /opt/cloud-iot/ is out of sync with the repo even if git is up to date.
# This catches the case where someone ran "git pull" manually before the script.
if diff -q "${REPO_DIR}/backend/app/main.py" "${APP_DIR}/backend/app/main.py" &>/dev/null; then
  : # files match — check a broader diff
fi
if ! diff -rq "${REPO_DIR}/backend/app/" "${APP_DIR}/backend/app/" &>/dev/null 2>&1; then
  NEEDS_SYNC=true
fi

if ! $NEEDS_PULL && ! $NEEDS_SYNC; then
  info "Already up to date (${CURRENT_COMMIT}) and /opt/cloud-iot/ is in sync. Nothing to do."
  echo ""
  exit 0
fi

if $NEEDS_PULL; then
  # Show what will be applied
  echo ""
  echo -e "  ${BOLD}Commits to apply:${NC}"
  git log "HEAD..origin/${BRANCH}" --oneline | sed 's/^/    /' | tee -a "$LOG_FILE"
  echo ""
fi

if $NEEDS_SYNC && ! $NEEDS_PULL; then
  warn "Git repo is up to date but /opt/cloud-iot/ is out of sync — will re-deploy."
  echo ""
fi

# Detect changed files (vs remote if pulling, vs deployed app if just syncing)
BACKEND_CHANGED=false
FRONTEND_CHANGED=false

if $NEEDS_PULL; then
  CHANGED_FILES=$(git diff "HEAD..origin/${BRANCH}" --name-only)
  echo "$CHANGED_FILES" | grep -q "^backend/" && BACKEND_CHANGED=true
  echo "$CHANGED_FILES" | grep -qE "^frontend/" && FRONTEND_CHANGED=true
elif $NEEDS_SYNC; then
  # Can't diff git commits — just force both
  BACKEND_CHANGED=true
  FRONTEND_CHANGED=true
fi

echo -e "  ${BOLD}Changes detected:${NC}"
$BACKEND_CHANGED  && echo -e "    ${YELLOW}● Backend${NC}" || echo -e "    · Backend (no changes)"
$FRONTEND_CHANGED && echo -e "    ${YELLOW}● Frontend${NC}" || echo -e "    · Frontend (no changes)"
echo ""

# Confirm
read -r -p "  Apply upgrade? [y/N]: " CONFIRM
[[ "${CONFIRM,,}" =~ ^(y|yes)$ ]] || { echo "  Aborted."; exit 0; }
echo ""

# ── Pull (only if there are new commits) ─────────────────────────────────────
if $NEEDS_PULL; then
  phase "Pulling latest code"
  git pull origin "$BRANCH" 2>&1 | tee -a "$LOG_FILE" || error "git pull failed"
else
  phase "Syncing (git already up to date)"
fi
NEW_COMMIT=$(git rev-parse --short HEAD)
info "Version: ${NEW_COMMIT}"

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
  fix_owner "${APP_DIR}/backend/.venv" "the backend virtualenv"
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
  fix_owner "${APP_DIR}/frontend/dist" "the built frontend"
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
  fix_owner "${APP_DIR}/backend/app" "the backend application"

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
for svc in cloud-iot-backend nginx; do
  STATE=$(systemctl is-active "$svc" 2>/dev/null || echo "not installed")
  if [ "$STATE" = "active" ]; then
    echo -e "    ${GREEN}●${NC} ${svc}: ${STATE}"
  else
    echo -e "    ${YELLOW}●${NC} ${svc}: ${STATE}"
  fi
done
# Mosquitto runs in Docker, not as a systemd service
if command -v docker &>/dev/null && docker ps --format '{{.Names}}' 2>/dev/null | grep -q "pedestal-mqtt-broker"; then
  echo -e "    ${GREEN}●${NC} mosquitto (docker): running"
else
  echo -e "    ${YELLOW}●${NC} mosquitto (docker): not running"
fi
echo ""
info "Log: ${LOG_FILE}"
echo ""
