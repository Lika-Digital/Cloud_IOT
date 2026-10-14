"""Generates System_Test_Document.docx — end-to-end system test plan.

Assumption: everything in Broker_Firmware_Contract.docx (including the P0/P1
items from Section 3 — opta/config/hardware, opta/meters/+/telemetry, breaker
topics) IS implemented on the Opta side.

Tester persona:
- One admin user, signed into the Pedestal SW UI (NUC frontend) in a browser
  on a laptop on the same LAN as the NUC.
- Same tester has an SSH session into the NUC with mosquitto_sub running as
  an MQTT tracer on `opta/#`, and a second tail on the backend journal.

Document is aligned with README.md changelog v3.4-v3.12 (latest on git main).
"""
from pathlib import Path
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT = Path(__file__).resolve().parent.parent / "System_Test_Document.docx"


def h1(doc, text):
    return doc.add_heading(text, level=1)


def h2(doc, text):
    return doc.add_heading(text, level=2)


def h3(doc, text):
    return doc.add_heading(text, level=3)


def para(doc, text, bold=False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.font.size = Pt(11)
    return p


def bullet(doc, text):
    p = doc.add_paragraph(text, style="List Bullet")
    for r in p.runs:
        r.font.size = Pt(11)
    return p


def numbered(doc, text):
    p = doc.add_paragraph(text, style="List Number")
    for r in p.runs:
        r.font.size = Pt(11)
    return p


def code_block(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.font.name = "Consolas"
    run.font.size = Pt(9)
    p.paragraph_format.left_indent = Cm(0.5)
    return p


def add_table(doc, headers, rows):
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr[i].text = h
        for r in hdr[i].paragraphs[0].runs:
            r.bold = True
            r.font.size = Pt(10)
    for r_idx, row in enumerate(rows, start=1):
        for c_idx, val in enumerate(row):
            table.rows[r_idx].cells[c_idx].text = val
            for r in table.rows[r_idx].cells[c_idx].paragraphs[0].runs:
                r.font.size = Pt(10)
    return table


def tc(doc, tcid, title, preconditions, steps, expected):
    """Render a single test case as a compact 3-row table."""
    h3(doc, f"{tcid}  —  {title}")
    table = doc.add_table(rows=3, cols=2)
    table.style = "Light Grid Accent 1"
    table.columns[0].width = Cm(3.5)
    table.columns[1].width = Cm(13.5)

    sections = [
        ("Preconditions", preconditions),
        ("Steps", steps),
        ("Expected result", expected),
    ]
    for i, (label, body) in enumerate(sections):
        c0 = table.rows[i].cells[0]
        c1 = table.rows[i].cells[1]
        c0.text = label
        for r in c0.paragraphs[0].runs:
            r.bold = True
            r.font.size = Pt(10)
        c1.text = ""
        first = True
        for line in body:
            if first:
                p = c1.paragraphs[0]
                first = False
            else:
                p = c1.add_paragraph()
            run = p.add_run(line)
            run.font.size = Pt(10)
    para(doc, "")  # spacer


def build():
    doc = Document()

    # ── Title ────────────────────────────────────────────────────────────
    title = doc.add_heading("Cloud_IOT — System Test Document", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = sub.add_run(
        "End-to-end test plan: Pedestal SW UI  ↔  NUC backend & MQTT broker (v3.12)  ↔  Arduino Opta"
    )
    r.italic = True
    r.font.size = Pt(10)

    # ── 0. Scope ─────────────────────────────────────────────────────────
    h1(doc, "0. Scope")
    para(doc,
         "This is a system-level test plan executed against a physical pedestal "
         "(or full HIL simulator). It verifies the end-user functions that emerge "
         "from the interaction between three components:")
    bullet(doc, "Pedestal SW UI — React frontend served by nginx on the NUC, FastAPI backend on :8000.")
    bullet(doc, "NUC MQTT broker — Mosquitto 2.0 in Docker on :1883 (container `pedestal-mqtt-broker`).")
    bullet(doc, "Arduino Opta firmware + PLC (Lika v2.0 baseline, assumed extended with all items from Section 3 of the Broker–Firmware Contract).")

    para(doc, "Assumptions:", bold=True)
    bullet(doc, "All P0 / P1 firmware gaps from Broker_Firmware_Contract.docx Section 3 are closed: opta/config/hardware (retained), opta/meters/+/telemetry (every 5 s), opta/breakers/Q{n}/status (retained), opta/cmd/breaker/Q{n} subscribe, BreakerTripped event.")
    bullet(doc, "Broker version is v3.12 (90% auto-stop overload protection in place — see README changelog 2026-04-30).")
    bullet(doc, "All system tests are aligned with the latest README on git `main` (v3.4 plug state machine → v3.12 overload protection).")
    bullet(doc, "Tests run against a clean DB unless a test explicitly inherits state from a previous one.")

    para(doc, "Out of scope:", bold=True)
    bullet(doc, "Unit / integration tests inside the backend or frontend (covered by 364-test pytest suite + Playwright).")
    bullet(doc, "Customer mobile app flows (separate mobile test plan).")
    bullet(doc, "Stress, load, penetration tests.")

    # ── 1. Test environment & tester setup ───────────────────────────────
    h1(doc, "1. Test environment")

    h2(doc, "1.1  Hardware under test")
    bullet(doc, "1× marina pedestal cabinet with Arduino Opta + PLC (Lika v2.0+).")
    bullet(doc, "4× electricity sockets — Q1, Q2 (1Φ 16A), Q3 (1Φ 32A), Q4 (3Φ 65A).")
    bullet(doc, "2× water valves — V1, V2 (normally-closed).")
    bullet(doc, "ABB D11/D13 Modbus RTU meters on addresses 1–4.")
    bullet(doc, "1× Intel Atom x7425E NUC running Ubuntu 24.04 with Cloud_IOT v3.12 installed at `/opt/cloud-iot/`.")
    bullet(doc, "Load tester capable of driving Q1/Q2/Q4 up to 90% of rated_amps (e.g. resistive load bank).")
    bullet(doc, "Test cables: CEE 16A (1Φ), CEE 32A (1Φ), CEE 63A (3Φ).")
    bullet(doc, "Garden hose + 5 L / 20 L measuring jug.")

    h2(doc, "1.2  Tester persona — single user, two windows")
    para(doc,
         "All tests are performed by ONE tester logged in as admin. The tester "
         "operates only the Pedestal SW UI (NUC frontend) and observes the MQTT "
         "bus and backend log via SSH to the NUC.")

    bullet(doc, "Window A — Browser on tester laptop, signed into Pedestal SW UI as admin (`damir@lika.digital`). URL: `https://marina-iot` (Tailscale DNS) or `http://192.168.1.167` (LAN — same IP carried over from the prior NUC, so existing Opta `BROKER_HOST` configs keep working with no firmware change).")
    bullet(doc, "Window B — SSH session to the NUC. From the tester laptop:")
    code_block(doc,
               "ssh cloud_iot@100.123.70.21        # Tailscale (works from anywhere)\n"
               "ssh cloud_iot@192.168.1.167        # LAN (when on marina Wi-Fi)\n"
               "# Hostname on the NUC prompt should read: cloud_iot@marina-iot:~$")
    bullet(doc, "Inside the SSH session, run two panes (tmux or two SSH sessions):")
    code_block(doc,
               "# Pane 1 — full MQTT tracer (matches the old-Opta trace format so old/new logs are comparable)\n"
               "mosquitto_sub -h localhost -p 1883 -t '#' -v -F '%I %t [QoS:%q] [Retain:%r] %p'\n"
               "\n"
               "# Pane 2 — backend journal\n"
               "sudo cloud-iot logs backend\n"
               "# (alias for: sudo journalctl -u cloud-iot-backend -f -n 0)")
    bullet(doc, "No mobile app, no second operator, no curl — every operator action is performed in the browser UI; every verification is read from the MQTT tracer pane and/or the backend journal pane.")

    h2(doc, "1.3  Test users (auth)")
    bullet(doc, "Admin: `damir@lika.digital` (full role). Used for all tests in Sections 3.A–3.G unless a test explicitly switches role.")
    bullet(doc, "Monitor: `monitor@test.local` (read-only role). Used only by TC-D05 to verify RBAC.")
    bullet(doc, "Default admin password is the value of `DEFAULT_ADMIN_PASSWORD` in `/opt/cloud-iot/backend/.env`. Change in production before testing.")
    bullet(doc, "OTP prints to backend journal (Pane 2) — no SMTP configured by default.")

    # ── 2. NUC prerequisites that must hold before any test runs ─────────
    doc.add_page_break()
    h1(doc, "2. NUC configuration prerequisites (apply once, before all tests)")
    para(doc,
         "Verify each item before starting the test session. If any item fails, "
         "stop and fix it — none of the test cases below will produce meaningful "
         "results otherwise.")

    h2(doc, "2.1  Services running")
    code_block(doc,
               "sudo cloud-iot status\n"
               "# Expect ACTIVE (running):\n"
               "#   cloud-iot-backend.service     (uvicorn :8000)\n"
               "#   cloud-iot-compose.service     (starts docker compose)\n"
               "#   nginx.service                 (reverse proxy + static frontend)\n"
               "#   cloudflared.service           (optional, for remote access)\n"
               "#   tailscaled.service            (for remote SSH)\n"
               "\n"
               "docker ps | grep mosquitto\n"
               "# Expect: pedestal-mqtt-broker  ...  Up  ...  0.0.0.0:1883->1883/tcp")

    h2(doc, "2.2  Required environment in `/opt/cloud-iot/backend/.env`")
    add_table(doc,
              ["Variable", "Value for test", "Why"],
              [
                  ["APP_ENV", "production", "Activates startup guards + rate limiting"],
                  ["JWT_SECRET", "≥ 32 random chars", "Backend refuses to boot otherwise (README §Auth hardening)"],
                  ["DEFAULT_ADMIN_EMAIL", "damir@lika.digital", "Used by all tests as admin login"],
                  ["DEFAULT_ADMIN_PASSWORD", "set, not blank", "Required for login"],
                  ["MQTT_BROKER_HOST", "127.0.0.1", "Broker reachable from FastAPI"],
                  ["MQTT_BROKER_PORT", "1883", "Mosquitto port"],
                  ["MARINA_TIMEZONE", "Europe/Zagreb", "v3.10 LED schedule uses local time"],
                  ["RATE_LIMIT_ENABLED", "true (default in prod)", "Enables slowapi limits — relevant for TC-G05"],
              ])

    h2(doc, "2.3  Initial database state")
    bullet(doc, "`/opt/cloud-iot/backend/pedestal.db` exists and has the v3.12 schema (all migrations applied by backend startup `_migrate_schema()`).")
    bullet(doc, "`/opt/cloud-iot/backend/data/users.db` has the default admin row created from the env vars above.")
    bullet(doc, "To reset to a clean test state (DESTRUCTIVE — only on a test NUC):")
    code_block(doc,
               "sudo systemctl stop cloud-iot-backend\n"
               "sudo rm /opt/cloud-iot/backend/pedestal.db\n"
               "sudo rm /opt/cloud-iot/backend/data/users.db\n"
               "sudo systemctl start cloud-iot-backend\n"
               "# First start re-creates both DBs and seeds the admin user.")

    h2(doc, "2.4  Network reachability — fixed IPs (carried over from prior NUC)")
    add_table(doc,
              ["Endpoint", "Address", "Notes"],
              [
                  ["NUC LAN IP (enp2s0)", "192.168.1.167", "Same as prior NUC. Opta `BROKER_HOST` continues to point here — no firmware change needed."],
                  ["NUC Tailscale IP", "100.123.70.21", "Remote SSH and remote browser access."],
                  ["NUC hostname", "marina-iot", "Visible on the SSH prompt; usable as `marina-iot` over Tailscale Magic DNS."],
                  ["MQTT broker", "192.168.1.167:1883", "Mosquitto in Docker, container `pedestal-mqtt-broker`."],
                  ["Backend API", "via nginx: http://192.168.1.167/api/", "FastAPI listens on 127.0.0.1:8000 only — not reachable from the LAN; testers go through nginx on :80/:443."],
                  ["Pedestal SW UI", "http://192.168.1.167  or  https://marina-iot", "Served by nginx."],
              ])
    bullet(doc, "Tester laptop → NUC: `ping 192.168.1.167` (LAN) or `tailscale ping marina-iot` (remote) must succeed before any test.")
    bullet(doc, "NUC → Opta cabinet: same /24 subnet (Opta on 192.168.1.x), no firewall rule on TCP/1883.")
    bullet(doc, "Opta cabinet config: `BROKER_HOST=192.168.1.167`, `BROKER_PORT=1883`, `CLIENT_ID=MAR_KRK_ORM_01` (or the marina-assigned cabinet ID).")

    h2(doc, "2.5  Quick health probes")
    code_block(doc,
               "curl -s http://127.0.0.1:8000/api/health             # → {\"status\":\"ok\"}\n"
               "mosquitto_pub -h 127.0.0.1 -t 'test/ping' -m 'hi'   # no error\n"
               "ls /opt/cloud-iot/backend/static/qr/ 2>/dev/null   # exists after first pedestal contact (v3.7)")

    # ── 3. TEST CASES ─────────────────────────────────────────────────────
    doc.add_page_break()
    h1(doc, "3. Test cases")
    para(doc,
         "Each test case lists Preconditions (the exact NUC-side state required), "
         "Steps (what the tester does in Window A — Pedestal SW UI), and Expected "
         "result (what should appear in the UI AND in Window B — MQTT tracer and "
         "backend journal). Tests are ordered to follow the natural lifecycle of "
         "a new cabinet: discovery → water → electricity → faults → recovery.")

    # ─────────────────────────────────────────────────────────────────────
    # A — INITIALISATION
    # ─────────────────────────────────────────────────────────────────────
    h2(doc, "3.A  Initialisation — new cabinet comes online")

    tc(doc, "TC-A01", "Auto-discovery of a new cabinet (v3.7)",
       preconditions=[
           "Section 2 prerequisites verified.",
           "`pedestals` table in pedestal.db is empty (or this cabinetId has never been seen).",
           "Pedestal cabinet is powered off.",
           "Window A: Pedestal SW UI is open at the fleet/sidebar view.",
           "Window B Pane 1 is subscribed to `opta/#`.",
       ],
       steps=[
           "1. Power on the cabinet.",
           "2. Wait up to 60 s while watching both windows.",
       ],
       expected=[
           "Window B Pane 1: a retained `opta/status` message arrives with cabinetId, seq=0, uptime_ms, door=closed.",
           "Window B Pane 2 (journal): line `auto-registered pedestal <CAB_ID>`.",
           "Window A: a new pedestal card appears in the sidebar with a prettified name (`MAR_KRK_ORM_01` → `MAR KRK ORM 01`) and a green online dot.",
           "A `pedestal_registered` WebSocket event fires with `is_new=true`; a bottom-right toast `New pedestal discovered: …` appears.",
       ])

    tc(doc, "TC-A02", "RTC time sync on seq=0 (v3.4)",
       preconditions=["TC-A01 passed."],
       steps=[
           "1. Watch Window B Pane 1 immediately after TC-A01 succeeds.",
       ],
       expected=[
           "Within 1 s of the seq=0 heartbeat, the backend publishes on `opta/cmd/time` with payload `{msgId, action:'sync', epoch, iso}`.",
           "Pane 2: line `RTC sync scheduled, next in 3600s`.",
           "A second publish on `opta/cmd/time` happens 60 ± 5 minutes later (verify by leaving the tracer running across one hour, or accept on visual inspection of the timer log).",
       ])

    tc(doc, "TC-A03", "Hardware config received and rendered (v3.11)",
       preconditions=[
           "TC-A01 passed.",
           "Opta firmware publishes `opta/config/hardware` as retained (per Broker_Firmware_Contract §3.1.1).",
       ],
       steps=[
           "1. In Pane 1, locate the retained payload on `opta/config/hardware`.",
           "2. In Window A, open the pedestal → Control Center → Sockets section, then inspect each SocketCard.",
       ],
       expected=[
           "Pane 1 payload contains 4 sockets with `phases` and `ratedAmps` (Q1=1Φ/16A, Q2=1Φ/16A, Q3=1Φ/32A, Q4=3Φ/65A) and 2 valves.",
           "Each SocketCard Hardware Info section shows the meter type and ratedAmps; NO amber `Awaiting hardware configuration` banner.",
           "DB check: `socket_configs.phases` and `rated_amps` are populated for all four sockets.",
       ])

    tc(doc, "TC-A04", "Diagnostic auto-fire and per-valve water auto-open (v3.9)",
       preconditions=[
           "TC-A03 passed.",
           "Both `valve_configs` rows have `auto_activate=TRUE` (the v3.9 default for newly-discovered valves).",
       ],
       steps=[
           "1. Watch Pane 1 for the broker → device sequence.",
       ],
       expected=[
           "~5 s after first heartbeat the backend publishes `opta/cmd/diagnostic`.",
           "Firmware replies on `opta/diagnostic` with `water_v1='ok'`, `water_v2='ok'`, and per-socket power statuses.",
           "Within 2 s after the diagnostic reply, backend publishes `opta/cmd/water/V1` and `opta/cmd/water/V2` with `action='activate'`.",
           "Firmware emits `OutletActivated` events; backend creates two sessions with `customer_id=NULL`.",
           "Window A: two valve cards show amber `UNATTRIBUTED` badge + green `AUTO` badge.",
       ])

    tc(doc, "TC-A05", "Zero-flow safety watchdog (v3.9)",
       preconditions=[
           "TC-A04 just passed.",
           "Hose physically disconnected from V1.",
       ],
       steps=[
           "1. Wait 35 s after the V1 auto-open publish.",
       ],
       expected=[
           "Pane 2: line `valve_flow_warning V1 zero flow after 30s`.",
           "Window A: warning banner on V1 card `Zero flow — hose may be disconnected`; admin gets a browser notification.",
           "V1 remains open (the watchdog is informational, not a stop).",
       ])

    # ─────────────────────────────────────────────────────────────────────
    # B — ELECTRICITY happy path
    # ─────────────────────────────────────────────────────────────────────
    doc.add_page_break()
    h2(doc, "3.B  Electricity — first socket use case (default + auto-activate)")

    para(doc,
         "Primary scenario requested: cabinet is powered, first socket is "
         "discovered, and a user plugs a cable in. First we test the default "
         "(operator must press Activate). Then we test the 'works immediately' "
         "variant by enabling auto_activate=TRUE on the socket.")

    tc(doc, "TC-B01", "Default plug-in flow — operator activates manually (v3.4 + v3.5 default)",
       preconditions=[
           "TC-A03 passed.",
           "`socket_configs` row for Q1 has `auto_activate=FALSE` (the v3.5 default).",
           "Cabinet door closed.",
           "Q1 is idle (no active session).",
       ],
       steps=[
           "1. Insert a CEE 16A cable into Q1 (firmware emits UserPluggedIn).",
           "2. In Window A, observe the Q1 socket card.",
           "3. Click the `Activate` button on the Q1 card.",
       ],
       expected=[
           "Step 1-2: Pane 1 shows `opta/events` payload `eventType=UserPluggedIn`. Q1 card turns yellow (`pending`) with tooltip `Plug inserted — awaiting activation`. Activate button becomes enabled.",
           "Step 3: Pane 1 shows backend publish on `opta/cmd/socket/Q1` with `{msgId, cabinetId, action:'activate'}`, then firmware ACK on `opta/acks` and `OutletActivated` on `opta/events`.",
           "Q1 card turns green (`active`). Stop button replaces Activate. Live kW / kWh readings update every ~15 s via `TelemetryUpdate`.",
           "DB: a new row in `sessions` with `customer_id=NULL`, `status='active'`.",
       ])

    tc(doc, "TC-B02", "Auto-activate ON — socket works immediately on plug-in (v3.5)",
       preconditions=[
           "TC-B01 stopped (session ended via TC-B04 or equivalent).",
           "Q1 idle.",
           "Tester used the SocketCard `Auto-activate` toggle to set `auto_activate=TRUE` (UI shows green `AUTO` badge next to Q1).",
           "All 5 preconditions hold: door closed, no active alarm on pedestal, heartbeat within 300 s, Q1 not already active, no diagnostic in the last 60 s.",
       ],
       steps=[
           "1. Insert the CEE 16A cable into Q1.",
           "2. Do nothing else — observe.",
       ],
       expected=[
           "Q1 card flashes yellow (`pending`) briefly. Tooltip changes to `Plug inserted — auto-activating in 2s`.",
           "After ~2 s firmware stabilisation delay, Pane 1 shows the backend publishing `opta/cmd/socket/Q1` activate without any UI click.",
           "Q1 turns green and the session starts.",
           "DB: `auto_activation_log` row with `status='success'`, `socket_id='Q1'`.",
       ])

    tc(doc, "TC-B03", "Auto-activate blocked by precondition (v3.5)",
       preconditions=[
           "Q1 `auto_activate=TRUE`.",
           "Cabinet door OPEN (verify door=open badge in UI and retained `opta/door/status`).",
       ],
       steps=[
           "1. Insert cable into Q1.",
           "2. Observe UI and Pane 1 for 10 s.",
           "3. Close the cabinet door.",
           "4. Unplug and re-plug the cable.",
       ],
       expected=[
           "Step 1-2: Q1 turns `pending` but stays there. NO `opta/cmd/socket/Q1` activate publish in Pane 1. UI shows amber skip-reason banner `Auto-activate skipped — door open`. DB: `auto_activation_log` row `status='skipped'`, `reason='door_open'`.",
           "Step 3-4: Door state flips to closed; on the new plug-in event the auto-activate runs normally.",
           "Repeat the test for the other precondition reasons by inducing each in turn (active hardware alarm, stale heartbeat, recent diagnostic) — verify each produces the documented `reason` string.",
       ])

    tc(doc, "TC-B04", "Operator stops an active session",
       preconditions=["Q1 has an active session (from TC-B01 or TC-B02)."],
       steps=[
           "1. In Window A, click `Stop` on Q1.",
           "2. Confirm the dialog.",
       ],
       expected=[
           "Pane 1: backend publishes `opta/cmd/socket/Q1` with `action='stop'`. Firmware ACK + `SessionEnded` event.",
           "Q1 returns to `pending` (cable still inserted) or `idle` (if cable was already out).",
           "DB: session row updated to `status='completed'`, `end_reason='operator_stop'`.",
       ])

    tc(doc, "TC-B05", "User unplugs the cable",
       preconditions=["Q1 has an active session."],
       steps=[
           "1. Physically pull the cable out of Q1.",
       ],
       expected=[
           "Pane 1 sequence: `UserPluggedOut` event → backend publishes `opta/cmd/socket/Q1` stop → firmware `SessionEnded`.",
           "Q1 turns white (`idle`).",
           "DB: session `end_reason='user_unplugged'`.",
       ])

    # ─────────────────────────────────────────────────────────────────────
    # C — WATER
    # ─────────────────────────────────────────────────────────────────────
    doc.add_page_break()
    h2(doc, "3.C  Water — opt-out behaviour")

    tc(doc, "TC-C01", "Water flows immediately after boot (v3.9 default ON)",
       preconditions=["TC-A04 passed; unattributed V1 session is active."],
       steps=[
           "1. Connect hose to V1; open the tap downstream.",
           "2. Let water flow for 30 s.",
       ],
       expected=[
           "Pane 1: `TelemetryUpdate` events every ~15 s with `flowLpm > 0` and growing `waterLitersTotal`.",
           "Window A V1 card shows live LPM and session litres.",
           "Volume in measuring jug matches reported litres within ±5%.",
       ])

    tc(doc, "TC-C02", "Operator opt-out — valve does not auto-open on next boot",
       preconditions=[
           "In Window A, set V2 `auto_activate=FALSE` via the WaterCard toggle.",
           "Cabinet power-cycled (or backend restarted) after the toggle is saved.",
       ],
       steps=[
           "1. Wait for the full initialisation sequence (TC-A01..A04 minus the V2 activate).",
           "2. Watch Pane 1 for `opta/cmd/water/V2` during the first 60 s after the diagnostic reply.",
       ],
       expected=[
           "No `opta/cmd/water/V2` activate publish.",
           "V1 still auto-opens normally; V2 stays closed.",
           "DB: `valve_configs.auto_activate=0` for V2, persisted across restart.",
       ])

    tc(doc, "TC-C03", "10-minute cooldown after operator stop (v3.9 guard)",
       preconditions=["Water session active on V1 (TC-C01)."],
       steps=[
           "1. In Window A, click `Stop` on V1.",
           "2. Wait 30 s.",
           "3. Click `Run Diagnostics` in Control Center to trigger another diagnostic reply.",
       ],
       expected=[
           "Step 1: V1 closes, session ends.",
           "Step 3: even though the diagnostic returns `water_v1='ok'`, backend does NOT publish auto-activate on V1.",
           "Pane 2: `V1 auto-open skipped, operator-stopped within last 10 min`.",
           "After 10+ minutes the next diagnostic does open V1 again.",
       ])

    # ─────────────────────────────────────────────────────────────────────
    # D — BREAKER (the key requested scenario)
    # ─────────────────────────────────────────────────────────────────────
    doc.add_page_break()
    h2(doc, "3.D  Breaker — trip detection and remote reset from Pedestal SW (v3.8)")

    para(doc,
         "Primary scenario requested: a breaker trips, the tester sees the "
         "notification in the Pedestal SW UI, and resets it remotely without "
         "physical access. Assumes the firmware items in Broker_Firmware_Contract "
         "§3.2 are implemented.")

    tc(doc, "TC-D01", "Retained breaker state visible at startup",
       preconditions=[
           "Cabinet just booted (TC-A01..A03 done).",
           "All four physical breakers are mechanically closed.",
       ],
       steps=[
           "1. In Pane 1, locate retained messages on `opta/breakers/Q{1..4}/status`.",
           "2. In Window A, open Pedestal → Control Center; each SocketCard now has a SocketBreakerPanel.",
       ],
       expected=[
           "Pane 1: four retained payloads, each with `state='closed'` and metadata (type, rating, poles, rcd, rcdSensitivity).",
           "Window A: each panel shows a green state dot `CLOSED` and the Hardware Info fields populated (no `Not reported`).",
           "No red alarm banner at the top of Control Center.",
       ])

    tc(doc, "TC-D02", "Breaker trip caused by overcurrent (v3.8 BreakerTripped flow)",
       preconditions=[
           "Q1 has an active session.",
           "Load tester rigged to push Q1 over its 16 A rating.",
       ],
       steps=[
           "1. Ramp the load on Q1 to 18-20 A until the breaker physically trips.",
           "2. Watch Pane 1 and Window A.",
       ],
       expected=[
           "Pane 1: `opta/events` event `eventType='BreakerTripped'`, `breaker.cause='overcurrent'`, `breaker.prevState='closed'`.",
           "Pane 1: retained `opta/breakers/Q1/status` updated to `state='tripped'` (overwrites the previous `closed`).",
           "Window A: red banner at the top of Control Center `Breaker tripped on Q1`. Q1 SocketCard shows a red state dot `TRIPPED` and a ⚡ overlay on the pedestal picture. Browser notification fires for admin role.",
           "DB: active session on Q1 closed with `end_reason='breaker_trip'`; new row in `breaker_events` with `cause='overcurrent'`, `prev_state='closed'`.",
       ])

    tc(doc, "TC-D03", "Remote breaker reset — SUCCESS (root cause cleared)",
       preconditions=[
           "TC-D02 left Q1 in `tripped` state.",
           "Load tester DISCONNECTED — overcurrent root cause removed.",
           "Tester logged in as admin (monitor cannot click Reset, see TC-D05).",
       ],
       steps=[
           "1. In Window A, dismiss the top alarm banner (or leave it).",
           "2. On the Q1 SocketBreakerPanel click `Reset Breaker`.",
           "3. Confirm the dialog.",
       ],
       expected=[
           "Pane 1: backend publishes `opta/cmd/breaker/Q1` with `{msgId, cabinetId, action:'reset'}`. Firmware ACK on `opta/acks`.",
           "Pane 1: retained `opta/breakers/Q1/status` transitions `tripped` → `resetting` → `closed` over ~1-2 s.",
           "Window A: state dot transitions red → grey (spinner) → green. The breaker-trip alarm is auto-resolved and removed from the top banner.",
           "Q1 is once again ready for activation — a fresh plug-in triggers the normal v3.4 flow.",
           "DB: `breaker_events` audit row tagged with `reset_initiated_by=<admin email>`.",
       ])

    tc(doc, "TC-D04", "Remote breaker reset — FAIL (fault still present)",
       preconditions=[
           "Q1 `tripped`.",
           "Load tester STILL CONNECTED at 20 A (fault not cleared).",
       ],
       steps=[
           "1. In Window A click `Reset Breaker` on Q1.",
       ],
       expected=[
           "Same publish + ACK as TC-D03.",
           "`opta/breakers/Q1/status` goes `tripped` → `resetting` → back to `tripped` (instead of `closed`).",
           "A new `BreakerTripped` event is appended.",
           "Window A: toast `Breaker reset failed — fault still present`; the alarm banner remains.",
           "DB: a second `breaker_events` row with the same socket; tester is expected to clear the underlying fault before re-trying.",
       ])

    tc(doc, "TC-D05", "Monitor role cannot reset breaker (RBAC)",
       preconditions=[
           "Q1 `tripped`.",
           "Sign out of admin in Window A and sign back in as `monitor@test.local`.",
       ],
       steps=[
           "1. Navigate to the same Control Center page.",
           "2. Attempt to click `Reset Breaker` on Q1.",
       ],
       expected=[
           "`Reset Breaker` button is disabled (or hidden) for monitor role.",
           "Browser DevTools network tab: no `POST /api/pedestals/.../breaker/reset` request fires (button gated client-side).",
           "If the request is forced via DevTools, backend returns HTTP 403.",
           "Pane 1: no `opta/cmd/breaker/Q1` publish.",
       ])

    # ─────────────────────────────────────────────────────────────────────
    # E — OVERLOAD PROTECTION (v3.11 + v3.12 — the LATEST critical feature)
    # ─────────────────────────────────────────────────────────────────────
    doc.add_page_break()
    h2(doc, "3.E  Load monitoring and 90% auto-stop overload protection (v3.11 + v3.12)")

    tc(doc, "TC-E01", "Meter telemetry arrives at 5 s cadence (v3.11)",
       preconditions=["TC-A03 passed (`opta/config/hardware` received → `rated_amps` populated)."],
       steps=[
           "1. With no active session, watch Pane 1 for `opta/meters/+/telemetry` for 30 s.",
       ],
       expected=[
           "One payload per socket every ~5 s.",
           "Q1/Q2/Q3 payload is single-phase shape (`currentAmps`, `voltageV`, `powerKw`, `powerFactor`, `energyKwh`, `frequency`).",
           "Q4 payload is three-phase shape (`currentAmpsL1/L2/L3`, `currentAmpsTotal`, `voltageL1/L2/L3`, `powerKwTotal`).",
           "Window A SocketLoadMeterPanel shows live readings updating every tick.",
       ])

    tc(doc, "TC-E02", "60% warning → 80% critical state transitions (v3.11)",
       preconditions=[
           "Q1 has an active session, `rated_amps=16` from TC-A03.",
           "Load tester can hold 10 A then 13 A.",
       ],
       steps=[
           "1. Set load to ~10 A (62%) and wait one 5 s tick.",
           "2. Increase to ~13 A (81%).",
       ],
       expected=[
           "Step 1: DB new row in `meter_load_alarms` `severity='warning'`. Window A shows yellow load bar and a warning ribbon.",
           "Step 2: previous warning auto-resolved with `resolved_by='auto-upgrade'`; new row `severity='critical'`. Browser notification fires. Session continues running.",
           "Hysteresis: dropping back to 11 A does NOT immediately downgrade — must fall below 78% (threshold − 2).",
       ])

    tc(doc, "TC-E03", "90% auto-stop with latch + acknowledge (v3.12)",
       preconditions=["TC-E02 step 2 just passed (Q1 critical state, active session, load tester present)."],
       steps=[
           "1. Increase load on Q1 to ~14.5 A (~91%).",
           "2. After the auto-stop fires, in Window A click `Activate` on Q1 (expect block).",
           "3. In Window A → System Health → AUTO-STOP ALARMS card, click `Acknowledge & Enable Re-activation` and confirm the warning dialog.",
           "4. Click `Activate` on Q1 again.",
       ],
       expected=[
           "Step 1: Pane 1 — backend publishes `opta/cmd/socket/Q1` with `action='stop'` (same shape as operator stop, includes `msgId` and `cabinetId`). Session closes with `end_reason='auto_stop_overload'`.",
           "DB: new `meter_load_alarms` row `alarm_type='auto_stop'`; any open warning/critical rows for Q1 are resolved with `resolved_by='auto-stop-supersedes'`; `socket_configs.auto_stop_pending_ack=1` on Q1.",
           "Window A: red banner `⚡ AUTO-STOP — OVERLOAD PROTECTION ACTIVATED` on Q1 SocketLoadMeterPanel. Activate button disabled with tooltip `Acknowledge the overload alarm first`. Admin browser notification fires (⚡ + percentage).",
           "Step 2: clicking Activate calls the API which returns HTTP 409 `overload alarm pending acknowledgment` (visible in DevTools). NO MQTT publish.",
           "Step 3: `POST /api/pedestals/{pid}/sockets/{sid}/load/auto-stop/acknowledge` clears `auto_stop_pending_ack`, marks the alarm row acknowledged with admin email, broadcasts `meter_load_auto_stop_acknowledged`.",
           "Step 4: Activate now proceeds normally — full v3.4 sequence runs.",
       ])

    # ─────────────────────────────────────────────────────────────────────
    # F — OTHER ALARMS
    # ─────────────────────────────────────────────────────────────────────
    doc.add_page_break()
    h2(doc, "3.F  Other alarms")

    tc(doc, "TC-F01", "Door open while session active",
       preconditions=["Q1 session active, cabinet door closed."],
       steps=["1. Open the cabinet door."],
       expected=[
           "Pane 1: retained `opta/door/status` updated to `door='open'`.",
           "Window A: door badge in the pedestal card switches to open (red icon).",
           "Active Q1 session keeps running (door open is not a destructive event for an already-active socket).",
           "Any new plug-in event on a different socket with `auto_activate=TRUE` is BLOCKED with reason `door_open` (cross-check with TC-B03 logic).",
       ])

    tc(doc, "TC-F02", "Temperature > 50°C alarm (legacy SNMP/sensor)",
       preconditions=["Cabinet initialised."],
       steps=[
           "1. Induce a high-temperature reading (heater near the temperature sensor, or PLC simulation).",
       ],
       expected=[
           "Backend persists a `hardware_alarm` of `alarm_type='temperature_high'`.",
           "Window A: red banner in System Health + persistent red dot in the navigation badge. Admin browser notification.",
           "Alarm does not self-resolve — admin must acknowledge in System Health.",
       ])

    tc(doc, "TC-F03", "Moisture > 90% alarm",
       preconditions=["Cabinet initialised."],
       steps=["1. Induce a high moisture reading on the moisture sensor."],
       expected=[
           "`hardware_alarm` row with `alarm_type='moisture_high'`. Same UI behaviour as TC-F02.",
       ])

    # ─────────────────────────────────────────────────────────────────────
    # G — RESILIENCE
    # ─────────────────────────────────────────────────────────────────────
    doc.add_page_break()
    h2(doc, "3.G  Resilience and edge cases")

    tc(doc, "TC-G01", "MQTT disconnect cleanup",
       preconditions=["At least one active session (Q1 electricity and V1 water)."],
       steps=[
           "1. Disconnect the Opta from the LAN (pull Ethernet).",
           "2. Wait 6 minutes.",
       ],
       expected=[
           "After 5 min of heartbeat silence, backend marks pedestal offline (sidebar dot red).",
           "All active sessions for that pedestal closed with `end_reason='disconnect'`.",
           "DB invariant: no orphan `status='active'` sessions remain.",
           "Reconnect the LAN cable and verify the pedestal comes back online via fresh heartbeat (TC-A01-style flow); no duplicate auto-registration.",
       ])

    tc(doc, "TC-G02", "Operator-initiated pedestal reset",
       preconditions=["1-2 active sessions."],
       steps=[
           "1. In Window A → Control Center → Reset card, double-click confirm.",
       ],
       expected=[
           "Pane 1: backend publishes `opta/cmd/reset` with `{cabinetId, cmd:'reset'}`.",
           "Firmware closes all sessions; backend writes `end_reason='device_reset'` for each.",
           "Cabinet re-initialises and produces a fresh seq=0 heartbeat → flow continues from TC-A01.",
       ])

    tc(doc, "TC-G03", "Operator rename survives a restart (v3.7)",
       preconditions=["Pedestal registered with an auto-prettified name."],
       steps=[
           "1. In Pedestal Detail, rename the cabinet to `Marina Krk — Pier 3 Cabinet 1` and save.",
           "2. Power-cycle the Opta.",
           "3. Wait for the next heartbeat.",
       ],
       expected=[
           "Display name persists as `Marina Krk — Pier 3 Cabinet 1`. The v3.7 auto-prettify path does NOT overwrite operator renames.",
       ])

    tc(doc, "TC-G04", "QR label generated on first contact (v3.7)",
       preconditions=["TC-A01 passed for a previously-unseen cabinet."],
       steps=[
           "1. On the NUC: `ls /opt/cloud-iot/backend/static/qr/`.",
           "2. In Window A → Control Center → QR Codes section, click `Download All`.",
       ],
       expected=[
           "Step 1: four PNGs `<CAB_ID>_Q1.png`..`Q4.png`, each 300×300 with a `{cabinet spaced} — Q{n}` caption.",
           "Step 2: a ZIP downloads containing all 4 PNGs.",
       ])

    tc(doc, "TC-G05", "Auth rate limit (defensive — slowapi)",
       preconditions=[
           "`APP_ENV=production` and/or `RATE_LIMIT_ENABLED=true` confirmed in .env.",
           "Tester is signed out.",
       ],
       steps=[
           "1. On the login page, submit 11 failed login attempts within 60 s (wrong password).",
       ],
       expected=[
           "Attempts 11+ return HTTP 429 with the rate-limit message.",
           "Attempts 1-10 returned 401.",
           "After 60 s the counter resets and a fresh attempt is accepted again.",
       ])

    # ─────────────────────────────────────────────────────────────────────
    # H — REGRESSION TESTS FROM PRIOR-OPTA TRACE
    # ─────────────────────────────────────────────────────────────────────
    doc.add_page_break()
    h2(doc, "3.H  Regression tests from prior-Opta MQTT trace (2026-04-20)")

    para(doc,
         "An MQTT capture taken from the previous NUC + Opta on 2026-04-20 "
         "exposed seven defects on the firmware/broker boundary. The new NUC "
         "carries the same broker IP (192.168.1.167) and the same cabinetId "
         "(`MAR_KRK_ORM_01`), so the same trace format applies. These TCs "
         "explicitly re-check each defect against the v3.12 broker + the "
         "assumed firmware updates from Broker_Firmware_Contract §3.")

    para(doc, "Defect summary (reference: anomalies in the 2026-04-20 trace):", bold=True)
    add_table(doc,
              ["ID", "Defect observed", "Re-checked by"],
              [
                  ["H1", "opta/acks `cmd_topic` field corrupted (`\"�\"` after activate, `\"0_\"` after stop) — should be the original command topic string", "TC-H01"],
                  ["H2", "Diagnostic shows `\"time\":\"NOT_SYNCED\"`; all event `occurredAt` timestamps are 1970-01-01 — RTC sync never happened and no `opta/cmd/time` publish was seen in the entire session", "TC-H02"],
                  ["H3", "`opta/door/status` retained payload only updates at the next 60 s heartbeat tick, not on the actual DoorOpened/Closed event — rapid door events get coalesced and lost", "TC-H03"],
                  ["H4", "Operator activate succeeded on Q1/Q3/Q4 with no prior UserPluggedIn for those outlets — pre-v3.4 missing plug-state gate", "TC-H04"],
                  ["H5", "After SessionEnded, socket status keeps reporting `hw_status:\"on\"` while `state:\"idle\"` — relay-state field doesn't follow the state transition", "TC-H05"],
                  ["H6", "Legacy bridge topic `marina/cabinet/MAR_KRK_ORM_01/outlet/PWR-1/cmd/stop` still being published alongside `opta/cmd/socket/Q1` — old pre-v3 control path was not removed", "TC-H06"],
                  ["H7", "Every operator stop immediately produces a fresh UserPluggedIn event for the same outlet (11:18:10 stop → 11:18:10 plug-in, 11:18:32 stop → 11:18:32 plug-in, etc.) — firmware emits phantom plug events on stop", "TC-H07"],
              ])

    tc(doc, "TC-H01", "ACK cmd_topic is a readable UTF-8 string matching the originating command (defect H1)",
       preconditions=[
           "Cabinet online, Q1 idle, cable plugged into Q1 (Q1 in `pending`).",
           "Window B Pane 1 actively tracing `#` so every `opta/acks` payload is captured.",
       ],
       steps=[
           "1. In Window A click `Activate` on Q1.",
           "2. Wait for the ACK in Pane 1.",
           "3. Click `Stop` on Q1.",
           "4. Wait for the second ACK.",
       ],
       expected=[
           "Both ACK payloads have `cmd_topic` equal to the exact topic string that was published — `\"cmd_topic\":\"opta/cmd/socket/Q1\"`.",
           "No replacement-character glyph (U+FFFD `�`), no garbled bytes, no `\"0_\"`.",
           "FAIL CRITERION (the old defect): if `cmd_topic` is `\"�\"` or `\"0_\"` or any non-ASCII garbage, the firmware string handling for the ACK builder is still broken.",
       ])

    tc(doc, "TC-H02", "RTC sync fires on seq=0 and clears `NOT_SYNCED` (defect H2)",
       preconditions=[
           "Cabinet online.",
           "Window B Pane 1 must be subscribed BEFORE the power-cycle to catch seq=0 (the retained `opta/status` shows only the latest value, so a late subscriber will miss it).",
       ],
       steps=[
           "1. Power-cycle the Opta (main MCB OFF then ON).",
           "2. From Pane 1, capture the very first non-retained `opta/status` after boot.",
           "3. Watch for `opta/cmd/time` from the broker.",
           "4. In Window A click `Run Diagnostics`.",
           "5. Read the `opta/diagnostic` response in Pane 1.",
           "6. Plug a cable into any socket and check the resulting `UserPluggedIn` event payload.",
       ],
       expected=[
           "Step 2: first heartbeat after boot has `seq:0`, `uptime_ms` < 30000 (small).",
           "Step 3: within 1 s of seq=0, broker publishes `opta/cmd/time` with `{msgId, action:'sync', epoch, iso}`. (Old trace: this publish was missing entirely.)",
           "Step 5: diagnostic response `time` field is an ISO timestamp from 2026, NOT `\"NOT_SYNCED\"`.",
           "Step 6: `UserPluggedIn` event `occurredAt` reads `2026-...Z`, NOT `1970-01-01T...Z`.",
       ])

    tc(doc, "TC-H03", "Retained door status updates on the actual event, not at the next heartbeat (defect H3)",
       preconditions=[
           "Cabinet online. Door currently closed (verify retained `opta/door/status` shows `door:closed`).",
           "Note exact wall-clock time before starting.",
       ],
       steps=[
           "1. Open the cabinet door at T+0.",
           "2. In Pane 1, note the timestamp of the next `opta/door/status` retained publish AND the timestamp of the `opta/events DoorOpened` event.",
           "3. Within 5 s rapidly open/close the door 3 more times.",
           "4. Verify each transition produces both a `DoorOpened`/`DoorClosed` event AND a retained `opta/door/status` update.",
       ],
       expected=[
           "Step 2: the retained `opta/door/status` payload with `door:open` arrives within ≤ 2 s of T+0, NOT delayed until the next 60 s heartbeat.",
           "Step 4: every door transition produces a matching retained-status update — no coalescing, no missed transitions.",
           "FAIL CRITERION (the old defect): if the retained door status only updates at the 60 s tick (matching the heartbeat cadence), the firmware is still piggybacking door status on the heartbeat loop instead of publishing on transition.",
       ])

    tc(doc, "TC-H04", "Operator activate is rejected when no plug is inserted (defect H4 / v3.4 plug-state gate)",
       preconditions=[
           "Cabinet online.",
           "Q1 in `idle` state (no plug inserted — verify `opta/sockets/Q1/status` has `state:\"idle\"` and there has been NO recent `UserPluggedIn` event for Q1).",
           "Browser DevTools Network tab open in Window A.",
       ],
       steps=[
           "1. In Window A, the `Activate` button on Q1 should be visibly disabled with tooltip `No plug inserted`.",
           "2. Force the call anyway: in DevTools Console, run `fetch('/api/controls/pedestal/<pid>/socket/Q1/cmd', {method:'POST', headers:{'Content-Type':'application/json','Authorization':'Bearer <admin JWT>'}, body:JSON.stringify({action:'activate'})}).then(r=>r.status)`.",
       ],
       expected=[
           "Step 1: button is disabled; clicking it does nothing.",
           "Step 2: response status is HTTP 409 with body containing `Socket has no plug inserted`.",
           "Pane 1: NO `opta/cmd/socket/Q1` publish appears — the broker refused to forward the command.",
           "FAIL CRITERION (the old defect): if a publish DOES appear on `opta/cmd/socket/Q1` and `OutletActivated` follows, the v3.4 plug-state gate is missing or bypassed.",
       ])

    tc(doc, "TC-H05", "hw_status follows state transition on session stop (defect H5)",
       preconditions=["Q1 has an active session (`opta/sockets/Q1/status` shows `state:\"active\"`, `hw_status:\"on\"`)."],
       steps=[
           "1. In Window A click `Stop` on Q1.",
           "2. In Pane 1, capture the next `opta/sockets/Q1/status` published after the `SessionEnded` event.",
           "3. Also capture the next periodic status tick (60 s later).",
       ],
       expected=[
           "Within ≤ 2 s of `SessionEnded`, `opta/sockets/Q1/status` publishes `state:\"idle\"` AND `hw_status:\"off\"` together.",
           "The 60 s periodic tick continues to report `hw_status:\"off\"` until the next activation.",
           "FAIL CRITERION (the old defect): if the status payload reports `state:\"idle\",\"hw_status\":\"on\"` after stop, the firmware is reading hw_status from a stale relay-feedback flag that isn't cleared on the stop path.",
       ])

    tc(doc, "TC-H06", "Legacy `marina/...` bridge topic is silent (defect H6)",
       preconditions=[
           "Cabinet online; at least one electricity session will be started and stopped during this test.",
           "In Window B Pane 1, the tracer is subscribed to `#` (not just `opta/#`) so any legacy topic is visible.",
       ],
       steps=[
           "1. Run a full plug-in / activate / stop cycle on Q1 (per TC-B01 + TC-B04).",
           "2. While running, scan Pane 1 for any topic prefix other than `opta/`.",
       ],
       expected=[
           "ZERO publishes on `marina/#` or any other non-`opta/` topic during normal operation.",
           "Specifically: no `marina/cabinet/MAR_KRK_ORM_01/outlet/PWR-1/cmd/stop` or any variant.",
           "FAIL CRITERION (the old defect): if any `marina/...` publish appears, an old bridge or duplicate publisher is still alive — find it (likely an old systemd unit, an abandoned Node-RED flow, or a leftover client) and remove it.",
       ])

    tc(doc, "TC-H07", "No phantom UserPluggedIn after a stop (defect H7)",
       preconditions=[
           "Q1 has an active session; cable is still physically inserted.",
       ],
       steps=[
           "1. In Window A click `Stop` on Q1 (operator stop, cable stays in).",
           "2. In Pane 1, watch the next 5 s of events for Q1.",
       ],
       expected=[
           "Sequence in Pane 1: `opta/cmd/socket/Q1 stop` → `SessionEnded` → `opta/sockets/Q1/status state:pending` (cable still inserted) — and NOTHING ELSE.",
           "Specifically: NO `UserPluggedIn` event for Q1 should appear in those 5 s.",
           "A real UserPluggedIn must only fire when the plug is physically pulled and re-inserted (verified separately by TC-B05 + replug).",
           "FAIL CRITERION (the old defect): if a `UserPluggedIn` for Q1 follows the stop within < 1 s while the cable was never pulled, the firmware is emitting phantom plug events on every stop — operator would see the socket re-arm immediately and potentially auto-activate again under v3.5.",
       ])

    # ─────────────────────────────────────────────────────────────────────
    # 4. EXIT CRITERIA
    # ─────────────────────────────────────────────────────────────────────
    doc.add_page_break()
    h1(doc, "4. Pass / fail criteria")

    para(doc, "MUST-PASS (release blockers):", bold=True)
    bullet(doc, "A01 (auto-discovery), A03 (hardware config), A04 (water auto-open).")
    bullet(doc, "B01 (default plug-in flow), B02 (auto-activate happy path), B04 (operator stop), B05 (user unplug).")
    bullet(doc, "C01 (water default ON).")
    bullet(doc, "D02 (breaker trip detection), D03 (remote reset success), D05 (RBAC on reset).")
    bullet(doc, "E03 (90% auto-stop + latch + acknowledge — v3.12).")
    bullet(doc, "G01 (MQTT disconnect cleanup), G02 (reset).")
    bullet(doc, "H01 (ACK cmd_topic readable), H02 (RTC sync), H04 (plug-state gate), H07 (no phantom UserPluggedIn) — these four are the regressions that broke the previous installation; they must not recur.")

    para(doc, "SHOULD-PASS (warnings, not blockers):", bold=True)
    bullet(doc, "A02, A05, B03, C02, C03, D01, D04, E01, E02, F01–F03, G03–G05.")
    bullet(doc, "H03 (door event immediacy), H05 (hw_status follows state), H06 (no legacy marina/ topic).")

    para(doc, "Tester sign-off:", bold=True)
    para(doc, "")
    para(doc, "Name: ______________________________   Date: ______________")
    para(doc, "Broker version: ______________   Firmware version: ______________")
    para(doc, "")
    para(doc, "☐ All MUST-PASS green   ☐ Ready for production   ☐ Blocked (see defect log)")

    doc.save(OUT)
    print(f"OK -> {OUT}")


if __name__ == "__main__":
    build()
