#!/usr/bin/env bash
# ============================================================================
# Create GitHub Release v2.0 — "NUC Release"
#
# Prerequisites:
#   - gh CLI installed and authenticated:  gh auth login
#   - ISO already built:  ./build_iso.sh
#
# Usage:
#   chmod +x create_github_release.sh
#   ./create_github_release.sh
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ISO_FILE="${SCRIPT_DIR}/cloud-iot-nuc-v2.0.iso"
REPO="Lika-Digital/Cloud_IOT"
TAG="v2.0"
RELEASE_TITLE="NUC Release v2.0"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'; BOLD='\033[1m'
info()  { echo -e "${GREEN}[✔]${NC} $*"; }
error() { echo -e "${RED}[✘]${NC} $*"; exit 1; }

# Checks
command -v gh &>/dev/null || error "gh CLI not found. Install from https://cli.github.com"
[ -f "$ISO_FILE" ] || error "ISO not found at ${ISO_FILE}. Run ./build_iso.sh first."

gh auth status &>/dev/null || error "Not authenticated. Run: gh auth login"

ISO_SIZE=$(du -sh "$ISO_FILE" | cut -f1)
info "ISO: ${ISO_FILE}  (${ISO_SIZE})"

# Confirm
echo -e "\n${YELLOW}${BOLD}About to create GitHub release:${NC}"
echo -e "  Repository : ${REPO}"
echo -e "  Tag        : ${TAG}"
echo -e "  Title      : ${RELEASE_TITLE}"
echo -e "  Asset      : $(basename $ISO_FILE)  (${ISO_SIZE})"
echo ""
read -r -p "Continue? [y/N]: " CONFIRM
[[ "${CONFIRM,,}" =~ ^(y|yes)$ ]] || { echo "Aborted."; exit 0; }

# Commit + tag (if not already tagged)
if ! git -C "$SCRIPT_DIR/.." tag | grep -q "^${TAG}$"; then
  echo ""
  info "Creating git tag ${TAG}..."
  git -C "$SCRIPT_DIR/.." add nuc_image/ 2>/dev/null || true
  git -C "$SCRIPT_DIR/.." diff --cached --quiet \
    || git -C "$SCRIPT_DIR/.." commit -m "feat(nuc): NUC bootable image Release v2.0

Add complete NUC deployment image with:
- Debian 12 preseed for automated OS installation
- Interactive first-boot setup wizard (network + marina config)
- Full Cloud IoT application installer
- nginx, Docker, MQTT broker auto-configured
- Management CLI (cloud-iot command)
- README.txt with system requirements and installation guide

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
  git -C "$SCRIPT_DIR/.." tag -a "$TAG" -m "NUC Release v2.0 — Bootable Debian 12 image for Intel NUC"
  git -C "$SCRIPT_DIR/.." push origin main --tags
  info "Pushed tag ${TAG} to GitHub"
else
  info "Tag ${TAG} already exists"
fi

# Create release notes
RELEASE_NOTES=$(cat << 'EOF'
## NUC Release v2.0

Bootable USB image for Intel NUC — installs Cloud IoT Marina Pedestal Management System on a bare-metal NUC with a single USB drive.

### What's included
- **Debian 12 "Bookworm"** — minimal server, auto-installed via preseed
- **Cloud IoT v2.0** — full application stack:
  - FastAPI backend + WebSocket + MQTT bridge
  - React 18 admin dashboard (nginx)
  - Customer mobile app API
  - Invoice & contract management (PDF)
  - Chat, push notifications, external API gateway
- **Eclipse Mosquitto 2.0** MQTT broker (Docker)
- **ML Worker** for ship detection (Docker, optional)
- **Interactive first-boot wizard** — configure network, admin, marina info
- **`cloud-iot` management CLI** — start/stop/update/logs

### Minimum requirements
| | |
|---|---|
| Hardware | Intel NUC 8th gen or newer |
| CPU | Intel Core i3 (64-bit) |
| RAM | 8 GB DDR4 |
| Storage | 120 GB SSD |
| Network | Gigabit Ethernet |

### Installation

1. Flash `cloud-iot-nuc-v2.0.iso` to a USB drive (≥ 2 GB):
   ```bash
   sudo dd if=cloud-iot-nuc-v2.0.iso of=/dev/sdX bs=4M status=progress
   ```
   Or use **Rufus** on Windows (GPT / UEFI non-CSM).

2. Disable **Secure Boot** in NUC BIOS (F2 → Security)

3. Boot from USB — Debian installs automatically (~10 min)

4. On first boot, the **setup wizard** appears — enter:
   - Static IP / gateway / DNS
   - Admin email + password
   - Marina name and contact details

5. Access the dashboard at `http://<your-ip>` after reboot.

See **`nuc_image/README.txt`** for full documentation.

---
*Previous release: [v1.0 — .deb package](../../releases/tag/v1.0)*
EOF
)

# Create the GitHub release and upload ISO
echo ""
info "Creating GitHub release and uploading ISO (~${ISO_SIZE})..."
echo -e "${YELLOW}Upload may take several minutes depending on connection speed.${NC}"
echo ""

gh release create "$TAG" \
  --repo "$REPO" \
  --title "$RELEASE_TITLE" \
  --notes "$RELEASE_NOTES" \
  --latest \
  "$ISO_FILE#Cloud IoT NUC v2.0 — Bootable USB ISO"

echo ""
info "Release published: https://github.com/${REPO}/releases/tag/${TAG}"
