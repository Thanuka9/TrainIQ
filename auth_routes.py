from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, jsonify
)
from flask_login import login_user, logout_user, login_required, current_user
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, timedelta
import logging
from audit import log_event
from extensions import db, mail
from models import (
    User, Department, Designation, Client, Role,
    log_failed_login_attempt, PasswordResetRequest
)
from models import FailedLogin
import os

from utils.logging_utils import mask_email
from utils.tenant_utils import (
    normalize_office_key,
    domain_matches_allowed,
    is_trainiq_staff,
    set_active_tenant_session,
)

auth_routes = Blueprint('auth_routes', __name__)

def _dev_only(msg):
    if os.getenv('FLASK_ENV', 'development') == 'development':
        logging.info(msg)


def _send_2fa_email(user):
    """Generate 2FA code, persist, and email the user."""
    user.generate_2fa_code()
    msg = Message(
        subject="Your 2FA Code",
        recipients=[user.employee_email],
    )
    msg.body = f"Your code is {user.two_fa_code}. It expires in 5 minutes."
    msg.html = render_template(
        'emails/two_factor_email.html',
        user=user,
        code=user.two_fa_code,
    )
    try:
        mail.send(msg)
    except Exception as e:
        logging.error(f"Failed to send 2FA email: {e}")
        _dev_only(f"[DEV] 2FA Code for {user.employee_email}: {user.two_fa_code}")


def _redirect_after_login(user):
    """Post-login destination — trial billing, platform CEO, or user dashboard."""
    from flask import session
    from utils.billing_plans import is_trial_expired
    from utils.platform_ceo import TRAINIQ_PLATFORM_OFFICE_KEY
    from utils.tenant_utils import is_trainiq_staff

    org = user.tenant
    trial_ended = bool(
        org
        and (
            is_trial_expired(org)
            or (getattr(org, "status", "") or "").lower() == "expired"
        )
    )
    if trial_ended and user.is_super_admin and not is_trainiq_staff(user):
        flash(
            "Your free trial has ended. Upgrade your plan in Billing to restore team access.",
            "warning",
        )
        return redirect(url_for("billing_routes.billing_home"))

    if session.get("platform_support") and is_trainiq_staff(user):
        flash(
            f"Support mode: viewing {session.get('tenant_name', 'customer organization')}.",
            "info",
        )
        return redirect(url_for("admin_routes.admin_dashboard"))

    if is_trainiq_staff(user):
        home_key = (getattr(org, "office_key", "") or "").upper()
        if home_key == TRAINIQ_PLATFORM_OFFICE_KEY.upper():
            return redirect(url_for("platform_routes.platform_dashboard"))

    return redirect(url_for("general_routes.dashboard"))

# Serializer for email-based tokens
s = URLSafeTimedSerializer(os.getenv("SECRET_KEY", "fallback-secret"))

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

MAX_FAILED_ATTEMPTS = 3

