"""Stretch targets: up to three levels past a goal's target.

Revision ID: e7b3d9a4c521
Revises: d5a1c8e2f370
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7b3d9a4c521"
down_revision: str | None = "d5a1c8e2f370"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "goal",
        sa.Column(
            "stretch_targets",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("goal", "stretch_targets")
