from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

#: What a source is. A Team is a Microsoft 365 group with Teams switched on; a
#: channel belongs to one.
SOURCE_KINDS = ("team", "channel")

#: How a channel decides who is in it. **Only `private` and `shared` have their
#: own members** — a standard channel contains exactly its Team, which is why it
#: can sort nobody and cannot be linked. See `app/directory/mirror.py`.
MEMBERSHIPS = ("standard", "private", "shared")

#: What a source can become here.
TARGETS = ("team", "office")


class M365Source(Base):
    """A Microsoft Team or one of its channels, as directory sync last saw it.

    **Kept by Microsoft's own id**, not by name, so renaming a Team in Microsoft
    renames it here on the next sync instead of breaking whatever it was linked
    to. Never deleted when it disappears — a link might point at it — only
    marked as gone, so the settings page can say "this Team no longer exists".
    """

    __tablename__ = "m365_source"
    __table_args__ = (
        CheckConstraint("kind IN ('team', 'channel')", name="m365_source_kind_valid"),
        CheckConstraint(
            "membership IS NULL OR membership IN ('standard', 'private', 'shared')",
            name="m365_source_membership_valid",
        ),
        Index("uq_m365_source", "organization_id", "kind", "external_id", unique=True),
        Index("ix_m365_source_parent", "parent_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(16))
    #: The group id for a Team, the channel id for a channel.
    external_id: Mapped[str] = mapped_column(String(200))
    #: The Team a channel belongs to.
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("m365_source.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(300))
    #: For a channel.
    membership: Mapped[str | None] = mapped_column(String(16))

    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    #: When a sync stopped finding it.
    gone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class M365Member(Base):
    """Somebody in a Team or in a private or shared channel.

    Keyed by the directory's id for the person — the same `external_id` a
    `directory_person` row carries — so a membership does not depend on an email
    address somebody might change. Standard channels have no rows: their members
    are their Team's.
    """

    __tablename__ = "m365_member"

    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("m365_source.id", ondelete="CASCADE"), primary_key=True
    )
    person_external_id: Mapped[str] = mapped_column(String(200), primary_key=True)


class M365Link(Base, TimestampMixin):
    """"This Team or channel is a GoalGetter team" — or an office.

    One target per source, and one source per target: two Teams feeding one
    GoalGetter team would make "who belongs here" two questions.
    """

    __tablename__ = "m365_link"
    __table_args__ = (
        CheckConstraint("target IN ('team', 'office')", name="m365_link_target_valid"),
        CheckConstraint(
            "(target = 'team' AND team_id IS NOT NULL AND office_id IS NULL) OR "
            "(target = 'office' AND office_id IS NOT NULL AND team_id IS NULL)",
            name="m365_link_one_target",
        ),
        Index("uq_m365_link_source", "source_id", unique=True),
        Index("uq_m365_link_team", "team_id", unique=True, postgresql_where="team_id IS NOT NULL"),
        Index("uq_m365_link_office", "office_id", unique=True, postgresql_where="office_id IS NOT NULL"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("m365_source.id", ondelete="CASCADE")
    )
    target: Mapped[str] = mapped_column(String(16))
    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id", ondelete="CASCADE")
    )
    office_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("office.id", ondelete="CASCADE")
    )


class MirrorPlacement(Base):
    """Where the mirror last put somebody — which is how it knows a hand move.

    **The mirror only undoes its own work.** If somebody's team no longer
    matches where the mirror last placed them, an admin moved them, and the
    mirror leaves them there and says so — rather than quietly moving them back
    on the next sync. That keeps GoalGetter a place people can be managed by
    hand while Microsoft 365 is a source of truth too, and it needs no change to
    how a person's own details are edited: the evidence is simply that their
    team is not the one the mirror chose.

    `pinned` is an admin saying "keep them here" about a hand move, so it stops
    being listed as something to resolve.
    """

    __tablename__ = "mirror_placement"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id", ondelete="SET NULL")
    )
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
