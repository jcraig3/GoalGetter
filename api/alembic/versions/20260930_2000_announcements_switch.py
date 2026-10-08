"""A master switch for posting wins into chat channels.

Each channel already has its own; this pauses every one at once.

Revision ID: f4a0c57e8b12
Revises: e2f9b36d4a71
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4a0c57e8b12"
down_revision: str | None = "e2f9b36d4a71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization",
        sa.Column("announcements_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("organization", "announcements_enabled")
