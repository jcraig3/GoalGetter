"""Ask a television to reload itself.

A wall runs for months without anybody touching it, which is the point — and
is also why it is the hardest thing in the product to fix when it goes wrong.
A browser that has been open since a deploy three weeks ago is running the old
bundle; one that has wedged shows a frozen board and no way in. The screen is
on a wall, often high up, and the nearest keyboard is three rooms away.

So the feed carries a timestamp. The screen remembers the one it started with,
and reloads when it changes.

**A column, not a message queue.** The wall already polls every minute and this
rides along in the answer it was going to fetch anyway.

Revision ID: c1a8f34b7e25
Revises: b8e5c40a7d13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1a8f34b7e25"
down_revision: str | None = "b8e5c40a7d13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "display",
        sa.Column("reload_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("display", "reload_at")
