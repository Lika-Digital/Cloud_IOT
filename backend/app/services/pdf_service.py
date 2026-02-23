"""PDF generation service using reportlab (pure-Python, 32-bit compatible)."""
from __future__ import annotations
import base64
import io
from datetime import datetime
from typing import Optional


def _make_pdf_buffer(draw_fn) -> bytes:
    """Create a PDF in memory and return bytes."""
    buf = io.BytesIO()
    draw_fn(buf)
    buf.seek(0)
    return buf.read()


def make_contract_pdf(
    *,
    template_title: str,
    template_body: str,
    customer_name: Optional[str],
    customer_email: str,
    signed_at: datetime,
    valid_until: Optional[datetime],
    signature_data: Optional[str],  # base64 PNG
) -> bytes:
    """Generate a signed contract PDF and return bytes."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Image as RLImage
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ContractTitle",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#1a3c5e"),
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    header_style = ParagraphStyle(
        "MarinHeader",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    label_style = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#666666"),
        spaceAfter=2,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        spaceAfter=6,
    )

    story = []

    # Header
    story.append(Paragraph("Marina Portorož", title_style))
    story.append(Paragraph(
        "Cesta solinarjev 8, 6320 Portorož, Slovenia | Tel: +386 5 676 02 00",
        header_style,
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a3c5e")))
    story.append(Spacer(1, 8 * mm))

    # Contract title
    story.append(Paragraph(template_title, title_style))
    story.append(Spacer(1, 4 * mm))

    # Customer info
    story.append(Paragraph(f"<b>Customer Name:</b> {customer_name or 'N/A'}", label_style))
    story.append(Paragraph(f"<b>Email:</b> {customer_email}", label_style))
    story.append(Paragraph(f"<b>Signed:</b> {signed_at.strftime('%Y-%m-%d %H:%M UTC')}", label_style))
    if valid_until:
        story.append(Paragraph(f"<b>Valid Until:</b> {valid_until.strftime('%Y-%m-%d')}", label_style))
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 4 * mm))

    # Contract body — split on newlines for paragraphs
    for line in template_body.split("\n"):
        stripped = line.strip()
        if stripped:
            story.append(Paragraph(stripped, body_style))
        else:
            story.append(Spacer(1, 3 * mm))

    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))
    story.append(Spacer(1, 4 * mm))

    # Signature
    story.append(Paragraph("<b>Customer Signature:</b>", label_style))
    story.append(Spacer(1, 2 * mm))
    if signature_data:
        try:
            # Strip data URI prefix if present
            raw = signature_data
            if "," in raw:
                raw = raw.split(",", 1)[1]
            img_bytes = base64.b64decode(raw)
            img_buf = io.BytesIO(img_bytes)
            img = RLImage(img_buf, width=60 * mm, height=25 * mm)
            story.append(img)
        except Exception:
            story.append(Paragraph("[Signature image could not be rendered]", label_style))
    else:
        story.append(Paragraph("[No signature]", label_style))

    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        f"Signed electronically on {signed_at.strftime('%Y-%m-%d')} — Marina Portorož IoT Portal",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=colors.grey, alignment=TA_CENTER),
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()


def make_invoice_pdf(
    *,
    invoice_id: int,
    customer_name: Optional[str],
    customer_email: str,
    session_id: int,
    session_type: str,
    started_at: Optional[datetime],
    ended_at: Optional[datetime],
    energy_kwh: Optional[float],
    water_liters: Optional[float],
    energy_cost_eur: Optional[float],
    water_cost_eur: Optional[float],
    total_eur: float,
    paid: bool,
    created_at: datetime,
) -> bytes:
    """Generate an invoice PDF and return bytes."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
    )
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvTitle",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#1a3c5e"),
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    header_style = ParagraphStyle(
        "InvHeader",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    label_style = ParagraphStyle(
        "InvLabel",
        parent=styles["Normal"],
        fontSize=10,
        spaceAfter=4,
    )
    right_style = ParagraphStyle(
        "InvRight",
        parent=styles["Normal"],
        fontSize=10,
        alignment=TA_RIGHT,
    )

    paid_color = colors.HexColor("#16a34a") if paid else colors.HexColor("#dc2626")
    paid_text = "PAID" if paid else "UNPAID"

    story = []

    # Header
    story.append(Paragraph("Marina Portorož", title_style))
    story.append(Paragraph(
        "Cesta solinarjev 8, 6320 Portorož, Slovenia | Tel: +386 5 676 02 00",
        header_style,
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1a3c5e")))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph(f"INVOICE #{invoice_id:05d}", title_style))
    story.append(Paragraph(
        f'<font color="{paid_color.hexval()}">{paid_text}</font>',
        ParagraphStyle("Status", parent=styles["Normal"], fontSize=12, alignment=TA_CENTER, spaceAfter=6),
    ))
    story.append(Spacer(1, 4 * mm))

    # Customer & session info
    story.append(Paragraph(f"<b>Customer:</b> {customer_name or 'N/A'}", label_style))
    story.append(Paragraph(f"<b>Email:</b> {customer_email}", label_style))
    story.append(Paragraph(f"<b>Session ID:</b> {session_id}", label_style))
    story.append(Paragraph(f"<b>Session Type:</b> {session_type.capitalize()}", label_style))
    if started_at:
        story.append(Paragraph(f"<b>Start:</b> {started_at.strftime('%Y-%m-%d %H:%M UTC')}", label_style))
    if ended_at:
        story.append(Paragraph(f"<b>End:</b> {ended_at.strftime('%Y-%m-%d %H:%M UTC')}", label_style))
    story.append(Paragraph(f"<b>Invoice Date:</b> {created_at.strftime('%Y-%m-%d')}", label_style))
    story.append(Spacer(1, 6 * mm))

    # Breakdown table
    table_data = [["Description", "Usage", "Unit Price", "Amount"]]
    if energy_kwh is not None and energy_kwh > 0:
        unit = (energy_cost_eur / energy_kwh) if energy_kwh else 0.0
        table_data.append([
            "Electricity",
            f"{energy_kwh:.4f} kWh",
            f"€{unit:.4f}/kWh",
            f"€{energy_cost_eur:.2f}",
        ])
    if water_liters is not None and water_liters > 0:
        unit = (water_cost_eur / water_liters) if water_liters else 0.0
        table_data.append([
            "Water",
            f"{water_liters:.2f} L",
            f"€{unit:.4f}/L",
            f"€{water_cost_eur:.2f}",
        ])
    table_data.append(["", "", "TOTAL", f"€{total_eur:.2f}"])

    tbl = Table(table_data, colWidths=[80 * mm, 40 * mm, 35 * mm, 30 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3c5e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f3f4f6")]),
        ("FONTNAME", (2, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1a3c5e")),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#1a3c5e")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph(
        "Thank you for using Marina Portorož services. For inquiries: info@marina-portoroz.si",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=colors.grey, alignment=TA_CENTER),
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()
