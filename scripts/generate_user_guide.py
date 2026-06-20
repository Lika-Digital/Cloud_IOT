"""Generate the Marina Operator User Guide as a .docx in docs/.

This is a one-shot generator. Re-run whenever the menu structure changes;
keep the prose in this script as the source of truth.
"""
from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "User Guide.docx"


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    h = doc.add_heading(text, level=level)
    if level == 0:
        for run in h.runs:
            run.font.color.rgb = RGBColor(0x10, 0x3D, 0x6E)


def add_paragraph(doc: Document, text: str, bold: bool = False) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(11)


def add_bullet(doc: Document, text: str) -> None:
    doc.add_paragraph(text, style="List Bullet")


def add_steps(doc: Document, steps: list[str]) -> None:
    for s in steps:
        doc.add_paragraph(s, style="List Number")


def add_callout(doc: Document, label: str, body: str) -> None:
    p = doc.add_paragraph()
    r1 = p.add_run(f"{label}: ")
    r1.bold = True
    r1.font.color.rgb = RGBColor(0xC0, 0x39, 0x2B)
    r2 = p.add_run(body)
    r2.font.size = Pt(11)


def build() -> None:
    doc = Document()

    # ── Title page ──────────────────────────────────────────────────────────
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    tr = title.add_run("Smart Pedestal IoT Management")
    tr.bold = True
    tr.font.size = Pt(28)
    tr.font.color.rgb = RGBColor(0x10, 0x3D, 0x6E)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    sr = sub.add_run("Marina Operator – User Guide")
    sr.italic = True
    sr.font.size = Pt(16)

    ver = doc.add_paragraph()
    ver.alignment = WD_ALIGN_PARAGRAPH.CENTER
    vr = ver.add_run("Version 3.32 · Cloud_IOT Operator Dashboard")
    vr.font.size = Pt(11)

    doc.add_paragraph()
    doc.add_paragraph()

    # ── Welcome ─────────────────────────────────────────────────────────────
    add_heading(doc, "1. Welcome", level=1)
    add_paragraph(
        doc,
        "This guide walks you through the Marina Operator dashboard – the web "
        "interface you use from any browser to monitor and control the marina "
        "pedestals (electricity sockets, water valves, cabinet door, camera) "
        "and to manage customers, contracts, and billing."
    )
    add_paragraph(
        doc,
        "The dashboard is designed around the daily rhythm of a marina: see "
        "what is happening on the dock right now, approve or stop sessions when "
        "needed, look up history when a customer asks, and keep an eye on "
        "system health. The mobile customer app is documented separately and is "
        "out of scope here."
    )

    add_heading(doc, "Roles", level=2)
    add_bullet(doc, "Admin – full access to every menu, can change settings, "
                    "approve/stop sessions, manage customers, set prices.")
    add_bullet(doc, "Monitor – read-only view of Dashboard, Analytics and "
                    "History. Cannot change anything. Cannot see admin-only menus.")

    # ── Sign in ─────────────────────────────────────────────────────────────
    add_heading(doc, "2. Signing in", level=1)
    add_paragraph(
        doc,
        "Every operator login uses two-factor authentication: your password plus "
        "a 6-digit code from an authenticator app on your phone (Google "
        "Authenticator, Microsoft Authenticator, 1Password, etc.). The "
        "authenticator works fully offline – no email or internet is needed."
    )
    add_heading(doc, "2.1 First login (new account)", level=2)
    add_steps(doc, [
        "Open the dashboard URL in your browser (Chrome, Edge, or Firefox).",
        "Enter your email and the temporary password your administrator gave "
        "you, then click Continue.",
        "Choose a new password (required on first login) and confirm it.",
        "A QR code appears. Open your authenticator app, choose Add / Scan QR "
        "code, and scan it. (Can't scan? Enter the key shown manually.)",
        "Your app now shows a 6-digit code that changes every ~30 seconds. Type "
        "the current code to finish – you are now logged in.",
    ])
    add_heading(doc, "2.2 Normal login (afterwards)", level=2)
    add_steps(doc, [
        "Enter your email and password and click Continue.",
        "Type the current 6-digit code from your authenticator app. It submits "
        "automatically once you type the sixth digit.",
    ])
    add_callout(doc, "Lost your phone / authenticator",
                "Ask an administrator to reset your two-factor in Settings -> "
                "Operator Accounts -> Reset 2FA. On your next login you will set "
                "up a new authenticator with a fresh QR code. Your password is "
                "unchanged.")
    add_paragraph(
        doc,
        "Your session stays active for two hours, after which you will be "
        "asked to sign in again. Use the Sign out link at the bottom of the "
        "left menu when you finish your shift on a shared computer."
    )

    # ── Layout overview ─────────────────────────────────────────────────────
    add_heading(doc, "3. Dashboard layout overview", level=1)
    add_paragraph(
        doc,
        "Every page shares the same frame:"
    )
    add_bullet(doc, "Left sidebar – the main menu. Each item has an icon and "
                    "a label. Items only visible to admins are hidden if you "
                    "are signed in as Monitor.")
    add_bullet(doc, "Top right – your email, role, and a Sign out link.")
    add_bullet(doc, "Bottom left – two small status dots that show whether the "
                    "browser is connected to the dashboard service (WebSocket) "
                    "and whether the pedestal hardware is online (Pedestal). "
                    "Both should be green during normal operation.")
    add_bullet(doc, "Toast tray (bottom right) – short pop-up messages about "
                    "events such as a new pedestal being discovered. They "
                    "disappear after about ten seconds.")

    # ── Menu reference ──────────────────────────────────────────────────────
    add_heading(doc, "4. Menu reference", level=1)
    add_paragraph(doc, "The left sidebar contains the following items:")

    # Dashboard
    add_heading(doc, "4.1 Dashboard ⚡", level=2)
    add_paragraph(doc, "Your home page. Shows every pedestal in the marina as a "
                       "card with its name, location, and live status (green = "
                       "online, grey = offline). Yellow rings on a card mean a "
                       "socket is in pending state (a plug is inserted but the "
                       "session has not yet been activated). Red means a fault.")
    add_paragraph(doc, "Click a pedestal card to open its detail view (described "
                       "in the next section).")
    add_callout(doc, "Auto-discovery",
                "When a new pedestal connects to the marina network for the first "
                "time, it appears here automatically – no manual setup is "
                "required. You will see a short toast at the bottom right "
                "announcing the discovery.")

    # Analytics
    add_heading(doc, "4.2 Analytics 📊", level=2)
    add_paragraph(doc, "Charts and totals about consumption and sessions:")
    add_bullet(doc, "Daily and monthly electricity consumption (kWh) and water "
                    "consumption (litres).")
    add_bullet(doc, "Session counts and average session duration.")
    add_bullet(doc, "Per-pedestal and per-socket breakdowns – use the filter at "
                    "the top of the page to drill into a single cabinet.")
    add_paragraph(doc, "Use this page for monthly reports, trend spotting, or "
                       "to answer 'how much did pedestal MAR_KRK_ORM_01 deliver "
                       "this week?'.")

    # History
    add_heading(doc, "4.3 History 📋", level=2)
    add_paragraph(doc, "A searchable log of every completed session: date, "
                       "customer, pedestal, socket or valve, energy or water "
                       "delivered, duration, and the reason a session ended "
                       "(operator stop, plug removed, breaker trip, etc.).")
    add_paragraph(doc, "Use the search field to look up a customer name or "
                       "pedestal. Click a row to see all readings recorded "
                       "during that session.")

    # Billing
    add_heading(doc, "4.4 Billing 💰 (admin only)", level=2)
    add_paragraph(doc, "Two areas:")
    add_bullet(doc, "Configuration – set the price per kWh of electricity and "
                    "per litre of water. The price applies from the moment "
                    "you save it; sessions in progress keep their original price.")
    add_bullet(doc, "Spending – see total turnover for the marina, broken down "
                    "by customer. Click a customer row to see every invoice "
                    "that customer has paid (or owes).")
    add_callout(doc, "Unattributed water flow",
                "If a water valve was opened automatically after a diagnostic "
                "(see Control Center) the flow is recorded but cannot be "
                "billed because there is no customer attached. The Spending "
                "page does not double-count this; it shows up in History "
                "with the UNATTRIBUTED tag.")

    # Customers
    add_heading(doc, "4.5 Customers 👥 (admin only)", level=2)
    add_paragraph(doc, "Manage the marina's customer accounts:")
    add_bullet(doc, "Search and view profile details: name, ship name, email.")
    add_bullet(doc, "Open the chat panel for direct messaging with a customer "
                    "who is using the mobile app. Unread message count appears "
                    "on the menu icon.")
    add_bullet(doc, "Disable or delete an account if needed.")
    add_paragraph(doc, "Customer sign-up itself happens through the mobile "
                       "app; you do not normally create accounts here.")

    # Contracts
    add_heading(doc, "4.6 Contracts 📝 (admin only)", level=2)
    add_paragraph(doc, "Manage Berth Service Agreements:")
    add_bullet(doc, "Edit the master contract template (legal text shown to "
                    "every customer when they sign up).")
    add_bullet(doc, "View signed contracts per customer, including their "
                    "validity period and the PDF copy with the customer's "
                    "signature.")
    add_bullet(doc, "Issue or revoke a contract when a customer arrives or "
                    "leaves the marina.")

    # Berth Occupancy
    add_heading(doc, "4.7 Berth Occupancy ⚓ (admin only)", level=2)
    add_paragraph(doc, "Live camera-based view of which berths are occupied. "
                       "The system uses image analysis to detect whether a vessel "
                       "is at each berth and compares it against the reference "
                       "photo you set up at installation.")
    add_bullet(doc, "Green tile = berth is free.")
    add_bullet(doc, "Blue tile = vessel detected, matches the reference (your "
                    "long-term contract holder is at home).")
    add_bullet(doc, "Yellow tile = vessel detected but does not match (a "
                    "different boat or guest in someone else's berth).")
    add_paragraph(doc, "Click a berth tile to see the latest captured frame "
                       "with detection overlay and the per-berth confidence score.")

    # System Health
    add_heading(doc, "4.8 System Health 🔧 (admin only)", level=2)
    add_paragraph(doc, "Operational dashboard for the technical side of the system:")
    add_bullet(doc, "Backend service status, uptime, MQTT broker connectivity.")
    add_bullet(doc, "Per-pedestal health grid: Opta connected, camera reachable, "
                    "temperature/moisture sensor reachable, last heartbeat.")
    add_bullet(doc, "Hardware alarms list (door open, sensor faults, breaker "
                    "trips). The icon turns red when there is an active warning "
                    "or critical alarm so you notice from any page.")
    add_bullet(doc, "Meter Load Alarms (v3.11) – live socket load alarms "
                    "across all pedestals. Yellow rows are warnings (load "
                    "above the warning threshold); red flashing rows are "
                    "critical (load above the critical threshold). Each row "
                    "has Acknowledge (silences the badge but keeps the alarm "
                    "visible) and Resolve (manually closes the alarm). "
                    "Alarms also auto-resolve when the load drops back below "
                    "the threshold.")
    add_bullet(doc, "Recent error log – the last 7 days of warnings and errors. "
                    "Filter by category (system, hardware, network) and by "
                    "severity. The badge on the menu icon shows new errors "
                    "you have not yet viewed.")
    add_paragraph(doc, "Use this page first when something seems wrong. Most "
                       "issues will be visible here long before a customer "
                       "notices.")

    # API Gateway
    add_heading(doc, "4.9 API Gateway 🔌 (admin only)", level=2)
    add_paragraph(doc, "External integration management. If you connect the "
                       "marina to an ERP system, this is where you turn it on:")
    add_bullet(doc, "Enable or disable the gateway (master switch).")
    add_bullet(doc, "Generate or rotate the API key the ERP uses to "
                    "authenticate.")
    add_bullet(doc, "Tick which endpoints the ERP is allowed to call (sessions, "
                    "billing, breaker management, etc.) and which events the "
                    "ERP receives via webhook (session created, breaker "
                    "alarm, etc.).")
    add_bullet(doc, "Verify connectivity – the page runs a quick test and "
                    "shows green/red dots so you know the integration is alive.")
    add_paragraph(doc, "The page is grouped by category so you can find related "
                       "endpoints together: Sessions, Controls, Billing, "
                       "Breaker Management, Camera, Berths, Discovery, etc.")

    # Settings
    add_heading(doc, "4.10 Settings ⚙️ (admin only)", level=2)
    add_paragraph(doc, "Marina-wide preferences and infrastructure settings:")
    add_bullet(doc, "Marina name, address, default time zone.")
    add_bullet(doc, "MQTT broker host and port (used by the pedestals to talk "
                    "to the system – usually 127.0.0.1:1883 on the NUC).")
    add_bullet(doc, "Operator Accounts – create operators, change roles, and "
                    "Reset 2FA for anyone who loses their authenticator.")
    add_bullet(doc, "Two-Factor Authentication – manage your own authenticator app.")
    add_bullet(doc, "Email server settings (optional – used for customer "
                    "notifications; login no longer needs email).")
    add_bullet(doc, "Pending session timeout – how long a pending session "
                    "waits for an operator decision before being auto-denied.")
    add_bullet(doc, "Diagnostic and discovery options.")

    # ── Pedestal detail view ────────────────────────────────────────────────
    add_heading(doc, "5. Working with a single pedestal", level=1)
    add_paragraph(doc, "From the Dashboard, click any pedestal card to open its "
                       "detail view. The view has three main areas:")

    add_heading(doc, "5.1 Pedestal picture overlay", level=2)
    add_paragraph(doc, "A photo of the cabinet with overlays on each socket, "
                       "valve, the door, and the camera. Each circle changes "
                       "colour to show its live state:")
    add_bullet(doc, "Green – session active, electricity or water flowing.")
    add_bullet(doc, "Yellow – plug inserted, awaiting activation.")
    add_bullet(doc, "Grey – idle, nothing connected.")
    add_bullet(doc, "Red ⚡ overlay – breaker has tripped on this socket. The "
                    "circle still shows its base colour underneath.")
    add_paragraph(doc, "Hover over a circle to see a quick label. Click it to "
                       "open the detail panel for that outlet.")

    add_heading(doc, "5.2 Quick Status panel", level=2)
    add_paragraph(doc, "A compact summary on the right of the picture: which "
                       "socket is currently active, who the customer is, and "
                       "how much energy or water has been consumed in this "
                       "session so far. Updates live without page reload.")

    add_heading(doc, "5.3 Control Center", level=2)
    add_paragraph(doc, "The full control panel underneath. This is where you "
                       "spend most of your operator time. It has these "
                       "sections from top to bottom:")

    add_bullet(doc, "Feedback toasts – short success/error messages for "
                    "commands you just sent.")
    add_bullet(doc, "Breaker alarm banner (red) – appears when one or more "
                    "circuit breakers on this pedestal have tripped. Lists "
                    "the affected sockets (Q1, Q3, …). Includes an "
                    "Acknowledge button that hides the banner for your "
                    "current browser session.")
    add_bullet(doc, "Socket Settings (v3.26) – choose how customers start a "
                    "session for this cabinet: QR (default) or NFC. In QR mode "
                    "you get the printable QR labels for each socket (Download a "
                    "single PNG, Download All as a ZIP, or Regenerate a fresh "
                    "image). In NFC mode you provision NFC tags per socket "
                    "instead. See 10.6 for the full NFC workflow.")
    add_bullet(doc, "Cabinet Status – Opta connected indicator, uptime, "
                    "current door state, MQTT heartbeat sequence number.")
    add_bullet(doc, "Sockets Q1-Q4 – one card per electricity socket (see "
                    "below).")
    add_bullet(doc, "Water valves V1-V2 – one card per valve (see below).")
    add_bullet(doc, "LED – turn the cabinet's (white) identification light ON "
                    "or OFF. The badge shows the real state confirmed by the "
                    "cabinet: ON, OFF, or “Switching…” until the firmware "
                    "acknowledges your command (v3.27). If it stays “Switching…”, "
                    "the cabinet did not confirm — check the link.")
    add_bullet(doc, "LED Schedule (v3.10) – set a daily on time and off time "
                    "for the pedestal LED. Pick the colour and the days of "
                    "the week. Backend fires the on/off commands automatically "
                    "at the configured times; a small Test LED button lets "
                    "you confirm the wiring without waiting for the schedule.")
    add_bullet(doc, "Diagnostic – run a hardware self-test on the pedestal "
                    "and see per-sensor pass/fail. Takes about 12 seconds.")
    add_bullet(doc, "Reset – reboot the cabinet (use with care; requires a "
                    "confirmation click).")
    add_bullet(doc, "Event log and ACK log – recent firmware events and "
                    "command acknowledgements; useful when troubleshooting.")

    # Socket card
    add_heading(doc, "5.4 The socket card (Q1 – Q4)", level=2)
    add_paragraph(doc, "Each electricity socket has its own card. From top to "
                       "bottom you see:")
    add_bullet(doc, "Socket label and current state badge (active, pending, "
                    "idle, fault).")
    add_bullet(doc, "AUTO badge – green, visible when auto-activation is "
                    "turned on for this socket.")
    add_bullet(doc, "Mobile owner indicator (📱) – present when the active "
                    "session was claimed by a customer through the mobile app.")
    add_bullet(doc, "QR button – open a printable PNG of this socket's QR code.")
    add_bullet(doc, "Hardware status line – live readings reported by the Opta.")
    add_bullet(doc, "Breaker panel – coloured dot with state (Breaker OK, "
                    "TRIPPED, Resetting…), hardware metadata reported by the "
                    "Arduino (type, rating, poles, RCD), trip count, and a "
                    "History button for the last 10 breaker events on this "
                    "socket.")
    add_bullet(doc, "Reset Breaker button (red, only when state = TRIPPED) – "
                    "remotely resets the motorised circuit breaker. A "
                    "confirmation dialog appears first; you must explicitly "
                    "confirm.")
    add_bullet(doc, "Auto-activate toggle – when on, the socket automatically "
                    "becomes active two seconds after a plug is inserted. The "
                    "five preconditions (door closed, no fault, recent "
                    "heartbeat, socket not already active, no diagnostic in "
                    "the last 60 s) must pass.")
    add_bullet(doc, "Activate / Stop buttons – manual control. Activate is "
                    "available only when a plug is inserted (state = pending). "
                    "Stop replaces Activate while a session is active.")
    add_bullet(doc, "Load meter panel (v3.11) – meter type, phase count, "
                    "rated current, and a live load bar showing current draw "
                    "as a percentage of rated. Single-phase sockets show one "
                    "bar; three-phase sockets show three stacked bars (L1, "
                    "L2, L3) so you can spot phase imbalance at a glance. "
                    "Below the bars: voltage, power, power factor, frequency. "
                    "Threshold editor (admin) lets you tune warning and "
                    "critical percentages.")

    # Water valve card
    add_heading(doc, "5.5 The water valve card (V1, V2)", level=2)
    add_paragraph(doc, "Each water valve has its own card with similar "
                       "elements to the socket card:")
    add_bullet(doc, "Valve label and current state badge.")
    add_bullet(doc, "AUTO badge – green, visible when auto-activation is on. "
                    "For valves the default is on; you can switch it off "
                    "if you do not want automatic post-diagnostic opening.")
    add_bullet(doc, "UNATTRIBUTED badge – amber, visible when the active water "
                    "session has no customer attached (typically because the "
                    "valve was opened automatically after a diagnostic). Flow "
                    "is still measured but cannot be billed.")
    add_bullet(doc, "Live readings – total litres and current session litres.")
    add_bullet(doc, "Zero-flow warning banner – appears if the valve was "
                    "auto-activated and 30 seconds later the flow meter is "
                    "still reading zero. Likely a disconnected hose. The "
                    "valve stays open; you decide what to do.")
    add_bullet(doc, "Auto-activate toggle, Activate, Stop – same idea as for "
                    "sockets.")

    # ── Newer features in detail ────────────────────────────────────────────
    add_heading(doc, "5.6 LED Schedule (v3.10)", level=2)
    add_paragraph(doc, "The LED on the cabinet can be put on a daily timer. "
                       "Useful for marina ambience lighting, security visibility "
                       "after dark, or simply marking that a pedestal is in "
                       "service.")
    add_bullet(doc, "Auto LED Schedule toggle – on/off master switch. With "
                    "it off the schedule is preserved in the database but "
                    "the scheduler ignores the row.")
    add_bullet(doc, "On time / Off time – pick HH:MM in 24-hour format. "
                    "Times are interpreted in the marina's local timezone "
                    "(set once on the NUC via MARINA_TIMEZONE).")
    add_bullet(doc, "Color – pick green, blue, red, or yellow. (White is "
                    "reserved until firmware confirms it.)")
    add_bullet(doc, "Days – tick Monday through Sunday. By default all "
                    "seven days are checked.")
    add_bullet(doc, "Next On / Next Off preview – the section computes when "
                    "the scheduler will next fire and updates this preview "
                    "every minute so you can verify the configuration without "
                    "waiting for the actual fire time.")
    add_bullet(doc, "Save / Test LED / Delete Schedule buttons – Save writes "
                    "the changes; Test LED fires the configured colour on now "
                    "(no waiting for the schedule); Delete removes the schedule "
                    "entirely. After delete the LED is no longer automatically "
                    "controlled.")
    add_callout(doc, "5-minute grace window",
                "If the backend was just restarted and missed the exact tick "
                "by less than 5 minutes, the scheduler still fires the on/off "
                "command. Beyond 5 minutes the missed fire is logged in System "
                "Health and skipped.")

    add_heading(doc, "5.7 Load monitoring (v3.11)", level=2)
    add_paragraph(doc, "Each socket card shows a live load bar driven by the "
                       "real-time current reading from the socket's electric "
                       "meter. The colour of the bar reflects how close the "
                       "socket is to its rated current:")
    add_bullet(doc, "Green – load is below the warning threshold (default 60% "
                    "of rated).")
    add_bullet(doc, "Yellow – load is between warning and critical thresholds.")
    add_bullet(doc, "Red, flashing – load is above the critical threshold "
                    "(default 80% of rated). A persistent banner appears on "
                    "the socket card and admins receive a Browser Notification.")
    add_paragraph(doc, "For three-phase sockets you see three stacked bars, "
                       "one per phase, so phase imbalance is visible at a "
                       "glance. The aggregate load percentage is driven by the "
                       "bottleneck phase (max of L1, L2, L3 over rated) – this "
                       "is the safety-meaningful number.")
    add_paragraph(doc, "Under the bars you see the secondary readings: "
                       "voltage(s), real power in kW, power factor, and "
                       "frequency. Hardware Info above the bars shows the "
                       "meter model the Arduino reported, the phase count, the "
                       "rated current, and the Modbus address.")
    add_paragraph(doc, "Admins can change the warning and critical thresholds "
                       "from the same panel – two number inputs and a Save "
                       "button. Defaults are 60% / 80%; the warning value must "
                       "be strictly less than the critical value, both between "
                       "1 and 99.")
    add_callout(doc, "If you see 'Awaiting hardware configuration from device'",
                "The Arduino has not yet published its hardware configuration "
                "for this socket. The dashboard will switch to live readings "
                "automatically once it arrives. If the message persists for "
                "more than a minute or two, check System Health → Errors and "
                "ask the firmware team whether opta/config/hardware is being "
                "published.")

    # ── Common tasks ────────────────────────────────────────────────────────
    add_heading(doc, "6. Common tasks", level=1)

    add_heading(doc, "6.1 Approve a customer's electricity request", level=2)
    add_paragraph(doc, "Most of the time the system handles this automatically. "
                       "If a customer plugs in and a session needs your manual "
                       "approval, you will see a yellow PENDING badge in the "
                       "Quick Status panel and an Activate button on the socket "
                       "card. Click Activate. The breaker (if present) closes "
                       "and the session goes green.")

    add_heading(doc, "6.2 Stop an active session", level=2)
    add_paragraph(doc, "Open the pedestal, find the socket or valve card, and "
                       "click Stop. The session is closed and an invoice is "
                       "generated for the customer (if any) within seconds.")

    add_heading(doc, "6.3 Reset a tripped breaker", level=2)
    add_steps(doc, [
        "On the pedestal page, find the socket card whose breaker dot is red "
        "and pulsing.",
        "Make sure the cause of the trip has been resolved (the customer has "
        "unplugged the offending appliance, the fault has been cleared, etc.).",
        "Click Reset Breaker. A confirmation dialog appears.",
        "Click Reset Breaker again to confirm.",
        "Watch the dot. Within a few seconds it should turn yellow "
        "(Resetting…) and then green (Breaker OK). If after 15 seconds it "
        "is still red, an error toast appears – there is likely still a "
        "downstream fault.",
    ])

    add_heading(doc, "6.4 Run a diagnostic on a pedestal", level=2)
    add_steps(doc, [
        "Open the pedestal detail view.",
        "Scroll to the Diagnostic section in the Control Center and click Run.",
        "Wait up to 12 seconds. A grid appears with one row per sensor "
        "(socket 1–4, water, temperature, moisture, camera) showing OK or "
        "FAIL.",
        "If everything is green the pedestal is marked as Initialized.",
    ])
    add_callout(doc, "After a successful diagnostic",
                "Any water valve whose auto-activate is on (the default) will "
                "open about 1–2 seconds after the diagnostic completes, "
                "provided no session is already active and the valve was not "
                "manually stopped in the last 10 minutes. This is intentional "
                "– the valve is normally closed by hardware, so the flow meter "
                "tells you immediately if anything unexpected happens.")

    add_heading(doc, "6.5 Print a QR code label", level=2)
    add_steps(doc, [
        "Open the pedestal detail view.",
        "In the QR Codes section, click Download to save a single socket's "
        "PNG, or Download All for a ZIP of all four sockets.",
        "Print the PNG at 300×300 pixels (label size depends on your "
        "label printer; the image already includes the cabinet + socket "
        "caption).",
        "If a label gets damaged, click Regenerate to create fresh PNGs and "
        "download again.",
    ])

    add_heading(doc, "6.6 Set or change prices", level=2)
    add_steps(doc, [
        "Open Billing.",
        "In the Configuration card, set the price per kWh and the price per "
        "litre.",
        "Click Save. The new prices apply to every session that starts after "
        "you save. Sessions already in progress keep their original prices.",
    ])

    add_heading(doc, "6.7 Schedule the LED on a daily timer", level=2)
    add_steps(doc, [
        "Open the pedestal detail view, scroll to the Control Center.",
        "Find the LED Schedule section.",
        "Tick Auto LED Schedule.",
        "Set the On time and Off time in HH:MM. The marina-local time zone "
        "is used (configured once on the NUC).",
        "Pick the colour (green / blue / red / yellow).",
        "Tick the days of the week the schedule should run.",
        "Click Save. The Next On and Next Off lines below update to confirm "
        "what will happen next.",
        "Optional: click Test LED to immediately fire the configured colour "
        "now without waiting for the schedule.",
    ])
    add_paragraph(doc, "To remove the schedule entirely click Delete Schedule.")

    add_heading(doc, "6.8 Tune load monitoring thresholds for a socket", level=2)
    add_steps(doc, [
        "Open the pedestal detail view; find the socket card.",
        "Scroll within the card to the Load section (under the breaker info).",
        "Change the warn and crit percentages. Defaults are 60 and 80; warn "
        "must be strictly less than crit, both between 1 and 99.",
        "Click Save.",
        "The new thresholds take effect on the next telemetry tick (≤ 5 s). "
        "If the current load is already above the new threshold, an alarm "
        "fires immediately.",
    ])

    add_heading(doc, "6.9 Handle a load alarm", level=2)
    add_steps(doc, [
        "When a critical load alarm fires, you'll see a red flashing badge "
        "on the System Health icon in the sidebar AND a Browser Notification "
        "(if you allowed notifications).",
        "Open System Health and find the Meter Load Alarms card.",
        "If the load is borderline and you want to silence the badge while "
        "monitoring, click Acknowledge — the alarm stays open but is dimmed "
        "and stops counting toward the badge.",
        "If you've checked physically and the load is fine (or you've reduced "
        "the load yourself), click Resolve to manually close the alarm.",
        "If the load drops back below the threshold on its own, the alarm "
        "auto-resolves and disappears with no action needed.",
    ])

    add_heading(doc, "6.10 Connect an ERP via the API Gateway", level=2)
    add_steps(doc, [
        "Open API Gateway.",
        "Click Generate API Key. Copy the key and store it safely; you will "
        "need it to configure the ERP side.",
        "Tick which endpoints the ERP is allowed to call (sessions, billing, "
        "breaker management, etc.).",
        "Optionally set a Webhook URL so the ERP receives push events; tick "
        "which events to forward.",
        "Toggle Active to ON.",
        "Click Verify – a small green dot next to each endpoint confirms it "
        "responds. Red dots show which feature is disabled or not yet "
        "configured.",
    ])

    # ── Indicators glossary ─────────────────────────────────────────────────
    add_heading(doc, "7. Indicator and badge glossary", level=1)
    add_paragraph(doc, "Quick reference for the small visual cues you see on "
                       "the dashboard:")
    add_bullet(doc, "Green dot – healthy, connected, active.")
    add_bullet(doc, "Yellow dot – pending or in-progress (e.g. plug inserted, "
                    "breaker resetting).")
    add_bullet(doc, "Red dot or red banner – fault, tripped, or alarm.")
    add_bullet(doc, "Grey dot – idle or unknown.")
    add_bullet(doc, "Orange dot – breaker manually opened.")
    add_bullet(doc, "AUTO badge (green) – auto-activation is enabled for this "
                    "socket or valve.")
    add_bullet(doc, "UNATTRIBUTED badge (amber) – the active session has no "
                    "customer attached; flow is recorded but unbilled.")
    add_bullet(doc, "📱 icon – the active session was claimed by a customer "
                    "via the mobile app QR scan.")
    add_bullet(doc, "⚡ icon overlay – breaker has tripped on this outlet.")
    add_bullet(doc, "Load bar (green / yellow / red flashing) – current draw "
                    "as a percentage of the socket's rated current. Three "
                    "stacked bars on a 3-phase socket show per-phase load.")
    add_bullet(doc, "Awaiting hardware configuration from device – amber "
                    "message on a socket's load panel meaning the Arduino "
                    "has not yet reported the meter type / rated current.")
    add_bullet(doc, "AUTO badge on LED Schedule – the daily LED schedule is "
                    "enabled for this pedestal.")
    add_bullet(doc, "WebSocket status dot – your browser's live connection to "
                    "the dashboard service.")
    add_bullet(doc, "Pedestal status dot – at least one pedestal in the "
                    "marina is reporting heartbeats.")

    # ── Troubleshooting ─────────────────────────────────────────────────────
    add_heading(doc, "8. When something looks wrong", level=1)
    add_paragraph(doc, "Try these steps before calling for support:")

    add_heading(doc, "8.1 The whole dashboard is empty / shows 'offline'", level=2)
    add_bullet(doc, "Check the WebSocket status dot in the bottom left – grey "
                    "means the browser cannot reach the dashboard service. "
                    "Reload the page.")
    add_bullet(doc, "If the Pedestal status dot is grey but WebSocket is green, "
                    "the dashboard is up but no pedestal has reported in. "
                    "Check System Health to see when the last heartbeat arrived.")

    add_heading(doc, "8.2 A pedestal card is missing", level=2)
    add_bullet(doc, "Pedestals appear automatically on first MQTT contact. "
                    "Check the network cable on the pedestal and make sure its "
                    "Ethernet link light is on.")
    add_bullet(doc, "Open System Health and look at the Pedestals section to "
                    "see whether the Opta is reachable.")

    add_heading(doc, "8.3 A socket is stuck on yellow (pending)", level=2)
    add_bullet(doc, "The plug has been inserted but no one activated the "
                    "session. If auto-activate is on for that socket, check "
                    "the skip reason that briefly appears in amber under the "
                    "card – it will say 'door open', 'pedestal heartbeat "
                    "timeout', or similar.")
    add_bullet(doc, "If everything looks fine, just click Activate manually.")

    add_heading(doc, "8.4 A breaker tripped", level=2)
    add_bullet(doc, "The red banner at the top of the pedestal shows which "
                    "socket is affected. Investigate the cause on the dock "
                    "(faulty appliance, overload, etc.) before clicking Reset "
                    "Breaker. The 15-second watchdog after reset will tell "
                    "you immediately if the fault is still present.")

    add_heading(doc, "8.5 A water valve auto-opened with no flow", level=2)
    add_bullet(doc, "An amber 'zero flow – possible disconnected hose' banner "
                    "appears. Check the dock; usually the customer's hose has "
                    "been removed since the valve was last used. The valve "
                    "stays open. You can either Stop it from the card or "
                    "leave it for the next user.")

    add_heading(doc, "8.6 An obvious bug or persistent error", level=2)
    add_bullet(doc, "Open System Health and check the error log. Filter by "
                    "Errors and copy the most recent message. Send it to your "
                    "support contact along with the time and the pedestal "
                    "name.")

    # ── Two-factor (authenticator) appendix ─────────────────────────────────
    add_heading(doc, "9. Appendix A – Two-factor (authenticator) setup", level=1)
    add_paragraph(
        doc,
        "Every operator login uses two-factor authentication: your password plus "
        "a 6-digit code from an authenticator app on your phone. The authenticator "
        "works fully offline – no email, SMTP, or internet is required (this is "
        "ideal for a NUC on an isolated marina LAN). Email one-time codes were "
        "removed in v3.33."
    )

    add_heading(doc, "A.1 Compatible authenticator apps", level=2)
    add_bullet(doc, "Aegis Authenticator (Android, open-source) – recommended.")
    add_bullet(doc, "Google Authenticator (Android / iOS).")
    add_bullet(doc, "Microsoft Authenticator (Android / iOS).")
    add_bullet(doc, "1Password, Bitwarden, or any other RFC-6238 TOTP app.")

    add_heading(doc, "A.2 First login – enrol your authenticator", level=2)
    add_paragraph(
        doc,
        "A brand-new account has a temporary password and no authenticator yet, "
        "so the first sign-in walks you through enrolment in the browser:"
    )
    add_steps(doc, [
        "Open the dashboard URL and enter your email + temporary password, then "
        "click Continue.",
        "Choose a new password (required on first login) and confirm it.",
        "A QR code appears. In your authenticator app choose Add / Scan QR code "
        "and scan it. (Can't scan? Choose 'Enter a setup key' and type the key "
        "shown manually; the issuer is 'Marina IoT'.)",
        "Your app shows a 6-digit code that changes every ~30 seconds. Type the "
        "current code to finish – you are now signed in and TOTP is enabled.",
    ])
    add_callout(doc, "No email needed",
                "Because the QR code is shown directly in the browser, there is no "
                "chicken-and-egg first login any more – even the very first admin "
                "login works with no SMTP configured.")

    add_heading(doc, "A.3 Resetting a lost authenticator (admin)", level=2)
    add_paragraph(
        doc,
        "If an operator loses or wipes their phone, an admin restores access – "
        "there is no self-service email recovery:"
    )
    add_steps(doc, [
        "Sign in as an admin and open Settings ⚙️ → Operator Accounts.",
        "On the affected user's row click Reset 2FA and confirm.",
        "That user re-enrols a new authenticator the next time they log in "
        "(the QR wizard from A.2). Their password is left unchanged.",
    ])
    add_callout(doc, "If every admin is locked out",
                "As a last resort, clear the 2FA columns directly in the database on "
                "the NUC: in users.db set totp_enabled=0, totp_secret=NULL, "
                "totp_failed_attempts=0, totp_locked_until=NULL for the account. See "
                "docs/totp-setup-guide.md for the exact snippet. The account then "
                "re-enrols on its next login.")

    add_heading(doc, "A.4 Managing your own authenticator", level=2)
    add_paragraph(doc, "From Settings ⚙️ → Two-Factor Authentication you can:")
    add_bullet(doc, "Setup Authenticator – generate a new secret + QR and verify it. "
                    "Re-running this invalidates the previous QR; only the most "
                    "recently verified secret works.")
    add_bullet(doc, "Disable – requires your current password and a current code. "
                    "Because 2FA is mandatory, you will be asked to enrol again on "
                    "your next login.")

    add_heading(doc, "A.5 Troubleshooting", level=2)
    add_bullet(doc, "'Invalid code' on setup or login – almost always phone clock "
                    "drift. Set the phone time to automatic / network time, then try "
                    "the next code. One window of drift (±30 s) is already tolerated.")
    add_bullet(doc, "'Too many failed attempts – locked for 15 minutes' – after 5 "
                    "failed code attempts the account locks for 15 minutes. Wait it "
                    "out, or an admin Reset 2FA also clears the lockout.")
    add_bullet(doc, "No second-factor screen appears – 2FA is mandatory; if you reach "
                    "the dashboard straight after the password, report it as a bug.")

    add_callout(doc, "Email / SMTP is now optional",
                "SMTP settings remain in Settings only for optional customer "
                "notifications – operator login no longer uses email at all. You can "
                "leave SMTP unconfigured.")

    # ── What's new ──────────────────────────────────────────────────────────
    add_heading(doc, "10. What's new (v3.19 – v3.33)", level=1)
    add_paragraph(doc, "Recent operator-facing additions. Earlier features are "
                       "documented in their sections above.")
    add_paragraph(doc, "v3.33 also makes the dashboard mobile-friendly: on a phone "
                       "the left menu collapses behind a ☰ button (tap to open, tap "
                       "the dimmed area to close), and the pedestal picture and its "
                       "detail panel stack vertically so everything fits a narrow screen.")

    add_heading(doc, "10.1 Two-factor sign-in — authenticator only (v3.33)", level=2)
    add_paragraph(doc, "Operator sign-in always requires a second factor after your "
                       "email and password. As of v3.33 the authenticator app (TOTP) "
                       "is the only second factor — email one-time codes were removed.")
    add_bullet(doc, "First login enrols an authenticator in the browser: set a new "
                    "password, scan the QR code with Aegis / Google / Microsoft "
                    "Authenticator (or 1Password / Bitwarden), enter a code, done. "
                    "No email or SMTP needed.")
    add_bullet(doc, "Later logins just ask for the current 6-digit code (it submits "
                    "automatically on the sixth digit).")
    add_bullet(doc, "Lost your phone? An admin clicks Reset 2FA in Settings → Operator "
                    "Accounts and you re-enrol on your next login. See Appendix A.")

    add_heading(doc, "10.2 Temperature sensor configuration (v3.22)", level=2)
    add_paragraph(doc, "A networked Papouch TME temperature sensor can now be added "
                       "from the dashboard. It is a separate device on the marina LAN "
                       "— not part of the Arduino Opta cabinet.")
    add_steps(doc, [
        "Open Settings → Device Configuration and pick the pedestal.",
        "In the “Temperature Sensor — Papouch TME” card, either click Scan "
        "Network (enter the subnet, e.g. 192.168.1, then Assign a found sensor) or type "
        "the sensor IP manually.",
        "Set the port (default 80) and protocol (HTTP), then click Save Device "
        "Configuration.",
    ])
    add_callout(doc, "If the scan finds nothing", "On a NUC with both a 5G/WAN link and "
                "the marina LAN, auto-detect may scan the wrong network. Type the marina "
                "subnet (e.g. 192.168.1) in the scan field, or just enter the sensor IP "
                "manually.")

    add_heading(doc, "10.3 Temperature alarms (v3.23)", level=2)
    add_paragraph(doc, "Once a temperature sensor is configured and responding, the "
                       "backend polls it every 30 seconds and raises range alarms:")
    add_bullet(doc, "Warning (yellow): temperature ≥ 45 °C or ≤ 0 °C.")
    add_bullet(doc, "Critical (red): temperature ≥ 60 °C or ≤ −10 °C.")
    add_bullet(doc, "Alarms escalate (warning → critical) and clear automatically "
                    "when the temperature returns to normal.")
    add_paragraph(doc, "The Device Configuration card shows the live reading coloured by "
                       "band. A configured sensor that stops responding raises a "
                       "“temperature sensor offline” warning.")

    add_heading(doc, "10.4 Active Alarms panel (v3.24)", level=2)
    add_paragraph(doc, "System Health now has an Active Alarms card listing every "
                       "currently-triggered alarm (temperature, fire, comm-loss, …) "
                       "colour-coded by severity (red = critical, yellow = warning). "
                       "Click Acknowledge to clear one; auto-resolving alarms disappear "
                       "on their own.")

    add_heading(doc, "10.5 Truthful diagnostics & socket status (v3.21)", level=2)
    add_bullet(doc, "Run Diagnostics now reports what the cabinet actually returns. "
                    "Sockets and water show real OK / FAIL; Temperature and Moisture "
                    "show N/A on Opta cabinets (they have no such sensors). A timeout no "
                    "longer shows a false “all OK”.")
    add_bullet(doc, "A socket shows FAULT (not ACTIVE) whenever the hardware reports a "
                    "fault or its breaker is tripped, regardless of any logical session "
                    "— the badge reflects reality.")

    add_heading(doc, "10.6 NFC provisioning & ERP activation (v3.26)", level=2)
    add_paragraph(doc, "Each cabinet can use one of two provisioning modes, chosen "
                       "in Control Center → Socket Settings. QR is the default and "
                       "every existing pedestal keeps it. NFC is for marinas using "
                       "the myMarina app with physical NFC tags on the pedestal.")
    add_paragraph(doc, "Switching modes:", bold=True)
    add_steps(doc, [
        "Open the pedestal → Control Center → Socket Settings.",
        "Pick QR or NFC. Switching to NFC asks you to confirm — it DISABLES "
        "auto-activate on all four sockets (the cabinet will then require explicit "
        "activation). Switching back to QR restores auto-activate on all four.",
    ])
    add_paragraph(doc, "Provisioning NFC tags (NFC mode):", bold=True)
    add_steps(doc, [
        "In the NFC table, each row is a socket (Q1–Q4) with its live status, the "
        "currently assigned tag, and actions.",
        "Type or scan the NFC tag ID for a socket and click Provision (or fill "
        "several rows and click Save All).",
        "A tag already assigned to another socket is rejected with a message "
        "telling you which cabinet/socket already owns it.",
        "Remove clears a socket's tag (with a confirmation).",
    ])
    add_paragraph(doc, "How an NFC session starts:", bold=True)
    add_bullet(doc, "The customer taps the socket's NFC tag in myMarina. That "
                    "pre-registers their intent for 5 minutes — it does NOT yet "
                    "switch the socket on.")
    add_bullet(doc, "When the customer plugs in within those 5 minutes, the "
                    "pedestal reports the plug-in and the socket activates, with "
                    "the customer attached to the session. If they do not plug in "
                    "in time, nothing happens and the socket stays idle.")
    add_bullet(doc, "If no valid NFC tap preceded the plug-in, the socket stays "
                    "idle (NFC mode does not auto-activate) until a valid tap, or "
                    "until you activate it yourself.")
    add_callout(doc, "You are always in control", "An NFC-started session is a "
                "normal session. The Stop button in Control Center stops it "
                "immediately, exactly like any other session — regardless of how "
                "it was started.")

    add_heading(doc, "10.7 Smart Mode — the master switch (v3.28)", level=2)
    add_paragraph(doc, "Smart Mode is the most important setting on a pedestal. It "
                       "is a firmware feature (Opta firmware v3.0.0) that decides WHO "
                       "controls the cabinet.", bold=True)
    add_paragraph(doc, "Every pedestal starts as “just a cabinet”:")
    add_bullet(doc, "Smart Mode OFF (the default on every power-up) — the Opta runs "
                    "in standalone mode and manages its own sockets. The dashboard is "
                    "effectively read-only: you can SEE everything (telemetry, breaker "
                    "state, door) but the NUC does not control sockets. None of the "
                    "smart features work in this mode.")
    add_bullet(doc, "Smart Mode ON — the Opta hands full control to the NUC. Only now "
                    "do sessions, per-socket Activate/Stop, NFC, auto-activate, load "
                    "monitoring and billing actually work.")
    add_paragraph(doc, "Where to find it:", bold=True)
    add_steps(doc, [
        "Open the pedestal → Control Center. The Smart Mode panel sits at the very "
        "top of Cabinet Status (green when ON, amber when OFF) — it is styled "
        "differently from the per-socket controls because it is a system-level switch.",
        "Click the toggle to turn Smart Mode ON (or OFF). The dashboard updates "
        "immediately; if the command fails it reverts and shows an error.",
    ])
    add_callout(doc, "After a power cut or reboot", "Smart Mode resets to OFF every "
                "time the Opta firmware boots. The dashboard reflects this "
                "automatically (the toggle goes amber). If your sockets suddenly stop "
                "responding to the dashboard after a reboot, check Smart Mode first — "
                "turn it back ON.")
    add_paragraph(doc, "While Smart Mode is OFF the socket Activate buttons stay "
                       "visible but are disabled with the tooltip “Enable Smart Mode to "
                       "activate sockets.” Telemetry is always readable in both modes.")
    add_paragraph(doc, "What changed in v3.30:", bold=True)
    add_bullet(doc, "When Smart Mode is OFF, ALL socket and valve controls are now "
                    "disabled and greyed (not just Activate) — the cabinet is in "
                    "standalone control and the dashboard is read-only for it. The "
                    "control commands are also refused at the API.")
    add_bullet(doc, "Clicking a socket on the pedestal image now opens an "
                    "information-only panel — state, live readings, the session "
                    "counter, and a Smart Mode badge. All controls live in the "
                    "Control Center.")
    add_bullet(doc, "The NUC no longer shuts a socket down on an overload or breaker "
                    "trip — it raises an alarm only. A tripped breaker still shows the "
                    "socket as faulted; reset it from the Control Center (Breaker panel).")

    add_heading(doc, "10.9 Usage history & monthly reports (v3.31)", level=2)
    add_paragraph(doc, "Every socket and valve keeps a history of completed sessions, "
                       "and you can download a plain-text report for any month.", bold=True)
    add_paragraph(doc, "Opening the history:", bold=True)
    add_steps(doc, [
        "Click the Usage button on a socket or valve — it is on each tile in the "
        "Dashboard Overview, on the cards in the Control Center, and on the socket-"
        "detail panel when you click a socket on the pedestal image. (v3.32 — the "
        "button was renamed from “History” to “Usage”.)",
        "Pick a month from the drop-down. The table lists each completed session for "
        "that outlet: start and end time, energy (kWh) or water (litres), and the "
        "customer / NFC user when one was attached.",
        "Click “Download report (.txt)” to save the month's report. The report covers "
        "the whole pedestal (all sockets and valves) with per-outlet and grand totals.",
    ])
    add_paragraph(doc, "What is recorded:", bold=True)
    add_bullet(doc, "For each completed session: socket/valve, start & end time, "
                    "kWh used, litres used, and the customer or NFC user id when known.")
    add_bullet(doc, "When Smart Mode is OFF (the Opta runs standalone), the NUC still "
                    "logs consumption as a usage session — the customer columns are "
                    "simply blank. So usage is recorded in both modes (v3.32).")
    add_bullet(doc, "Energy (kWh) is measured by the dashboard as power × time, sampled "
                    "every few seconds, because the meter's own energy total is not "
                    "reported. Sessions from before v3.32 may show 0.000 (no history to "
                    "back-fill); new sessions show real energy.")
    add_callout(doc, "Reports are protected", "A new report is created automatically "
                "each month and older ones are kept on disk. They can be deleted ONLY "
                "by an admin (using the Delete button in the history window) — the "
                "system never deletes them. On the NUC, keep REPORTS_DIR pointed at "
                "persistent storage so reports survive an upgrade.")

    add_heading(doc, "10.10 Dashboard Overview vs Control Center (v3.32)", level=2)
    add_paragraph(doc, "Each pedestal has two tabs with a clear division of labour:", bold=True)
    add_bullet(doc, "Dashboard Overview — your at-a-glance MONITORING view. Shows the "
                    "cabinet status (Smart Mode, connection, door, uptime) and, for "
                    "every socket and valve, the live readings: state, load bar, "
                    "voltage / current / power, breaker status, and water litres. Each "
                    "tile has quick Usage and Alarms buttons. Nothing here changes the "
                    "cabinet — it is read-only.")
    add_bullet(doc, "Control Center — where you CONFIGURE and ACT: Smart Mode, "
                    "auto-activate, load thresholds, breaker reset, Activate / Stop, the "
                    "LED and its schedule, QR / NFC provisioning, and the event / ACK "
                    "logs. Each setting keeps just the small status line it needs for "
                    "context; the full live readings live in the Overview.")
    add_paragraph(doc, "In Smart Mode OFF the Control Center controls are greyed out "
                       "(the Opta is in charge), so the Overview is your main view.")

    add_heading(doc, "10.8 Per-socket Start / Stop (v3.28)", level=2)
    add_paragraph(doc, "With Smart Mode ON you control each electricity socket "
                       "individually from its card in Control Center:")
    add_bullet(doc, "Activate — turns the socket on. Enabled when a plug is inserted "
                    "(socket shows “pending”). Disabled with a tooltip when Smart Mode "
                    "is OFF, when no plug is inserted, or when an overload alarm is "
                    "pending acknowledgement.")
    add_bullet(doc, "Stop — turns the socket off and ends the session. Always "
                    "available to the operator regardless of how the session started "
                    "(operator, NFC, auto-activate).")
    add_callout(doc, "Manual Stop turns off Auto-activate", "When you manually Stop a "
                "socket that had Auto-activate ON, the system also switches "
                "Auto-activate OFF for that socket (and tells you so). This stops the "
                "“stop → it comes straight back on” loop when a cable is still plugged "
                "in. Re-enable Auto-activate from the socket's toggle whenever you want.")

    # ── Closing ─────────────────────────────────────────────────────────────
    add_heading(doc, "11. Need more?", level=1)
    add_paragraph(doc, "This guide covers the operator dashboard you use every "
                       "day. For deeper topics see:")
    add_bullet(doc, "README.md (in the project root) – architecture overview, "
                    "deployment, and recent changelog.")
    add_bullet(doc, "docs/firmware_requirements.md – the contract between the "
                    "Arduino Opta firmware and the backend.")
    add_bullet(doc, "docs/mobile_api.md – the mobile customer app interface "
                    "(out of scope for this guide).")
    add_paragraph(doc, "")
    add_paragraph(doc, "Happy operating, and welcome to Cloud_IOT.")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(OUTPUT))
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    build()
