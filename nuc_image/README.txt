================================================================================
  Cloud IoT Marina Pedestal Management System
  NUC Bootable Image — Release v2.0  (Self-Contained, NO internet required)
  Created by Lika Digital — info@lika.digital
================================================================================


CONTENTS OF THIS IMAGE
───────────────────────
This is a SELF-CONTAINED bootable ISO. All software is bundled inside.
No internet connection is required on the NUC during or after installation.

  Operating System:
    • Debian 12 "Bookworm" (minimal server install, LTS until 2028)
    • OpenSSH server (remote management)
    • nginx (reverse proxy + static frontend)

  Cloud IoT Application (v2.0):
    • FastAPI backend            — REST API, WebSocket, MQTT bridge, JWT auth
    • React 18 frontend          — Admin dashboard (pre-built, served via nginx)
    • Customer mobile API        — REST endpoints for the Expo mobile app
    • SQLite databases           — IoT data + user/auth data (WAL mode enabled)
    • Chat & support messaging   — Real-time via WebSocket
    • Push notification dispatch — Expo push API integration
    • External API gateway       — Webhook dispatch for third-party integration

  Runtime Dependencies (all bundled in ISO — no download needed on NUC):
    • Python 3.11+               — Backend runtime
    • Docker CE                  — MQTT broker container
    • Eclipse Mosquitto 2.0      — MQTT broker (Docker, persistence enabled)
    • FastAPI, PyJWT, pydantic, SQLAlchemy, paho-mqtt, uvicorn, httpx ...


MINIMUM SYSTEM REQUIREMENTS
────────────────────────────
  Hardware:   Intel NUC (8th generation or newer)
  CPU:        Intel Core i3 (64-bit, 2+ cores)
  RAM:        8 GB DDR4 (minimum)
  Storage:    120 GB SSD — M.2 NVMe or 2.5" SATA (HDD not recommended)
  Network:    1× Gigabit Ethernet (wired, required)
  USB:        1× USB 3.0 port (for installation media — 8 GB minimum)
  BIOS:       UEFI firmware — Secure Boot must be DISABLED
  Internet:   NOT required. Installation is fully offline.

RECOMMENDED HARDWARE
─────────────────────
  Intel NUC 11 (NUC11TNHi5) or Intel NUC 12 (NUC12WSHi5)
  CPU:     Intel Core i5 / i7
  RAM:     16 GB DDR4
  Storage: 256 GB NVMe SSD


================================================================================
  FIRST-TIME INSTALLATION GUIDE (NUC — bare metal, no OS)
================================================================================

STEP 1 — BUILD THE ISO (on your development machine, not the NUC)
  Requirements: Docker Desktop, xorriso, wget  (Linux, macOS, or WSL on Windows)

    cd nuc_image/
    chmod +x build_iso.sh
    ./build_iso.sh

  This takes 10–30 minutes. Output: cloud-iot-nuc-v2.0.iso (~3–5 GB)

  NOTE: You only need to build once. The ISO is fully self-contained.
        xorriso install: sudo apt install xorriso   (or: brew install xorriso)

──────────────────────────────────────────────────────────────────────────────

STEP 2 — FLASH ISO TO USB DRIVE (minimum 8 GB)

  Windows (easiest):
    1. Download Rufus from https://rufus.ie  (free, no install needed)
    2. Insert USB drive
    3. In Rufus:
         Device:          select your USB drive
         Boot selection:  click SELECT → choose cloud-iot-nuc-v2.0.iso
         Partition scheme: GPT
         Target system:    UEFI (non-CSM)
    4. Click START → Yes to warnings
    5. Wait for "READY" → close Rufus → safely eject USB

  Linux / macOS:
    sudo dd if=cloud-iot-nuc-v2.0.iso of=/dev/sdX bs=4M status=progress
    (replace /dev/sdX with your USB — use 'lsblk' or 'diskutil list' to find it)

──────────────────────────────────────────────────────────────────────────────

STEP 3 — BIOS SETUP ON THE NUC

    a. Insert the USB drive into the NUC
    b. Power on the NUC → press F2 immediately to open BIOS setup
    c. Go to:   Security → Secure Boot → set to DISABLED
    d. Go to:   Boot → Boot Priority Order → move USB to first position
    e. Press F10 → Save and Exit

──────────────────────────────────────────────────────────────────────────────

