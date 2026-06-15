import os
import logging
import mimetypes
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('text/css', '.css')
import click
from flask import Flask, render_template, jsonify, request, session, redirect, url_for, g, flash
from flask.cli import with_appcontext
from flask_wtf import CSRFProtect
# Optional rate-limiter import
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    rate_limiting_available = True
except ImportError:
    logging.warning("Flask-Limiter not installed; skipping rate limiting.")
    rate_limiting_available = False
from flask_migrate import Migrate, upgrade as migrate_upgrade
from flask_login import LoginManager, login_required, current_user
from dotenv import load_dotenv
from datetime import datetime, timedelta

from extensions import db, mail, scheduler
from auth_routes import auth_routes
from general_routes import general_routes
from profile_routes import profile_routes
from task_routes import task_routes
from exams_routes import exams_routes
from study_material_routes import study_material_routes
from admin_routes import admin_routes
from ai_routes import ai_routes
from management_routes import management_routes
from special_exams_routes import special_exams_routes
from models import User, FailedLogin, AuditLog
from mongodb_operations import initialize_mongodb, setup_collections
from utils.email_utils import init_scheduler
from audit import log_event  # our helper

# Load environment variables
load_dotenv(override=True)

IS_PRODUCTION = os.getenv('FLASK_ENV', 'development') != 'development'

# Initialize Flask app
app = Flask(
    __name__,
    static_folder='static',
    static_url_path='/static'
)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ----------------------------------------------------------------------
# CLI: Backfill historical failed-logins
# ----------------------------------------------------------------------
@click.command('backfill-failures')
@with_appcontext
def backfill_failures():
    """
    Migrate existing FailedLogin records into audit_log.
    """
    for fl in FailedLogin.query.order_by(FailedLogin.timestamp).all():
        entry = AuditLog(
            event_type  = 'FAILED_LOGIN',
            ip_address  = fl.ip_address,
            description = {'email': fl.email, 'user_agent': fl.user_agent},
            created_at  = fl.timestamp
        )
        db.session.add(entry)
    db.session.commit()
    click.echo('✅ Backfilled failed-logins into audit_log.')

# Register CLI command
app.cli.add_command(backfill_failures)

# ----------------------------------------------------------------------
# Scheduler API (disable in production)
# ----------------------------------------------------------------------
app.config['SCHEDULER_API_ENABLED'] = not IS_PRODUCTION
app.config['SCHEDULER_API_PREFIX'] = '/jobs'
app.config['SCHEDULER_TIMEZONE'] = 'UTC'
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # analytics PDF chart uploads

# ----------------------------------------------------------------------
# Rate limiting (if available)
# ----------------------------------------------------------------------
if rate_limiting_available:
    raw_redis_uri = os.getenv("REDIS_URI", "").strip()
    if raw_redis_uri.startswith("REDIS_URI="):
        raw_redis_uri = raw_redis_uri.split("=", 1)[1]
    if raw_redis_uri:
        storage_uri = raw_redis_uri
    elif IS_PRODUCTION:
        logging.warning("REDIS_URI not set — rate limits use in-memory storage (single-worker only).")
        storage_uri = "memory://"
    else:
        storage_uri = "memory://"
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=["1000 per day", "200 per hour"],
        storage_uri=storage_uri,
    )
    limiter.init_app(app)
else:
    limiter = None
    if IS_PRODUCTION:
        logging.warning("Flask-Limiter not installed — install it for production rate limiting.")

# ----------------------------------------------------------------------
# CSRF Protection
# ----------------------------------------------------------------------
csrf = CSRFProtect(app)

# ─── Exempt our keep-alive ping from CSRF ──────────────────────────
@csrf.exempt
@app.route('/ping', methods=['POST'])
def ping():
    """Session keep-alive — client sends every ~5 min while user is active."""
    if 'user_id' not in session:
        return jsonify({'ok': False, 'reason': 'no_session'}), 401
    now = datetime.utcnow()
    session['last_activity'] = now.strftime('%Y-%m-%d %H:%M:%S.%f')
    session.modified = True
    afk_minutes = int(os.getenv('SESSION_AFK_MINUTES', '75'))
    return jsonify({'ok': True, 'timeout_minutes': afk_minutes}), 200