@auth_routes.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('general_routes.dashboard'))

    if request.method == 'POST':
        # 1. Extract form fields
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        employee_email = request.form.get('employee_email')
        password = request.form.get('password')
        company_name = request.form.get('company_name', '').strip()

        if not all([first_name, last_name, employee_email, password, company_name]):
            flash("All fields are required.", "error")
            return redirect(url_for('auth_routes.register'))

        # Captcha validation
        user_captcha = request.form.get('captchaAnswer')
        session_captcha = session.get('captcha_answer')
        if not session_captcha or str(user_captcha).strip() != str(session_captcha):
            flash("Security check answer is incorrect. Please try again.", "error")
            return redirect(url_for('auth_routes.register'))

        # Password complexity validation
        import re
        password_pattern = re.compile(r'^(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$')
        if not password_pattern.match(password):
            flash("Password must be at least 8 characters and contain 1 uppercase letter, 1 symbol, and 1 number.", "error")
            return redirect(url_for('auth_routes.register'))

        # Duplication check
        if User.query.filter_by(employee_email=employee_email).first():
            flash("Email already registered.", "error")
            return redirect(url_for('auth_routes.register'))

        # 2. Lookup Tenant by email domain
        email_domain = employee_email.split('@')[-1].lower()
        from models import Tenant
        matched_tenant = None
        for tenant in Tenant.query.filter(Tenant.allowed_domain.isnot(None)).all():
            if domain_matches_allowed(employee_email, tenant.allowed_domain):
                matched_tenant = tenant
                break

        is_new_tenant = False
        generated_office_key = None
        if not matched_tenant:
            from utils.tenant_utils import generate_office_key
            generated_office_key = generate_office_key()
            while Tenant.query.filter_by(office_key=generated_office_key).first():
                generated_office_key = generate_office_key()
            matched_tenant = Tenant(
                name=company_name,
                allowed_domain=email_domain,
                office_key=generated_office_key.upper(),
            )
            from utils.billing_plans import apply_trial_to_tenant
            apply_trial_to_tenant(matched_tenant)
            db.session.add(matched_tenant)
            db.session.flush() # Populate matched_tenant.id
            is_new_tenant = True

        # 3. Create user linked to their Tenant
        import uuid
        from datetime import datetime
        employee_prefix = "ADM" if is_new_tenant else "EMP"
        employee_id = f"{employee_prefix}-{uuid.uuid4().hex[:6].upper()}"

        token = s.dumps(employee_email, salt='email-confirmation')

        new_user = User(
            first_name=first_name,
            last_name=last_name,
            employee_email=employee_email,
            employee_id=employee_id,
            join_date=datetime.utcnow().date(),
            is_verified=True if is_new_tenant else False, # Auto-verify if they are creating a new company
            verification_token=token,
            tenant_id=matched_tenant.id
        )
        new_user.set_password(password)
        db.session.add(new_user)

        # 4. If new tenant, assign admin / super_admin roles and a default client
        from models import Role, Client
        if is_new_tenant:
            new_user.is_super_admin = True
            
            # Assign admin and super_admin roles
            super_admin_role = Role.query.filter_by(name='super_admin').first()
            admin_role = Role.query.filter_by(name='admin').first()
            if super_admin_role:
                new_user.roles.append(super_admin_role)
            if admin_role:
                new_user.roles.append(admin_role)
                
            # Create a default client for this new company
            default_client_name = f"{company_name} Client"
            client = Client.query.filter_by(name=default_client_name, tenant_id=matched_tenant.id).first()
            if not client:
                client = Client(name=default_client_name, tenant_id=matched_tenant.id)
                db.session.add(client)
            elif client.tenant_id != matched_tenant.id:
                flash("Client name conflict. Contact support.", "error")
                db.session.rollback()
                return redirect(url_for('auth_routes.register'))
            new_user.clients.append(client)
            from utils.tenant_seeds import seed_tenant_catalog
            seed_tenant_catalog(matched_tenant.id)
        else:
            # Standard member role for existing tenant join
            from utils.tenant_limits import assert_tenant_can_register
            if getattr(matched_tenant, 'enable_invite_only', False):
                flash(
                    "This organization is invite-only. Use the link from your invitation email to join.",
                    "error",
                )
                return redirect(url_for('auth_routes.login'))
            if not assert_tenant_can_register(matched_tenant):
                return redirect(url_for('auth_routes.login'))
            member_role = Role.query.filter_by(name='member').first()
            if member_role:
                new_user.roles.append(member_role)

        # 5. Commit everything
        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            logging.error(f"Database error during registration: {e}")
            flash("Registration error. Please try again.", "error")
            return redirect(url_for('auth_routes.register'))

        # 6. Send verification email only if they need verification (existing tenant join)
        if not is_new_tenant:
            verify_url = url_for('auth_routes.verify_email', token=token, _external=True)
            msg = Message(
                subject="Verify Your Email",
                recipients=[employee_email]
            )
            msg.body = f"Please verify your email by clicking the link:\n\n{verify_url}"
            msg.html = render_template('emails/verification_email.html', user=new_user, verify_url=verify_url)
            try:
                mail.send(msg)
            except Exception as e:
                logging.error(f"Failed to send verification email: {e}")
                _dev_only(f"[DEV] Verification Link: {verify_url}")
            flash("Registration successful! Check your email to verify.", "success")
            return redirect(url_for('auth_routes.login'))
        else:
            # If new tenant, log in immediately
            from flask_login import login_user
            from utils.mongo_tenant import provision_tenant_mongo

            provision_tenant_mongo(matched_tenant.id)
            login_user(new_user)
            session['tenant_name'] = company_name
            session['tenant_id'] = matched_tenant.id
            key_msg = f" Your Office Key is: {generated_office_key}. Save it — you'll need it to sign in."
            flash(f"Welcome to TrainIQ! Your organization '{company_name}' has been created successfully.{key_msg}", "success")
            return redirect(url_for('general_routes.dashboard'))

    import random
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    session['captcha_a'] = a
    session['captcha_b'] = b
    session['captcha_answer'] = a + b
    return render_template('register.html')


