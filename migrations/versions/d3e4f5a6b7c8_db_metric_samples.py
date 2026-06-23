"""db_metric_samples time-series table

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
"""
from alembic import op
import sqlalchemy as sa


revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'db_metric_samples',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collected_at', sa.DateTime(), nullable=False),
        sa.Column('snapshot_id', sa.Integer(), nullable=True),
        sa.Column('metric_key', sa.String(length=80), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['snapshot_id'], ['db_performance_snapshots.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_db_metric_samples_collected_at', 'db_metric_samples', ['collected_at'])
    op.create_index('ix_db_metric_samples_metric_key', 'db_metric_samples', ['metric_key'])
    op.create_index('ix_db_metric_samples_snapshot_id', 'db_metric_samples', ['snapshot_id'])
    op.create_index('ix_db_metric_samples_key_time', 'db_metric_samples', ['metric_key', 'collected_at'])


def downgrade():
    op.drop_index('ix_db_metric_samples_key_time', table_name='db_metric_samples')
    op.drop_index('ix_db_metric_samples_snapshot_id', table_name='db_metric_samples')
    op.drop_index('ix_db_metric_samples_metric_key', table_name='db_metric_samples')
    op.drop_index('ix_db_metric_samples_collected_at', table_name='db_metric_samples')
    op.drop_table('db_metric_samples')
