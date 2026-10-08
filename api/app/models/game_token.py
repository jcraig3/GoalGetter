from sqlalchemy import BigInteger, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class GameToken(Base, TimestampMixin):
    """The piece somebody moves round one family of game board.

    **Per family, not per board.** A race track, and whatever boards follow it,
    each want their own kind of piece — a car does not belong on a board game —
    but choosing one for every individual leaderboard would be a setting nobody
    finds. So a person picks once per family, and every board of that family
    uses it.

    Its own table, like `walkup_media`, rather than a column on the person: it
    is an optional flourish most people will never set, and `user_account` is
    identity and access.

    Absent means the default, which is the person's own face — the piece that
    needs no choosing and is recognisable from across a room.
    """

    __tablename__ = "game_token"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True
    )
    #: Which family of board, from `app/game_boards.py`.
    family: Mapped[str] = mapped_column(String(16), primary_key=True)
    #: Which piece, from that family's set.
    token: Mapped[str] = mapped_column(String(16))

    def __repr__(self) -> str:
        return f"<GameToken user={self.user_id} {self.family}={self.token}>"
