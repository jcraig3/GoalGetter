from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Who a goal is for. Not a free string — every query that resolves progress
# branches on this, and a third value appearing without the code to handle it
# would silently return nothing.
SUBJECT_TYPES = ("user", "team", "organization")


class Goal(Base, TimestampMixin):
    """A target for one metric, one subject, over one period.

    Progress is never stored. It is `aggregate.run()` over the goal's metric,
    period, and subject — the same query the leaderboards use, so a goal and a
    leaderboard can never disagree about someone's number. See
    documentation/07-goals-and-targets.md.
    """

    __tablename__ = "goal"
    __table_args__ = (
        # Exactly one subject, enforced by the database rather than by every
        # write path remembering. A goal for both a person and a team, or for
        # neither, has no defined meaning — so it must not be storable.
        CheckConstraint(
            "(subject_type = 'user' AND subject_user_id IS NOT NULL "
            "AND subject_team_id IS NULL) OR "
            "(subject_type = 'team' AND subject_team_id IS NOT NULL "
            "AND subject_user_id IS NULL) OR "
            # **Both null, deliberately.** An organization goal is not about a
            # row in another table; it is about everyone. Inventing a sentinel
            # id to point at would make every query that joins a subject have
            # to know about it.
            "(subject_type = 'organization' AND subject_user_id IS NULL "
            "AND subject_team_id IS NULL)",
            name="subject_matches_type",
        ),
        CheckConstraint(
            "subject_type IN ('user', 'team', 'organization')",
            name="subject_type_valid",
        ),
        CheckConstraint(
            "period_type IN ('day', 'week', 'month', 'quarter', 'year', 'custom')",
            name="period_type_valid",
        ),
        # A custom period needs both explicit dates; every other type needs an
        # anchor. Without this, a goal can exist that no period can be resolved
        # for, and it would fail at read time on a page rather than at write.
        CheckConstraint(
            "(period_type = 'custom' AND period_start IS NOT NULL "
            "AND period_end IS NOT NULL AND period_end >= period_start) OR "
            "(period_type <> 'custom' AND period_anchor IS NOT NULL)",
            name="period_fields_match_type",
        ),
        # A target of zero is meaningless for higher_is_better and unreachable
        # for lower_is_better; either way it is a typo, not an intention.
        CheckConstraint("target_value > 0", name="target_positive"),
        # A custom range has no "next one" — there is no rule to advance. And a
        # spawned copy never spawns further: only the original recurs, so the
        # chain stays one level deep and cannot fork.
        CheckConstraint(
            "recurring = false OR (period_type <> 'custom' AND spawned_from_goal_id IS NULL)",
            name="recurring_shape_valid",
        ),
        # THE idempotency guarantee.
        #
        # One spawned copy per source per period, enforced by the database
        # rather than by the job checking first. A check-then-insert is a race:
        # two workers, or one worker restarted mid-run, both see nothing and
        # both insert. This makes the second insert impossible instead.
        #
        # Partial, so ordinary goals are unaffected — two manual goals for the
        # same person, metric, and month with different targets ("minimum" and
        # "stretch") stay perfectly legal.
        Index(
            "uq_goal_spawn",
            "spawned_from_goal_id",
            "period_anchor",
            unique=True,
            postgresql_where="spawned_from_goal_id IS NOT NULL",
        ),
        # The list query: an organization's active goals, newest period first.
        Index("ix_goal_org_period", "organization_id", "period_anchor"),
        # "What are this person's goals?" — the dashboard's first question.
        Index("ix_goal_subject_user", "subject_user_id"),
        Index("ix_goal_subject_team", "subject_team_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    #: How this looks wherever it is shown. Empty means inherit from the
    #: organization; a channel or an individual screen can still override it.
    #: See `app/appearance.py`.
    appearance: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    #: Levels past the target — `[{"value": "65000", "label": "Stretch"}]`, up
    #: to three, each harder than the last. See `app/goal_tiers.py`.
    stretch_targets: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # No index=True here: ix_goal_org_period below already leads with this
    # column, and Postgres uses a composite index for a prefix of its columns.
    # A second index on organization_id alone would cost writes and disk to
    # answer queries the first one already answers.
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )

    # No cascade: archiving a metric must not silently delete the goals that
    # measured it, and deleting one is already blocked while facts reference it.
    metric_definition_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("metric_definition.id")
    )

    #: 16, not 8: "organization" is twelve characters and the original column
    #: fitted "user" and "team" exactly.
    subject_type: Mapped[str] = mapped_column(String(16))
    subject_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE")
    )
    subject_team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id", ondelete="CASCADE")
    )

    target_value: Mapped[Decimal] = mapped_column(Numeric(18, 4))

    # The period is stored the way it was chosen — a type plus an anchor —
    # rather than as resolved timestamps.
    #
    # "August 2026" survives a change to the organization's timezone; a stored
    # pair of instants would not, and the goal would then disagree with the
    # leaderboard showing the same month. Resolution goes through the same
    # periods.resolve() every other query uses.
    period_type: Mapped[str] = mapped_column(String(16))
    period_anchor: Mapped[date | None] = mapped_column(Date)
    # Only for `custom`, where there is no type to re-resolve from.
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)

    # Optional. A goal is identified by its metric, target, subject, and
    # period; a name is for the ones people talk about ("Q3 push").
    name: Mapped[str | None] = mapped_column(String(120))

    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    # Archive rather than delete once a period has closed: last quarter's goals
    # are the record of what was asked for, and a dashboard showing "you hit 4
    # of 5 goals" needs the two that are no longer current.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── Recurrence ───────────────────────────────────────────────────────────
    #
    # There is no separate "template" row. A recurring goal is a real goal for
    # its own period that also spawns a copy for each later period, and every
    # copy points back at the same original. A template would be a row with no
    # progress, which every query would then have to remember to exclude.
    #
    # The cadence is `period_type` — a monthly goal repeats monthly. Storing a
    # separate frequency would let the two disagree.
    recurring: Mapped[bool] = mapped_column(Boolean, server_default="false")

    # Stop date, so a goal can be set to repeat for two quarters and then stop
    # without anyone having to remember to turn it off.
    recurrence_ends_on: Mapped[date | None] = mapped_column(Date)

    # Set on spawned copies, pointing at the ORIGINAL — never at the previous
    # copy. A chain of parent links would make "has this period been spawned?"
    # a recursive walk; pointing at the root makes it one indexed lookup, which
    # is what the unique index above depends on.
    spawned_from_goal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("goal.id", ondelete="CASCADE")
    )

    def __repr__(self) -> str:
        return (
            f"<Goal metric={self.metric_definition_id} "
            f"{self.subject_type} target={self.target_value}>"
        )