# ----------------------------------------------------------------------
# App Configuration
# ----------------------------------------------------------------------
if IS_PRODUCTION and not os.getenv('SECRET_KEY'):
    raise RuntimeError('SECRET_KEY environment variable is required in production.')
if IS_PRODUCTION and not os.getenv('DATABASE_URL'):
    raise RuntimeError('DATABASE_URL environment variable is required in production.')
if not os.getenv('SECRET_KEY'):
    logging.warning('SECRET_KEY not set — using insecure fallback (development only).')

app.config.update({
    'SECRET_KEY':                 os.getenv('SECRET_KEY', 'fallback-secret-key'),
    'SQLALCHEMY_DATABASE_URI':    os.getenv('DATABASE_URL', 'postgresql://postgres:root@localhost/collectivercm'),
    'SQLALCHEMY_TRACK_MODIFICATIONS': False,
    'MAIL_SERVER':                os.getenv('MAIL_SERVER'),
    'MAIL_PORT':                  int(os.getenv('MAIL_PORT', 0)),
    'MAIL_USE_TLS':               os.getenv('MAIL_USE_TLS', 'False') == 'True',
    'MAIL_USERNAME':              os.getenv('MAIL_USERNAME'),
    'MAIL_PASSWORD':              os.getenv('MAIL_PASSWORD'),
    'MAIL_DEFAULT_SENDER':        os.getenv('MAIL_DEFAULT_SENDER'),
    'ALLOWED_EMAIL_DOMAINS':      os.getenv('ALLOWED_EMAIL_DOMAINS', ''),
})

from utils.security import validate_production_config
validate_production_config(app)

# ─── Session Cookie & Lifetime ────────────────────────────────────────
# Keep the cookie alive for 3 hours and set sane defaults for cross-site
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=3)
app.config['SESSION_COOKIE_SECURE']   = os.getenv(
    'SESSION_COOKIE_SECURE', 'True' if IS_PRODUCTION else 'False'
) == 'True'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# (SESSION_REFRESH_EACH_REQUEST=True by default, so Flask will auto-refresh)

# ----------------------------------------------------------------------
# Initialize extensions and auto-migrate
# ----------------------------------------------------------------------
login_manager = LoginManager()

def run_tenant_backfill():
    try:
        from models import Tenant, User, Exam, StudyMaterial, Task, Client, Department, Question
        if Tenant.query.count() == 0:
            from utils.billing_plans import apply_trial_to_tenant
            default_tenant = Tenant(
                name="Collective RCM",
                allowed_domain="collectivercm.com",
                office_key="COLLECTIVE",
            )
            apply_trial_to_tenant(default_tenant)
            db.session.add(default_tenant)
            db.session.commit()
            logging.info("Default tenant 'Collective RCM' created.")

        default = Tenant.query.get(1) or Tenant.query.first()
        if default and not default.office_key:
            default.office_key = "COLLECTIVE"
            db.session.commit()
        if default and default.office_key:
            default.office_key = default.office_key.upper()

        tid = default.id if default else 1
        for model in (Exam, StudyMaterial, Task, Client, Department):
            db.session.execute(
                db.text(f"UPDATE {model.__tablename__} SET tenant_id = :tid WHERE tenant_id IS NULL"),
                {"tid": tid},
            )
        db.session.execute(
            db.text("UPDATE questions SET question_type = 'single_choice' WHERE question_type IS NULL")
        )
        db.session.execute(
            db.text("UPDATE exams SET passing_score = 70.0 WHERE passing_score IS NULL")
        )
        db.session.commit()

        users = User.query.all()
        for u in users:
            if u.tenant_id is None:
                u.tenant_id = tid
        db.session.commit()
        logging.info("Tenant backfill completed.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Tenant backfill failed: {e}")


