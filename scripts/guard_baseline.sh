#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  guard_baseline.sh — before/after safety capture for touching the production venv
#
#  Only needed if you decide to install openvino into the PRODUCTION venv.
#  The Stage A.5 measurement does not require that — use guard_measure.sh, which
#  runs entirely from $HOME/guard-staging. Keep this script for the Stage B
#  deploy, or for a deliberate production install.
#
#  USAGE
#    sudo bash scripts/guard_baseline.sh before     # capture + save pip freeze
#    ... make the change ...
#    sudo bash scripts/guard_baseline.sh after      # re-capture and DIFF vs before
#    sudo bash scripts/guard_baseline.sh rollback   # uninstall openvino, restore freeze
#
#  Snapshots live in /var/backups/guard-baseline/ (outside /opt, so upgrade.sh
#  cannot clobber them).
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${CYAN}[baseline]${NC} $*"; }
ok()   { echo -e "${GREEN}[ ok ]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
die()  { echo -e "${RED}[fail]${NC} $*" >&2; exit 1; }

SNAP_DIR="/var/backups/guard-baseline"
VENV_PIP="/opt/cloud-iot/backend/.venv/bin/pip"
ENV_FILE="/opt/cloud-iot/backend/.env"
SERVICES="cloud-iot-backend nginx docker cloudflared tailscaled"
PHASE="${1:-}"

[ -d /opt/cloud-iot ] || die "/opt/cloud-iot not found — run this on the NUC."

capture() {
  local tag="$1"
  local dir="${SNAP_DIR}/${tag}"
  mkdir -p "$dir" || die "cannot create $dir"

  info "Capturing '${tag}' snapshot → $dir"

  # pip freeze — the rollback anchor
  if [ -x "$VENV_PIP" ]; then
    "$VENV_PIP" freeze > "${dir}/pip-freeze.txt" 2>/dev/null \
      && ok "pip freeze: $(wc -l < "${dir}/pip-freeze.txt") packages" \
      || warn "pip freeze failed"
  else
    warn "production pip not found at $VENV_PIP"
  fi

  # CPU: 60 s average is the honest figure, not an instantaneous spike.
  info "Sampling CPU for 60 s (mirrors the watchdog's 60 s rolling average)..."
  {
    echo "# sampled $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    read -r _ u n s i rest < /proc/stat
    local prev_idle=$i prev_total=$((u+n+s+i))
    for _ in $(seq 1 12); do
      sleep 5
      read -r _ u n s i rest < /proc/stat
      local total=$((u+n+s+i))
      local d_total=$((total - prev_total)) d_idle=$((i - prev_idle))
      [ "$d_total" -gt 0 ] && \
        echo "cpu_pct $(awk "BEGIN{printf \"%.1f\", 100*($d_total-$d_idle)/$d_total}")"
      prev_idle=$i; prev_total=$total
    done
  } > "${dir}/cpu-samples.txt" 2>/dev/null
  local avg
  avg=$(awk '/^cpu_pct/{s+=$2;n++} END{if(n)printf "%.1f",s/n}' "${dir}/cpu-samples.txt")
  echo "cpu_avg_pct=${avg:-unknown}" > "${dir}/summary.txt"
  ok "CPU 60 s average: ${avg:-unknown} %"

  # Memory
  free -m > "${dir}/free.txt" 2>/dev/null
  local mem_used
  mem_used=$(awk '/^Mem:/{print $3}' "${dir}/free.txt")
  echo "mem_used_mb=${mem_used:-unknown}" >> "${dir}/summary.txt"
  ok "Memory used: ${mem_used:-unknown} MB"

  # Backend RSS specifically — Stage B must prove the model is NOT resident
  local rss
  rss=$(ps -o rss= -C uvicorn 2>/dev/null | awk '{s+=$1} END{if(s)print int(s/1024)}')
  echo "backend_rss_mb=${rss:-unknown}" >> "${dir}/summary.txt"
  ok "Backend RSS: ${rss:-unknown} MB"

  # Services
  : > "${dir}/services.txt"
  for svc in $SERVICES; do
    printf '%s %s\n' "$svc" "$(systemctl is-active "$svc" 2>/dev/null || echo unknown)" \
      >> "${dir}/services.txt"
  done
  ok "Services: $(tr '\n' ' ' < "${dir}/services.txt")"

  # Disk
  df -h / /var > "${dir}/disk.txt" 2>/dev/null

  # The flag that must stay false
  local flag
  flag=$(grep -E '^USE_ML_MODELS' "$ENV_FILE" 2>/dev/null || echo "USE_ML_MODELS (unset → false)")
  echo "use_ml_models=${flag}" >> "${dir}/summary.txt"
  ok "Flag: ${flag}"

  # Live functional checks — is the app actually serving?
  {
    echo "# $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo -n "api_pedestals_http="
    curl -s -o /dev/null -w '%{http_code}' --max-time 10 \
      http://localhost:8000/api/pedestals 2>/dev/null || echo "unreachable"
    echo ""
    echo -n "mqtt_clients_connected="
    timeout 10 docker exec pedestal-mqtt-broker \
      mosquitto_sub -h localhost -t '$SYS/broker/clients/connected' -C 1 2>/dev/null \
      || echo "unknown"
  } > "${dir}/health.txt" 2>&1
  cat "${dir}/health.txt" | grep -E '^(api|mqtt)' | sed 's/^/  /'

  echo ""
  cat "${dir}/summary.txt"
}

case "$PHASE" in

before)
  capture before
  echo ""
  ok "Baseline saved. Rollback anchor: ${SNAP_DIR}/before/pip-freeze.txt"
  warn "Run this when the marina is NOT busy."
  ;;

