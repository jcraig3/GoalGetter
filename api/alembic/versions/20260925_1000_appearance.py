"""One place each look comes from.

**Scattered customization is the mistake being avoided here.** The product this
is modelled on keeps its logo in two pages, fonts under Company Settings,
colours under Branding, per-competition colours in a wizard step and
per-celebration colours somewhere else again — so "why is this screen green?"
has five possible answers and no way to tell which.

One column, the same shape, at every level that can override: organization,
channel, and the individual screen. `appearance.resolve()` merges them
outermost-first, and `None` at any level means inherit.

JSONB rather than forty columns on three tables. The trade is that the database
cannot validate the contents, so `app/appearance.py` does — every read goes
through a model that drops keys it does not know, so a knob removed next year
stops arriving rather than lingering in rows for ever.

Revision ID: c1e73b9a4f28
Revises: b6d92e4f70c3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1e73b9a4f28"
down_revision: str | None = "b6d92e4f70c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Empty rather than null, so nothing downstream has to tell the two apart. A
#: layer that has never been customised and one customised back to nothing mean
#: the same thing: inherit.
TABLES = ("organization", "channel", "channel_screen")


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
