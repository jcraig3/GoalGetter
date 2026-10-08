from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from decimal import Decimal

from app.models.base import Base, TimestampMixin

#: How a fact's value is compared against the threshold.
#:
#: Two, not a expression language. "A deal over $5,000" and "a response under
#: 60 seconds" cover what a sales floor celebrates, and every operator beyond
#: them is one more thing to validate, explain, and get wrong on a wall.
COMPARATORS = ("gte", "lte")

#: Who a rule applies to.
SCOPES = ("everyone", "team")


class AchievementRule(Base, TimestampMixin):
    """Celebrate a piece of work, rather than the completion of a goal.

    A goal is a target over a period. "Closed a deal over $5,000" is neither,
    and it is most of what a sales floor actually celebrates — so until this
    existed the only way to mark one was for a manager to notice and write a
    shout-out by hand.

    Matches Spinify's achievements, which fire on any record matching a filter
    rather than on a goal being met. See
    documentation/11-notifications-and-celebrations.md.
    """

    __tablename__ = "achievement_rule"
    __table_args__ = (
        CheckConstraint(
            "comparator IN ('gte', 'lte')", name="comparator_valid"
        ),
        CheckConstraint("scope IN ('everyone', 'team')", name="scope_valid"),
        # A team-scoped rule needs a team; an everyone-scoped one must not have
        # one, or the column would silently mean nothing.
        CheckConstraint(
            "(scope = 'team' AND scope_team_id IS NOT NULL) OR "
            "(scope = 'everyone' AND scope_team_id IS NULL)",
            name="scope_matches_team",
        ),
        Index("ix_achievement_rule_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )

    #: What the wall says. "Big deal closed" rather than "revenue_closed >= 5000".
    name: Mapped[str] = mapped_column(String(120))

    metric_definition_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("metric_definition.id", ondelete="CASCADE")
    )
    comparator: Mapped[str] = mapped_column(String(8))
    threshold: Mapped[Decimal] = mapped_column(Numeric(18, 4))

    scope: Mapped[str] = mapped_column(String(16), default="everyone")
    scope_team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id", ondelete="CASCADE")
    )

    #: What the announcement says, one alternative per line.
    #:
    #: Empty is the fixed shape this always had — the rule's name over
    #: "Peter Parker — $6,200" — which is correct and is the same sentence
    #: every time. Several lines is the air-gapped answer to a floor tuning it
    #: out: one is picked per win, seeded by the win, so the same piece of work
    #: always reads the same way and the next one probably does not.
    #:
    #: See `app/merge_tags.py` for what may go in it.
    message: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    #: What plays on the wall for *this kind of win*, alongside whatever
    #: walk-up media the person has. A rule's media is about the achievement
    #: ("every big deal plays this"); a person's is about them.
    media_url: Mapped[str | None] = mapped_column(String(500))
    media_start_seconds: Mapped[int | None] = mapped_column(Integer)
    media_end_seconds: Mapped[int | None] = mapped_column(Integer)

    #: Whether somebody's own walk-up music beats this rule's media.
    #:
    #: On by default, and that is the interesting default. The rule's clip then
    #: acts as the **fallback** — everybody gets something, and the people who
    #: have bothered to choose their own get theirs. Most people never open
    #: their settings, so a rule with media and this switch on is how a floor
    #: ends up with sound at all.
    #:
    #: Off forces the rule's clip on everybody, for the win that should always
    #: sound the same — a gong for a record month. Off with no media set is a
    #: deliberate silence: the announcement still appears on the screen, it
    #: just does not play anything.
    allow_personal_media: Mapped[bool] = mapped_column(Boolean, default=True)

    #: Org-wide off switch, separate from each person's own mute.
    #:
    #: Disabling stops it firing from now on and leaves what it already
    #: announced alone. **This is the archive**, and it is reversible from the
    #: list — a rule you want back is one click away.
    #:
    #: There was an `archived_at` column here as well, doing the same job one
    #: way only: nothing could restore it and the list filtered it out, so an
    #: archived rule was invisible and unrecoverable. Two mechanisms for one
    #: outcome, one of them a trapdoor. Deleting now really deletes, which is
    #: safe because nothing points at a rule — see the delete endpoint.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    #: What one of these is worth in the points economy.
    #:
    #: On the rule rather than in `point_value`, because it is an attribute of
    #: this rule — edited in the same form as its message and its media, by
    #: somebody who is already thinking about how often it will fire.
    #:
    #: The default is low on purpose. A rule fires on *every* matching record,
    #: so it is the one award whose volume nobody can predict at the moment
    #: they write it: "a deal over $5,000" might be twice a month or twice an
    #: hour, and one careless threshold at 100 points apiece would swamp every
    #: other source in the economy. Zero is allowed and means "celebrate it,
    #: do not pay for it", which is a reasonable thing to want.
    points: Mapped[int] = mapped_column(Integer, default=10, server_default="10")

    #: The highest `metric_fact.id` this rule has already considered.
    #:
    #: Purely an optimisation: without it every pass would re-examine every
    #: fact in the table forever. Correctness does not depend on it — the
    #: unique index on `notification` is what guarantees one announcement per
    #: fact — so a watermark that is wrong costs time, not duplicates.
    last_fact_id: Mapped[int] = mapped_column(BigInteger, default=0)

    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )
    @property
    def event_key(self) -> str:
        """What a notification from this rule is keyed on.

        Includes the id, so two rules on the same metric are two different
        events and one cannot suppress the other through the unique index.
        """
        return f"achievement:{self.id}"

    def __repr__(self) -> str:
        return f"<AchievementRule {self.name!r} {self.comparator} {self.threshold}>"
