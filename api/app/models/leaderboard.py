from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Numeric,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

ENTITY_TYPES = ("user", "team", "office")
SCOPE_TYPES = ("organization", "team", "office")
RANK_METHODS = ("rank", "dense_rank")

# Who may look at the board.
#
# This is the one place the product deliberately relaxes the rule that an agent
# sees only their own numbers. A leaderboard that showed an agent a board with
# one row on it — theirs — would be pointless; public ranking IS the mechanism.
#
# The control moves from "who are you" to "what did the publisher choose to
# publish". It applies to ranks and scores on the board and nowhere else: a
# person's detail, goals, and raw facts stay scoped as before.
VISIBILITIES = ("org", "team", "private")

# Periods a saved board can use. `custom` is absent: a board pinned to a fixed
# past range stops changing, which is the opposite of what a leaderboard is
# for. Rolling windows cover the "always populated" case instead.
BOARD_PERIODS = ("day", "week", "month", "quarter", "year", "rolling_7", "rolling_30")


class Leaderboard(Base, TimestampMixin):
    """A saved question, not a saved answer.

    Results are never stored — they are computed from `metric_fact` on request,
    by the same `aggregate` query goals and dashboards use. What is saved is
    which metric, over what window, among whom, and who may look.
    """

    __tablename__ = "leaderboard"
    __table_args__ = (
        CheckConstraint(f"entity_type IN {ENTITY_TYPES}", name="entity_type_valid"),
        CheckConstraint(f"scope_type IN {SCOPE_TYPES}", name="scope_type_valid"),
        CheckConstraint(f"visibility IN {VISIBILITIES}", name="visibility_valid"),
        CheckConstraint(
            "finish_line IS NULL OR finish_line > 0", name="leaderboard_finish_line_positive"
        ),
        CheckConstraint(f"rank_method IN {RANK_METHODS}", name="rank_method_valid"),
        CheckConstraint(f"period_type IN {BOARD_PERIODS}", name="period_type_valid"),
        # Exactly one scope id, matching the scope type. An organization-wide
        # board must not carry a stale id that nothing reads, and a scoped one
        # must not be missing the id it is scoped by.
        CheckConstraint(
            "(scope_type = 'organization' AND scope_team_id IS NULL "
            "AND scope_office_id IS NULL) OR "
            "(scope_type = 'team' AND scope_team_id IS NOT NULL "
            "AND scope_office_id IS NULL) OR "
            "(scope_type = 'office' AND scope_office_id IS NOT NULL "
            "AND scope_team_id IS NULL)",
            name="scope_matches_type",
        ),
        # "Visible to the team" needs a team to mean. Without this, a board
        # scoped to the whole organization but visible to "team" would have no
        # defined audience — and an undefined audience defaults to nobody or
        # everybody, both of which are wrong.
        CheckConstraint(
            "visibility <> 'team' OR scope_type = 'team'",
            name="team_visibility_needs_a_team",
        ),
        CheckConstraint(
            "display_limit IS NULL OR display_limit > 0", name="display_limit_positive"
        ),
        # A wall screen has no audience control at all — anyone walking past
        # reads it. So a board can only be eligible for one if it is already
        # published to the whole organization. Without this, a private board
        # could be put on a TV and shown to the cleaners.
        CheckConstraint(
            "is_tv_enabled = false OR visibility = 'org'",
            name="tv_requires_org_visibility",
        ),
        Index("ix_leaderboard_org", "organization_id"),
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

    metric_definition_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("metric_definition.id")
    )

    #: Rank individuals, teams against each other, or offices against each
    #: other. Office boards read from the `subject_office_id` snapshot, so a
    #: restructure does not rewrite which office won last quarter.
    entity_type: Mapped[str] = mapped_column(String(8), server_default="user")

    scope_type: Mapped[str] = mapped_column(String(16), server_default="organization")
    scope_team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id", ondelete="CASCADE")
    )
    scope_office_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("office.id", ondelete="CASCADE")
    )

    period_type: Mapped[str] = mapped_column(String(16), server_default="month")

    #: Top N, or all of them. Not a page size — a board is a whole thing.
    display_limit: Mapped[int | None] = mapped_column(Integer)

    visibility: Mapped[str] = mapped_column(String(8), server_default="org")

    #: Eligible for a wall display. Not the same as being displayed — a display
    #: URL is issued separately, so switching this off revokes eligibility
    #: without silently invalidating links that were never meant to exist.
    is_tv_enabled: Mapped[bool] = mapped_column(Boolean, server_default="false")

    #: RANK gives 1,2,2,4 — the honest default, and how contests actually work.
    #: DENSE_RANK gives 1,2,2,3 for boards that prefer it.
    rank_method: Mapped[str] = mapped_column(String(16), server_default="rank")

    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    #: Archive rather than delete: a board people have bookmarked should stop
    #: appearing without its URL becoming a 404 for everyone at once.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Where a race layout draws its finish line, in the metric's own unit.
    #:
    #: **Data about the item, not appearance.** Appearance cascades through
    #: channels and screens, and a channel-wide finish line laid over boards of
    #: different metrics would be nonsense. Optional: a race with none is
    #: measured against whoever is leading. See `app/game_boards.py`.
    finish_line: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))

    def __repr__(self) -> str:
        return f"<Leaderboard {self.name!r} {self.entity_type} by {self.period_type}>"
