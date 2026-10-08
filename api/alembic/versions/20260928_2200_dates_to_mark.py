"""Birthdays and work anniversaries.

**A birthday is a month and a day, and deliberately not a year.** A wall saying
"happy birthday" needs the date; nothing in this product needs somebody's age,
and a column that holds it is a column that leaks it — to every admin, every
export, and every future feature that thought it was there to be used.

A start date keeps its year, and the asymmetry is the point: "three years
today" is the whole of what a work anniversary says, and when somebody joined
is a company fact rather than a personal one.

Revision ID: c05e93b7f142
Revises: d7b4e1c8a520
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c05e93b7f142"
down_revision: str | None = "d7b4e1c8a520"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_account", sa.Column("birthday_month", sa.Integer(), nullable=True)
    )
    op.add_column(
        "user_account", sa.Column("birthday_day", sa.Integer(), nullable=True)
    )
    op.add_column("user_account", sa.Column("started_on", sa.Date(), nullable=True))

    # Both halves or neither. A month with no day is a date nothing can mark,
    # and the sweep would have to decide what to do with it every pass.
    op.create_check_constraint(
        "birthday_whole",
        "user_account",
        "(birthday_month IS NULL AND birthday_day IS NULL) OR "
        "(birthday_month BETWEEN 1 AND 12 AND birthday_day BETWEEN 1 AND 31)",
    )


def downgrade() -> None:
    op.drop_constraint("birthday_whole", "user_account", type_="check")
    op.drop_column("user_account", "started_on")
    op.drop_column("user_account", "birthday_day")
    op.drop_column("user_account", "birthday_month")
