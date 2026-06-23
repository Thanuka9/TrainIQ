"""Single catalog for idempotent DB optimizations (indexes, extensions, FTS).

PRODUCTION POLICY: schema changes ship via Alembic migrations only.
This catalog is for local/dev bootstrap backfill when SCHEMA_GUARDS_FROZEN=false.
Do not add new production DDL here without a matching Alembic revision.
"""
from __future__ import annotations

from dataclasses import dataclass

# ── Column / table guards (idempotent ALTER) ───────────────────────────────────
TENANT_COLUMN_DDL = (
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS primary_color VARCHAR(7) DEFAULT '#4f46e5'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS secondary_color VARCHAR(7) DEFAULT '#06b6d4'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS support_email VARCHAR(120) DEFAULT 'support@trainiq.com'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS portal_tagline VARCHAR(255) DEFAULT 'Centralized HR and Performance Hub'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS enable_2fa BOOLEAN DEFAULT FALSE",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS enable_proctoring BOOLEAN DEFAULT TRUE",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS office_key VARCHAR(50) UNIQUE",
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
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS billing_email VARCHAR(120)",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS billing_cycle VARCHAR(20) DEFAULT 'monthly'",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_customer_id VARCHAR(120)",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS stripe_subscription_id VARCHAR(120)",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS billing_period_start TIMESTAMP",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS billing_period_end TIMESTAMP",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS enable_invite_only BOOLEAN DEFAULT FALSE",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMP",
    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS suspended_reason TEXT",
)

TABLE_COLUMN_DDL = (
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id)",
    "ALTER TABLE exams ADD COLUMN IF NOT EXISTS passing_score FLOAT DEFAULT 70.0",
    "ALTER TABLE study_materials ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id)",
    "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id)",
    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id)",
    "ALTER TABLE departments ADD COLUMN IF NOT EXISTS tenant_id INTEGER REFERENCES tenants(id)",
    "ALTER TABLE questions ADD COLUMN IF NOT EXISTS question_type VARCHAR(50) DEFAULT 'single_choice'",
    "ALTER TABLE questions ALTER COLUMN correct_answer TYPE TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_checklist_dismissed BOOLEAN DEFAULT FALSE",
    "ALTER TABLE tenant_invites ADD COLUMN IF NOT EXISTS role VARCHAR(32) DEFAULT 'learner'",
)

CATALOG_TABLES = ('categories', 'levels', 'areas', 'designations')

PERFORMANCE_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_users_join_date ON users (join_date)",
    "CREATE INDEX IF NOT EXISTS ix_users_tenant_verified ON users (tenant_id, is_verified)",
    "CREATE INDEX IF NOT EXISTS ix_users_is_locked ON users (is_locked)",
    "CREATE INDEX IF NOT EXISTS ix_users_tenant_deleted ON users (tenant_id, deleted_at)",
    "CREATE INDEX IF NOT EXISTS ix_users_deleted_at ON users (deleted_at)",
    "CREATE INDEX IF NOT EXISTS ix_users_tenant_join ON users (tenant_id, join_date)",
    "CREATE INDEX IF NOT EXISTS ix_users_email_lower ON users (employee_email)",
    "CREATE INDEX IF NOT EXISTS ix_support_tickets_status ON support_tickets (status)",
    "CREATE INDEX IF NOT EXISTS ix_support_tickets_user_id ON support_tickets (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_support_tickets_created_at ON support_tickets (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_tenants_plan ON tenants (plan)",
    "CREATE INDEX IF NOT EXISTS ix_tenants_status ON tenants (status)",
    "CREATE INDEX IF NOT EXISTS ix_tenants_trial_ends_at ON tenants (trial_ends_at)",
    "CREATE INDEX IF NOT EXISTS ix_tenants_created_at ON tenants (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_tenant_invites_tenant_id ON tenant_invites (tenant_id)",
    "CREATE INDEX IF NOT EXISTS ix_tenant_invites_used_at ON tenant_invites (used_at)",
    "CREATE INDEX IF NOT EXISTS ix_tenant_invites_tenant_pending ON tenant_invites (tenant_id, used_at)",
    "CREATE INDEX IF NOT EXISTS ix_audit_log_event_created ON audit_log (event_type, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_audit_log_created_at ON audit_log (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_user_scores_created_at ON user_scores (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_user_scores_user_created ON user_scores (user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_notifications_user_read_created ON notifications (user_id, is_read, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_course_notes_tenant_material ON course_notes (tenant_id, study_material_id)",
    "CREATE INDEX IF NOT EXISTS ix_billing_events_tenant_created ON billing_events (tenant_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_billing_events_stripe_event ON billing_events (stripe_event_id)",
    "CREATE INDEX IF NOT EXISTS ix_announcements_tenant_active ON announcements (tenant_id, is_active)",
    "CREATE INDEX IF NOT EXISTS ix_exams_tenant_id ON exams (tenant_id)",
    "CREATE INDEX IF NOT EXISTS ix_study_materials_tenant_id ON study_materials (tenant_id)",
    "CREATE INDEX IF NOT EXISTS ix_tasks_tenant_due ON tasks (tenant_id, due_date)",
)

