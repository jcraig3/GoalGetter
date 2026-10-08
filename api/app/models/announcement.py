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
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

#: Where an announcement can go. `slack` is reserved for the next still-open
#: item; the table is shaped for it now so it arrives as a new kind rather than
#: a second table.
KINDS = ("teams", "slack")

#: How a Teams channel is reached: its own Workflows link, or picked from the
#: signed-in account's Teams and posted to through Microsoft Graph.
VIAS = ("workflow", "graph")


class AnnouncementDestination(Base, TimestampMixin):
    """A chat channel wins are posted to — "what to announce, and where".

    **A Teams channel is reached through its own Workflows link**, not through
    Microsoft Graph. Graph can post to a channel only as a signed-in person —
    application-only posting is reserved for migrations — so going that way
    would mean a real account whose departure silently stops every
    announcement. Microsoft retired the old channel webhooks in May 2026 and
    Workflows is the replacement: a link somebody makes in the channel, which
    accepts a card. It needs no app registration and no permission, which is
    also why this works for an organization that never connected Microsoft 365.

    **Or picked from a list** (`via = graph`), which is what most people expect:
    one account signs in once, and every channel it is in can be chosen from a
    dropdown. The cost is the one above — posts come from that account, and stop
    if it is disabled — so both ways are offered and the page says which is
    which.
    """

    __tablename__ = "announcement_destination"
    __table_args__ = (
        CheckConstraint("kind IN ('teams', 'slack')", name="announcement_kind_valid"),
        # Whose wins: everybody's, one office's or one team's — never both.
        CheckConstraint(
            "office_id IS NULL OR team_id IS NULL", name="announcement_one_scope"
        ),
        Index("ix_announcement_destination_org", "organization_id"),
        CheckConstraint(
            "(via = 'workflow' AND webhook_url IS NOT NULL) OR "
            "(via = 'graph' AND team_external_id IS NOT NULL AND channel_external_id IS NOT NULL)",
            name="announcement_how_reached",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(16), default="teams")

    #: What the admin calls it: "Sales floor channel".
    name: Mapped[str] = mapped_column(String(80))

    #: The channel's webhook link, **encrypted**. It carries its own signature,
    #: so anybody holding it can post into that channel — it is a credential,
    #: and it is never sent back to a browser in full.
    webhook_url: Mapped[str | None] = mapped_column(Text)

    via: Mapped[str] = mapped_column(String(16), default="workflow", server_default="workflow")
    #: For `graph`: the Team and channel by Microsoft's ids, and how to name them.
    team_external_id: Mapped[str | None] = mapped_column(String(200))
    channel_external_id: Mapped[str | None] = mapped_column(String(200))
    channel_label: Mapped[str | None] = mapped_column(String(300))

    #: Which kinds of win, from `app/announcements.py`'s `CHOICES`.
    events: Mapped[list] = mapped_column(JSONB, default=list)

    #: Whose wins, by the same snapshot columns a wall uses: the office or team
    #: somebody was in when they earned it.
    office_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("office.id", ondelete="CASCADE")
    )
    team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id", ondelete="CASCADE")
    )

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    #: The highest notification id already considered. Set to the newest one
    #: when the destination is made, so a new channel is not flooded with every
    #: win from before it existed.
    last_notification_id: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")

    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnnouncementDelivery(Base):
    """One win, posted — or trying to be — to one destination."""

    __tablename__ = "announcement_delivery"
    __table_args__ = (
        # **Once per win per channel**, whatever a job restart or a team goal
        # reaching eight people does. The key is the same one-per-win key the
        # wall uses, so eight notification rows about one team goal are one post.
        Index("uq_announcement_delivery_once", "destination_id", "win_key", unique=True),
        Index(
            "ix_announcement_delivery_due",
            "destination_id",
            "next_attempt_at",
            postgresql_where="status IN ('pending', 'retrying')",
        ),
        CheckConstraint(
            "status IN ('pending', 'retrying', 'sent', 'gave_up')",
            name="announcement_delivery_status_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    destination_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("announcement_destination.id", ondelete="CASCADE")
    )
    notification_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("notification.id", ondelete="SET NULL")
    )
    win_key: Mapped[str] = mapped_column(String(200))

    #: The card, built when the win was found. Stored so a retry posts exactly
    #: what the first attempt did, even if the notification has since been
    #: pruned.
    payload: Mapped[dict] = mapped_column(JSONB)

    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(String(500))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
