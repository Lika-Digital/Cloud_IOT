#!/usr/bin/env bash
# ============================================================================
# Cloud IoT NUC v2.0 — First Boot Setup Wizard
# Runs automatically on first boot. Fully offline — uses bundled ISO assets.
# ============================================================================
set -euo pipefail

SETUP_DIR="/opt/cloud-iot-setup"
LOG_FILE="/var/log/cloud-iot-setup.log"
COMPLETE_FLAG="/etc/cloud-iot-setup-complete"

[ -f "$COMPLETE_FLAG" ] && exit 0

exec > >(tee -a "$LOG_FILE") 2>&1

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; WHITE='\033[1;37m'; BOLD='\033[1m'; NC='\033[0m'

info()  { echo -e "${GREEN}[✔]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✘]${NC} $*"; }

ask() {
  local prompt="$1" default="${2:-}" result
  if [ -n "$default" ]; then
    read -r -p "$(echo -e "  ${CYAN}${prompt}${NC} [${WHITE}${default}${NC}]: ")" result
    echo "${result:-$default}"
  else
    while true; do
      read -r -p "$(echo -e "  ${CYAN}${prompt}${NC}: ")" result
      [ -n "$result" ] && break
      echo -e "  ${RED}Required.${NC}"
    done
    echo "$result"
  fi
}

ask_password() {
  local prompt="$1" pass1 pass2
  while true; do
    read -r -s -p "$(echo -e "  ${CYAN}${prompt} (min 8 chars)${NC}: ")" pass1; echo
    [ "${#pass1}" -ge 8 ] || { echo -e "  ${RED}Too short.${NC}"; continue; }
    read -r -s -p "$(echo -e "  ${CYAN}Confirm${NC}: ")" pass2; echo
    [ "$pass1" = "$pass2" ] && break
    echo -e "  ${RED}Mismatch. Try again.${NC}"
  done
  echo "$pass1"
}

ask_yn() {
  local prompt="$1" default="${2:-n}" answer
  read -r -p "$(echo -e "  ${CYAN}${prompt}${NC} [y/N]: ")" answer
  [[ "${answer:-$default}" =~ ^[Yy] ]]
}

