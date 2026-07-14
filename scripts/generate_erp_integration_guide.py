"""Generates Cloud_IOT_ERP_Integration_Guide_v3.pdf — the integration proposal
handed to the R&D manager on the MarinaMaster (ERP) side.

v3 adds, on top of v2:
  - Cloudflare-fronted connectivity (NUC reachable via a Cloudflare Tunnel).
  - Smart-Mode control gate: control over the API is honoured only when a
    pedestal's Smart Mode is ON; otherwise the API is view-only.
  - Full dashboard read coverage: new GET /api/ext/pedestals/{id}/status and
    /api/ext/pedestals/{id}/water endpoints.
  - Fail-closed endpoint modes, per-IP rate limiting and request body-size cap.

Rendered with reportlab (no external converter needed).

Run:  python scripts/generate_erp_integration_guide.py
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    XPreformatted, PageBreak, ListFlowable, ListItem,
)

OUT = Path(__file__).resolve().parent.parent / "Cloud_IOT_ERP_Integration_Guide_v3.pdf"

# ── Styles ────────────────────────────────────────────────────────────────────
ss = getSampleStyleSheet()
NAVY = colors.HexColor("#12324f")
BLUE = colors.HexColor("#1d6fb8")
GREY = colors.HexColor("#f2f4f7")
DGREY = colors.HexColor("#5b6b7b")

title = ParagraphStyle("title", parent=ss["Title"], textColor=NAVY, fontSize=24, leading=28)
subtitle = ParagraphStyle("subtitle", parent=ss["Normal"], textColor=DGREY, fontSize=11, leading=15)
h1 = ParagraphStyle("h1", parent=ss["Heading1"], textColor=NAVY, fontSize=15, leading=19, spaceBefore=14, spaceAfter=6)
h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=BLUE, fontSize=12, leading=16, spaceBefore=10, spaceAfter=4)
body = ParagraphStyle("body", parent=ss["Normal"], fontSize=10, leading=14, alignment=TA_LEFT, spaceAfter=5)
bullet = ParagraphStyle("bullet", parent=body, leftIndent=6, spaceAfter=2)
codest = ParagraphStyle("code", parent=ss["Code"], fontName="Courier", fontSize=8.3, leading=11,
                        backColor=GREY, borderPadding=6, textColor=colors.HexColor("#22303c"))
note = ParagraphStyle("note", parent=body, backColor=colors.HexColor("#fff8e1"), borderPadding=6,
                      borderColor=colors.HexColor("#e0c060"), borderWidth=0.5)

F = []  # flowables


def P(t, s=body): F.append(Paragraph(t, s))
def S(h=6): F.append(Spacer(1, h))
def H1(t): F.append(Paragraph(t, h1))
def H2(t): F.append(Paragraph(t, h2))
def CODE(t): F.append(XPreformatted(t, codest))
def NOTE(t): F.append(Paragraph("<b>Note:</b> " + t, note))


def BULLETS(items):
    F.append(ListFlowable(
        [ListItem(Paragraph(i, bullet), leftIndent=10, value="•") for i in items],
        bulletType="bullet", start="•", leftIndent=12,
    ))
    S(3)


def TABLE(headers, rows, widths=None):
    data = [[Paragraph(f"<b>{h}</b>", ParagraphStyle('th', parent=body, textColor=colors.white, fontSize=9)) for h in headers]]
    for r in rows:
        data.append([Paragraph(str(c), ParagraphStyle('td', parent=body, fontSize=9, leading=12)) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GREY]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d3dd")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    F.append(t)
    S(6)


# ══ COVER ════════════════════════════════════════════════════════════════════
P("Cloud_IOT &mdash; Pedestal Software", subtitle)
F.append(Paragraph("ERP Integration Guide", title))
P("Version 3 &nbsp;&bull;&nbsp; MarinaMaster &harr; Pedestal SW integration proposal", subtitle)
S(10)
P("<b>Audience:</b> R&amp;D / Integration manager on the MarinaMaster side.", body)
P("<b>Purpose:</b> a complete, step-by-step plan to connect MarinaMaster to the "
  "Cloud_IOT Pedestal software over the External API, including Cloudflare-fronted "
  "connectivity, authentication, data read/export, remote control, and real-time events.", body)
S(6)
P("<b>Scope of this release (what changed in v3):</b>", body)
BULLETS([
    "Connectivity is via a <b>Cloudflare Tunnel</b> in front of each marina's NUC.",
    "<b>Smart-Mode control gate</b>: control actions over the API are honoured only when the "
    "target pedestal has Smart Mode ON; otherwise the API is strictly view-only.",
    "<b>Full read coverage</b>: new pull endpoints expose every status element the dashboard shows.",
    "<b>Hardening</b>: fail-closed endpoint modes, per-IP rate limiting, and a request body-size cap.",
])

# ══ 1. ARCHITECTURE ═══════════════════════════════════════════════════════════
H1("1. Integration architecture")
P("The integration has two independent channels. Get both working:", body)
BULLETS([
    "<b>Pull (request/response):</b> MarinaMaster calls the Pedestal SW REST API to read data and "
    "issue control commands. Direction: MarinaMaster &rarr; Cloudflare &rarr; NUC.",
    "<b>Push (webhooks):</b> the Pedestal SW POSTs real-time events to a webhook URL that "
    "MarinaMaster hosts. Direction: NUC &rarr; MarinaMaster (public HTTPS receiver).",
])
CODE(
"                         (inbound: pull)\n"
"  +---------------+   HTTPS   +------------+  tunnel  +------------------+\n"
"  | MarinaMaster  | ------->  | Cloudflare | -------> |  NUC / Pedestal  |\n"
"  |   (ERP)       |           |   Edge     |          |   SW  REST API   |\n"
"  |               | <-------  +------------+          |  /api/ext/...    |\n"
"  |  webhook recv |   HTTPS (outbound: push events)   +------------------+\n"
"  +---------------+ <-------------------------------- POST X-API-Key ....\n"
)
NOTE("One NUC serves one marina (all that marina's pedestals). Each marina has its own "
     "Cloudflare hostname and its own API credential. There is no shared multi-marina key.")

# ══ 2. PREREQUISITES ═════════════════════════════════════════════════════════
H1("2. Prerequisites &mdash; who provides what")
TABLE(["Item", "Provided by", "Notes"], [
    ["Cloudflare hostname of the NUC", "Cloud_IOT (us)", "e.g. https://pedestal-krk-orm.example.com"],
    ["API credential (service account or key)", "Cloud_IOT (us)", "See section 4"],
    ["List of pedestal IDs / cabinet IDs", "Cloud_IOT (us)", "Numeric id or opta_client_id (e.g. MAR_KRK_ORM_01)"],
    ["Endpoints &amp; events enabled + Activated", "Cloud_IOT (us)", "Done on the NUC /api-gateway admin page"],
    ["Public HTTPS webhook receiver URL", "MarinaMaster (you)", "To receive push events; must be HTTPS"],
    ["Egress IP range of MarinaMaster", "MarinaMaster (you)", "For optional Cloudflare Access / IP allowlist"],
], widths=[62*mm, 40*mm, 68*mm])

# ══ 3. CLOUDFLARE CONNECTIVITY ═══════════════════════════════════════════════
H1("3. Connectivity via Cloudflare")
P("Each NUC is published to the internet through a <b>Cloudflare Tunnel</b> (cloudflared). "
  "MarinaMaster never talks to the NUC's LAN IP directly &mdash; it always uses the public "
  "Cloudflare hostname over HTTPS. Cloudflare terminates TLS at its edge and forwards the "
  "request through the tunnel to the NUC.", body)
H2("3.1 Base URL")
CODE("BASE = https://<pedestal-hostname>        # supplied per marina\n"
     "All API calls are under:  {BASE}/api/ext/...\n"
     "Auth (service token):     {BASE}/api/auth/service-token")
H2("3.2 What MarinaMaster must configure for Cloudflare")
BULLETS([
    "Use <b>HTTPS only</b> and validate the certificate (standard public CA via Cloudflare).",
    "Send the API token on every request (section 4). Cloudflare does not authenticate the API "
    "call &mdash; it only transports it.",
    "The Pedestal SW rate-limiter reads the real client IP from <b>X-Forwarded-For / "
    "CF-Connecting-IP</b>, which Cloudflare sets automatically. No action needed, but be aware "
    "all MarinaMaster traffic shares one source-IP bucket.",
    "Expect Cloudflare's proxy read-timeout (~100s). Use the single-frame camera endpoint rather "
    "than the continuous MJPEG stream for still snapshots.",
])
H2("3.3 Recommended: Cloudflare Access in front of the API (defense in depth)")
BULLETS([
    "We can place a <b>Cloudflare Access</b> policy on /api/ext/* so only MarinaMaster can reach it "
    "&mdash; using a <b>service token</b> (CF-Access-Client-Id / CF-Access-Client-Secret headers) "
    "or mutual TLS, and/or an <b>IP allowlist</b> of your egress ranges.",
    "This is layered <i>on top of</i> the API token: even a leaked API token cannot be used from an "
    "unauthorised network. Coordinate the service-token pair with us if you want this enabled.",
])
NOTE("The webhook channel (section 7) is OUTBOUND from the NUC to MarinaMaster and does NOT pass "
     "through the NUC's Cloudflare tunnel. MarinaMaster must expose its own public HTTPS receiver.")

# ══ 4. AUTHENTICATION ════════════════════════════════════════════════════════
H1("4. Authentication")
P("Two credential types are supported. <b>Option A (service account) is recommended</b> for "
  "MarinaMaster because it is short-lived and revocable.", body)
H2("4.1 Option A &mdash; service account (recommended)")
P("<b>Step 1 (us):</b> we create an ERP service account on the NUC. Easiest is the "
  "dashboard: <b>Settings &rarr; Add User</b>, choose role <b>\"ERP User\"</b>, and set the "
  "email + password &mdash; that pair is the credential we hand you. (Equivalently, on the NUC "
  "shell:)", body)
CODE("python scripts/create_erp_service_account.py \\\n"
     "       --email erp@marinamaster.example --password <strong-secret>")
P("<b>Step 2 (you):</b> exchange those credentials for a short-lived bearer token:", body)
CODE("POST {BASE}/api/auth/service-token\n"
     "Content-Type: application/json\n\n"
     '{ \"email\": \"erp@marinamaster.example\", \"password\": \"<strong-secret>\" }\n\n'
     "-> 200  { \"access_token\": \"<JWT>\", \"role\": \"api_client\", \"email\": \"...\" }")
P("<b>Step 3 (you):</b> send the token on every API call, and refresh it before it expires "
  "(token lifetime = the NUC's jwt_expire_minutes, typically ~120 min):", body)
CODE("Authorization: Bearer <access_token>")
BULLETS([
    "Revocation is immediate: we disable the account and the credential stops working.",
    "Store the email/password in MarinaMaster's secret store; never in source or logs.",
])
H2("4.2 Option B &mdash; static API key")
P("Alternatively we generate a long-lived static key on the NUC /api-gateway page (Rotate Key) "
  "and hand it to you. You send it the same way: <font face='Courier'>Authorization: Bearer &lt;key&gt;</font>. "
  "Simpler, but revocation means rotating the key and re-distributing it. Prefer Option A.", body)

# ══ 5. WHAT WE ENABLE ════════════════════════════════════════════════════════
H1("5. What we enable on the Pedestal SW side")
P("On the NUC, our admin opens the <b>API Gateway</b> page and, together with you, configures:", body)
BULLETS([
    "<b>Endpoints</b>: each endpoint is enabled in <i>monitor</i> (read/GET only) or <i>bidirectional</i> "
    "(read + control) mode. Read-only endpoints can only be monitor.",
    "<b>Events</b>: the set of webhook events pushed to your receiver.",
    "<b>Webhook URL</b>: your public HTTPS receiver.",
    "<b>Verify</b> then <b>Activate</b>: verification live-tests the enabled GETs; activation turns the "
    "gateway on. Any later config change resets it &mdash; we must re-verify and re-activate.",
])
NOTE("Until we Activate, all /api/ext calls return 403 (\"External API is not active\"). Coordinate "
     "the activation window with us.")

# ══ 6. READING DATA (PULL) ═══════════════════════════════════════════════════
H1("6. Reading data (pull / export)")
P("All read endpoints are GET under {BASE}/api/ext/. Reads are always allowed regardless of a "
  "pedestal's Smart Mode. Key endpoints:", body)
TABLE(["Purpose", "Method &amp; path (under {BASE})"], [
    ["List pedestals", "GET /api/ext/pedestals"],
    ["Pedestal health (opta link, camera, smart_mode)", "GET /api/ext/pedestals/health"],
    ["<b>Env/cabinet status</b> (temp, moisture, door) &mdash; <b>new in v3</b>", "GET /api/ext/pedestals/{id}/status"],
    ["<b>Water valve totals</b> per valve &mdash; <b>new in v3</b>", "GET /api/ext/pedestals/{id}/water"],
    ["Active / pending sessions", "GET /api/ext/sessions/active &bull; /sessions/pending"],
    ["Socket load / meter telemetry", "GET /api/ext/pedestals/{id}/load &bull; /sockets/{sid}/load"],
    ["Breaker state &amp; history", "GET /api/ext/pedestals/{id}/breakers &bull; /breaker/history"],
    ["Alarms (load / breaker)", "GET /api/ext/pedestals/{id}/load/alarms"],
    ["Usage history &amp; monthly reports", "GET /api/ext/pedestals/{id}/usage/history"],
    ["Berth occupancy", "GET /api/ext/pedestals/{id}/berths/occupancy"],
    ["Camera still frame", "GET /api/ext/pedestals/{id}/camera/frame"],
], widths=[95*mm, 75*mm])
P("Example &mdash; read environmental status:", body)
CODE("GET {BASE}/api/ext/pedestals/1/status\n"
     "Authorization: Bearer <token>\n\n"
     "-> 200\n"
     "{\n"
     '  \"pedestal_id\": \"MAR_KRK_ORM_01\",\n'
     '  \"temperature\": { \"value\": 21.4, \"unit\": \"°C\", \"alarm\": false, \"updated_at\": \"...Z\" },\n'
     '  \"moisture\":    { \"value\": 47.0, \"unit\": \"%\",  \"alarm\": false, \"updated_at\": \"...Z\" },\n'
     '  \"door_state\": \"closed\",\n'
     '  \"opta_connected\": true, \"status\": \"online\"\n'
     "}")
NOTE("Two dashboard values are delivered in real time only, via webhook events, not by a GET: "
     "cabinet uptime/seq (event opta_status) and live valve state/hw_status (event opta_water_status). "
     "Subscribe to those events (section 7) if you need them.")

# ══ 7. REAL-TIME EVENTS (PUSH) ═══════════════════════════════════════════════
H1("7. Real-time events (push / webhooks)")
P("When enabled, the Pedestal SW POSTs a JSON body to your webhook URL for each selected event. "
  "MarinaMaster must:", body)
BULLETS([
    "Expose a <b>public HTTPS</b> endpoint that accepts POST and returns 2xx quickly.",
    "Validate the <b>X-API-Key</b> header on each delivery (shared secret we configure) and, "
    "recommended, restrict the source to our egress.",
    "Be tolerant: delivery is best-effort fire-and-forget &mdash; there is no automatic retry, so "
    "reconcile via the pull endpoints if your receiver was down.",
])
P("Representative events: session_created / session_updated / session_completed, "
  "power_reading, water_reading, temperature_reading, moisture_reading, heartbeat, "
  "pedestal_health_updated, breaker_state_changed, breaker_alarm, opta_status (uptime/seq), "
  "opta_water_status (valve state/hw_status), marina_door, diagnostics_result.", body)

# ══ 8. CONTROL (WRITE) + SMART MODE ══════════════════════════════════════════
H1("8. Controlling a pedestal (write) &mdash; Smart-Mode rule")
P("<b>Control over the API is conditional on the target pedestal's Smart Mode.</b> Smart Mode is set "
  "on the pedestal/cabinet itself (firmware), not via the API:", body)
BULLETS([
    "<b>Smart Mode ON</b> &mdash; control endpoints work: start/stop a socket or water valve, "
    "allow / deny / stop a session, reset, LED, breaker reset, config changes.",
    "<b>Smart Mode OFF</b> &mdash; the cabinet runs standalone and ignores NUC commands, so the API "
    "is <b>view-only</b>: any control call returns <b>409</b>. Reads still work.",
])
P("A control endpoint must also be enabled in <i>bidirectional</i> mode (section 5). Example:", body)
CODE("POST {BASE}/api/ext/controls/{session_id}/allow      # approve a charging session\n"
     "POST {BASE}/api/ext/controls/{session_id}/stop       # stop an active session\n"
     "POST {BASE}/api/ext/controls/pedestal/{id}/socket/Q1/cmd   { \"action\": \"activate\" }\n"
     "Authorization: Bearer <token>\n\n"
     "-> 200  on success\n"
     "-> 409  { \"detail\": \"Smart Mode is OFF ... the API is view-only ...\" }")
NOTE("Design your control flows to check for 409 and surface \"pedestal in standalone mode\" to the "
     "operator, rather than treating it as a transient error.")

# ══ 9. ERRORS & LIMITS ═══════════════════════════════════════════════════════
H1("9. Response codes, limits &amp; retries")
TABLE(["Code", "Meaning", "MarinaMaster action"], [
    ["200", "OK", "Process body"],
    ["401", "Missing / invalid / expired token", "Refresh the service token, retry once"],
    ["403", "Gateway not active, endpoint not allowed, or read-only mode", "Coordinate enablement with us"],
    ["404", "Pedestal / resource not found", "Check the id"],
    ["409", "Smart Mode OFF &mdash; control refused (view-only)", "Surface standalone state; do not hammer"],
    ["413", "Request body too large (&gt;1 MB default)", "Reduce payload"],
    ["429", "Rate limit exceeded (per source IP)", "Back off; tune the limit with us"],
    ["502", "Upstream error inside the NUC", "Retry with backoff"],
    ["503", "Feature disabled / not available", "Confirm the feature is enabled"],
], widths=[16*mm, 92*mm, 62*mm])
BULLETS([
    "The gateway applies a <b>per-source-IP rate limit</b> and a <b>1 MB body cap</b>. Tell us your "
    "expected peak polling rate so we set the limit above it (all your traffic is one IP).",
    "Poll at a sensible cadence and prefer webhooks for real-time; use pull to reconcile.",
])

# ══ 10. SECURITY CHECKLIST ═══════════════════════════════════════════════════
H1("10. Security checklist (MarinaMaster side)")
BULLETS([
    "Store the API credential in a secret manager; never in code, tickets, or logs.",
    "Use HTTPS everywhere; validate certificates; never disable TLS verification.",
    "Prefer the service-account token (revocable, short-lived) over the static key.",
    "Validate the X-API-Key header on inbound webhooks; reject anything else.",
    "Adopt Cloudflare Access (service token / mTLS) and/or IP allowlisting with us.",
    "Handle 409 (Smart Mode) and 429 (rate limit) as first-class, expected outcomes.",
])

# ══ 11. INTEGRATION TEST CHECKLIST ═══════════════════════════════════════════
H1("11. Integration test checklist")
TABLE(["#", "Test", "Expected"], [
    ["1", "GET {BASE}/api/ext/pedestals with token", "200 + pedestal list"],
    ["2", "Call any endpoint before we Activate", "403 (not active) &mdash; confirms gating"],
    ["3", "GET /pedestals/{id}/status and /water", "200 + values matching the dashboard"],
    ["4", "Control call while Smart Mode OFF", "409 view-only"],
    ["5", "Control call while Smart Mode ON", "200 + action takes effect"],
    ["6", "Trigger an event; receive it on your webhook", "POST received, X-API-Key validated"],
    ["7", "Send oversized body / hammer requests", "413 / 429 as designed"],
    ["8", "Rotate/disable the credential", "Subsequent calls 401/403"],
], widths=[10*mm, 92*mm, 68*mm])

# ══ 12. CONTACTS ═════════════════════════════════════════════════════════════
H1("12. Coordination &amp; next steps")
BULLETS([
    "We provide: Cloudflare hostname, credential, pedestal IDs, and enable + Activate the agreed "
    "endpoints/events with your webhook URL.",
    "You provide: the webhook receiver URL, your egress IPs, and expected peak polling rate.",
    "Joint step: run the section-11 checklist end to end on one pedestal before going wide.",
])
S(8)
P("<i>Document generated from the live Pedestal SW catalog and gateway behaviour "
  "(git main). Endpoint IDs and modes are configurable per marina on the NUC API Gateway page.</i>",
  subtitle)


def build():
    doc = SimpleDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm, topMargin=16*mm, bottomMargin=16*mm,
        title="Cloud_IOT ERP Integration Guide v3",
        author="Cloud_IOT",
    )
    doc.build(F)
    print(f"[OK] wrote {OUT}")


if __name__ == "__main__":
    build()
