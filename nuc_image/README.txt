================================================================================
  Cloud IoT Marina Pedestal Management System
  NUC Bootable Image — Release v2.0
  Created by Lika Digital — info@lika.digital
================================================================================

CONTENTS OF THIS IMAGE
───────────────────────
This image installs a fully configured Intel NUC server running:

  Operating System:
    • Debian 12 "Bookworm" (minimal server install)
    • OpenSSH server (for remote management)
    • nginx (reverse proxy + frontend web server)

  Cloud IoT Application (v2.0):
    • FastAPI backend            — REST API, WebSocket, MQTT bridge, JWT auth
    • React 18 frontend          — Admin dashboard (served via nginx)
    • Customer mobile API        — REST endpoints for the Expo mobile app
    • SQLite databases           — IoT data + user/auth data (auto-migrated)
    • Invoice & contract system  — PDF generation via ReportLab
    • Chat & support messaging   — Real-time via WebSocket
    • Push notification dispatch — Expo push API integration
    • External API gateway       — Webhook dispatch for third-party integration
    • Camera / ship detection    — ML worker (Docker, optional ONNX models)

  Runtime Dependencies (auto-installed):
    • Python 3.11+               — Backend runtime
    • Node.js 20 LTS             — Frontend build tool
    • Docker CE                  — MQTT broker + ML worker containers
    • Eclipse Mosquitto 2.0      — MQTT broker (via Docker)
    • ReportLab, httpx, PyJWT, pydantic, SQLAlchemy, paho-mqtt, zeroconf ...


MINIMUM SYSTEM REQUIREMENTS
────────────────────────────
  Hardware:   Intel NUC (8th generation or newer)
  CPU:        Intel Core i3 (64-bit, 2+ cores)
  RAM:        8 GB DDR4 (minimum)
  Storage:    120 GB SSD — M.2 NVMe or 2.5" SATA (HDD not recommended)
  Network:    1× Gigabit Ethernet (wired, required)
  USB:        1× USB 3.0 port (for installation media)
  BIOS:       UEFI firmware — Secure Boot must be DISABLED

  Internet:   Required during installation (downloads ~1.5 GB of packages)
              Not required after installation.

RECOMMENDED HARDWARE
─────────────────────
  Intel NUC 11 (NUC11TNHi5) or Intel NUC 12 (NUC12WSHi5)
  CPU:     Intel Core i5 / i7
  RAM:     16 GB DDR4
  Storage: 256 GB NVMe SSD
  Network: Gigabit Ethernet + Wi-Fi (for redundancy)


INSTALLATION INSTRUCTIONS
──────────────────────────

