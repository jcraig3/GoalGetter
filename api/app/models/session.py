from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Session(Base):
    """A signed-in browser.

    Sessions live in the database rather than in a self-contained token (JWT)
    so that access can be revoked instantly. Suspending someone deletes their
    rows and their very next request fails — a JWT would stay valid until it
    expired on its own.
    """

    __tablename__ = "session"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), index=True
    )

    # The SHA-256 of the cookie value, never the value itself.
    #
    # If this table ever leaked, raw tokens would let an attacker resume every
    # active session. Hashes are useless for that. Plain SHA-256 is correct
    # here — unlike a password, the token is 32 bytes of randomness, so there
    # is nothing to brute-force and no need for a slow hash.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # Context for a future "your active sessions" screen, and for answering
    # "where was this account used from?" after an incident.
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(400))

    def __repr__(self) -> str:
        return f"<Session id={self.id} user_id={self.user_id}>"