STEP 4 — AUTOMATIC DEBIAN INSTALLATION (hands-off, ~10 minutes)

    • NUC boots from USB into the Debian installer
    • The installation is fully automatic — do NOT touch the keyboard
    • All partitioning, package install, and service setup happen automatically
    • When the screen shows "Remove installation media and press Enter":
        → Pull out the USB drive
        → Press Enter
    • NUC reboots automatically into Debian

──────────────────────────────────────────────────────────────────────────────

STEP 5 — FIRST-BOOT SETUP WIZARD (interactive, on NUC screen)

  On the very first boot, a setup wizard appears directly on the NUC screen (TTY).
  Connect a monitor + keyboard to the NUC for this step only.

  You will be asked for:

  ┌─ DATE & TIME ────────────────────────────────────────────┐
  │  Current date/time  e.g. 2025-06-01 14:30               │
  │  Timezone           e.g. Europe/Zagreb                  │
  └──────────────────────────────────────────────────────────┘
  ┌─ NETWORK ────────────────────────────────────────────────┐
  │  Network interface  auto-detected (you select)          │
  │  Static IP address  e.g. 192.168.1.100                  │
  │  Subnet mask        e.g. 255.255.255.0 (or prefix /24)  │
  │  Default gateway    e.g. 192.168.1.1                    │
  │  DNS server(s)      e.g. 8.8.8.8                        │
  │  Hostname           e.g. marina-iot-01                  │
  └──────────────────────────────────────────────────────────┘
  ┌─ ADMIN ACCOUNT ──────────────────────────────────────────┐
  │  Admin email        e.g. admin@marina.local              │
  │  Admin password     min. 8 characters                   │
  └──────────────────────────────────────────────────────────┘
  ┌─ MARINA INFORMATION ─────────────────────────────────────┐
  │  Company / marina name                                  │
  │  Address, phone, email                                  │
  │  Portal name        e.g. Marina IoT Portal              │
  └──────────────────────────────────────────────────────────┘
  ┌─ SMTP EMAIL (optional) ──────────────────────────────────┐
  │  If configured: OTP login codes are sent by email       │
  │  If skipped:    OTP codes appear in system log          │
  │    (view with: sudo journalctl -u cloud-iot-backend)    │
  └──────────────────────────────────────────────────────────┘

  After you finish the wizard, the installer runs automatically (~15 minutes).
  The NUC reboots when complete. You can disconnect the monitor and keyboard.

──────────────────────────────────────────────────────────────────────────────

STEP 6 — ACCESS THE SYSTEM

  From any browser on the same network:

    Admin Dashboard:   http://<IP-you-configured-in-wizard>
    Login:             the email and password you set in the wizard

  SSH remote access (for management):
    ssh cloud-iot@<NUC-IP>

  MQTT broker (for Arduino Opta):
    Host: <NUC-IP>
    Port: 1883

  Mobile customer app (set in mobile/.env):
    EXPO_PUBLIC_API_URL=http://<NUC-IP>
    EXPO_PUBLIC_WS_URL=ws://<NUC-IP>


================================================================================
  TESTING THE ISO ON A PC (VirtualBox — no NUC needed)
================================================================================

You can test the full install flow on your Windows/Linux/macOS PC using
VirtualBox (free) before flashing to a real NUC.

STEP 1 — Install VirtualBox
  Download from https://www.virtualbox.org  → install with defaults.

STEP 2 — Create a new Virtual Machine
  a. Open VirtualBox → click "New"
  b. Name:        cloud-iot-test
     Type:        Linux
     Version:     Debian (64-bit)
  c. Memory:      4096 MB (minimum)
  d. Hard disk:   Create new → VDI → Dynamically allocated → 40 GB

STEP 3 — Configure the VM for UEFI boot
  a. Select the VM → Settings → System → Motherboard
     ☑ Enable EFI (special OSes only)   ← IMPORTANT
  b. Settings → System → Processor: set to 2 CPUs
  c. Settings → Display: Video Memory 16 MB (enough for installer)

STEP 4 — Attach the ISO
  a. Settings → Storage → Controller: IDE → click the CD icon
  b. Click "Choose a disk file..." → select cloud-iot-nuc-v2.0.iso
  c. Click OK

STEP 5 — Boot and install
  a. Click Start to power on the VM
  b. The Debian installer runs automatically (fully unattended)
  c. After ~10 minutes it will show "Finish the installation" / reboot
  d. VirtualBox may auto-remove the ISO — if it boots to GRUB prompt,
     the ISO was removed correctly
  e. Wait for the first-boot wizard to appear on the VM screen

