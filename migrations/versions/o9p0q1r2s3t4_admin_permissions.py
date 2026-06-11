"""Add user admin_permissions JSON overrides

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'o9p0q1r2s3t4'
down_revision = 'n8o9p0q1r2s3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column('admin_permissions', JSONB, nullable=True),
    )


def downgrade():
    op.drop_column('users', 'admin_permissions')
