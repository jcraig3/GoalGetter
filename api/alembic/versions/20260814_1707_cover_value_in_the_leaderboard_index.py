"""cover value in the leaderboard index

Revision ID: 3d61902cb44e
Revises: 1129f4fbdc82
Create Date: 2026-08-14 17:07:43.568074
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '3d61902cb44e'
down_revision: str | None = '1129f4fbdc82'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Hand-written. Autogenerate compares which columns an index has but not
    # its INCLUDE clause, so it saw no change here — the same blind spot that
    # left two CHECK constraints stale one migration ago.
    #
    # CONCURRENTLY, because building an index on `metric_fact` takes a lock on
    # a table that every write path touches. It cannot run inside a
    # transaction, hence the autocommit block.
    #
    # Measured at 4M rows: 7,423ms before, 12ms after.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX IF EXISTS ix_bench_covering")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_metric_fact_leaderboard")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY ix_metric_fact_leaderboard
            ON metric_fact (organization_id, metric_definition_id,
                            occurred_at, subject_user_id)
            INCLUDE (value)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_metric_fact_leaderboard")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY ix_metric_fact_leaderboard
            ON metric_fact (organization_id, metric_definition_id,
                            occurred_at, subject_user_id)
            """
        )
