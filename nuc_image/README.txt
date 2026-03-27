================================================================================
  Cloud IoT Marina Pedestal Management System
  NUC Installation Guide — Release v2.0
  Created by Lika Digital — info@lika.digital
================================================================================

OVERVIEW
─────────
Two-phase installation:

  PHASE 1  Install Ubuntu Server 24.04 LTS (standard, from Ubuntu ISO)
  PHASE 2  Run ubuntu-install.sh — installs and configures all Cloud IoT software

Internet connection is required during Phase 2 (packages downloaded from internet).
After install the NUC runs fully standalone on your LAN.


MINIMUM SYSTEM REQUIREMENTS
────────────────────────────
  Hardware:   Intel NUC (8th generation or newer)
  CPU:        Intel Core i3 (64-bit, 2+ cores)
  RAM:        8 GB DDR4 (minimum)
  Storage:    64 GB eMMC, NVMe, or SSD
  Network:    Ethernet (wired) connected to the internet during install
  USB:        1x USB 3.0 port (for Ubuntu installer — 8 GB minimum)
  BIOS:       UEFI firmware — Secure Boot must be DISABLED

TESTED HARDWARE
────────────────
  ASUS NUC 13 (BNUC13BRF) — eMMC storage (/dev/mmcblk0)
  Ubuntu Server 24.04 LTS installer handles eMMC correctly with no extra config.


================================================================================
  PHASE 1 — INSTALL UBUNTU SERVER 24.04 LTS
================================================================================

STEP 1 — DOWNLOAD UBUNTU SERVER ISO

  Go to:  https://ubuntu.com/download/server
  Download: Ubuntu Server 24.04 LTS (ubuntu-24.04-live-server-amd64.iso)


STEP 2 — FLASH ISO TO USB DRIVE (minimum 8 GB)

  Windows (easiest):
    1. Download Rufus from https://rufus.ie (free, no install needed)
    2. Insert USB drive
    3. In Rufus:
         Device:          select your USB drive
         Boot selection:  click SELECT -> choose ubuntu-24.04-live-server-amd64.iso
         Partition scheme: GPT
         Target system:    UEFI (non-CSM)
    4. Click START -> if asked about ISO mode, choose "Write in ISO Image mode"
    5. Wait for "READY" -> safely eject USB


STEP 3 — BIOS SETUP ON THE NUC

    a. Insert the USB drive into the NUC
    b. Power on -> press F2 immediately to enter BIOS setup
    c. Security -> Secure Boot -> set to DISABLED
    d. Boot -> Boot Priority Order -> move USB to first position
    e. Press F10 -> Save and Exit


STEP 4 — UBUNTU SERVER INSTALLER (interactive)

  The Ubuntu installer starts. Follow these screens:

  Language:
    -> English

  Keyboard:
    -> English (US) or your layout

  Type of install:
    -> Ubuntu Server  (NOT "minimized", NOT Desktop)

  Network:
    -> Leave as DHCP — the installer will auto-detect your ethernet
    -> Press Done

  Storage:
    -> "Use an entire disk"
    -> Select the disk shown (eMMC shows as /dev/mmcblk0, NVMe as /dev/nvme0n1)
    -> Leave LVM option as default
    -> Done -> Continue on the destructive action warning

  Profile setup:
    -> Your name:    anything (e.g. Cloud IoT)
    -> Server name:  marina-iot
    -> Username:     cloud-iot
    -> Password:     choose a strong password (you will need this for SSH)

  SSH Setup:
    -> Check "Install OpenSSH server"   <- IMPORTANT
    -> "Allow password authentication over SSH" -> leave ON
    -> Done

  Featured snaps:
    -> Do NOT select anything
    -> Done

  Ubuntu Pro:
    -> Skip -> Continue without Ubuntu Pro

  Installing system:
    -> Wait 5-10 minutes for installation to complete

  Reboot:
    -> "Reboot Now" appears -> press Enter
    -> When prompted "Remove installation medium" -> pull out the USB -> press Enter

  After reboot you will see a text login prompt.
  Log in with the username and password you set above.

  IMPORTANT: Ubuntu may store the username with an underscore internally.
  If "cloud-iot" is rejected at SSH login, try "cloud_iot" (underscore).


