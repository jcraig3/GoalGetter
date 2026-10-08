"""A television waiting to be told which channel it plays."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DisplayPairing(Base):
    """One screen's request for a code, and the display it became.

    **The code is for the human; the secret is for the screen.** Four
    characters are short enough to read across a room and type with a remote,
    which makes them short enough to guess — so they never authenticate
    anything. The screen keeps `secret` from the moment it asks, and that is
    what it polls with; guessing a code lets somebody claim a pairing they
    cannot then read.

    No `TimestampMixin`: `created_at` is the whole state. A pairing is offered
    for a few minutes and is then over, and nothing ever edits one except the
    single moment it is claimed.
    """

    __tablename__ = "display_pairing"
    __table_args__ = (
        # Unique only while waiting. A claimed pairing keeps its code until it
        # is swept and two of those colliding is harmless; two *waiting* ones
        # sharing a code would let an admin claim the wrong television.
        Index(
            "uq_display_pairing_waiting",
            "code",
            unique=True,
            postgresql_where=text("display_id IS NULL"),
        ),
        Index("ix_display_pairing_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    #: What the room reads off the screen.
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    #: What the screen polls with. Long, never displayed, never typed.
    secret: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    #: NULL until an admin claims it. A television asking for a code does not
    #: know which organization it belongs to — that is what the admin decides.
    display_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("display.id", ondelete="CASCADE")
    )

    #: The display this screen used to be, when a disconnected one asks for a
    #: code (6.2) — so the inbox can name it and reconnect it in one press.
    #: Only ever a *revoked* display: a working link has no reason to ask.
    previous_display_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("display.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<DisplayPairing {self.code} claimed={self.display_id is not None}>"
