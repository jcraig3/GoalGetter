"""Room in a badge's art for an organization's own picture (6.5).

A badge's `icon` was a key into the drawn set, at most 32 characters. It can
now also be `asset:<sha256>` — a picture from Organization → Assets — which is
70.

Revision ID: b6d1f8e2a407
Revises: a9e3c7f1d254
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6d1f8e2a407"
down_revision: str | None = "a9e3c7f1d254"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "badge", "icon", type_=sa.String(80), existing_type=sa.String(32),
        existing_server_default="medal",
    )


def downgrade() -> None:
    # An uploaded picture's reference does not fit back; it becomes the medal.
    op.execute("UPDATE badge SET icon = 'medal' WHERE length(icon) > 32")
    op.alter_column(
        "badge", "icon", type_=sa.String(32), existing_type=sa.String(80),
        existing_server_default="medal",
    )