@auth_routes.route('/invite/<token>', methods=['GET', 'POST'])
def accept_invite(token):
    """Magic-link invite acceptance — creates account then routes through 2FA."""
    from models import Tenant, Role
    from utils.tenant_invites import get_valid_invite, mark_invite_used
    from utils.tenant_limits import assert_tenant_can_register
    import re
    import uuid

    invite = get_valid_invite(token)
    if not invite:
        flash("This invitation link is invalid or has expired.", "error")
        return redirect(url_for('auth_routes.login'))

    tenant = Tenant.query.get(invite.tenant_id)
    if not tenant:
        flash("Organization not found.", "error")
        return redirect(url_for('auth_routes.login'))

    if request.method == 'POST':
        first_name = (request.form.get('first_name') or '').strip()
        last_name = (request.form.get('last_name') or '').strip()
        employee_email = (request.form.get('employee_email') or '').strip().lower()
        password = request.form.get('password')

        if employee_email != invite.email.lower():
            flash("Email does not match this invitation.", "error")
            return redirect(url_for('auth_routes.accept_invite', token=token))

        if not all([first_name, last_name, employee_email, password]):
            flash("All fields are required.", "error")
            return redirect(url_for('auth_routes.accept_invite', token=token))

        password_pattern = re.compile(r'^(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$')
        if not password_pattern.match(password):
            flash("Password must be at least 8 characters and contain 1 uppercase letter, 1 symbol, and 1 number.", "error")
            return redirect(url_for('auth_routes.accept_invite', token=token))

        if User.query.filter_by(employee_email=employee_email).first():
            flash("An account with this email already exists. Please log in.", "error")
            return redirect(url_for('auth_routes.login'))

        if not assert_tenant_can_register(tenant):
            return redirect(url_for('auth_routes.login'))

        new_user = User(
            first_name=first_name,
            last_name=last_name,
            employee_email=employee_email,
            employee_id=f"EMP-{uuid.uuid4().hex[:6].upper()}",
            join_date=datetime.utcnow().date(),
            is_verified=True,
            tenant_id=tenant.id,
        )
        new_user.set_password(password)
        member_role = Role.query.filter_by(name='member').first()
        if member_role:
            new_user.roles.append(member_role)
        db.session.add(new_user)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            logging.error(f"Invite acceptance DB error: {e}")
            flash("Could not create account. Please try again.", "error")
            return redirect(url_for('auth_routes.accept_invite', token=token))

        mark_invite_used(invite, new_user.id)

        session['user_id'] = new_user.id
        session['is_super_admin'] = False
        session['role_id'] = new_user.roles[0].id if new_user.roles else None
        session['designation_id'] = new_user.designation_id
        set_active_tenant_session(tenant, platform_support=False)
        session.permanent = True

        try:
            _send_2fa_email(new_user)
        except SQLAlchemyError as e:
            db.session.rollback()
            logging.error(f"2FA setup after invite failed: {e}")
            flash("Account created but verification failed. Try logging in.", "error")
            return redirect(url_for('auth_routes.login'))

        flash("Account created! Enter the 2FA code sent to your email.", "info")
        return redirect(url_for('auth_routes.verify_2fa'))

    return render_template('accept_invite.html', invite=invite, tenant=tenant, token=token)


@auth_routes.route('/verify/<token>')
def verify_email(token):
    try:
        # 1) Decode the token to get back the original email
        email = s.loads(token, salt='email-confirmation', max_age=60*60*24)
    except SignatureExpired:
        flash("That verification link has expired.", "error")
        return redirect(url_for('auth_routes.login'))
    except BadSignature:
        flash("Invalid verification link.", "error")
        return redirect(url_for('auth_routes.login'))

    # 2) Look up the user record by email
    user = User.query.filter_by(employee_email=email).first()
    if not user:
        flash("Invalid verification link.", "error")
        return redirect(url_for('auth_routes.login'))

    # 3) If the user exists, check if they’re already verified
    if user.is_verified:
        flash("Your email is already verified.", "info")
    else:
        user.is_verified = True
        user.verification_token = None
        try:
            db.session.commit()
            flash("Email verified! You can now log in.", "success")
        except SQLAlchemyError as e:
            db.session.rollback()
            logging.error(f"Database error during email verification: {e}")
            flash("Could not verify email. Please try again or contact support.", "error")

    return redirect(url_for('auth_routes.login'))

