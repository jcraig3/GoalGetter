from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

TOKEN_PURPOSES = ("invite", "password_reset")


class UserToken(Base):
    """A single-use link: an invitation, or a password reset.

    One table for both because they are the same mechanism — issue a random
    secret, email or paste it, exchange it once for the right to set a password.
    Two tables would duplicate the expiry, hashing, and single-use logic, and
    the two copies would drift.
    """

    __tablename__ = "user_token"
    __table_args__ = (
        CheckConstraint(f"purpose IN {TOKEN_PURPOSES}", name="purpose_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), index=True
    )

    # SHA-256 of the value in the link, never the value itself — the same
    # reasoning as session tokens. If this table leaked, raw tokens would let an
    # attacker claim any pending invitation and set its password. Plain SHA-256
    # is right here: the token is 32 bytes of randomness, so there is nothing to
    # brute-force and no need for a slow hash.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    purpose: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<UserToken user={self.user_id} purpose={self.purpose}>"
