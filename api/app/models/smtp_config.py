"""Where this deployment sends mail from.

Alongside `sso_config` and `oauth_client` rather than in environment variables, for
the same reason as both: an admin of a self-hosted deployment should not have to SSH
into a server and restart containers to change a mail host.

**Email is an enhancement here, never a dependency.** Every flow that sends one also
produces a link an admin can hand over, and that stays true with a mail server
configured — a send that fails must not swallow an invitation. See `app/mail.py`.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

#: How to secure the connection.
#:
#: `starttls` — connect in the clear on 587, then upgrade. What almost every
#:              provider documents, and the default.
#: `ssl`      — TLS from the first byte, on 465. Older, still common.
#: `none`     — no encryption. For an internal relay on a trusted network, and
#:              named plainly rather than hidden, because somebody choosing it
#:              should have to choose it.
SMTP_SECURITY = ("starttls", "ssl", "none")


class SmtpConfig(Base):
    """One mail server, per organization."""

    __tablename__ = "smtp_config"
    __table_args__ = (
        CheckConstraint(f"security IN {SMTP_SECURITY}", name="smtp_security_valid"),
        CheckConstraint("port > 0 AND port < 65536", name="smtp_port_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE"), unique=True
    )

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    host: Mapped[str] = mapped_column(String(255), nullable=False, server_default="")
    port: Mapped[int] = mapped_column(Integer, nullable=False, server_default="587")
    security: Mapped[str] = mapped_column(String(20), nullable=False, server_default="starttls")

    #: Often an address rather than a name, and often the same as `from_address` —
    #: but not always, so it is asked for separately rather than assumed.
    username: Mapped[str] = mapped_column(String(320), nullable=False, server_default="")
    #: Fernet ciphertext, never the password, and never returned by the API. The
    #: UI shows "configured" or "not configured" — the same rule as every other
    #: secret here.
    password_encrypted: Mapped[str | None] = mapped_column(String(2000))

    #: What a recipient sees. Must be an address the server is allowed to send as,
    #: which is the single most common reason a correctly-configured server still
    #: refuses.
    from_address: Mapped[str] = mapped_column(String(320), nullable=False, server_default="")
    from_name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="GoalGetter")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<SmtpConfig {self.host!r} enabled={self.enabled}>"
