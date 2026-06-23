"""CEO maintenance run audit table

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
"""
from alembic import op
import sqlalchemy as sa


revision = 'b1c2d3e4f5a6'
down_revision = 'a0b1c2d3e4f5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'db_maintenance_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('restart_requested', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('restart_status', sa.String(length=20), nullable=True),
        sa.Column('steps_json', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_db_maintenance_runs_started_at', 'db_maintenance_runs', ['started_at'])
    op.create_index('ix_db_maintenance_runs_status', 'db_maintenance_runs', ['status'])


def downgrade():
    op.drop_index('ix_db_maintenance_runs_status', table_name='db_maintenance_runs')
    op.drop_index('ix_db_maintenance_runs_started_at', table_name='db_maintenance_runs')
    op.drop_table('db_maintenance_runs')
