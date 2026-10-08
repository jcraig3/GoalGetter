from datetime import time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

#: What a screen can be.
#:
#: Each kind reads exactly one payload column, enforced below — a `video`
#: screen with a `leaderboard_id` and no URL would render nothing and look like
#: a bug in the display rather than a half-filled row.
SCREEN_KINDS = (
    "leaderboard",
    "goal",
    "competition",
    "achievements",
    "image",
    "video",
    "message",
    "spotlight",
    "comparison",
)

#: How long a screen holds the wall before the rotation moves on.
#:
#: Twenty seconds is long enough to find your own name on a board and short
#: enough that a six-screen channel comes round inside two minutes. Spinify
#: defaults its achievements to 45s, which is right for something you watch and
#: wrong for something you scan.
DEFAULT_DWELL_SECONDS = 20

#: Who a channel is about.
#:
#: The thing that stops one office's numbers turning up on another office's
#: wall. Set once on the channel, inherited by every screen, overridable per
#: screen for the deliberate exception — the company-wide board on a floor
#: that otherwise only shows itself.
SCOPES = ("organization", "office", "team")


class Channel(Base, TimestampMixin):
    """An authored playlist for a wall screen.

    Replaces the derived channel from Phase 1, where a display pointed at an
    office and played every TV-enabled board that matched. That put the
    ordering out of anybody's hands and made a board the only thing a wall
    could show.

    A channel is a name and an ordered list of screens. A display points at
    one, and several displays can point at the same one — which is the usual
    case for two TVs on one floor.
    """

    __tablename__ = "channel"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('organization', 'office', 'team')", name="scope_valid"
        ),
        # The pointer has to match the kind, or the column silently means
        # nothing — the same shape as `goal.subject_matches_type`.
        CheckConstraint(
            "(scope_type = 'organization' AND scope_office_id IS NULL AND scope_team_id IS NULL) OR "
            "(scope_type = 'office' AND scope_office_id IS NOT NULL AND scope_team_id IS NULL) OR "
            "(scope_type = 'team' AND scope_team_id IS NOT NULL AND scope_office_id IS NULL)",
            name="scope_matches_type",
        ),
        CheckConstraint("quiet_mode IN ('off', 'clock', 'dark')", name="quiet_mode_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))

    #: Overrides for how this looks on a wall. Empty means inherit from the
    #: organization; see `app/appearance.py`, which owns the shape and the merge.
    appearance: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    #: Addresses allowed to fetch this channel. Empty means anywhere.
    #:
    #: The strongest answer to the readable display token from 1f-iv. That
    #: token is the whole credential and is visible in a browser's address bar
    #: on a wall all day, so the realistic leak is somebody photographing a
    #: screen. An allowlist makes the photograph useless: the link only works
    #: from the office network.
    #:
    #: Empty by default, and it has to be. A deployment behind a NAT nobody has
    #: written down would otherwise blank every screen on upgrade, and the
    #: person diagnosing it is standing in front of a television.
    #:
    #: Stored as CIDR strings rather than Postgres `inet` — the comparison
    #: happens in Python against one channel, so the database type would buy an
    #: operator we never use and a migration if the shape ever changes.
    allowed_ips: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, server_default="{}"
    )

    #: The channel's audience. Every screen inherits it unless it says
    #: otherwise, so a wall is right by default and spillover is something
    #: somebody chose rather than something they forgot.
    scope_type: Mapped[str] = mapped_column(String(16), default="organization")
    scope_office_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("office.id", ondelete="CASCADE")
    )
    scope_team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id", ondelete="CASCADE")
    )

    # No `archived_at`, unlike teams, offices and goals.
    #
    # Those three earn it: `metric_fact` points at a team and an office with
    # ON DELETE NO ACTION, so the database refuses to delete one that has any
    # history — archiving is the only way to retire it. And an archived goal
    # answers "what did we hit last quarter".
    #
    # A channel is pure configuration. No fact, notification or export
    # references one, and nothing about last month is harder to answer once it
    # is gone. An archived state here was a tab, two endpoints and a
    # third thing every list had to reason about, in exchange for nothing.

    #: **Night mode** (6.10): what the wall shows out of hours instead of the
    #: rotation — `clock`, a large clock drifting slowly round the screen, or
    #: `dark`, near-black with a small one. Both move, so nothing burns in.
    #: Real celebrations wait for the morning; previews still show, so
    #: somebody setting up after hours can see their work.
    quiet_mode: Mapped[str] = mapped_column(String(8), default="off", server_default="off")
    #: The nightly window, in the organization's time. It may cross midnight
    #: (19:00–07:00), which is the usual case.
    quiet_from: Mapped[time | None] = mapped_column(Time)
    quiet_until: Mapped[time | None] = mapped_column(Time)
    #: Quiet all Saturday and Sunday as well.
    quiet_weekends: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    def __repr__(self) -> str:
        return f"<Channel {self.name!r}>"


