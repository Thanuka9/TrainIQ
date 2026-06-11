"""SaaS tenant limits + Client/Department composite unique constraints.

Revision ID: f1a2b3c4d5e6
Revises: e8f9a0b1c2d3
"""
from alembic import op
import sqlalchemy as sa


revision = 'f1a2b3c4d5e6'
down_revision = 'e8f9a0b1c2d3'
branch_labels = None
depends_on = None


def _drop_unique_if_exists(table, name):
    conn = op.get_bind()
    conn.execute(sa.text(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}'))


def upgrade():
    op.add_column('tenants', sa.Column('plan', sa.String(50), nullable=False, server_default='trial'))
    op.add_column('tenants', sa.Column('status', sa.String(30), nullable=False, server_default='active'))
    op.add_column('tenants', sa.Column('max_users', sa.Integer(), nullable=False, server_default='50'))
    op.add_column('tenants', sa.Column('max_storage_mb', sa.Integer(), nullable=False, server_default='5120'))
    op.add_column('tenants', sa.Column('trial_ends_at', sa.DateTime(), nullable=True))
    op.add_column('tenants', sa.Column('billing_email', sa.String(120), nullable=True))

    _drop_unique_if_exists('clients', 'clients_name_key')
    _drop_unique_if_exists('departments', 'departments_name_key')
    op.create_unique_constraint('uq_client_tenant_name', 'clients', ['tenant_id', 'name'])
    op.create_unique_constraint('uq_department_tenant_name', 'departments', ['tenant_id', 'name'])


def downgrade():
    op.drop_constraint('uq_department_tenant_name', 'departments', type_='unique')
    op.drop_constraint('uq_client_tenant_name', 'clients', type_='unique')
    op.create_unique_constraint('departments_name_key', 'departments', ['name'])
    op.create_unique_constraint('clients_name_key', 'clients', ['name'])

    op.drop_column('tenants', 'billing_email')
    op.drop_column('tenants', 'trial_ends_at')
    op.drop_column('tenants', 'max_storage_mb')
    op.drop_column('tenants', 'max_users')
    op.drop_column('tenants', 'status')
    op.drop_column('tenants', 'plan')
