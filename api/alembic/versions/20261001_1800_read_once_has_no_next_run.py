"""A read-once source that has run has no next run.

`sync._next_run` now leaves it empty. Sources that read before that carry a
next-run of "the moment they finished", which every lateness check reads as
overdue — so it is cleared here once.

Revision ID: b2f8c4d1e937
Revises: a7d3e9c2b461
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2f8c4d1e937"
down_revision: str | None = "a7d3e9c2b461"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE data_source
        SET next_run_at = NULL
        WHERE interval_minutes = 0
          AND last_run_at IS NOT NULL
        """
    )


def downgrade() -> None:
    # The old value was never read by the scheduler, only misread as overdue,
    # so there is nothing worth putting back.
    pass
