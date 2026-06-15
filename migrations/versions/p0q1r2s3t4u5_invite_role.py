"""Add role to tenant invites

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
"""
from alembic import op
import sqlalchemy as sa


revision = 'p0q1r2s3t4u5'
down_revision = 'o9p0q1r2s3t4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'tenant_invites',
        sa.Column('role', sa.String(32), nullable=True, server_default='learner'),
    )


def downgrade():
    op.drop_column('tenant_invites', 'role')
