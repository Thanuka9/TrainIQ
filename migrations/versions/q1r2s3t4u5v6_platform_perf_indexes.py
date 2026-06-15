"""Performance indexes for platform console and analytics queries

Revision ID: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
"""
from alembic import op
import sqlalchemy as sa


revision = 'q1r2s3t4u5v6'
down_revision = 'p0q1r2s3t4u5'
branch_labels = None
depends_on = None

# (index_name, table, columns)
INDEX_SPECS = [
    # Platform dashboards: user growth, per-tenant verified counts, lock review
    ('ix_users_join_date', 'users', ['join_date']),
    ('ix_users_tenant_verified', 'users', ['tenant_id', 'is_verified']),
    ('ix_users_is_locked', 'users', ['is_locked']),
    # Support queue filtering and per-user joins
    ('ix_support_tickets_status', 'support_tickets', ['status']),
    ('ix_support_tickets_user_id', 'support_tickets', ['user_id']),
    ('ix_support_tickets_created_at', 'support_tickets', ['created_at']),
    # Tenant filtering on plan/status, trial reminders, growth charts
    ('ix_tenants_plan', 'tenants', ['plan']),
    ('ix_tenants_status', 'tenants', ['status']),
    ('ix_tenants_trial_ends_at', 'tenants', ['trial_ends_at']),
    ('ix_tenants_created_at', 'tenants', ['created_at']),
    # Pending invite counts per tenant
    ('ix_tenant_invites_tenant_id', 'tenant_invites', ['tenant_id']),
    ('ix_tenant_invites_used_at', 'tenant_invites', ['used_at']),
    # Security feed: 7-day windows per event type
    ('ix_audit_logs_event_created', 'audit_logs', ['event_type', 'created_at']),
    # Analytics date filters on exam attempts
    ('ix_user_scores_created_at', 'user_scores', ['created_at']),
]


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())

    existing = set()
    for tbl in tables:
        for idx in insp.get_indexes(tbl):
            existing.add(idx['name'])

    for name, tbl, cols in INDEX_SPECS:
        if tbl not in tables or name in existing:
            continue
        tbl_cols = {c['name'] for c in insp.get_columns(tbl)}
        if not all(c in tbl_cols for c in cols):
            continue
        op.create_index(name, tbl, cols, unique=False)


def downgrade():
    for name, tbl, _cols in reversed(INDEX_SPECS):
        try:
            op.drop_index(name, table_name=tbl)
        except Exception:
            pass
