"""Whether colleagues can see each other's profiles (9.5).

Revision ID: e9a4c2b7d358
Revises: d8f3b1c6e247
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9a4c2b7d358"
down_revision: str | None = "d8f3b1c6e247"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization",
        sa.Column("profiles_public", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("organization", "profiles_public")
