# management_routes.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import date
from admin_routes import admin_required
import logging
from utils.tenant_utils import filter_by_user_tenant, user_tenant_id, tenant_category_names, tenant_levels_query
from utils.task_filters import assigned_to_user
from models import User, UserScore, SpecialExamRecord, Category, Level, Department, Task, UserProgress, db

management_routes = Blueprint('management_routes', __name__)


def calculate_work_experience(user):
    """
    Calculate approximate work experience (in years & months) 
    based on the user's join_date. Returns a string like '2 yr(s), 3 mo(s)'.
    """
    if not user.join_date:
        return "N/A"
    today = date.today()
    days_diff = (today - user.join_date).days  # user.join_date is a Date column
    years = days_diff // 365
    leftover_days = days_diff % 365
    months = leftover_days // 30
    return f"{years} yr(s), {months} mo(s)"


def average_score(scores):
    """
    Helper function to calculate average exam score for a user.
    If no scores, returns 0.
    """
    if not scores:
        return 0
    return round(sum(s.score for s in scores) / len(scores), 2)


@management_routes.route('/compare_users', methods=['GET', 'POST'])
@login_required
@admin_required
def compare_users():
    if request.method == 'POST':
        user1_id = request.form.get('user1')
        user2_id = request.form.get('user2')
        selected_level = request.form.get('level', type=int, default=1)

        if not user1_id or not user2_id:
            flash("Please select two users to compare.", "warning")
            return redirect(url_for('management_routes.compare_users'))

        if user1_id == user2_id:
            flash("Select two different users to compare.", "warning")
            return redirect(url_for('management_routes.compare_users'))

        user1 = User.query.get(user1_id)
        user2 = User.query.get(user2_id)

        if not user1 or not user2:
            flash("One or both selected users not found.", "danger")
            return redirect(url_for('management_routes.compare_users'))

        tid = user_tenant_id()
        if tid and (user1.tenant_id != tid or user2.tenant_id != tid):
            flash("You can only compare users within your organization.", "danger")
            return redirect(url_for('management_routes.compare_users'))

        # Calculate overall average score
        user1_scores = UserScore.query.filter_by(user_id=user1.id).all()
        user2_scores = UserScore.query.filter_by(user_id=user2.id).all()
        user1_avg = average_score(user1_scores)
        user2_avg = average_score(user2_scores)

        # Work experience
        user1_work_exp = calculate_work_experience(user1)
        user2_work_exp = calculate_work_experience(user2)

        # Departments (many-to-many)
        user1_departments = [d.name for d in user1.departments] if user1.departments else []
        user2_departments = [d.name for d in user2.departments] if user2.departments else []

        # Special Exam Records
        user1_sprec = SpecialExamRecord.query.filter_by(user_id=user1.id).first()
        user2_sprec = SpecialExamRecord.query.filter_by(user_id=user2.id).first()

        # Categories for Radar Chart
        categories = tenant_category_names(current_user) or ["General"]
        performance_labels = []
        user1_cat_scores = []
        user2_cat_scores = []

        for name in categories:
            performance_labels.append(name)
            cat = Category.query.filter_by(name=name, tenant_id=tid).first()

            for user, scores_list in [(user1, user1_cat_scores), (user2, user2_cat_scores)]:
                if cat:
                    scores = UserScore.query.filter_by(
                        user_id=user.id,
                        category_id=cat.id,
                        level_id=selected_level
                    ).all()
                    avg_score = sum(s.score for s in scores) / len(scores) if scores else 0
                    scores_list.append(round(avg_score, 2))
                else:
                    scores_list.append(0)

        levels = tenant_levels_query().order_by(Level.level_number).all()

        def _avg_trust(uid):
            scores = UserScore.query.filter_by(user_id=uid).all()
            trusts = [s.trust_score for s in scores if getattr(s, 'trust_score', None) is not None]
            return round(sum(trusts) / len(trusts), 1) if trusts else 0

        def _task_counts(uid):
            assigned = Task.query.filter(assigned_to_user(uid)).all()
            active = sum(1 for t in assigned if (t.progress or 0) < 100)
            done = sum(1 for t in assigned if (t.progress or 0) >= 100)
            return active, done

        def _completed_courses(uid):
            return UserProgress.query.filter_by(user_id=uid, completed=True).count()

        u1_active, u1_done = _task_counts(user1.id)
        u2_active, u2_done = _task_counts(user2.id)

        strengths = []
        for i, label in enumerate(performance_labels):
            s1, s2 = user1_cat_scores[i], user2_cat_scores[i]
            diff = round(s1 - s2, 1)
            if abs(diff) >= 5:
                if diff > 0:
                    strengths.append(f"{user1.first_name} exceeds {user2.first_name} in {label} by +{diff}%")
                else:
                    strengths.append(f"{user2.first_name} exceeds {user1.first_name} in {label} by +{abs(diff)}%")

        return render_template(
            'compare_users.html',
            user1=user1,
            user2=user2,
            user1_avg=user1_avg,
            user2_avg=user2_avg,
            user1_work_exp=user1_work_exp,
            user2_work_exp=user2_work_exp,
            user1_sprec=user1_sprec,
            user2_sprec=user2_sprec,
            user1_departments=user1_departments,
            user2_departments=user2_departments,
            performance_labels=performance_labels,
            user1_scores=user1_cat_scores,
            user2_scores=user2_cat_scores,
            levels=levels,
            selected_level=selected_level,
            user1_level=user1.get_current_level(),
            user2_level=user2.get_current_level(),
            user1_courses_done=_completed_courses(user1.id),
            user2_courses_done=_completed_courses(user2.id),
            user1_tasks_active=u1_active,
            user1_tasks_done=u1_done,
            user2_tasks_active=u2_active,
            user2_tasks_done=u2_done,
            user1_trust=_avg_trust(user1.id),
            user2_trust=_avg_trust(user2.id),
            strengths=strengths,
        )

    else:
        users = filter_by_user_tenant(User.query, User).all()
        levels = tenant_levels_query().order_by(Level.level_number).all()
        return render_template('compare_users_form.html', users=users, levels=levels)