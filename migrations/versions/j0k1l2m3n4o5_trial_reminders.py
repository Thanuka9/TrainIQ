"""Trial reminder tracking columns.

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
"""
from alembic import op
import sqlalchemy as sa


revision = 'j0k1l2m3n4o5'
down_revision = 'i9j0k1l2m3n4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tenants', sa.Column('trial_reminder_7d_at', sa.DateTime(), nullable=True))
    op.add_column('tenants', sa.Column('trial_reminder_1d_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('tenants', 'trial_reminder_1d_at')
    op.drop_column('tenants', 'trial_reminder_7d_at')
