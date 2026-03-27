#!/usr/bin/env bash
# ============================================================================
# Cloud IoT NUC v2.0 — SELF-CONTAINED Bootable ISO Builder
#
# Everything is bundled inside the ISO. No internet required on the NUC.
#
# What this script does:
#   1. Prepares app: removes simulator + PDF customer features, patches WAL
#   2. Builds the React frontend via Docker (no local Node.js needed)
#   3. Downloads Python wheels via Docker (offline pip install on NUC)
#   4. Pulls and saves Docker images (mosquitto) as .tar files
#   5. Downloads all required Debian .deb packages via Docker
#   6. Creates a local apt repository inside the ISO
#   7. Downloads Debian 12 netinstall ISO, injects everything, rebuilds
#
# Build machine requirements:
#   sudo apt install xorriso wget dpkg-dev   # for ISO building
#   + Docker running                          # for everything else
#
# Usage:
#   chmod +x build_iso.sh
#   ./build_iso.sh
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORK_DIR="${SCRIPT_DIR}/.build_work"
ISO_EXTRACT="${WORK_DIR}/iso_contents"
OUTPUT_ISO="${SCRIPT_DIR}/cloud-iot-nuc-v2.0.iso"

DEBIAN_VERSION="12.9.0"
DEBIAN_ARCH="amd64"
DEBIAN_ISO_URL="https://cdimage.debian.org/debian-cd/${DEBIAN_VERSION}/${DEBIAN_ARCH}/iso-cd/debian-${DEBIAN_VERSION}-${DEBIAN_ARCH}-netinst.iso"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; WHITE='\033[1;37m'; NC='\033[0m'; BOLD='\033[1m'
info()  { echo -e "${GREEN}[✔]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✘]${NC} $*"; exit 1; }
phase() { echo -e "\n${CYAN}${BOLD}══ $* ══${NC}"; }

# ── Dependency check ─────────────────────────────────────────────────────────
phase "Checking build dependencies"

for cmd in docker xorriso wget; do
  command -v "$cmd" &>/dev/null || error "Missing: $cmd   (sudo apt install xorriso wget; and ensure Docker is running)"
done

MBR_BIN=""
for p in /usr/lib/ISOLINUX/isohdpfx.bin /usr/lib/syslinux/mbr/isohdpfx.bin; do
  [ -f "$p" ] && MBR_BIN="$p" && break
done
if [ -z "$MBR_BIN" ]; then
  sudo apt install -y isolinux dpkg-dev
  for p in /usr/lib/ISOLINUX/isohdpfx.bin /usr/lib/syslinux/mbr/isohdpfx.bin; do
    [ -f "$p" ] && MBR_BIN="$p" && break
  done
fi
[ -z "$MBR_BIN" ] && error "isohdpfx.bin not found. Install: sudo apt install isolinux"
info "Build environment OK"

mkdir -p "${WORK_DIR}"

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Prepare application (remove simulator, PDF, add WAL mode)
# ═══════════════════════════════════════════════════════════════════════════════
phase "Preparing application"
APP_WORK="${WORK_DIR}/app"
rm -rf "$APP_WORK"
mkdir -p "$APP_WORK"

# Copy required parts of the repo (exclude dev artifacts)
for d in backend frontend mosquitto; do
  [ -d "${REPO_ROOT}/${d}" ] && cp -r "${REPO_ROOT}/${d}" "${APP_WORK}/${d}"
done
[ -f "${REPO_ROOT}/docker-compose.yml" ] && cp "${REPO_ROOT}/docker-compose.yml" "${APP_WORK}/"

# ── Remove simulator ──────────────────────────────────────────────────────────
rm -rf "${APP_WORK}/backend/app/services/simulator_manager.py" 2>/dev/null || true
info "Simulator removed"

# ── Stub PDF service (remove reportlab dependency) ───────────────────────────
cat > "${APP_WORK}/backend/app/services/pdf_service.py" << 'PDFEOF'
"""
PDF service — disabled in NUC deployment.
Customer PDF downloads are not available on the pedestal controller.
"""
from fastapi import HTTPException

