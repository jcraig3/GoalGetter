"""A notification can be recorded without being announced (7.2, Q2-11).

Revision ID: c7e2a9d4f135
Revises: b5d1f3a7c824
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e2a9d4f135"
down_revision: str | None = "b5d1f3a7c824"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notification",
        sa.Column("quiet", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("notification", "quiet")