@auth_routes.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        office_key = normalize_office_key(request.form.get('office_key'))
        email = request.form.get('employee_email')
        pwd   = request.form.get('password')

        if not office_key:
            flash("Office Key is required.", "error")
            return redirect(url_for('auth_routes.login'))

        from models import Tenant
        tenant = Tenant.query.filter_by(office_key=office_key).first()
        if not tenant:
            flash("Invalid Office Key.", "error")
            return redirect(url_for('auth_routes.login'))

        from utils.tenant_limits import tenant_is_active, trial_expired_message
        from utils.billing_plans import is_trial_expired
        user  = User.query.filter_by(employee_email=email).first()

        org = user.tenant if user and user.tenant else tenant
        trial_ended = is_trial_expired(org) or (getattr(org, 'status', '') or '').lower() == 'expired'
        if trial_ended and user and not user.is_super_admin and not is_trainiq_staff(user):
            flash(trial_expired_message(org), "error")
            return redirect(url_for('auth_routes.login'))

        if not tenant_is_active(tenant) and not (user and is_trainiq_staff(user)):
            if trial_ended and user and user.is_super_admin:
                pass
            else:
                flash("This organization account is suspended. Contact your administrator.", "error")
                return redirect(url_for('auth_routes.login'))

        platform_login = user and is_trainiq_staff(user) and user.tenant_id != tenant.id

        if user and user.tenant_id != tenant.id and not platform_login:
            flash("Invalid email or password.", "error")
            log_event('FAILED_LOGIN', user=None, email=email)
            return redirect(url_for('auth_routes.login'))

        if user and user.tenant_id is None and not platform_login:
            user.tenant_id = tenant.id
            db.session.commit()

        # 1) Locked‐out users
        if user and user.is_locked:
            flash(
                "Your account has been locked due to too many failed login attempts. "
                "Please use Forgot Password to reset.",
                "error"
            )
            return redirect(url_for('auth_routes.login'))

        # 2) Correct password path
        if user and user.check_password(pwd):
            # ─── Audit: successful login ─────────────────────────────
            log_event('USER_LOGIN', user=user)

            # reset counters & 2FA
            user.failed_login_count = 0
            user.is_locked          = False
            user.locked_at          = None
            db.session.commit()

            if not user.is_verified:
                flash("Account not verified. Contact support.", "error")
                return redirect(url_for('auth_routes.login'))

            # put user info into session
            session['user_id']          = user.id
            session['is_super_admin']   = user.is_super_admin
            session['role_id']          = user.roles[0].id if user.roles else None
            session['designation_id']   = user.designation_id
            if platform_login:
                set_active_tenant_session(tenant, platform_support=True)
                session['is_super_admin'] = True
            else:
                set_active_tenant_session(user.tenant or tenant, platform_support=False)
            session['tenant_name']      = session.get('tenant_name') or (user.tenant.name if user.tenant else tenant.name)
            # ← Make this a permanent session (uses PERMANENT_SESSION_LIFETIME)
            session.permanent = True

            # check if 2FA is enabled for the tenant
            enable_2fa = False
            if user.tenant and user.tenant.enable_2fa:
                enable_2fa = True
            
            if enable_2fa:
                try:
                    _send_2fa_email(user)
                except SQLAlchemyError as e:
                    db.session.rollback()
                    logging.error(f"DB error during 2FA setup: {e}")
                    flash("Server error. Please try again.", "error")
                    return redirect(url_for('auth_routes.login'))

                flash("2FA code sent. Please verify.", "info")
                return redirect(url_for('auth_routes.verify_2fa'))
            else:
                login_user(user)
                logging.info(f"User {user.id} logged in without 2FA (disabled for tenant) from {request.remote_addr}")
                return _redirect_after_login(user)

        # 3) Invalid credentials
        if user:
            user.failed_login_count += 1
            if user.failed_login_count >= MAX_FAILED_ATTEMPTS:
                user.is_locked  = True
                user.locked_at  = datetime.utcnow()
                flash("Too many failed attempts. Your account has been locked.", "error")
            else:
                flash("Invalid email or password.", "error")

            db.session.commit()

            # ─── Audit: failed login with known email ───────────────
            log_event(
                'FAILED_LOGIN',
                user=None,
                email=user.employee_email
            )
        else:
            flash("Invalid email or password.", "error")

            # ─── Audit: failed login with unknown email ─────────────
            log_event(
                'FAILED_LOGIN',
                user=None,
                email=email
            )

        logging.warning(f"Failed login for {mask_email(email)} from {request.remote_addr}")
        return redirect(url_for('auth_routes.login'))

    # GET -> just render the form
    return render_template('login.html')


