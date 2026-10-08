from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

#: The reactions on offer. A fixed handful rather than any emoji: a feed of
#: thirty different faces under one shout-out reads as noise, and a set this
#: small can be counted at a glance.
REACTIONS = ("clap", "fire", "party", "muscle", "heart")

#: Long enough to say something, short enough to stay a comment.
MAX_COMMENT = 300


class FeedReaction(Base, TimestampMixin):
    """One person's reaction to one entry on the recognition feed (6.15).

    **Keyed by the entry, not by a notification row.** A team hitting its goal
    is one notification per member, and the feed shows them as one entry — so
    a reaction pinned to whichever row the feed happened to pick would move
    between entries as the pick changed. `feed_key` is what the feed groups
    by: the event, its subject and its period. See `app/feed.py`.
    """

    __tablename__ = "feed_reaction"
    __table_args__ = (
        # One of each per person per entry: a reaction is a toggle, and a
        # second click takes it back rather than counting twice.
        UniqueConstraint("organization_id", "feed_key", "user_id", "reaction", name="uq_feed_reaction_one_each"),
        CheckConstraint(
            "reaction IN ('clap', 'fire', 'party', 'muscle', 'heart')", name="reaction_valid"
        ),
        Index("ix_feed_reaction_entry", "organization_id", "feed_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    feed_key: Mapped[str] = mapped_column(String(160))
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE")
    )
    reaction: Mapped[str] = mapped_column(String(16))


class FeedComment(Base, TimestampMixin):
    """A comment under an entry on the recognition feed (6.15). Keyed by the
    entry, for the reason `FeedReaction` is."""

    __tablename__ = "feed_comment"
    __table_args__ = (
        CheckConstraint("char_length(body) BETWEEN 1 AND 300", name="body_sane"),
        Index("ix_feed_comment_entry", "organization_id", "feed_key", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    feed_key: Mapped[str] = mapped_column(String(160))
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE")
    )
    body: Mapped[str] = mapped_column(String(MAX_COMMENT))
