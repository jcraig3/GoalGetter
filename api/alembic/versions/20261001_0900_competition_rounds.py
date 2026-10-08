"""Recurring competitions: a first round that repeats, and its later rounds.

No template table — the first round repeats (`repeat`, `repeat_until`) and each
later round is an ordinary competition pointing back at it with a round number.
A unique index on (series, round) makes a second copy of a round impossible.

Revision ID: d5a1c8e2f370
Revises: c3e9a7d15b40
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5a1c8e2f370"
down_revision: str | None = "c3e9a7d15b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("competition", sa.Column("repeat", sa.String(length=8), nullable=True))
    op.add_column("competition", sa.Column("repeat_until", sa.Date(), nullable=True))
    op.add_column(
        "competition",
        sa.Column("spawned_from_competition_id", sa.BigInteger(), nullable=True),
    )
    op.add_column("competition", sa.Column("round", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "competition_spawned_from_fkey", "competition", "competition",
        ["spawned_from_competition_id"], ["id"], ondelete="SET NULL",
    )
    op.create_check_constraint(
        "repeat_shape_valid",
        "competition",
        "repeat IS NULL OR (repeat IN ('daily', 'weekly', 'monthly') "
        "AND spawned_from_competition_id IS NULL)",
    )
    op.create_index(
        "uq_competition_round", "competition", ["spawned_from_competition_id", "round"],
        unique=True, postgresql_where=sa.text("spawned_from_competition_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_competition_round", table_name="competition")
    op.drop_constraint("repeat_shape_valid", "competition", type_="check")
    op.drop_constraint("competition_spawned_from_fkey", "competition", type_="foreignkey")
    op.drop_column("competition", "round")
    op.drop_column("competition", "spawned_from_competition_id")
    op.drop_column("competition", "repeat_until")
    op.drop_column("competition", "repeat")
