"""Let a source read once and stop.

**The setting a first test actually wants.** Every source repeats: create one and
it starts syncing on its own, for ever, whether or not anybody has confirmed the
numbers are right. Against a spreadsheet that costs nothing. Against a warehouse
it resumes compute and bills by the second, which makes "I just wanted to see if
it worked" an expense.

`interval_minutes = 0` means "do not repeat". Zero rather than NULL because the
column is non-null everywhere else and a nullable one would make every reader ask
what absent means; and because the check constraint below can then say the rule
out loud rather than leaving it to a comment.

Pausing a source already achieves something similar, but it says the wrong thing:
paused is a state somebody chose to stop, and a one-off that has finished is not
stopped — it is done.

Revision ID: c8f3a2d47b91
Revises: b2e8f4a71c53
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8f3a2d47b91"
down_revision: str | None = "b2e8f4a71c53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("interval_sane", "data_source", type_="check")
    op.create_check_constraint(
        "interval_sane",
        "data_source",
        "interval_minutes = 0 OR interval_minutes >= 5",
    )


def downgrade() -> None:
    # Anything set to read once becomes hourly again, which is the old default
    # and the safest of the values the old constraint allowed.
    op.execute("UPDATE data_source SET interval_minutes = 60 WHERE interval_minutes = 0")
    op.drop_constraint("interval_sane", "data_source", type_="check")
    op.create_check_constraint("interval_sane", "data_source", "interval_minutes >= 5")
