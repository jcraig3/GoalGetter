from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LoginAttempt(Base):
    """One row per sign-in attempt, successful or not.

    Kept in the database rather than in process memory so the limit survives a
    restart and still holds if the API is ever run with more than one replica.
    An in-memory counter is reset by `docker compose restart api`, which makes
    it useless as a defence.
    """

    __tablename__ = "login_attempt"
    __table_args__ = (
        # The two lookups this table exists to serve: recent failures for an
        # account, and recent failures from an address. Both filter on
        # attempted_at, so it leads each index.
        Index("ix_login_attempt_email_time", "email", "attempted_at"),
        Index("ix_login_attempt_ip_time", "ip_address", "attempted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Stored as typed, not as a foreign key to user_account: attempts against
    # addresses that do not exist are exactly what an enumeration attack looks
    # like, and those need counting too.
    email: Mapped[str] = mapped_column(String(320))
    ip_address: Mapped[str | None] = mapped_column(INET)

    succeeded: Mapped[bool] = mapped_column(Boolean)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    def __repr__(self) -> str:
        return f"<LoginAttempt {self.email} ok={self.succeeded}>"
