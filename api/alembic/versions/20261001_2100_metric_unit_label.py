"""What a count is a count of: "48,210 deals" (§8).

Optional, and only read for count metrics. Empty means a bare number, which
is what every metric showed until now.

Revision ID: e3b9f6a1c805
Revises: d7a2e5c94f18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3b9f6a1c805"
down_revision: str | None = "d7a2e5c94f18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "metric_definition", sa.Column("unit_label", sa.String(32), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("metric_definition", "unit_label")