@auth_routes.route('/verify_2fa', methods=['GET', 'POST'])
def verify_2fa():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth_routes.login'))

    user = User.query.get(user_id)
    now = datetime.utcnow()

    # On GET: if there’s no valid code or it’s already expired, let the user know
    if request.method == 'GET':
        if not user.two_fa_code or not user.two_fa_expiration or user.two_fa_expiration <= now:
            flash("Your 2FA code has expired. Please click “Resend Code” to get a new one.", "warning")

    # Initialize (or preserve) a counter for failed 2FA attempts in this session
    if '2fa_attempts' not in session:
        session['2fa_attempts'] = 0

    if request.method == 'POST':
        code = request.form.get('2fa_code')
        session['2fa_attempts'] += 1

        # If the user tries more than 5 times, force them to log in again
        if session['2fa_attempts'] > 5:
            session.pop('2fa_attempts', None)
            session.pop('user_id', None)
            flash("Too many failed attempts. Please log in again.", "error")
            logging.warning(f"User {user_id} exceeded 2FA attempts from {request.remote_addr}")
            return redirect(url_for('auth_routes.login'))

        # Check submitted code against what’s in the database and ensure it hasn't expired
        if (
            code
            and user.two_fa_code == code
            and user.two_fa_expiration
            and user.two_fa_expiration > now
        ):
            # ✅ Correct code: clear it out, commit, then log in the user
            user.two_fa_code = None
            user.two_fa_expiration = None

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                logging.error(f"Database error clearing 2FA code: {e}")
                flash("Server error. Please try again.", "error")
                return redirect(url_for('auth_routes.login'))

            session.pop('2fa_attempts', None)
            login_user(user)
            # ensure tenant is in session
            session['tenant_name']      = user.tenant.name if user.tenant else "TrainIQ"
            session['tenant_id']        = user.tenant_id
            # ← ensure this session uses the 3-hour permanent cookie
            session.permanent = True

            logging.info(f"User {user.id} passed 2FA from {request.remote_addr}")
            return _redirect_after_login(user)

        # ❌ Invalid or expired code
        flash("Invalid or expired 2FA code.", "error")
        logging.warning(f"Invalid 2FA attempt for user {user.id} from {request.remote_addr}")
        return redirect(url_for('auth_routes.verify_2fa'))

    return render_template('verify_2fa.html')


@auth_routes.route('/resend_2fa')
def resend_2fa():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('auth_routes.login'))

    user = User.query.get(user_id)
    now = datetime.utcnow()

    # If there’s still a valid (non-expired) code, enforce a 30s “cooldown” before regenerating
    if user.two_fa_expiration and user.two_fa_expiration > now:
        # generation_timestamp = (expiration_timestamp - 5 minutes)
        gen_time = user.two_fa_expiration - timedelta(minutes=5)
        allowed_time = gen_time + timedelta(seconds=30)

        if now < allowed_time:
            wait_seconds = int((allowed_time - now).total_seconds())
            flash(f"Please wait {wait_seconds}s before requesting a new code.", "error")
            return redirect(url_for('auth_routes.verify_2fa'))

    # Generate a fresh 2FA code (assumes User.generate_2fa_code() sets two_fa_code and two_fa_expiration = now + 5m)
    user.generate_2fa_code()
    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        logging.error(f"Database error during 2FA resend: {e}")
        flash("Server error. Please try again.", "error")
        return redirect(url_for('auth_routes.login'))

    # Email the new code
    msg = Message(
        subject="Your 2FA Code",
        recipients=[user.employee_email]
    )
    msg.body = f"Your code is {user.two_fa_code}. It expires in 5 minutes."
    msg.html = render_template(
        'emails/two_factor_email.html',
        user=user,
        code=user.two_fa_code
    )
    try:
        mail.send(msg)
    except Exception as e:
        logging.error(f"Failed to send 2FA email: {e}")
        _dev_only(f"[DEV] 2FA Code for {user.employee_email}: {user.two_fa_code}")

    flash("New 2FA code sent.", "info")
    return redirect(url_for('auth_routes.verify_2fa'))

