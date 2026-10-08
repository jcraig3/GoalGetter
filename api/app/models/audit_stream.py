from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

#: How entries are shaped on the way out. `json` is a batch array any HTTP
#: collector can take; `splunk` is Splunk's HTTP Event Collector format.
FORMATS = ("json", "splunk")


class AuditStream(Base, TimestampMixin):
    """Where the activity log is sent as it grows — a SIEM's HTTP collector.

    **Pushed, in order, exactly once.** `last_audit_id` is the newest entry the
    collector has accepted; a pass sends what comes after it and moves it on
    only when the collector says yes, so a collector that is down gets the
    backlog when it is back, and nothing twice. See `app/audit_stream.py`.
    """

    __tablename__ = "audit_stream"
    __table_args__ = (
        CheckConstraint("format IN ('json', 'splunk')", name="format_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE"), unique=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    #: The collector's address, encrypted — a Splunk HEC URL is often all an
    #: attacker needs to fill somebody's SIEM with noise.
    url_encrypted: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(16), default="json")
    #: The header the collector authenticates with — `Authorization` for both
    #: Splunk ("Splunk <token>") and most others ("Bearer <token>").
    header_name: Mapped[str] = mapped_column(String(100), default="Authorization")
    header_value_encrypted: Mapped[str | None] = mapped_column(Text)

    last_audit_id: Mapped[int] = mapped_column(BigInteger, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
