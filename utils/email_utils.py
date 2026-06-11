from datetime import datetime, timedelta
from flask import current_app, render_template, url_for
from flask_mail import Message

from extensions import mail
from models import Task

# ──────────────────────────────────────────────────────────────────────────────
# Scheduler bootstrap
# ──────────────────────────────────────────────────────────────────────────────
def init_scheduler(scheduler):
    """
    Call this once from app.py after `scheduler.init_app(app)`:
        from utils.email_utils import init_scheduler
        init_scheduler(scheduler)

    Registers a job that runs every hour to check for tasks
    whose deadline falls within the next 24 h and are still open.
    """
    scheduler.add_job(
        id='deadline_notification',
        func=check_and_send_deadline_notifications,
        trigger='interval',
        minutes=60,
        replace_existing=True
    )
    scheduler.add_job(
        id='expire_saas_trials',
        func=expire_saas_trials_job,
        trigger='interval',
        hours=6,
        replace_existing=True,
    )
    scheduler.add_job(
        id='trial_reminder_emails',
        func=trial_reminder_emails_job,
        trigger='interval',
        hours=12,
        replace_existing=True,
    )
    scheduler.add_job(
        id='onboarding_drip_emails',
        func=onboarding_drip_emails_job,
        trigger='interval',
        hours=6,
        replace_existing=True,
    )


def expire_saas_trials_job():
    """Background job: mark overdue free trials as expired."""
    from extensions import scheduler
    from utils.billing_plans import backfill_missing_trial_dates
    from utils.tenant_limits import expire_overdue_trials

    app = scheduler.app
    with app.app_context():
        backfill_missing_trial_dates()
        count = expire_overdue_trials()
        if count:
            app.logger.info("[billing] Expired %s trial tenant(s)", count)


def trial_reminder_emails_job():
    """Background job: 7-day and 1-day trial reminder emails."""
    from extensions import scheduler
    from utils.trial_reminders import process_trial_reminder_emails

    app = scheduler.app
    with app.app_context():
        stats = process_trial_reminder_emails()
        if stats.get("seven_day") or stats.get("one_day"):
            app.logger.info(
                "[billing] Trial reminders sent: 7d=%s, 1d=%s",
                stats.get("seven_day", 0),
                stats.get("one_day", 0),
            )


def onboarding_drip_emails_job():
    """Background job: day 1 / 3 / 7 onboarding drip emails."""
    from extensions import scheduler
    from utils.onboarding_emails import process_onboarding_drip_emails

    app = scheduler.app
    with app.app_context():
        stats = process_onboarding_drip_emails()
        if any(stats.values()):
            app.logger.info("[onboarding] Drip emails sent: %s", stats)

# ──────────────────────────────────────────────────────────────────────────────
# Helper for attaching files safely
# ──────────────────────────────────────────────────────────────────────────────
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 MB

def _safe_attach(msg: Message, filename: str, mimetype: str, data: bytes):
    """
    Attach `data` iff it is ≤ 10 MB. Otherwise log & skip.
    """
    if len(data) <= MAX_ATTACHMENT_SIZE:
        msg.attach(filename, mimetype, data)
        current_app.logger.debug(f"[email_utils] Attached '{filename}' ({len(data)} bytes).")
    else:
        current_app.logger.warning(f"[email_utils] Skipping oversized attachment '{filename}' ({len(data)} bytes).")


# ──────────────────────────────────────────────────────────────────────────────
# New-task assignment
# ──────────────────────────────────────────────────────────────────────────────
def send_task_assignment_email(user, task):
    subject    = f"🆕 New Task Assigned — {task.title}"
    recipients = [user.employee_email]
    task_url   = url_for('task_routes.view_task', task_id=task.id, _external=True)

    msg = Message(subject=subject, recipients=recipients)
    msg.html = render_template(
        "emails/task_assignment.html",
        user=user,
        task=task,
        task_url=task_url,
    )

    for doc in task.documents:
        _safe_attach(msg, doc.filename, doc.filetype, doc.data)

    current_app.logger.info(f"[email_utils] Sending assignment email to {recipients} for Task #{task.id}")
    try:
        mail.send(msg)
        current_app.logger.info(f"[email_utils] Assignment email sent successfully for Task #{task.id}")
    except Exception as e:
        current_app.logger.error(f"[email_utils] Failed to send assignment email for Task #{task.id}: {e}", exc_info=True)


