"""Database performance monitor tables

Revision ID: a0b1c2d3e4f5
Revises: z9a0b1c2d3e4
"""
from alembic import op
import sqlalchemy as sa


revision = 'a0b1c2d3e4f5'
down_revision = 'z9a0b1c2d3e4'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'db_performance_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collected_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('issue_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('recommendation_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('summary_json', sa.Text(), nullable=True),
        sa.Column('postgres_stats_json', sa.Text(), nullable=True),
        sa.Column('mongo_stats_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_db_performance_snapshots_collected_at', 'db_performance_snapshots', ['collected_at'])
    op.create_index('ix_db_performance_snapshots_status', 'db_performance_snapshots', ['status'])

    op.create_table(
        'db_optimization_recommendations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('snapshot_id', sa.Integer(), nullable=False),
        sa.Column('action_type', sa.String(length=40), nullable=False),
        sa.Column('target_key', sa.String(length=120), nullable=False),
        sa.Column('tier', sa.String(length=20), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('ddl', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('applied_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['snapshot_id'], ['db_performance_snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('snapshot_id', 'target_key', name='uq_db_opt_rec_snapshot_target'),
    )
    op.create_index(
        'ix_db_optimization_recommendations_snapshot_id',
        'db_optimization_recommendations',
        ['snapshot_id'],
    )
    op.create_index(
        'ix_db_optimization_recommendations_status',
        'db_optimization_recommendations',
        ['status'],
    )


def downgrade():
    op.drop_index('ix_db_optimization_recommendations_status', table_name='db_optimization_recommendations')
    op.drop_index('ix_db_optimization_recommendations_snapshot_id', table_name='db_optimization_recommendations')
    op.drop_table('db_optimization_recommendations')
    op.drop_index('ix_db_performance_snapshots_status', table_name='db_performance_snapshots')
    op.drop_index('ix_db_performance_snapshots_collected_at', table_name='db_performance_snapshots')
    op.drop_table('db_performance_snapshots')
