"""Where this deployment is, set in Settings (11.7).

Revision ID: b3d7f5e1c682
Revises: a2c6e4d9b571
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3d7f5e1c682"
down_revision: str | None = "a2c6e4d9b571"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("public_url", sa.String(300), nullable=True))


def downgrade() -> None:
    op.drop_column("organization", "public_url")