@auth_routes.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['employee_email']
        user = User.query.filter_by(employee_email=email).first()
        if not user:
            flash("Email not found.", "error")
            return redirect(url_for('auth_routes.login'))

        # 1) generate the token & expiry
        token = s.dumps(email, salt='password-reset-salt')
        expires_at = datetime.utcnow() + timedelta(hours=1)

        # 2) record it in PasswordResetRequest table
        pr = PasswordResetRequest(
            user_id=user.id,
            token=token,
            expires_at=expires_at
        )
        db.session.add(pr)

        # (optional) still keep it on the User for quick lookup
        user.password_reset_token = token
        user.password_reset_expiration = expires_at

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            logging.error(f"Database error during forgot password: {e}")
            flash("Server error. Please try again.", "error")
            return redirect(url_for('auth_routes.login'))

        # 3) send the email
        reset_url = url_for('auth_routes.reset_password', token=token, _external=True)
        msg = Message(subject='Password Reset', recipients=[email])
        msg.body = f'Reset your password using this link: {reset_url}'
        msg.html = render_template(
            'emails/password_reset_email.html',
            user=user,
            reset_url=reset_url
        )
        try:
            mail.send(msg)
        except Exception as e:
            logging.error(f"Failed to send forgot password email: {e}")
            _dev_only(f"[DEV] Reset Link: {reset_url}")

        flash("Check your email for the reset link.", "info")
        return redirect(url_for('auth_routes.login'))

    return render_template('forgot_password.html')


@auth_routes.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    # 1) verify signature & max_age
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except (SignatureExpired, BadSignature):
        flash("That link is invalid or has expired.", "error")
        return redirect(url_for('auth_routes.forgot_password'))

    # 2) load your request record and check expiry
    pr = PasswordResetRequest.query.filter_by(token=token).first()
    if not pr or pr.expires_at < datetime.utcnow():
        flash("Invalid or expired reset link.", "error")
        return redirect(url_for('auth_routes.forgot_password'))

    user = User.query.get(pr.user_id)

    if request.method == 'POST':
        pw1 = request.form['new_password']
        pw2 = request.form['confirm_password']

        if not pw1 or not pw2:
            flash("Password fields cannot be empty.", "error")
            return render_template('reset_password.html', token=token)

        if pw1 != pw2:
            flash("Passwords do not match.", "error")
            return render_template('reset_password.html', token=token)

        if len(pw1) < 8:
            flash("Password must be at least 8 characters.", "error")
            return render_template('reset_password.html', token=token)

        # all good → set new password and clean up
        user.set_password(pw1)
        db.session.delete(pr)
        user.password_reset_token = None
        user.password_reset_expiration = None

        try:
            db.session.commit()
            flash("Password has been reset! You can now log in.", "success")
            return redirect(url_for('auth_routes.login'))
        except SQLAlchemyError as e:
            db.session.rollback()
            logging.error(f"Database error during password reset: {e}")
            flash("Could not reset password. Please try again.", "error")
            return render_template('reset_password.html', token=token)

    # on GET (or after any POST flash), render with token
    return render_template('reset_password.html', token=token)

# ─── Alias routes for hyphens ─────────────────────────────────────────

@auth_routes.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password_dash():
    return forgot_password()

@auth_routes.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_dash(token):
    return reset_password(token)


# ─── Catch-all 404 inside /auth → redirect to login ────────────────────

@auth_routes.errorhandler(404)     # <-- use errorhandler, not app_errorhandler
def auth_404(e):
    return redirect(url_for('auth_routes.login'))

@auth_routes.route('/logout')
@login_required
def logout():
    user_id = current_user.get_id()
    logout_user()
    session.clear()
    logging.info(f"User {user_id} logged out from {request.remote_addr}")
    flash("You have been logged out successfully.", "success")
    return redirect(url_for('auth_routes.login'))


def log_failed_login_attempt(email):
    ip = request.remote_addr
    ua = request.headers.get('User-Agent')
    fl = FailedLogin(
        email=email,
        ip_address=ip,
        user_agent=ua,
        timestamp=datetime.utcnow()
    )
    db.session.add(fl)
    db.session.commit()


@auth_routes.route('/resend-verification', methods=['GET', 'POST'])
@auth_routes.route('/resend_verification', methods=['GET', 'POST'])
def resend_verification():
    if current_user.is_authenticated:
        return redirect(url_for('general_routes.dashboard'))
        
    if request.method == 'POST':
        email = request.form.get('employee_email')
        user = User.query.filter_by(employee_email=email).first()
        if user:
            if user.is_verified:
                flash("Email already verified. Please sign in.", "info")
                return redirect(url_for('auth_routes.login'))
                
            token = s.dumps(email, salt='email-confirmation')
            user.verification_token = token
            db.session.commit()
            
            verify_url = url_for('auth_routes.verify_email', token=token, _external=True)
            msg = Message(
                subject="Verify Your Email",
                recipients=[email]
            )
            msg.body = (
                "Please verify your email by clicking the link:\n\n"
                f"{verify_url}"
            )
            msg.html = render_template(
                'emails/verification_email.html',
                user=user,
                verify_url=verify_url
            )
            try:
                mail.send(msg)
            except Exception as e:
                logging.error(f"Failed to send verification email: {e}")
                _dev_only(f"[DEV] Verification Link: {verify_url}")
            
            flash("Verification email has been resent successfully.", "success")
            return redirect(url_for('auth_routes.login'))
        else:
            flash("Email address not found.", "error")
            return redirect(url_for('auth_routes.resend_verification'))
            
    return render_template('resend_verification.html')


