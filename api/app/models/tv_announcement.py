"""An announcement for the TVs, and each time it was sent (Phase 25)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TvAnnouncement(Base, TimestampMixin):
    """A neutral announcement — about nobody in particular — that takes over
    the screens when it is sent: "Lunch is here", "All-hands at 3".

    **Designed once, sent any number of times.** The words, the look, the
    media and the sound live here; every send is a `TvAnnouncementSend`, so a
    weekly reminder is sent again rather than made again.

    Media is one string, as everywhere a wall plays something (`app/media.py`):
    a YouTube link, a link to an image, or a stored file — `video:`, `image:`.
    The sound effect is a stored clip, `asset:<sha256>`.
    """

    __tablename__ = "tv_announcement"
    __table_args__ = (Index("ix_tv_announcement_org", "organization_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    #: The big words.
    title: Mapped[str] = mapped_column(String(120))
    #: Underneath, smaller.
    body: Mapped[str | None] = mapped_column(String(500))
    #: How long it holds the screens.
    hold_seconds: Mapped[int] = mapped_column(Integer, default=15)
    #: The screen behind the words: an `appearance.Background`, as a channel's
    #: — a colour, a picture, a video, or a YouTube video filling the screen
    #: with the words over it.
    background: Mapped[dict | None] = mapped_column(JSONB)
    #: Shown beside the words: a YouTube video, an MP4, or a picture.
    media_url: Mapped[str | None] = mapped_column(String(500))
    media_start_seconds: Mapped[int | None] = mapped_column(Integer)
    #: A sound effect from the library, `asset:<sha256>`, played first — the
    #: video's own sound comes in when it ends.
    sound_url: Mapped[str | None] = mapped_column(String(100))
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )


class TvAnnouncementSend(Base):
    """One time an announcement was put on the screens.

    Like a replay (`CelebrationReplay`): considered for a few minutes, then
    over, and nothing edits it.
    """

    __tablename__ = "tv_announcement_send"
    __table_args__ = (Index("ix_tv_announcement_send_pending", "organization_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    announcement_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tv_announcement.id", ondelete="CASCADE")
    )
    #: NULL: every wall in the organization.
    channel_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("channel.id", ondelete="CASCADE")
    )
    sent_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