def run_catalog_backfill():
    """Assign legacy global catalog rows to the default tenant."""
    try:
        from models import Tenant, Category, Level, Area, Designation
        default = Tenant.query.first()
        if not default:
            return
        tid = default.id
        for model in (Category, Level, Area, Designation):
            db.session.execute(
                db.text(f"UPDATE {model.__tablename__} SET tenant_id = :tid WHERE tenant_id IS NULL"),
                {"tid": tid},
            )
        db.session.commit()
        logging.info("Catalog tenant backfill completed.")
    except Exception as e:
        db.session.rollback()
        logging.error(f"Catalog backfill failed: {e}")

db.init_app(app)
migrate = Migrate(app, db)
with app.app_context():
    migrate_upgrade()
    try:
        db.session.execute(db.text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS primary_color VARCHAR(7) DEFAULT '#4f46e5'"))
        db.session.execute(db.text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS secondary_color VARCHAR(7) DEFAULT '#06b6d4'"))
        db.session.execute(db.text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS support_email VARCHAR(120) DEFAULT 'support@trainiq.com'"))
        db.session.execute(db.text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS portal_tagline VARCHAR(255) DEFAULT 'Centralized HR and Performance Hub'"))
        db.session.execute(db.text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS enable_2fa BOOLEAN DEFAULT FALSE"))
        db.session.execute(db.text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS enable_proctoring BOOLEAN DEFAULT TRUE"))
        db.session.execute(db.text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS office_key VARCHAR(50) UNIQUE"))
        db.session.execute(db.text("ALTER TABLE exams ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id)"))
        db.session.execute(db.text("ALTER TABLE exams ADD COLUMN IF NOT EXISTS passing_score FLOAT DEFAULT 70.0"))
        db.session.execute(db.text("ALTER TABLE study_materials ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id)"))
        db.session.execute(db.text("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id)"))
        db.session.execute(db.text("ALTER TABLE clients ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id)"))
        db.session.execute(db.text("ALTER TABLE departments ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id)"))
        db.session.execute(db.text("ALTER TABLE questions ADD COLUMN IF NOT EXISTS question_type VARCHAR(50) DEFAULT 'single_choice'"))
        db.session.execute(db.text("ALTER TABLE questions ALTER COLUMN correct_answer TYPE TEXT"))
        for catalog_table in ('categories', 'levels', 'areas', 'designations'):
            db.session.execute(db.text(
                f"ALTER TABLE {catalog_table} ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id)"
            ))
        for col_sql in (
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS plan VARCHAR(50) DEFAULT 'trial'",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'trial'",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_users INTEGER DEFAULT 10",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS max_storage_mb INTEGER DEFAULT 2048",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMP",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS trial_reminder_7d_at TIMESTAMP",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS trial_reminder_1d_at TIMESTAMP",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS onboarding_welcome_at TIMESTAMP",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS onboarding_drip_1_at TIMESTAMP",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS onboarding_drip_3_at TIMESTAMP",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS onboarding_drip_7_at TIMESTAMP",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS sso_enabled BOOLEAN DEFAULT FALSE",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS sso_provider VARCHAR(30)",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS sso_client_id VARCHAR(255)",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS sso_client_secret VARCHAR(512)",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS sso_issuer_url VARCHAR(512)",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS sso_tenant_domain VARCHAR(255)",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_checklist_dismissed BOOLEAN DEFAULT FALSE",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS billing_email VARCHAR(120)",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS billing_cycle VARCHAR(20) DEFAULT 'monthly'",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(120)",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS enable_invite_only BOOLEAN DEFAULT FALSE",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMP",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS suspended_reason TEXT",
        ):
            db.session.execute(db.text(col_sql))
        # Invite role + platform performance indexes (mirrors p0q1r2s3t4u5 / q1r2s3t4u5v6)
        db.session.execute(db.text(
            "ALTER TABLE tenant_invites ADD COLUMN IF NOT EXISTS role VARCHAR(32) DEFAULT 'learner'"
        ))
        for idx_sql in (
            "CREATE INDEX IF NOT EXISTS ix_users_join_date ON users (join_date)",
            "CREATE INDEX IF NOT EXISTS ix_users_tenant_verified ON users (tenant_id, is_verified)",
            "CREATE INDEX IF NOT EXISTS ix_users_is_locked ON users (is_locked)",
            "CREATE INDEX IF NOT EXISTS ix_support_tickets_status ON support_tickets (status)",
            "CREATE INDEX IF NOT EXISTS ix_support_tickets_user_id ON support_tickets (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_support_tickets_created_at ON support_tickets (created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenants_plan ON tenants (plan)",
            "CREATE INDEX IF NOT EXISTS ix_tenants_status ON tenants (status)",
            "CREATE INDEX IF NOT EXISTS ix_tenants_trial_ends_at ON tenants (trial_ends_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenants_created_at ON tenants (created_at)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_invites_tenant_id ON tenant_invites (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_tenant_invites_used_at ON tenant_invites (used_at)",
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_event_created ON audit_logs (event_type, created_at)",
            "CREATE INDEX IF NOT EXISTS ix_user_scores_created_at ON user_scores (created_at)",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(120)",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS billing_period_start TIMESTAMP",
            "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS billing_period_end TIMESTAMP",
        ):
            try:
                db.session.execute(db.text(idx_sql))
            except Exception as idx_err:
                logging.warning("Skipped index DDL (%s): %s", idx_sql[:55], idx_err)
        db.session.commit()
        from utils.billing_plans import backfill_missing_trial_dates
        backfill_missing_trial_dates()
        run_tenant_backfill()
        run_catalog_backfill()
        from utils.platform_ceo import ensure_platform_ceo
        ensure_platform_ceo()
    except Exception as db_err:
        db.session.rollback()
        logging.error(f"Error checking/adding customization columns: {db_err}")

login_manager.init_app(app)
login_manager.login_view = 'auth_routes.login'
mail.init_app(app)

# ----------------------------------------------------------------------
# MongoDB Setup
# ----------------------------------------------------------------------
try:
    mongo_client, mongo_db = initialize_mongodb()
    if mongo_db is not None:
        setup_collections(mongo_db)
        logging.info("MongoDB initialized successfully.")
    else:
        logging.warning(
            "MongoDB unavailable — course file uploads and GridFS storage are disabled until MongoDB is running."
        )
except Exception as e:
    mongo_client, mongo_db = None, None
    logging.warning(f"MongoDB setup skipped: {e}")

# ----------------------------------------------------------------------
# APScheduler Setup
# ----------------------------------------------------------------------
scheduler.init_app(app)
init_scheduler(scheduler)
scheduler.start()

# ----------------------------------------------------------------------
# Register Blueprints
# ----------------------------------------------------------------------
app.register_blueprint(auth_routes, url_prefix='/auth')
app.register_blueprint(general_routes)
app.register_blueprint(profile_routes, url_prefix='/profile')
app.register_blueprint(task_routes, url_prefix='/tasks')
app.register_blueprint(exams_routes, url_prefix='/exams')
app.register_blueprint(study_material_routes, url_prefix='/study_materials')
app.register_blueprint(admin_routes, url_prefix='/admin')
app.register_blueprint(__import__('billing_routes', fromlist=['billing_routes']).billing_routes, url_prefix='')
from billing_routes import stripe_webhook as _stripe_webhook_handler
csrf.exempt(_stripe_webhook_handler)
app.register_blueprint(ai_routes, url_prefix='/ai')
app.register_blueprint(management_routes, url_prefix='/management')
app.register_blueprint(special_exams_routes)
app.register_blueprint(__import__('platform_routes', fromlist=['platform_routes']).platform_routes, url_prefix='')
app.register_blueprint(__import__('notification_routes', fromlist=['notification_routes']).notification_routes, url_prefix='')

# Rate-limit sensitive auth endpoints
if rate_limiting_available:
    for _ep in (
        'auth_routes.login',
        'auth_routes.forgot_password',
        'auth_routes.verify_2fa',
        'auth_routes.register',
        'auth_routes.accept_invite',
        'auth_routes.sso_start',
        'auth_routes.sso_callback',
        'platform_routes.enter_by_office_key',
        'platform_routes.enter_tenant',
    ):
        if _ep in app.view_functions:
            limiter.limit("10 per minute")(app.view_functions[_ep])
elif not rate_limiting_available:
    pass

# ----------------------------------------------------------------------
# Root & utility routes
# ----------------------------------------------------------------------
@app.context_processor
def inject_global_helpers():
    from utils.special_exams import special_paper_label

    def has_profile_picture(user_id):
        try:
            from mongodb_operations import get_mongo_connection, PROFILE_PICTURES_COLLECTION
            _, db, _ = get_mongo_connection()
            record = db[PROFILE_PICTURES_COLLECTION].find_one({"user_id": str(user_id)}, {"_id": 1})
            return record is not None
        except Exception:
            return False
    def user_initials(user):
        if not user:
            return '?'
        f = (getattr(user, 'first_name', '') or '')[:1].upper()
        l = (getattr(user, 'last_name', '') or '')[:1].upper()
        return (f + l) if (f and l) else (f or l or '?')

    return dict(
        has_profile_picture=has_profile_picture,
        special_paper_label=special_paper_label,
        user_initials=user_initials,
        ** _billing_context(),
    )


def _billing_context():
    """Inject tenant usage and trial checklist for Super Admins."""
    try:
        from flask_login import current_user
        if not current_user.is_authenticated:
            return {"tenant_usage_global": None, "trial_checklist": None}
        from utils.billing_context import get_active_tenant_usage
        from utils.trial_checklist import get_trial_checklist
        tenant, usage = get_active_tenant_usage(current_user)
        checklist = get_trial_checklist(tenant) if tenant else None
        if checklist and getattr(current_user, "trial_checklist_dismissed", False):
            checklist = None
        return {"tenant_usage_global": usage, "trial_checklist": checklist}
    except Exception:
        return {"tenant_usage_global": None, "trial_checklist": None}


@app.route('/')
def root():
    return render_template('home.html')

if not IS_PRODUCTION:
    @app.route('/routes')
    def list_routes():
        return jsonify([{'endpoint': r.endpoint, 'url': r.rule} for r in app.url_map.iter_rules()])

# ----------------------------------------------------------------------
# Security headers
# ----------------------------------------------------------------------
from utils.security import apply_security_headers

@app.after_request
def add_security_headers(response):
    if request.path.endswith('.js'):
        response.headers['Content-Type'] = 'application/javascript'
    elif request.path.endswith('.css'):
        response.headers['Content-Type'] = 'text/css'
    return apply_security_headers(response, is_production=IS_PRODUCTION)

# ----------------------------------------------------------------------
# User session timeout
# ----------------------------------------------------------------------
def check_afk_timeout():
    if request.endpoint in [
        'static',
        'auth_routes.login',
        'auth_routes.logout',
        'auth_routes.register',
        'auth_routes.onboarding',
        'exams_routes.start_exam',
        'exams_routes.submit_exam',
        'special_exams_routes.exam_paper1',
        'special_exams_routes.submit_paper1',
        'special_exams_routes.exam_paper2',
        'special_exams_routes.submit_paper2',
        'ping',
    ]:
        return

    if 'user_id' in session:
        now = datetime.utcnow()
        afk_minutes = int(os.getenv('SESSION_AFK_MINUTES', '75'))
        last_activity = session.get('last_activity')
        if last_activity:
            last_activity = datetime.strptime(last_activity, '%Y-%m-%d %H:%M:%S.%f')
            if now - last_activity > timedelta(minutes=afk_minutes):
                session.clear()
                flash("Your session expired due to inactivity. Please sign in again.", "warning")
                return redirect(url_for('auth_routes.login'))

        session['last_activity'] = now.strftime('%Y-%m-%d %H:%M:%S.%f')
        session.modified = True

app.before_request(check_afk_timeout)


def enforce_user_agreement():
    """Block platform use until the current User Agreement version is accepted."""
    if app.config.get('TESTING') and not app.config.get('ENFORCE_AGREEMENT_IN_TESTS'):
        return
    from flask_login import current_user
    from utils.user_agreement import is_agreement_exempt_endpoint, user_needs_agreement

    if not current_user.is_authenticated:
        return
    if is_agreement_exempt_endpoint(request.endpoint, request.path):
        return
    if user_needs_agreement(current_user):
        if request.endpoint != 'general_routes.user_agreement_accept':
            session['post_agreement_next'] = request.url
        return redirect(url_for('general_routes.user_agreement_accept'))


app.before_request(enforce_user_agreement)


def resolve_tenant():
    from models import Tenant
    # 1. Resolve from request host domain
    host = request.host.split(':')[0].lower()
    matched_tenant = None
    
    # Identify if request is on the main SaaS platform domain (non-tenant domain)
    is_custom_domain = host not in ('localhost', '127.0.0.1', 'trainiq.com', 'www.trainiq.com')
    
    if is_custom_domain:
        from utils.tenant_utils import host_matches_allowed
        candidates = Tenant.query.filter(Tenant.allowed_domain.isnot(None)).all()
        matched_tenant = None
        for tenant in candidates:
            if host_matches_allowed(host, tenant.allowed_domain):
                matched_tenant = tenant
                break

    # Identify public marketing/product landing and auth pages
    public_paths = ('/', '/home', '/pricing', '/privacy-policy', '/help', '/user-agreement')
    is_public = (request.path in public_paths) or (request.path.startswith('/auth/') and request.path != '/auth/logout')

    # Determine resolved values
    if is_custom_domain and matched_tenant:
        g.tenant = matched_tenant
        g.tenant_id = matched_tenant.id
        g.tenant_name = matched_tenant.name
        g.tenant_logo_url = url_for('general_routes.serve_tenant_logo', tenant_id=matched_tenant.id) if matched_tenant.logo_filename else None
        
        session['tenant_id'] = matched_tenant.id
        session['tenant_name'] = matched_tenant.name
    elif not is_public and current_user.is_authenticated:
        from utils.tenant_utils import user_tenant_id
        active_tid = user_tenant_id()
        user_tenant = db.session.get(Tenant, active_tid) if active_tid else None
        if user_tenant:
            g.tenant = user_tenant
            g.tenant_id = user_tenant.id
            g.tenant_name = user_tenant.name
            g.tenant_logo_url = url_for('general_routes.serve_tenant_logo', tenant_id=user_tenant.id) if user_tenant.logo_filename else None
            if not session.get('platform_support'):
                session['tenant_id'] = user_tenant.id
                session['tenant_name'] = user_tenant.name
        else:
            g.tenant = None
            g.tenant_id = None
            g.tenant_name = 'TrainIQ'
            g.tenant_logo_url = None
    else:
        # Public page on main domain or guest visitor
        g.tenant = None
        g.tenant_id = None
        g.tenant_name = 'TrainIQ'
        g.tenant_logo_url = None
        
        # Reset session only if they are not authenticated, so logged-in state is not broken
        if not current_user.is_authenticated:
            session.pop('tenant_id', None)
            session['tenant_name'] = 'TrainIQ'

def hex_to_rgb(hex_str):
    if not hex_str or not hex_str.startswith('#'):
        return "79, 70, 229"
    try:
        h = hex_str.lstrip('#')
        if len(h) == 3:
            h = ''.join([c*2 for c in h])
        return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"
    except Exception:
        return "79, 70, 229"


from utils.branding import resolve_display_brand


app.before_request(resolve_tenant)

@app.context_processor
def inject_platform_helpers():
    from utils.tenant_utils import is_trainiq_staff
    from utils.platform_ceo import is_platform_ceo
    from utils.platform_staff_permissions import staff_has_permission, effective_staff_role
    from utils.admin_permissions import user_has_permission, user_can_access_admin, permission_summary, user_can_manage_permissions
    from flask_login import current_user

    def has_admin_perm(code):
        if not current_user.is_authenticated:
            return False
        return user_has_permission(current_user, code)

    def has_platform_perm(code):
        if not current_user.is_authenticated:
            return False
        return staff_has_permission(current_user, code)

    return dict(
        is_trainiq_staff=is_trainiq_staff,
        is_platform_ceo=is_platform_ceo,
        has_admin_perm=has_admin_perm,
        has_platform_perm=has_platform_perm,
        platform_staff_role=effective_staff_role(current_user) if current_user.is_authenticated else None,
        has_admin_perm_any=lambda *codes: any(has_admin_perm(c) for c in codes),
        user_can_access_admin=user_can_access_admin,
        user_can_manage_permissions=user_can_manage_permissions,
        permission_summary=permission_summary,
    )


@app.context_processor
def inject_global_branding():
    tenant = getattr(g, 'tenant', None)
    primary_color = tenant.primary_color if (tenant and tenant.primary_color) else '#4f46e5'
    secondary_color = tenant.secondary_color if (tenant and tenant.secondary_color) else '#06b6d4'
    display_org_name, is_platform_brand, org_initial = resolve_display_brand(tenant)
    portal_tagline = (
        tenant.portal_tagline if (tenant and tenant.portal_tagline)
        else 'Centralized HR and Performance Hub'
    )
    return {
        'global_org_name': tenant.name if tenant else 'TrainIQ',
        'display_org_name': display_org_name,
        'is_platform_brand': is_platform_brand,
        'org_initial': org_initial,
        'portal_tagline': portal_tagline,
        'global_logo_url': url_for('general_routes.serve_tenant_logo', tenant_id=tenant.id) if (tenant and tenant.logo_filename) else None,
        'global_tenant_id': tenant.id if tenant else None,
        'global_tenant': tenant,
        'primary_color': primary_color,
        'secondary_color': secondary_color,
        'primary_color_rgb': hex_to_rgb(primary_color),
        'secondary_color_rgb': hex_to_rgb(secondary_color),
        'trainiq_website_url': os.getenv('TRAINIQ_WEBSITE_URL', 'https://trainiq.com'),
        'current_year': datetime.utcnow().year,
    }


@app.context_processor
def inject_legal_context():
    from utils.user_agreement import agreement_context, user_has_accepted_agreement
    from flask_login import current_user

    ctx = agreement_context()
    ctx["user_has_accepted_agreement"] = (
        current_user.is_authenticated and user_has_accepted_agreement(current_user)
    )
    return ctx


# ----------------------------------------------------------------------
# User loader
# ----------------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except Exception as e:
        logging.error(f"Error loading user: {e}")
        return None

# ----------------------------------------------------------------------
# Error Handlers
# ----------------------------------------------------------------------
@app.errorhandler(404)
def page_not_found(e):
    logging.warning("404 - Page not found.")
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(e):
    logging.error(f"500 - Internal server error: {e}")
    return render_template('500.html'), 500

# ----------------------------------------------------------------------
# Seed Runner (one-time)
# ----------------------------------------------------------------------
def run_seed_once():
    lock_file = "seed.lock"
    if not os.path.exists(lock_file):
        try:
            from seed_all import run_all_seeds
            run_all_seeds()
            with open(lock_file, 'w') as f:
                f.write("seeded")
        except Exception as e:
            logging.error(f"Seeding failed: {e}")


# ----------------------------------------------------------------------
# Main entry
# ----------------------------------------------------------------------
if __name__ == '__main__':
    with app.app_context():
        run_seed_once()
    env = os.getenv('FLASK_ENV', 'development')
    debug_mode = True if env == 'development' else False
    app.run(host='0.0.0.0', debug=debug_mode)
