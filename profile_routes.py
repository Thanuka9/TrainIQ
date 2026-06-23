from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, abort, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import User, Designation, Event, Department, Client, UserScore, Category, Level, Role
from utils.tenant_utils import (
    filter_by_user_tenant,
    tenant_departments_query,
    tenant_clients_query,
    tenant_designations_query,
    assert_user_in_tenant,
    user_tenant_id,
)
from utils.profile_utils import performance_for_level, tenant_levels_for_user
from mongodb_operations import get_profile_picture, save_profile_picture, delete_profile_picture
from io import BytesIO
from datetime import datetime
import imghdr
import logging

profile_routes = Blueprint('profile_routes', __name__)

@profile_routes.route('/')
@login_required
def profile():
    """
    Display the profile page of the current user, including calendar events and performance graphs.
    Performance data is filtered by the selected exam level.
    """
    # Fetch user events
    calendar_events = Event.query.filter_by(user_id=current_user.id).all()

    # Get designation title (if available)
    designation_title = current_user.designation.title if current_user.designation else "Not Assigned"

    # Fetch user's profile picture from MongoDB
    profile_picture = get_profile_picture(current_user.id)

    # Use the department relationship
    user_departments = current_user.departments if current_user.departments else []


    # --- Determine selected exam level ---
    try:
        selected_level = int(request.args.get('level', 1))
    except ValueError:
        selected_level = 1

    # --- Compute Performance Data ---
    performance_labels, user_performance, overall_performance = performance_for_level(
        current_user, selected_level
    )

    levels = tenant_levels_for_user(current_user)

    return render_template(
        'profile.html',
        user=current_user,
        calendar_events=calendar_events,
        designation_title=designation_title,
        profile_picture=profile_picture,
        user_departments=user_departments,
        performance_labels=performance_labels,
        user_performance=user_performance,
        average_performance=overall_performance,
        levels=levels,
        selected_level=selected_level
    )


@profile_routes.route('/performance_data')
@login_required
def performance_data():
    """JSON endpoint for profile chart — avoids full page reload on level change."""
    try:
        level_number = int(request.args.get('level', 1))
    except ValueError:
        level_number = 1
    labels, user_perf, avg_perf = performance_for_level(current_user, level_number)
    user_avg = round(sum(user_perf) / len(user_perf), 1) if user_perf else 0
    org_avg = round(sum(avg_perf) / len(avg_perf), 1) if avg_perf else 0
    best_idx = user_perf.index(max(user_perf)) if user_perf and max(user_perf) > 0 else None
    return jsonify({
        'labels': labels,
        'user_performance': user_perf,
        'average_performance': avg_perf,
        'level': level_number,
        'user_avg': user_avg,
        'org_avg': org_avg,
        'delta': round(user_avg - org_avg, 1),
        'best_category': labels[best_idx] if best_idx is not None else None,
        'best_score': user_perf[best_idx] if best_idx is not None else 0,
    })

