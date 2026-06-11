"""Tenant invite tokens for magic-link registration.

Revision ID: h8i9j0k1l2m3
Revises: g2h3i4j5k6l7
"""
from alembic import op
import sqlalchemy as sa


revision = 'h8i9j0k1l2m3'
down_revision = 'g2h3i4j5k6l7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'tenant_invites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('token', sa.String(length=128), nullable=False),
        sa.Column('invited_by_user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('used_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['invited_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['used_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )
    op.create_index('ix_tenant_invites_email', 'tenant_invites', ['email'])
    op.create_index('ix_tenant_invites_token', 'tenant_invites', ['token'])


def downgrade():
    op.drop_index('ix_tenant_invites_token', table_name='tenant_invites')
    op.drop_index('ix_tenant_invites_email', table_name='tenant_invites')
    op.drop_table('tenant_invites')
