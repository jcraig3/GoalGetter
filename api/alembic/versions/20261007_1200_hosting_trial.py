"""A hosting change tried before it is kept, and Undo (Phase 22).

Revision ID: f7b2d9c5a036
Revises: e6a1c8b4f925
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7b2d9c5a036"
down_revision: str | None = "e6a1c8b4f925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hosting_config", sa.Column("previous", sa.JSON(), nullable=True))
    op.add_column("hosting_config", sa.Column("trial_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("hosting_config", "trial_until")
    op.drop_column("hosting_config", "previous")
