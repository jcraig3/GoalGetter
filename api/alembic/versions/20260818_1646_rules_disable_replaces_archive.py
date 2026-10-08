"""rules: disable replaces archive

`achievement_rule.archived_at` was `enabled = False` with no way back — the list
filtered archived rules out and no endpoint could restore one, so archiving was a
trapdoor. Disable does the same job reversibly, and delete now really deletes
(nothing holds a foreign key to a rule; a notification carries its announcement
copied onto the row).

**The data step is the point of this migration.** Dropping the column on its own
would un-hide every archived rule — and any that still had `enabled = true` would
start announcing again on the next job pass. Rules the admin believed they had
removed would begin celebrating things. So they are switched off first.

Off rather than deleted: the button they pressed said the rule would stop firing,
not that it would be erased. Switched off, it is visible in the list, silent, and
theirs to delete or re-enable — which is strictly better than either state it
could have been in before.

Revision ID: 50b62b1669a1
Revises: 12213205a069
Create Date: 2026-08-18 16:46:18.640891
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '50b62b1669a1'
down_revision: str | None = '12213205a069'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Before the column goes, or the information needed to do this is gone.
    op.execute(
        """
        UPDATE achievement_rule
           SET enabled = false
         WHERE archived_at IS NOT NULL
        """
    )
    op.drop_column('achievement_rule', 'archived_at')


def downgrade() -> None:
    """Restores the column, but not which rules were archived.

    That is not recoverable: after the upgrade, a formerly-archived rule and one
    an admin simply switched off are the same row. Everything comes back as
    un-archived and disabled, which keeps them silent — the safe direction for a
    thing whose job is to announce.
    """
    op.add_column(
        'achievement_rule',
        sa.Column(
            'archived_at',
            postgresql.TIMESTAMP(timezone=True),
            autoincrement=False,
            nullable=True,
        ),
    )
