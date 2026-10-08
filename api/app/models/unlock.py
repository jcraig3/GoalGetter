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

#: What a cosmetic changes.
#:
#: Two, and both are things other people *see*, which is the test for whether
#: a cosmetic is worth its price. A ring goes round somebody's face everywhere
#: it appears, the wall included; a title sits under their name. Neither needs
#: artwork, which is the thing that deferred the trophies in 4f and the badge
#: marks in 4j-iii.
KINDS = ("ring", "title")


class Unlockable(Base, TimestampMixin):
    """Something points can buy.

    **Why this exists at all:** in the economy this product was measured
    against, lifetime points equalled reward points because nothing was ever
    spent. A number you can only accumulate is a number that eventually stops
    meaning anything, and a season reset fixes the ranking without giving the
    points a use. This gives them one — without building a store, which would
    mean stock, shipping, and somebody in finance.

    Titles are written by an admin, never typed by the person wearing one.
    A free-text title on a television in reception is a moderation job nobody
    signed up for.
    """

    __tablename__ = "unlockable"
    __table_args__ = (
        CheckConstraint("kind IN ('ring', 'title')", name="unlockable_kind_valid"),
        CheckConstraint("price > 0", name="unlockable_price_positive"),
        Index("uq_unlockable_name", "organization_id", "name", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )

    #: What it is called in the list: "Gold ring", "The Closer".
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(16))

    #: For a ring, a `#rrggbb` colour. For a title, the words shown.
    value: Mapped[str] = mapped_column(String(40))

    price: Mapped[int] = mapped_column(Integer)

    #: Whether it can still be bought.
    #:
    #: **The way to retire one**, rather than deleting it. Somebody paid for
    #: it; taking it off them because an admin tidied the list would be taking
    #: their points back without saying so. Retired, it cannot be bought and
    #: everybody who has one keeps it. Deleting is allowed only while nobody
    #: owns it.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    def __repr__(self) -> str:
        return f"<Unlockable {self.name!r} {self.kind} {self.price}>"


class Unlock(Base):
    """One person owning one cosmetic, and whether they are wearing it.

    Bought once and kept. Cosmetics do not reset with the season — they are
    what somebody spent their points *on*, and a purchase that vanished every
    quarter would be a rental nobody was told about.
    """

    __tablename__ = "unlock"
    __table_args__ = (
        # Once each. The spend and this insert share a transaction, and the
        # person's row is locked before either — so a double-click cannot buy
        # twice — but the index is what makes it impossible rather than
        # merely handled.
        Index("uq_unlock_once", "unlockable_id", "user_id", unique=True),
        # **One of each kind worn at a time.** Two rings is a rendering
        # question with no good answer, and two titles is a sentence.
        Index(
            "uq_unlock_worn",
            "user_id",
            "kind",
            unique=True,
            postgresql_where="equipped",
        ),
        CheckConstraint("kind IN ('ring', 'title')", name="unlock_kind_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    unlockable_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("unlockable.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE")
    )

    #: Copied from the unlockable, so "one worn per kind" can be a unique index
    #: on this table alone. An unlockable's kind never changes after it is
    #: bought — the edit endpoint refuses it — so the copy cannot go stale.
    kind: Mapped[str] = mapped_column(String(16))

    #: Worn rather than merely owned. Kept here rather than on `user_account`,
    #: which this feature does not touch at all.
    equipped: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    #: What was paid, recorded at the time. The price can change afterwards;
    #: what somebody spent does not.
    paid: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<Unlock {self.unlockable_id} user={self.user_id}>"
