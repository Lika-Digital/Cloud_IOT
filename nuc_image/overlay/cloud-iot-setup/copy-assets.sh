#!/bin/bash
# ============================================================================
# Cloud IoT NUC v2.0 — Asset Copy Script
# Called by Debian preseed late_command while installer is still running
# and the ISO is mounted at /cdrom.
#
# Copies ALL offline assets from the ISO to the target system so they are
# available after reboot (the ISO/USB is no longer mounted at first boot).
# ============================================================================
set -e

CDROM="/cdrom"
TARGET_SETUP="/target/opt/cloud-iot-setup"
TARGET_ASSETS="/target/opt/cloud-iot-assets"

echo "[copy-assets] Copying Cloud IoT assets from ISO to target disk..."
echo "[copy-assets] This may take a few minutes..."

mkdir -p "$TARGET_SETUP" "$TARGET_ASSETS"

# ── Setup scripts (firstboot wizard, installer) ───────────────────────────────
cp -r "${CDROM}/cloud-iot-setup/." "$TARGET_SETUP/"
chmod +x "${TARGET_SETUP}/"*.sh 2>/dev/null || true
echo "[copy-assets] Setup scripts: OK"

# ── Application (backend, frontend/dist, mosquitto config) ───────────────────
cp -r "${CDROM}/cloud-iot-app"    "${TARGET_ASSETS}/cloud-iot-app"
echo "[copy-assets] Application:   $(du -sh ${TARGET_ASSETS}/cloud-iot-app | cut -f1)"

# ── Python wheels (offline pip cache) ────────────────────────────────────────
cp -r "${CDROM}/cloud-iot-python" "${TARGET_ASSETS}/cloud-iot-python"
echo "[copy-assets] Python wheels: $(du -sh ${TARGET_ASSETS}/cloud-iot-python | cut -f1)"

# ── Docker image tars ─────────────────────────────────────────────────────────
cp -r "${CDROM}/cloud-iot-docker" "${TARGET_ASSETS}/cloud-iot-docker"
echo "[copy-assets] Docker images: $(du -sh ${TARGET_ASSETS}/cloud-iot-docker | cut -f1)"

# ── Debian package pool (for Docker CE install after reboot) ─────────────────
cp -r "${CDROM}/cloud-iot-pool"   "${TARGET_ASSETS}/cloud-iot-pool"
echo "[copy-assets] Debian pool:   $(du -sh ${TARGET_ASSETS}/cloud-iot-pool | cut -f1)"

# ── Install first-boot systemd service ───────────────────────────────────────
cp "${TARGET_SETUP}/cloud-iot-firstboot.service" \
   /target/etc/systemd/system/cloud-iot-firstboot.service

chroot /target systemctl enable cloud-iot-firstboot.service
chroot /target systemctl set-default multi-user.target

# ── sudo for cloud-iot user ───────────────────────────────────────────────────
echo 'cloud-iot ALL=(ALL) NOPASSWD: ALL' > /target/etc/sudoers.d/90-cloud-iot
chmod 0440 /target/etc/sudoers.d/90-cloud-iot

# ── Mark stage 1 complete ─────────────────────────────────────────────────────
echo "stage1-complete $(date --utc +%Y-%m-%dT%H:%M:%SZ)" > /target/etc/cloud-iot-stage1-done

echo "[copy-assets] All assets copied. Total assets:"
du -sh "${TARGET_ASSETS}"
echo "[copy-assets] Done."