def make_contract_pdf(*args, **kwargs) -> bytes:
    raise HTTPException(status_code=501, detail="PDF generation not available in NUC deployment.")

def make_invoice_pdf(*args, **kwargs) -> bytes:
    raise HTTPException(status_code=501, detail="PDF generation not available in NUC deployment.")
PDFEOF

# Remove reportlab from requirements (not needed)
sed -i '/reportlab/d' "${APP_WORK}/backend/requirements.txt"
info "PDF customer features stubbed, reportlab removed from requirements"

# ── Add SQLite WAL mode to backend service startup ────────────────────────────
# We inject a pragma helper that database.py can import
cat > "${APP_WORK}/backend/app/wal_pragma.py" << 'WALEOF'
"""
SQLite WAL mode configuration for NUC deployment.
Improves concurrent read performance and crash safety.
Import this module early in the application startup.
"""
import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

WAL_DATABASES = [
    os.path.join(os.path.dirname(__file__), '..', 'pedestal.db'),
    os.path.join(os.path.dirname(__file__), '..', 'data', 'users.db'),
]

def apply_wal_mode() -> None:
    """Set WAL mode and NORMAL sync on all SQLite databases."""
    for db_path in WAL_DATABASES:
        db_path = os.path.normpath(db_path)
        if not os.path.exists(db_path):
            continue
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-32000")   # 32 MB page cache
            conn.execute("PRAGMA wal_autocheckpoint=1000")
            conn.commit()
            conn.close()
            logger.info("WAL mode enabled: %s", db_path)
        except Exception as exc:
            logger.warning("Could not set WAL mode on %s: %s", db_path, exc)
WALEOF

# Patch main.py to call apply_wal_mode() at startup
MAIN_PY="${APP_WORK}/backend/app/main.py"
if [ -f "$MAIN_PY" ]; then
  # Add import if not already present
  if ! grep -q "wal_pragma" "$MAIN_PY"; then
    sed -i '1s/^/from app.wal_pragma import apply_wal_mode\n/' "$MAIN_PY"
    # Add call inside lifespan or startup event
    # Find @asynccontextmanager or @app.on_event("startup") and inject
    python3 - <<PYEOF
import re, sys

with open("${MAIN_PY}", 'r') as f:
    content = f.read()

# Look for the lifespan async generator — inject apply_wal_mode() early
# Pattern: async def lifespan(... followed by first 'yield' or first await
if 'async def lifespan' in content:
    content = re.sub(
        r'(async def lifespan\([^)]*\)[^:]*:\n)',
        r'\1    apply_wal_mode()  # NUC: enable WAL mode on startup\n',
        content, count=1
    )
elif '@app.on_event("startup")' in content:
    content = content.replace(
        '@app.on_event("startup")',
        '@app.on_event("startup")\nasync def _wal_startup():\n    apply_wal_mode()\n\n@app.on_event("startup")',
        1
    )
else:
    # Fallback: append a startup call at module level (after app creation)
    content = content.replace(
        'app = FastAPI(',
        'apply_wal_mode()  # NUC: enable WAL mode\napp = FastAPI(',
        1
    )

with open("${MAIN_PY}", 'w') as f:
    f.write(content)
print("main.py patched for WAL mode")
PYEOF
  fi
fi
info "SQLite WAL mode injection complete"

# ── Remove dev/build artifacts that bloat the ISO ────────────────────────────
find "${APP_WORK}/backend" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "${APP_WORK}/backend" -name "*.pyc" -delete 2>/dev/null || true
rm -rf "${APP_WORK}/backend/.venv" 2>/dev/null || true
rm -f  "${APP_WORK}/backend/pedestal.db" 2>/dev/null || true
rm -f  "${APP_WORK}/backend/data/users.db" 2>/dev/null || true
rm -rf "${APP_WORK}/frontend/node_modules" 2>/dev/null || true
rm -rf "${APP_WORK}/frontend/dist" 2>/dev/null || true

