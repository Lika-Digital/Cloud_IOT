#!/usr/bin/env bash
# ============================================================================
# Cloud IoT — guard worker INSTALL step (2026-10-13)
#
#   sudo bash nuc_image/install-guard.sh
#
# INSTALL IS NOT START. This puts the worker, its own venv, its env file and its systemd
# unit in place, and then STOPS. It never enables, starts or restarts cloud-iot-guard. The
# first start is a separate §13 step, because it needs the camera URL — a cabinet fact that
# carries the camera's password.
#
# Exit codes — read by upgrade.sh and by a person:
#   0  installed, and everything the worker needs to start is present
#   3  installed, but NOT READY: the model is missing. NOT a success.
#   1  error — something was not installed, or openvino cannot load and run the model;
#      nothing claims success
#
# Idempotent: a second run changes nothing, and says "unchanged" for every step.
#
# What it never does:
#   - print the camera URL (GUARD_STREAM_URL holds the password) — not on success, not in
#     an error, not in the log. Its presence and format are checked without echoing it.
#   - touch the backend venv. openvino must never enter it; this script CHECKS that and
#     fails if it has.
#   - touch sshd, cloudflared, tailscaled, ufw/iptables/nftables or Docker networking.
#
# Every absolute path sits under GUARD_INSTALL_ROOT (empty on the NUC) so the test suite can
# run the real script in a temp dir. GUARD_PYTHON / GUARD_SYSTEMCTL / GUARD_USERADD /
# GUARD_CHOWN / GUARD_OWNER_OF / GUARD_ID replace the commands it calls, for the same reason.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(dirname "$SCRIPT_DIR")}"
R="${GUARD_INSTALL_ROOT:-}"
APP_DIR="${R}/opt/cloud-iot"
GUARD_DIR="${APP_DIR}/guard"
VENV="${GUARD_DIR}/.venv"
ENV_FILE="${GUARD_DIR}/guard.env"
MODEL_DIR="${GUARD_DIR}/models"
DATA_DIR="${R}/var/lib/marina-guard"
UNIT_DST="${R}/etc/systemd/system/cloud-iot-guard.service"
BACKEND_ENV="${APP_DIR}/backend/.env"
BACKEND_PY="${APP_DIR}/backend/.venv/bin/python"
LOG_DIR="${R}/var/log/cloud-iot"
LOG_FILE="${LOG_DIR}/guard-install.log"

PYTHON="${GUARD_PYTHON:-python3}"
SYSTEMCTL="${GUARD_SYSTEMCTL:-systemctl}"
USERADD="${GUARD_USERADD:-useradd}"
CHOWN="${GUARD_CHOWN:-chown}"
OWNER_OF="${GUARD_OWNER_OF:-stat -c %U}"
ID="${GUARD_ID:-id}"
GUARD_USER="guard"

mkdir -p "$LOG_DIR"
say()   { echo "  [*] $*" | tee -a "$LOG_FILE"; }
same()  { echo "  [=] $* — unchanged" | tee -a "$LOG_FILE"; }
did()   { echo "  [+] $*" | tee -a "$LOG_FILE"; }
fail()  { echo "  [x] $*" | tee -a "$LOG_FILE"; echo "GUARD INSTALL FAILED — nothing here is a success." | tee -a "$LOG_FILE"; exit 1; }
echo "── guard install $(date -u +%Y-%m-%dT%H:%M:%SZ) ──" >> "$LOG_FILE"

# Read KEY=value from an env file without sourcing it (sourcing would execute it).
env_get() { [ -f "$1" ] && sed -n "s/^$2=//p" "$1" | tail -n1 | tr -d '\r' || true; }

# ── 1. account ───────────────────────────────────────────────────────────────
if $ID "$GUARD_USER" >/dev/null 2>&1; then
  same "system account '${GUARD_USER}'"
