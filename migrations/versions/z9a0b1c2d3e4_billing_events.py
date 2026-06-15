"""Billing events + tenant billing period columns

Revision ID: z9a0b1c2d3e4
Revises: y8z9a0b1c2d3
"""
from alembic import op
import sqlalchemy as sa


revision = 'z9a0b1c2d3e4'
down_revision = 'y8z9a0b1c2d3'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tenant_cols = {c['name'] for c in insp.get_columns('tenants')}

    if 'stripe_subscription_id' not in tenant_cols:
        op.add_column('tenants', sa.Column('stripe_subscription_id', sa.String(120), nullable=True))
    if 'billing_period_start' not in tenant_cols:
        op.add_column('tenants', sa.Column('billing_period_start', sa.DateTime(), nullable=True))
    if 'billing_period_end' not in tenant_cols:
        op.add_column('tenants', sa.Column('billing_period_end', sa.DateTime(), nullable=True))

    if 'billing_events' not in insp.get_table_names():
        op.create_table(
            'billing_events',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('tenant_id', sa.Integer(), nullable=False),
            sa.Column('idempotency_key', sa.String(180), nullable=False),
            sa.Column('source', sa.String(40), nullable=False),
            sa.Column('status', sa.String(30), nullable=False, server_default='applied'),
            sa.Column('plan_id', sa.String(50), nullable=False),
            sa.Column('billing_cycle', sa.String(20), nullable=False, server_default='monthly'),
            sa.Column('amount_cents', sa.Integer(), nullable=True),
            sa.Column('stripe_event_id', sa.String(120), nullable=True),
            sa.Column('stripe_session_id', sa.String(120), nullable=True),
            sa.Column('stripe_subscription_id', sa.String(120), nullable=True),
            sa.Column('billing_period_start', sa.DateTime(), nullable=True),
            sa.Column('billing_period_end', sa.DateTime(), nullable=True),
            sa.Column('details', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('idempotency_key'),
            sa.UniqueConstraint('stripe_event_id'),
            sa.UniqueConstraint('stripe_session_id'),
        )
        op.create_index('ix_billing_events_tenant_id', 'billing_events', ['tenant_id'])


def downgrade():
    op.drop_table('billing_events')
    for col in ('billing_period_end', 'billing_period_start', 'stripe_subscription_id'):
        try:
            op.drop_column('tenants', col)
        except Exception:
            pass
