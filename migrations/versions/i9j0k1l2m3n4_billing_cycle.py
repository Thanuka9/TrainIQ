"""Billing cycle column on tenants.

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
"""
from alembic import op
import sqlalchemy as sa


revision = 'i9j0k1l2m3n4'
down_revision = 'h8i9j0k1l2m3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'tenants',
        sa.Column('billing_cycle', sa.String(length=20), nullable=False, server_default='monthly'),
    )


def downgrade():
    op.drop_column('tenants', 'billing_cycle')
