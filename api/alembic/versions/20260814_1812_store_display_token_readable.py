"""Store the display token readably instead of hashed.

A wall display is set up by a person walking to a TV, often days after the link
was issued, and the link may need to go to whoever is standing next to it. A
hashed token made that impossible: lose the URL and the only recourse was to
issue a new one. In practice that means links get written down somewhere less
safe than this table, so the hash bought nothing and cost a lot.

The trade is acceptable for this token specifically — one channel, read-only,
boards already published organization-wide, revocable in one click, and shown
on a wall all day regardless. It is not a precedent for session or invitation
tokens, which stay hashed.

Existing tokens cannot be carried across: a SHA-256 hash does not invert, so
there is nothing to migrate. Every existing display gets a fresh token, and any
screen already showing an old link stops working and needs the new one. There
is no way around that, and pretending otherwise would leave rows whose `token`
did not open anything.

Revision ID: 7c3a1f5b9e42
Revises: 1e2bfaae4daa
"""

import secrets

import sqlalchemy as sa
from alembic import op

revision = "7c3a1f5b9e42"
down_revision = "1e2bfaae4daa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable first: existing rows have no value to put here yet.
    op.add_column("display", sa.Column("token", sa.String(length=64), nullable=True))

    display = sa.table("display", sa.column("id", sa.Integer), sa.column("token", sa.String))
    connection = op.get_bind()
    for (display_id,) in connection.execute(sa.select(display.c.id)):
        connection.execute(
            display.update()
            .where(display.c.id == display_id)
            .values(token=secrets.token_urlsafe(32))
        )

    op.alter_column("display", "token", nullable=False)
    op.create_index(op.f("ix_display_token"), "display", ["token"], unique=True)

    op.drop_index(op.f("ix_display_token_hash"), table_name="display")
    op.drop_column("display", "token_hash")


def downgrade() -> None:
    # Hashing back is lossless in the direction that matters — the hash of the
    # readable token is exactly what the old column held — so downgrading
    # leaves every existing display link working.
    op.add_column("display", sa.Column("token_hash", sa.String(length=64), nullable=True))
    op.execute("UPDATE display SET token_hash = encode(sha256(token::bytea), 'hex')")
    op.alter_column("display", "token_hash", nullable=False)
    op.create_index(op.f("ix_display_token_hash"), "display", ["token_hash"], unique=True)

    op.drop_index(op.f("ix_display_token"), table_name="display")
    op.drop_column("display", "token")
