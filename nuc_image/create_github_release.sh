#!/usr/bin/env bash
# ============================================================================
# Create GitHub Release v3.0 — "NUC 3.0 Light"
#
# Prerequisites:
#   - gh CLI installed and authenticated:  gh auth login
#   - Working directory: Cloud_IOT repo root or nuc_image/
#
# Usage:
#   chmod +x nuc_image/create_github_release.sh
#   bash nuc_image/create_github_release.sh
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO="Lika-Digital/Cloud_IOT"
TAG="v3.0"
RELEASE_TITLE="Cloud IoT — v3.0 Release"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'; BOLD='\033[1m'
info()  { echo -e "${GREEN}[✔]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✘]${NC} $*"; exit 1; }

# Checks
command -v gh &>/dev/null || error "gh CLI not found. Install from https://cli.github.com"
gh auth status &>/dev/null || error "Not authenticated. Run: gh auth login"

# Confirm
echo -e "\n${YELLOW}${BOLD}About to create GitHub release:${NC}"
echo -e "  Repository : ${REPO}"
echo -e "  Tag        : ${TAG}"
echo -e "  Title      : ${RELEASE_TITLE}"
echo -e "  Branch     : main (script-only release — no ISO)"
echo ""
read -r -p "Continue? [y/N]: " CONFIRM
[[ "${CONFIRM,,}" =~ ^(y|yes)$ ]] || { echo "Aborted."; exit 0; }

# Ensure we are on main and pushed
CURRENT_BRANCH=$(git -C "$REPO_DIR" rev-parse --abbrev-ref HEAD)
if [ "$CURRENT_BRANCH" != "main" ]; then
  warn "Not on main branch (currently: ${CURRENT_BRANCH})"
  warn "Make sure main is up to date before running this."
fi

# Create tag if it doesn't exist
if git -C "$REPO_DIR" tag | grep -q "^${TAG}$"; then
  warn "Tag ${TAG} already exists — using existing tag"
else
  info "Creating git tag ${TAG} on main..."
  git -C "$REPO_DIR" tag -a "$TAG" -m "NUC 3.0 Light — Script-based NUC installer with real-hardware features"
  git -C "$REPO_DIR" push origin "$TAG"
  info "Tag ${TAG} pushed to GitHub"
fi

# Release notes
RELEASE_NOTES=$(cat << 'EOF'
## Cloud IoT — v3.0 Release

Script-based NUC installer — no bootable ISO required.
Install Ubuntu Server 24.04 LTS first, then run `sudo bash nuc_image/ubuntu-install.sh`.

---

### What's new in v3.0

#### Pilot Mode
- Admin assigns a customer username to a specific pedestal and socket from the Settings page
- Customer mobile app shows **only the assigned pedestal** with the assigned socket pre-selected
- Non-assigned sockets are grayed out and unclickable
- Backend enforces: correct pedestal, correct socket, and **physical plug-in within 3 minutes** before session start

#### MQTT-Driven Pedestal Registration
- Pedestals start at **zero on every application restart** — no pre-configuration needed
- Pedestal appears on the dashboard only after the Arduino sends its first MQTT register or heartbeat message
- Fleet Configuration removed from Settings — replaced with a live **Active MQTT Clients** panel

#### Socket State Tracking
- Physical plug-in / unplug events tracked via MQTT `socket/{id}/status` messages
- Session start is blocked if the Arduino has explicitly reported a socket as disconnected

#### SNMP Trap Receiver
- Built-in UDP listener for SNMP traps from IP temperature sensors (e.g. Papouch TME)
- Configurable OID, port, community string, and target pedestal — no restart required

#### Session Management
- **Auto-start sessions** — customers get electricity/water immediately, no operator approval step
- Operator can stop any active session from the dashboard at any time

#### Device Discovery & Configuration
- **ONVIF WS-Discovery** subnet scan — auto-discovers IP cameras on the LAN
- **Papouch TME** HTTP scan — auto-discovers temperature/humidity sensors
- DevicesPanel in Settings: scan + manual config for Arduino Opta, IP camera, TME sensor

#### Mobile App
- Pilot mode: assigned socket auto-selected; others locked
- WebSocket stays connected across all tabs
- Real-time session stop notifications from operator

#### NUC Installer & Management CLI
- **`sudo cloud-iot upgrade`** — pull latest code, rebuild frontend, restart services
- **`sudo cloud-iot version`** — show installed version
- **`sudo cloud-iot logs [backend|nginx|mqtt]`** — tail service logs
- Simulator and reportlab removed from NUC deployment

#### Automated Test Suite
- **105 backend tests** — billing, chat, contracts, sessions, workflow lifecycle
- Full MQTT lifecycle tests: register → heartbeat → socket connect → session → stop
- SNMP BER decoder unit tests

---

### NUC Installation

**Fresh install** (uninstall previous version first):
```bash
# 1. Uninstall old version
sudo bash ~/Cloud_IOT/nuc_image/nuc_uninstall.sh

# 2. Clone fresh and install
git clone https://github.com/Lika-Digital/Cloud_IOT.git
cd Cloud_IOT
sudo bash nuc_image/ubuntu-install.sh
```
Follow the 5-step wizard (network, admin account, marina info, SMTP, confirm).
Dashboard available at `http://<NUC-IP>` after automatic reboot.

**Upgrade existing v3 install:**
```bash
sudo cloud-iot upgrade
```

---

### Minimum requirements
| | |
|---|---|
| Hardware | Intel NUC 8th gen or newer (tested: ASUS NUC 13 BNUC13BRF) |
| CPU | Intel Core i3 64-bit, 2+ cores |
| RAM | 8 GB DDR4 |
| Storage | 64 GB eMMC / NVMe / SSD |
| Network | Gigabit Ethernet (wired, internet during install) |

---

*Previous releases: [v2.0 — NUC bootable ISO](../../releases/tag/v2.0) · [v1.0 — .deb package](../../releases/tag/v1.0)*
EOF
)

# Delete existing release if present, then recreate
echo ""
if gh release view "$TAG" --repo "$REPO" &>/dev/null; then
  warn "Release ${TAG} already exists — deleting and recreating..."
  gh release delete "$TAG" --repo "$REPO" --yes
fi

info "Creating GitHub release ${TAG}..."
gh release create "$TAG" \
  --repo "$REPO" \
  --title "$RELEASE_TITLE" \
  --notes "$RELEASE_NOTES" \
  --latest

echo ""
info "Release published: https://github.com/${REPO}/releases/tag/${TAG}"