after)
  [ -d "${SNAP_DIR}/before" ] || die "no 'before' snapshot — run 'before' first"
  capture after

  echo ""
  echo "════════════════ BEFORE vs AFTER ════════════════"
  for key in cpu_avg_pct mem_used_mb backend_rss_mb use_ml_models; do
    b=$(grep "^${key}=" "${SNAP_DIR}/before/summary.txt" 2>/dev/null | cut -d= -f2-)
    a=$(grep "^${key}=" "${SNAP_DIR}/after/summary.txt"  2>/dev/null | cut -d= -f2-)
    printf '  %-18s %-28s -> %s\n' "$key" "${b:-?}" "${a:-?}"
  done

  echo ""
  echo "Services:"
  if diff -q "${SNAP_DIR}/before/services.txt" "${SNAP_DIR}/after/services.txt" >/dev/null 2>&1; then
    ok "identical to baseline"
  else
    warn "CHANGED:"
    diff "${SNAP_DIR}/before/services.txt" "${SNAP_DIR}/after/services.txt" | sed 's/^/    /'
  fi

  echo ""
  echo "Packages added/removed in the production venv:"
  if [ -f "${SNAP_DIR}/before/pip-freeze.txt" ] && [ -f "${SNAP_DIR}/after/pip-freeze.txt" ]; then
    # Capture first: piping grep into sed would mask grep's "no matches" status.
    PKG_DIFF=$(diff "${SNAP_DIR}/before/pip-freeze.txt" \
                    "${SNAP_DIR}/after/pip-freeze.txt" | grep -E '^[<>]')
    if [ -n "$PKG_DIFF" ]; then
      echo "$PKG_DIFF" | sed 's/^/    /'
    else
      ok "none — production venv unchanged"
    fi
  fi

  echo ""
  echo "Health:"
  grep -E '^(api|mqtt)' "${SNAP_DIR}/after/health.txt" | sed 's/^/    /'
  echo ""
  warn "Confirm manually: berth occupancy analyse still returns, dashboard loads"
  warn "through the tunnel, and USE_ML_MODELS is still false."
  ;;

rollback)
  [ -f "${SNAP_DIR}/before/pip-freeze.txt" ] || die "no baseline freeze to restore"
  warn "Rolling back the production venv to the 'before' snapshot."
  info "Uninstalling openvino"
  "$VENV_PIP" uninstall -y openvino 2>&1 | tail -3 || warn "uninstall reported an error"
  info "Restoring packages from the baseline freeze"
  "$VENV_PIP" install -q -r "${SNAP_DIR}/before/pip-freeze.txt" 2>&1 | tail -5 \
    || warn "restore reported errors — inspect manually"
  info "Restarting backend"
  systemctl restart cloud-iot-backend
  sleep 8
  systemctl is-active cloud-iot-backend && ok "backend is active" || die "backend did NOT come up — check journalctl -u cloud-iot-backend"
  ;;

*)
  sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 1
  ;;
esac
