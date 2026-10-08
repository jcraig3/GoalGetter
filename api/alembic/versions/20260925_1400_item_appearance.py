"""Let a board, a goal or a contest carry its own look.

**"Shark Week is blue everywhere it appears" is a different statement from "this
slide is blue".** Until now a screen could be themed and the thing behind it
could not, so an organization running the same contest on four TVs had to set
its colours four times and keep them in step by hand — which is how one wall
ends up a month behind the others.

The chain becomes:

    organization -> item -> channel -> screen
    brand           its own    the venue  this slide

**The item sits before the channel, deliberately.** A venue's concerns beat a
thing's own identity: "this TV is in a lobby, show initials only" has to win over
"this contest is themed red", because the legibility and privacy decisions belong
to the room the screen is in, not to the contest being shown.

Revision ID: d94a5c02e1f7
Revises: c1e73b9a4f28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d94a5c02e1f7"
down_revision: str | None = "c1e73b9a4f28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Everything a screen can point at. Empty rather than null, so nothing
#: downstream has to tell "never customised" from "customised back to nothing" —
#: both mean inherit.
TABLES = ("leaderboard", "goal", "competition")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "appearance",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
        )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_column(table, "appearance")
