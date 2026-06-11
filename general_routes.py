from flask import Blueprint, render_template, session, logging, jsonify, request, redirect, url_for, flash
from utils.api_errors import handle_api_exception
from flask_login import login_required, current_user
from datetime import date, datetime
from flask import send_file
from wtforms import StringField, TextAreaField, FileField
from wtforms.validators import DataRequired
from flask_wtf import FlaskForm
from io import BytesIO
from werkzeug.utils import secure_filename
from models import (
    db,
    StudyMaterial,
    UserProgress,
    UserScore,
    SpecialExamRecord,
    Task,
    SupportTicket,
    SupportAttachment,
    IncorrectAnswer,
    Question,
)
class SupportRequestForm(FlaskForm):
    title       = StringField('Issue Title', validators=[DataRequired()])
    description = TextAreaField('Detailed Description', validators=[DataRequired()])
    attachment  = FileField('Attach File (Optional)')

from utils.tenant_utils import filter_by_user_tenant, user_tenant_id
from utils.task_filters import assigned_to_user

# Initialize Blueprint
general_routes = Blueprint('general_routes', __name__)

@general_routes.route('/home')
def home():
    return render_template('home.html')

@general_routes.route('/dashboard')
@login_required
def dashboard():
    user_name        = current_user.first_name
    user_designation = current_user.designation.title if current_user.designation else "Not Assigned"
    user_id          = current_user.id

    # — Learning Progress —
    current_progress = (
        db.session.query(StudyMaterial.title, UserProgress.progress_percentage)
          .join(UserProgress, StudyMaterial.id == UserProgress.study_material_id)
          .filter(UserProgress.user_id == user_id)
          .order_by(UserProgress.progress_percentage.desc())
          .first()
    )
    if current_progress:
        current_course, course_progress = current_progress
    else:
        current_course, course_progress = "No course in progress.", 0

    # — Last Exam Results (special or regular) —
    special_record = SpecialExamRecord.query.filter_by(user_id=user_id).first()
    user_score     = UserScore.query.filter_by(user_id=user_id).order_by(UserScore.created_at.desc()).first()

    if special_record:
        if special_record.paper1_completed_at:
            last_exam_title = "Special Exam Paper 1"
            last_exam_score = special_record.paper1_score
        elif special_record.paper2_completed_at:
            last_exam_title = "Special Exam Paper 2"
            last_exam_score = special_record.paper2_score
        else:
            last_exam_title = "Special Exam – Incomplete"
            last_exam_score = 0
    elif user_score:
        last_exam_title = user_score.exam.title if user_score.exam else "N/A"
        last_exam_score = user_score.score
    else:
        last_exam_title = "No exams completed yet."
        last_exam_score = 0

    # — Upcoming Deadlines: next 5 tasks due today or later —
    upcoming_tasks = (
        filter_by_user_tenant(Task.query, Task)
            .filter(
                assigned_to_user(current_user.id),
                Task.due_date >= date.today()
            )
            .order_by(Task.due_date.asc())
            .limit(5)
            .all()
    )

    return render_template(
        'dashboard.html',
        user_name        = user_name,
        user_role        = user_designation,
        current_course   = current_course,
        course_progress  = course_progress,
        last_exam_title  = last_exam_title,
        last_exam_score  = last_exam_score,
        upcoming_tasks   = upcoming_tasks
    )

@general_routes.route('/study_materials')
@login_required
def study_materials():
    try:
        materials = filter_by_user_tenant(StudyMaterial.query, StudyMaterial).all()
        progress_data = []
        user_id = session.get('user_id')

        for material in materials:
            up = UserProgress.query.filter_by(
                study_material_id=material.id,
                user_id=user_id
            ).first()
            progress_data.append({
                'course_id': material.id,
                'progress_percentage': up.progress_percentage if up else 0
            })

        is_super_admin = session.get('is_super_admin', False)
        return render_template(
            'study_materials.html',
            materials=materials,
            progress_data=progress_data,
            is_super_admin=is_super_admin,
            user_role=session.get('role')
        )
    except Exception as e:
        logging.error(f"Error rendering study materials: {e}")
        return jsonify({'error': 'Failed to load study materials'}), 500

