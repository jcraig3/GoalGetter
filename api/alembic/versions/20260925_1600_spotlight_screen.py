"""A screen about one person.

**The observation this came from is a workaround, not a feature request.** In a
real 157-user account, nearly every hand-authored message screen turned out to
be an image of one rep, made in an image editor and uploaded. People were
already building this screen; the product just had no template for it, so the
version on the wall went stale the moment somebody's numbers changed.

A spotlight names either a person, a board, or both:

    person only     "employee of the month" — a face, and what they have won
    board only      whoever leads it right now, updated on every refresh
    both            that person's standing on that board

The board-only form is the one that makes this a product feature rather than a
slide somebody edits by hand each month.

Revision ID: f3a1c8d92b47
Revises: d94a5c02e1f7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a1c8d92b47"
down_revision: str | None = "d94a5c02e1f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The kinds before and after, written out rather than built from a list, so a
#: later change to `SCREEN_KINDS` in the model cannot silently rewrite what this
#: migration did.
KINDS_BEFORE = (
    "'leaderboard', 'goal', 'competition', 'achievements', 'image', 'video', "
    "'message'"
)
KINDS_AFTER = KINDS_BEFORE + ", 'spotlight'"

PAYLOAD_BEFORE = (
    "(kind = 'leaderboard' AND leaderboard_id IS NOT NULL) OR "
    "(kind = 'goal' AND goal_id IS NOT NULL) OR "
    "(kind = 'competition' AND competition_id IS NOT NULL) OR "
    "(kind = 'achievements') OR "
    "(kind IN ('image', 'video') AND url IS NOT NULL) OR "
    "(kind = 'message' AND title IS NOT NULL)"
)
PAYLOAD_AFTER = PAYLOAD_BEFORE + (
    " OR (kind = 'spotlight' AND (user_id IS NOT NULL OR leaderboard_id IS NOT NULL))"
)


def upgrade() -> None:
    # CASCADE, like every other payload pointer here: a spotlight whose person
    # was deleted cannot render, and the CHECK would refuse to let it sit with
    # a null id anyway.
    op.add_column(
        "channel_screen",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.drop_constraint("kind_valid", "channel_screen", type_="check")
    op.create_check_constraint(
        "kind_valid", "channel_screen", f"kind IN ({KINDS_AFTER})"
    )
    op.drop_constraint("payload_matches_kind", "channel_screen", type_="check")
    op.create_check_constraint(
        "payload_matches_kind", "channel_screen", PAYLOAD_AFTER
    )


def downgrade() -> None:
    # The rows go first. Narrowing the CHECK while a spotlight still exists
    # would fail the migration halfway and leave the constraint dropped.
    op.execute("DELETE FROM channel_screen WHERE kind = 'spotlight'")
    op.drop_constraint("payload_matches_kind", "channel_screen", type_="check")
    op.create_check_constraint(
        "payload_matches_kind", "channel_screen", PAYLOAD_BEFORE
    )
    op.drop_constraint("kind_valid", "channel_screen", type_="check")
    op.create_check_constraint(
        "kind_valid", "channel_screen", f"kind IN ({KINDS_BEFORE})"
    )
    op.drop_column("channel_screen", "user_id")
