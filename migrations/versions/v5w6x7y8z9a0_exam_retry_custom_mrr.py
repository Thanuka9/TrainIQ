"""Exam retry cooldown + tenant custom MRR override

Revision ID: v5w6x7y8z9a0
Revises: u5v6w7x8y9z0
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa


revision = "v5w6x7y8z9a0"
down_revision = "u5v6w7x8y9z0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("exams", sa.Column("retry_cooldown_days", sa.Integer(), nullable=True))
    op.add_column("tenants", sa.Column("custom_mrr_cents", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("tenants", "custom_mrr_cents")
    op.drop_column("exams", "retry_cooldown_days")