================================================================================
  PHASE 2 — INSTALL CLOUD IOT SOFTWARE
================================================================================

STEP 5 — VERIFY INTERNET CONNECTION

  Log in to the NUC and run:
    ping -c 3 google.com

  You should see replies. If not, check your ethernet cable and router.


STEP 6 — CLONE THE REPOSITORY

    git clone https://github.com/Lika-Digital/Cloud_IOT.git
    cd Cloud_IOT
    git checkout nuc-iot
    git pull origin nuc-iot


STEP 7 — RUN THE INSTALL SCRIPT

    sudo bash nuc_image/ubuntu-install.sh

  The script runs an interactive wizard. Answer each prompt:

  STEP 1: NETWORK
    Configure static IP? [y/N]
      -> n  (DHCP is fine — check router for NUC IP after reboot)
      -> y  if you want a fixed IP (you will be asked for IP/gateway/DNS)
    Hostname:  marina-iot  (or press Enter for default)

  STEP 2: ADMIN ACCOUNT
    Admin email:     e.g. admin@marina.local
    Admin password:  min 8 characters — type it, press Enter, confirm it

  STEP 3: MARINA INFORMATION
    Marina/company name, address, phone, email
    Press Enter to skip any optional field

  STEP 4: SMTP (optional)
    Configure SMTP? [y/N]  -> n to skip
    If skipped: 2FA OTP codes print to the system log (see LOGIN section)

  STEP 5: CONFIRM
    Review the summary -> y to proceed

  The script then runs automatically (~10-15 minutes):
    OK  Installs Docker CE, Python 3, Node.js, nginx
    OK  Pulls Eclipse Mosquitto 2.0 Docker image
    OK  Builds the React frontend
    OK  Installs Python packages into virtual environment
    OK  Writes .env configuration
    OK  Configures nginx reverse proxy
    OK  Creates and enables systemd services
    OK  Configures network (static IP if selected)
    OK  Installs cloud-iot management CLI

  The NUC reboots automatically when done.


================================================================================
  FIRST LOGIN
================================================================================

FIND THE NUC IP ADDRESS
  Option A — on the NUC screen after login:
    ip a
    Look for "inet" under the ethernet interface (e.g. enp3s0 or enp88s0)

  Option B — check your router's DHCP client list

ACCESS THE DASHBOARD
  Open any browser on the same network:
    http://<NUC-IP>

LOGIN PROCESS (2-Factor Authentication)
  1. Enter your admin email and password on the login page
  2. The system sends a one-time OTP code

  If SMTP is NOT configured, the OTP code appears in the backend log.
  To retrieve it, SSH into the NUC and run:

    sudo journalctl -u cloud-iot-backend -f

  Then submit the login form in the browser — watch the log for the OTP code.
  Enter that code in the browser to complete login.

SSH REMOTE ACCESS
  From Windows PowerShell or any terminal:
    ssh cloud_iot@<NUC-IP>

  Note: if you typed "cloud-iot" during Ubuntu install, SSH uses "cloud_iot"
  (Ubuntu converts hyphens to underscores in usernames).


================================================================================
  POST-INSTALLATION MANAGEMENT
================================================================================

  SSH into the NUC and use the built-in CLI:

    sudo cloud-iot status            Check all service status
    sudo cloud-iot start             Start all services
    sudo cloud-iot stop              Stop all services
    sudo cloud-iot restart           Restart all services
    sudo cloud-iot logs backend      Live backend log (Ctrl+C to exit)
    sudo cloud-iot logs nginx        nginx error log
    sudo cloud-iot logs mqtt         MQTT broker log
    sudo cloud-iot config            Edit .env (auto-restarts backend)
    sudo cloud-iot ip                Show current IP address

  View configuration:
    sudo cat /opt/cloud-iot/backend/.env


