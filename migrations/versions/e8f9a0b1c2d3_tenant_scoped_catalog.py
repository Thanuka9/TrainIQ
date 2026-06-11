"""Tenant-scoped catalog tables (categories, levels, areas, designations).

Revision ID: e8f9a0b1c2d3
Revises: c7d8e9f0a1b2
Create Date: 2026-06-08
"""
from alembic import op
import sqlalchemy as sa


revision = 'e8f9a0b1c2d3'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None


def _drop_unique_if_exists(table, name):
    conn = op.get_bind()
    conn.execute(sa.text(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}'))


def upgrade():
    for table in ('categories', 'levels', 'areas', 'designations'):
        op.add_column(table, sa.Column('tenant_id', sa.Integer(), nullable=True))
        op.create_foreign_key(
            f'fk_{table}_tenant_id',
            table,
            'tenants',
            ['tenant_id'],
            ['id'],
        )

    op.execute("UPDATE categories SET tenant_id = 1 WHERE tenant_id IS NULL")
    op.execute("UPDATE levels SET tenant_id = 1 WHERE tenant_id IS NULL")
    op.execute("UPDATE areas SET tenant_id = 1 WHERE tenant_id IS NULL")
    op.execute("UPDATE designations SET tenant_id = 1 WHERE tenant_id IS NULL")

    _drop_unique_if_exists('categories', 'categories_name_key')
    _drop_unique_if_exists('levels', 'levels_level_number_key')
    _drop_unique_if_exists('areas', 'areas_name_key')
    _drop_unique_if_exists('designations', 'designations_title_key')

    op.create_unique_constraint('uq_category_tenant_name', 'categories', ['tenant_id', 'name'])
    op.create_unique_constraint('uq_level_tenant_number', 'levels', ['tenant_id', 'level_number'])
    op.create_unique_constraint('uq_area_tenant_name', 'areas', ['tenant_id', 'name'])
    op.create_unique_constraint('uq_designation_tenant_title', 'designations', ['tenant_id', 'title'])


def downgrade():
    op.drop_constraint('uq_designation_tenant_title', 'designations', type_='unique')
    op.drop_constraint('uq_area_tenant_name', 'areas', type_='unique')
    op.drop_constraint('uq_level_tenant_number', 'levels', type_='unique')
    op.drop_constraint('uq_category_tenant_name', 'categories', type_='unique')

    op.create_unique_constraint('designations_title_key', 'designations', ['title'])
    op.create_unique_constraint('areas_name_key', 'areas', ['name'])
    op.create_unique_constraint('levels_level_number_key', 'levels', ['level_number'])
    op.create_unique_constraint('categories_name_key', 'categories', ['name'])

    for table in ('designations', 'areas', 'levels', 'categories'):
        op.drop_constraint(f'fk_{table}_tenant_id', table, type_='foreignkey')
        op.drop_column(table, 'tenant_id')
