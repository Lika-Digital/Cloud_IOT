#!/bin/bash
# build_deb.sh — build the cloud-iot .deb package from the current repo
#
# Run this from Linux / WSL from the DEB_Pack directory:
#   cd DEB_Pack
#   chmod +x build_deb.sh
#   ./build_deb.sh
#
# Prerequisites (Ubuntu/Debian):
#   sudo apt-get install -y dpkg-dev

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEB_ROOT="$(cd "$(dirname "$0")" && pwd)"
PKG_DIR="$DEB_ROOT/package"
APP_DEST="$PKG_DIR/opt/cloud-iot"
VERSION=$(grep '^Version:' "$PKG_DIR/DEBIAN/control" | awk '{print $2}')
OUTPUT_DEB="$DEB_ROOT/cloud-iot_${VERSION}_amd64.deb"

echo "[build] Cloud IoT .deb builder"
echo "[build] Repo root : $REPO_ROOT"
echo "[build] Package   : $OUTPUT_DEB"
echo ""

# ── Validate prerequisites ────────────────────────────────────────────────────
command -v dpkg-deb >/dev/null || { echo "ERROR: dpkg-deb not found. Install: sudo apt-get install dpkg-dev"; exit 1; }

# ── Clean previous build ──────────────────────────────────────────────────────
rm -rf "$APP_DEST"
mkdir -p "$APP_DEST"

echo "[build] Copying application source..."

# ── Backend ───────────────────────────────────────────────────────────────────
rsync -a --quiet \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.venv' \
    --exclude '.env' \
    --exclude 'pedestal.db' \
    --exclude 'data/' \
    --exclude 'models/' \
    --exclude 'backgrounds/' \
    "$REPO_ROOT/backend/" "$APP_DEST/backend/"

# ── Frontend (source — built during postinst) ─────────────────────────────────
rsync -a --quiet \
    --exclude 'node_modules' \
    --exclude 'dist' \
    "$REPO_ROOT/frontend/" "$APP_DEST/frontend/"

# ── ML Worker ─────────────────────────────────────────────────────────────────
rsync -a --quiet \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    "$REPO_ROOT/ml_worker/" "$APP_DEST/ml_worker/"

# ── MQTT broker config ────────────────────────────────────────────────────────
rsync -a --quiet \
    "$REPO_ROOT/mosquitto/" "$APP_DEST/mosquitto/"

# ── Docker compose ────────────────────────────────────────────────────────────
cp "$REPO_ROOT/docker-compose.yml" "$APP_DEST/docker-compose.yml"

# ── Create required empty directories ────────────────────────────────────────
mkdir -p "$APP_DEST/backend/data"
mkdir -p "$APP_DEST/backend/models"
mkdir -p "$APP_DEST/backend/backgrounds"

# ── Optionally bundle ML models if already downloaded ─────────────────────────
if [[ -f "$REPO_ROOT/backend/models/rtdetr.onnx" && -f "$REPO_ROOT/backend/models/dinov2.onnx" ]]; then
    echo "[build] Bundling ONNX models (rtdetr.onnx + dinov2.onnx)..."
    cp "$REPO_ROOT/backend/models/rtdetr.onnx"  "$APP_DEST/backend/models/"
    cp "$REPO_ROOT/backend/models/dinov2.onnx"  "$APP_DEST/backend/models/"
else
    echo "[build] ONNX models not found — skipping (user must run: cloud-iot download-models)"
fi

# ── Set DEBIAN script permissions ─────────────────────────────────────────────
echo "[build] Setting permissions..."
chmod 755 "$PKG_DIR/DEBIAN"
chmod 644 "$PKG_DIR/DEBIAN/control"
chmod 755 "$PKG_DIR/DEBIAN/postinst"
chmod 755 "$PKG_DIR/DEBIAN/prerm"
chmod 755 "$PKG_DIR/DEBIAN/postrm"
chmod 755 "$PKG_DIR/usr/bin/cloud-iot"

# Ensure Unix line endings on all scripts (important if built from Windows)
if command -v dos2unix &>/dev/null; then
    dos2unix -q "$PKG_DIR/DEBIAN/postinst" \
                "$PKG_DIR/DEBIAN/prerm" \
                "$PKG_DIR/DEBIAN/postrm" \
                "$PKG_DIR/usr/bin/cloud-iot"
else
    # sed fallback
    for f in "$PKG_DIR/DEBIAN/postinst" "$PKG_DIR/DEBIAN/prerm" \
              "$PKG_DIR/DEBIAN/postrm" "$PKG_DIR/usr/bin/cloud-iot"; do
        sed -i 's/\r$//' "$f"
    done
fi

# Update installed-size in control file
INSTALLED_KB=$(du -sk "$PKG_DIR" | awk '{print $1}')
sed -i "s/^Installed-Size:.*/Installed-Size: $INSTALLED_KB/" "$PKG_DIR/DEBIAN/control" 2>/dev/null || \
    echo "Installed-Size: $INSTALLED_KB" >> "$PKG_DIR/DEBIAN/control"

# ── Build the .deb ────────────────────────────────────────────────────────────
echo "[build] Building .deb package..."
dpkg-deb --build --root-owner-group "$PKG_DIR" "$OUTPUT_DEB"

echo ""
echo "[build] ✓ Package ready: $OUTPUT_DEB"
echo "[build]   Size: $(du -sh "$OUTPUT_DEB" | awk '{print $1}')"
echo ""
echo "[build] Deploy to Ubuntu server:"
echo "   scp $OUTPUT_DEB user@server:~/"
echo "   ssh user@server 'sudo dpkg -i ~/cloud-iot_${VERSION}_amd64.deb'"
echo ""
