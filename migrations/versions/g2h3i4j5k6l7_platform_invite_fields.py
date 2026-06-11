"""Additional SaaS fields: invite-only, suspension metadata, Stripe ref.

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
"""
from alembic import op
import sqlalchemy as sa


revision = 'g2h3i4j5k6l7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tenants', sa.Column('stripe_customer_id', sa.String(120), nullable=True))
    op.add_column('tenants', sa.Column('enable_invite_only', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('suspended_at', sa.DateTime(), nullable=True))
    op.add_column('tenants', sa.Column('suspended_reason', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('tenants', 'suspended_reason')
    op.drop_column('tenants', 'suspended_at')
    op.drop_column('tenants', 'enable_invite_only')
    op.drop_column('tenants', 'stripe_customer_id')