else
  $USERADD --system --no-create-home --shell /usr/sbin/nologin --user-group "$GUARD_USER" \
    || fail "could not create the '${GUARD_USER}' account"
  did "created system account '${GUARD_USER}'"
fi

# ── 2. directories ───────────────────────────────────────────────────────────
for d in "$GUARD_DIR" "$MODEL_DIR" "${DATA_DIR}/recordings"; do
  if [ -d "$d" ]; then same "directory ${d#$R}"; else mkdir -p "$d"; did "created ${d#$R}"; fi
done
if [ "$($OWNER_OF "$DATA_DIR")" = "$GUARD_USER" ]; then
  same "owner of ${DATA_DIR#$R}"
else
  $CHOWN -R "${GUARD_USER}:${GUARD_USER}" "$DATA_DIR" || fail "could not chown ${DATA_DIR#$R}"
  did "${DATA_DIR#$R} owned by ${GUARD_USER} (the only place the worker writes)"
fi

# ── 3. worker code ───────────────────────────────────────────────────────────
SRC="${REPO_DIR}/guard_worker"
DST="${APP_DIR}/guard_worker"
[ -f "${SRC}/__main__.py" ] || fail "no guard_worker/__main__.py in ${REPO_DIR} — wrong checkout?"
if [ -d "$DST" ] && diff -rq --exclude=__pycache__ "$SRC" "$DST" >/dev/null 2>&1; then
  same "worker code ${DST#$R}"
else
  rm -rf "$DST" && mkdir -p "$DST"
  (cd "$SRC" && find . -name __pycache__ -prune -o -type f -print) | while read -r f; do
    mkdir -p "$DST/$(dirname "$f")"; cp "$SRC/$f" "$DST/$f"
  done
  did "worker code copied to ${DST#$R}"
fi
[ -d "${APP_DIR}/backend/app/guard" ] \
  || fail "${APP_DIR#$R}/backend/app is not deployed — the worker imports its shared modules from there. Run upgrade.sh first."

# ── 4. the worker's OWN venv ─────────────────────────────────────────────────
REQ="${DST}/requirements.txt"
STAMP="${VENV}/.requirements.sha256"
WANT="$(sha256sum "$REQ" | cut -d' ' -f1)"
if [ ! -x "${VENV}/bin/python" ]; then
  "$PYTHON" -m venv "$VENV" || fail "could not create ${VENV#$R}"
  did "created venv ${VENV#$R}"
fi
if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$WANT" ]; then
  same "guard venv packages (requirements unchanged)"
else
  # Wheels only: a source build of numpy/openvino on the NUC takes tens of minutes and can
  # fail halfway, leaving a venv that imports but does not work.
  "${VENV}/bin/pip" install -q --only-binary=:all: -r "$REQ" >>"$LOG_FILE" 2>&1 \
    || fail "pip install into ${VENV#$R} FAILED (see ${LOG_FILE#$R}). Most likely no wheel for this Python — §13."
  echo "$WANT" > "$STAMP"
  did "guard venv packages installed"
fi
"${VENV}/bin/python" -c "import openvino, numpy, PIL, paho.mqtt" >>"$LOG_FILE" 2>&1 \
  || fail "the guard venv does not import openvino/numpy/PIL/paho — not usable"

# ── 5. the backend venv stays clean ──────────────────────────────────────────
if [ -x "$BACKEND_PY" ]; then
  "$BACKEND_PY" -c "import importlib.util as u, sys; sys.exit(1 if u.find_spec('openvino') else 0)" \
    || fail "openvino is IMPORTABLE from the backend venv ${BACKEND_PY#$R} — it must never be there"
  same "backend venv has no openvino"
else
  fail "no backend venv at ${BACKEND_PY#$R} — cannot prove it is clean"
fi

