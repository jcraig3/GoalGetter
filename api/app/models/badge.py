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

#: How a badge is come by.
#:
#: Two, not an expression language. "An admin decided" and "this happened N
#: times" cover what a floor actually pins on people, and every operator beyond
#: them is one more thing to validate, explain, and get wrong in public.
KINDS = ("manual", "count")

#: The window a count is taken over.
#:
#: `season` rather than `year` deliberately: the economy's unit of time is the
#: season, and a badge counted over a year would straddle three of them and
#: reward somebody for a stretch nobody was still watching.
WINDOWS = ("week", "month", "season")


class Badge(Base, TimestampMixin):
    """Something you are, rather than something you have.

    The distinction from a tier is the whole design, and it is worth stating
    because they look alike on a profile:

        a tier    a current state, read from this season's balance
        a badge   a thing that happened, and stays happened

    A tier you can lose by having a quiet month, and should — that is what
    makes the top one worth wearing. A badge for ten big deals in March is
    still true in December, because March does not change. Storing a tier
    would be storing a derived number; *not* storing a badge would be
    recomputing history, and history is the one thing that must not move.
    """

    __tablename__ = "badge"
    __table_args__ = (
        CheckConstraint("kind IN ('manual', 'count')", name="badge_kind_valid"),
        CheckConstraint(
            "counted_over IS NULL OR counted_over IN ('week', 'month', 'season')",
            # The name the migration gave it, so the model and the database agree.
            name="badge_counted_over_valid",
        ),
        # A counted badge needs something to count and a number to reach; a
        # manual one must have neither, or the columns silently mean nothing.
        CheckConstraint(
            "(kind = 'count' AND achievement_rule_id IS NOT NULL "
            "AND threshold IS NOT NULL AND counted_over IS NOT NULL) OR "
            "(kind = 'manual' AND achievement_rule_id IS NULL "
            "AND threshold IS NULL AND counted_over IS NULL)",
            name="badge_kind_matches_fields",
        ),
        CheckConstraint(
            "threshold IS NULL OR threshold > 0", name="badge_threshold_positive"
        ),
        Index("uq_badge_name", "organization_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )

    name: Mapped[str] = mapped_column(String(60))
    #: What it takes, in the words of whoever set it up. Shown wherever the
    #: badge is, so somebody who has not got one knows what it is for — which
    #: is most of what a badge is doing on a page at all.
    description: Mapped[str] = mapped_column(String(200), server_default="")

    kind: Mapped[str] = mapped_column(String(16), default="manual")

    #: Which rule's firings are counted, for `kind='count'`.
    achievement_rule_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("achievement_rule.id", ondelete="CASCADE")
    )
    #: How many times it has to fire.
    threshold: Mapped[int | None] = mapped_column(Integer)
    #: Named `counted_over` rather than `window`, which is a reserved word in
    #: Postgres and would need quoting in every CHECK that mentions it.
    counted_over: Mapped[str | None] = mapped_column(String(16))

    #: A key into the drawn set (`badgeMarks.tsx`), or `asset:<sha256>` for a
    #: picture from Organization → Assets (6.5). Never a URL.
    icon: Mapped[str] = mapped_column(String(80), server_default="medal")

    #: Points paid on earning it, through the same ledger as everything else.
    #:
    #: Zero by default. **A badge is mostly not about points** — it is the part
    #: of the economy that survives a season reset, and making it pay well
    #: would turn it back into a balance.
    points: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<Badge {self.name!r} {self.kind}>"


class BadgeAward(Base):
    """One person holding one badge, once.

    No `updated_at`, and nothing here is editable, for the same reason as
    `point_award`: this is a record that something happened. Taking a badge
    back is a delete — visible, deliberate, and auditable — rather than a
    field somebody flipped.
    """

    __tablename__ = "badge_award"
    __table_args__ = (
        # The same latch as `notification` and `point_award`, for the same
        # reason: the pass that detects these runs on a loop over state that is
        # a query rather than a column, and can be restarted mid-pass.
        #
        # Keyed on the window's anchor, so "ten big deals in March" and "ten in
        # April" are two badges and a re-run of either is none.
        #
        # Partial on `awarded_by_user_id IS NULL`: a manager pinning the same
        # badge on somebody twice meant to.
        Index(
            "uq_badge_award_once",
            "badge_id",
            "user_id",
            "period_anchor",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where="awarded_by_user_id IS NULL",
        ),
        Index("ix_badge_award_person", "user_id", "id"),
        Index("ix_badge_award_org", "organization_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    badge_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("badge.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE")
    )

    #: The start of the window it was earned in. Null for a manual one, which
    #: belongs to a moment rather than to a period.
    period_anchor: Mapped[date | None] = mapped_column(Date)

    #: What it says on the award. Written once, like a notification's title:
    #: renaming the badge later must not rewrite what somebody was given.
    reason: Mapped[str] = mapped_column(String(200), server_default="")

    awarded_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<BadgeAward badge={self.badge_id} user={self.user_id}>"
