from sqlalchemy import BigInteger, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WalkupMedia(Base, TimestampMixin):
    """One person's celebration clip — their walk-up music.

    Set by the person, or by a manager or admin on their behalf — plenty of
    people never open their own settings, and a wall with no music is the
    result. An earlier version of this was self-only; the scope check on the
    endpoint is what keeps the wider version from becoming a way to edit
    strangers, and changing somebody else's is audited.

    Its own table rather than columns on `user_account`, which holds identity
    and access. This is an optional flourish most people will never set, and
    the same reasoning that gave notification preferences their own table
    applies: a core table should not accumulate a column per feature.

    **No `kind` column.** What a URL is gets derived from the URL — see
    `media.kind_of`. Storing it would be one more pair that can disagree, and
    this disagreement would only ever surface on a screen in front of an
    office.
    """

    __tablename__ = "walkup_media"

    #: One clip per person, so the person *is* the key. No surrogate id.
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("user_account.id", ondelete="CASCADE"),
        primary_key=True,
    )

    url: Mapped[str] = mapped_column(String(500))
    #: Where in the clip to begin and end, in seconds. Meaningless for an image
    #: and stored as 0..MAX anyway, so the display page needs no special case.
    start_seconds: Mapped[int] = mapped_column(Integer, default=0)
    end_seconds: Mapped[int] = mapped_column(Integer)

    def __repr__(self) -> str:
        return f"<WalkupMedia user={self.user_id} {self.url[:40]}>"
