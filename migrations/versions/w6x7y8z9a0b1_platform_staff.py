"""Platform staff fields and invites

Revision ID: w6x7y8z9a0b1
Revises: v5w6x7y8z9a0
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa


revision = "w6x7y8z9a0b1"
down_revision = "v5w6x7y8z9a0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("is_platform_staff", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("platform_staff_role", sa.String(30), nullable=True))

    op.create_table(
        "platform_staff_invites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(120), nullable=False),
        sa.Column("first_name", sa.String(50), nullable=False),
        sa.Column("last_name", sa.String(50), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("token", sa.String(128), nullable=False),
        sa.Column("invited_by_user_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_platform_staff_invites_email", "platform_staff_invites", ["email"])


def downgrade():
    op.drop_index("ix_platform_staff_invites_email", table_name="platform_staff_invites")
    op.drop_table("platform_staff_invites")
    op.drop_column("users", "platform_staff_role")
    op.drop_column("users", "is_platform_staff")