@profile_routes.route('/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    """
    Allow users to edit their profile information, including profile picture,
    department, designation, and clients.
    """
    user = current_user
    can_edit_org = user.is_super_admin or any(r.name in ('admin', 'super_admin') for r in (user.roles or []))

    if request.method == 'POST':
        try:
            user.first_name     = request.form.get('first_name', user.first_name)
            user.last_name      = request.form.get('last_name', user.last_name)
            user.employee_email = request.form.get('employee_email', user.employee_email)
            user.employee_id    = request.form.get('employee_id', user.employee_id)
            user.phone_number   = request.form.get('phone_number', user.phone_number)

            if can_edit_org:
                dept_ids = request.form.getlist('departments', type=int)
                user.departments = (
                    tenant_departments_query().filter(Department.id.in_(dept_ids)).all()
                    if dept_ids else []
                )
                desig_id = request.form.get('designation_id', type=int)
                if desig_id:
                    desig = tenant_designations_query().filter_by(id=desig_id).first()
                    if desig:
                        user.designation = desig
                client_ids = request.form.getlist('clients', type=int)
                user.clients = (
                    tenant_clients_query().filter(Client.id.in_(client_ids)).all()
                    if client_ids else []
                )

            # Handle profile picture upload
            if 'profile_picture' in request.files:
                file = request.files['profile_picture']
                if file and file.filename:
                    data = file.read()
                    if len(data) > 5 * 1024 * 1024:
                        flash("Profile picture size exceeds the 5MB limit.", "danger")
                        return redirect(url_for('profile_routes.edit_profile'))
                    ext = (file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else '')
                    if ext not in ('jpg', 'jpeg', 'png'):
                        flash("Only JPEG and PNG images are allowed.", "danger")
                        return redirect(url_for('profile_routes.edit_profile'))
                    from models import Tenant
                    from utils.tenant_storage import assert_storage_allowed, invalidate_tenant_storage_cache

                    tenant = current_user.tenant or Tenant.query.get(user_tenant_id())
                    if tenant and not assert_storage_allowed(tenant, len(data)):
                        return redirect(url_for('profile_routes.edit_profile'))
                    save_profile_picture(user.id, data)
                    if tenant:
                        invalidate_tenant_storage_cache(tenant.id)

            db.session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('profile_routes.profile'))

        except Exception as e:
            db.session.rollback()
            logging.exception("Profile update failed for user %s", current_user.id)
            flash("Could not save your profile. Please try again or contact support.", 'danger')
            return redirect(url_for('profile_routes.edit_profile'))

    # GET request: fetch lists for dropdowns
    designations = tenant_designations_query().order_by(Designation.title).all()
    departments  = tenant_departments_query().order_by(Department.name).all()
    clients      = tenant_clients_query().order_by(Client.name).all()
    profile_picture = get_profile_picture(user.id)
    return render_template(
        'edit_profile.html',
        user=user,
        designations=designations,
        departments=departments,
        clients=clients,
        can_edit_org=can_edit_org,
        profile_picture=profile_picture,
    )


@profile_routes.route('/delete_picture', methods=['POST'])
@login_required
def delete_profile_picture_handler():
    """
    Allow users to delete their profile picture.
    """
    try:
        result = delete_profile_picture(current_user.id)
        if result.get('status') == 'deleted':
            flash("Profile picture deleted successfully!", "success")
        else:
            flash(result.get('message', "Error deleting profile picture"), "info")
    except Exception as e:
        logging.exception("Profile picture delete failed for user %s", current_user.id)
        flash("Could not delete profile picture. Please try again.", "danger")
    return redirect(url_for('profile_routes.profile'))

@profile_routes.route('/add_event', methods=['POST'])
@login_required
def add_event():
    """
    Allow users to add new events to their calendar.
    """
    title = request.form['event_title']
    description = request.form['event_description']
    event_date = request.form['event_date']

    new_event = Event(title=title, description=description, date=event_date, user_id=current_user.id)
    db.session.add(new_event)
    db.session.commit()
    flash("Event added successfully!", "success")
    return redirect(url_for('profile_routes.profile'))

@profile_routes.route('/edit_event/<int:event_id>', methods=['POST'])
def edit_event(event_id):
    event = Event.query.get_or_404(event_id)
    if event.user_id != current_user.id:
        flash("Unauthorized action.", "danger")
        return redirect(url_for('profile_routes.profile'))

    event.title = request.form['event_title']
    event.description = request.form['event_description']
    
    # Safely parse the date string
    date_str = request.form['event_date']  # e.g. '2025-04-18' or maybe '04/18/2025'
    try:
        # If your <input type="date"> uses yyyy-mm-dd, use '%Y-%m-%d'
        event.date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        # If you expect mm/dd/yyyy, use '%m/%d/%Y' instead
        try:
            event.date = datetime.strptime(date_str, '%m/%d/%Y').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD or adjust your date field.", "danger")
            return redirect(url_for('profile_routes.profile'))

    db.session.commit()
    flash("Event updated successfully!", "success")
    return redirect(url_for('profile_routes.profile'))

@profile_routes.route('/delete_event/<int:event_id>', methods=['POST'])
@login_required
def delete_event(event_id):
    """
    Allow users to delete an event from their calendar.
    """
    event = Event.query.get_or_404(event_id)
    if event.user_id != current_user.id:
        flash("Unauthorized action.", "danger")
        return redirect(url_for('profile_routes.profile'))

    db.session.delete(event)
    db.session.commit()
    flash("Event deleted successfully!", "success")
    return redirect(url_for('profile_routes.profile'))

@profile_routes.route('/profile_picture/<int:user_id>')
@login_required
def serve_profile_picture(user_id):
    """Serve profile picture — self, super admin, or same-tenant users only."""
    target = User.query.get_or_404(user_id)
    if target.id != current_user.id and not current_user.is_super_admin:
        assert_user_in_tenant(target)
    try:
        profile_picture = get_profile_picture(user_id)
        if profile_picture:
            return send_file(BytesIO(profile_picture), mimetype='image/jpeg')
        abort(404)
    except Exception as e:
        logging.error(f"Error serving profile picture for user {user_id}: {e}")
        flash("Error retrieving profile picture.", "danger")
        return redirect(url_for('profile_routes.profile'))