class ChannelScreen(Base, TimestampMixin):
    """One slide in a channel's rotation."""

    __tablename__ = "channel_screen"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('leaderboard', 'goal', 'competition', 'achievements', "
            "'image', 'video', 'message', 'spotlight', 'comparison')",
            name="kind_valid",
        ),
        # Exactly the payload its kind needs, and nothing else.
        #
        # The same shape as `goal.subject_matches_type`: a row that cannot
        # render must not be storable, because the alternative is a screen that
        # goes blank in front of an office and a bug report that says "the TV
        # broke".
        CheckConstraint(
            "(kind = 'leaderboard' AND leaderboard_id IS NOT NULL) OR "
            "(kind = 'goal' AND goal_id IS NOT NULL) OR "
            "(kind = 'competition' AND competition_id IS NOT NULL) OR "
            "(kind = 'achievements') OR "
            "(kind IN ('image', 'video') AND url IS NOT NULL) OR "
            "(kind = 'message' AND title IS NOT NULL) OR "
            # A spotlight names a person, a board, or both. Board alone means
            # "whoever leads it right now", which is the form that keeps itself
            # up to date; person alone is the employee-of-the-month card.
            "(kind = 'spotlight' AND (user_id IS NOT NULL OR leaderboard_id IS NOT NULL)) OR "
            # Like `achievements`: what a comparison shows lives in
            # `channel_screen_board`, so there is nothing on this row to check.
            "(kind = 'comparison')",
            name="payload_matches_kind",
        ),
        # Up to an hour (Phase 26): a video screen plays for as long as asked —
        # "start 40 seconds in, play for 60" — and a long one is a real wish.
        CheckConstraint("dwell_seconds BETWEEN 5 AND 3600", name="dwell_sane"),
        CheckConstraint("weight BETWEEN 1 AND 4", name="weight_sane"),
        CheckConstraint(
            "scope_type IS NULL OR "
            "(scope_type = 'organization' AND scope_office_id IS NULL AND scope_team_id IS NULL) OR "
            "(scope_type = 'office' AND scope_office_id IS NOT NULL) OR "
            "(scope_type = 'team' AND scope_team_id IS NOT NULL)",
            name="override_matches_type",
        ),
        # The rotation reads in this order, so it is the access path.
        Index("ix_channel_screen_order", "channel_id", "position"),
    )

    #: Overrides for how this looks on a wall. Empty means inherit from the
    #: organization; see `app/appearance.py`, which owns the shape and the merge.
    appearance: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("channel.id", ondelete="CASCADE")
    )

    #: Where in the rotation. Sparse and rewritten wholesale on reorder rather
    #: than nudged — drag-and-drop sends the whole order, so there is never a
    #: half-applied shuffle to reason about.
    position: Mapped[int] = mapped_column(Integer)

    kind: Mapped[str] = mapped_column(String(24))
    dwell_seconds: Mapped[int] = mapped_column(
        Integer, default=DEFAULT_DWELL_SECONDS
    )

    #: **A video screen starts here** (Phase 26), seconds in — and plays for
    #: `dwell_seconds`. NULL: from the beginning.
    media_start_seconds: Mapped[int | None] = mapped_column(Integer)
    #: **How a picture screen fills the TV** (Phase 26): `cover`, the whole
    #: screen, cropping what doesn't fit; `contain`, all of the picture, with
    #: bars. NULL is `cover`.
    fit: Mapped[str | None] = mapped_column(String(8))

    #: **When it plays** (6.10), in the organization's time: the days of the
    #: week (0 is Monday; NULL is every day) and the hours (either end may be
    #: open, and a window may cross midnight). Outside them the slide is left
    #: out of the rotation. See `app/schedule.py`.
    days: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    play_from: Mapped[time | None] = mapped_column(Time)
    play_until: Mapped[time | None] = mapped_column(Time)
    #: How many times it comes round in one cycle, spread evenly.
    weight: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    #: CASCADE, not SET NULL: a screen whose board was deleted cannot render,
    #: and the CHECK above would refuse to let it exist with a null id anyway.
    leaderboard_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("leaderboard.id", ondelete="CASCADE")
    )
    goal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("goal.id", ondelete="CASCADE")
    )
    competition_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("competition.id", ondelete="CASCADE")
    )

    #: For `spotlight`: the person it is about.
    #:
    #: Optional even for a spotlight — a screen with only a `leaderboard_id`
    #: follows whoever is leading, which is the whole point of the thing being
    #: a screen rather than an uploaded image.
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE")
    )

    #: For `image` and `video`. Validated through `app.media` on the way in, so
    #: a wall screen never fetches an arbitrary URL — see the reasoning there.
    url: Mapped[str | None] = mapped_column(String(500))

    #: For `message`: something a person wrote for the room.
    title: Mapped[str | None] = mapped_column(String(120))
    body: Mapped[str | None] = mapped_column(String(500))

    #: Overrides the channel's audience for this one screen.
    #:
    #: NULL means inherit, which is the case for almost every screen. The
    #: override exists for the company-wide board on a floor that otherwise
    #: shows only itself — a deliberate exception rather than a field somebody
    #: has to fill in every time.
    scope_type: Mapped[str | None] = mapped_column(String(16))
    scope_office_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("office.id", ondelete="CASCADE")
    )
    scope_team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id", ondelete="CASCADE")
    )

    def __repr__(self) -> str:
        return f"<ChannelScreen {self.kind} pos={self.position}>"


class ChannelScreenBoard(Base):
    """One panel of a comparison screen.

    **A row per panel rather than four nullable columns**, so the limit is a
    rule about what reads on a television rather than something baked into the
    schema — and so "which order are they in" has an answer.

    No `TimestampMixin`: a panel has no life of its own. It is created and
    destroyed wholesale with the screen it belongs to, and "when was this
    column added" is a question nobody asks about a layout.
    """

    __tablename__ = "channel_screen_board"
    __table_args__ = (
        # The same board twice is two identical columns — a mistake every time
        # rather than a layout anybody wanted.
        UniqueConstraint(
            "channel_screen_id", "leaderboard_id", name="one_panel_per_board"
        ),
        Index("ix_channel_screen_board_order", "channel_screen_id", "position"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_screen_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("channel_screen.id", ondelete="CASCADE")
    )
    #: CASCADE: a panel whose board was deleted has nothing to draw. The screen
    #: keeps its remaining panels rather than going blank — see
    #: `channels._comparison`.
    leaderboard_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leaderboard.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)

    def __repr__(self) -> str:
        return f"<ChannelScreenBoard screen={self.channel_screen_id} pos={self.position}>"
