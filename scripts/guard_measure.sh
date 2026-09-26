#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  guard_measure.sh — run the Stage A.5 measurement with ZERO production changes
#
#  Answers the approval question directly: the classmap and clip probes do NOT
#  need openvino in the production venv. This script proves it by doing the whole
#  measurement in isolation:
#
#    * model IR      → $HOME/guard-staging/models   (never /opt/cloud-iot)
#    * python deps   → $HOME/guard-staging/venv     (openvino + numpy + Pillow)
#    * production venv, /opt/cloud-iot, .env, USE_ML_MODELS : ALL UNTOUCHED
#
#  numpy is pinned to 2.1.2 to match backend/requirements.txt, so the numbers
#  come from the same numpy production runs.
#
#  The only shared resources touched are read-only: pedestal.db (opened
#  mode=ro, to find the camera URL) and the camera's RTSP stream.
#
#  USAGE
#    bash scripts/guard_measure.sh setup                  # one-time: venv + IR
#    bash scripts/guard_measure.sh classmap               # on-disk class map proof
#    bash scripts/guard_measure.sh record 20 /tmp/day.mp4 # record a real-angle clip
#    bash scripts/guard_measure.sh probe --clip /tmp/day.mp4 --expect person
#    bash scripts/guard_measure.sh tests                  # decode+rule tests on this venv
#    bash scripts/guard_measure.sh clean                  # remove the staging tree
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${CYAN}[measure]${NC} $*"; }
ok()   { echo -e "${GREEN}[ ok ]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
die()  { echo -e "${RED}[fail]${NC} $*" >&2; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGING="${GUARD_STAGING:-$HOME/guard-staging}"
VENV="${STAGING}/venv"
MODELS="${STAGING}/models"
PY="${VENV}/bin/python"
NUMPY_PIN="numpy==2.1.2"    # match backend/requirements.txt

CMD="${1:-}"; shift || true

need_venv() {
  [ -x "$PY" ] || die "staging venv missing — run: bash scripts/guard_measure.sh setup"
}

case "$CMD" in

setup)
  info "Staging tree : $STAGING"
  info "Repo         : $REPO_DIR"
  echo ""
  warn "Nothing under /opt/cloud-iot is written by this script."
  echo ""

  FREE_MB=$(df -Pm "$HOME" | awk 'NR==2{print $4}')
  info "Free space in \$HOME: ${FREE_MB} MB"
  [ "$FREE_MB" -ge 1024 ] || die "need >=1 GB free in \$HOME for the measurement venv"

  mkdir -p "$STAGING" || die "cannot create $STAGING"
  if [ ! -x "$PY" ]; then
    info "Creating measurement venv at $VENV"
    python3 -m venv "$VENV" || die "venv creation failed"
    "${VENV}/bin/pip" install --quiet --upgrade pip || warn "pip self-upgrade failed"
  else
    ok "venv already exists"
  fi

  info "Installing openvino + $NUMPY_PIN + Pillow (NOT into the production venv)"
  "${VENV}/bin/pip" install --quiet --no-cache-dir openvino "$NUMPY_PIN" Pillow \
    || die "install failed inside the measurement venv"

  echo ""
  info "Versions in the measurement venv:"
  "$PY" - <<'PYEOF'
import importlib
for m in ("openvino", "numpy", "PIL"):
    try:
        mod = importlib.import_module(m)
        print(f"  {m:10s} {getattr(mod, '__version__', '?')}")
    except Exception as exc:
        print(f"  {m:10s} MISSING ({exc})")
PYEOF

  echo ""
  if [ -d "${MODELS}/yolov8n_openvino" ] && ls "${MODELS}/yolov8n_openvino"/*.xml >/dev/null 2>&1; then
    ok "IR already staged at ${MODELS}/yolov8n_openvino"
  else
    info "Exporting the IR into staging (throwaway venv for ultralytics/torch)"
    MODELS_DIR="$MODELS" bash "${REPO_DIR}/scripts/guard_export_model.sh" \
      || die "IR export failed"
  fi

  echo ""
  ok "Setup complete. Production untouched. Next:"
  echo "     bash scripts/guard_measure.sh classmap"
  ;;

classmap)
  need_venv
  "$PY" "${REPO_DIR}/scripts/guard_detect_probe.py" --classmap --model-dir "$MODELS"
  ;;

record)
  need_venv
  SECS="${1:-20}"; OUT="${2:-/tmp/guard_clip.mp4}"
  "$PY" "${REPO_DIR}/scripts/guard_detect_probe.py" \
    --record "$SECS" --out "$OUT" --model-dir "$MODELS"
  ;;

probe)
  need_venv
  "$PY" "${REPO_DIR}/scripts/guard_detect_probe.py" --model-dir "$MODELS" "$@"
  ;;

tests)
  # Runs the pure decode + alarm-rule tests against the measurement venv's numpy
  # (2.1.2 — the production pin), so the logic is validated on the same numpy the
  # NUC runs. Needs pytest, which is installed here and NOT in production.
  need_venv
  "${VENV}/bin/pip" install --quiet pytest || die "pytest install failed"
  cd "$REPO_DIR" || die "cd failed"
  "${VENV}/bin/python" -m pytest \
    tests/backend/test_yolo_multiclass.py tests/backend/test_guard_alarm_rule.py \
    -q --no-header -p no:cacheprovider
  ;;

clean)
  info "Removing $STAGING"
  rm -rf "$STAGING" && ok "removed" || die "removal failed"
  ;;

*)
  sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 1
  ;;
esac
