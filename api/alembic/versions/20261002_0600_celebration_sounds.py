"""Default celebration sounds per kind of win (6.17).

Revision ID: b5d1f3a7c824
Revises: a2c8e4f6b913
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "b5d1f3a7c824"
down_revision: str | None = "a2c8e4f6b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organization",
        sa.Column("celebration_sounds", JSONB(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("organization", "celebration_sounds")