# ── 6. identity: one instance id, the same in guard.env and the backend .env ──
[ -f "$BACKEND_ENV" ] || fail "no backend .env at ${BACKEND_ENV#$R}"
B_INST="$(env_get "$BACKEND_ENV" GUARD_INSTANCE_ID)"
G_INST="$(env_get "$ENV_FILE" GUARD_INSTANCE_ID)"
if [ -n "$B_INST" ] && [ -n "$G_INST" ] && [ "$B_INST" != "$G_INST" ]; then
  fail "GUARD_INSTANCE_ID differs: backend .env '${B_INST}', guard.env '${G_INST}' — the backend would ignore its own worker"
fi
INST="${G_INST:-${B_INST:-}}"
if [ -z "$INST" ]; then
  INST="guard-$(od -An -tx1 -N8 /dev/urandom | tr -d ' \n')"
  did "generated instance id ${INST}"
fi
# MARINA_ID: the backend's, or its default (config.py: "KRK"). Both sides must agree.
MARINA="$(env_get "$BACKEND_ENV" MARINA_ID)"; MARINA="${MARINA:-KRK}"

if [ -f "$ENV_FILE" ]; then
  same "guard.env exists (kept as is)"
  if [ -z "$G_INST" ]; then echo "GUARD_INSTANCE_ID=${INST}" >> "$ENV_FILE"; did "added GUARD_INSTANCE_ID to guard.env"; fi
  G_MARINA="$(env_get "$ENV_FILE" MARINA_ID)"
  [ "${G_MARINA:-KRK}" = "$MARINA" ] \
    || fail "MARINA_ID differs: backend '${MARINA}', guard.env '${G_MARINA}' — they would use different topics"
else
  umask 027
  cat > "$ENV_FILE" <<EOF
# cloud-iot-guard — written by install-guard.sh $(date -u +%Y-%m-%dT%H:%M:%SZ). Kept on later runs.
# Readable by root and the guard account only: GUARD_STREAM_URL carries the camera password.
MARINA_ID=${MARINA}
GUARD_INSTANCE_ID=${INST}
# Cabinet facts — set at first start (§13). The worker exits 2 while the URL is empty.
GUARD_CAMERA_ID=1
GUARD_PEDESTAL_ID=1
GUARD_STREAM_URL=
MQTT_BROKER_HOST=127.0.0.1
MQTT_BROKER_PORT=1883
GUARD_MODEL_DIR=/opt/cloud-iot/guard/models
GUARD_STORAGE_PATH=/var/lib/marina-guard/recordings
GUARD_NUM_THREADS=1
EOF
  umask 022
  did "wrote guard.env"
fi
$CHOWN "root:${GUARD_USER}" "$ENV_FILE" || fail "could not chown guard.env"
chmod 640 "$ENV_FILE"
if [ -z "$B_INST" ]; then
  echo "GUARD_INSTANCE_ID=${INST}" >> "$BACKEND_ENV"
  did "added GUARD_INSTANCE_ID to the backend .env (takes effect when the backend restarts)"
else
  same "backend .env GUARD_INSTANCE_ID"
fi

# ── 7. the unit — installed, NOT enabled, NOT started ────────────────────────
mkdir -p "$(dirname "$UNIT_DST")"
if [ -f "$UNIT_DST" ] && cmp -s "${SCRIPT_DIR}/cloud-iot-guard.service" "$UNIT_DST"; then
  same "unit ${UNIT_DST#$R}"
else
  cp "${SCRIPT_DIR}/cloud-iot-guard.service" "$UNIT_DST"
  $SYSTEMCTL daemon-reload || fail "systemctl daemon-reload failed"
  did "unit installed at ${UNIT_DST#$R} (not enabled, not started)"
fi

# ── 8. readiness — what the first start will need ────────────────────────────
READY=true
XML="$(ls "${MODEL_DIR}/yolov8n_openvino/"*.xml 2>/dev/null | head -n1 || true)"
if [ -n "$XML" ] && [ -s "${XML%.xml}.bin" ]; then
  say "model: present (${XML#$R})"
