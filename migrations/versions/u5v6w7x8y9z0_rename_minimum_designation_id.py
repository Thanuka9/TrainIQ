"""Rename exams.minimum_designation_level to minimum_designation_id

Revision ID: u5v6w7x8y9z0
Revises: t4u5v6w7x8y9
Create Date: 2026-06-14

"""
from alembic import op


revision = "u5v6w7x8y9z0"
down_revision = "t4u5v6w7x8y9"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "exams",
        "minimum_designation_level",
        new_column_name="minimum_designation_id",
    )


def downgrade():
    op.alter_column(
        "exams",
        "minimum_designation_id",
        new_column_name="minimum_designation_level",
    )
