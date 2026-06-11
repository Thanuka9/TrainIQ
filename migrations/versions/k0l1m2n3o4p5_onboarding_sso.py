"""Onboarding drip tracking and Enterprise SSO columns.

Revision ID: k0l1m2n3o4p5
Revises: j0k1l2m3n4o5
"""
from alembic import op
import sqlalchemy as sa


revision = 'k0l1m2n3o4p5'
down_revision = 'j0k1l2m3n4o5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tenants', sa.Column('onboarding_welcome_at', sa.DateTime(), nullable=True))
    op.add_column('tenants', sa.Column('onboarding_drip_1_at', sa.DateTime(), nullable=True))
    op.add_column('tenants', sa.Column('onboarding_drip_3_at', sa.DateTime(), nullable=True))
    op.add_column('tenants', sa.Column('onboarding_drip_7_at', sa.DateTime(), nullable=True))
    op.add_column('tenants', sa.Column('sso_enabled', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('tenants', sa.Column('sso_provider', sa.String(30), nullable=True))
    op.add_column('tenants', sa.Column('sso_client_id', sa.String(255), nullable=True))
    op.add_column('tenants', sa.Column('sso_client_secret', sa.String(512), nullable=True))
    op.add_column('tenants', sa.Column('sso_issuer_url', sa.String(512), nullable=True))
    op.add_column('tenants', sa.Column('sso_tenant_domain', sa.String(255), nullable=True))


def downgrade():
    for col in (
        'sso_tenant_domain', 'sso_issuer_url', 'sso_client_secret', 'sso_client_id',
        'sso_provider', 'sso_enabled', 'onboarding_drip_7_at', 'onboarding_drip_3_at',
        'onboarding_drip_1_at', 'onboarding_welcome_at',
    ):
        op.drop_column('tenants', col)
