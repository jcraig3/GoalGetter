"""What people actually call somebody.

**Closing a setting that has been offered and inert since Phase 4c.** The
Appearance tab lists "Their nickname" as a way to write names on a wall, and
there was nothing behind it — choosing it silently fell back to the full name.
The same class of thing as the light theme that was written and unreachable.

Short on purpose. A nickname is what a floor shouts across a room, not a second
biography: forty characters is "Sparky" and "Big Mike", and it is not a
sentence.

Revision ID: f19a4e6b2d80
Revises: e8d31a70c4b2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f19a4e6b2d80"
down_revision: str | None = "e8d31a70c4b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Empty rather than NULL, like `job_title` beside it: "has not set one" and
    # "set it to nothing" are the same state, and a nullable column would make
    # every reader decide which it was holding.
    op.add_column(
        "user_account",
        sa.Column(
            "nickname", sa.String(40), nullable=False, server_default=""
        ),
    )


def downgrade() -> None:
    op.drop_column("user_account", "nickname")
