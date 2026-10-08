"""data source activated_at

Tells a draft apart from a source somebody finished and then paused.

NULL means the connect flow was started and never completed. Those are hidden from
the list and swept after a day — a half-built source nobody came back to is
clutter, and it has no credentials worth keeping and no facts to lose.

**The backfill has to decide that for rows created before the column existed, and
"all of them are finished" is the wrong answer.** The first version of this
migration stamped every existing row with `now()`, reasoning that anything already
in the table predated drafts and so could not be one. That is exactly backwards: a
source somebody abandoned last week is *already* a draft, and marking it finished
pins it to the list forever, reporting itself as *setup unfinished* with no way to
tidy it away. Found immediately, on a real abandoned source.

So the backfill asks the data instead. A source counts as having been finished if it
shows evidence of having run:

* it has an **enabled mapping** — somebody switched it on, which is the definition
  the application uses from here on; or
* it has **written facts** — it demonstrably ran, whatever its mappings say now.

Everything else was a draft when this migration ran, and is treated as one. The
worst case is a source somebody set up and then disabled every mapping on before
this migration, which is swept — that is why the check includes facts, since such a
source has almost certainly imported something.

Revision ID: dae5ed662199
Revises: 794e677dacd2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'dae5ed662199'
down_revision: str | None = '794e677dacd2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'data_source',
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    )

    # `created_at` rather than `now()`: the column means "when setup was finished",
    # and for a source that has been running for months, today is a worse answer
    # than the day it was created. Nothing reads the exact value — only whether it
    # is NULL — but a timestamp that is visibly wrong is a trap for whoever starts
    # reading it later.
    op.execute(
        """
        UPDATE data_source AS s
           SET activated_at = s.created_at
         WHERE EXISTS (
                   SELECT 1 FROM source_mapping m
                    WHERE m.data_source_id = s.id AND m.enabled
               )
            OR EXISTS (
                   SELECT 1 FROM metric_fact f
                    WHERE f.data_source_id = s.id
               )
        """
    )


def downgrade() -> None:
    # Loses which sources were finished. Nothing about their facts changes.
    op.drop_column('data_source', 'activated_at')
