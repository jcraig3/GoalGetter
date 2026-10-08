"""Game boards: a finish line on the things that race, and a piece per person.

`finish_line` on a leaderboard and a competition is data about the item — "the
first to fifty deals" — rather than appearance, because appearance cascades
through channels and screens, and a channel-wide finish line applied to boards
of different metrics would be nonsense. It is optional: a race with none is
measured against the leader.

`game_token` is the piece each person moves, per family of board.

Revision ID: c3d6f15b8e49
Revises: b9c5e04a7d38
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d6f15b8e49"
down_revision: str | None = "b9c5e04a7d38"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("leaderboard", "competition"):
        op.add_column(table, sa.Column("finish_line", sa.Numeric(18, 4), nullable=True))
        op.create_check_constraint(
            f"{table}_finish_line_positive", table, "finish_line IS NULL OR finish_line > 0"
        )

    op.create_table(
        "game_token",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("family", sa.String(length=16), nullable=False),
        sa.Column("token", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "family"),
    )


def downgrade() -> None:
    op.drop_table("game_token")
    for table in ("competition", "leaderboard"):
        op.drop_constraint(f"{table}_finish_line_positive", table, type_="check")
        op.drop_column(table, "finish_line")