STEP 6 — Complete the wizard
  - Enter any IP in the 10.0.x.x or 192.168.x.x range for testing
  - After install (~15 min), the VM reboots to the running system

STEP 7 — Access the VM
  - In VirtualBox: Settings → Network → change to "Bridged Adapter"
    (or use NAT with port forwarding: host 8080 → guest 80)
  - Open http://localhost:8080 (NAT) or http://<VM-IP> (bridged)


NOTE — VMware alternative:
  VMware Workstation Player (free) also works. Use similar steps.
  When creating the VM, select: "I will install the OS later"
  then manually attach the ISO before first boot.


================================================================================
  POST-INSTALLATION MANAGEMENT
================================================================================

  SSH into the NUC and use the built-in CLI:

    sudo cloud-iot status            Check all service status
    sudo cloud-iot start             Start all services
    sudo cloud-iot stop              Stop all services
    sudo cloud-iot restart           Restart all services
    sudo cloud-iot logs backend      Live backend log
    sudo cloud-iot logs nginx        nginx error log
    sudo cloud-iot logs mqtt         MQTT broker log
    sudo cloud-iot logs watchdog     Watchdog log
    sudo cloud-iot config            Edit .env (auto-restarts backend)
    sudo cloud-iot ip                Show current IP address


NETWORK PORTS
──────────────
    80    HTTP  — Web dashboard + API (nginx, expose to LAN)
    22    TCP   — SSH management (restrict to admin IPs in production)
    1883  MQTT  — Arduino Opta connection (restrict to device IP)
    9001  WS    — MQTT over WebSocket (internal)
    8000  HTTP  — FastAPI backend (internal only, do NOT expose)


DIRECTORY STRUCTURE (on installed NUC)
────────────────────────────────────────
    /opt/cloud-iot/               Application root
    /opt/cloud-iot/backend/       FastAPI + Python venv + SQLite databases
    /opt/cloud-iot/frontend/dist/ Pre-built React app (served by nginx)
    /opt/cloud-iot/backend/.env   Configuration (sensitive — root only)
    /var/log/cloud-iot/           Application logs (logrotate managed)
    /var/lib/cloud-iot/mosquitto/ MQTT persistence data


SECURITY NOTES
───────────────
  • Change the admin password after first login via the web UI
  • Enable SSH key auth and disable password login for production:
      ssh-copy-id cloud-iot@<nuc-ip>
      sudo nano /etc/ssh/sshd_config  → set PasswordAuthentication no
  • Firewall (ufw) recommended for production:
      sudo ufw allow from <arduino-ip> to any port 1883
      sudo ufw allow 80/tcp
      sudo ufw allow 22/tcp
      sudo ufw enable
  • Port 8000 must NOT be exposed externally (nginx proxies it)
  • The .env file contains JWT_SECRET — keep it confidential


TROUBLESHOOTING
────────────────
  First-boot wizard did not appear:
    Login: cloud-iot / ChangeOnFirstLogin
    Run:   sudo /opt/cloud-iot-setup/firstboot-setup.sh

  Services not running after install:
    sudo cloud-iot status
    sudo cloud-iot start

  View full install log:
    sudo cat /var/log/cloud-iot-setup.log

  NUC keeps rebooting (watchdog):
    The MQTT broker is not responding. Check:
    sudo cloud-iot logs mqtt
    sudo cloud-iot restart


RELEASE NOTES — v2.0
──────────────────────
  New in v2.0 (NUC Self-Contained Image):
    + Fully offline bootable ISO — no internet required on NUC
    + Automated Debian 12 install via preseed
    + Interactive first-boot wizard (datetime, network, admin, SMTP)
    + Hardware watchdog — auto-reboot if MQTT broker crashes >60s
    + MQTT persistence — broker state survives reboots
    + SQLite WAL mode — safe concurrent reads during writes
    + Log rotation — prevents disk fill from sensor/camera logs
    + Pre-built frontend (no Node.js needed on NUC)
    + Docker CE + Mosquitto 2.0 installed offline from bundled pool
    + Customer mobile app API (Expo mobile app support)
    + External API gateway with webhook dispatch

  Previous — v1.0 (.deb package):
    + FastAPI backend, React dashboard, MQTT, WebSocket
    + Session management, admin controls
    + Debian .deb package installer


================================================================================
  Cloud IoT Marina Pedestal Management System — NUC Release v2.0
  Lika Digital — https://github.com/Lika-Digital/Cloud_IOT
================================================================================
