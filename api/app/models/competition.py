from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

#: Who competes. Not a "format" column: head-to-head is what two entrants
#: *look like*, not a third kind of thing to store — and a stored format could
#: disagree with the participant count, which is the sort of pair this codebase
#: has been bitten by.
ENTITY_TYPES = ("user", "team")

#: The lifecycle.
#:
#:     draft → scheduled → active → ended → closed
#:       └──────────────→ cancelled ←────────┘
#:
#: `ended` and `closed` are separate on purpose — see `settlement_hours`.
STATES = ("draft", "scheduled", "active", "ended", "closed", "cancelled")

#: How a tie is broken when two entrants finish level.
#:
#: `earliest_to_reach` costs one extra query at close, and is worth it: a sales
#: contest with a prize needs a decisive winner, and "you tied" is the answer
#: nobody accepts.
TIE_BREAKS = ("earliest_to_reach", "shared_rank")

#: Hours between a competition ending and its result being frozen.
#:
#: A deal closed at 4:55pm that syncs at 5:10pm should count. Announcing a
#: winner and then changing it is far worse than a day's delay.
DEFAULT_SETTLEMENT_HOURS = 24


class Competition(Base, TimestampMixin):
    """A contest with a start, an end, and a winner who stays the winner.

    **The one place this product stores a computed number.** Everything else is
    derived, because derived numbers stay correct: correct an August fact and
    August's leaderboard updates, which is what you want. A competition result
    is the opposite — a prize was handed over on the strength of it, so it must
    stay fixed. That inversion is the whole reason this is not a goal.

    See documentation/09-competitions.md.
    """

    __tablename__ = "competition"
    __table_args__ = (
        CheckConstraint("entity_type IN ('user', 'team')", name="entity_type_valid"),
        CheckConstraint(
            "state IN ('draft', 'scheduled', 'active', 'ended', 'closed', 'cancelled')",
            name="state_valid",
        ),
        CheckConstraint(
            "tie_break IN ('earliest_to_reach', 'shared_rank')", name="tie_break_valid"
        ),
        CheckConstraint("ends_at > starts_at", name="window_ordered"),
        CheckConstraint("settlement_hours BETWEEN 0 AND 168", name="settlement_sane"),
        CheckConstraint(
            "finish_line IS NULL OR finish_line > 0", name="competition_finish_line_positive"
        ),
        Index("ix_competition_org_state", "organization_id", "state"),
        # Only a series' first round repeats; a later round is a copy and
        # never spawns rounds of its own, so a series cannot fork.
        CheckConstraint(
            "repeat IS NULL OR (repeat IN ('daily', 'weekly', 'monthly') "
            "AND spawned_from_competition_id IS NULL)",
            name="repeat_shape_valid",
        ),
        # One copy per series per round, enforced by the database — the same
        # guarantee recurring goals rely on. See `app/competition_rounds.py`.
        Index(
            "uq_competition_round",
            "spawned_from_competition_id",
            "round",
            unique=True,
            postgresql_where="spawned_from_competition_id IS NOT NULL",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    #: How this looks wherever it is shown. Empty means inherit from the
    #: organization; a channel or an individual screen can still override it.
    #: See `app/appearance.py`.
    appearance: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )

    name: Mapped[str] = mapped_column(String(120))
    #: Why anyone cares. Shown everywhere the competition appears.
    prize: Mapped[str | None] = mapped_column(String(200))

    metric_definition_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("metric_definition.id", ondelete="CASCADE")
    )
    entity_type: Mapped[str] = mapped_column(String(8), default="user")

    #: Absolute instants, not a period type.
    #:
    #: A competition is an event somebody scheduled — "the first two weeks of
    #: August" — rather than a recurring window. Storing a period type would
    #: mean re-resolving it later and getting a different answer if the
    #: organization's timezone changed, which for a settled result would be
    #: rewriting history.
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    settlement_hours: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_SETTLEMENT_HOURS
    )
    state: Mapped[str] = mapped_column(String(16), default="draft")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tie_break: Mapped[str] = mapped_column(String(24), default="earliest_to_reach")

    #: A floor below which an entrant is unranked.
    #:
    #: Stops somebody with a single data point winning an average-based
    #: contest. NULL means no floor, which is right for a sum or a count.
    min_participation: Mapped[int | None] = mapped_column(Integer)

    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    @property
    def is_settled(self) -> bool:
        """Whether standings come from the frozen columns rather than a query."""
        return self.state == "closed"

    # ── Repeating ────────────────────────────────────────────────────────────
    #
    # No template row: the first round repeats, and every later round points
    # back at it. See `app/competition_rounds.py`.

    #: daily, weekly or monthly — on the first round only.
    repeat: Mapped[str | None] = mapped_column(String(8))
    #: The last day a round may start on, in the organization's own calendar.
    repeat_until: Mapped[date | None] = mapped_column(Date)
    #: On a later round: the series' first round. SET NULL rather than cascade,
    #: so a settled round survives whatever happens to the one it came from.
    spawned_from_competition_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("competition.id", ondelete="SET NULL")
    )
    #: 1 for the second round, 2 for the third; NULL on a first round.
    round: Mapped[int | None] = mapped_column(Integer)

    #: Where a race layout draws its finish line, in the metric's own unit.
    #:
    #: **Data about the item, not appearance.** Appearance cascades through
    #: channels and screens, and a channel-wide finish line laid over boards of
    #: different metrics would be nonsense. Optional: a race with none is
    #: measured against whoever is leading. See `app/game_boards.py`.
    finish_line: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    def __repr__(self) -> str:
        return f"<Competition {self.name!r} {self.state}>"


class CompetitionParticipant(Base, TimestampMixin):
    """One entrant, and where they finished once it is over.

    Entrants are named explicitly rather than derived from a scope, matching
    Spinify: "Phoenix versus Dallas" is two teams somebody chose, not everybody
    who happens to match a filter. A derived entrant set would also change
    after the fact when somebody transferred — which is exactly what a frozen
    result exists to prevent.
    """

    __tablename__ = "competition_participant"
    __table_args__ = (
        # Exactly one subject, like `goal`. The parent's `entity_type` says
        # which; this makes a row that names both, or neither, unstorable.
        CheckConstraint(
            "(user_id IS NOT NULL AND team_id IS NULL) OR "
            "(user_id IS NULL AND team_id IS NOT NULL)",
            name="one_subject",
        ),
        Index("ix_competition_participant_comp", "competition_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("competition.id", ondelete="CASCADE")
    )

    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE")
    )
    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id", ondelete="CASCADE")
    )

    #: Written once, at close, and never recomputed.
    #:
    #: NULL while the competition is running, when standings are a live query
    #: like everything else. After close these are the answer — a correction to
    #: an August fact changes August's leaderboard and must not change August's
    #: winner.
    final_rank: Mapped[int | None] = mapped_column(Integer)
    final_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    #: When they reached `final_value`, for `earliest_to_reach`.
    reached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<CompetitionParticipant comp={self.competition_id}>"
