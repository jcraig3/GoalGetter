"""Roles from groups on SSO sign-in.

Revision ID: b1e6f3a8d247
Revises: a9d4e2b7c615
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1e6f3a8d247"
down_revision: str | None = "a9d4e2b7c615"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sso_config", sa.Column("role_sync", sa.Boolean(), server_default="false", nullable=False))
    op.add_column(
        "sso_config",
        sa.Column("role_rules", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("sso_config", "role_rules")
    op.drop_column("sso_config", "role_sync")