else
  say "MODEL MISSING: no yolov8n_openvino/*.xml with its .bin under ${MODEL_DIR#$R}"
  say "  export it with scripts/guard_export_model.sh and copy the IR there (§13)"
  READY=false
fi
# Presence and format only. The value is never printed: it holds the camera password.
URL_SET="$(sed -n 's/^GUARD_STREAM_URL=//p' "$ENV_FILE" | tail -n1 | tr -d '\r')"
if [ -z "$URL_SET" ]; then
  say "camera URL: not set yet — the first start (§13) sets it in guard.env"
elif [ "${URL_SET#rtsp://}" != "$URL_SET" ]; then
  say "camera URL: set (rtsp://…, value not shown)"
else
  say "camera URL: set, but does NOT start with rtsp:// (value not shown)"
fi
unset URL_SET

# ── 9. openvino-telemetry: removed only if openvino PROVABLY works without it ──
# It IS installed — pip pulls it in as a dependency of openvino (measured on cabinet 1,
# 2026-10-15: "Would install openvino-2026.4.1 openvino-telemetry-2025.2.0"). A constraint
# cannot exclude a dependency, and --no-deps would mean listing openvino's other dependencies
# by hand with pip no longer checking them. So: remove it, then the SMOKE TEST — the worker's
# own loading path, one inference on an empty frame (guard_smoke.py). If openvino needs the
# package after all, it goes back and the install continues: never leave openvino broken.
# Either way the barrier is the kernel filter in the unit (§13 F.3); this only takes away
# the thing it would have to stop. Which branch ran is printed as one TELEMETRY: line (§13).
SMOKE="${SCRIPT_DIR}/guard_smoke.py"
smoke() {
  "${VENV}/bin/python" "$SMOKE" "$MODEL_DIR" "$APP_DIR" 2>&1 | tee -a "$LOG_FILE"
  return "${PIPESTATUS[0]}"
}
TELE_VER="$("${VENV}/bin/python" -c "import importlib.metadata as m; print(m.version('openvino-telemetry'))" 2>/dev/null || true)"
if ! $READY; then
  say "TELEMETRY: NOT DECIDED — no model, so nothing proves openvino works without it; openvino-telemetry ${TELE_VER:-absent} left as it is. Run again once the model is in place."
elif [ -z "$TELE_VER" ]; then
  smoke || fail "SMOKE TEST FAILED (openvino-telemetry already absent) — this venv cannot load and run the model"
  same "TELEMETRY: REMOVED — openvino-telemetry absent, and the smoke test passes without it"
else
  "${VENV}/bin/pip" uninstall -y -q openvino-telemetry >>"$LOG_FILE" 2>&1     || fail "pip uninstall openvino-telemetry FAILED"
  if smoke; then
    did "TELEMETRY: REMOVED — openvino-telemetry ${TELE_VER} uninstalled; the smoke test loads the model and runs one inference without it"
  else
    say "smoke test FAILED without openvino-telemetry — putting it back"
    "${VENV}/bin/pip" install -q --only-binary=:all: "openvino-telemetry==${TELE_VER}" >>"$LOG_FILE" 2>&1       || fail "could not reinstall openvino-telemetry ${TELE_VER} — the guard venv now lacks a dependency openvino needs"
    smoke || fail "SMOKE TEST FAILED with openvino-telemetry back in place — openvino cannot load and run the model; not a telemetry problem"
    say "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    say "TELEMETRY: KEPT — openvino needs openvino-telemetry ${TELE_VER}: the smoke test failed without it and passed with it."
    say "  Egress protection is now the kernel filter ALONE — §13 F.3 must show it blocks."
    say "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
  fi
fi

echo ""
if $READY; then
  echo "GUARD INSTALLED — not enabled, not started. Start it as the separate §13 step." | tee -a "$LOG_FILE"
  exit 0
fi
echo "GUARD NOT READY — installed, but the model is missing. This is NOT a success." | tee -a "$LOG_FILE"
exit 3
