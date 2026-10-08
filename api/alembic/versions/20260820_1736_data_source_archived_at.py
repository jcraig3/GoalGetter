"""data source archived_at

Lets an integration be removed without removing its numbers.

`metric_fact.data_source_id` is `ON DELETE RESTRICT`, deliberately: a fact that
cannot say where it came from is a fact nobody can audit, so a source with
history refuses to be deleted. That left no way to tidy away a test webhook —
the row stayed in the list forever. Archiving is the third state: the row
survives so facts keep their provenance, and the UI stops showing it.

Nullable with no default and no backfill, so it applies instantly on a large
table: every existing source is "not archived", which is exactly what NULL
already means.

No index. The scheduler's access path is `(enabled, next_run_at)` and archiving
disables the source, so `ix_data_source_due` already excludes archived rows;
`app/sync.due()` also filters on `archived_at` directly so the exclusion does not
depend on that coupling holding. Listing sources for one organization is a
handful of rows either way.

Revision ID: dea8225095f8
Revises: 8ca82511c871
Create Date: 2026-08-20 17:36:57.924499
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'dea8225095f8'
down_revision: str | None = '8ca82511c871'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'data_source',
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Loses which sources were removed: they reappear in the list, disabled and
    # without credentials. Nothing about the facts they imported changes.
    op.drop_column('data_source', 'archived_at')
