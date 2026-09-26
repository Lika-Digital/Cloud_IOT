#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  guard_export_model.sh — export stock COCO YOLOv8n to OpenVINO IR on the NUC
#
#  Guard Stage A.5. Run ONCE. Idempotent: does nothing if the IR already exists.
#
#  SAFETY: ultralytics + torch (~2 GB) are installed into a THROWAWAY venv under
#  /tmp and deleted afterwards. The production venv at
#  /opt/cloud-iot/backend/.venv is never touched — it only ever gets `openvino`
#  from requirements-vision.txt. This is deliberate: the NUC must keep running,
#  and a torch install inside the production venv is exactly the kind of change
#  that broke the 3.14 venv during the v3.19 deploy.
#
#  The exported weights are the STOCK COCO checkpoint (80 classes, class 0 =
#  person, class 8 = boat). Nothing here fine-tunes or retrains.
#
#  Usage:  sudo bash scripts/guard_export_model.sh [--force]
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
WORK_DIR="/tmp/guard-yolo-export.$$"
MIN_FREE_MB=4096
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

case "$MODELS_DIR" in
  /opt/cloud-iot/*) [ -d /opt/cloud-iot ] || die "/opt/cloud-iot not found — run this on the NUC (or set MODELS_DIR to a staging path)." ;;
esac

# ── Already done? ───────────────────────────────────────────────────────────
if [ -d "$OUT_DIR" ] && ls "$OUT_DIR"/*.xml >/dev/null 2>&1 && [ $FORCE -eq 0 ]; then
  ok "IR already present at $OUT_DIR — nothing to do (use --force to re-export)."
  ls -la "$OUT_DIR"
  exit 0
fi

# ── Disk guard: never fill the disk the backend is running on ───────────────
FREE_MB=$(df -Pm /tmp | awk 'NR==2{print $4}')
info "Free space on /tmp: ${FREE_MB} MB (need ≥ ${MIN_FREE_MB} MB for torch)"
[ "$FREE_MB" -ge "$MIN_FREE_MB" ] || die "Not enough free space on /tmp (${FREE_MB} MB < ${MIN_FREE_MB} MB). Free space or export on another machine and copy the IR."

cleanup() {
  if [ -d "$WORK_DIR" ]; then
    info "Removing throwaway venv $WORK_DIR"
    rm -rf "$WORK_DIR"
  fi
}
trap cleanup EXIT INT TERM

# ── Throwaway venv ──────────────────────────────────────────────────────────
info "Creating throwaway venv at $WORK_DIR (production venv untouched)"
python3 -m venv "$WORK_DIR" || die "venv creation failed"
PIP="${WORK_DIR}/bin/pip"
PY="${WORK_DIR}/bin/python"

"$PIP" install --quiet --upgrade pip || warn "pip self-upgrade failed — continuing"

# CPU-only torch keeps the download to a few hundred MB instead of pulling CUDA.
info "Installing ultralytics + CPU-only torch (this takes several minutes)"
"$PIP" install --quiet --no-cache-dir \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  ultralytics openvino || die "ultralytics/openvino install failed inside the throwaway venv"

# ── Export ──────────────────────────────────────────────────────────────────
info "Exporting stock COCO yolov8n.pt → OpenVINO IR"
cd "$WORK_DIR" || die "cd failed"
"$PY" - <<'PY' || die "export failed"
from ultralytics import YOLO
m = YOLO("yolov8n.pt")          # stock COCO weights, auto-downloaded
names = m.names
assert names[0] == "person", f"class 0 is {names[0]!r}, expected 'person'"
assert names[8] == "boat",   f"class 8 is {names[8]!r}, expected 'boat'"
print(f"[export] class map OK: {len(names)} classes, 0={names[0]!r}, 8={names[8]!r}")
p = m.export(format="openvino", dynamic=False, half=False)
print(f"[export] wrote {p}")
PY

SRC=""
for cand in "${WORK_DIR}/yolov8n_openvino_model" "${WORK_DIR}/yolov8n_openvino"; do
  [ -d "$cand" ] && SRC="$cand" && break
done
[ -n "$SRC" ] || die "could not locate the ultralytics export output directory"

install -d -m 0755 "$MODELS_DIR"
rm -rf "$OUT_DIR"
cp -r "$SRC" "$OUT_DIR" || die "copy to $OUT_DIR failed"

# Backend runs as the cloud-iot user; make sure it can read the IR.
case "$OUT_DIR" in
  /opt/cloud-iot/*) chown -R cloud-iot:cloud-iot "$OUT_DIR" 2>/dev/null || warn "chown skipped (not root?)" ;;
esac
chmod -R a+rX "$OUT_DIR"

ok "IR installed at $OUT_DIR"
ls -la "$OUT_DIR"
echo ""
info "Class map recorded in the IR metadata:"
grep -o 'names:.\{0,120\}' "${OUT_DIR}/metadata.yaml" 2>/dev/null || warn "metadata.yaml not found"
echo ""
ok "Done. Next steps:"
echo "     (staging run? use scripts/guard_measure.sh — it needs NO production changes)"
echo "     1. /opt/cloud-iot/backend/.venv/bin/pip install -r /opt/cloud-iot/backend/requirements-vision.txt"
echo "     2. add USE_ML_MODELS=true to /opt/cloud-iot/backend/.env"
echo "     3. python3 scripts/guard_detect_probe.py --classmap      # verify"
echo "     4. sudo systemctl restart cloud-iot-backend"
