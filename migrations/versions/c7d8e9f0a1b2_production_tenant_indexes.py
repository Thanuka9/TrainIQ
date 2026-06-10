"""Production tenant columns and indexes

Revision ID: c7d8e9f0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-06-10 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'c7d8e9f0a1b2'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None

TENANT_TABLES = ('exams', 'study_materials', 'tasks', 'clients', 'departments')


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)

    # tenants.office_key
    cols = {c['name'] for c in insp.get_columns('tenants')}
    if 'office_key' not in cols:
        op.add_column('tenants', sa.Column('office_key', sa.String(50), nullable=True))
        op.create_index('ix_tenants_office_key', 'tenants', ['office_key'], unique=True)

    if 'exams' in insp.get_table_names():
        ec = {c['name'] for c in insp.get_columns('exams')}
        if 'tenant_id' not in ec:
            op.add_column('exams', sa.Column('tenant_id', sa.Integer(), nullable=True))
        if 'passing_score' not in ec:
            op.add_column('exams', sa.Column('passing_score', sa.Float(), server_default='70.0', nullable=True))

    for tbl in TENANT_TABLES:
        if tbl not in insp.get_table_names():
            continue
        tc = {c['name'] for c in insp.get_columns(tbl)}
        if 'tenant_id' not in tc:
            op.add_column(tbl, sa.Column('tenant_id', sa.Integer(), nullable=True))

    qc = {c['name'] for c in insp.get_columns('questions')} if 'questions' in insp.get_table_names() else set()
    if 'question_type' not in qc:
        op.add_column('questions', sa.Column('question_type', sa.String(50), server_default='single_choice', nullable=True))

    # Indexes (idempotent via try/except for PG)
    index_specs = [
        ('ix_users_tenant_id', 'users', ['tenant_id']),
        ('ix_exams_tenant_id', 'exams', ['tenant_id']),
        ('ix_study_materials_tenant_id', 'study_materials', ['tenant_id']),
        ('ix_tasks_tenant_id', 'tasks', ['tenant_id']),
        ('ix_clients_tenant_id', 'clients', ['tenant_id']),
        ('ix_departments_tenant_id', 'departments', ['tenant_id']),
    ]
    existing_indexes = set()
    for tbl in insp.get_table_names():
        for idx in insp.get_indexes(tbl):
            existing_indexes.add(idx['name'])

    for name, tbl, cols in index_specs:
        if tbl in insp.get_table_names() and name not in existing_indexes:
            op.create_index(name, tbl, cols, unique=False)


def downgrade():
    for name, tbl, _ in [
        ('ix_departments_tenant_id', 'departments', None),
        ('ix_clients_tenant_id', 'clients', None),
        ('ix_tasks_tenant_id', 'tasks', None),
        ('ix_study_materials_tenant_id', 'study_materials', None),
        ('ix_exams_tenant_id', 'exams', None),
        ('ix_users_tenant_id', 'users', None),
    ]:
        try:
            op.drop_index(name, table_name=tbl)
        except Exception:
            pass
