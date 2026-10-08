"""Let an admin write what a celebration says.

Until now an achievement announced itself in a fixed shape — the rule's name as
the heading and "Peter Parker — $6,200" underneath. That is correct and it is
the same sentence every time, which is what makes a floor stop looking up.

`message` holds one alternative per line. Empty keeps the fixed shape, so every
rule that already exists keeps saying exactly what it said.

Revision ID: a2f6c90d5b31
Revises: c4b81f27ea60
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2f6c90d5b31"
down_revision: str | None = "c4b81f27ea60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # TEXT rather than a bounded VARCHAR: the limit that matters is per line
    # and is about what reads across a room, which a column width cannot
    # express. `app/merge_tags.py` enforces it where the sentence is.
    op.add_column(
        "achievement_rule",
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("achievement_rule", "message")
