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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

#: What a segment of the wheel gives.
#:
#:     points    paid into the wallet on the spot
#:     prize     something real — a long lunch, a gift card — that a person
#:               has to hand over, and so goes on a list until they do
#:     nothing   a miss, said plainly
#:
#: Three, because the difference between them decides what happens *after*
#: the wheel stops. A real prize with no list behind it is a promise that
#: gets forgotten on a Friday afternoon.
PRIZE_KINDS = ("points", "prize", "nothing")


class PrizeWheel(Base, TimestampMixin):
    """The wheel's own settings. One per organization."""

    __tablename__ = "prize_wheel"
    __table_args__ = (
        Index("uq_prize_wheel_org", "organization_id", unique=True),
        CheckConstraint("spin_cost > 0", name="prize_wheel_cost_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )

    #: What one spin takes out of the wallet.
    spin_cost: Mapped[int] = mapped_column(Integer, default=100)

    #: Off until an admin has put something on it. A wheel that can be spun
    #: with no prizes is a way to lose points to an animation.
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class WheelPrize(Base, TimestampMixin):
    """One segment."""

    __tablename__ = "wheel_prize"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('points', 'prize', 'nothing')", name="wheel_prize_kind_valid"
        ),
        # Points only on a points segment, and a points segment has to pay
        # something — otherwise it is a "nothing" wearing the wrong label.
        CheckConstraint(
            "(kind = 'points' AND points > 0) OR (kind <> 'points' AND points = 0)",
            name="wheel_prize_points_match_kind",
        ),
        CheckConstraint("weight > 0", name="wheel_prize_weight_positive"),
        # Stock only means something for a real prize: there are only so many
        # gift cards in the drawer. Points and misses are unlimited by nature.
        CheckConstraint(
            "stock IS NULL OR (kind = 'prize' AND stock >= 0)",
            name="wheel_prize_stock_only_for_prizes",
        ),
        Index("ix_wheel_prize_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )

    #: What the segment says: "Long lunch", "+250", "So close".
    label: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(16))
    points: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    #: How likely, relative to the others. A weight rather than a percentage
    #: so adding a segment never means re-balancing all the rest by hand — and
    #: so the percentages shown to a spinner are always the true ones, computed
    #: rather than typed.
    weight: Mapped[int] = mapped_column(Integer, default=1)

    #: How many are left, for a real prize. Null means unlimited. At zero the
    #: segment drops out of the draw, and out of the odds shown.
    stock: Mapped[int | None] = mapped_column(Integer)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class WheelSpin(Base):
    """One spin, what it landed on, and — for a real prize — whether anybody
    has handed it over yet.

    The label and kind are copied at the moment of the spin, for the same
    reason a notification stores its title: renaming a segment afterwards must
    not rewrite what somebody won.
    """

    __tablename__ = "wheel_spin"
    __table_args__ = (
        Index("ix_wheel_spin_person", "user_id", "id"),
        # The list somebody works through on a Friday: real prizes not yet
        # handed over. Partial, so it never grows past the handful waiting.
        Index(
            "ix_wheel_spin_waiting",
            "organization_id",
            "id",
            postgresql_where="kind = 'prize' AND given_at IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE")
    )
    #: Null once the segment is deleted. The spin still happened, and the
    #: copied label says what it was.
    prize_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("wheel_prize.id", ondelete="SET NULL")
    )

    label: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(16))
    cost: Mapped[int] = mapped_column(Integer)
    points_won: Mapped[int] = mapped_column(Integer, default=0)

    given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    given_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