def _analyticsiq_payload(user):
    """Collect learner data for AnalyticsIQ."""
    scores = (
        UserScore.query.filter_by(user_id=user.id)
        .order_by(UserScore.created_at.desc())
        .limit(10)
        .all()
    )
    scores_summary = "; ".join(
        f"{s.exam.title if s.exam else 'Exam'}: {s.score}%"
        for s in scores
    ) or "No exam attempts yet."

    incorrects = (
        IncorrectAnswer.query.filter_by(user_id=user.id)
        .order_by(IncorrectAnswer.answered_at.desc())
        .limit(20)
        .all()
    )
    incorrect_parts = []
    for rec in incorrects:
        q = Question.query.get(rec.question_id)
        qtext = q.question_text[:80] if q else f"Q#{rec.question_id}"
        incorrect_parts.append(
            f"[{qtext}] answered '{rec.user_answer}' (correct: '{rec.correct_answer}')"
        )
    incorrect_summary = "; ".join(incorrect_parts) or "No incorrect answers logged."

    courses = filter_by_user_tenant(StudyMaterial.query, StudyMaterial).order_by(StudyMaterial.title).limit(15).all()
    available_courses = ", ".join(c.title for c in courses) or "No courses available."
    return scores_summary, incorrect_summary, available_courses


@general_routes.route('/ai/performance-insights/start', methods=['POST'])
@login_required
def analyticsiq_start():
    """Start AnalyticsIQ analysis as a background job."""
    from utils.local_ai import analyticsiq_diagnose, get_ai_status
    from utils.ai_jobs import create_job, run_job
    from utils.ai_rate_limit import check_ai_rate_limit

    ok, retry = check_ai_rate_limit()
    if not ok:
        return jsonify({"error": f"Rate limit exceeded. Retry in {retry}s.", "retry_after": retry}), 429

    ai_status = get_ai_status()
    if not ai_status["available"] or not ai_status["model_ready"]:
        return jsonify({"error": ai_status["message"], **ai_status}), 503

    scores_summary, incorrect_summary, available_courses = _analyticsiq_payload(current_user)
    user_name = current_user.first_name or "Learner"
    from utils.tenant_utils import user_tenant_id
    job_id = create_job(current_user.id, "analyticsiq", tenant_id=user_tenant_id())

    def work():
        diagnosis = analyticsiq_diagnose(
            user_name,
            scores_summary,
            incorrect_summary,
            available_courses,
        )
        return {"diagnosis": diagnosis, "feature": "AnalyticsIQ", **get_ai_status()}

    from flask import current_app
    run_job(job_id, work, app=current_app._get_current_object())
    return jsonify({"job_id": job_id, "status": "pending"})


@general_routes.route('/ai/performance-insights')
@login_required
def analyticsiq_insights():
    """AnalyticsIQ sync fallback (prefer /start + job polling)."""
    from utils.local_ai import analyticsiq_diagnose, get_ai_status
    from utils.ai_rate_limit import check_ai_rate_limit

    ok, retry = check_ai_rate_limit()
    if not ok:
        return jsonify({"error": f"Rate limit exceeded. Retry in {retry}s.", "retry_after": retry}), 429

    ai_status = get_ai_status()
    if not ai_status["available"] or not ai_status["model_ready"]:
        return jsonify({"error": ai_status["message"], **ai_status}), 503

    scores_summary, incorrect_summary, available_courses = _analyticsiq_payload(current_user)

    try:
        diagnosis = analyticsiq_diagnose(
            current_user.first_name or "Learner",
            scores_summary,
            incorrect_summary,
            available_courses,
        )
        return jsonify({
            "diagnosis": diagnosis,
            "feature": "AnalyticsIQ",
            **ai_status,
        })
    except ConnectionError as e:
        return jsonify({"error": "AI service is temporarily unavailable.", "available": False}), 503


@general_routes.route('/client_materials')
@login_required
def client_materials():
    user_clients = current_user.clients
    materials_list = []
    for client in user_clients:
        materials_list.append({
            'title': f"{client.name} - Standard Billing Procedures",
            'description': f"SOP and billing code guidelines for processing claims under the {client.name} account.",
            'filename': f"{client.name.lower().replace(' ', '_')}_billing_sop.pdf",
            'client_name': client.name,
            'summary': f"This document covers the specific RCM and claim submission guidelines for {client.name}. This includes major payer ID rules, documentation requirements, and typical rejection reasons specific to {client.name}'s state programs."
        })
        materials_list.append({
            'title': f"{client.name} - Portal Security Guidelines",
            'description': f"Access protocols and HIPAA security compliance checklists for {client.name} portals.",
            'filename': f"{client.name.lower().replace(' ', '_')}_security_checklist.pdf",
            'client_name': client.name,
            'summary': f"HIPAA and internal network access rules for logging into the secure portals of {client.name}. Access logs are strictly monitored. Sharing credentials or using unsecured networks is strictly prohibited."
        })
    return render_template('client_materials.html', client_materials=materials_list)

@general_routes.route('/hr_management')
@login_required
def hr_management():
    return render_template('hr_management.html')