# ── Set Mosquitto persistence config ─────────────────────────────────────────
mkdir -p "${APP_WORK}/mosquitto/config"
cp "${SCRIPT_DIR}/overlay/cloud-iot-setup/mosquitto.conf" \
   "${APP_WORK}/mosquitto/config/mosquitto.conf"
info "Mosquitto persistence config copied"

# ── Override docker-compose to use persisted mosquitto data ──────────────────
cat > "${APP_WORK}/docker-compose.yml" << 'DCEOF'
services:
  mosquitto:
    image: eclipse-mosquitto:2.0
    container_name: pedestal-mqtt-broker
    ports:
      - "1883:1883"
      - "9001:9001"
    volumes:
      - ./mosquitto/config:/mosquitto/config:ro
      - mosquitto-data:/mosquitto/data
      - mosquitto-log:/mosquitto/log
    restart: unless-stopped

volumes:
  mosquitto-data:
  mosquitto-log:
DCEOF

info "App prepared at ${APP_WORK}"

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Build frontend inside Docker (no local Node.js needed)
# ═══════════════════════════════════════════════════════════════════════════════
phase "Building React frontend (via Docker)"

docker run --rm \
  -v "${APP_WORK}/frontend:/app" \
  -w /app \
  node:20-slim \
  sh -c "npm ci --prefer-offline --no-audit --no-fund && npm run build"

info "Frontend built: ${APP_WORK}/frontend/dist/"

# Remove frontend source files — only dist/ is needed on NUC
# Keep src/ for reference but remove node_modules (already excluded above)
# Keep package.json for version reference
find "${APP_WORK}/frontend" -maxdepth 1 -type d \
  ! -name "dist" ! -name "frontend" ! -name "public" \
  -exec rm -rf {} + 2>/dev/null || true

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Download Python wheels (offline pip install on NUC)
# ═══════════════════════════════════════════════════════════════════════════════
phase "Downloading Python wheels (offline cache)"

PY_PKG_DIR="${WORK_DIR}/python-packages"
rm -rf "$PY_PKG_DIR"
mkdir -p "$PY_PKG_DIR"

docker run --rm \
  -v "${APP_WORK}/backend/requirements.txt:/requirements.txt:ro" \
  -v "${PY_PKG_DIR}:/packages" \
  python:3.11-slim \
  pip download -r /requirements.txt -d /packages \
    --prefer-binary \
    --no-deps \
    --quiet

# Second pass: download with deps to catch anything missed
docker run --rm \
  -v "${APP_WORK}/backend/requirements.txt:/requirements.txt:ro" \
  -v "${PY_PKG_DIR}:/packages" \
  python:3.11-slim \
  pip download -r /requirements.txt -d /packages \
    --prefer-binary \
    --quiet 2>/dev/null || true

# Also get email-validator (Pydantic EmailStr dependency)
docker run --rm \
  -v "${PY_PKG_DIR}:/packages" \
  python:3.11-slim \
  pip download email-validator -d /packages --prefer-binary --quiet

PKG_COUNT=$(ls "$PY_PKG_DIR" | wc -l)
PKG_SIZE=$(du -sh "$PY_PKG_DIR" | cut -f1)
info "Python wheels: ${PKG_COUNT} packages (${PKG_SIZE})"

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Pull and save Docker images
# ═══════════════════════════════════════════════════════════════════════════════
phase "Saving Docker images"

DOCKER_IMG_DIR="${WORK_DIR}/docker-images"
rm -rf "$DOCKER_IMG_DIR"
mkdir -p "$DOCKER_IMG_DIR"

docker pull eclipse-mosquitto:2.0
docker save eclipse-mosquitto:2.0 -o "${DOCKER_IMG_DIR}/mosquitto.tar"

