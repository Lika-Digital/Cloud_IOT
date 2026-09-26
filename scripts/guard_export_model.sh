#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  guard_export_model.sh — export stock COCO YOLOv8n to OpenVINO IR
#
#  Guard Stage A.5. Run ONCE. Idempotent: does nothing if the IR already exists.
#
#  The exported weights are the STOCK COCO checkpoint (80 classes, class 0 =
#  person, class 8 = boat). Nothing here fine-tunes or retrains. The script
#  asserts that class map BEFORE writing anything.
#
#  TWO EXPORT ROUTES
#    --docker  (DEFAULT on Python 3.13+)  Runs the export inside a python:3.12
#              container. Nothing is installed on the host at all. This exists
#              because the NUC runs Python 3.14 and torch may have no cp314
#              wheel — inside the container we control the interpreter version,
#              so the question disappears.
#    --venv    Throwaway venv under /tmp, deleted afterwards. Uses
#              --only-binary=:all: so a missing wheel fails in seconds instead
#              of starting a source build of torch (hours, then likely failure).
#
#  The production venv at /opt/cloud-iot/backend/.venv is NEVER touched by
#  either route.
#
#  USAGE
#    sudo bash scripts/guard_export_model.sh                 # auto-pick route
#    sudo bash scripts/guard_export_model.sh --docker
#    sudo bash scripts/guard_export_model.sh --venv
#    MODELS_DIR=$HOME/guard-staging/models bash scripts/guard_export_model.sh
#    sudo bash scripts/guard_export_model.sh --force         # re-export
# ─────────────────────────────────────────────────────────────────────────────
set -uo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[export]${NC} $*"; }
ok()    { echo -e "${GREEN}[ ok ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC} $*"; }
die()   { echo -e "${RED}[fail]${NC} $*" >&2; exit 1; }

# Where the IR lands. Override to keep the measurement run entirely out of
# production, e.g. MODELS_DIR=$HOME/guard-staging/models (what guard_measure.sh does).
MODELS_DIR="${MODELS_DIR:-/opt/cloud-iot/backend/models}"
OUT_DIR="${MODELS_DIR}/yolov8n_openvino"
WORK_DIR="${GUARD_EXPORT_TMPDIR:-/tmp}/guard-yolo-export.$$"
MIN_FREE_MB=4096
DOCKER_IMAGE="python:3.12-slim"

FORCE=0; ROUTE=""
for arg in "$@"; do
  case "$arg" in
    --force)  FORCE=1 ;;
    --docker) ROUTE="docker" ;;
    --venv)   ROUTE="venv" ;;
    *) die "unknown argument: $arg" ;;
  esac
done