STEP 1 — PREPARE INSTALLATION MEDIA
  Build the ISO (requires Linux or WSL with xorriso and wget):

    cd nuc_image/
    chmod +x build_iso.sh
    ./build_iso.sh

  Flash to a USB drive (minimum 2 GB capacity):

    Linux / macOS:
      sudo dd if=cloud-iot-nuc-v2.0.iso of=/dev/sdX bs=4M status=progress
      (replace /dev/sdX with your USB drive — use 'lsblk' to identify)

    Windows:
      Use Rufus (https://rufus.ie)
        → Device: your USB drive
        → Boot selection: cloud-iot-nuc-v2.0.iso
        → Partition scheme: GPT
        → Target system: UEFI (non-CSM)
        → Click START

STEP 2 — BIOS SETUP ON NUC
  a. Insert USB drive into NUC
  b. Power on NUC and press F2 to enter BIOS
  c. Navigate to:  Security → Secure Boot → DISABLE
  d. Navigate to:  Boot → Boot Priority → move USB drive to position 1
  e. Press F10 to save and exit

STEP 3 — AUTOMATIC DEBIAN INSTALLATION
  • The NUC boots from USB into Debian installer
  • Installation is fully automated — no interaction needed
  • Duration: 5–15 minutes depending on internet speed
  • When prompted "Remove installation media" — pull out the USB
  • System reboots automatically into Debian

STEP 4 — FIRST BOOT SETUP WIZARD (interactive)
  On first boot, an interactive wizard runs on the screen (TTY1).
  You will be asked for the following information:

  ┌─ NETWORK ───────────────────────────────────────────┐
  │  Hostname              e.g. marina-iot-01           │
  │  Network interface     auto-detected (select)       │
  │  Static IP address     e.g. 192.168.1.100           │
  │  Subnet mask           e.g. 255.255.255.0           │
  │  Default gateway       e.g. 192.168.1.1             │
  │  DNS servers           e.g. 8.8.8.8 8.8.4.4        │
  └─────────────────────────────────────────────────────┘
  ┌─ ADMIN ACCOUNT ─────────────────────────────────────┐
  │  Admin email           e.g. admin@marina.local      │
  │  Admin password        min. 8 characters            │
  └─────────────────────────────────────────────────────┘
  ┌─ MARINA INFORMATION (for PDF invoices) ─────────────┐
  │  Marina / company name                              │
  │  Street address                                     │
  │  Phone number                                       │
  │  Contact email                                      │
  │  Portal name           e.g. Marina IoT Portal       │
  └─────────────────────────────────────────────────────┘
  ┌─ SMTP EMAIL — OPTIONAL ─────────────────────────────┐
  │  If configured: OTP codes are sent by email         │
  │  If skipped:   OTP codes print to system log        │
  │    (readable with: sudo journalctl -u cloud-iot-backend) │
  └─────────────────────────────────────────────────────┘

  Installation and configuration runs automatically after the wizard.
  Duration: 10–20 minutes.
  System reboots automatically when done.

STEP 5 — ACCESS THE SYSTEM
  After reboot, open in a web browser:

    Admin Dashboard:   http://<your-configured-ip>
    Login:             the email and password you entered in the wizard

  SSH remote access:
    ssh cloud-iot@<your-configured-ip>
    (password set in wizard, change it with: passwd)

  MQTT broker (for Arduino Opta):
    Host: <your-configured-ip>
    Port: 1883

  Mobile customer app:
    Set EXPO_PUBLIC_API_URL=http://<your-configured-ip> in mobile/.env


POST-INSTALLATION MANAGEMENT
──────────────────────────────
  SSH into the NUC and use the management CLI:

    sudo cloud-iot status            Check all service status
    sudo cloud-iot start             Start all services
    sudo cloud-iot stop              Stop all services
    sudo cloud-iot restart           Restart all services
    sudo cloud-iot logs backend      View backend logs (live)
    sudo cloud-iot logs nginx        View nginx error logs
    sudo cloud-iot logs mqtt         View MQTT broker logs
    sudo cloud-iot config            Edit .env configuration
    sudo cloud-iot update            Pull latest code from GitHub, rebuild


NETWORK PORTS
──────────────
    80    HTTP  — Web dashboard and API (nginx, public)
    22    TCP   — SSH remote management (restrict to admin IPs)
    1883  MQTT  — Arduino Opta device connection (restrict to device IP)
    8000  HTTP  — FastAPI backend (internal, proxied by nginx, do not expose)
    8001  HTTP  — ML worker (internal, Docker, do not expose)


DIRECTORY STRUCTURE (on installed system)
──────────────────────────────────────────
    /opt/cloud-iot/          Application root
    /opt/cloud-iot/backend/  FastAPI backend + Python venv + databases
    /opt/cloud-iot/frontend/ React source + built dist/
    /opt/cloud-iot/backend/.env   Configuration file (sensitive — root only)
    /var/log/cloud-iot/      Application logs


SECURITY NOTES
───────────────
  • Change the admin password immediately after first login
  • SSH key-based authentication recommended for production:
      ssh-copy-id cloud-iot@<nuc-ip>
      then set: PasswordAuthentication no in /etc/ssh/sshd_config
  • MQTT port 1883 should be firewalled to Arduino Opta IP only:
      sudo ufw allow from <arduino-ip> to any port 1883
      sudo ufw allow 80/tcp
      sudo ufw allow 22/tcp
      sudo ufw enable
  • Do not expose port 8000 externally — use nginx proxy only
  • The .env file contains JWT_SECRET — keep it confidential


INCLUDED SOFTWARE VERSIONS
────────────────────────────
    Debian:          12 "Bookworm" (LTS until June 2028)
    Cloud IoT App:   2.0
    Python:          3.11+
    Node.js:         20 LTS
    Docker CE:       Latest stable
    nginx:           1.22+
    Mosquitto MQTT:  2.0 (Docker)
    FastAPI:         0.115.x
    React:           18.x


TROUBLESHOOTING
────────────────
  If the first-boot wizard does not appear:
    Login as: cloud-iot  Password: ChangeOnFirstLogin
    Run manually: sudo /opt/cloud-iot-setup/firstboot-setup.sh

  To view installation logs:
    sudo cat /var/log/cloud-iot-setup.log

  If services are not running after install:
    sudo cloud-iot status
    sudo cloud-iot start

  To re-run the app installer (without re-installing Debian):
    sudo /opt/cloud-iot-setup/install-cloud-iot.sh --reconfigure


RELEASE NOTES — v2.0
──────────────────────
  New in v2.0 (NUC Release):
    + Bootable NUC image with automated Debian 12 installation
    + Interactive first-boot network and configuration wizard
    + Customer mobile app backend (full REST API)
    + Invoice and contract management with PDF generation
    + Chat and operator messaging
    + Push notification dispatch via Expo Push API
    + External API gateway with webhook support
    + Berth booking and camera integration
    + NUC deployment via single bootable USB

  Previous — v1.0 (.deb package release):
    + FastAPI backend, React dashboard, MQTT, WebSocket
    + Session management, admin controls
    + Debian .deb package installer


================================================================================
  Cloud IoT Marina Pedestal Management System — NUC Release v2.0
  © 2025 Lika Digital — https://github.com/Lika-Digital/Cloud_IOT
================================================================================
