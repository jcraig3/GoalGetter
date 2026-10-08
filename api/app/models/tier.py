from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Tier(Base, TimestampMixin):
    """A rung on the ladder: reach this many points in a season and you are Gold.

    **Measured against the season balance, never the lifetime total**, and that
    is the whole reason this table did not exist until seasons did. The account
    this product was measured against had a top tier at 100,000 points and a
    top dozen reps sitting between 165,000 and 178,000 — every one of them had
    been Platinum for over a year, and the ladder had stopped being a ladder.
    A tier read against a number that only grows is a tier everybody
    eventually has.

    There are two ways to get this wrong and they look nothing alike:

        threshold too high   nobody reaches it, so nobody aims at it
        threshold too low    everybody passes it, so it says nothing

    Both are invisible when you are typing round numbers into a form, which is
    why `app/tiers.py` suggests them from what people have actually scored
    rather than leaving an admin to guess.

    No colour or icon column. A tier is a name and a number; how it is drawn
    belongs to the appearance layer like everything else that is drawn.
    """

    __tablename__ = "tier"
    __table_args__ = (
        # Two rungs at the same height is not a ladder — it is two names for
        # one thing, and `tier_for` would have to pick between them.
        Index("uq_tier_threshold", "organization_id", "threshold", unique=True),
        Index("uq_tier_name", "organization_id", "name", unique=True),
        # A rung at zero would be held by everybody who has never scored,
        # which is the "says nothing" failure in its purest form.
        CheckConstraint("threshold > 0", name="tier_threshold_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )

    name: Mapped[str] = mapped_column(String(40))

    #: Season points needed to hold it. Order is the ladder — there is no
    #: `position` column, because a position that disagreed with the threshold
    #: would be a bug nobody could see.
    threshold: Mapped[int] = mapped_column(Integer)

    def __repr__(self) -> str:
        return f"<Tier {self.name!r} at {self.threshold}>"
