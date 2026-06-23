"""Platform ops run audit table

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
"""
from alembic import op
import sqlalchemy as sa


revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'platform_ops_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=40), nullable=False),
        sa.Column('trigger', sa.String(length=20), nullable=False, server_default='scheduled'),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('snapshot_id', sa.Integer(), nullable=True),
        sa.Column('issue_count', sa.Integer(), nullable=True),
        sa.Column('indexes_applied', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('indexes_failed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('result_json', sa.Text(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['snapshot_id'], ['db_performance_snapshots.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_platform_ops_runs_started_at', 'platform_ops_runs', ['started_at'])
    op.create_index('ix_platform_ops_runs_source', 'platform_ops_runs', ['source'])
    op.create_index('ix_platform_ops_runs_status', 'platform_ops_runs', ['status'])


def downgrade():
    op.drop_index('ix_platform_ops_runs_status', table_name='platform_ops_runs')
    op.drop_index('ix_platform_ops_runs_source', table_name='platform_ops_runs')
    op.drop_index('ix_platform_ops_runs_started_at', table_name='platform_ops_runs')
    op.drop_table('platform_ops_runs')