@general_routes.route('/privacy-policy')
def privacy_policy():
    if current_user.is_authenticated:
        base_template = 'base.html'
        if current_user.is_super_admin or (current_user.roles and current_user.roles[0].name in ('admin', 'super_admin')):
            base_template = 'admin_base.html'
        return render_template('privacy_policy.html', base_template=base_template)
    else:
        return render_template('public_privacy_policy.html')

@general_routes.route('/tenant-logo/<int:tenant_id>')
def serve_tenant_logo(tenant_id):
    from models import Tenant
    tenant = Tenant.query.get_or_404(tenant_id)
    if not tenant.logo_data:
        return redirect(url_for('static', filename='images/logo.png'))
    return send_file(
        BytesIO(tenant.logo_data),
        mimetype=tenant.logo_mimetype or 'image/png'
    )

@general_routes.route('/pricing')
def pricing():
    from utils.billing_plans import (
        TRIAL_DAYS,
        TRIAL_MAX_USERS,
        get_feature_comparison,
        get_public_plans,
    )
    return render_template(
        'pricing.html',
        public_plans=get_public_plans(),
        feature_comparison=get_feature_comparison(),
        trial_days=TRIAL_DAYS,
        trial_max_users=TRIAL_MAX_USERS,
    )

@general_routes.route('/help')
def help_page():
    return render_template('help.html')

@general_routes.route('/request-support', methods=['GET', 'POST'])
@login_required
def request_support():
    form = SupportRequestForm()

    if form.validate_on_submit():
        title       = form.title.data
        description = form.description.data
        uploaded_file = form.attachment.data  # FileStorage or None

        ticket = SupportTicket(
            user_id     = current_user.id,
            title       = title,
            description = description,
            status      = 'Open',
            created_at  = datetime.utcnow()
        )

        if uploaded_file and uploaded_file.filename:
            filename  = secure_filename(uploaded_file.filename)
            file_data = uploaded_file.read()
            mimetype  = uploaded_file.mimetype or 'application/octet-stream'

            attachment = SupportAttachment(
                filename    = filename,
                data        = file_data,
                mimetype    = mimetype,
                upload_time = datetime.utcnow()
            )
            ticket.attachments.append(attachment)

        db.session.add(ticket)
        db.session.commit()

        from utils.notifications import notify_tenant_super_admins
        tid = current_user.tenant_id
        if tid:
            notify_tenant_super_admins(
                tid,
                f"New support ticket #{ticket.id}",
                f"{current_user.first_name}: {title[:80]}",
                category="support",
                link_url=url_for("admin_routes.admin_view_ticket", ticket_id=ticket.id),
                icon="headset",
            )

        flash(f"Support ticket #{ticket.id} created successfully.", "success")
        return redirect(url_for('general_routes.support'))

    return render_template('submit_support.html', form=form)


# ─── 2) View Your Submitted Tickets ────────────────────────────────────
@general_routes.route('/support')
@login_required
def support():
    tickets = (
        SupportTicket.query
        .filter_by(user_id=current_user.id)
        .order_by(SupportTicket.created_at.desc())
        .all()
    )
    return render_template('support.html', user_tickets=tickets)


# ─── 3) Download an Attachment ─────────────────────────────────────────
@general_routes.route('/support/attachment/<int:attachment_id>')
@login_required
def download_attachment(attachment_id):
    attachment = SupportAttachment.query.get_or_404(attachment_id)

    # Ensure the current user owns this ticket (or is assigned to it, or is admin/super_admin)
    is_admin = current_user.is_super_admin or any(role.id == 2 for role in current_user.roles)
    if not is_admin and attachment.ticket.user_id != current_user.id and attachment.ticket.assigned_to != current_user.id:
        flash("You do not have permission to download this file.", "danger")
        return redirect(url_for('general_routes.support'))

    return send_file(
        BytesIO(attachment.data),
        download_name=attachment.filename,
        mimetype=attachment.mimetype,
        as_attachment=True
    )

# ─── One-Time Privacy Policy Agreement ─────────────────────────────
@general_routes.route('/privacy-policy-agreement', methods=['GET', 'POST'])
@login_required
def privacy_policy_agreement():
    if request.method == 'POST':
        # mark their consent
        current_user.privacy_agreed    = True
        current_user.privacy_agreed_at = datetime.utcnow()
        db.session.commit()
        # redirect to dashboard (not root)
        next_url = session.pop('next', url_for('general_routes.dashboard'))
        return redirect(next_url)

    # on GET, show the standalone agreement page
    return render_template('privacy_policy1.html')


@general_routes.route('/dismiss-trial-checklist', methods=['POST'])
@login_required
def dismiss_trial_checklist():
    """Hide the trial setup checklist for the current Super Admin."""
    if not current_user.is_super_admin:
        return jsonify({"ok": False}), 403
    current_user.trial_checklist_dismissed = True
    db.session.commit()
    return jsonify({"ok": True})

