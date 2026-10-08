"""A win somebody asked a wall to play again."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CelebrationReplay(Base):
    """One request to put a celebration back on a screen.

    **Its own row, not a rewritten notification.** Bumping a win's timestamp to
    make it recent again would rewrite when it happened, and a record of what
    happened is the one thing that must not move.

    No `TimestampMixin`: `created_at` is the whole state. A replay is
    considered for a few minutes and then it is over — there is no "updated",
    and nothing ever edits one.
    """

    __tablename__ = "celebration_replay"
    __table_args__ = (
        Index(
            "ix_celebration_replay_pending", "organization_id", "created_at"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )

    #: NULL means every wall in the organization.
    channel_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("channel.id", ondelete="CASCADE")
    )

    #: CASCADE: a replay of a win that has since aged out of the feed has
    #: nothing to play, and the row would outlive its own subject.
    notification_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("notification.id", ondelete="CASCADE")
    )

    requested_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<CelebrationReplay {self.id} channel={self.channel_id}>"
