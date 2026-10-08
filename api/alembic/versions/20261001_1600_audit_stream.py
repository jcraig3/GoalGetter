"""Sending the activity log to a SIEM as it grows.

Revision ID: e4c9d2a7f158
Revises: d8a3b6f1e592
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4c9d2a7f158"
down_revision: str | None = "d8a3b6f1e592"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_stream",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("url_encrypted", sa.Text(), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("header_name", sa.String(length=100), nullable=False),
        sa.Column("header_value_encrypted", sa.Text(), nullable=True),
        sa.Column("last_audit_id", sa.BigInteger(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("format IN ('json', 'splunk')", name="format_valid"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", name="uq_audit_stream_organization_id"),
    )


def downgrade() -> None:
    op.drop_table("audit_stream")