@auth_routes.route('/onboarding', methods=['GET', 'POST'])
def onboarding():
    if current_user.is_authenticated:
        return redirect(url_for('general_routes.dashboard'))
        
    from models import Client, Role
    if request.method == 'POST':
        org_name = request.form.get('org_name')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        email = request.form.get('email')
        password = request.form.get('password')
        client_name = request.form.get('client_name')
        
        # Simple validation
        if not all([org_name, first_name, last_name, email, password, client_name]):
            flash("All fields are required.", "error")
            return redirect(url_for('auth_routes.onboarding'))
            
        # Duplication check
        if User.query.filter_by(employee_email=email).first():
            flash("Email already registered.", "error")
            return redirect(url_for('auth_routes.onboarding'))
            
        # Create tenant first, then client scoped to that tenant
        from models import Tenant
        from utils.tenant_utils import generate_office_key
        office_key = generate_office_key()
        while Tenant.query.filter_by(office_key=office_key).first():
            office_key = generate_office_key()

        new_tenant = Tenant(
            name=org_name,
            allowed_domain=email.split('@')[-1].lower(),
            office_key=office_key.upper(),
        )
        from utils.billing_plans import apply_trial_to_tenant
        from utils.mongo_tenant import provision_tenant_mongo

        apply_trial_to_tenant(new_tenant)
        db.session.add(new_tenant)
        db.session.flush()

        client = Client.query.filter_by(name=client_name, tenant_id=new_tenant.id).first()
        if not client:
            client = Client(name=client_name, tenant_id=new_tenant.id)
            db.session.add(client)
        
        # Create the admin user
        import uuid
        employee_id = f"ADM-{uuid.uuid4().hex[:6].upper()}"
        
        new_user = User(
            first_name=first_name,
            last_name=last_name,
            employee_email=email,
            employee_id=employee_id,
            join_date=datetime.utcnow().date(),
            is_verified=True,
            is_super_admin=True,
            tenant_id=new_tenant.id
        )
        new_user.set_password(password)
        db.session.add(new_user)
        
        # Assign the client
        new_user.clients.append(client)
        
        # Assign roles - make sure "admin" and "super_admin" roles are assigned if they exist
        admin_role = Role.query.filter_by(name='admin').first()
        super_admin_role = Role.query.filter_by(name='super_admin').first()
        if admin_role:
            new_user.roles.append(admin_role)
        if super_admin_role:
            new_user.roles.append(super_admin_role)

        from utils.tenant_seeds import seed_tenant_catalog
        seed_tenant_catalog(new_tenant.id)
            
        try:
            db.session.commit()
            provision_tenant_mongo(new_tenant.id)
            from utils.onboarding_emails import send_welcome_email
            send_welcome_email(new_tenant, admin_user=new_user)
            # Log in the user immediately
            from flask_login import login_user
            login_user(new_user)
            # Store org name in session for dynamic branding!
            session['tenant_name'] = org_name
            session['tenant_id'] = new_tenant.id
            flash(
                f"Welcome to TrainIQ! Organization '{org_name}' created. "
                f"Your Office Key is: {office_key}. Save it for sign-in. "
                f"You have a 30-day free trial with up to 10 team members.",
                "success",
            )
            return redirect(url_for('general_routes.dashboard'))
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error during onboarding registration: {e}")
            flash("An error occurred during onboarding. Please try again.", "error")
            return redirect(url_for('auth_routes.onboarding'))
            
    selected_plan = (request.args.get('plan') or 'trial').strip().lower()
    from utils.billing_plans import TRIAL_DAYS, TRIAL_MAX_USERS, get_plan
    return render_template(
        'onboarding.html',
        selected_plan=selected_plan,
        selected_plan_info=get_plan(selected_plan if selected_plan != 'trial' else 'trial'),
        trial_days=TRIAL_DAYS,
        trial_max_users=TRIAL_MAX_USERS,
    )


