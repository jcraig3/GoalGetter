from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    """One row per privileged action: who did what, to whom, and when.

    Only actions that change someone's access or the organization's
    configuration are recorded — role changes, suspensions, team moves, SSO
    edits. Reads are not logged. Logging every GET would bury the handful of
    rows that actually matter under millions that never get read, and the
    question this table answers is "who gave that person admin?", not "who
    looked at the user list?".

    Rows are never updated or deleted by the application. An audit trail that
    the application can rewrite is not evidence of anything.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        # The two ways this is read: an organization's recent activity, and
        # everything that has ever been done to one person. Both are
        # time-ordered, so occurred_at trails each index.
        Index("ix_audit_log_org_time", "organization_id", "occurred_at"),
        Index("ix_audit_log_target_time", "target_user_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE")
    )

    # Nullable, and deliberately NOT a cascading delete: if the actor's account
    # is ever removed, the record of what they did must survive them. SET NULL
    # keeps the row and loses only the link.
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    # Denormalised copies, frozen at the time of the action. A rename or a
    # departure would otherwise silently rewrite history — "Admin User changed
    # a role" is useless if the name now belongs to someone else.
    actor_email: Mapped[str | None] = mapped_column(String(320))

    action: Mapped[str] = mapped_column(String(64))

    target_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id", ondelete="SET NULL")
    )
    target_email: Mapped[str | None] = mapped_column(String(320))

    # What actually changed, e.g. {"org_role": {"from": "agent", "to": "admin"}}.
    # JSONB rather than a column per field: the shape differs per action, and a
    # table with thirty mostly-null columns is harder to read than one that
    # says exactly what happened. Queried rarely, so the flexibility is free.
    #
    # Must never contain a password, token, or client secret — this table is
    # readable by every admin and is exactly the wrong place to leak one.
    details: Mapped[dict | None] = mapped_column(JSONB)

    ip_address: Mapped[str | None] = mapped_column(INET)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} by={self.actor_email} target={self.target_email}>"
