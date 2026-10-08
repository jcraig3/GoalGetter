"""Derived metrics: a ratio of two other metrics, with no facts of its own.

Revision ID: f2c8a6e1d934
Revises: e7b3d9a4c521
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2c8a6e1d934"
down_revision: str | None = "e7b3d9a4c521"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("metric_definition", sa.Column("numerator_metric_id", sa.BigInteger(), nullable=True))
    op.add_column("metric_definition", sa.Column("denominator_metric_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "metric_definition_numerator_fkey", "metric_definition", "metric_definition",
        ["numerator_metric_id"], ["id"],
    )
    op.create_foreign_key(
        "metric_definition_denominator_fkey", "metric_definition", "metric_definition",
        ["denominator_metric_id"], ["id"],
    )
    op.drop_constraint("aggregation_valid", "metric_definition", type_="check")
    op.create_check_constraint(
        "aggregation_valid", "metric_definition",
        "aggregation IN ('sum', 'count', 'avg', 'max', 'min', 'last', 'ratio')",
    )
    op.create_check_constraint(
        "ratio_parts", "metric_definition",
        "(aggregation = 'ratio') = "
        "(numerator_metric_id IS NOT NULL AND denominator_metric_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM metric_definition WHERE aggregation = 'ratio'")
    op.drop_constraint("ratio_parts", "metric_definition", type_="check")
    op.drop_constraint("aggregation_valid", "metric_definition", type_="check")
    op.create_check_constraint(
        "aggregation_valid", "metric_definition",
        "aggregation IN ('sum', 'count', 'avg', 'max', 'min', 'last')",
    )
    op.drop_constraint("metric_definition_denominator_fkey", "metric_definition", type_="foreignkey")
    op.drop_constraint("metric_definition_numerator_fkey", "metric_definition", type_="foreignkey")
    op.drop_column("metric_definition", "denominator_metric_id")
    op.drop_column("metric_definition", "numerator_metric_id")
