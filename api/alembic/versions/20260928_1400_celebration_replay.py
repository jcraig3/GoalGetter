"""Play a win on the wall again, on purpose.

For the manager whose team's best moment of the week happened while the room
was in a meeting.

**A row rather than a rewritten notification.** Bumping the win's timestamp to
make it recent again would rewrite when it happened, which is the one thing a
record of what happened must not do.

Revision ID: e8d31a70c4b2
Revises: a2f6c90d5b31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8d31a70c4b2"
down_revision: str | None = "a2f6c90d5b31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "celebration_replay",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.BigInteger(),
            sa.ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # NULL means every wall in the organization. A replay is usually aimed
        # at one room, and "all of them" is the thing an admin testing a fresh
        # deployment wants before any channel exists.
        sa.Column(
            "channel_id",
            sa.BigInteger(),
            sa.ForeignKey("channel.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "notification_id",
            sa.BigInteger(),
            sa.ForeignKey("notification.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
        ),
    )
    # Every read is "what should this channel play now", so that is the access
    # path. No expiry column: the window is one constant in `app/events.py`,
    # and a column could disagree with it.
    op.create_index(
        "ix_celebration_replay_pending",
        "celebration_replay",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_celebration_replay_pending", table_name="celebration_replay")
    op.drop_table("celebration_replay")
