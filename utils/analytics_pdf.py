"""Build structured Analytics PDF reports (KPIs, AI summary, chart images)."""
from __future__ import annotations

import base64
import io
from datetime import datetime


def build_analytics_pdf(
    org_name: str,
    filters: dict,
    kpis: dict,
    insights_text: str,
    chart_images: list[dict],
) -> bytes:
    """
    chart_images: [{"title": str, "data": "base64..."}, ...]
    Returns PDF bytes.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=48,
        leftMargin=48,
        topMargin=48,
        bottomMargin=48,
        title=f"{org_name} Analytics Report",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=22,
        spaceAfter=6,
        textColor=colors.HexColor("#1E293B"),
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#64748B"),
        spaceAfter=16,
    )
    h2 = ParagraphStyle(
        "SectionH2",
        parent=styles["Heading2"],
        fontSize=14,
        spaceBefore=14,
        spaceAfter=8,
        textColor=colors.HexColor("#334155"),
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#475569"),
    )

    story = []
    story.append(Paragraph(f"{org_name} — Analytics Report", title_style))
    story.append(
        Paragraph(
            f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} · Platform Insights & Trends",
            subtitle_style,
        )
    )

    filter_bits = []
    for key, label in (
        ("start_date", "From"),
        ("end_date", "To"),
        ("department", "Department"),
        ("designation", "Designation"),
        ("period", "Period"),
    ):
        val = (filters or {}).get(key)
        if val:
            filter_bits.append(f"<b>{label}:</b> {val}")
    if filter_bits:
        story.append(Paragraph(" · ".join(filter_bits), body))
        story.append(Spacer(1, 12))

    kpi_rows = [
        ["Metric", "Value"],
        ["Total Users", str(kpis.get("total_users", "—"))],
        ["Active Users", str(kpis.get("active_users", "—"))],
        ["Avg Exam Score", f"{kpis.get('avg_exam_score', '—')}%"],
        ["Avg Course Progress", f"{kpis.get('avg_course_progress', '—')}%"],
        ["Avg Special Exam", f"{kpis.get('special_avg_score', '—')}%"],
        ["Pass Rate", f"{kpis.get('pass_pct', '—')}%"],
    ]
    kpi_table = Table(kpi_rows, colWidths=[2.8 * inch, 2.2 * inch])
    kpi_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2FF")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#3730A3")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(Paragraph("Executive KPIs", h2))
    story.append(kpi_table)
    story.append(Spacer(1, 16))

    if insights_text and insights_text.strip():
        story.append(Paragraph("AnalyticsIQ Summary", h2))
        safe = (
            insights_text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )
        story.append(Paragraph(safe, body))
        story.append(Spacer(1, 16))

    if chart_images:
        story.append(Paragraph("Charts & Visualizations", h2))
        max_w = doc.width
        for item in chart_images:
            title = item.get("title") or "Chart"
            raw = item.get("data") or ""
            if not raw:
                continue
            try:
                payload = raw.split(",")[-1] if "," in raw else raw
                img_bytes = base64.b64decode(payload)
                img = Image(io.BytesIO(img_bytes))
                ratio = img.imageHeight / float(img.imageWidth or 1)
                img.drawWidth = max_w
                img.drawHeight = max_w * ratio
                if img.drawHeight > 4.5 * inch:
                    img.drawHeight = 4.5 * inch
                    img.drawWidth = img.drawHeight / ratio
                story.append(Paragraph(title, ParagraphStyle("ChartTitle", parent=body, fontName="Helvetica-Bold")))
                story.append(Spacer(1, 6))
                story.append(img)
                story.append(Spacer(1, 14))
            except Exception:
                continue

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