@auth_routes.route('/sso/check')
def sso_check():
    """JSON: is SSO enabled for this office key? (login page uses this.)"""
    from models import Tenant
    from utils.sso import sso_label, tenant_sso_available

    office_key = normalize_office_key(request.args.get('office_key'))
    if not office_key:
        return jsonify({"sso_enabled": False})
    tenant = Tenant.query.filter_by(office_key=office_key).first()
    if not tenant or not tenant_sso_available(tenant):
        return jsonify({"sso_enabled": False})
    return jsonify({"sso_enabled": True, "provider_label": sso_label(tenant)})


@auth_routes.route('/sso/start')
def sso_start():
    """Redirect to IdP authorization endpoint."""
    from models import Tenant
    from utils.sso import build_authorization_url, new_sso_state, tenant_sso_available

    office_key = normalize_office_key(request.args.get('office_key'))
    if not office_key:
        flash("Office Key is required for SSO.", "error")
        return redirect(url_for('auth_routes.login'))

    tenant = Tenant.query.filter_by(office_key=office_key).first()
    if not tenant or not tenant_sso_available(tenant):
        flash("Single sign-on is not enabled for this organization.", "error")
        return redirect(url_for('auth_routes.login'))

    state, nonce = new_sso_state()
    session['sso_state'] = state
    session['sso_nonce'] = nonce
    session['sso_tenant_id'] = tenant.id
    session['sso_office_key'] = office_key

    redirect_uri = url_for('auth_routes.sso_callback', _external=True)
    try:
        auth_url = build_authorization_url(
            tenant, redirect_uri=redirect_uri, state=state, nonce=nonce
        )
    except Exception as exc:
        logging.error("SSO start failed: %s", exc)
        flash("SSO configuration error. Contact your administrator.", "error")
        return redirect(url_for('auth_routes.login'))
    return redirect(auth_url)


@auth_routes.route('/sso/callback')
def sso_callback():
    """OIDC callback — match IdP email to tenant user and log in."""
    from models import Tenant, User
    from utils.sso import exchange_code_and_userinfo, tenant_sso_available

    err = request.args.get('error')
    if err:
        flash(f"SSO sign-in cancelled: {err}", "error")
        return redirect(url_for('auth_routes.login'))

    state = request.args.get('state')
    code = request.args.get('code')
    if not code or state != session.get('sso_state'):
        flash("Invalid SSO response. Please try again.", "error")
        return redirect(url_for('auth_routes.login'))

    tenant_id = session.get('sso_tenant_id')
    tenant = Tenant.query.get(tenant_id) if tenant_id else None
    if not tenant or not tenant_sso_available(tenant):
        flash("SSO session expired. Please start again.", "error")
        return redirect(url_for('auth_routes.login'))

    redirect_uri = url_for('auth_routes.sso_callback', _external=True)
    try:
        userinfo = exchange_code_and_userinfo(tenant, code=code, redirect_uri=redirect_uri)
    except Exception as exc:
        logging.error("SSO token exchange failed: %s", exc)
        flash("Could not complete SSO sign-in.", "error")
        return redirect(url_for('auth_routes.login'))

    email = (userinfo.get('email') or userinfo.get('preferred_username') or '').lower().strip()
    if not email:
        flash("SSO provider did not return an email address.", "error")
        return redirect(url_for('auth_routes.login'))

    user = User.query.filter_by(employee_email=email, tenant_id=tenant.id).first()
    if not user:
        flash(
            "No TrainIQ account exists for this email in your organization. "
            "Ask your admin to invite you first.",
            "error",
        )
        return redirect(url_for('auth_routes.login'))

    if user.is_locked:
        flash("Your account is locked. Use password reset or contact support.", "error")
        return redirect(url_for('auth_routes.login'))

    from utils.tenant_limits import tenant_is_active, trial_expired_message
    if not tenant_is_active(tenant) and not user.is_super_admin:
        flash(trial_expired_message(tenant), "error")
        return redirect(url_for('auth_routes.login'))

    for key in ('sso_state', 'sso_nonce', 'sso_tenant_id', 'sso_office_key'):
        session.pop(key, None)

    session['user_id'] = user.id
    session['is_super_admin'] = user.is_super_admin
    session['role_id'] = user.roles[0].id if user.roles else None
    session['designation_id'] = user.designation_id
    set_active_tenant_session(tenant, platform_support=False)
    session['tenant_name'] = tenant.name
    session.permanent = True

    log_event('USER_LOGIN', user=user, details={'method': 'sso'})
    login_user(user)
    logging.info("User %s logged in via SSO from %s", user.id, request.remote_addr)
    return _redirect_after_login(user)
