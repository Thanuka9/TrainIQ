"""User Agreement acceptance tracking and audit table

Revision ID: y8z9a0b1c2d3
Revises: x7y8z9a0b1c2
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa


revision = "y8z9a0b1c2d3"
down_revision = "x7y8z9a0b1c2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("user_agreement_version", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("user_agreement_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_user_agreement_version", "users", ["user_agreement_version"])
    op.create_index("ix_users_user_agreement_at", "users", ["user_agreement_at"])

    op.create_table(
        "user_agreement_acceptances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("agreement_version", sa.String(20), nullable=False),
        sa.Column("document_hash", sa.String(64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_agreement_acceptances_user_id", "user_agreement_acceptances", ["user_id"])
    op.create_index("ix_user_agreement_acceptances_version", "user_agreement_acceptances", ["agreement_version"])
    op.create_index("ix_user_agreement_acceptances_accepted_at", "user_agreement_acceptances", ["accepted_at"])


def downgrade():
    op.drop_index("ix_user_agreement_acceptances_accepted_at", table_name="user_agreement_acceptances")
    op.drop_index("ix_user_agreement_acceptances_version", table_name="user_agreement_acceptances")
    op.drop_index("ix_user_agreement_acceptances_user_id", table_name="user_agreement_acceptances")
    op.drop_table("user_agreement_acceptances")
    op.drop_index("ix_users_user_agreement_at", table_name="users")
    op.drop_index("ix_users_user_agreement_version", table_name="users")
    op.drop_column("users", "user_agreement_at")
    op.drop_column("users", "user_agreement_version")