# ──────────────────────────────────────────────────────────────────────────────
# Task completed
# ──────────────────────────────────────────────────────────────────────────────
def send_task_completion_email(assigner, task, new_documents=None):
    """
    `new_documents` is a list of dicts produced in task_routes.view_task, each
    dict having keys: filename / filetype / data.
    """
    subject    = f"✅ Task Completed — {task.title}"
    recipients = [assigner.employee_email]
    task_url   = url_for('task_routes.view_task', task_id=task.id, _external=True)

    msg = Message(subject=subject, recipients=recipients)
    msg.html = render_template(
        "emails/task_completion.html",
        assigner=assigner,
        task=task,
        task_url=task_url,
    )

    # 1) existing TaskDocument rows
    for doc in task.documents:
        _safe_attach(msg, doc.filename, doc.filetype, doc.data)

    # 2) any freshly-uploaded files (dicts)
    if new_documents:
        for doc in new_documents:
            _safe_attach(msg, doc["filename"], doc["filetype"], doc["data"])

    current_app.logger.info(f"[email_utils] Sending completion email to {recipients} for Task #{task.id}")
    try:
        mail.send(msg)
        current_app.logger.info(f"[email_utils] Completion email sent successfully for Task #{task.id}")
    except Exception as e:
        current_app.logger.error(f"[email_utils] Failed to send completion email for Task #{task.id}: {e}", exc_info=True)


# ──────────────────────────────────────────────────────────────────────────────
# Deadline reminder
# ──────────────────────────────────────────────────────────────────────────────
def send_deadline_reminder(task):
    subject    = f"⏰ Reminder: Task Deadline Approaching — {task.title}"
    # Send to all assignees + assigner
    recipients = [u.employee_email for u in task.assignees]
    recipients.append(task.assigned_by_user.employee_email)
    task_url   = url_for('task_routes.view_task', task_id=task.id, _external=True)

    msg = Message(subject=subject, recipients=recipients)
    msg.html = render_template(
        "emails/task_deadline_reminder.html",
        task=task,
        task_url=task_url,
    )

    for doc in task.documents:
        _safe_attach(msg, doc.filename, doc.filetype, doc.data)

    current_app.logger.info(f"[email_utils] Sending deadline reminder to {recipients} for Task #{task.id}")
    try:
        mail.send(msg)
        current_app.logger.info(f"[email_utils] Deadline reminder sent successfully for Task #{task.id}")
    except Exception as e:
        current_app.logger.error(f"[email_utils] Failed to send deadline reminder for Task #{task.id}: {e}", exc_info=True)


# ──────────────────────────────────────────────────────────────────────────────
# Periodic scan for soon-due tasks
# ──────────────────────────────────────────────────────────────────────────────
def check_and_send_deadline_notifications():
    """
    Every hour, find tasks due ≤ 24 h from *now* but still incomplete.
    """
    from extensions import scheduler

    app = scheduler.app
    with app.app_context():
        now = datetime.utcnow()
        soon = now + timedelta(hours=24)

        tasks = Task.query.filter(
            Task.due_date <= soon,
            Task.due_date > now,
            Task.status != 'Complete! Ready to Go!'
        ).all()

        current_app.logger.info(
            f"[email_utils] check_and_send_deadline_notifications → now={now}, soon={soon}, matched={len(tasks)} tasks"
        )
        for task in tasks:
            current_app.logger.info(
                f"[email_utils] → queueing reminder for Task #{task.id} (due={task.due_date}, status='{task.status}')"
            )
            try:
                send_deadline_reminder(task)
            except Exception as e:
                current_app.logger.error(
                    f"[email_utils] Exception in send_deadline_reminder for Task #{task.id}: {e}",
                    exc_info=True
                )
