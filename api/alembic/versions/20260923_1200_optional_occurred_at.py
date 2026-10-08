"""Let a mapping have no date column.

**Plenty of sources have no date to give.** A pre-aggregated view — one row per
person, a number that moves — is the shape every leaderboard tool before this one
asks for, so it is the shape a lot of warehouses already hold. Refusing it meant
telling somebody to write SQL that invents a date, which they would get wrong in
a way nothing here could see.

NULL means the fact is dated by when its number last changed: first import counts
as a change, and a row that stops moving keeps the date it last moved on. One
rule covering both shapes — a deal row written once keeps the day it arrived, and
a running total moves to today the moment it changes.

Widening only. Every existing mapping has a column and keeps it.

Revision ID: e4a7c93f1b28
Revises: d3b91c5f8e42
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a7c93f1b28"
down_revision: str | None = "d3b91c5f8e42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "source_mapping", "occurred_at_field", existing_type=sa.String(200), nullable=True
    )


def downgrade() -> None:
    # A dateless mapping cannot be expressed in the old schema. Its facts keep the
    # dates they were given; what is lost is the ability to sync it again, so the
    # mapping is pointed at nothing rather than silently guessing a column.
    op.execute("DELETE FROM source_mapping WHERE occurred_at_field IS NULL")
    op.alter_column(
        "source_mapping", "occurred_at_field", existing_type=sa.String(200), nullable=False
    )