validate_ip() {
  local ip="$1"
  [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  IFS='.' read -ra o <<< "$ip"
  for x in "${o[@]}"; do [[ "$x" -le 255 ]] || return 1; done
}

ask_ip() {
  local prompt="$1" default="${2:-}" ip
  while true; do
    ip=$(ask "$prompt" "$default")
    validate_ip "$ip" && { echo "$ip"; return; }
    echo -e "  ${RED}Invalid IP.${NC}"
  done
}

mask_to_cidr() {
  local mask="$1" cidr=0 bit
  IFS='.' read -ra octs <<< "$mask"
  for o in "${octs[@]}"; do
    bit=128
    while [[ $bit -gt 0 ]]; do
      (( o & bit )) && cidr=$((cidr+1)) || { echo "$cidr"; return; }
      bit=$((bit>>1))
    done
  done
  echo "$cidr"
}

# ── Welcome ───────────────────────────────────────────────────────────────────
clear
echo -e "${BLUE}"
cat << 'BANNER'
  ╔══════════════════════════════════════════════════════════════════╗
  ║        Cloud IoT — Marina Pedestal Management System            ║
  ║                   NUC Setup Wizard  v2.0                        ║
  ║                    FULLY OFFLINE INSTALL                        ║
  ╚══════════════════════════════════════════════════════════════════╝
BANNER
echo -e "${NC}"
echo -e "  ${WHITE}This wizard configures the NUC and installs Cloud IoT.${NC}"
echo -e "  ${GREEN}No internet connection required.${NC}"
echo ""
echo "  Press ENTER to begin..."
read -r

# ── STEP 1: Date / Time ───────────────────────────────────────────────────────
clear
echo -e "${BLUE}${BOLD}"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   STEP 1 / 6  —  DATE & TIME"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${NC}"
echo -e "  ${YELLOW}NTP is not available without internet. Please set the clock manually.${NC}"
echo -e "  Current system time: ${WHITE}$(date)${NC}"
echo ""

if ask_yn "Set date/time manually?" "y"; then
  while true; do
    DATETIME=$(ask "Date and time" "$(date '+%Y-%m-%d %H:%M:%S')")
    if date -s "$DATETIME" &>/dev/null; then
      hwclock --systohc 2>/dev/null || true   # sync to hardware clock
      info "System clock set to: $(date)"
      break
    else
      echo -e "  ${RED}Invalid format. Use: YYYY-MM-DD HH:MM:SS${NC}"
    fi
  done

  TIMEZONE=$(ask "Timezone (e.g. Europe/Ljubljana, UTC)" "UTC")
  if timedatectl set-timezone "$TIMEZONE" 2>/dev/null; then
    info "Timezone set: $TIMEZONE"
  else
    warn "Unknown timezone '$TIMEZONE' — using UTC"
    timedatectl set-timezone UTC 2>/dev/null || true
  fi
else
  info "Keeping system time: $(date)"
fi

# ── STEP 2: Network ───────────────────────────────────────────────────────────
clear
echo -e "${BLUE}${BOLD}"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   STEP 2 / 6  —  NETWORK CONFIGURATION"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${NC}"

mapfile -t IFACES < <(
  ip -o link show 2>/dev/null \
  | grep -v 'lo\|docker\|veth\|br-\|virbr' \
  | awk -F': ' '{print $2}' | cut -d'@' -f1 | tr -d ' '
)
[ ${#IFACES[@]} -eq 0 ] && { error "No network interfaces found!"; exit 1; }

echo -e "  ${WHITE}Available interfaces:${NC}"
for i in "${!IFACES[@]}"; do
  IFACE="${IFACES[$i]}"
  MAC=$(cat "/sys/class/net/${IFACE}/address" 2>/dev/null || echo "?")
  echo -e "    ${WHITE}$((i+1)).${NC} ${IFACE}  (MAC: ${MAC})"
done
echo ""

IFACE_IDX=1
if [ ${#IFACES[@]} -gt 1 ]; then
  while true; do
    read -r -p "$(echo -e "  ${CYAN}Select interface [1]:${NC} ")" IFACE_IDX
    IFACE_IDX="${IFACE_IDX:-1}"
    [[ "$IFACE_IDX" =~ ^[0-9]+$ ]] \
      && [ "$IFACE_IDX" -ge 1 ] \
      && [ "$IFACE_IDX" -le "${#IFACES[@]}" ] && break
    echo -e "  ${RED}Invalid.${NC}"
  done
fi
NETWORK_IFACE="${IFACES[$((IFACE_IDX-1))]}"

HOSTNAME=$(ask  "Hostname"             "marina-iot-01")
STATIC_IP=$(ask_ip "Static IP"         "192.168.1.100")
NETMASK=$(ask_ip   "Subnet mask"       "255.255.255.0")
GATEWAY=$(ask_ip   "Default gateway"   "192.168.1.1")
DNS=$(ask          "DNS servers"       "8.8.8.8 8.8.4.4")

echo ""
echo -e "  ${GREEN}${BOLD}Summary:${NC}"
echo -e "    Interface : ${WHITE}${NETWORK_IFACE}${NC}"
echo -e "    Hostname  : ${WHITE}${HOSTNAME}${NC}"
echo -e "    IP        : ${WHITE}${STATIC_IP}${NC}"
echo -e "    Mask      : ${WHITE}${NETMASK}${NC}"
echo -e "    Gateway   : ${WHITE}${GATEWAY}${NC}"
echo -e "    DNS       : ${WHITE}${DNS}${NC}"
echo ""
if ! ask_yn "Confirm?" "y"; then exec "$0"; fi

# ── STEP 3: Admin account ─────────────────────────────────────────────────────
clear
echo -e "${BLUE}${BOLD}"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   STEP 3 / 6  —  ADMIN ACCOUNT"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${NC}"
echo ""
ADMIN_EMAIL=$(ask "Admin email" "admin@marina.local")
ADMIN_PASSWORD=$(ask_password "Admin password")

# ── STEP 4: Marina information ────────────────────────────────────────────────
clear
echo -e "${BLUE}${BOLD}"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   STEP 4 / 6  —  MARINA INFORMATION"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${NC}"
echo ""
COMPANY_NAME=$(ask    "Marina / company name" "Marina")
COMPANY_ADDRESS=$(ask "Address"               "")
COMPANY_PHONE=$(ask   "Phone"                 "")
COMPANY_EMAIL=$(ask   "Contact email"         "$ADMIN_EMAIL")
PORTAL_NAME=$(ask     "Portal name"           "${COMPANY_NAME} IoT Portal")

# ── STEP 5: SMTP (optional) ───────────────────────────────────────────────────
clear
echo -e "${BLUE}${BOLD}"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   STEP 5 / 6  —  EMAIL / SMTP  (optional)"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${NC}"
echo -e "  If skipped: OTP codes print to log — sudo journalctl -u cloud-iot-backend -f"
echo ""

SMTP_HOST="" SMTP_PORT="587" SMTP_TLS="true"
SMTP_USER="" SMTP_PASS="" SMTP_FROM="noreply@marina.local"

if ask_yn "Configure SMTP?" "n"; then
  SMTP_HOST=$(ask  "SMTP host"     "smtp.gmail.com")
  SMTP_PORT=$(ask  "SMTP port"     "587")
  SMTP_TLS=$(ask   "TLS (true/false)" "true")
  SMTP_FROM=$(ask  "From address"  "noreply@${ADMIN_EMAIL##*@}")
  SMTP_USER=$(ask  "SMTP user"     "$SMTP_FROM")
  SMTP_PASS=$(ask_password "SMTP password")
fi

# ── STEP 6: Apply configuration and install ───────────────────────────────────
clear
echo -e "${BLUE}${BOLD}"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   STEP 6 / 6  —  INSTALLING  (fully offline)"
echo "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${NC}"

JWT_SECRET=$(openssl rand -hex 32)

# Apply hostname
echo "$HOSTNAME" > /etc/hostname
hostname "$HOSTNAME"
if grep -q '127.0.1.1' /etc/hosts; then
  sed -i "s/^127\.0\.1\.1.*/127.0.1.1\t${HOSTNAME}/" /etc/hosts
else
  echo "127.0.1.1    ${HOSTNAME}" >> /etc/hosts
fi
info "Hostname: ${HOSTNAME}"

# Apply network
CIDR=$(mask_to_cidr "$NETMASK")
cat > /etc/network/interfaces << EOF
# Cloud IoT NUC — configured $(date --utc +"%Y-%m-%dT%H:%M:%SZ")
source /etc/network/interfaces.d/*

auto lo
iface lo inet loopback

auto ${NETWORK_IFACE}
iface ${NETWORK_IFACE} inet static
    address ${STATIC_IP}/${CIDR}
    gateway ${GATEWAY}
    dns-nameservers ${DNS}
    dns-search local
EOF
{ for ns in $DNS; do echo "nameserver $ns"; done; echo "search local"; } > /etc/resolv.conf
info "Network: ${STATIC_IP}/${CIDR} via ${NETWORK_IFACE}"

# Write config for installer
CONFIG_FILE=$(mktemp)
chmod 600 "$CONFIG_FILE"
cat > "$CONFIG_FILE" << EOF
STATIC_IP="${STATIC_IP}"
ADMIN_EMAIL="${ADMIN_EMAIL}"
ADMIN_PASSWORD="${ADMIN_PASSWORD}"
COMPANY_NAME="${COMPANY_NAME}"
COMPANY_ADDRESS="${COMPANY_ADDRESS}"
COMPANY_PHONE="${COMPANY_PHONE}"
COMPANY_EMAIL="${COMPANY_EMAIL}"
PORTAL_NAME="${PORTAL_NAME}"
JWT_SECRET="${JWT_SECRET}"
SMTP_HOST="${SMTP_HOST}"
SMTP_PORT="${SMTP_PORT}"
SMTP_TLS="${SMTP_TLS}"
SMTP_FROM="${SMTP_FROM}"
SMTP_USER="${SMTP_USER}"
SMTP_PASS="${SMTP_PASS}"
EOF

echo ""
info "Starting offline installation..."
echo -e "  ${YELLOW}Do not power off. Takes ~5 minutes.${NC}"
echo ""

bash "${SETUP_DIR}/install-cloud-iot.sh" "$CONFIG_FILE"
rm -f "$CONFIG_FILE"

# Disable this service (runs only once)
systemctl disable cloud-iot-firstboot.service 2>/dev/null || true
touch "$COMPLETE_FLAG"

# Done
echo ""
echo -e "${GREEN}${BOLD}"
cat << 'DONE'
  ╔══════════════════════════════════════════════════════════════════╗
  ║                INSTALLATION COMPLETE!  🎉                       ║
  ╚══════════════════════════════════════════════════════════════════╝
DONE
echo -e "${NC}"
echo -e "  ${WHITE}Dashboard:${NC}  http://${STATIC_IP}"
echo -e "  ${WHITE}SSH:${NC}        ssh cloud-iot@${STATIC_IP}"
echo -e "  ${WHITE}MQTT:${NC}       ${STATIC_IP}:1883  (Arduino Opta)"
echo ""
[ -z "$SMTP_HOST" ] && \
  echo -e "  ${YELLOW}OTP codes:${NC} sudo journalctl -u cloud-iot-backend -f"
echo ""
echo -e "  ${GREEN}Rebooting in 10 seconds...${NC}"
sleep 10
reboot
