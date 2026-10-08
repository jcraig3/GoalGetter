"""Which disconnected screen is asking for a pairing code (6.2).

A revoked television shows a fresh code (6.1). When it says which link it used
to have, the code is tied to that display, so the admin inbox can say "Lobby
TV is showing a pairing code" and reconnect it in one press, without anybody
reading four characters off the screen.

Revision ID: f4c8d2a6b913
Revises: e3b9f6a1c805
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4c8d2a6b913"
down_revision: str | None = "e3b9f6a1c805"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "display_pairing",
        sa.Column(
            "previous_display_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "display.id",
                ondelete="SET NULL",
                name=op.f("fk_display_pairing_previous_display_id_display"),
            ),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("display_pairing", "previous_display_id")
