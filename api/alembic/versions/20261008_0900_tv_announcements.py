"""Announcements for the TVs, and each time one was sent (Phase 25).

Revision ID: c1e5a2f8d369
Revises: b9d4f1e7c258
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1e5a2f8d369"
down_revision: str | None = "b9d4f1e7c258"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tv_announcement",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("body", sa.String(500), nullable=True),
        sa.Column("hold_seconds", sa.Integer(), nullable=False),
        sa.Column("background", postgresql.JSONB(), nullable=True),
        sa.Column("media_url", sa.String(500), nullable=True),
        sa.Column("media_start_seconds", sa.Integer(), nullable=True),
        sa.Column("sound_url", sa.String(100), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tv_announcement_org", "tv_announcement", ["organization_id", "created_at"])
    op.create_table(
        "tv_announcement_send",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organization.id", ondelete="CASCADE"), nullable=False),
        sa.Column("announcement_id", sa.BigInteger(), sa.ForeignKey("tv_announcement.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), sa.ForeignKey("channel.id", ondelete="CASCADE"), nullable=True),
        sa.Column("sent_by_user_id", sa.BigInteger(), sa.ForeignKey("user_account.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tv_announcement_send_pending", "tv_announcement_send", ["organization_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_tv_announcement_send_pending", table_name="tv_announcement_send")
    op.drop_table("tv_announcement_send")
    op.drop_index("ix_tv_announcement_org", table_name="tv_announcement")
    op.drop_table("tv_announcement")
