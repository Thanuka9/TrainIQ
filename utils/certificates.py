"""Completion certificate PDF generation."""
from __future__ import annotations

from datetime import datetime

from models import UserProgress


def user_has_completed_material(user, study_material) -> bool:
    """True when the learner has 100% progress on the material."""
    if not user or not study_material:
        return False
    prog = UserProgress.query.filter_by(
        user_id=user.id,
        study_material_id=study_material.id,
    ).first()
    if not prog:
        return False
    return bool(prog.completed or (prog.progress_percentage or 0) >= 100)


def generate_completion_certificate(user, study_material) -> bytes | None:
    """
    Build a PDF completion certificate when the user has finished the course.
    Returns None when the course is not complete.
    """
    if not user_has_completed_material(user, study_material):
        return None

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    import io

    prog = UserProgress.query.filter_by(
        user_id=user.id,
        study_material_id=study_material.id,
    ).first()
    completed_on = (
        prog.completion_date.strftime("%B %d, %Y")
        if prog and prog.completion_date
        else datetime.utcnow().strftime("%B %d, %Y")
    )
    learner_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.employee_email
    org_name = user.tenant.name if getattr(user, "tenant", None) else "TrainIQ"

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72,
        title=f"Certificate — {study_material.title}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CertTitle",
        parent=styles["Heading1"],
        fontSize=28,
        alignment=1,
        spaceAfter=12,
        textColor=colors.HexColor("#3730A3"),
    )
    subtitle_style = ParagraphStyle(
        "CertSubtitle",
        parent=styles["Normal"],
        fontSize=14,
        alignment=1,
        spaceAfter=24,
        textColor=colors.HexColor("#64748B"),
    )
    body_style = ParagraphStyle(
        "CertBody",
        parent=styles["Normal"],
        fontSize=16,
        alignment=1,
        leading=24,
        textColor=colors.HexColor("#334155"),
    )
    course_style = ParagraphStyle(
        "CertCourse",
        parent=styles["Heading2"],
        fontSize=22,
        alignment=1,
        spaceBefore=12,
        spaceAfter=24,
        textColor=colors.HexColor("#1E293B"),
    )
    footer_style = ParagraphStyle(
        "CertFooter",
        parent=styles["Normal"],
        fontSize=11,
        alignment=1,
        textColor=colors.HexColor("#94A3B8"),
    )

    story = [
        Spacer(1, 0.5 * inch),
        Paragraph("Certificate of Completion", title_style),
        Paragraph(org_name, subtitle_style),
        Paragraph("This certifies that", body_style),
        Paragraph(f"<b>{learner_name}</b>", ParagraphStyle(
            "CertName",
            parent=body_style,
            fontSize=20,
            textColor=colors.HexColor("#3730A3"),
        )),
        Paragraph("has successfully completed the course", body_style),
        Paragraph(study_material.title, course_style),
        Paragraph(f"Completed on {completed_on}", footer_style),
        Spacer(1, 0.75 * inch),
        Paragraph("TrainIQ Learning Management System", footer_style),
    ]

    doc.build(story)
    buffer.seek(0)
    return buffer.read()
