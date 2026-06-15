"""Final notification improvements — read_at + dedupe uniqueness

Revision ID: x7y8z9a0b1c2
Revises: w6x7y8z9a0b1
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa


revision = "x7y8z9a0b1c2"
down_revision = "w6x7y8z9a0b1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notifications", sa.Column("read_at", sa.DateTime(), nullable=True))

    conn = op.get_bind()
    conn.execute(sa.text("""
        DELETE FROM notifications
        WHERE dedupe_key IS NOT NULL
          AND id NOT IN (
            SELECT MIN(id)
            FROM notifications
            WHERE dedupe_key IS NOT NULL
            GROUP BY user_id, dedupe_key
          )
    """))

    try:
        op.create_index(
            "uq_notifications_user_dedupe",
            "notifications",
            ["user_id", "dedupe_key"],
            unique=True,
            postgresql_where=sa.text("dedupe_key IS NOT NULL"),
            sqlite_where=sa.text("dedupe_key IS NOT NULL"),
        )
    except TypeError:
        op.create_index(
            "uq_notifications_user_dedupe",
            "notifications",
            ["user_id", "dedupe_key"],
            unique=True,
        )


def downgrade():
    op.drop_index("uq_notifications_user_dedupe", table_name="notifications")
    op.drop_column("notifications", "read_at")
