from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Season(Base, TimestampMixin):
    """A window the points economy resets at the end of.

    **Seasons are not a refinement, and building tiers without them inherits a
    dead economy.** In the live account this product was measured against, the
    top dozen reps sat at 165K–178K points against a top tier of 100K, and
    lifetime points equalled reward points because nothing was ever spent. Two
    years in, every one of them had maxed every tier: the number still went up
    and had stopped meaning anything, which is worse than not having it. Nobody
    can be caught, so nobody is chasing.

    A season is the fix, and it has to exist from the first award rather than
    be introduced later — retrofitting one means either wiping balances people
    earned or carrying a lifetime total that defeats the point.

    Seasons never overlap, and that is enforced by the database rather than by
    the service. An award belongs to exactly one season, and "which season is
    this?" must have one answer at any instant — a pair of overlapping rows
    would make the balance on somebody's profile depend on which row a query
    happened to find first.
    """

    __tablename__ = "season"
    __table_args__ = (
        # **Unstorable, not merely rejected.** Needs btree_gist for the equality
        # part on `organization_id`; the migration installs it.
        ExcludeConstraint(
            ("organization_id", "="),
            (text("daterange(starts_on, ends_on, '[]')"), "&&"),
            name="seasons_do_not_overlap",
            using="gist",
        ),
        Index("ix_season_org_dates", "organization_id", "starts_on", "ends_on"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )

    #: What people call it. "Q1 2027", "Spring push".
    name: Mapped[str] = mapped_column(String(80))

    #: Inclusive at both ends, which is what the exclusion constraint above
    #: declares. A season runs *through* its last day — a range ending at
    #: midnight would silently drop everything earned on the final afternoon,
    #: which is the afternoon people care most about.
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)

    #: When the season was wrapped up: standings frozen, tiers settled.
    #:
    #: Separate from `ends_on` for the same reason a competition separates
    #: `ended` from `closed`. A deal closed at 4:55pm that syncs at 5:10pm
    #: should count toward the season it happened in, so there is a gap between
    #: the last day and the final word.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<Season {self.name!r} {self.starts_on}..{self.ends_on}>"
