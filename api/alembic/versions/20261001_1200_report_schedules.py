"""Scheduled report delivery: the coaching digest, emailed on a schedule.

Revision ID: a9d4e2b7c615
Revises: f2c8a6e1d934
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9d4e2b7c615"
down_revision: str | None = "f2c8a6e1d934"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_schedule",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("cadence", sa.String(length=16), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=True),
        sa.Column("hour", sa.SmallInteger(), nullable=False),
        sa.Column("recipient_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_slot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("cadence IN ('weekdays', 'weekly', 'monthly')", name="cadence_valid"),
        sa.CheckConstraint("hour BETWEEN 0 AND 23", name="hour_valid"),
        sa.CheckConstraint("weekday IS NULL OR weekday BETWEEN 0 AND 6", name="weekday_valid"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user_account.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_schedule_org", "report_schedule", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_report_schedule_org", table_name="report_schedule")
    op.drop_table("report_schedule")
