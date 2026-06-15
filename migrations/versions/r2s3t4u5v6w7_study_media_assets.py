"""Add media_assets JSONB to study_materials

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'r2s3t4u5v6w7'
down_revision = 'q1r2s3t4u5v6'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = {c['name'] for c in insp.get_columns('study_materials')}
    if 'media_assets' not in cols:
        op.add_column(
            'study_materials',
            sa.Column('media_assets', JSONB, nullable=False, server_default='[]'),
        )


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    cols = {c['name'] for c in insp.get_columns('study_materials')}
    if 'media_assets' in cols:
        op.drop_column('study_materials', 'media_assets')
