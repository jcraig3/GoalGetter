"""When a hosting trial nobody kept was undone, for the Inbox (Phase 23).

Revision ID: a8c3e0d6b147
Revises: f7b2d9c5a036
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8c3e0d6b147"
down_revision: str | None = "f7b2d9c5a036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hosting_config", sa.Column("trial_expired_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("hosting_config", "trial_expired_at")