# Compress to save space
gzip -f "${DOCKER_IMG_DIR}/mosquitto.tar"
info "Saved: mosquitto.tar.gz ($(du -sh ${DOCKER_IMG_DIR}/mosquitto.tar.gz | cut -f1))"

# Create manifest for the installer
echo "eclipse-mosquitto:2.0|mosquitto.tar.gz" > "${DOCKER_IMG_DIR}/manifest.txt"

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Download Debian packages and build local apt pool
# ═══════════════════════════════════════════════════════════════════════════════
phase "Downloading Debian packages for offline apt pool"

DEB_POOL_DIR="${WORK_DIR}/deb-pool"
rm -rf "$DEB_POOL_DIR"
mkdir -p "$DEB_POOL_DIR/packages"

# System packages needed on NUC (Python, nginx, utilities — NO Node.js needed)
SYSTEM_PACKAGES="
  python3 python3-pip python3-venv python3-dev python3-setuptools python3-wheel
  nginx
  sqlite3
  openssl libssl-dev libffi-dev
  build-essential
  net-tools ifupdown iproute2 iputils-ping
  curl wget ca-certificates gnupg lsb-release apt-transport-https
  software-properties-common
  vim htop unzip
  logrotate
  watchdog
  mosquitto-clients
  dbus
"

