from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

#: How often. `weekdays` rather than "daily": a coaching digest on a Saturday
#: morning is read on Monday, next to Monday's.
CADENCES = ("weekdays", "weekly", "monthly")


class ReportSchedule(Base, TimestampMixin):
    """The coaching digest, emailed on a schedule.

    **Each recipient gets their own.** The digest is worked out per person with
    that person's own scope, exactly as the reporting page would show them — so
    adding a manager to an admin's schedule shows the manager their team, not
    the organization. That is also why recipients are accounts here rather than
    free-typed addresses: an address has no scope to work anything out with.

    **Email only.** Everything in it is "who is behind", which is a
    conversation with a manager — the rule that keeps it off the wall keeps it
    out of a Teams channel. See `app/report_delivery.py`.
    """

    __tablename__ = "report_schedule"
    __table_args__ = (
        CheckConstraint("cadence IN ('weekdays', 'weekly', 'monthly')", name="cadence_valid"),
        CheckConstraint("hour BETWEEN 0 AND 23", name="hour_valid"),
        CheckConstraint("weekday IS NULL OR weekday BETWEEN 0 AND 6", name="weekday_valid"),
        Index("ix_report_schedule_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(80))
    cadence: Mapped[str] = mapped_column(String(16), default="weekly")
    #: For `weekly`: 0 is Monday. The 1st of the month for `monthly`.
    weekday: Mapped[int | None] = mapped_column(SmallInteger)
    #: In the organization's own clock.
    hour: Mapped[int] = mapped_column(SmallInteger, default=8)
    #: Account ids. Admins and managers only — see the router.
    recipient_ids: Mapped[list] = mapped_column(JSONB, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    #: The slot most recently delivered for — what makes a pass idempotent.
    last_slot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
