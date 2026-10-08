"""Two to four boards side by side on one slide.

**The question a comparison answers is one no single board can.** "Who is
calling and who is closing" is two boards, and a rotation showing them ninety
seconds apart makes the room hold one in their head while they wait for the
other. Side by side, the person who is top of one and bottom of the other is
visible in a glance — which is the conversation a sales floor actually wants to
have.

**A join table rather than four nullable columns.** Four columns would encode
the limit in the schema and need a migration to move it; they would also let a
board appear twice, and make "which order are they in" a question with no
answer. A row per panel with a position says all of it.

The 2-4 rule lives in the router rather than in a CHECK: it is a statement
about legibility on a television, not about integrity, and a screen that has
lost a board to a deletion should keep showing the rest rather than become
unstorable.

Revision ID: b7e04f5c1a93
Revises: f3a1c8d92b47
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e04f5c1a93"
down_revision: str | None = "f3a1c8d92b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS_BEFORE = (
    "'leaderboard', 'goal', 'competition', 'achievements', 'image', 'video', "
    "'message', 'spotlight'"
)
KINDS_AFTER = KINDS_BEFORE + ", 'comparison'"

PAYLOAD_BEFORE = (
    "(kind = 'leaderboard' AND leaderboard_id IS NOT NULL) OR "
    "(kind = 'goal' AND goal_id IS NOT NULL) OR "
    "(kind = 'competition' AND competition_id IS NOT NULL) OR "
    "(kind = 'achievements') OR "
    "(kind IN ('image', 'video') AND url IS NOT NULL) OR "
    "(kind = 'message' AND title IS NOT NULL) OR "
    "(kind = 'spotlight' AND (user_id IS NOT NULL OR leaderboard_id IS NOT NULL))"
)
#: Like `achievements`: what it shows lives somewhere other than a column on
#: this row, so there is nothing here to check.
PAYLOAD_AFTER = PAYLOAD_BEFORE + " OR (kind = 'comparison')"


def upgrade() -> None:
    op.create_table(
        "channel_screen_board",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "channel_screen_id",
            sa.BigInteger(),
            sa.ForeignKey("channel_screen.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "leaderboard_id",
            sa.BigInteger(),
            sa.ForeignKey("leaderboard.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        # The same board twice is two identical columns, which is a mistake
        # every time rather than a layout anybody wanted.
        sa.UniqueConstraint(
            "channel_screen_id", "leaderboard_id", name="one_panel_per_board"
        ),
    )
    # The renderer reads every panel of one screen in order, so that is the
    # access path.
    op.create_index(
        "ix_channel_screen_board_order",
        "channel_screen_board",
        ["channel_screen_id", "position"],
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
    # The rows go first, or narrowing the CHECK fails halfway and leaves it
    # dropped. The panels go with them by cascade.
    op.execute("DELETE FROM channel_screen WHERE kind = 'comparison'")
    op.drop_constraint("payload_matches_kind", "channel_screen", type_="check")
    op.create_check_constraint(
        "payload_matches_kind", "channel_screen", PAYLOAD_BEFORE
    )
    op.drop_constraint("kind_valid", "channel_screen", type_="check")
    op.create_check_constraint(
        "kind_valid", "channel_screen", f"kind IN ({KINDS_BEFORE})"
    )
    op.drop_index("ix_channel_screen_board_order", table_name="channel_screen_board")
    op.drop_table("channel_screen_board")