NETWORK PORTS
──────────────
    80    HTTP  — Web dashboard + API (nginx)
    22    TCP   — SSH management
    1883  MQTT  — Arduino Opta connection
    8000  HTTP  — FastAPI backend (internal only — do NOT expose externally)


DIRECTORY STRUCTURE (on installed NUC)
────────────────────────────────────────
    /opt/cloud-iot/               Application root
    /opt/cloud-iot/backend/       FastAPI + Python venv + SQLite databases
    /opt/cloud-iot/frontend/dist/ Pre-built React app (served by nginx)
    /opt/cloud-iot/backend/.env   Configuration (admin credentials, MQTT, SMTP)
    /var/log/cloud-iot/           Application logs
    /var/log/cloud-iot-install.log  Full install log


ARDUINO OPTA CONNECTION
─────────────────────────
  MQTT broker runs on the NUC at port 1883.
  Configure the Arduino Opta with:
    Broker host: <NUC-IP>
    Broker port: 1883
    Authentication: none (anonymous allowed)


MOBILE APP SETUP
─────────────────
  In mobile/.env set:
    EXPO_PUBLIC_API_URL=http://<NUC-IP>
    EXPO_PUBLIC_WS_URL=ws://<NUC-IP>


SECURITY NOTES (production)
─────────────────────────────
  • Change admin password after first login via the web UI
  • Enable SSH key auth and disable password SSH:
      ssh-copy-id cloud_iot@<NUC-IP>
      sudo nano /etc/ssh/sshd_config  -> PasswordAuthentication no
      sudo systemctl restart ssh
  • Firewall:
      sudo ufw allow 22/tcp
      sudo ufw allow 80/tcp
      sudo ufw allow from <arduino-ip> to any port 1883
      sudo ufw enable


TROUBLESHOOTING
────────────────
  Backend not starting:
    sudo journalctl -u cloud-iot-backend -n 50 --no-pager

  All services status:
    sudo cloud-iot status

  Full install log:
    sudo cat /var/log/cloud-iot-install.log

  OTP not received by email:
    sudo journalctl -u cloud-iot-backend -f
    (submit login form — OTP code appears in the log)

  SSH "Permission denied":
    Try username with underscore: ssh cloud_iot@<NUC-IP>
    Reset password on NUC screen:  sudo passwd cloud_iot

  Backend fails with "No module named ...":
    sudo journalctl -u cloud-iot-backend -n 30 --no-pager
    (report the module name — likely a missing Python package)

  .env has wrong admin password (split across two lines):
    sudo nano /opt/cloud-iot/backend/.env
    Fix DEFAULT_ADMIN_PASSWORD= to be on one line
    sudo rm /opt/cloud-iot/backend/data/users.db
    sudo systemctl restart cloud-iot-backend


================================================================================
  RELEASE NOTES — v2.0
================================================================================

  v2.0 (Ubuntu Server 24.04 LTS — internet-connected install):
    + Ubuntu Server 24.04 LTS — reliable eMMC/NVMe/SSD support out of the box
    + Interactive install wizard (network, admin, marina info, SMTP)
    + Docker CE + Eclipse Mosquitto 2.0 MQTT broker
    + FastAPI backend with JWT 2FA authentication
    + React 18 admin dashboard (pre-built, served via nginx)
    + Customer mobile app REST + WebSocket API
    + SQLite WAL mode for safe concurrent access
    + Systemd services with auto-restart on failure
    + cloud-iot management CLI (start/stop/logs/config/ip)
    + External API gateway with webhook dispatch
    + Real-time chat & support messaging (WebSocket)
    + Push notifications via Expo push API
    + Customer billing, contracts, service orders

  v1.0 (.deb package — legacy):
    + FastAPI backend, React dashboard, MQTT, WebSocket
    + Session management, admin controls
    + Debian .deb package installer


================================================================================
  Cloud IoT Marina Pedestal Management System — v2.0
  Lika Digital — https://github.com/Lika-Digital/Cloud_IOT
================================================================================
