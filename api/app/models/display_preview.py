"""Something unsaved, sent to one television to see how it looks there."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DisplayPreview(Base):
    """One request to show a slide or a celebration on one screen, once.

    **One television, not a channel**, and gone after `hold_seconds`. The
    "send a test to the wall" button removed in 4f interrupted every screen in
    the building and would not go away; this one is aimed at the screen
    somebody is standing in front of.

    **What to show is stored, already built**, rather than the form that made
    it: the slide or announcement is rendered once, by the same code the wall
    uses, when it is sent, so a screen polling every three seconds does not
    rebuild it each time — and the form it came from was never saved.
    """

    __tablename__ = "display_preview"
    __table_args__ = (
        CheckConstraint(
            "(slide IS NULL) <> (celebration IS NULL)",
            name="one_thing",
        ),
        Index("ix_display_preview_display", "display_id", "starts_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    display_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("display.id", ondelete="CASCADE")
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: When it takes the screen. A few seconds after it was sent, so a screen
    #: polling every three hears of it before it begins and plays it from the
    #: start.
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hold_seconds: Mapped[int] = mapped_column(Integer)

    #: A slide as `display_feed.SlideRead` carries it. Exactly one of these two.
    slide: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    #: An announcement as `display_feed.CelebrationRead` carries it, less its
    #: place in a timetable.
    celebration: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))

    def __repr__(self) -> str:
        return f"<DisplayPreview {self.id} display={self.display_id}>"
