"""User preference: hide trial setup checklist.

Revision ID: l1m2n3o4p5q6
Revises: k0l1m2n3o4p5
"""
from alembic import op
import sqlalchemy as sa


revision = 'l1m2n3o4p5q6'
down_revision = 'k0l1m2n3o4p5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column('trial_checklist_dismissed', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade():
    op.drop_column('users', 'trial_checklist_dismissed')
