"""Announcements into chat channels: what to announce, and where.

A destination is a Teams channel reached through its own Workflows link — the
replacement Microsoft made for channel webhooks when it retired them in May
2026. Graph cannot post to a channel as an application, only as a signed-in
person, and an announcement feed that stops the day that person leaves is not
one to build on.

Deliveries are one row per win per channel, so a restarted job or a team goal
reaching eight people is still one post.

Revision ID: d8e1a27c6f50
Revises: c3d6f15b8e49
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d8e1a27c6f50"
down_revision: str | None = "c3d6f15b8e49"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "announcement_destination",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("webhook_url", sa.Text(), nullable=False),
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("office_id", sa.BigInteger(), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_notification_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('teams', 'slack')", name="announcement_kind_valid"),
        sa.CheckConstraint("office_id IS NULL OR team_id IS NULL", name="announcement_one_scope"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["office_id"], ["office.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["team.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_announcement_destination_org", "announcement_destination", ["organization_id"])

    op.create_table(
        "announcement_delivery",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("destination_id", sa.BigInteger(), nullable=False),
        sa.Column("notification_id", sa.BigInteger(), nullable=True),
        sa.Column("win_key", sa.String(length=200), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'retrying', 'sent', 'gave_up')",
            name="announcement_delivery_status_valid",
        ),
        sa.ForeignKeyConstraint(["destination_id"], ["announcement_destination.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["notification_id"], ["notification.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_announcement_delivery_once", "announcement_delivery",
        ["destination_id", "win_key"], unique=True,
    )
    op.create_index(
        "ix_announcement_delivery_due", "announcement_delivery",
        ["destination_id", "next_attempt_at"],
        postgresql_where=sa.text("status IN ('pending', 'retrying')"),
    )


def downgrade() -> None:
    op.drop_index("ix_announcement_delivery_due", table_name="announcement_delivery")
    op.drop_index("uq_announcement_delivery_once", table_name="announcement_delivery")
    op.drop_table("announcement_delivery")
    op.drop_index("ix_announcement_destination_org", table_name="announcement_destination")
    op.drop_table("announcement_destination")
