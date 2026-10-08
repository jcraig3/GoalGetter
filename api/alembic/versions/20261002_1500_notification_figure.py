"""The number a win was for, said once and kept (7.9).

Revision ID: d8f3b1c6e247
Revises: c7e2a9d4f135
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8f3b1c6e247"
down_revision: str | None = "c7e2a9d4f135"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notification", sa.Column("figure", sa.String(length=60), nullable=True))


def downgrade() -> None:
    op.drop_column("notification", "figure")
