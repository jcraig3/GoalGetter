from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PointAward(Base):
    """One row per award, and a balance is a sum of them.

    **Never a running total on the person.** A `points` column on
    `user_account` is one number that four code paths increment, and the first
    time two of them race, or a job is restarted mid-pass, it is wrong with no
    way to tell — because nothing recorded what it was supposed to be made of.
    A ledger cannot drift from itself: the balance is derived, so a corrected
    row corrects the balance, and "why do I have 4,200?" is a query rather than
    an apology.

    Same reasoning as `metric_fact`, and the same reasoning that keeps a
    leaderboard derived. The one thing in this product that stores a computed
    number is a settled competition, and it does so because a prize was handed
    over on the strength of it.

    No `updated_at`: a ledger row is never edited. A mistake is corrected by
    writing the opposite row, which is why `points` may be negative — and why
    somebody can read what happened rather than finding a number quietly
    different from yesterday.
    """

    __tablename__ = "point_award"
    __table_args__ = (
        # **The idempotency guarantee**, copied deliberately from
        # `notification`, because the jobs that award points are the same jobs
        # that announce things: they run on a loop over state that is a query
        # rather than a column, and they can be restarted mid-pass. The row
        # *is* the record that we awarded it, so the insert is
        # ON CONFLICT DO NOTHING and races stop mattering.
        #
        # NULLS NOT DISTINCT, because Postgres treats NULLs as distinct in a
        # unique index by default — without it every award with no period
        # would insert again on every cycle, forever.
        #
        # PARTIAL on `awarded_by_user_id IS NULL`: detected awards latch,
        # authored ones must repeat. A manager handing somebody 50 points twice
        # means to do it twice.
        #
        # **`season_id` is deliberately not in the key.** If a goal achievement
        # were somehow re-detected after a rollover it must not pay out again
        # into the new season, which is exactly what including it would allow.
        Index(
            "uq_point_award_once",
            "organization_id",
            "user_id",
            "event_key",
            "subject_type",
            "subject_id",
            "period_anchor",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where="awarded_by_user_id IS NULL",
        ),
        # The balance query, which is the hottest read in the economy: every
        # profile, every standings table, every tier check.
        Index("ix_point_award_balance", "season_id", "user_id"),
        Index("ix_point_award_statement", "organization_id", "user_id", "id"),
        # Zero-point awards are noise in a statement somebody reads. A rule
        # worth nothing should not write a row at all.
        CheckConstraint("points <> 0", name="points_not_zero"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )

    #: Which season it counts toward. Resolved at award time from the date, and
    #: then fixed — a season's standings must not change when a later season
    #: opens.
    season_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("season.id", ondelete="CASCADE")
    )

    #: Who earned it. Always a person, never a team: a team goal pays every
    #: member, because a balance somebody can spend has to belong to somebody.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE")
    )

    #: Positive for an award, negative for a correction or a spend.
    points: Mapped[int] = mapped_column(Integer)

    #: Which event paid out, from the catalogue in `app/events.py`, or one of
    #: the ledger's own keys — see `app/points.py`.
    event_key: Mapped[str] = mapped_column(String(64))

    #: What it was for — ("goal", 41) — matching the notification about the
    #: same moment, so a statement line can link where the bell did.
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[int] = mapped_column(BigInteger)

    #: The period the award belongs to, for anything that recurs. August's
    #: "you hit your goal" and September's are different awards about the same
    #: goal, and only this tells them apart.
    period_anchor: Mapped[date | None] = mapped_column(Date)

    #: The statement line, written at award time.
    #:
    #: Stored rather than rendered on read, for the same reason a notification
    #: stores its title: renaming a goal must not rewrite what somebody was
    #: paid for last March.
    reason: Mapped[str] = mapped_column(String(200))

    #: Set only when a person did this by hand. Null means the system detected
    #: it, which is also what the idempotency index keys on.
    awarded_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    #: Written once. Declared here rather than inherited from `TimestampMixin`,
    #: which would bring `updated_at` with it — and a ledger row that records
    #: when it was last changed is a ledger row somebody has changed.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<PointAward {self.points:+} {self.event_key}>"


class PointValue(Base, TimestampMixin):
    """What one kind of event is worth, for one organization.

    A table rather than a column per event: the catalogue gains entries as
    features land, and a schema that needs a migration to make competitions
    worth more than birthdays is a schema that will be out of date by the time
    anybody wants to tune it.

    Absent means the built-in default in `app/points.py`, not zero. An
    organization that has never opened the settings page still has a working
    economy, and an admin who sets something to 0 has said something different
    from never having looked.
    """

    __tablename__ = "point_value"
    __table_args__ = (
        Index(
            "uq_point_value_event",
            "organization_id",
            "event_key",
            unique=True,
        ),
        CheckConstraint("points >= 0", name="point_value_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    event_key: Mapped[str] = mapped_column(String(64))
    points: Mapped[int] = mapped_column(Integer)

    def __repr__(self) -> str:
        return f"<PointValue {self.event_key}={self.points}>"
