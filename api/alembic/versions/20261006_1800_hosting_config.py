"""HTTPS set up from the app (Phase 20).

Revision ID: d5f9b7a3e814
Revises: c4e8a6f2d793
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5f9b7a3e814"
down_revision: str | None = "c4e8a6f2d793"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hosting_config",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("https_on", sa.Boolean(), nullable=False),
        sa.Column("https_host", sa.String(253), nullable=False),
        sa.Column("certificate", sa.String(16), nullable=False),
        sa.Column("dns_provider", sa.String(32), nullable=False),
        sa.Column("dns_api_token_encrypted", sa.Text(), nullable=True),
        sa.Column("acme_email", sa.String(320), nullable=False),
        sa.Column("env_snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("hosting_config")
