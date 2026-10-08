from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Dismissal(Base):
    """Somebody put an Inbox item or a Home banner away, until it changes (12.2).

    Those items are worked out on every request, so there is no row of theirs
    to mark — this remembers the dismissal instead, with what the item was
    about when it was put away. It stays away while that holds, and comes back
    on the next sync that changes it, or the next day, whichever is first.
    See `app/dismissals.py`.

    One row per person per item: dismissing again replaces it.
    """

    __tablename__ = "dismissal"
    __table_args__ = (UniqueConstraint("user_id", "surface", "key", name="uq_dismissal_item"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), index=True
    )
    #: `inbox` or `home`.
    surface: Mapped[str] = mapped_column(String(16))
    #: Which item: "source_quiet:12", "data_stale".
    key: Mapped[str] = mapped_column(String(120))
    #: What it was about — the newest row, the error, the date last seen.
    fingerprint: Mapped[str] = mapped_column(String(300), default="")
    #: For an item that is a count ("3 people waiting"): back only if it grows.
    count: Mapped[int | None] = mapped_column(Integer)
    #: The organization's date it was dismissed on: back the day after.
    dismissed_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
