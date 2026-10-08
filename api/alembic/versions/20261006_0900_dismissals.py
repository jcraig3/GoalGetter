"""Dismissing notifications: the bell, the Inbox and Home's banners (12).

Revision ID: a2c6e4d9b571
Revises: f1b5d3c8a469
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2c6e4d9b571"
down_revision: str | None = "f1b5d3c8a469"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification", sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "dismissal",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("surface", sa.String(16), nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("fingerprint", sa.String(300), nullable=False),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("dismissed_on", sa.Date(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("user_id", "surface", "key", name="uq_dismissal_item"),
    )
    op.create_index("ix_dismissal_user_id", "dismissal", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_dismissal_user_id", table_name="dismissal")
    op.drop_table("dismissal")
    op.drop_column("notification", "dismissed_at")
