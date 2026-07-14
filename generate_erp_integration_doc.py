"""
Generate ERP Integration Guide PDF for Cloud_IOT Pedestal SW.
Uses reportlab (already in backend/requirements.txt).
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, ListFlowable, ListItem, KeepTogether, HRFlowable
)
from reportlab.platypus.tableofcontents import TableOfContents
from datetime import datetime
import os

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "Cloud_IOT_ERP_Integration_Guide_v3.pdf")

# ── Live catalog loader ──────────────────────────────────────────────────────
# Load the endpoint/event catalog straight from the backend so this guide always
# reflects exactly what the gateway exposes. api_catalog.py is pure data (no
# backend imports), so loading it by path is safe and dependency-free.
import importlib.util as _ilu


def _load_catalog():
    path = os.path.join(os.path.dirname(__file__),
                        "backend", "app", "services", "api_catalog.py")
    spec = _ilu.spec_from_file_location("api_catalog", path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ENDPOINT_CATALOG, mod.EVENT_CATALOG


ENDPOINT_CATALOG, EVENT_CATALOG = _load_catalog()


def _epath(path):
    """Insert zero-width breaks after slashes so long API paths wrap in a cell."""
    return path.replace("/", "/​").replace("_", "_​")


# Short ERP-relevance note per event category (used in the event catalog table).
EVENT_ERP_USE = {
    "Sessions": "Billing &amp; session tracking",
    "Sensors": "Live consumption / monitoring",
    "Health": "Connectivity &amp; maintenance",
    "Discovery": "Provisioning",
    "Billing": "Invoicing",
    "Berths": "Marina &amp; berth management",
    "Diagnostics": "Maintenance",
    "Hardware": "Diagnostics &amp; audit",
    "Controls": "Audit trail",
    "Breaker Management": "Circuit safety",
    "Load Monitoring": "Overload protection",
}

# Colors
BRAND_BLUE = HexColor("#1e3a5f")
BRAND_LIGHT = HexColor("#e8f0fe")
ACCENT = HexColor("#2563eb")
GRAY = HexColor("#6b7280")
LIGHT_GRAY = HexColor("#f3f4f6")
TABLE_HEADER_BG = HexColor("#1e3a5f")
TABLE_ALT_BG = HexColor("#f8fafc")
CODE_BG = HexColor("#f1f5f9")
GREEN = HexColor("#059669")
ORANGE = HexColor("#d97706")

styles = getSampleStyleSheet()

# Custom styles
styles.add(ParagraphStyle(
    "DocTitle", parent=styles["Title"],
    fontSize=26, leading=32, textColor=BRAND_BLUE,
    spaceAfter=6, alignment=TA_CENTER
))
styles.add(ParagraphStyle(
    "DocSubtitle", parent=styles["Normal"],
    fontSize=13, leading=18, textColor=GRAY,
    spaceAfter=20, alignment=TA_CENTER
))
styles.add(ParagraphStyle(
    "H1", parent=styles["Heading1"],
    fontSize=18, leading=24, textColor=BRAND_BLUE,
    spaceBefore=24, spaceAfter=10,
    borderPadding=(0, 0, 4, 0),
))
styles.add(ParagraphStyle(
    "H2", parent=styles["Heading2"],
    fontSize=14, leading=18, textColor=BRAND_BLUE,
    spaceBefore=16, spaceAfter=8
))
styles.add(ParagraphStyle(
    "H3", parent=styles["Heading3"],
    fontSize=12, leading=16, textColor=HexColor("#374151"),
    spaceBefore=12, spaceAfter=6
))
styles.add(ParagraphStyle(
    "BodyText2", parent=styles["Normal"],
    fontSize=10, leading=14, alignment=TA_JUSTIFY,
    spaceAfter=6
))
styles.add(ParagraphStyle(
    "CodeBlock", parent=styles["Normal"],
    fontName="Courier", fontSize=8.5, leading=12,
    backColor=CODE_BG, borderPadding=6,
    spaceBefore=4, spaceAfter=8,
    leftIndent=8
))
styles.add(ParagraphStyle(
    "CodeInline", parent=styles["Normal"],
    fontName="Courier", fontSize=9,
))
styles.add(ParagraphStyle(
    "Note", parent=styles["Normal"],
    fontSize=9.5, leading=13, textColor=HexColor("#1e40af"),
    backColor=BRAND_LIGHT, borderPadding=8,
    spaceBefore=6, spaceAfter=10, leftIndent=8, rightIndent=8
))
styles.add(ParagraphStyle(
    "TableCell", parent=styles["Normal"],
    fontSize=9, leading=12
))
styles.add(ParagraphStyle(
    "TableHeader", parent=styles["Normal"],
    fontSize=9, leading=12, textColor=white, fontName="Helvetica-Bold"
))
styles.add(ParagraphStyle(
    "Footer", parent=styles["Normal"],
    fontSize=8, textColor=GRAY, alignment=TA_CENTER
))


def make_table(headers, rows, col_widths=None):
    """Create a styled table."""
    header_cells = [Paragraph(h, styles["TableHeader"]) for h in headers]
    data = [header_cells]
    for row in rows:
        data.append([Paragraph(str(c), styles["TableCell"]) for c in row])

    t = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
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
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), TABLE_ALT_BG))
    t.setStyle(TableStyle(style_cmds))
    return t


def hr():
    return HRFlowable(width="100%", thickness=0.5, color=HexColor("#d1d5db"),
                       spaceBefore=6, spaceAfter=6)


def code(text):
    return Paragraph(text.replace("\n", "<br/>").replace(" ", "&nbsp;"), styles["CodeBlock"])


def p(text, style="BodyText2"):
    return Paragraph(text, styles[style])


def note(text):
    return Paragraph(f"<b>Note:</b> {text}", styles["Note"])


def bullet_list(items):
    return ListFlowable(
        [ListItem(Paragraph(item, styles["BodyText2"]), bulletColor=ACCENT)
         for item in items],
        bulletType="bullet", bulletFontSize=8, leftIndent=16,
        spaceBefore=4, spaceAfter=8
    )


def build_pdf():
    doc = SimpleDocTemplate(
        OUTPUT_PATH, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2.5*cm, bottomMargin=2*cm,
        title="Cloud_IOT Pedestal SW - ERP Integration Guide",
        author="Lika Digital"
    )

    story = []
    W = doc.width

    # ── COVER ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 60))
    story.append(p("Cloud_IOT Pedestal SW", "DocTitle"))
    story.append(p("ERP Integration Guide", "DocSubtitle"))
    story.append(Spacer(1, 10))
    story.append(hr())
    story.append(Spacer(1, 10))
    story.append(p(f"Version 3.2 (covers SW v3.32) &mdash; {datetime.now().strftime('%B %d, %Y')}", "DocSubtitle"))
    story.append(p("Lika Digital d.o.o.", "DocSubtitle"))
    story.append(Spacer(1, 20))
    story.append(p(
        "This document describes the complete API surface, webhook events, authentication "
        "model, and integration patterns for connecting an external ERP system to the "
        "Cloud_IOT Smart Pedestal management platform. It documents the complete live endpoint "
        "and event catalog, and is written as a concrete integration guide for the MarinaMaster "
        "ERP and its MyMarina end-user mobile application.",
        "BodyText2"
    ))
    story.append(Spacer(1, 10))

    # TOC placeholder
    story.append(p("<b>Contents</b>", "H1"))
    toc_items = [
        "MarinaMaster ERP &mdash; Integration Quick-Start Summary",
        "MVP Pilot &mdash; First Integration Set (Temperature, Berths, Camera)",
        "NFC Activation API (myMarina ERP)",
        "1. Architecture Overview",
        "2. Authentication",
        "3. External API Gateway Setup",
        f"4. Endpoint Catalog ({len(ENDPOINT_CATALOG)} endpoints)",
        f"5. Webhook Event Catalog ({len(EVENT_CATALOG)} events)",
        "6. Core Integration Flows",
        "7. Session Lifecycle &amp; Billing",
        "8. Contracts &amp; Invoices",
        "9. Webhook Payload Reference",
        "10. Error Handling &amp; Resilience",
        "11. Security Considerations",
        "12. Network &amp; Cloudflare Configuration",
        "13. Multi-Client Authentication (Service Accounts)",
        "14. Reference Implementation (ERP-IOT)",
        "15. Quick-Start Checklist",
        "16. Data for the Marina Operator Persona",
        "17. Data Exposed to the MyMarina End-User App",
    ]
    story.append(bullet_list(toc_items))
    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # MARINMASTER ERP — INTEGRATION QUICK-START SUMMARY
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("MarinaMaster ERP &mdash; Integration Quick-Start Summary", "H1"))
    story.append(p(
        "This section provides a high-level overview of all steps required for the MarinaMaster "
        "ERP management team to begin integration with Lika Digital's Cloud_IOT Pedestal SW. "
        "Each step references the detailed section later in this document."
    ))
    story.append(Spacer(1, 6))

    story.append(p("<b>Phase 1 &mdash; Network Connectivity</b>", "H2"))
    steps_phase1 = [
        "<b>Step 1: Determine your network setup.</b> Does MarinaMaster have a static public IP "
        "address? If yes, proceed with Option A. If no, proceed with Option B. "
        "(See Section 12 for full details.)",
        "<b>Step 2 (Option A &mdash; Static IP):</b> Send your server's public IP address and "
        "the port your ERP application runs on to Lika Digital. No further action required from "
        "MarinaMaster &mdash; Lika Digital handles all Cloudflare and DNS configuration.",
        "<b>Step 3 (Option B &mdash; No Static IP):</b> Install <font face='Courier'>cloudflared</font> "
        "on your server, create a tunnel, and send the tunnel ID to Lika Digital. "
        "Lika Digital will configure the DNS record. Full step-by-step instructions are in Section 12.3. "
        "This takes approximately 5 minutes.",
    ]
    for s in steps_phase1:
        story.append(p(s))
        story.append(Spacer(1, 2))

    story.append(p("<b>Phase 2 &mdash; Credentials &amp; Configuration</b>", "H2"))
    steps_phase2 = [
        "<b>Step 4: Provide service account details to Lika Digital.</b> Send the desired "
        "email address and password for your ERP's service account. Lika Digital will create "
        "the account on the Pedestal SW with role <font face='Courier'>api_client</font>. "
        "(See Section 13.)",
        "<b>Step 5: Provide your webhook URL.</b> This is the HTTPS endpoint on the MarinaMaster "
        "side where the Pedestal SW will send real-time events (session started, session completed, "
        "sensor readings, alarms). (See Section 5 for event catalog.)",
        "<b>Step 6: Provide the list of required endpoints and events.</b> Review the endpoint "
        "catalog (Section 4) and event catalog (Section 5). Tell Lika Digital which endpoints "
        "you need and whether each should be <font face='Courier'>monitor</font> (read-only) or "
        "<font face='Courier'>bidirectional</font> (read + write/control).",
        "<b>Step 7 (Optional): Provide IP whitelist or mTLS certificate.</b> For additional "
        "security, provide your server's IP range or a client TLS certificate. Lika Digital "
        "will configure Cloudflare Access policies accordingly.",
    ]
    for s in steps_phase2:
        story.append(p(s))
        story.append(Spacer(1, 2))

    story.append(p("<b>Phase 3 &mdash; Lika Digital Configuration</b>", "H2"))
    story.append(p(
        "Once MarinaMaster provides the above information, Lika Digital will:"
    ))
    story.append(bullet_list([
        "Create the service account on the Pedestal SW.",
        "Configure the API Gateway with MarinaMaster's requested endpoints, events, and webhook URL.",
        "Configure Cloudflare DNS/tunnel routing (and Access policies if requested).",
        "Verify and activate the gateway.",
        "Provide MarinaMaster with the API base URL: <font face='Courier'>https://marina.lika.solutions</font>.",
    ]))

    story.append(p("<b>Phase 4 &mdash; MarinaMaster Implementation</b>", "H2"))
    steps_phase4 = [
        "<b>Step 8: Implement authentication.</b> Call "
        "<font face='Courier'>POST https://marina.lika.solutions/api/auth/service-token</font> "
        "with your service account credentials to obtain a JWT token. Cache it for 7 hours and "
        "refresh before expiry. (See Section 13.3.)",
        "<b>Step 9: Implement API polling.</b> Call the gateway endpoints (e.g., "
        "<font face='Courier'>GET /api/ext/sessions/active</font>) with the JWT in the "
        "<font face='Courier'>Authorization: Bearer</font> header. Implement retry + stale-data "
        "fallback. (See Sections 6 and 10.)",
        "<b>Step 10: Implement webhook handler.</b> Accept incoming POST events at your webhook URL. "
        "Validate the <font face='Courier'>X-API-Key</font> header. Persist events and return "
        "HTTP 200 within 5 seconds. (See Section 5.2 and 9.)",
        "<b>Step 11: Implement control actions (if needed).</b> To approve, deny, or stop sessions "
        "from the ERP, call the bidirectional control endpoints. (See Section 6.2.)",
        "<b>Step 12: Implement billing sync.</b> Listen for <font face='Courier'>session_completed</font> "
        "webhook events and query <font face='Courier'>/api/ext/billing/spending/detail</font> "
        "for reconciliation. (See Section 7.)",
    ]
    for s in steps_phase4:
        story.append(p(s))
        story.append(Spacer(1, 2))

    story.append(p("<b>Phase 5 &mdash; Testing &amp; Go-Live</b>", "H2"))
    steps_phase5 = [
        "<b>Step 13: End-to-end testing.</b> Lika Digital will run the pedestal simulator to "
        "generate test sessions. MarinaMaster verifies that webhook events arrive, API polling "
        "returns correct data, and control actions work.",
        "<b>Step 14: Go-live.</b> Once both parties confirm the integration is working, the "
        "system is ready for production use.",
    ]
    for s in steps_phase5:
        story.append(p(s))
        story.append(Spacer(1, 2))

    story.append(Spacer(1, 8))
    story.append(note(
        "<b>Summary of what MarinaMaster must provide to Lika Digital:</b><br/>"
        "1. Network: Static IP + port, <b>or</b> cloudflared tunnel ID<br/>"
        "2. Service account: desired email + password<br/>"
        "3. Webhook URL (HTTPS)<br/>"
        "4. Required endpoints (with monitor/bidirectional mode)<br/>"
        "5. Required webhook events<br/>"
        "6. (Optional) IP whitelist or mTLS certificate"
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # MVP PILOT — FIRST INTEGRATION SET
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("MVP Pilot &mdash; First Integration Set", "H1"))
    story.append(p(
        "Before wiring the full endpoint and event catalog, MarinaMaster and Lika Digital will "
        "validate the integration with a small, concrete pilot. The pilot exercises every part of "
        "the pipeline &mdash; API key authentication, a per-endpoint toggle, a pull endpoint, a "
        "webhook push event, and a media stream &mdash; against three real use cases. Once these "
        "three work end-to-end, every other capability described in the API segment (Sections 4 and "
        "5) can be enabled the same way, with no new integration mechanics to learn."
    ))
    story.append(p(
        "The three pilot use cases are:"
    ))
    story.append(bullet_list([
        "<b>1. Export temperature sensor state</b> &mdash; the cabinet temperature (Papouch TME "
        "sensor) is pushed to MarinaMaster in real time, including alarm severity.",
        "<b>2. Berth status per berth</b> &mdash; occupied / free status for each berth under a "
        "pedestal, available both on demand (pull) and as a real-time push.",
        "<b>3. Live camera per berth via the NUC</b> &mdash; MarinaMaster obtains a live view of a "
        "defined berth, either as the camera stream URL or as a single JPEG frame fetched through "
        "the NUC.",
    ]))
    story.append(note(
        "All three are <b>monitor (read-only)</b> capabilities &mdash; no control or write access is "
        "required for the pilot. Authentication, base URL, and gateway activation are exactly as "
        "described in the Quick-Start Summary above (service token or API key in the "
        "<font face='Courier'>Authorization: Bearer</font> header; webhook secured with "
        "<font face='Courier'>X-API-Key</font>)."
    ))

    # ── MVP 1 — Temperature ──────────────────────────────────────────────────
    story.append(p("Use Case 1 &mdash; Export Temperature Sensor State", "H2"))
    story.append(p(
        "The cabinet temperature is read from a networked Papouch TME sensor by the NUC every 30 "
        "seconds and pushed to MarinaMaster as a <font face='Courier'>temperature_reading</font> "
        "webhook event. This is a <b>push-only</b> capability &mdash; there is no polling endpoint "
        "for temperature; MarinaMaster receives each reading as it is taken."
    ))
    story.append(p("<b>Event:</b> <font face='Courier'>temperature_reading</font> (enable in the gateway's allowed events).", "BodyText2"))
    story.append(code(
        "{\n"
        '  "event": "temperature_reading",\n'
        '  "data": {\n'
        '    "pedestal_id": 1,\n'
        '    "value": 47.2,\n'
        '    "severity": "warning",\n'
        '    "alarm": true,\n'
        '    "temp_sensor_reachable": true,\n'
        '    "last_temp_sensor_check": "2026-06-14T13:05:00Z",\n'
        '    "timestamp": "2026-06-14T13:05:00Z"\n'
        "  },\n"
        '  "timestamp": "2026-06-14T13:05:01Z"\n'
        "}"
    ))
    story.append(p(
        "<font face='Courier'>severity</font> is <font face='Courier'>null</font> when the reading "
        "is in the normal band, <font face='Courier'>\"warning\"</font> or "
        "<font face='Courier'>\"critical\"</font> otherwise; <font face='Courier'>alarm</font> is "
        "<font face='Courier'>true</font> whenever severity is non-null. The alarm bands are "
        "documented in Section 9.4. If the sensor becomes unreachable the NUC emits a separate "
        "<font face='Courier'>temp_sensor_offline</font> alarm and "
        "<font face='Courier'>temp_sensor_reachable</font> reports <font face='Courier'>false</font>."
    ))

    # ── MVP 2 — Berths ───────────────────────────────────────────────────────
    story.append(p("Use Case 2 &mdash; Berth Status per Berth (Occupied / Free)", "H2"))
    story.append(p(
        "Each berth under a pedestal carries an occupancy bit derived from the camera analysis on "
        "the NUC. MarinaMaster can read it on demand (pull) and also receive a push whenever it "
        "changes."
    ))
    story.append(p("<b>Pull:</b> current occupancy for all berths under a pedestal.", "BodyText2"))
    story.append(code(
        "GET /api/ext/pedestals/{pedestal_id}/berths/occupancy\n"
        "Authorization: Bearer {api_key}\n"
        "\n"
        "# pedestal_id may be the numeric DB id OR the Opta client id,\n"
        "# e.g.  GET /api/ext/pedestals/MAR_KRK_ORM_01/berths/occupancy\n"
        "\n"
        "200 OK\n"
        "{\n"
        '  "pedestal_id": "MAR_KRK_ORM_01",\n'
        '  "berths": [\n'
        '    { "berth_id": 7, "berth_name": "A-12", "occupied": true,\n'
        '      "last_analyzed": "2026-06-14T13:02:11Z" },\n'
        '    { "berth_id": 8, "berth_name": "A-13", "occupied": false,\n'
        '      "last_analyzed": "2026-06-14T13:02:11Z" }\n'
        "  ]\n"
        "}"
    ))
    story.append(p(
        "<font face='Courier'>occupied</font> is <font face='Courier'>true</font> / "
        "<font face='Courier'>false</font>, or <font face='Courier'>null</font> with a "
        "<font face='Courier'>note</font> field when the berth has not been analyzed yet. A pedestal "
        "with no berth definitions returns <font face='Courier'>\"berths\": []</font> plus a "
        "<font face='Courier'>message</font>. Requires the <font face='Courier'>berths.occupancy_ext</font> "
        "endpoint to be enabled (returns <font face='Courier'>503</font> if not)."
    ))
    story.append(p("<b>Push:</b> real-time occupancy change.", "BodyText2"))
    story.append(code(
        "{\n"
        '  "event": "berth_occupancy_updated",\n'
        '  "data": {\n'
        '    "pedestal_id": 1,\n'
        '    "berths": [ { "berth_id": 7, "occupied": true } ]\n'
        "  },\n"
        '  "timestamp": "2026-06-14T13:02:12Z"\n'
        "}"
    ))
    story.append(note(
        "The webhook delivers a deliberately slim occupancy shape "
        "(<font face='Courier'>berth_id</font> + <font face='Courier'>occupied</font> only). "
        "Internal analysis details &mdash; zone rectangles, camera URL, match scores, re-ID "
        "embeddings &mdash; are never sent to the ERP."
    ))

    # ── MVP 3 — Camera ───────────────────────────────────────────────────────
    story.append(p("Use Case 3 &mdash; Live Camera per Berth via the NUC", "H2"))
    story.append(p(
        "Each pedestal has one camera that covers its berths, so a &ldquo;defined berth&rdquo; is "
        "viewed through its parent pedestal's camera. MarinaMaster has two options, both served by "
        "the NUC at that marina:"
    ))
    story.append(p(
        "<b>Option A &mdash; Stream URL:</b> the NUC returns the RTSP URL and current reachability; "
        "MarinaMaster connects to the stream directly.", "BodyText2"
    ))
    story.append(code(
        "GET /api/ext/pedestals/{pedestal_id}/camera/stream\n"
        "Authorization: Bearer {api_key}\n"
        "\n"
        "200 OK\n"
        "{\n"
        '  "pedestal_id": "MAR_KRK_ORM_01",\n'
        '  "stream_url": "rtsp://.../profile1",\n'
        '  "reachable": true,\n'
        '  "last_checked": "2026-06-14T13:04:00Z"\n'
        "}"
    ))
    story.append(p(
        "<b>Option B &mdash; Single frame through the NUC:</b> the NUC grabs one live JPEG from the "
        "camera and returns the image bytes, so MarinaMaster never needs RTSP access or direct "
        "network reach to the camera.", "BodyText2"
    ))
    story.append(code(
        "GET /api/ext/pedestals/{pedestal_id}/camera/frame\n"
        "Authorization: Bearer {api_key}\n"
        "\n"
        "200 OK   Content-Type: image/jpeg   (raw JPEG bytes)"
    ))
    story.append(p(
        "Option A requires the <font face='Courier'>camera.stream_ext</font> endpoint; Option B "
        "requires <font face='Courier'>camera.frame_ext</font>. Either returns "
        "<font face='Courier'>503</font> with <font face='Courier'>{error, reason}</font> if the "
        "camera is not configured, not reachable, or the endpoint is disabled. For a pilot behind a "
        "Cloudflare tunnel, Option B is recommended &mdash; it travels over the same HTTPS channel "
        "as the rest of the API and needs no separate RTSP path."
    ))

    # ── Enablement summary ──────────────────────────────────────────────────
    story.append(p("Pilot Enablement Checklist", "H2"))
    story.append(p(
        "To run the pilot, Lika Digital enables the following on the gateway for MarinaMaster's "
        "API key (all read-only / monitor):"
    ))
    story.append(make_table(
        ["Use Case", "Type", "Catalog item to enable"],
        [
            ["1. Temperature", "Event (push)", "<font face='Courier'>temperature_reading</font>"],
            ["2. Berth status", "Endpoint (pull)", "<font face='Courier'>berths.occupancy_ext</font>"],
            ["2. Berth status", "Event (push)", "<font face='Courier'>berth_occupancy_updated</font>"],
            ["3. Camera (URL)", "Endpoint (pull)", "<font face='Courier'>camera.stream_ext</font>"],
            ["3. Camera (frame)", "Endpoint (pull)", "<font face='Courier'>camera.frame_ext</font>"],
        ],
        col_widths=[doc.width*0.28, doc.width*0.22, doc.width*0.50],
    ))
    story.append(note(
        "<b>What success unlocks:</b> the pilot proves the full mechanism &mdash; key auth, "
        "per-endpoint toggles, pull endpoints, webhook push, and media through the NUC. Once it is "
        "green, any of the remaining "
        f"{len(ENDPOINT_CATALOG)} endpoints and {len(EVENT_CATALOG)} events in Sections 4 and 5 "
        "(sessions, billing, power/water telemetry, breaker and load monitoring, diagnostics, "
        "contracts) can be exported by simply adding them to MarinaMaster's allowed lists &mdash; "
        "no new integration code on either side."
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # NFC ACTIVATION API (myMarina ERP)
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("NFC Activation API (myMarina ERP)", "H1"))
    story.append(p(
        "This is a dedicated machine-to-machine API for the myMarina end-user app, <b>separate</b> "
        "from the gateway in sections 1&ndash;13. It lets myMarina pre-register an NFC tap; the "
        "socket then activates only when the boater physically plugs in their charger. The marina "
        "operator always retains highest-priority control over every session."
    ))

    story.append(p("Prerequisite &mdash; Smart Mode must be ON", "H2"))
    story.append(p(
        "Smart Mode (Opta firmware v3.0.0) is the master switch that decides who controls a cabinet. "
        "It defaults <b>OFF</b> on every firmware boot, and while OFF the Opta runs <b>standalone</b> "
        "and ignores NUC commands &mdash; so sessions, NFC activation, auto-activate, load monitoring "
        "and billing do nothing. The whole NUC/ERP integration (including this NFC API and the gateway "
        "in sections 1&ndash;13) is only effective when Smart Mode is <b>ON</b> for that pedestal."
    ))
    story.append(make_table(
        ["Field / endpoint", "Meaning"],
        [
            ["<font face='Courier'>smart_mode</font> (bool)", "Reported per pedestal in the health response and on every "
             "<font face='Courier'>opta_status</font> webhook/WS event. False = standalone (NUC control inert)."],
            ["<font face='Courier'>POST /api/pedestals/{cabinet_id}/smartmode</font>", "Operator/admin sets it "
             "(<font face='Courier'>{\"value\": true|false}</font>). Publishes <font face='Courier'>opta/cmd/smartmode</font> to the cabinet."],
        ],
        col_widths=[doc.width*0.42, doc.width*0.58],
    ))
    story.append(note(
        "ERP guidance: before driving a pedestal, confirm <font face='Courier'>smart_mode == true</font> "
        "(from the health response or the latest opta_status). If it is false, the pedestal is operator-managed "
        "standalone hardware &mdash; surface that to the user rather than expecting activation to take effect. "
        "Smart Mode is enabled by the marina operator, not by the ERP."
    ))

    story.append(p("Usage history &amp; monthly reports (v3.31)", "H2"))
    story.append(p(
        "Each completed session is retained as usage history per socket/valve and is exposed read-only to the "
        "ERP. The marina operator opts each endpoint in from the API Gateway page (they appear under the "
        "<b>Usage History</b> category). Values come straight from the session record; when a session was not "
        "attributed to a customer (e.g. Smart Mode was off), the customer / NFC fields are simply empty."
    ))
    story.append(make_table(
        ["Endpoint", "Returns"],
        [
            ["<font face='Courier'>GET /api/ext/pedestals/{id}/usage/history</font>",
             "Completed-session rows (socket/valve, start &amp; end, kWh, litres, customer_id, customer_name, "
             "nfc_user_id). Optional query: <font face='Courier'>resource</font>, <font face='Courier'>socket_id</font>, "
             "<font face='Courier'>month=YYYY-MM</font>."],
            ["<font face='Courier'>GET /api/ext/pedestals/{id}/usage/reports</font>",
             "List of available monthly report files (month, filename, size, generated_at)."],
            ["<font face='Courier'>GET /api/ext/pedestals/{id}/usage/reports/{YYYY-MM}</font>",
             "The plain-text monthly report for the pedestal (all sockets/valves, with totals). Generated on "
             "demand if it does not exist yet."],
        ],
        col_widths=[doc.width*0.52, doc.width*0.48],
    ))
    story.append(note(
        "Reports are protected: they are created automatically each month, kept on disk, and can be deleted "
        "ONLY by an operator-admin on the dashboard &mdash; never by the system and never via this API "
        "(the gateway permits GET only for these endpoints)."
    ))

    story.append(p("Authentication", "H2"))
    story.append(p(
        "Every <font face='Courier'>/api/nfc/</font> request authenticates with a static API key in "
        "the <font face='Courier'>X-API-Key</font> header (configured server-side as "
        "<font face='Courier'>ERP_API_KEY</font>). This is independent of the gateway JWT and its "
        "endpoint/event toggles. Missing or invalid key &rarr; <font face='Courier'>401</font>; the "
        "feature being unconfigured on the server &rarr; <font face='Courier'>503</font>."
    ))
    story.append(code(
        "POST https://marina.lika.solutions/api/nfc/scan\n"
        "X-API-Key: {ERP_API_KEY}\n"
        "Content-Type: application/json"
    ))

    story.append(p("Provisioning (operator side)", "H2"))
    story.append(p(
        "NFC tags are mapped to sockets by the marina operator in the dashboard "
        "(Control Center &rarr; Socket Settings &rarr; NFC) &mdash; one tag per socket; a tag already "
        "assigned elsewhere is rejected. The ERP does not provision tags; it only sends scans for "
        "tags that are already mapped."
    ))

    story.append(p("Endpoints", "H2"))
    story.append(make_table(
        ["Method &amp; path", "Purpose"],
        [
            ["<font face='Courier'>POST /api/nfc/scan</font>", "Pre-register an NFC tap. Does NOT activate the socket."],
            ["<font face='Courier'>GET /api/nfc/session/{id}</font>", "Live session status + spending data."],
            ["<font face='Courier'>POST /api/nfc/session/{id}/stop</font>", "Remote stop (operator override still applies)."],
        ],
        col_widths=[doc.width*0.45, doc.width*0.55],
    ))

    story.append(p("Activation flow", "H2"))
    story.append(code(
        "1. Boater taps the socket's NFC tag in myMarina\n"
        "     ERP -> POST /api/nfc/scan {nfc_tag_id, user_id}\n"
        "     <- 200 {status:\"pending\", expires_at = now + 5 min}\n"
        "\n"
        "2. Boater plugs in WITHIN 5 minutes\n"
        "     Pedestal reports the plug-in over MQTT -> socket activates,\n"
        "     the myMarina user is attached to the session.\n"
        "     (no tap, or tap expired -> socket stays idle; nothing happens)\n"
        "\n"
        "3. ERP polls GET /api/nfc/session/{id} for live kWh / cost\n"
        "\n"
        "4. Stop: operator (dashboard) OR ERP POST /api/nfc/session/{id}/stop"
    ))
    story.append(note(
        "The socket is NOT switched on by the scan. Activation happens exclusively when the Opta "
        "pedestal detects a physical plug-in. A scan with no plug-in inside 5 minutes simply expires."
    ))

    story.append(p("Payloads", "H2"))
    story.append(p("<b>POST /api/nfc/scan</b> &mdash; request &amp; response:", "BodyText2"))
    story.append(code(
        "// request\n"
        "{ \"nfc_tag_id\": \"04:A2:3B:1C\", \"user_id\": \"erp-12345\" }\n"
        "\n"
        "// 200\n"
        "{\n"
        '  "status": "pending",\n'
        '  "message": "Please plug in your charger to activate the socket",\n'
        '  "cabinet_id": "MAR_KRK_ORM_01",\n'
        '  "socket_id": "Q1",\n'
        '  "berth_id": "VEZ_A1",\n'
        '  "expires_at": "2026-06-16T12:05:00Z"\n'
        "}"
    ))
    story.append(p("<b>GET /api/nfc/session/{id}</b> &mdash; response (same shape the webhook sends):", "BodyText2"))
    story.append(code(
        "{\n"
        '  "session_id": 123,\n'
        '  "cabinet_id": "MAR_KRK_ORM_01",\n'
        '  "socket_id": "Q1",\n'
        '  "customer_id": "erp-12345",        // the myMarina user\n'
        '  "status": "active",                 // "active" | "ended"\n'
        '  "activated_at": "2026-06-16T12:01:30Z",\n'
        '  "duration_minutes": 42.5,\n'
        '  "energy_kwh": 2.45,\n'
        '  "power_kw_current": 1.10,\n'
        '  "estimated_cost": 0.74              // null if no tariff configured\n'
        "}"
    ))
    story.append(note(
        "Scan status codes: <font face='Courier'>404</font> NFC tag not provisioned &middot; "
        "<font face='Courier'>409</font> Socket already in use &middot; "
        "<font face='Courier'>503</font> Socket unavailable (fault) &middot; "
        "<font face='Courier'>401</font> missing/invalid key. Remote stop returns "
        "<font face='Courier'>409 &ldquo;Session already ended by operator&rdquo;</font> if the "
        "operator already stopped it &mdash; a stopped session is never restarted."
    ))

    story.append(p("Webhook (optional)", "H2"))
    story.append(p(
        "If <font face='Courier'>ERP_WEBHOOK_URL</font> is configured, the backend POSTs session "
        "updates to it (with the <font face='Courier'>X-API-Key</font> header) on three events: "
        "socket activated, a throttled telemetry update roughly every 60 s while active, and session "
        "ended &mdash; regardless of whether the stop came from the operator, the ERP, an unplug, or "
        "an automatic overload stop. The payload is the <font face='Courier'>GET /api/nfc/session</font> "
        "structure plus an <font face='Courier'>event</font> field. Delivery is fire-and-forget; "
        "failures are logged and never affect the session, MQTT flow, or operator control."
    ))
    story.append(note(
        "<b>Operator override is absolute.</b> An NFC-started session is an ordinary session. The "
        "marina operator can stop it from the dashboard at any time; the ERP stop is best-effort and "
        "yields 409 if the operator already ended it."
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 1. ARCHITECTURE OVERVIEW
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("1. Architecture Overview", "H1"))
    story.append(p(
        "The Cloud_IOT Pedestal SW is a full-stack IoT management platform deployed on an "
        "Intel NUC at each marina location. It manages physical pedestals (Arduino Opta controllers) "
        "that provide electricity (4 sockets) and water metering to boats. The system communicates "
        "locally via MQTT and exposes a REST API + WebSocket interface for real-time monitoring."
    ))
    story.append(Spacer(1, 6))
    story.append(p("<b>Integration Architecture:</b>", "H3"))
    story.append(code(
        "ERP System (cloud)                     Pedestal SW (NUC, per marina)\n"
        "  |                                        |\n"
        "  |-- HTTPS REST (/api/ext/...) ---------->| FastAPI backend\n"
        "  |   Authorization: Bearer {JWT}          |   |\n"
        "  |                                        |   +-- MQTT --> Arduino Opta\n"
        "  |<-- Webhook POST (events) ------------- |   +-- SQLite (sessions, sensors)\n"
        "  |   X-API-Key: {JWT}                     |   +-- WebSocket (real-time)\n"
        "  |   X-Webhook-Signature: sha256=...      |\n"
        "  |                                        |\n"
        "  +-- PostgreSQL (marinas, audit, cache)   +-- nginx (reverse proxy)\n"
    ))
    story.append(p(
        "The external API gateway (<font face='Courier' size=9>/api/ext/{path}</font>) acts as a "
        "self-proxy: it validates the external JWT, generates a short-lived internal admin JWT, "
        "and forwards the request to the internal API. This ensures the external system never "
        "needs direct access to admin credentials."
    ))
    story.append(Spacer(1, 6))
    story.append(p("<b>Key Design Principles:</b>"))
    story.append(bullet_list([
        "<b>Single source of truth:</b> Pedestal SW owns all device data, sessions, and billing. "
        "The ERP system caches and aggregates but does not generate authoritative data.",
        "<b>Resilient integration:</b> ERP should implement retry + stale-cache fallback. "
        "Webhooks provide real-time push; polling provides on-demand pull.",
        "<b>Per-marina isolation:</b> Each NUC is independent. ERP manages multiple marinas "
        "by maintaining separate API clients with per-marina credentials.",
        "<b>Audit trail:</b> Both sides should log all control actions (allow, deny, stop) "
        "with user identity and timestamps for compliance.",
    ]))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 2. AUTHENTICATION
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("2. Authentication", "H1"))

    story.append(p("2.1 External API Key (Static JWT)", "H2"))
    story.append(p(
        "The primary authentication method for ERP integration. A long-lived JWT token is "
        "generated by the Pedestal SW admin and provided to the ERP system."
    ))
    story.append(make_table(
        ["Property", "Value"],
        [
            ["Algorithm", "HS256"],
            ["Lifetime", "10 years (3,650 days)"],
            ["JWT Claims", '<font face="Courier" size=8>{ "sub": "external_api", "role": "external_api", "exp": ..., "iat": ... }</font>'],
            ["Generation", '<font face="Courier" size=8>POST /api/admin/ext-api/config/rotate-key</font>'],
            ["Usage", '<font face="Courier" size=8>Authorization: Bearer {api_key}</font>'],
        ],
        col_widths=[W*0.25, W*0.75]
    ))
    story.append(Spacer(1, 8))

    story.append(p("2.2 Service Account JWT (Short-Lived)", "H2"))
    story.append(p(
        "An alternative method using service account credentials. The ERP authenticates with "
        "email/password and receives a short-lived JWT. This is the method used by the "
        "ERP-IOT reference implementation."
    ))
    story.append(code(
        "POST /api/auth/service-token\n"
        "Content-Type: application/json\n"
        "\n"
        '{ "email": "service@marina.com", "password": "..." }\n'
        "\n"
        "Response:\n"
        '{ "access_token": "eyJ...", "token_type": "bearer" }'
    ))
    story.append(make_table(
        ["Property", "Value"],
        [
            ["Lifetime", "8 hours"],
            ["JWT Claims", '<font face="Courier" size=8>{ "sub": user_id, "email": "...", "role": "api_client", "exp": ... }</font>'],
            ["Refresh strategy", "Cache for 7 hours, refresh 1 hour before expiry"],
        ],
        col_widths=[W*0.25, W*0.75]
    ))
    story.append(Spacer(1, 8))

    story.append(p("2.3 Accepted Gateway Roles", "H2"))
    story.append(p(
        "The external API gateway accepts tokens with either role:"
    ))
    story.append(make_table(
        ["Role", "Token Type", "Use Case"],
        [
            ["external_api", "Static 10-year JWT", "Simple integration, single ERP"],
            ["api_client", "Short-lived service JWT", "Multi-system integration, credential rotation"],
        ],
        col_widths=[W*0.2, W*0.35, W*0.45]
    ))
    story.append(note(
        "Both roles provide the same endpoint access. The difference is lifecycle management. "
        "For pilot deployments, the static API key is simplest. For production with multiple "
        "integrating systems, service accounts provide better credential hygiene."
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 3. EXTERNAL API GATEWAY SETUP
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("3. External API Gateway Setup", "H1"))
    story.append(p(
        "Before an ERP system can call Pedestal SW endpoints, an admin must configure and "
        "activate the API gateway. This is done through the admin UI (<font face='Courier' size=9>/api-gateway</font> page) "
        "or directly via the admin API."
    ))

    story.append(p("3.1 Configuration Workflow", "H2"))
    story.append(p("<b>Step 1 &mdash; Set allowed endpoints and events:</b>"))
    story.append(code(
        "PUT /api/admin/ext-api/config\n"
        "Authorization: Bearer {admin_jwt}\n"
        "Content-Type: application/json\n"
        "\n"
        "{\n"
        '  "allowed_endpoints": [\n'
        '    { "id": "pedestals.list",    "mode": "monitor" },\n'
        '    { "id": "sessions.active",   "mode": "monitor" },\n'
        '    { "id": "sessions.pending",  "mode": "monitor" },\n'
        '    { "id": "controls.allow",    "mode": "bidirectional" },\n'
        '    { "id": "controls.deny",     "mode": "bidirectional" },\n'
        '    { "id": "controls.stop",     "mode": "bidirectional" },\n'
        '    { "id": "analytics.daily",   "mode": "monitor" },\n'
        '    { "id": "analytics.summary", "mode": "monitor" },\n'
        '    { "id": "alarms.active",     "mode": "monitor" }\n'
        "  ],\n"
        '  "webhook_url": "https://erp.example.com/api/webhooks/pedestal/1",\n'
        '  "allowed_events": [\n'
        '    "session_created", "session_updated", "session_completed",\n'
        '    "power_reading", "water_reading", "temperature_reading"\n'
        "  ]\n"
        "}"
    ))
    story.append(p("<b>Step 2 &mdash; Generate API key:</b>"))
    story.append(code(
        "POST /api/admin/ext-api/config/rotate-key\n"
        "Authorization: Bearer {admin_jwt}\n"
        "\n"
        'Response: { "api_key": "eyJhbGciOiJIUzI1NiIs..." }'
    ))
    story.append(p("<b>Step 3 &mdash; Verify configuration:</b>"))
    story.append(code(
        "POST /api/admin/ext-api/config/verify\n"
        "Authorization: Bearer {admin_jwt}\n"
        "\n"
        "Response: { verified: true, results: { ... per-endpoint test results } }"
    ))
    story.append(p("<b>Step 4 &mdash; Activate gateway:</b>"))
    story.append(code(
        "POST /api/admin/ext-api/config/activate\n"
        "Authorization: Bearer {admin_jwt}\n"
        "\n"
        "(Requires verified=true from Step 3)"
    ))
    story.append(note(
        "Any change to <font face='Courier'>allowed_endpoints</font> or "
        "<font face='Courier'>allowed_events</font> resets <font face='Courier'>verified=false</font>, "
        "requiring re-verification before re-activation. This prevents misconfigured gateways."
    ))

    story.append(p("3.2 Endpoint Access Modes", "H2"))
    story.append(make_table(
        ["Mode", "Allowed Methods", "Description"],
        [
            ["monitor", "GET only", "Read-only access. ERP can query data but cannot trigger actions."],
            ["bidirectional", "GET, POST, PUT, DELETE, PATCH", "Full access. ERP can read data and trigger control actions."],
        ],
        col_widths=[W*0.18, W*0.22, W*0.60]
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 4. ENDPOINT CATALOG
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("4. Endpoint Catalog", "H1"))
    story.append(p(
        f"The following {len(ENDPOINT_CATALOG)} endpoints are exposed through the external API "
        "gateway, grouped by category exactly as they appear on the admin API Gateway page. "
        "Requests are sent to <font face='Courier' size=9>https://&lt;base&gt;/api/ext/{path}</font> "
        "with the external JWT in the <font face='Courier' size=9>Authorization: Bearer</font> header."
    ))
    story.append(note(
        "For catalog paths that do not already begin with <font face='Courier'>/api/ext</font>, add "
        "that prefix when calling: e.g. <font face='Courier'>pedestals.list</font> "
        "(<font face='Courier'>/api/pedestals</font>) is called as "
        "<font face='Courier'>/api/ext/pedestals</font>. Paths already containing "
        "<font face='Courier'>/api/ext</font> are direct (non-proxied) routes. "
        "&ldquo;Bi-dir = Yes&rdquo; means the endpoint accepts write/control methods only when the "
        "admin enables it in <font face='Courier'>bidirectional</font> mode; in "
        "<font face='Courier'>monitor</font> mode every endpoint is read-only and a write returns "
        "<font face='Courier'>403</font>."
    ))

    # Group endpoints by category, preserving first-seen order from the catalog.
    _cat_order, _by_cat = [], {}
    for _e in ENDPOINT_CATALOG:
        _c = _e["category"]
        if _c not in _by_cat:
            _by_cat[_c] = []
            _cat_order.append(_c)
        _by_cat[_c].append(_e)

    _sec = 0
    for _c in _cat_order:
        _sec += 1
        story.append(p(f"4.{_sec} {_c} ({len(_by_cat[_c])})".replace("&", "&amp;"), "H2"))
        _rows = [[
            _e["id"],
            _e["method"],
            f"<font face='Courier' size=8>{_epath(_e['path'])}</font>",
            "Yes" if _e["allow_bidirectional"] else "No",
        ] for _e in _by_cat[_c]]
        story.append(make_table(
            ["Endpoint ID", "Method", "Path", "Bi-dir"],
            _rows, col_widths=[W * 0.26, W * 0.10, W * 0.50, W * 0.14]))
        story.append(Spacer(1, 6))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 5. WEBHOOK EVENT CATALOG
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("5. Webhook Event Catalog", "H1"))
    story.append(p(
        f"When a webhook URL is configured and events are activated, Pedestal SW POSTs these "
        f"{len(EVENT_CATALOG)} event types to the ERP in real time. Events fire on every WebSocket "
        "broadcast (the same data the admin dashboard receives). The operator opts each event in on "
        "the API Gateway page; only enabled events are delivered."
    ))

    story.append(p("5.1 All Events", "H2"))
    _evrows = [[
        f"<font face='Courier' size=8>{ev['id']}</font>",
        ev["name"],
        ev["category"].replace("&", "&amp;"),
        EVENT_ERP_USE.get(ev["category"], "&mdash;"),
    ] for ev in EVENT_CATALOG]
    story.append(make_table(
        ["Event ID", "Name", "Category", "ERP use"],
        _evrows, col_widths=[W * 0.30, W * 0.26, W * 0.21, W * 0.23]))

    story.append(p("5.2 Webhook Delivery", "H2"))
    story.append(make_table(
        ["Property", "Value"],
        [
            ["Method", "POST"],
            ["Content-Type", "application/json"],
            ["Timeout", "5 seconds (fire-and-forget)"],
            ["Retry", "None (single attempt per event)"],
            ["Authentication", '<font face="Courier" size=8>X-API-Key: {api_key_jwt}</font>'],
            ["Cache", "Config cached 30 seconds (invalidated on config change)"],
        ],
        col_widths=[W*0.25, W*0.75]
    ))
    story.append(note(
        "Webhook delivery is fire-and-forget with a 5-second timeout. The ERP system must respond "
        "quickly (HTTP 2xx) or the event is dropped. For reliability, implement a combination of "
        "webhooks (push) and API polling (pull) as the reference implementation does."
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 6. CORE INTEGRATION FLOWS
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("6. Core Integration Flows", "H1"))

    story.append(p("6.1 Dashboard / Monitoring (Pull)", "H2"))
    story.append(p(
        "The ERP system periodically polls Pedestal SW endpoints to build a dashboard view. "
        "This is supplemented by webhook events for real-time updates."
    ))
    story.append(code(
        "# 1. List pedestals and their state\n"
        "GET /api/ext/pedestals\n"
        "Authorization: Bearer {api_key}\n"
        "\n"
        "# 2. Get health overview\n"
        "GET /api/ext/pedestals/health\n"
        "\n"
        "# 3. Get active sessions (with consumption data)\n"
        "GET /api/ext/sessions/active\n"
        "\n"
        "# 4. Get pending sessions (awaiting approval)\n"
        "GET /api/ext/sessions/pending\n"
        "\n"
        "# 5. Get active alarms\n"
        "GET /api/ext/alarms/active"
    ))
    story.append(p(
        "The ERP-IOT reference implementation fetches all 4 data points in parallel "
        "(async) and merges them into a single dashboard response. On failure, it falls "
        "back to cached data and marks the response as stale."
    ))

    story.append(p("6.2 Session Control (Push)", "H2"))
    story.append(p(
        "When an operator in the ERP system needs to approve, deny, or stop a session:"
    ))
    story.append(code(
        "# Approve a pending session\n"
        "POST /api/ext/controls/{session_id}/allow\n"
        "Authorization: Bearer {api_key}\n"
        "\n"
        "# Deny a session (with optional reason)\n"
        "POST /api/ext/controls/{session_id}/deny\n"
        'Body: { "reason": "Berth not assigned" }\n'
        "\n"
        "# Stop an active session\n"
        "POST /api/ext/controls/{session_id}/stop\n"
        "Authorization: Bearer {api_key}"
    ))
    story.append(note(
        "These endpoints require <font face='Courier'>mode: bidirectional</font> in the gateway configuration."
    ))

    story.append(p("6.3 Real-Time Events (Webhook Push)", "H2"))
    story.append(p(
        "Configure the ERP webhook endpoint to receive real-time events. The ERP should:"
    ))
    story.append(bullet_list([
        "Validate the <font face='Courier'>X-API-Key</font> header matches the expected API key",
        "Optionally validate HMAC signature via <font face='Courier'>X-Webhook-Signature</font> "
        "(if webhook_secret is configured on both sides)",
        "Persist events to a local database (session_log, alarm_log, etc.)",
        "Update cached dashboard data based on event type",
        "Broadcast to connected UI clients via WebSocket",
        "Return HTTP 200 within 5 seconds",
    ]))

    story.append(p("6.4 Energy Analytics", "H2"))
    story.append(code(
        "# Daily consumption (with date range)\n"
        "GET /api/ext/analytics/consumption/daily?start=2026-04-01&end=2026-04-16\n"
        "\n"
        "# Session summary (totals and averages)\n"
        "GET /api/ext/analytics/sessions/summary"
    ))

    story.append(p("6.5 Berth Occupancy &amp; Camera (Marina View)", "H2"))
    story.append(p(
        "These are the marina-facing pull endpoints used in the MVP Pilot (see the MVP Pilot "
        "section). Berth occupancy is also delivered in real time via the "
        "<font face='Courier'>berth_occupancy_updated</font> webhook event."
    ))
    story.append(code(
        "# Occupancy for all berths under a pedestal (numeric id or Opta client id)\n"
        "GET /api/ext/pedestals/{pedestal_id}/berths/occupancy\n"
        "\n"
        "# Live camera stream URL for the pedestal that covers the berth\n"
        "GET /api/ext/pedestals/{pedestal_id}/camera/stream\n"
        "\n"
        "# Single live JPEG frame, captured by the NUC (no RTSP needed by the ERP)\n"
        "GET /api/ext/pedestals/{pedestal_id}/camera/frame"
    ))
    story.append(note(
        "Each capability has its own gateway toggle "
        "(<font face='Courier'>berths.occupancy_ext</font>, "
        "<font face='Courier'>camera.stream_ext</font>, "
        "<font face='Courier'>camera.frame_ext</font>) and returns "
        "<font face='Courier'>503 {error, reason}</font> when disabled or the feature is unavailable."
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 7. SESSION LIFECYCLE & BILLING
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("7. Session Lifecycle & Billing", "H1"))

    story.append(p("7.1 Session State Machine", "H2"))
    story.append(code(
        "  Customer requests power/water\n"
        "           |\n"
        "           v\n"
        "      [ PENDING ]  ---deny--->  [ DENIED ]\n"
        "           |\n"
        "         allow\n"
        "           |\n"
        "           v\n"
        "      [ ACTIVE ]  ---stop/complete--->  [ COMPLETED ]\n"
        "           |                                  |\n"
        "           +-- energy_kwh accumulating         +-- final readings frozen\n"
        "           +-- water_liters accumulating       +-- invoice generated\n"
    ))

    story.append(p("7.2 Billing Data Flow", "H2"))
    story.append(p(
        "Billing is calculated by the Pedestal SW based on configured rates. "
        "The ERP should consume this data, not recalculate it."
    ))
    story.append(make_table(
        ["Data Point", "Source", "ERP Action"],
        [
            ["Billing rates", "GET /api/billing/config (admin)", "Display, optionally mirror to ERP billing module"],
            ["Session consumption", "session_completed webhook event", "Record energy_kwh, water_liters, calculate costs"],
            ["Invoice", "Generated on session completion", "Sync via /api/customer/invoices or webhook"],
            ["Spending summary", "GET /api/billing/spending", "Aggregate for reporting"],
            ["Per-session detail", "GET /api/billing/spending/detail", "Detailed breakdown for accounting"],
        ],
        col_widths=[W*0.20, W*0.40, W*0.40]
    ))

    story.append(p("7.3 Billing Configuration", "H2"))
    story.append(code(
        "# Current rates\n"
        "GET /api/ext/billing/config\n"
        "\n"
        "Response:\n"
        "{\n"
        '  "kwh_price_eur": 0.30,\n'
        '  "liter_price_eur": 0.015\n'
        "}"
    ))
    story.append(note(
        "Default rates are seeded on first startup (0.30 EUR/kWh, 0.015 EUR/liter). "
        "Rates can be changed by admin via the UI or API. The ERP should periodically "
        "sync these rates rather than hardcoding them."
    ))

    story.append(p("7.4 Invoice Model", "H2"))
    story.append(make_table(
        ["Field", "Type", "Description"],
        [
            ["id", "int", "Invoice primary key"],
            ["session_id", "int", "Associated session"],
            ["customer_id", "int", "Customer who consumed"],
            ["energy_kwh", "float", "Total electricity consumed"],
            ["water_liters", "float", "Total water consumed"],
            ["energy_cost_eur", "float", "Electricity cost (energy_kwh x rate)"],
            ["water_cost_eur", "float", "Water cost (water_liters x rate)"],
            ["total_eur", "float", "energy_cost + water_cost"],
            ["paid", "0/1", "Payment status (0=unpaid, 1=paid)"],
            ["created_at", "datetime", "Invoice creation timestamp"],
        ],
        col_widths=[W*0.20, W*0.12, W*0.68]
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 8. CONTRACTS & INVOICES
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("8. Contracts & Invoices", "H1"))

    story.append(p("8.1 Contract Templates", "H2"))
    story.append(p(
        "Admins create contract templates that customers must sign before using marina services. "
        "Templates define terms, conditions, and validity period."
    ))
    story.append(make_table(
        ["Endpoint", "Method", "Description"],
        [
            ["/api/contracts/templates", "GET", "List all active templates"],
            ["/api/contracts/templates", "POST", "Create new template (admin)"],
            ["/api/contracts/templates/{id}", "PATCH", "Update template (admin)"],
            ["/api/admin/contracts", "GET", "List all signed contracts (admin)"],
            ["/api/admin/contracts/{id}/pdf", "GET", "Download contract PDF (admin)"],
        ],
        col_widths=[W*0.38, W*0.1, W*0.52]
    ))

    story.append(p("8.2 Customer Contract Flow", "H2"))
    story.append(make_table(
        ["Endpoint", "Method", "Description"],
        [
            ["/api/customer/contracts/pending", "GET", "Templates not yet signed by customer"],
            ["/api/customer/contracts/{template_id}/sign", "POST", "Sign with base64 signature image"],
            ["/api/customer/contracts/mine", "GET", "Customer's signed contracts"],
            ["/api/customer/contracts/{id}/pdf", "GET", "Download signed contract PDF"],
        ],
        col_widths=[W*0.42, W*0.1, W*0.48]
    ))

    story.append(p("8.3 Invoice Endpoints", "H2"))
    story.append(make_table(
        ["Endpoint", "Method", "Description"],
        [
            ["/api/customer/invoices/mine", "GET", "Customer's invoice list"],
            ["/api/customer/invoices/{id}/pay", "POST", "Mark invoice as paid"],
            ["/api/customer/invoices/{id}/pdf", "GET", "Download invoice PDF"],
            ["/api/billing/spending", "GET", "Aggregate spending by customer (admin)"],
            ["/api/billing/spending/detail", "GET", "Per-session cost breakdown (admin)"],
        ],
        col_widths=[W*0.38, W*0.1, W*0.52]
    ))
    story.append(note(
        "For ERP integration, the admin billing endpoints (<font face='Courier'>/api/billing/*</font>) "
        "are most relevant. These provide aggregated spending data suitable for importing into "
        "ERP accounting modules. Invoice PDFs can be downloaded and archived in the ERP document store."
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 9. WEBHOOK PAYLOAD REFERENCE
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("9. Webhook Payload Reference", "H1"))
    story.append(p(
        "All webhook payloads follow the same envelope structure:"
    ))
    story.append(code(
        "{\n"
        '  "event": "event_id",\n'
        '  "data": { ... event-specific payload ... },\n'
        '  "timestamp": "2026-04-16T12:34:57Z"\n'
        "}"
    ))

    story.append(p("9.1 session_created", "H2"))
    story.append(code(
        "{\n"
        '  "event": "session_created",\n'
        '  "data": {\n'
        '    "session_id": 123,\n'
        '    "pedestal_id": 1,\n'
        '    "socket_id": 2,\n'
        '    "type": "electricity",\n'
        '    "status": "active",\n'
        '    "started_at": "2026-04-16T12:34:56Z",\n'
        '    "customer_id": 5,\n'
        '    "customer_name": "John Doe"\n'
        "  },\n"
        '  "timestamp": "2026-04-16T12:34:57Z"\n'
        "}"
    ))

    story.append(p("9.2 session_completed", "H2"))
    story.append(code(
        "{\n"
        '  "event": "session_completed",\n'
        '  "data": {\n'
        '    "session_id": 123,\n'
        '    "pedestal_id": 1,\n'
        '    "socket_id": 2,\n'
        '    "type": "electricity",\n'
        '    "status": "completed",\n'
        '    "energy_kwh": 2.45,\n'
        '    "water_liters": 0.0,\n'
        '    "customer_id": 5\n'
        "  },\n"
        '  "timestamp": "2026-04-16T14:22:10Z"\n'
        "}"
    ))

    story.append(p("9.3 power_reading", "H2"))
    story.append(code(
        "{\n"
        '  "event": "power_reading",\n'
        '  "data": {\n'
        '    "pedestal_id": 1,\n'
        '    "socket_id": 2,\n'
        '    "voltage": 230.5,\n'
        '    "current": 4.2,\n'
        '    "power_w": 968.1,\n'
        '    "energy_kwh": 1.23,\n'
        '    "timestamp": "2026-04-16T13:00:00Z"\n'
        "  },\n"
        '  "timestamp": "2026-04-16T13:00:01Z"\n'
        "}"
    ))

    story.append(p("9.4 temperature_reading / moisture_reading", "H2"))
    story.append(code(
        "{\n"
        '  "event": "temperature_reading",\n'
        '  "data": {\n'
        '    "pedestal_id": 1,\n'
        '    "value": 47.2,\n'
        '    "severity": "warning",\n'
        '    "alarm": true,\n'
        '    "temp_sensor_reachable": true,\n'
        '    "last_temp_sensor_check": "2026-06-14T13:05:00Z",\n'
        '    "timestamp": "2026-06-14T13:05:00Z"\n'
        "  },\n"
        '  "timestamp": "2026-06-14T13:05:01Z"\n'
        "}"
    ))
    story.append(p(
        "Temperature is read from the Papouch TME sensor by the NUC every 30 s and evaluated against "
        "two-sided range alarms with clearing hysteresis (1&deg;C):"
    ))
    story.append(make_table(
        ["Band", "Threshold", "severity"],
        [
            ["High critical", "&ge; 60 &deg;C", "<font face='Courier'>critical</font>"],
            ["High warning", "&ge; 45 &deg;C", "<font face='Courier'>warning</font>"],
            ["Normal", "0 &deg;C &ndash; 45 &deg;C", "<font face='Courier'>null</font>"],
            ["Low warning", "&le; 0 &deg;C", "<font face='Courier'>warning</font>"],
            ["Low critical", "&le; -10 &deg;C", "<font face='Courier'>critical</font>"],
        ],
        col_widths=[doc.width*0.30, doc.width*0.35, doc.width*0.35],
    ))
    story.append(note(
        "<font face='Courier'>severity</font> is <font face='Courier'>null</font> in the normal "
        "band; <font face='Courier'>alarm</font> is <font face='Courier'>true</font> whenever "
        "severity is non-null. <font face='Courier'>temperature_reading</font> is push-only (no pull "
        "endpoint). Moisture alarm triggers at &gt;90%. When "
        "<font face='Courier'>severity: \"critical\"</font>, the ERP should log this as a critical event."
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 10. ERROR HANDLING & RESILIENCE
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("10. Error Handling & Resilience", "H1"))

    story.append(p("10.1 Gateway Error Codes", "H2"))
    story.append(make_table(
        ["HTTP Code", "Meaning", "ERP Action"],
        [
            ["200", "Success", "Process response normally"],
            ["401", "Invalid/expired JWT", "Refresh token (service account) or alert admin (API key)"],
            ["403", "Endpoint not allowed or monitor-mode POST", "Check gateway config; do not retry"],
            ["404", "Unknown endpoint path", "Check endpoint catalog; do not retry"],
            ["502", "Pedestal internal error (upstream failure)", "Retry with backoff; fall back to cache"],
            ["503", "Gateway not activated", "Alert admin to activate gateway"],
        ],
        col_widths=[W*0.12, W*0.38, W*0.50]
    ))

    story.append(p("10.2 Recommended Retry Strategy", "H2"))
    story.append(p("Based on the ERP-IOT reference implementation:"))
    story.append(make_table(
        ["Parameter", "Value", "Rationale"],
        [
            ["Max retries", "3", "Balance between reliability and latency"],
            ["Backoff", "Exponential: 1s, 2s, 4s", "Avoid overwhelming a recovering service"],
            ["Retry on", "Connection errors, timeouts, 5xx", "Transient failures"],
            ["No retry on", "4xx (except 401)", "Client errors won't resolve on retry"],
            ["Request timeout", "10 seconds", "NUC is local network; fast responses expected"],
            ["Token refresh on 401", "Auto-refresh and retry once", "Token may have expired"],
        ],
        col_widths=[W*0.22, W*0.30, W*0.48]
    ))

    story.append(p("10.3 Stale Data Pattern", "H2"))
    story.append(p(
        "When the Pedestal SW is unreachable (NUC offline, network issue), the ERP should:"
    ))
    story.append(bullet_list([
        "Return the last successfully cached response",
        "Mark the response with an <font face='Courier'>is_stale: true</font> flag",
        "Display a visual indicator in the UI (e.g., yellow banner)",
        "Continue retrying in the background",
        "Log the failure to a sync_log table for diagnostics",
    ]))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 11. SECURITY CONSIDERATIONS
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("11. Security Considerations", "H1"))

    story.append(p("11.1 Transport Security", "H2"))
    story.append(bullet_list([
        "<b>HTTPS required</b> for production. The NUC uses nginx with optional TLS or Cloudflare tunnel.",
        "<b>Webhook URL</b> must be HTTPS in production to protect event payloads in transit.",
        "<b>API keys</b> should never be logged, displayed in UIs, or stored in plaintext config files.",
    ]))

    story.append(p("11.2 Credential Management", "H2"))
    story.append(bullet_list([
        "<b>API key rotation:</b> Use <font face='Courier'>POST /api/admin/ext-api/config/rotate-key</font> "
        "to generate a new key. The old key is immediately invalidated.",
        "<b>Service account passwords:</b> Encrypt at rest using Fernet (AES-128-CBC + HMAC-SHA256) "
        "as the reference implementation does.",
        "<b>JWT secret:</b> Must match between Pedestal SW and any system validating its tokens. "
        "Minimum 32 bytes of randomness.",
    ]))

    story.append(p("11.3 Webhook Validation", "H2"))
    story.append(p(
        "The ERP should validate incoming webhooks to prevent spoofed events:"
    ))
    story.append(code(
        "import hmac, hashlib\n"
        "\n"
        "def verify_webhook(payload_bytes, signature_header, secret):\n"
        '    expected = "sha256=" + hmac.new(\n'
        "        secret.encode(), payload_bytes, hashlib.sha256\n"
        "    ).hexdigest()\n"
        "    return hmac.compare_digest(expected, signature_header)"
    ))

    story.append(p("11.4 Access Control", "H2"))
    story.append(bullet_list([
        "<b>Principle of least privilege:</b> Only enable endpoints the ERP actually needs.",
        "<b>Use monitor mode</b> for read-only endpoints; only enable bidirectional for control actions.",
        "<b>Separate API keys</b> per integrating system if multiple systems connect.",
        "<b>Audit all control actions</b> with user identity and timestamps.",
    ]))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 12. NETWORK & CLOUDFLARE CONFIGURATION
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("12. Network & Cloudflare Configuration", "H1"))
    story.append(p(
        "The Pedestal SW runs on an Intel NUC at the marina with no static public IP address. "
        "Internet access is provided via a 5G/LTE router with dynamic IP. All external access "
        "to the NUC is routed through a <b>Cloudflare Tunnel</b>, managed by Lika Digital. "
        "This section explains the network architecture and what the ERP system provider must "
        "supply to Lika Digital to enable connectivity."
    ))

    story.append(p("12.1 Current Network Architecture", "H2"))
    story.append(code(
        "ERP System (cloud/on-prem)           Cloudflare Edge            Marina NUC\n"
        "  |                                      |                          |\n"
        "  |--- HTTPS request ------------------>|                          |\n"
        "  |    https://marina.lika.solutions    |                          |\n"
        "  |                                     |--- tunnel (outbound) --->|\n"
        "  |                                     |    cloudflared daemon    |\n"
        "  |                                     |                         |\n"
        "  |                                     |<-- response ----------- |\n"
        "  |<--- HTTPS response ----------------|                          |\n"
        "  |                                                                |\n"
        "  |                          Webhook (reverse direction)           |\n"
        "  |<--- HTTPS POST -------------------------------------------- |\n"
        "  |    https://erp.example.com/webhooks  (NUC pushes to ERP)     |\n"
    ))
    story.append(p(
        "The NUC maintains a persistent outbound connection to Cloudflare (via "
        "<font face='Courier'>cloudflared</font> daemon). No inbound ports are opened on the "
        "marina's firewall. Cloudflare terminates TLS and routes traffic through the tunnel "
        "to nginx on the NUC (port 80), which proxies to the FastAPI backend."
    ))

    story.append(p("12.2 Pedestal SW Access (ERP &rarr; NUC)", "H2"))
    story.append(p(
        "The ERP system accesses the Pedestal SW API through the Cloudflare tunnel hostname. "
        "This is already configured and operational:"
    ))
    story.append(make_table(
        ["Property", "Value"],
        [
            ["Base URL", '<font face="Courier" size=8>https://marina.lika.solutions</font>'],
            ["API Gateway", '<font face="Courier" size=8>https://marina.lika.solutions/api/ext/{path}</font>'],
            ["TLS", "Terminated by Cloudflare (automatic, managed certificate)"],
            ["Authentication", "Bearer JWT in Authorization header (see Section 2)"],
            ["Tunnel ID", '<font face="Courier" size=8>0c795485-c696-49a9-973c-55b2aab98c39</font>'],
        ],
        col_widths=[W*0.25, W*0.75]
    ))
    story.append(note(
        "The ERP system does not need to know the NUC's IP address. All API requests go to "
        "<font face='Courier'>https://marina.lika.solutions/api/ext/...</font> and Cloudflare "
        "handles routing through the tunnel. TLS is automatic."
    ))

    story.append(p("12.3 MarinaMaster ERP &mdash; Cloudflare Tunnel Setup", "H2"))
    story.append(p(
        "For the Pedestal SW to send webhook events to MarinaMaster, and for MarinaMaster to be "
        "reachable at a stable HTTPS URL, there are two options depending on whether MarinaMaster "
        "has a static public IP address."
    ))

    story.append(p("<b>Option A &mdash; MarinaMaster Has a Static Public IP</b>", "H3"))
    story.append(p(
        "If MarinaMaster has a static public IP address, <b>Lika Digital handles the entire "
        "setup</b>. MarinaMaster only needs to provide:"
    ))
    story.append(bullet_list([
        "Their server's public IP address",
        "The port their ERP application runs on (e.g., 8000, 3000)",
    ]))
    story.append(p(
        "Lika Digital will configure the Cloudflare tunnel and DNS record on their side. "
        "<b>No action required from MarinaMaster.</b>"
    ))
    story.append(Spacer(1, 6))

    story.append(p("<b>Option B &mdash; MarinaMaster Does NOT Have a Static Public IP</b>", "H3"))
    story.append(p(
        "If MarinaMaster does not have a static public IP, they need to install a small "
        "tunneling agent called <font face='Courier'>cloudflared</font> on their server. "
        "This is a free tool provided by Cloudflare and takes approximately 5 minutes to set up."
    ))
    story.append(Spacer(1, 4))

    story.append(p(
        "<b>Step 1 &mdash; Download and install cloudflared.</b><br/>"
        "Download the installer for your platform from:<br/>"
        "<font face='Courier' color='#2563eb'>https://github.com/cloudflare/cloudflared/releases/latest</font><br/>"
        "Available for Windows, Linux, and macOS."
    ))
    story.append(Spacer(1, 4))

    story.append(p(
        "<b>Step 2 &mdash; Log in to Cloudflare.</b><br/>"
        "Open a terminal on the server and run:"
    ))
    story.append(code("cloudflared tunnel login"))
    story.append(p(
        "A browser window will open asking you to log in to a Cloudflare account. "
        "If MarinaMaster does not have a Cloudflare account, create a free one at "
        "<font face='Courier'>cloudflare.com</font>."
    ))
    story.append(Spacer(1, 4))

    story.append(p(
        "<b>Step 3 &mdash; Create a tunnel.</b><br/>"
        "Run the following command:"
    ))
    story.append(code("cloudflared tunnel create marinamaster-tunnel"))
    story.append(p(
        "This will generate a tunnel ID that looks like "
        "<font face='Courier'>xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx</font>. "
        "<b>Copy this ID &mdash; you will send it to Lika Digital.</b>"
    ))
    story.append(Spacer(1, 4))

    story.append(p(
        "<b>Step 4 &mdash; Start the tunnel.</b><br/>"
        "Replace <font face='Courier'>PORT</font> with the port your ERP application runs on "
        "(e.g., 8000 or 3000):"
    ))
    story.append(code("cloudflared tunnel run --url http://localhost:PORT marinamaster-tunnel"))
    story.append(Spacer(1, 4))

    story.append(p(
        "<b>Step 5 &mdash; Send the tunnel ID to Lika Digital.</b><br/>"
        "Lika Digital will add a DNS record pointing "
        "<font face='Courier'>marinamaster.lika.solutions</font> to your tunnel. "
        "Once done, the ERP application will be accessible at "
        "<font face='Courier'>https://marinamaster.lika.solutions</font>."
    ))
    story.append(Spacer(1, 4))

    story.append(p(
        "<b>Step 6 &mdash; Make the tunnel start automatically on server restart.</b><br/>"
        "Run the following commands:"
    ))
    story.append(code(
        "cloudflared service install\n"
        "systemctl enable cloudflared\n"
        "systemctl start cloudflared"
    ))
    story.append(Spacer(1, 8))

    story.append(note(
        "<b>Note for Lika Digital (internal):</b> Once MarinaMaster provides the tunnel ID, "
        "add a CNAME DNS record in the Cloudflare dashboard for <font face='Courier'>lika.solutions</font> "
        "pointing <font face='Courier'>marinamaster</font> to "
        "<font face='Courier'>{tunnel_id}.cfargotunnel.com</font> with proxy enabled (orange cloud). "
        "No changes to the NUC configuration are needed for Option B."
    ))
    story.append(Spacer(1, 6))

    story.append(p("<b>Summary &mdash; Webhook URL After Setup</b>", "H3"))
    story.append(make_table(
        ["Option", "Webhook URL configured in Pedestal SW", "Who sets it up"],
        [
            ["A (static IP)", '<font face="Courier" size=8>https://marinamaster.lika.solutions/api/webhooks/...</font>', "Lika Digital"],
            ["B (cloudflared)", '<font face="Courier" size=8>https://marinamaster.lika.solutions/api/webhooks/...</font>', "MarinaMaster installs cloudflared, Lika adds DNS"],
        ],
        col_widths=[W*0.15, W*0.55, W*0.30]
    ))
    story.append(p(
        "In both cases, the final webhook URL uses the same "
        "<font face='Courier'>marinamaster.lika.solutions</font> domain, with HTTPS provided "
        "automatically by Cloudflare."
    ))

    story.append(p("12.4 Information ERP Provider Must Supply to Lika Digital", "H2"))
    story.append(p(
        "To enable integration, the ERP system management team must provide the following "
        "information to Lika Digital (the Cloudflare account owner):"
    ))
    story.append(make_table(
        ["Item", "Required?", "Description", "Example"],
        [
            ["Webhook URL", "YES",
             "Public HTTPS endpoint where the NUC should send real-time events. "
             "Must respond within 5 seconds.",
             '<font face="Courier" size=8>https://erp.example.com/api/webhooks/pedestal/1</font>'],
            ["Webhook auth token", "YES",
             "Shared secret or token that Lika will configure in the gateway. "
             "The NUC sends this as X-API-Key header on every webhook POST.",
             "Agreed during setup"],
            ["Service account email", "YES",
             "Email address to use for the ERP's service account on Pedestal SW. "
             "Lika Digital will create this account with role=api_client.",
             '<font face="Courier" size=8>erp-service@partner.com</font>'],
            ["Service account password", "YES",
             "Password for the service account. ERP must store this securely "
             "(encrypted at rest). Used to obtain short-lived JWT tokens.",
             "Agreed during setup"],
            ["Required endpoints", "YES",
             "List of endpoint IDs from the catalog (Section 4) that the ERP needs access to, "
             "with mode (monitor or bidirectional).",
             "sessions.active (monitor), controls.allow (bidirectional)"],
            ["Required events", "YES",
             "List of webhook event IDs from the catalog (Section 5) the ERP wants to receive.",
             "session_created, session_completed, power_reading"],
            ["IP whitelist", "OPTIONAL",
             "If the ERP has a static IP range, Lika can add a Cloudflare Access policy to "
             "restrict API access to those IPs only.",
             '<font face="Courier" size=8>203.0.113.0/24</font>'],
            ["mTLS certificate", "OPTIONAL",
             "For maximum security, the ERP can provide a client TLS certificate. "
             "Lika configures Cloudflare Access to require it on the tunnel.",
             "X.509 PEM certificate"],
        ],
        col_widths=[W*0.15, W*0.10, W*0.45, W*0.30]
    ))

    story.append(p("12.5 What Lika Digital Configures", "H2"))
    story.append(p(
        "Once the ERP provider supplies the above information, Lika Digital will:"
    ))
    story.append(bullet_list([
        "<b>Create a service account</b> on the Pedestal SW with role <font face='Courier'>api_client</font> "
        "using the agreed email and password.",
        "<b>Configure the API Gateway</b> with the requested endpoints, modes, webhook URL, and events.",
        "<b>Verify and activate</b> the gateway configuration.",
        "<b>Optionally add Cloudflare Access policy</b> to restrict tunnel access to the ERP's IP range or mTLS certificate.",
        "<b>Provide the API base URL</b> to the ERP team: <font face='Courier'>https://marina.lika.solutions</font>.",
        "<b>Test end-to-end</b> connectivity with the ERP team before go-live.",
    ]))

    story.append(p("12.6 DNS & TLS (Managed by Lika Digital)", "H2"))
    story.append(p(
        "All DNS and TLS configuration is handled by Lika Digital. The ERP team does "
        "<b>not</b> need to configure any DNS records or TLS certificates. For reference:"
    ))
    story.append(make_table(
        ["Component", "Configuration", "Managed By"],
        [
            ["Domain", '<font face="Courier" size=8>*.lika.solutions</font>', "Lika Digital (Cloudflare DNS)"],
            ["TLS Certificate", "Automatic via Cloudflare (edge certificate)", "Lika Digital"],
            ["Tunnel daemon", '<font face="Courier" size=8>cloudflared</font> on NUC (systemd service)', "Lika Digital"],
            ["Ingress rules", "Per-hostname routing in tunnel config", "Lika Digital"],
            ["Access policies", "Optional IP whitelist or mTLS enforcement", "Lika Digital"],
        ],
        col_widths=[W*0.18, W*0.50, W*0.32]
    ))

    story.append(p("12.7 Multiple Marina Sites", "H2"))
    story.append(p(
        "Each marina has its own NUC with its own Cloudflare tunnel and subdomain. "
        "If the ERP integrates with multiple marinas, it will use separate base URLs "
        "and separate service account credentials for each:"
    ))
    story.append(code(
        "# Marina 1\n"
        "Base URL:        https://marina-1.lika.solutions\n"
        "Service account: erp-service@partner.com / {password_1}\n"
        "\n"
        "# Marina 2\n"
        "Base URL:        https://marina-2.lika.solutions\n"
        "Service account: erp-service@partner.com / {password_2}\n"
        "\n"
        "# Each marina is independent — separate NUC, separate DB, separate credentials."
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 13. MULTI-CLIENT AUTH (SERVICE ACCOUNTS)
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("13. Multi-Client Authentication (Service Accounts)", "H1"))
    story.append(p(
        "When multiple external systems need to integrate with the same Pedestal SW instance "
        "(e.g., an ERP system and a separate analytics platform), each system should authenticate "
        "with its own <b>service account</b>. This provides credential isolation, independent "
        "revocation, and per-client audit trails."
    ))

    story.append(p("13.1 Why Not Share the Static API Key?", "H2"))
    story.append(p(
        "The external API gateway supports a single static API key (Section 2.1). While simple, "
        "sharing this key between multiple systems has significant drawbacks:"
    ))
    story.append(make_table(
        ["Problem", "Impact"],
        [
            ["No audit trail separation", "Cannot distinguish which system made a request in logs"],
            ["All-or-nothing revocation", "Rotating the key invalidates ALL integrations simultaneously"],
            ["Single point of compromise", "If one system leaks the key, all systems are exposed"],
            ["No per-client permissions", "All systems share the same endpoint access configuration"],
        ],
        col_widths=[W*0.30, W*0.70]
    ))

    story.append(p("13.2 Service Account Architecture", "H2"))
    story.append(p(
        "Instead, each ERP or external system gets its own service account with role "
        "<font face='Courier'>api_client</font>. The authentication flow:"
    ))
    story.append(code(
        "# Step 1: ERP authenticates with service credentials (once per 8 hours)\n"
        "POST https://marina.lika.solutions/api/auth/service-token\n"
        "Content-Type: application/json\n"
        "\n"
        "{\n"
        '  "email": "erp-service@partner.com",\n'
        '  "password": "securePassword123"\n'
        "}\n"
        "\n"
        "Response:\n"
        "{\n"
        '  "access_token": "eyJhbGciOiJIUzI1NiIs...",\n'
        '  "role": "api_client",\n'
        '  "email": "erp-service@partner.com"\n'
        "}\n"
        "\n"
        "# Step 2: ERP uses the JWT for all API calls (valid 8 hours)\n"
        "GET https://marina.lika.solutions/api/ext/sessions/active\n"
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIs...\n"
        "\n"
        "# Step 3: ERP refreshes token before expiry (recommended: every 7 hours)\n"
        "# Simply repeat Step 1 to get a new token."
    ))

    story.append(p("13.3 Token Lifecycle Management", "H2"))
    story.append(p("The ERP should implement token caching and refresh logic:"))
    story.append(make_table(
        ["Parameter", "Value", "Notes"],
        [
            ["Token lifetime", "8 hours", "Set by Pedestal SW (JWT exp claim)"],
            ["Recommended cache", "7 hours", "Refresh 1 hour before expiry to avoid request failures"],
            ["On 401 response", "Re-authenticate immediately", "Token may have been revoked or clock skew"],
            ["Storage", "In-memory (preferred) or encrypted at rest", "Never store JWT in plaintext files or logs"],
            ["Concurrency", "Cache per-client, not globally", "Each marina/integration gets its own token"],
        ],
        col_widths=[W*0.22, W*0.28, W*0.50]
    ))
    story.append(code(
        "# Pseudocode: Token caching pattern\n"
        "class PedestalClient:\n"
        "    def __init__(self, base_url, email, password):\n"
        "        self.base_url = base_url\n"
        "        self.email = email\n"
        "        self.password = password\n"
        "        self._token = None\n"
        "        self._token_expires = None\n"
        "\n"
        "    def _get_token(self):\n"
        "        if self._token and datetime.utcnow() < self._token_expires:\n"
        "            return self._token\n"
        "        resp = httpx.post(f'{self.base_url}/api/auth/service-token',\n"
        "                          json={'email': self.email, 'password': self.password})\n"
        "        resp.raise_for_status()\n"
        "        self._token = resp.json()['access_token']\n"
        "        self._token_expires = datetime.utcnow() + timedelta(hours=7)\n"
        "        return self._token\n"
        "\n"
        "    def get_sessions(self):\n"
        "        token = self._get_token()\n"
        "        return httpx.get(f'{self.base_url}/api/ext/sessions/active',\n"
        "                         headers={'Authorization': f'Bearer {token}'})"
    ))

    story.append(p("13.4 Service Account Setup (Performed by Lika Digital)", "H2"))
    story.append(p(
        "Service accounts are created by a Pedestal SW admin. The process:"
    ))
    story.append(bullet_list([
        "<b>Step 1:</b> ERP provider sends Lika Digital the desired service account email and password.",
        "<b>Step 2:</b> Lika Digital creates the account on the NUC from the dashboard "
        "(<b>Settings &rarr; Add User &rarr; role \"ERP User\"</b>, setting the email + password), or "
        "equivalently via <font face='Courier'>scripts/create_erp_service_account.py</font>. "
        "Both create a role <font face='Courier'>api_client</font> account.",
        "<b>Step 3:</b> Lika Digital configures the API Gateway endpoints and events for this integration.",
        "<b>Step 4:</b> ERP team tests authentication: "
        "<font face='Courier'>POST /api/auth/service-token</font> with their credentials.",
        "<b>Step 5:</b> ERP team begins calling gateway endpoints with the obtained JWT.",
    ]))
    story.append(note(
        "Service accounts use role <font face='Courier'>api_client</font> and can only authenticate "
        "via <font face='Courier'>/api/auth/service-token</font>. They cannot use the admin UI "
        "login (which requires authenticator-app TOTP two-factor). The service-token endpoint "
        "returns a JWT directly, with no 2FA step, making it suitable for automated "
        "system-to-system integration."
    ))

    story.append(note(
        "ERP authentication and access are audited. Every service-token success and every "
        "failed / denied attempt is written to the security log (source "
        "<font face='Courier'>ext-api/auth</font>), and gateway denials plus control (write) "
        "actions are logged (source <font face='Courier'>ext-api/gateway</font>) with the source IP. "
        "These appear in the dashboard log viewer (category \"security\") and via "
        "<font face='Courier'>journalctl -u cloud-iot-backend</font>, so the operator can see who "
        "connected, when, and from where. Successful GET reads are not logged, to avoid noise."
    ))

    story.append(p("13.5 Multiple ERP Systems on One Pedestal", "H2"))
    story.append(p(
        "If multiple ERP systems connect to the same marina's Pedestal SW:"
    ))
    story.append(make_table(
        ["Feature", "Current Support", "Recommendation"],
        [
            ["Separate service accounts", "YES &mdash; each ERP gets its own api_client user",
             "Create one per integrating system"],
            ["Separate endpoint permissions", "PARTIAL &mdash; gateway config is global (single row)",
             "All service accounts share the same allowed endpoints"],
            ["Separate webhook URLs", "NO &mdash; single webhook_url in config",
             "ERP systems should use polling + one shared webhook URL that fans out internally"],
            ["Audit by client", "YES &mdash; JWT contains email/sub, logged in gateway",
             "Each service account's actions are distinguishable in logs"],
        ],
        col_widths=[W*0.20, W*0.38, W*0.42]
    ))
    story.append(note(
        "For the pilot phase, a single ERP integration with one service account is the expected "
        "setup. Multi-client support with per-client endpoint permissions and multiple webhook "
        "URLs can be added in a future release if demand requires it."
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 14. REFERENCE IMPLEMENTATION
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("14. Reference Implementation (ERP-IOT)", "H1"))
    story.append(p(
        "The ERP-IOT project is a working reference implementation that demonstrates all "
        "integration patterns described in this document. It is deployed and tested against "
        "the Pedestal SW."
    ))

    story.append(p("14.1 Technology Stack", "H2"))
    story.append(make_table(
        ["Component", "Technology", "Purpose"],
        [
            ["Backend", "FastAPI (Python 3.11+)", "REST API, webhook handling, Pedestal API client"],
            ["Frontend", "React + TypeScript", "Multi-marina dashboard, controls, analytics"],
            ["Database", "PostgreSQL 16", "Marinas, users, cache, audit logs"],
            ["Auth", "JWT (HS256) + bcrypt", "User auth + service account auth to Pedestal"],
            ["Encryption", "Fernet (AES-128-CBC)", "Service account password storage"],
            ["Deployment", "Docker Compose + nginx", "Orchestration and reverse proxy"],
        ],
        col_widths=[W*0.15, W*0.35, W*0.50]
    ))

    story.append(p("14.2 Key Design Patterns", "H2"))

    story.append(p("<b>Per-Marina API Client Factory:</b>"))
    story.append(p(
        "A singleton factory creates one <font face='Courier'>PedestalAPIClient</font> per marina. "
        "Each client manages its own JWT token lifecycle (authenticate on first call, cache token, "
        "refresh before expiry). This ensures efficient connection reuse."
    ))

    story.append(p("<b>Stale Data Fallback:</b>"))
    story.append(p(
        "Every API call to Pedestal SW is wrapped in retry logic. On total failure, the system "
        "falls back to the last cached response from the <font face='Courier'>pedestal_cache</font> "
        "table. Responses include an <font face='Courier'>is_stale</font> boolean so the frontend "
        "can display a degraded-mode indicator."
    ))

    story.append(p("<b>Webhook Reception + WebSocket Broadcast:</b>"))
    story.append(p(
        "Incoming webhooks from Pedestal SW are validated (HMAC), persisted to typed log tables "
        "(alarm_log, session_log), and immediately broadcast to connected WebSocket clients "
        "scoped by marina_id."
    ))

    story.append(p("<b>Comprehensive Audit Trail:</b>"))
    story.append(p(
        "Every control action (allow, deny, stop, acknowledge alarm) is recorded in an "
        "<font face='Courier'>audit_log</font> table with: user_id, marina_id, pedestal_id, "
        "action name, target_id, JSON details, and timestamp."
    ))

    story.append(p("14.3 Data Model Summary", "H2"))
    story.append(make_table(
        ["Table", "Purpose", "Key Fields"],
        [
            ["marinas", "Marina configuration", "api_base_url, service_email, encrypted_password, webhook_secret"],
            ["users", "ERP operator accounts", "email, password_hash, role (super_admin/marina_manager)"],
            ["user_marina_access", "RBAC junction table", "user_id, marina_id, granted_by"],
            ["pedestal_cache", "Cached Pedestal data", "marina_id, pedestal_id, last_seen_data (JSON), is_stale"],
            ["alarm_log", "Alarm event history", "marina_id, pedestal_id, alarm_data (JSON), acknowledged_at"],
            ["session_log", "Session event history", "marina_id, pedestal_id, session_data (JSON)"],
            ["sync_log", "API call audit", "marina_id, sync_type, status, error_message"],
            ["audit_log", "Control action audit", "user_id, marina_id, action, target_id, details (JSON)"],
        ],
        col_widths=[W*0.20, W*0.30, W*0.50]
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 15. QUICK-START CHECKLIST
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("15. Quick-Start Checklist", "H1"))
    story.append(p(
        "Follow these steps to integrate a new ERP system with the Pedestal SW:"
    ))

    checklist = [
        ("<b>1. Network access</b> &mdash; Ensure the ERP can reach the NUC's IP address (or "
         "Cloudflare tunnel URL) on port 80/443."),
        ("<b>2. Configure gateway</b> &mdash; Admin logs into Pedestal UI &rarr; API Gateway page "
         "&rarr; selects endpoints + events &rarr; sets webhook URL."),
        ("<b>3. Generate API key</b> &mdash; Click 'Rotate Key' in the gateway page. "
         "Copy the JWT and store it securely in the ERP configuration."),
        ("<b>4. Verify &amp; activate</b> &mdash; Click 'Verify' to test connectivity, then 'Activate'."),
        ("<b>5. Implement authentication</b> &mdash; ERP sends "
         "<font face='Courier'>Authorization: Bearer {api_key}</font> on every request."),
        ("<b>6. Implement polling</b> &mdash; Periodically call "
         "<font face='Courier'>GET /api/ext/pedestals</font>, "
         "<font face='Courier'>GET /api/ext/sessions/active</font>, etc."),
        ("<b>7. Implement webhook handler</b> &mdash; Accept POST events at the configured URL. "
         "Validate the <font face='Courier'>X-API-Key</font> header. Return 200 quickly."),
        ("<b>8. Implement stale-data fallback</b> &mdash; Cache successful responses. "
         "On failure, serve cached data with a stale indicator."),
        ("<b>9. Implement control actions</b> &mdash; If needed, call "
         "<font face='Courier'>POST /api/ext/controls/{id}/allow|deny|stop</font> "
         "for session management."),
        ("<b>10. Implement billing sync</b> &mdash; Listen for <font face='Courier'>session_completed</font> "
         "events. Query <font face='Courier'>/api/ext/billing/spending/detail</font> for reconciliation."),
        ("<b>11. Audit logging</b> &mdash; Log all control actions with operator identity and timestamps."),
        ("<b>12. Test end-to-end</b> &mdash; Use the pedestal simulator to generate sessions "
         "and verify the full flow from event &rarr; webhook &rarr; ERP processing."),
    ]
    for item in checklist:
        story.append(p(item))
        story.append(Spacer(1, 2))

    # ═══════════════════════════════════════════════════════════════════════════
    # 16. DATA FOR THE MARINA OPERATOR PERSONA
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("16. Data for the Marina Operator Persona", "H1"))
    story.append(p(
        "Inside MarinaMaster, the <b>Marina Operator</b> is the staff role that runs the site day "
        "to day. This section maps each operator need to the Pedestal SW data that satisfies it, so "
        "MarinaMaster knows which endpoints to poll and which webhook events to subscribe to when "
        "building the operator console. The operator console is the read/write surface &mdash; it "
        "both displays state and issues control actions."
    ))

    story.append(p("16.1 Core Data Objects Exchanged", "H2"))
    story.append(p(
        "The following objects are the primary structures exchanged over the API and webhooks. "
        "Field-level payloads are in Section 9 (events), Section 7.4 (invoice) and the endpoint "
        "responses."
    ))
    story.append(make_table(
        ["Object", "Key fields", "Primary source"],
        [
            ["Pedestal", "id, name, location, online, initialized, mobile_enabled, sockets[]",
             "pedestals.list / pedestals.health"],
            ["Session", "id, pedestal_id, socket_id, type (electricity/water), status, started_at, "
                        "ended_at, energy_kwh, water_liters, customer_id",
             "sessions.active / sessions.pending / session_* events"],
            ["Socket load", "socket_id, phases, rated_amps, current_amps, load_pct, status "
                            "(normal/warning/critical), meter_type",
             "load.socket_get_ext / meter_load_* events"],
            ["Breaker", "socket_id, state, trip_cause, type, rating, poles, rcd, trip_count",
             "breakers.* / breaker_state_changed, breaker_alarm"],
            ["Alarm", "id, kind, pedestal_id, socket_id, value, threshold, acknowledged, triggered_at",
             "alarms.active / temperature_reading, moisture_reading, hardware_alarm"],
            ["Invoice", "id, session_id, customer_id, energy_kwh, water_liters, total_eur, paid",
             "invoice_created event / billing endpoints"],
        ],
        col_widths=[W * 0.16, W * 0.50, W * 0.34]))

    story.append(p("16.2 Operator Need &rarr; Pedestal Data Mapping", "H2"))
    story.append(make_table(
        ["Operator need", "Endpoints (pull)", "Events (push)"],
        [
            ["Live site overview &amp; connectivity",
             "pedestals.list, pedestals.health",
             "heartbeat, pedestal_health_updated"],
            ["Who is drawing power / water now",
             "sessions.active",
             "session_created, session_updated, session_telemetry"],
            ["Pending requests to approve",
             "sessions.pending",
             "socket_pending, user_plugged_in"],
            ["Allow / deny / stop a session",
             "controls.allow, controls.deny, controls.stop (bidirectional)",
             "session_updated, session_completed, socket_rejected"],
            ["Load &amp; overload protection",
             "load.pedestal_get_ext, load.socket_get_ext, load.*_alarms_ext, load.auto_stop_ack_ext",
             "meter_load_warning, meter_load_critical, meter_load_auto_stop, meter_load_resolved"],
            ["Breaker status &amp; reset",
             "breakers.pedestal_list_ext, breakers.socket_get_ext, breakers.socket_reset_ext",
             "breaker_state_changed, breaker_alarm"],
            ["Environmental &amp; security alarms",
             "alarms.active, alarms.acknowledge",
             "temperature_reading, moisture_reading, hardware_alarm, marina_door"],
            ["Run diagnostics / commission",
             "diagnostics.run, pedestals.list",
             "diagnostics_result, hardware_config_updated, pedestal_registered"],
            ["Camera, occupancy &amp; berths",
             "camera.frame_ext, camera.stream_ext, berths.list, berths.occupancy_ext",
             "berth_occupancy_updated"],
            ["LED, schedule &amp; reset",
             "controls.led, led_schedule.*, controls.reset (bidirectional)",
             "led_changed, pedestal_reset_sent"],
            ["Energy analytics &amp; billing reconciliation",
             "analytics.daily, analytics.summary",
             "session_completed, invoice_created"],
        ],
        col_widths=[W * 0.28, W * 0.40, W * 0.32]))
    story.append(note(
        "All control actions (allow, deny, stop, acknowledge, reset, breaker reset) require "
        "<font face='Courier'>bidirectional</font> mode and should be recorded in MarinaMaster's "
        "audit log with operator identity and timestamp. Read-only monitor staff in MarinaMaster "
        "should be given only the pull endpoints and events, never the control endpoints."
    ))

    story.append(PageBreak())

    # ═══════════════════════════════════════════════════════════════════════════
    # 17. DATA EXPOSED TO THE MYMARINA END-USER APP
    # ═══════════════════════════════════════════════════════════════════════════
    story.append(p("17. Data Exposed to the MyMarina End-User App", "H1"))
    story.append(p(
        "<b>MyMarina</b> is MarinaMaster's mobile application for boat owners (end users). "
        "MarinaMaster acts as the broker: it consumes the full operator-grade data from Pedestal "
        "SW (Section 16) and re-exposes a <b>curated, customer-scoped subset</b> to MyMarina. "
        "MyMarina never talks to operator control endpoints and only ever sees the signed-in "
        "customer's own data."
    ))

    story.append(p("17.1 MyMarina Feature &rarr; Underlying Data", "H2"))
    story.append(make_table(
        ["MyMarina feature", "Underlying pedestal data", "Source"],
        [
            ["Start a session by scanning the socket QR",
             "Claim the socket for this customer; bind customer_id to the session",
             "mobile.qr_claim, mobile.socket_qr"],
            ["Live meter while charging / taking water",
             "duration, energy_kwh, power_kw (electricity) or litres (water) &mdash; own session only",
             "mobile.session_live, session_telemetry event"],
            ["My session history",
             "completed sessions filtered to this customer_id, with consumption",
             "sessions + session_completed (customer-scoped by MarinaMaster)"],
            ["My invoices &amp; payment status",
             "energy/water cost, total_eur, paid flag, invoice PDF",
             "invoice_created event + billing data"],
            ["My contracts",
             "pending agreements to sign, signed agreements + PDF",
             "customer contract data (MarinaMaster-side)"],
            ["Service requests",
             "request a marina service with notes; status updates",
             "service-order data (MarinaMaster-side)"],
            ["Support chat &amp; notifications",
             "messages to/from staff; push on approval, reply, alarm-affecting-me",
             "chat data + push tokens (MarinaMaster-side)"],
        ],
        col_widths=[W * 0.28, W * 0.44, W * 0.28]))

    story.append(p("17.2 Scoping &amp; Privacy Rules", "H2"))
    story.append(bullet_list([
        "<b>Customer scoping is mandatory.</b> MyMarina must filter every list (sessions, invoices, "
        "contracts) to the authenticated <font face='Courier'>customer_id</font>. Pedestal SW "
        "session and invoice records carry <font face='Courier'>customer_id</font> for exactly this "
        "purpose.",
        "<b>No control surface.</b> Do not expose allow / deny / stop / reset / breaker / LED "
        "endpoints to MyMarina. End users start and stop only their <i>own</i> session via the "
        "mobile/QR endpoints.",
        "<b>Auto-activate sessions are invisible to MyMarina.</b> A plug-and-go (auto-activate) "
        "session is created with <font face='Courier'>customer_id = null</font>, so it has no owner "
        "and must not appear in any customer's history or invoices. Only QR/app-claimed sessions are "
        "billable to a MyMarina account.",
        "<b>Data minimization.</b> MyMarina should receive only the fields a boat owner needs "
        "(their consumption, cost, status) &mdash; not raw operator telemetry, other berths, camera "
        "frames, or site-wide alarms.",
    ]))
    story.append(note(
        "The split is clean: Section 16 (operator) is the full read/write operational surface; "
        "Section 17 (MyMarina) is a narrow, per-customer, read-mostly slice. MarinaMaster owns the "
        "boundary &mdash; Pedestal SW provides the data and the customer_id; MarinaMaster enforces "
        "which customer sees what."
    ))

    story.append(Spacer(1, 20))
    story.append(hr())
    story.append(Spacer(1, 10))
    story.append(p(
        f"Document generated: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
        "Cloud_IOT Pedestal SW | MarinaMaster + MyMarina Integration | Lika Digital d.o.o.",
        "Footer"
    ))

    # Build
    doc.build(story)
    print(f"\nPDF generated: {OUTPUT_PATH}")


if __name__ == "__main__":
    build_pdf()
