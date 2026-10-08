"""What a directory said, and what an admin decided about it.

Two tables, and the reason there are two rather than none is the whole design:
**sync never writes to `user_account` directly.** Everything read from a tenant
lands in `directory_person` with a status, and only an approved row becomes a real
account.

That is the same shape as the quarantine for unmatched metric rows, and for the same
reason: an automated guess about identity should be answerable before it becomes a
fact. It is also what makes "people are added by hand" the default without a second
mode to maintain — sync always proposes, an admin always disposes, and the first
bulk-approve is the moment a company opts in.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.user import UserAccount

#: What an admin has decided about somebody the directory reported.
#:
#: `pending`  — seen, not yet decided. Every new person starts here.
#: `approved` — has, or should have, an account here.
#: `hidden`   — wanted in the roster, not on a wall. Becomes a real account,
#:              created hidden: findable, photographable, movable onto a team
#:              later, and off every leaderboard until somebody says otherwise.
#:              Most of a directory sits here — contractors, service accounts,
#:              the departments that do not sell.
#: `declined` — deliberately not wanted. Survives sync, so somebody declined is
#:              not re-proposed every hour for ever.
#: `archived` — disabled at the far end, or no longer returned at all. Never
#:              deleted, so anything attached to them still says where it came
#:              from.
DIRECTORY_STATUSES = ("pending", "approved", "hidden", "declined", "archived")

#: The statuses a sync must not overwrite.
#:
#: A decision an admin made outranks anything the directory says about somebody
#: still being there. Without this, declining somebody would last exactly until the
#: next sync — which is the kind of thing that makes people stop trusting a feature.
DECIDED = ("approved", "hidden", "declined")


class DirectoryPerson(Base, TimestampMixin):
    """One person the directory reported, and what we did about them."""

    __tablename__ = "directory_person"
    __table_args__ = (
        # In the database, not only in Python. This table is written by a sync
        # loop, and a typo'd status would otherwise sit there being neither
        # pending nor approved — invisible to every list an admin looks at.
        CheckConstraint(f"status IN {DIRECTORY_STATUSES}", name="directory_status_valid"),
        # One row per person per directory. **Provider is part of the key**, which
        # the `provider` column exists for: an id is only unique within the
        # directory that issued it, so leaving it out would let two people from two
        # directories collide on a shared id.
        #
        # And the directory's own id rather than their email: people change their
        # email and keep their job, and matching on email would make that look like
        # a leaver and a joiner.
        UniqueConstraint(
            "organization_id",
            "provider",
            "external_id",
            name="uq_directory_person_external",
        ),
        # The list an admin actually opens: everyone waiting on a decision.
        Index("ix_directory_person_status", "organization_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False
    )

    #: Which provider this came from — `microsoft`, `google`. Kept per row rather
    #: than assumed, so a deployment that switches providers, or reads two, does not
    #: silently merge two different people who happen to share an id.
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The directory's own stable identifier. Entra's object id, Google's user id.
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)

    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    job_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    department: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    office_location: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    #: Group or team names, as the directory gave them. JSONB rather than a join
    #: table because nothing queries across them — they are read whole, matched
    #: against a rule, and written whole.
    groups: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    #: False for somebody disabled at the far end. Archived rather than deleted.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")

    #: The account this became, once approved. NULL while pending or declined, and
    #: SET NULL if that account is later deleted — which leaves the directory row
    #: as a record that the person was seen, without a dangling pointer.
    user_account_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )
    #: The account itself, for comparing what the rules now say against what the
    #: person actually has. Lazy: most rows are pending and have no account, and
    #: a reconcile touching two hundred people should not join for all of them.
    account: Mapped["UserAccount | None"] = relationship(lazy="select")

    #: Why this row is waiting, when it is not simply new. Set when an approved
    #: person's rule now resolves differently — a promotion should not silently
    #: change what somebody is.
    pending_reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    #: When the directory last returned them, and when they stopped being returned.
    #:
    #: `last_seen_at` is what a reconcile uses to find leavers: anybody not touched
    #: by the pass that just ran is no longer in the directory.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<DirectoryPerson {self.email!r} {self.status}>"


class DirectoryRule(Base, TimestampMixin):
    """One "people like this become that" statement.

    **Order is not stored, because order does not matter.** Which rule wins is
    decided by specificity — see `app/directory/rules.py` — precisely so that an
    admin adding a broad rule cannot silently disable every specific one. A
    `position` column would invite somebody to make it matter later.
    """

    __tablename__ = "directory_rule"
    __table_args__ = (Index("ix_directory_rule_org", "organization_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False
    )

    # ── Conditions. Empty means "any". ──────────────────────────────────────
    #
    # Stored as the admin typed them, and compared normalised. Somebody should see
    # their own rule on the page, not our folded version of it.
    department: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    job_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    #: A condition, never an assignment — a person's office is derived through
    #: their team, so setting one here could put somebody in the Phoenix team and
    #: the Dallas office at once.
    office: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    group: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    # ── Assignments ─────────────────────────────────────────────────────────
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="agent")
    #: NULL places somebody without choosing a team, leaving them for an admin.
    #: SET NULL rather than CASCADE if the team is deleted: losing the team should
    #: not silently delete the rule and change who gets what role.
    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id", ondelete="SET NULL")
    )

    def __repr__(self) -> str:
        return f"<DirectoryRule dept={self.department!r} → team={self.team_id}>"


#: How a directory run ended.
#:
#: `partial` earns its place for the same reason it does on a metric sync: people
#: read *and* something held back is a normal outcome, and calling it failed trains
#: an admin to ignore the word.
RUN_STATUSES = ("running", "ok", "partial", "failed")


class DirectoryRun(Base):
    """One pass over a directory, and what it did.

    History rather than a last-run stamp on the connection, for the same reason
    `sync_run` exists on the metric side: *"it has not worked since Tuesday"* and
    *"it has never worked"* are different problems with different fixes, and a
    single timestamp cannot tell them apart.
    """

    __tablename__ = "directory_run"
    __table_args__ = (
        CheckConstraint(f"status IN {RUN_STATUSES}", name="directory_run_status_valid"),
        # The only query: the most recent runs for one organization.
        Index("ix_directory_run_recent", "organization_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)

    #: `schedule` or `manual`. Worth keeping: "it only works when I press the
    #: button" is a real and specific complaint.
    trigger: Mapped[str] = mapped_column(String(20), nullable=False, default="schedule")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: What the pass did. Counts rather than a blob, so the page can say "12 new,
    #: 3 left" without parsing anything.
    people_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    needs_review: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: How many are waiting on a decision *after* this pass — the number the tab
    #: badge shows, which is about work outstanding rather than work done.
    pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    applied: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: An admin-readable reason, when there is one. Never a stack trace.
    error: Mapped[str | None] = mapped_column(String(2000))

    def __repr__(self) -> str:
        return f"<DirectoryRun {self.provider} {self.status}>"
