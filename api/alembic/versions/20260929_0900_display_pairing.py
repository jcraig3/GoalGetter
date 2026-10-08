"""Pair a television with a four-character code.

**Typing a display URL with a remote control is the worst part of setting one
up.** The token is thirty-odd characters of base64 in an address bar, entered
on an on-screen keyboard with arrow keys, by somebody standing on a chair. It
matters more here than anywhere else: a hosted product can email the link to a
laptop, and a self-hosted wall is often a television on a network with no mail
client on it.

So the screen asks for a code instead. It shows four characters; an admin types
those four characters into an app they are already signed in to, chooses a
channel, and the screen picks up its real token on the next poll.

**The code is for the human; the secret is for the screen.** A four-character
code has to be short enough to read across a room and type with a remote, which
makes it short enough to guess — so it never authenticates anything. The screen
keeps a long secret from the moment it asks, and that is what it polls with.
Guessing a code lets somebody claim a pairing they cannot then read.

Revision ID: b8e5c40a7d13
Revises: a3f7d21c6b09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8e5c40a7d13"
down_revision: str | None = "a3f7d21c6b09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "display_pairing",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        # What the room reads off the screen. Unique among pairings that are
        # still waiting — see the partial index below.
        sa.Column("code", sa.String(8), nullable=False),
        # What the screen polls with. Long, never displayed, never typed.
        sa.Column("secret", sa.String(64), nullable=False, unique=True),
        # NULL until an admin claims it. A television asking for a code does
        # not know which organization it belongs to — that is the whole thing
        # the admin is deciding.
        sa.Column(
            "display_id",
            sa.BigInteger(),
            sa.ForeignKey("display.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # **Unique only while waiting.** A claimed pairing keeps its code for the
    # few minutes before it is swept, and two of those colliding is harmless —
    # but two *waiting* pairings sharing a code would let an admin claim the
    # wrong television.
    op.create_index(
        "uq_display_pairing_waiting",
        "display_pairing",
        ["code"],
        unique=True,
        postgresql_where=sa.text("display_id IS NULL"),
    )
    op.create_index(
        "ix_display_pairing_created", "display_pairing", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_display_pairing_created", table_name="display_pairing")
    op.drop_index("uq_display_pairing_waiting", table_name="display_pairing")
    op.drop_table("display_pairing")