# Tables included in ANALYZE during maintenance (planner stats refresh)
ANALYZE_TABLES = (
    'users', 'tenants', 'notifications', 'user_scores', 'audit_log',
    'support_tickets', 'course_notes', 'exams', 'study_materials',
    'billing_events', 'tenant_invites', 'announcements', 'tasks',
)


@dataclass(frozen=True)
class SqlOptimizationSpec:
    """One applyable optimization the CEO module can run without manual SQL."""
    key: str
    tier: str  # safe | manual | advisory
    action_type: str  # run_sql | create_index (alias)
    reason: str
    ddl: str
    index_name: str | None = None  # for existence checks


# Parsed from PERFORMANCE_INDEX_DDL for agent recommendations
def _index_specs_from_ddl() -> tuple[SqlOptimizationSpec, ...]:
    specs = []
    for ddl in PERFORMANCE_INDEX_DDL:
        # CREATE INDEX IF NOT EXISTS name ON table (cols)
        parts = ddl.replace('CREATE INDEX IF NOT EXISTS ', '').split(' ON ', 1)
        if len(parts) != 2:
            continue
        name, rest = parts[0].strip(), parts[1].strip()
        table = rest.split('(', 1)[0].strip()
        specs.append(
            SqlOptimizationSpec(
                key=name,
                tier='safe',
                action_type='run_sql',
                reason=f'Performance index on {table} ({name}).',
                ddl=ddl,
                index_name=name,
            )
        )
    return tuple(specs)


SQL_OPTIMIZATION_CATALOG: tuple[SqlOptimizationSpec, ...] = _index_specs_from_ddl() + (
    SqlOptimizationSpec(
        key='extension_pg_trgm',
        tier='manual',
        action_type='run_sql',
        reason='Enables fuzzy text search for platform user name/email ILIKE queries.',
        ddl='CREATE EXTENSION IF NOT EXISTS pg_trgm',
        index_name=None,
    ),
    SqlOptimizationSpec(
        key='ix_users_first_name_trgm',
        tier='manual',
        action_type='run_sql',
        reason='GIN trigram index for fast fuzzy search on users.first_name.',
        ddl='CREATE INDEX IF NOT EXISTS ix_users_first_name_trgm ON users USING GIN (first_name gin_trgm_ops)',
        index_name='ix_users_first_name_trgm',
    ),
    SqlOptimizationSpec(
        key='ix_users_last_name_trgm',
        tier='manual',
        action_type='run_sql',
        reason='GIN trigram index for fast fuzzy search on users.last_name.',
        ddl='CREATE INDEX IF NOT EXISTS ix_users_last_name_trgm ON users USING GIN (last_name gin_trgm_ops)',
        index_name='ix_users_last_name_trgm',
    ),
    SqlOptimizationSpec(
        key='ix_users_email_trgm',
        tier='manual',
        action_type='run_sql',
        reason='GIN trigram index for fast fuzzy search on users.employee_email.',
        ddl='CREATE INDEX IF NOT EXISTS ix_users_email_trgm ON users USING GIN (employee_email gin_trgm_ops)',
        index_name='ix_users_email_trgm',
    ),
    SqlOptimizationSpec(
        key='course_notes_fts_column',
        tier='manual',
        action_type='run_sql',
        reason='Add tsvector column for full-text search on course note content.',
        ddl='ALTER TABLE course_notes ADD COLUMN IF NOT EXISTS content_search tsvector',
        index_name=None,
    ),
    SqlOptimizationSpec(
        key='course_notes_fts_backfill',
        tier='manual',
        action_type='run_sql',
        reason='Backfill full-text search vectors for existing course notes.',
        ddl=(
            "UPDATE course_notes SET content_search = to_tsvector('english', coalesce(content, '')) "
            "WHERE content_search IS NULL"
        ),
        index_name=None,
    ),
    SqlOptimizationSpec(
        key='ix_course_notes_content_fts',
        tier='manual',
        action_type='run_sql',
        reason='GIN index for PostgreSQL full-text search on course notes.',
        ddl='CREATE INDEX IF NOT EXISTS ix_course_notes_content_fts ON course_notes USING GIN (content_search)',
        index_name='ix_course_notes_content_fts',
    ),
)

ADVISORY_MESSAGES: tuple[dict[str, str], ...] = (
    {
        'target_key': 'advisory_no_elasticsearch',
        'reason': (
            'Elasticsearch is not needed at current TrainIQ scale. '
            'Use this module for migrations, indexes, pg_trgm, and FTS instead.'
        ),
        'tier': 'advisory',
    },
    {
        'target_key': 'advisory_password_hashing',
        'reason': (
            'Password hashing (Werkzeug/bcrypt) runs automatically at login/register — '
            'no manual action required.'
        ),
        'tier': 'advisory',
    },
)


def all_schema_ddl() -> list[str]:
    """Every idempotent schema statement for bootstrap."""
    out = list(TENANT_COLUMN_DDL) + list(TABLE_COLUMN_DDL)
    for catalog_table in CATALOG_TABLES:
        out.append(
            f"ALTER TABLE {catalog_table} ADD COLUMN IF NOT EXISTS "
            f"tenant_id INTEGER REFERENCES tenants(id)"
        )
    out.extend(PERFORMANCE_INDEX_DDL)
    return out
