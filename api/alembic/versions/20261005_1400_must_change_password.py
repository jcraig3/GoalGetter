"""A password somebody else chose, to be replaced at first sign-in (11.2).

Revision ID: f1b5d3c8a469
Revises: e9a4c2b7d358
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1b5d3c8a469"
down_revision: str | None = "e9a4c2b7d358"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_account",
        sa.Column(
            "must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("user_account", "must_change_password")
