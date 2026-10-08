"""Count the facts a sync withdrew because the source no longer has them.

Its own counter rather than folding into `rows_written`, for the same reason
`conflicts` has one: a deletion is not a write, and a number that goes down is
exactly the thing somebody wants to see on a run rather than infer from a total
that moved.

Revision ID: f4c82e6b1d95
Revises: e7b3d5a91f42
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4c82e6b1d95"
down_revision: str | None = "e7b3d5a91f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sync_run",
        sa.Column(
            "rows_removed", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("sync_run", "rows_removed")
