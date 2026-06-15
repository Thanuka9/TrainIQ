"""Add course_notes table for learner notes

Revision ID: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
"""
from alembic import op
import sqlalchemy as sa


revision = 't4u5v6w7x8y9'
down_revision = 's3t4u5v6w7x8'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'course_notes' in insp.get_table_names():
        return
    op.create_table(
        'course_notes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('study_material_id', sa.Integer(), nullable=False),
        sa.Column('asset_id', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('page_num', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['study_material_id'], ['study_materials.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'study_material_id', 'asset_id', 'page_num',
            name='uq_course_note_scope',
        ),
    )
    op.create_index('ix_course_notes_user_material', 'course_notes', ['user_id', 'study_material_id'])
    op.create_index(op.f('ix_course_notes_user_id'), 'course_notes', ['user_id'], unique=False)
    op.create_index(op.f('ix_course_notes_study_material_id'), 'course_notes', ['study_material_id'], unique=False)
    op.create_index(op.f('ix_course_notes_tenant_id'), 'course_notes', ['tenant_id'], unique=False)


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if 'course_notes' not in insp.get_table_names():
        return
    op.drop_index(op.f('ix_course_notes_tenant_id'), table_name='course_notes')
    op.drop_index(op.f('ix_course_notes_study_material_id'), table_name='course_notes')
    op.drop_index(op.f('ix_course_notes_user_id'), table_name='course_notes')
    op.drop_index('ix_course_notes_user_material', table_name='course_notes')
    op.drop_table('course_notes')
