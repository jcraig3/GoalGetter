"""Index one team over time, for sparklines.

`metric_fact` already has an index for "one person, over time"
(`ix_metric_fact_subject_time`) and one for "one office, over time". It has
never had the equivalent for a team, which nothing needed until a sparkline
started asking for a team's line on a team board or a team goal.

Measured at 4M facts, warm cache, against the index set as it actually stands:

    one team,   a fiscal year    1,677 ms  ->  31 ms   (54x)
    one team,   a month            148 ms  ->   3.9 ms (38x)
    one person, a fiscal year        8.6ms ->   8.6 ms (already covered)
    one person, a month              1.3ms ->   1.3 ms (already covered)

The bottom two rows are the point of writing this down. The first version of
this migration added a covering `(organization_id, metric_definition_id,
subject_user_id, occurred_at) INCLUDE (value)` index for the person case too,
on the strength of a benchmark showing 1,393 ms -> 3.5 ms. That benchmark was
run against a table carrying only the leaderboard index, which is not the table
this product has — `ix_metric_fact_subject_time` was already doing the job. The
speedup was real and entirely redundant.

A covering variant of the team index was also measured: 18 ms instead of 31 ms
on the year, for 259 MB instead of 138 MB. Half the size for 13 ms on the
rarest chart in the product is the better trade, and matching the shape of the
two indexes already here keeps the table's index set explicable.

Revision ID: 9b47c2e05a13
Revises: 7c3a1f5b9e42
"""

from alembic import op

revision = "9b47c2e05a13"
down_revision = "7c3a1f5b9e42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY, because building an index on `metric_fact` otherwise locks
    # out every write path — and that cannot run inside a transaction, hence
    # the autocommit block.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_metric_fact_team_time")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY ix_metric_fact_team_time
            ON metric_fact (subject_team_id, occurred_at)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_metric_fact_team_time")
