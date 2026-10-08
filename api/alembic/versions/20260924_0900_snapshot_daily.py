"""Let a mapping keep one fact per row per day.

**The only way to get history out of a source that has none.** A pre-aggregated
view holds one row per person and a number that moves. Keyed by the person
alone, tomorrow's read overwrites today's and the week is unrecoverable — every
leaderboard can then only show the current figure, which is exactly the
limitation of the tools this shape of data comes from.

With this on, the row's id carries the date, so each day is its own fact and a
week is the sum of seven.

Defaults false, and stays opt-in. For a source with one row per *event* it would
be actively wrong: a deal keyed by deal id plus the date becomes a new deal every
day, and one sale turns into thirty.

Revision ID: f7c41d0e3a52
Revises: e4a7c93f1b28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7c41d0e3a52"
down_revision: str | None = "e4a7c93f1b28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_mapping",
        sa.Column(
            "snapshot_daily", sa.Boolean(), nullable=False, server_default="false"
        ),
    )


def downgrade() -> None:
    # Facts already written keep their dated ids; what is lost is the setting
    # that would write more of them. A source reverts to one fact per row.
    op.drop_column("source_mapping", "snapshot_daily")