case "$MODELS_DIR" in
  /opt/cloud-iot/*) [ -d /opt/cloud-iot ] || die "/opt/cloud-iot not found — run this on the NUC (or set MODELS_DIR to a staging path)." ;;
esac

# ── Already done? ───────────────────────────────────────────────────────────
if [ -d "$OUT_DIR" ] && ls "$OUT_DIR"/*.xml >/dev/null 2>&1 && [ $FORCE -eq 0 ]; then
  ok "IR already present at $OUT_DIR — nothing to do (use --force to re-export)."
  ls -la "$OUT_DIR"
  exit 0
fi

# ── Pick a route ────────────────────────────────────────────────────────────
PYV="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "?")"
# /tmp on Ubuntu is frequently tmpfs (RAM). A 4 GB torch install there is 4 GB of RAM
# on a 14 Gi box — the precise thing the Docker route exists to avoid. Detect it.
TMP_FS="$(df -PT /tmp 2>/dev/null | awk 'NR==2{print $2}')"
TMP_IS_RAM=0
case "$TMP_FS" in tmpfs|ramfs) TMP_IS_RAM=1 ;; esac

DOCKER_USABLE=0
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  DOCKER_USABLE=1
fi

if [ -z "$ROUTE" ]; then
  if [ "$DOCKER_USABLE" = "1" ]; then
    ROUTE="docker"
    info "Route auto-selected: DOCKER (docker present and daemon reachable)."
    info "Host Python is ${PYV}; the container pins 3.12, so the torch cp${PYV/./} wheel"
    info "question does not arise and nothing is installed on the host."
  else
    ROUTE="venv"
    if command -v docker >/dev/null 2>&1; then
      warn "docker binary found but the daemon is NOT reachable as this user."
      warn "Re-run with sudo to get the container route:  sudo bash $0 --docker"
    else
      warn "docker not found on PATH."
    fi
    info "Route auto-selected: VENV (throwaway /tmp venv)."
  fi
else
  info "Route forced by argument: ${ROUTE}"
  if [ "$ROUTE" = "docker" ] && [ "$DOCKER_USABLE" != "1" ]; then
    die "--docker requested but the Docker daemon is not reachable (try sudo)."
  fi
fi

if [ "$ROUTE" = "venv" ] && [ "$TMP_IS_RAM" = "1" ]; then
  echo ""
  warn "/tmp is ${TMP_FS} — RAM-backed. The venv route would put ~4 GB of torch into RAM."
  if [ "$DOCKER_USABLE" = "1" ]; then
    die "Refusing. Docker IS usable here — re-run without --venv, or with --docker."
  fi
  warn "Docker is not usable, so there is no better route available."
  warn "Set GUARD_EXPORT_TMPDIR=/var/tmp (disk-backed) to avoid RAM, or export on"
  warn "another machine and pass GUARD_IR_SRC=... to guard_measure.sh."
  if [ "${GUARD_ALLOW_TMPFS:-0}" != "1" ]; then
    die "Refusing to fill RAM. Re-run with GUARD_ALLOW_TMPFS=1 only if you accept that."
  fi
  warn "GUARD_ALLOW_TMPFS=1 set — proceeding into RAM-backed /tmp."
fi

info "Route: $ROUTE   →   $OUT_DIR"

# The export program, shared by both routes. Asserts the class map before export.
EXPORT_PY='
import os, shutil, sys


def main() -> int:
    from ultralytics import YOLO
    m = YOLO("yolov8n.pt")          # stock COCO weights, auto-downloaded
    names = m.names
    assert names[0] == "person", f"class 0 is {names[0]!r}, expected person"
    assert names[8] == "boat",   f"class 8 is {names[8]!r}, expected boat"
    print(f"[export] class map OK: {len(names)} classes, 0={names[0]!r}, 8={names[8]!r}")
    p = m.export(format="openvino", dynamic=False, half=False)
    dest = os.environ["EXPORT_DEST"]
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(str(p), dest)
    print(f"[export] wrote {dest}")
    return 0


# Run as a FILE with this guard, never `python -c`. Python 3.14 defaults to the
# forkserver start method, and torch/ultralytics spawn workers; a forkserver child
# re-imports __main__, which for `-c` code is <stdin> and produces a wall of
# alarming-but-harmless tracebacks before the export still succeeds.
if __name__ == "__main__":
    sys.exit(main())
'

install -d -m 0755 "$MODELS_DIR" || die "cannot create $MODELS_DIR"

# ── Route 1: Docker ─────────────────────────────────────────────────────────
if [ "$ROUTE" = "docker" ]; then
  command -v docker >/dev/null 2>&1 || die "docker not found but --docker requested"
  docker info >/dev/null 2>&1 || die "cannot talk to the Docker daemon (need sudo, or add your user to the docker group)"

  info "Pulling $DOCKER_IMAGE (small; the heavy deps stay inside the container)"
  docker pull -q "$DOCKER_IMAGE" >/dev/null 2>&1 || warn "pull failed — will use a cached image if present"

  info "Exporting inside the container (nothing is installed on the host)"
  # libgl1/libglib2.0-0: ultralytics pulls opencv-python, which needs libGL.
  docker run --rm \
    -v "${MODELS_DIR}:/out" \
    -e EXPORT_DEST=/out/yolov8n_openvino \
    -e EXPORT_PY="$EXPORT_PY" \
    "$DOCKER_IMAGE" \
    bash -c '
      set -e
      apt-get update -qq >/dev/null
      apt-get install -y -qq --no-install-recommends libgl1 libglib2.0-0 >/dev/null
      pip install --quiet --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        ultralytics openvino
      cd /tmp
      printf '%s' "$EXPORT_PY" > /tmp/guard_export.py
      python /tmp/guard_export.py
    ' || die "container export failed. Re-run with --venv, or export on another machine and use GUARD_IR_SRC=..."

  [ -d "$OUT_DIR" ] || die "container reported success but $OUT_DIR is missing"

# ── Route 2: throwaway venv ─────────────────────────────────────────────────
else
  FREE_MB=$(df -Pm "$(dirname "$WORK_DIR")" | awk 'NR==2{print $4}')
  info "Free space on $(dirname "$WORK_DIR"): ${FREE_MB} MB (need >= ${MIN_FREE_MB} MB for torch)"
  [ "${FREE_MB:-0}" -ge "$MIN_FREE_MB" ] || die "Not enough free space on /tmp (${FREE_MB} MB < ${MIN_FREE_MB} MB). Use --docker, or export elsewhere and use GUARD_IR_SRC=..."

  cleanup() {
    if [ -d "$WORK_DIR" ]; then
      info "Removing throwaway venv $WORK_DIR"
      rm -rf "$WORK_DIR"
    fi
  }
  trap cleanup EXIT INT TERM

  info "Creating throwaway venv at $WORK_DIR (production venv untouched)"
  python3 -m venv "$WORK_DIR" || die "venv creation failed"
  PIP="${WORK_DIR}/bin/pip"
  PY="${WORK_DIR}/bin/python"
  "$PIP" install --quiet --upgrade pip || warn "pip self-upgrade failed — continuing"

  # --only-binary=:all: is the whole point here: without it, a missing cp314 torch
  # wheel sends pip into a source build that would run for hours on this CPU.
  info "Installing ultralytics + CPU-only torch (wheels only, no source builds)"
  if ! "$PIP" install --no-cache-dir --only-binary=:all: \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        ultralytics openvino; then
    echo ""
    die "install failed — most likely no torch wheel for Python ${PYV}.
     Options, in order of preference:
       1. sudo bash scripts/guard_export_model.sh --docker
       2. export on any machine with Python 3.11-3.13, copy the ~12 MB IR over, then:
          GUARD_IR_SRC=/path/to/yolov8n_openvino bash scripts/guard_measure.sh setup
     Do NOT drop --only-binary to force a source build."
  fi

  info "Exporting stock COCO yolov8n.pt → OpenVINO IR"
  cd "$WORK_DIR" || die "cd failed"
  printf '%s' "$EXPORT_PY" > "${WORK_DIR}/guard_export.py"
  EXPORT_DEST="$OUT_DIR" "$PY" "${WORK_DIR}/guard_export.py" || die "export failed"
fi

# ── Permissions + verification ──────────────────────────────────────────────
case "$OUT_DIR" in
  /opt/cloud-iot/*) chown -R cloud-iot:cloud-iot "$OUT_DIR" 2>/dev/null || warn "chown skipped (not root?)" ;;
esac
chmod -R a+rX "$OUT_DIR" 2>/dev/null || warn "chmod skipped"

ls "$OUT_DIR"/*.xml >/dev/null 2>&1 || die "no .xml in $OUT_DIR — export did not produce an IR"

ok "IR installed at $OUT_DIR"
ls -la "$OUT_DIR"
echo ""
info "Class map recorded in the IR metadata:"
grep -o 'names:.\{0,120\}' "${OUT_DIR}/metadata.yaml" 2>/dev/null || warn "metadata.yaml not found"
echo ""
ok "Done. Next:"
echo "     bash scripts/guard_measure.sh classmap      # verify the class map on disk"
