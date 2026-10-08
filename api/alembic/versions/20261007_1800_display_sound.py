"""A screen's browser holding sound back, as it reports it (Phase 24).

Revision ID: b9d4f1e7c258
Revises: a8c3e0d6b147
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9d4f1e7c258"
down_revision: str | None = "a8c3e0d6b147"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("display", sa.Column("sound_blocked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("display", "sound_blocked_at")
