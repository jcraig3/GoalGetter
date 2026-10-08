"""Team identity (6.7): a short name and a logo, beside the colour.

A team board drew every team the same way — a name and nothing to know it by
from across a room. A team can now have a short name ("ENT") for where a full
one will not fit, and a logo from Organization → Assets; its colour, which
existed and was drawn nowhere, is now used too.

Revision ID: d8f2b4c6e731
Revises: c3a7e9d2f560
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8f2b4c6e731"
down_revision: str | None = "c3a7e9d2f560"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("team", sa.Column("short_name", sa.String(12), nullable=True))
    op.add_column("team", sa.Column("logo", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("team", "logo")
    op.drop_column("team", "short_name")
