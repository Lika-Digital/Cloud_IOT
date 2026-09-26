#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  guard_measure.sh — run the Stage A.5 measurement with ZERO production changes
#
#  The classmap and clip probes do NOT need openvino in the production venv:
#  app/__init__.py and app/services/__init__.py are both empty and
#  yolo_openvino.py imports only stdlib at module level (numpy/PIL/openvino are
#  lazy). So the whole measurement runs in isolation:
#
#    * model IR      → $GUARD_STAGING/models   (never /opt/cloud-iot)
#    * python deps   → $GUARD_STAGING/venv     (openvino + numpy + Pillow)
#    * production venv, /opt/cloud-iot, .env, USE_ML_MODELS : ALL UNTOUCHED
#
#  numpy is pinned to whatever the PRODUCTION venv actually has (read at runtime,
#  not hardcoded) so measurements match production. Installs use
#  --only-binary=:all: so a missing wheel fails instantly instead of starting a
#  source build — on Python 3.14 an old numpy pin has no wheel and would other-
#  wise try to compile.
#
#  The only shared resources touched are read-only: pedestal.db (opened
#  mode=ro, to find the camera URL) and the camera's RTSP stream.
#
#  USAGE
#    bash scripts/guard_measure.sh setup                  # one-time: venv + IR
#    bash scripts/guard_measure.sh classmap               # on-disk class map proof
#    bash scripts/guard_measure.sh record 30 /tmp/day.mp4 # record a real-angle clip
#    bash scripts/guard_measure.sh probe --clip /tmp/day.mp4 --expect person
#    bash scripts/guard_measure.sh tests                  # decode+rule tests on this venv
#    bash scripts/guard_measure.sh clean                  # remove the staging tree
#
#  ENV OVERRIDES
#    GUARD_STAGING=/tmp/guard-staging   # default $HOME/guard-staging (see note below)
#    GUARD_NUMPY=2.4.6                  # override the auto-detected numpy version
#    GUARD_IR_SRC=/path/to/yolov8n_openvino
#                                       # import a pre-exported IR and SKIP the
#                                       # ultralytics/torch export entirely (~4 GB saved)
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info() { echo -e "${CYAN}[measure]${NC} $*"; }
ok()   { echo -e "${GREEN}[ ok ]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*"; }
die()  { echo -e "${RED}[fail]${NC} $*" >&2; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# $HOME, not /tmp: Ubuntu mounts /tmp as tmpfs on many installs, and the one-time
# IR export needs ~4 GB — which would be RAM on a 14 Gi box. Override if you want
# reboot-clean behaviour and know /tmp is disk-backed.
STAGING="${GUARD_STAGING:-$HOME/guard-staging}"
VENV="${STAGING}/venv"
MODELS="${STAGING}/models"
PY="${VENV}/bin/python"
PROD_PY="/opt/cloud-iot/backend/.venv/bin/python"

CMD="${1:-}"; shift || true

need_venv() {
  [ -x "$PY" ] || die "staging venv missing — run: bash scripts/guard_measure.sh setup"
}

# Match production's numpy exactly. Hardcoding a version is how this script
# previously ended up pinning 2.1.2, which has NO cp314 wheel and would have
# tried to source-build on the Python 3.14 NUC.
resolve_numpy() {
  if [ -n "${GUARD_NUMPY:-}" ]; then
    echo "$GUARD_NUMPY"; return 0
  fi
  if [ -x "$PROD_PY" ]; then
    local v
    v="$("$PROD_PY" -c 'import numpy; print(numpy.__version__)' 2>/dev/null)"
    if [ -n "$v" ]; then echo "$v"; return 0; fi
  fi
  return 1
}

case "$CMD" in

setup)
  info "Staging tree : $STAGING"
  info "Repo         : $REPO_DIR"
  echo ""
  warn "Nothing under /opt/cloud-iot is written by this script."
  echo ""

  # ── numpy version must match production, and must have a wheel ────────────
  if NUMPY_VER="$(resolve_numpy)"; then
    if [ -n "${GUARD_NUMPY:-}" ]; then
      info "numpy $NUMPY_VER (from GUARD_NUMPY override)"
    else
      ok "numpy $NUMPY_VER detected from the production venv — staging will match"
    fi
  else
    NUMPY_VER=""
    warn "Could not read numpy from $PROD_PY."
    warn "Falling back to an UNPINNED numpy; note the resolved version in the report"
    warn "or re-run with GUARD_NUMPY=<version> to match production exactly."
  fi

  PY_TAG="$(python3 -c 'import sys; print(f"cp{sys.version_info.major}{sys.version_info.minor}")' 2>/dev/null || echo unknown)"
  info "Interpreter  : $(python3 -V 2>&1) (${PY_TAG})"

  FREE_MB=$(df -Pm "$HOME" | awk 'NR==2{print $4}')
  info "Free space in \$HOME: ${FREE_MB} MB"
  [ "${FREE_MB:-0}" -ge 1024 ] || die "need >=1 GB free in \$HOME for the measurement venv"

  mkdir -p "$STAGING" || die "cannot create $STAGING"
  if [ ! -x "$PY" ]; then
    info "Creating measurement venv at $VENV"
    python3 -m venv "$VENV" || die "venv creation failed"
    "${VENV}/bin/pip" install --quiet --upgrade pip || warn "pip self-upgrade failed"
  else
    ok "venv already exists"
  fi

  # --only-binary=:all: is the wheel-existence check AND the install in one step:
  # if no matching wheel exists for this interpreter, pip fails immediately rather
  # than falling back to a source build.
  NUMPY_SPEC="numpy"
  [ -n "$NUMPY_VER" ] && NUMPY_SPEC="numpy==${NUMPY_VER}"
  info "Installing openvino + ${NUMPY_SPEC} + Pillow (wheels only, no source builds)"
  if ! "${VENV}/bin/pip" install --no-cache-dir --only-binary=:all: \
        openvino "$NUMPY_SPEC" Pillow; then
    echo ""
    die "install failed. If it names ${NUMPY_SPEC}, there is no ${PY_TAG} wheel for that
     version — check what production really has:
       $PROD_PY -c 'import numpy; print(numpy.__version__)'
     then re-run with GUARD_NUMPY=<that version>. Do NOT drop --only-binary:
     a source build of numpy on this box is exactly what we are avoiding."
  fi

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

  if [ -n "$NUMPY_VER" ]; then
    GOT="$("$PY" -c 'import numpy; print(numpy.__version__)' 2>/dev/null)"
    if [ "$GOT" = "$NUMPY_VER" ]; then
      ok "staging numpy matches production ($GOT)"
    else
      warn "staging numpy $GOT != production $NUMPY_VER — report this with the numbers"
    fi
  fi

  # ── the IR ────────────────────────────────────────────────────────────────
  echo ""
  if [ -d "${MODELS}/yolov8n_openvino" ] && ls "${MODELS}/yolov8n_openvino"/*.xml >/dev/null 2>&1; then
    ok "IR already staged at ${MODELS}/yolov8n_openvino — export SKIPPED (no torch needed)"
  elif [ -n "${GUARD_IR_SRC:-}" ]; then
    [ -d "$GUARD_IR_SRC" ] || die "GUARD_IR_SRC=$GUARD_IR_SRC is not a directory"
    ls "$GUARD_IR_SRC"/*.xml >/dev/null 2>&1 || die "no .xml in $GUARD_IR_SRC — not an OpenVINO IR"
    info "Importing a pre-exported IR from $GUARD_IR_SRC (skipping ultralytics/torch)"
    mkdir -p "$MODELS"
    cp -r "$GUARD_IR_SRC" "${MODELS}/yolov8n_openvino" || die "copy failed"
    ok "IR imported — no torch download required"
  else
    warn "No IR staged yet. The export needs ultralytics + CPU torch (~4 GB, ONE TIME)."
    warn "To skip it, export on another 64-bit machine and re-run with"
    warn "  GUARD_IR_SRC=/path/to/yolov8n_openvino  (the IR itself is only ~12 MB)"
    echo ""
    info "Exporting now into staging (throwaway venv; production venv untouched)"
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
  SECS="${1:-30}"; OUT="${2:-/tmp/guard_clip.mp4}"
  "$PY" "${REPO_DIR}/scripts/guard_detect_probe.py" \
    --record "$SECS" --out "$OUT" --model-dir "$MODELS"
  ;;

probe)
  need_venv
  "$PY" "${REPO_DIR}/scripts/guard_detect_probe.py" --model-dir "$MODELS" "$@"
  ;;

tests)
  # Runs the pure decode + alarm-rule tests against the measurement venv's numpy
  # (matched to production), so the logic is validated on the same numpy the NUC
  # runs. pytest is installed here and NOT in production.
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
  sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 1
  ;;
esac
