"""Add asset_progress JSONB to user_progress

Revision ID: s3t4u5v6w7x8
Revises: r2s3t4u5v6w7
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 's3t4u5v6w7x8'
down_revision = 'r2s3t4u5v6w7'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = {c['name'] for c in insp.get_columns('user_progress')}
    if 'asset_progress' not in cols:
        op.add_column(
            'user_progress',
            sa.Column('asset_progress', JSONB, nullable=False, server_default='{}'),
        )


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = {c['name'] for c in insp.get_columns('user_progress')}
    if 'asset_progress' in cols:
        op.drop_column('user_progress', 'asset_progress')
