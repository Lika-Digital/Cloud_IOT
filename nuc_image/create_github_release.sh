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
RELEASE_TITLE="NUC 3.0 Light"

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
## NUC 3.0 Light

Script-based NUC installer — no bootable ISO required.
Install Ubuntu Server 24.04 LTS first, then run `sudo bash nuc_image/ubuntu-install.sh`.

This release brings full **real-hardware** support for marina pedestal deployments on Intel NUC.

---

### What's new in v3.0

#### Session Management
- **Auto-start sessions** — customers get electricity/water immediately, no operator approval step
- Operator can still stop any active session from the dashboard at any time
- Removed Allow/Deny workflow (NUC real-hardware mode)

#### Dashboard UI
- **Live IP camera stream** in Camera modal — shows authenticated MJPEG snapshot polling from configured IP camera; falls back to YOLO/synthetic with "No live stream available" badge when camera not configured
- **"Stop Session" hover tooltip** on active socket circles (red badge on hover)
- Removed "Pending Approval" state from dashboard legend and session overview
- Contextual help bubbles on Not Initialized, Run Diagnostics, Scan Network states

#### Device Discovery & Configuration
- **ONVIF WS-Discovery** subnet scan — auto-discovers IP cameras on the LAN
- **Papouch TME** HTTP subnet scan — auto-discovers temperature/humidity sensors
- DevicesPanel UI in dashboard: scan + manual config for Arduino Opta, IP camera, TME sensor
- Papouch TME temp sensor added to pedestal config model and API

#### Berth Occupancy
- Lightweight on-demand occupancy check via live snapshot + histogram matching (no ML model required)
- Subnet scan timeout fix — prevents hang on large/slow networks

#### Mobile App
- WebSocket connection moved to app layout — stays connected across all tabs
- Operator stop session now reliably notifies the mobile customer in real time
- Chat screen receives live messages without duplicate WebSocket connection
- Duplicate session on dashboard fixed (idempotent store)

#### NUC Installer & Management CLI
- **`sudo cloud-iot upgrade`** — pulls latest code from git, rebuilds frontend, updates Python packages, restarts services
- **`sudo cloud-iot version`** — shows installed version and last commit
- Simulator completely removed from NUC deployment (real hardware only)
- Fixed AttributeError in simulator stub on `configure_pedestals`
- Fixed `email-validator` missing from install (required for Pydantic EmailStr)
- Fixed admin password newline issue in generated `.env`

#### Testing
- 81 automated backend tests (full regression suite, runs before every commit)
- 20 new pedestal config tests: camera URL/auth, MQTT credentials, TME sensor, site IDs, feature toggles
- 4 new session tests: auto-start verification, water session, operator stop flow

---

### Installation

**Fresh install** (new NUC):
1. Install Ubuntu Server 24.04 LTS (download from ubuntu.com/download/server)
2. Clone this repo on the NUC and run the installer:
   ```bash
   git clone https://github.com/Lika-Digital/Cloud_IOT.git
   cd Cloud_IOT
   sudo bash nuc_image/ubuntu-install.sh
   ```
3. Follow the 5-step wizard (network, admin, marina info, SMTP, confirm)
4. Dashboard available at `http://<NUC-IP>` after reboot

**Upgrade** (existing v2.0 NUC):
```bash
# On the NUC, SSH in and run:
cd ~/Cloud_IOT
git pull origin main
sudo cloud-iot upgrade
```

See **`nuc_image/README.txt`** for full documentation including hardware requirements, step-by-step guide, and troubleshooting.

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

# Create the GitHub release (no asset file — script-only release)
echo ""
info "Creating GitHub release ${TAG}..."
gh release create "$TAG" \
  --repo "$REPO" \
  --title "$RELEASE_TITLE" \
  --notes "$RELEASE_NOTES" \
  --latest

echo ""
info "Release published: https://github.com/${REPO}/releases/tag/${TAG}"