# Download system packages via a Debian Bookworm container
docker run --rm \
  -v "${DEB_POOL_DIR}/packages:/packages" \
  debian:bookworm \
  bash -c "
    set -e
    apt-get update -qq
    apt-get install -y --download-only --no-install-recommends \
      ${SYSTEM_PACKAGES} 2>/dev/null || true
    # Copy downloaded .deb files
    find /var/cache/apt/archives -name '*.deb' -exec cp {} /packages/ \;
    echo 'System packages downloaded: '$(ls /packages/*.deb 2>/dev/null | wc -l)
  "

# Download Docker CE packages separately (needs extra repo)
docker run --rm \
  -v "${DEB_POOL_DIR}/packages:/packages" \
  debian:bookworm \
  bash -c "
    set -e
    apt-get update -qq
    apt-get install -y curl gnupg ca-certificates
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo 'deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] \
      https://download.docker.com/linux/debian bookworm stable' \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y --download-only \
      docker-ce docker-ce-cli containerd.io docker-compose-plugin 2>/dev/null || true
    find /var/cache/apt/archives -name '*.deb' -exec cp {} /packages/ \;
    echo 'Docker packages downloaded: '$(ls /packages/docker*.deb /packages/containerd*.deb 2>/dev/null | wc -l)
  "

DEB_COUNT=$(ls "${DEB_POOL_DIR}/packages/"*.deb 2>/dev/null | wc -l)
DEB_SIZE=$(du -sh "${DEB_POOL_DIR}/packages" | cut -f1)
info "Debian packages: ${DEB_COUNT} .deb files (${DEB_SIZE})"

# Build local apt repository index
phase "Building local apt repository index"
docker run --rm \
  -v "${DEB_POOL_DIR}:/pool" \
  debian:bookworm \
  bash -c "
    apt-get install -y dpkg-dev -qq
    cd /pool
    mkdir -p dists/local/main/binary-amd64
    dpkg-scanpackages packages/ > dists/local/main/binary-amd64/Packages 2>/dev/null
    gzip -k  dists/local/main/binary-amd64/Packages
    bzip2 -k dists/local/main/binary-amd64/Packages
    # Write Release file
    cat > dists/local/Release << 'REOF'
Origin: Cloud IoT NUC
Label: Cloud IoT Offline Packages
Suite: local
Codename: local
Components: main
Architectures: amd64
Description: Offline package pool for Cloud IoT NUC deployment
REOF
  "
info "Local apt repository built"

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Download Debian netinstall ISO
# ═══════════════════════════════════════════════════════════════════════════════
phase "Downloading Debian ${DEBIAN_VERSION} netinstall ISO"

ORIG_ISO="${WORK_DIR}/debian-netinst.iso"
if [ ! -f "$ORIG_ISO" ]; then
  wget -q --show-progress -O "$ORIG_ISO" "$DEBIAN_ISO_URL" \
    || error "Failed to download Debian ISO from: $DEBIAN_ISO_URL"
fi
info "Debian ISO ready: $(du -sh $ORIG_ISO | cut -f1)"

# Extract ISO
phase "Extracting Debian ISO"
rm -rf "$ISO_EXTRACT"
mkdir -p "$ISO_EXTRACT"
xorriso -osirrox on -indev "$ORIG_ISO" -extract / "$ISO_EXTRACT" -- 2>/dev/null
chmod -R u+w "$ISO_EXTRACT"
info "ISO extracted"

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — Inject all assets into ISO
# ═══════════════════════════════════════════════════════════════════════════════
phase "Injecting app, packages, and scripts into ISO"

# ── preseed.cfg ───────────────────────────────────────────────────────────────
cp "${SCRIPT_DIR}/preseed.cfg" "${ISO_EXTRACT}/preseed.cfg"
info "preseed.cfg injected"

# ── Setup scripts ─────────────────────────────────────────────────────────────
mkdir -p "${ISO_EXTRACT}/cloud-iot-setup"
cp -r "${SCRIPT_DIR}/overlay/cloud-iot-setup/." "${ISO_EXTRACT}/cloud-iot-setup/"
chmod +x "${ISO_EXTRACT}/cloud-iot-setup/"*.sh 2>/dev/null || true
info "Setup scripts injected"

# ── Application ───────────────────────────────────────────────────────────────
mkdir -p "${ISO_EXTRACT}/cloud-iot-app"
cp -r "${APP_WORK}/." "${ISO_EXTRACT}/cloud-iot-app/"
info "Application injected ($(du -sh ${ISO_EXTRACT}/cloud-iot-app | cut -f1))"

# ── Python wheels ─────────────────────────────────────────────────────────────
mkdir -p "${ISO_EXTRACT}/cloud-iot-python"
cp -r "${PY_PKG_DIR}/." "${ISO_EXTRACT}/cloud-iot-python/"
info "Python wheels injected ($(du -sh ${ISO_EXTRACT}/cloud-iot-python | cut -f1))"

# ── Docker image tars ─────────────────────────────────────────────────────────
mkdir -p "${ISO_EXTRACT}/cloud-iot-docker"
cp -r "${DOCKER_IMG_DIR}/." "${ISO_EXTRACT}/cloud-iot-docker/"
info "Docker images injected ($(du -sh ${ISO_EXTRACT}/cloud-iot-docker | cut -f1))"

# ── Debian package pool ───────────────────────────────────────────────────────
mkdir -p "${ISO_EXTRACT}/cloud-iot-pool"
cp -r "${DEB_POOL_DIR}/." "${ISO_EXTRACT}/cloud-iot-pool/"
info "Debian package pool injected ($(du -sh ${ISO_EXTRACT}/cloud-iot-pool | cut -f1))"

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — Patch boot menus
# ═══════════════════════════════════════════════════════════════════════════════
phase "Patching boot menus"

KERNEL_APPEND="auto=true priority=critical preseed/file=/cdrom/preseed.cfg quiet"

# BIOS isolinux
for cfg in "${ISO_EXTRACT}/isolinux/isolinux.cfg" \
           "${ISO_EXTRACT}/isolinux/txt.cfg" \
           "${ISO_EXTRACT}/isolinux/menu.cfg"; do
  [ -f "$cfg" ] || continue
  cp "$cfg" "${cfg}.orig"
  cat > "$cfg" << EOF
# Cloud IoT NUC v2.0
default cloud-iot
timeout 50
prompt 0

label cloud-iot
  menu label ^Install Cloud IoT NUC v2.0 (offline)
  kernel /install.${DEBIAN_ARCH}/vmlinuz
  append vga=normal initrd=/install.${DEBIAN_ARCH}/initrd.gz --- ${KERNEL_APPEND}

label manual
  menu label Manual Debian 12 Install
  kernel /install.${DEBIAN_ARCH}/vmlinuz
  append vga=normal initrd=/install.${DEBIAN_ARCH}/initrd.gz ---
EOF
  info "Patched: $(basename $cfg)"
  break
done

# EFI GRUB
for grub_cfg in "${ISO_EXTRACT}/boot/grub/grub.cfg" \
                "${ISO_EXTRACT}/EFI/boot/grub.cfg"; do
  [ -f "$grub_cfg" ] || continue
  cp "$grub_cfg" "${grub_cfg}.orig"
  cat > "$grub_cfg" << EOF
set default=0
set timeout=5

menuentry 'Install Cloud IoT NUC v2.0 (offline)' {
  set background_color=black
  linux   /install.${DEBIAN_ARCH}/vmlinuz vga=normal ${KERNEL_APPEND} ---
  initrd  /install.${DEBIAN_ARCH}/initrd.gz
}

menuentry 'Manual Debian 12 Install' {
  set background_color=black
  linux   /install.${DEBIAN_ARCH}/vmlinuz vga=normal ---
  initrd  /install.${DEBIAN_ARCH}/initrd.gz
}
EOF
  info "Patched: ${grub_cfg}"
done

# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — Rebuild hybrid ISO (BIOS + UEFI)
# ═══════════════════════════════════════════════════════════════════════════════
phase "Building cloud-iot-nuc-v2.0.iso"

# Extract MBR from original ISO
MBR_IMG="${WORK_DIR}/mbr.bin"
dd if="$ORIG_ISO" bs=1 count=432 of="$MBR_IMG" 2>/dev/null

rm -f "$OUTPUT_ISO"

XORRISO_ARGS=(
  -as mkisofs
  -r -V "Cloud IoT NUC v2.0"
  -J -joliet-long -l -iso-level 3
  -partition_offset 16 --mbr-force-bootable
  -isohybrid-mbr "$MBR_BIN"
  -b "isolinux/isolinux.bin"
  -c "isolinux/boot.cat"
  -no-emul-boot -boot-load-size 4 -boot-info-table
)

# EFI boot entry (if present)
EFI_IMG=""
for p in "${ISO_EXTRACT}/boot/grub/efi.img" "${ISO_EXTRACT}/EFI/boot/bootx64.efi"; do
  [ -f "$p" ] && EFI_IMG="$p" && break
done
if [ -n "$EFI_IMG" ]; then
  EFI_REL="${EFI_IMG#${ISO_EXTRACT}/}"
  XORRISO_ARGS+=( -eltorito-alt-boot -e "$EFI_REL" -no-emul-boot -isohybrid-gpt-basdat )
fi

XORRISO_ARGS+=( -o "$OUTPUT_ISO" "$ISO_EXTRACT" )

xorriso "${XORRISO_ARGS[@]}" 2>&1 | grep -Ev "^(xorriso|$)" | tail -5

# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════
ISO_SIZE=$(du -sh "$OUTPUT_ISO" | cut -f1)
echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔═══════════════════════════════════════════════════════════╗"
echo "  ║   ISO Built Successfully!                                 ║"
echo "  ╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"
echo -e "  Output  : ${WHITE}${OUTPUT_ISO}${NC}  (${ISO_SIZE})"
echo ""
echo -e "  Flash to USB:"
echo -e "    ${CYAN}sudo dd if=${OUTPUT_ISO} of=/dev/sdX bs=4M status=progress${NC}"
echo -e "    Windows: Rufus → GPT → UEFI (non-CSM)"
echo ""
echo -e "  ${YELLOW}NOTE:${NC} This ISO is fully self-contained."
echo -e "         No internet connection required on the NUC."
echo ""
echo -e "  Clean build cache: rm -rf ${WORK_DIR}"
