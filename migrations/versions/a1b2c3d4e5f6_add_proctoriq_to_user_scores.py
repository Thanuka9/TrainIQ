"""Add ProctorIQ fields to user_scores

Revision ID: a1b2c3d4e5f6
Revises: 19ca565aef45
Create Date: 2026-06-08 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '19ca565aef45'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user_scores', schema=None) as batch_op:
        batch_op.add_column(sa.Column('trust_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('proctor_events', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('proctor_narrative', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('user_scores', schema=None) as batch_op:
        batch_op.drop_column('proctor_narrative')
        batch_op.drop_column('proctor_events')
        batch_op.drop_column('trust_score')
