"""
Generate the Pedestal User Guide PDF for Cloud_IOT Pedestal SW.

One combined document, two parts:
  PART A — Marina Operator Guide (admin & monitor): configuration, fault
           management, monitoring, control management.
  PART B — Customer Guide: two usage modes — (1) auto-activate plug-and-go,
           (2) QR scan + MyMarina mobile application.

Uses reportlab (already in backend/.venv). Run with the venv python:
    backend/.venv/Scripts/python.exe scripts/generate_pedestal_user_guide.py

Content is derived from the live codebase (frontend pages, mqtt_handlers,
controls router, api_catalog) as of the generation date — keep in sync when
features change.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, ListFlowable, ListItem, HRFlowable
)
from datetime import datetime
import os

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "Pedestal_User_Guide.pdf"
)

# ── Brand palette (matches ERP Integration Guide) ───────────────────────────
BRAND_BLUE = HexColor("#1e3a5f")
BRAND_LIGHT = HexColor("#e8f0fe")
ACCENT = HexColor("#2563eb")
GRAY = HexColor("#6b7280")
TABLE_HEADER_BG = HexColor("#1e3a5f")
TABLE_ALT_BG = HexColor("#f8fafc")
CODE_BG = HexColor("#f1f5f9")
GREEN = HexColor("#059669")
ORANGE = HexColor("#d97706")
RED = HexColor("#b91c1c")

styles = getSampleStyleSheet()

styles.add(ParagraphStyle("DocTitle", parent=styles["Title"],
    fontSize=26, leading=32, textColor=BRAND_BLUE, spaceAfter=6, alignment=TA_CENTER))
styles.add(ParagraphStyle("DocSubtitle", parent=styles["Normal"],
    fontSize=13, leading=18, textColor=GRAY, spaceAfter=20, alignment=TA_CENTER))
styles.add(ParagraphStyle("PartBanner", parent=styles["Title"],
    fontSize=20, leading=26, textColor=white, alignment=TA_CENTER,
    backColor=BRAND_BLUE, borderPadding=12, spaceBefore=10, spaceAfter=18))
styles.add(ParagraphStyle("H1", parent=styles["Heading1"],
    fontSize=18, leading=24, textColor=BRAND_BLUE, spaceBefore=22, spaceAfter=10))
styles.add(ParagraphStyle("H2", parent=styles["Heading2"],
    fontSize=14, leading=18, textColor=BRAND_BLUE, spaceBefore=15, spaceAfter=7))
styles.add(ParagraphStyle("H3", parent=styles["Heading3"],
    fontSize=12, leading=16, textColor=HexColor("#374151"), spaceBefore=11, spaceAfter=5))
styles.add(ParagraphStyle("BodyText2", parent=styles["Normal"],
    fontSize=10, leading=14, alignment=TA_JUSTIFY, spaceAfter=6))
styles.add(ParagraphStyle("CodeBlock", parent=styles["Normal"],
    fontName="Courier", fontSize=8.5, leading=12, backColor=CODE_BG,
    borderPadding=6, spaceBefore=4, spaceAfter=8, leftIndent=8))
styles.add(ParagraphStyle("Note", parent=styles["Normal"],
    fontSize=9.5, leading=13, textColor=HexColor("#1e40af"), backColor=BRAND_LIGHT,
    borderPadding=8, spaceBefore=6, spaceAfter=10, leftIndent=8, rightIndent=8))
styles.add(ParagraphStyle("Warn", parent=styles["Normal"],
    fontSize=9.5, leading=13, textColor=HexColor("#7c2d12"), backColor=HexColor("#fff7ed"),
    borderPadding=8, spaceBefore=6, spaceAfter=10, leftIndent=8, rightIndent=8))
styles.add(ParagraphStyle("TableCell", parent=styles["Normal"], fontSize=9, leading=12))
styles.add(ParagraphStyle("TableHeader", parent=styles["Normal"],
    fontSize=9, leading=12, textColor=white, fontName="Helvetica-Bold"))
styles.add(ParagraphStyle("Footer", parent=styles["Normal"],
    fontSize=8, textColor=GRAY, alignment=TA_CENTER))


def make_table(headers, rows, col_widths=None):
    data = [[Paragraph(h, styles["TableHeader"]) for h in headers]]
    for row in rows:
        data.append([Paragraph(str(c), styles["TableCell"]) for c in row])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, 0), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#d1d5db")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), TABLE_ALT_BG))
    t.setStyle(TableStyle(cmds))
    return t


def hr():
    return HRFlowable(width="100%", thickness=0.5, color=HexColor("#d1d5db"),
                      spaceBefore=6, spaceAfter=6)


def code(text):
    return Paragraph(text.replace("&", "&amp;").replace("\n", "<br/>").replace(" ", "&nbsp;"),
                     styles["CodeBlock"])


def p(text, style="BodyText2"):
    return Paragraph(text, styles[style])


def note(text):
    return Paragraph(f"<b>Note:</b> {text}", styles["Note"])


def warn(text):
    return Paragraph(f"<b>Important:</b> {text}", styles["Warn"])


def bullets(items):
    return ListFlowable(
        [ListItem(Paragraph(i, styles["BodyText2"]), bulletColor=ACCENT) for i in items],
        bulletType="bullet", bulletFontSize=8, leftIndent=16, spaceBefore=4, spaceAfter=8)


def steps(items):
    return ListFlowable(
        [ListItem(Paragraph(i, styles["BodyText2"]), bulletColor=ACCENT) for i in items],
        bulletType="1", bulletFontSize=9, leftIndent=18, spaceBefore=4, spaceAfter=8)


def build():
    doc = SimpleDocTemplate(
        OUTPUT_PATH, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2.5 * cm, bottomMargin=2 * cm,
        title="Cloud_IOT Pedestal SW - User Guide", author="Lika Digital")
    s = []
    W = doc.width

    # ── COVER ───────────────────────────────────────────────────────────────
    s.append(Spacer(1, 70))
    s.append(p("Cloud_IOT Smart Pedestal", "DocTitle"))
    s.append(p("Pedestal User Guide", "DocSubtitle"))
    s.append(hr())
    s.append(Spacer(1, 10))
    s.append(p(f"Version 1.1 (covers SW v3.18) &mdash; {datetime.now().strftime('%B %d, %Y')}", "DocSubtitle"))
    s.append(p("Lika Digital d.o.o.", "DocSubtitle"))
    s.append(Spacer(1, 16))
    s.append(p(
        "This guide covers everyday use of the Cloud_IOT marina pedestal system for two "
        "audiences. <b>Part A</b> is for the Marina Operator (dashboard administrators and "
        "read-only monitors) and covers configuration, fault management, monitoring and control. "
        "<b>Part B</b> is for the marina customer (boat owner) and covers the two ways to use a "
        "pedestal: automatic plug-and-go, and the QR-code + MyMarina mobile application."))
    s.append(Spacer(1, 14))
    s.append(p("<b>Contents</b>", "H1"))
    s.append(bullets([
        "<b>Part A &mdash; Marina Operator Guide</b>",
        "&nbsp;&nbsp;A1. Roles &amp; Access (Admin vs Monitor)",
        "&nbsp;&nbsp;A2. Logging In",
        "&nbsp;&nbsp;A3. Configuration Guide",
        "&nbsp;&nbsp;A4. Monitoring",
        "&nbsp;&nbsp;A5. Fault Management",
        "&nbsp;&nbsp;A6. Control Management",
        "<b>Part B &mdash; Customer Guide</b>",
        "&nbsp;&nbsp;B1. Two Ways to Use a Pedestal",
        "&nbsp;&nbsp;B2. Mode 1 &mdash; Auto-Activate (Plug-and-Go)",
        "&nbsp;&nbsp;B3. Mode 2 &mdash; QR Scan + MyMarina Mobile App",
        "&nbsp;&nbsp;B4. Which Mode Applies to You",
    ]))
    s.append(PageBreak())

    # ════════════════════════════════════════════════════════════════════════
    # PART A — MARINA OPERATOR GUIDE
    # ════════════════════════════════════════════════════════════════════════
    s.append(p("PART A &mdash; Marina Operator Guide", "PartBanner"))
    s.append(p(
        "The Marina Operator uses the web dashboard (open <font face='Courier'>http://&lt;NUC-IP&gt;</font> "
        "from any browser on the marina network). The dashboard manages every pedestal, socket, "
        "water valve, camera and alarm at the site.", "BodyText2"))

    # A1 — ROLES
    s.append(p("A1. Roles &amp; Access (Admin vs Monitor)", "H1"))
    s.append(p(
        "Every operator account has one of two roles. The role decides which pages are visible "
        "and whether the operator can change anything or only look."))
    s.append(make_table(
        ["Capability", "Admin", "Monitor"],
        [
            ["Dashboard, Analytics, History (view)", "Yes", "Yes"],
            ["Start / stop / allow / deny sessions", "Yes", "No"],
            ["Auto-activate toggle, LED, reset, QR", "Yes", "No (hidden)"],
            ["Settings / device configuration", "Yes", "No"],
            ["Billing rates &amp; customer spending", "Yes", "No"],
            ["Customers, Contracts, Berths, API Gateway", "Yes", "No"],
            ["System Health, error logs, alarms (view)", "Yes", "Limited"],
            ["Acknowledge overload auto-stop alarm", "Yes", "No"],
        ],
        col_widths=[W * 0.56, W * 0.22, W * 0.22]))
    s.append(note(
        "Monitor is a safe read-only login for staff who should see status but never operate "
        "hardware. All control buttons and admin-only pages are hidden for monitors &mdash; if a "
        "control looks missing, check the role of the logged-in account."))

    # A2 — LOGIN
    s.append(p("A2. Logging In", "H1"))
    s.append(steps([
        "Open <font face='Courier'>http://&lt;NUC-IP&gt;</font> in a browser on the same network.",
        "Enter your operator email and password.",
        "A one-time code (OTP) is required as the second factor. If marina email (SMTP) is "
        "configured, the code arrives by email. If not, it is printed to the backend log &mdash; "
        "an administrator can read it on the NUC with "
        "<font face='Courier'>sudo journalctl -u cloud-iot-backend -f</font>.",
        "Enter the OTP to finish signing in.",
    ]))
    s.append(note(
        "The first admin account and password are set during NUC installation and stored in "
        "<font face='Courier'>/opt/cloud-iot/backend/.env</font>. Change the password after first "
        "login via Settings &rarr; Users."))

    # A3 — CONFIGURATION
    s.append(p("A3. Configuration Guide", "H1"))
    s.append(p(
        "All configuration lives on the <b>Settings</b> page (admin only). Configuration is a "
        "one-time-per-pedestal setup followed by occasional adjustments."))

    s.append(p("A3.1 Connect a Pedestal", "H2"))
    s.append(bullets([
        "<b>Select pedestal</b> from the dropdown. Pedestals appear automatically once their "
        "Arduino Opta connects to the MQTT broker (auto-registration by heartbeat).",
        "<b>Pedestal IP</b> &mdash; the hardware controller address (informational; data flows over MQTT).",
        "<b>Camera IP</b> &mdash; the ONVIF/RTSP camera bound to this pedestal's berth.",
        "<b>Data mode</b> &mdash; <font face='Courier'>real</font> for live hardware (NUC default).",
    ]))

    s.append(p("A3.2 Discover Devices", "H2"))
    s.append(p("The Devices panel scans the local network so you do not have to type addresses by hand:"))
    s.append(make_table(
        ["Device", "How it is found", "Action"],
        [
            ["IP camera", "ONVIF WS-Discovery subnet scan", "Click Assign to bind to a pedestal"],
            ["Temp / humidity sensor", "Papouch TME HTTP subnet scan", "Assign to a pedestal"],
            ["Arduino Opta controller", "MQTT heartbeat registration", "Appears with last-seen time"],
        ],
        col_widths=[W * 0.26, W * 0.44, W * 0.30]))

    s.append(p("A3.3 Run Diagnostics &amp; Initialize", "H2"))
    s.append(p(
        "A new pedestal shows <b>Not Initialized</b> until it passes a diagnostics check. Click "
        "<b>Run Diagnostics</b>: the backend asks the Opta to report every sensor and waits up to "
        "12 seconds. When all sensors respond, the pedestal is marked <b>Ready</b> and live tiles "
        "appear. The 8-point check covers: temperature, moisture, the four power meters, the water "
        "flow meter, the cabinet door switch, the breaker board, the ONVIF camera and the Papouch "
        "sensor."))
    s.append(warn(
        "Sockets show &ldquo;Awaiting hardware configuration from device&rdquo; until the pedestal "
        "publishes its hardware profile (meter type, phases, rated amps) over MQTT. Load bars and "
        "overload protection only work once that profile has been received."))

    s.append(p("A3.4 Feature Toggles", "H2"))
    s.append(bullets([
        "<b>Mobile App Access</b> (<font face='Courier'>mobile_enabled</font>) &mdash; makes this "
        "pedestal visible to customers in the MyMarina app.",
        "<b>AI Integration</b> (<font face='Courier'>ai_enabled</font>) &mdash; enables camera ship-"
        "matching and berth occupancy detection.",
    ]))

    s.append(p("A3.5 Socket, Valve, LED &amp; Threshold Settings", "H2"))
    s.append(bullets([
        "<b>Load thresholds</b> &mdash; per socket, set the warning and critical percentage of "
        "rated current (used by the load meter and the 90% auto-stop protection).",
        "<b>Auto-activate</b> &mdash; <b>ON by default</b> for every electricity socket and water valve "
        "(plug-and-go), so a boat plugging in starts automatically. Turn it off per socket for manual "
        "control. Valves can also auto-open after a successful diagnostic. The setting persists across reboots.",
        "<b>LED schedule</b> &mdash; set a daily on/off schedule and colour (red / green / blue / off) "
        "for the pedestal indicator, or send a direct LED command.",
    ]))

    s.append(p("A3.6 Site Settings", "H2"))
    s.append(make_table(
        ["Setting", "Purpose"],
        [
            ["SMTP / Email", "Delivers login OTP codes and notifications. If unset, OTP prints to the log."],
            ["SNMP trap receiver", "Receives temperature alerts from Papouch sensors (UDP port, OID, target)."],
            ["Pilot mode assignments", "Restrict a customer to one pedestal/socket; activation only within "
                                       "3 minutes of physical plug-in. Useful for demos and training."],
            ["Users", "Create operator accounts, set role (Admin/Monitor), enable/disable, delete."],
            ["Billing rates", "Set &euro;/kWh and &euro;/litre used for invoices and spending reports."],
            ["Contract templates", "Author agreements customers must sign in the app before use."],
            ["Config Backup / Restore", "Download a timestamped JSON of all config (redacted by default) "
                                        "or a one-click Support Bundle for troubleshooting; restore from a saved file."],
        ],
        col_widths=[W * 0.26, W * 0.74]))

    s.append(note(
        "All configuration (pedestal flags, socket auto-activate, thresholds, schedules, camera, "
        "SMTP/SNMP, billing, contracts) lives in the NUC database and <b>persists across reboots</b> "
        "(v3.18). A NUC restart no longer resets anything, and any sessions already running on the "
        "hardware are <b>adopted and kept alive</b> rather than stopped."))

    s.append(PageBreak())

    # A4 — MONITORING
    s.append(p("A4. Monitoring", "H1"))

    s.append(p("A4.1 Pedestal States", "H2"))
    s.append(make_table(
        ["State", "Meaning"],
        [
            ["Not Initialized", "Diagnostics have not yet passed. Run Diagnostics to bring it online."],
            ["Idle", "Online, no active session on the socket."],
            ["Pending", "Plug inserted / session requested, awaiting activation."],
            ["Active", "Session running &mdash; power or water is flowing and being metered."],
            ["Fault", "A breaker trip or sensor fault is present."],
            ["Blocked", "Manually disabled by an operator, or auto-stopped due to overload."],
        ],
        col_widths=[W * 0.22, W * 0.78]))

    s.append(p("A4.2 Live Load &amp; Meter Telemetry", "H2"))
    s.append(p(
        "Each electricity socket shows a live load meter. Single-phase sockets show one bar; "
        "three-phase sockets show L1/L2/L3 bars plus a total. The bar colour follows the warning "
        "and critical thresholds. Secondary readings show voltage, power (kW), power factor and "
        "frequency. Water valves show flow rate (L/min), session litres and cumulative total."))

    s.append(p("A4.3 Camera, Berths &amp; Occupancy", "H2"))
    s.append(bullets([
        "<b>Live view</b> &mdash; authenticated snapshot polling from the berth camera.",
        "<b>Occupancy check</b> &mdash; on-demand free/occupied classification with a confidence score.",
        "<b>Ship matching</b> &mdash; compares the live frame to stored reference photos; flags "
        "&ldquo;wrong ship&rdquo; when the match score is low (requires AI Integration enabled).",
    ]))

    s.append(p("A4.4 Analytics, History &amp; System Health", "H2"))
    s.append(bullets([
        "<b>Analytics</b> &mdash; daily consumption charts, per-pedestal comparison, socket breakdown.",
        "<b>History</b> &mdash; full session log, filterable by status (pending / active / completed / denied).",
        "<b>System Health</b> &mdash; CPU / memory / disk, MQTT broker status, WebSocket status, load "
        "alarms, and the rolling error/event log (1h to 7d window).",
    ]))

    s.append(PageBreak())

    # A5 — FAULT MANAGEMENT
    s.append(p("A5. Fault Management", "H1"))
    s.append(p(
        "Faults surface as banners on the dashboard, badges on the sidebar (System Health / "
        "Customers), and entries in the event log. Some clear themselves; some require an operator "
        "to acknowledge."))

    s.append(p("A5.1 Alarm Types", "H2"))
    s.append(make_table(
        ["Alarm", "Trigger", "Operator action"],
        [
            ["Temperature", "Cabinet temp &gt; 50&deg;C", "Investigate ventilation; auto-actions may apply"],
            ["Moisture", "Cabinet moisture &gt; 90%", "Check for water ingress"],
            ["Load warning", "Socket current above warning %", "Monitor; no action required"],
            ["Load critical", "Socket current above critical %", "Prepare for auto-stop; check the boat's load"],
            ["Overload auto-stop", "Socket &ge; 90% of rated current", "Acknowledge to re-enable (see A5.3)"],
            ["Breaker tripped", "Opta reports breaker open", "Inspect circuit, then reset the breaker"],
            ["Communication loss", "No heartbeat for 60s", "Check Opta power and network"],
            ["Cabinet door open", "Door switch reports open", "Close and secure the cabinet"],
        ],
        col_widths=[W * 0.22, W * 0.36, W * 0.42]))

    s.append(p("A5.2 Breaker &amp; Communication Faults", "H2"))
    s.append(p(
        "Breaker state and trip history are shown per socket. A communication-loss watchdog raises "
        "an alarm when a pedestal stops sending heartbeats; the pedestal returns to normal "
        "automatically when the heartbeat resumes."))

    s.append(p("A5.3 Overload Auto-Stop &amp; Acknowledgment", "H2"))
    s.append(p(
        "When a socket reaches 90% of its rated current, the system automatically stops it to "
        "protect the circuit. The socket becomes <b>Blocked</b> and an auto-stop alarm is raised "
        "with the current, rated current and load percentage. An admin must press "
        "<b>Acknowledge &amp; Enable Re-activation</b> (in the socket's load panel or System Health) "
        "before the socket can be used again. This guard also prevents auto-activate from "
        "re-starting the socket until acknowledged."))

    s.append(p("A5.4 Event &amp; Error Logs", "H2"))
    s.append(p(
        "System Health holds a filterable log (System / Hardware categories; Error / Warning / Info "
        "levels) over a configurable window, with expandable detail rows for stack traces, plus a "
        "24-hour summary of error and warning counts."))

    s.append(PageBreak())

    # A6 — CONTROL MANAGEMENT
    s.append(p("A6. Control Management", "H1"))
    s.append(p("Control actions are admin only. Monitors see status but no control buttons."))

    s.append(p("A6.1 Session Lifecycle", "H2"))
    s.append(code(
        "  Customer requests / plugs in\n"
        "            |\n"
        "            v\n"
        "       [ PENDING ] ---- deny (with reason) ----> [ DENIED ]\n"
        "            |\n"
        "          allow / auto-activate\n"
        "            |\n"
        "            v\n"
        "       [ ACTIVE ] ---- stop / complete ----> [ COMPLETED ]\n"
        "            |                                      |\n"
        "            +-- energy_kwh / water_l metering      +-- final readings frozen"))

    s.append(p("A6.2 Allow, Deny, Stop", "H2"))
    s.append(bullets([
        "<b>Allow</b> &mdash; approve a pending session so power/water begins.",
        "<b>Deny</b> &mdash; reject a pending session; a dialog captures a reason stored on the record.",
        "<b>Stop</b> &mdash; end an active session at any time; final energy/water totals are frozen.",
    ]))
    s.append(note(
        "On NUC real-hardware deployments sessions auto-start on request (no approval step); the "
        "operator can still Stop any active session. The Allow/Deny flow is used where manual "
        "approval is enabled."))

    s.append(p("A6.3 Auto-Activate", "H2"))
    s.append(p(
        "Auto-activate is <b>ON by default</b> (plug-and-go): each plug-in starts a session "
        "automatically after a 2-second settle and a precondition check. Use the per-socket toggle to "
        "turn it OFF for manual control; the choice persists across reboots. See Part B, Mode 1."))

    s.append(p("A6.4 LED, Reset &amp; QR Codes", "H2"))
    s.append(bullets([
        "<b>LED control</b> &mdash; set colour and state immediately, or run a daily schedule.",
        "<b>Reset</b> &mdash; reboot the pedestal controller (clears state and re-initializes).",
        "<b>QR codes</b> &mdash; generate, download (per socket or all), and regenerate the printable "
        "QR labels customers scan to claim a socket in MyMarina. Regenerating invalidates old codes.",
    ]))

    s.append(PageBreak())

    # ════════════════════════════════════════════════════════════════════════
    # PART B — CUSTOMER GUIDE
    # ════════════════════════════════════════════════════════════════════════
    s.append(p("PART B &mdash; Customer Guide", "PartBanner"))
    s.append(p(
        "This part is for the marina customer (boat owner). How you start using a pedestal depends "
        "on how the marina has set up your berth: either fully automatic, or through the MyMarina "
        "mobile app using the QR code on the socket.", "BodyText2"))

    s.append(p("B1. Two Ways to Use a Pedestal", "H1"))
    s.append(make_table(
        ["", "Mode 1 &mdash; Auto-Activate", "Mode 2 &mdash; QR + MyMarina"],
        [
            ["What you do", "Just plug in", "Scan the socket QR, start in the app"],
            ["App needed", "No", "Yes (MyMarina)"],
            ["Who you are", "Anonymous", "Linked to your account"],
            ["Billing", "Not billed to your account", "Itemised invoice to your account"],
            ["Typical use", "Included / flat-rate berths", "Pay-per-use metered power &amp; water"],
        ],
        col_widths=[W * 0.20, W * 0.40, W * 0.40]))
    s.append(p("Your marina decides which mode applies to each socket. The next two sections explain both."))

    # B2 — AUTO ACTIVATE
    s.append(p("B2. Mode 1 &mdash; Auto-Activate (Plug-and-Go)", "H1"))
    s.append(p(
        "Electricity sockets and water valves are plug-and-go <b>by default</b> &mdash; you simply "
        "connect your shore-power cable and power starts on its own; no app, no scanning, no waiting "
        "for staff."))
    s.append(p("B2.1 How It Works", "H2"))
    s.append(steps([
        "The socket is plug-and-go by default (the operator can turn this off per socket).",
        "You plug your cable into the socket.",
        "The pedestal detects the plug, waits about 2 seconds to settle, runs a quick safety check, "
        "then switches the socket on.",
        "Power flows and energy is metered. To stop, unplug or ask the operator to stop the session.",
    ]))
    s.append(p("B2.2 Safety Preconditions", "H2"))
    s.append(p(
        "Auto-activation is skipped (you'd need the operator) if any of these are true at plug-in time:"))
    s.append(bullets([
        "There is an active fault on the pedestal.",
        "The pedestal has lost communication (no recent heartbeat).",
        "The socket is already in use, or a diagnostic is running.",
        "An overload auto-stop alarm is waiting to be acknowledged by an operator.",
    ]))
    s.append(note(
        "An <b>open cabinet door no longer blocks</b> activation (v3.18) &mdash; the socket still "
        "works and the system just logs a warning. Circuit breakers remain the protection against "
        "electrical faults."))
    s.append(warn(
        "Auto-activated sessions are anonymous: power is metered but the session is not linked to a "
        "customer account, so it cannot be itemised on your personal invoice. Use Mode 2 (MyMarina) "
        "if you need a billed, itemised session."))

    # B3 — QR + MOBILE
    s.append(p("B3. Mode 2 &mdash; QR Scan + MyMarina Mobile App", "H1"))
    s.append(p(
        "MyMarina is the customer mobile app. It links each session to your account so usage is "
        "metered, invoiced and stored in your history, and it gives you contracts, services and "
        "support in one place."))

    s.append(p("B3.1 Get Started", "H2"))
    s.append(steps([
        "Install MyMarina and tap <b>Register</b>. Enter your email and password; optionally add "
        "your name, ship name, VAT number and ship registration.",
        "Sign in. Your session token keeps you logged in for 30 days.",
        "If your marina requires an agreement, a contract appears to sign on first use (see B3.4).",
    ]))

    s.append(p("B3.2 Start Power or Water by Scanning the QR", "H2"))
    s.append(steps([
        "Find the QR label on the socket you want to use.",
        "Open MyMarina and scan it (or use your phone camera to open the deep link).",
        "The app opens directly on that exact socket and claims it for you.",
        "Confirm to start. A live meter shows elapsed time, energy (kWh) and current power (kW); "
        "water sessions show litres.",
        "Tap <b>Stop</b> in the app when you are done. Final totals are recorded.",
    ]))
    s.append(note(
        "If someone else is already using that socket, the app opens in read-only mode &mdash; you "
        "can see the live meter but cannot control a session that is not yours."))

    s.append(p("B3.3 Invoices &amp; Payment", "H2"))
    s.append(bullets([
        "Each completed session produces an itemised invoice: date, type, consumption and cost.",
        "Open <b>History</b> to see sessions and invoices with a Paid / Unpaid badge.",
        "Tap an unpaid invoice to pay it, and download the invoice PDF for your records.",
    ]))

    s.append(p("B3.4 Contracts", "H2"))
    s.append(bullets([
        "<b>Pending</b> shows agreements your marina requires; open one and sign with your finger on "
        "the signature pad.",
        "<b>Signed</b> keeps your countersigned agreements; download any as a PDF.",
    ]))

    s.append(p("B3.5 Services, Support &amp; Profile", "H2"))
    s.append(bullets([
        "<b>Service orders</b> &mdash; request marina services (crane, engine check, hull clean, "
        "diver, battery check, electrical check) with optional notes; staff follow up.",
        "<b>Chat</b> &mdash; message marina staff in real time; replies arrive as push notifications.",
        "<b>Profile</b> &mdash; update your name and ship name, toggle push notifications, sign out.",
    ]))

    s.append(p("B4. Which Mode Applies to You", "H1"))
    s.append(p(
        "If you plug in and power simply starts, your socket is in <b>auto-activate</b> mode &mdash; "
        "nothing else to do. If plugging in does nothing, look for the <b>QR label</b> on the socket "
        "and use <b>MyMarina</b> to start (and be billed for) your session. When in doubt, contact "
        "marina staff through the app chat or at the office."))

    s.append(Spacer(1, 18))
    s.append(hr())
    s.append(Spacer(1, 8))
    s.append(p(
        f"Document generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
        "Cloud_IOT Pedestal SW | Lika Digital d.o.o.", "Footer"))

    doc.build(s)
    print(f"PDF generated: {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
