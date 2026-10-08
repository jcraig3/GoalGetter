from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Display(Base, TimestampMixin):
    """A wall screen, authenticated by a URL rather than an account.

    A TV in a sales floor has no keyboard and nobody to log it in, so it holds
    a long-lived secret in its address bar instead. That is a real trade: the
    URL *is* the credential, and anyone who photographs it has the board.

    Three things make it acceptable:

      * It grants **one channel, read-only**, and nothing else. No user list,
        no goals, no raw facts, no way back into the app.
      * Only boards published to the whole organization can appear on one, so
        a display can never show something its audience could not already see
        by signing in.
      * It is revocable in one click, and `last_seen_at` shows whether the
        screen it was issued for is still alive.

    A `viewer` role existed for this once and was dropped: the token scopes
    access precisely, so the role protected nothing and added a column to every
    permission table.
    """

    __tablename__ = "display"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )

    #: What it is, for whoever has to find and revoke it later. "Phoenix wall
    #: screen by the stairs" is worth more than "Display 3".
    name: Mapped[str] = mapped_column(String(120))

    #: The channel it plays.
    #:
    #: Was `office_id` through Phase 1, when a channel was derived: point a
    #: display at an office and it played every TV-enabled board matching it.
    #: That put the running order out of anybody's hands and made a board the
    #: only thing a wall could show. Now it points at an authored playlist, and
    #: several displays can share one — the usual case for two TVs on a floor.
    channel_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("channel.id", ondelete="CASCADE"), index=True
    )

    #: The value in the URL, stored as-is.
    #:
    #: A deliberate exception to the rule that credentials are hashed at rest,
    #: which every other token in this system follows. A wall display has to be
    #: *operable*: somebody sets a TV up weeks after the link was issued, or
    #: emails it to whoever is standing next to the screen. A hash makes the
    #: link unrecoverable, and the honest consequence of that is admins
    #: reissuing links constantly, or writing them down somewhere far less safe
    #: than this table.
    #:
    #: The trade is affordable only because of what the token grants: one
    #: channel, read-only, boards already published to the whole organization,
    #: and revocable in one click. It is closer to an unlisted URL than to a
    #: password — and unlike a password, it is displayed on a wall all day.
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    #: Updated when the screen fetches its feed, so an admin can tell a live
    #: display from one that was unplugged months ago and never revoked.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Since when this screen's browser has been holding sound back (Phase 24),
    #: as the screen reports it: a page can't start sound by itself until the
    #: browser allows it, and nobody clicks a TV. Cleared once something plays
    #: with sound. Shown on TVs & Channels with how to allow it.
    sound_blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Revoked rather than deleted, so the row survives as the record that a
    #: URL was once issued and by whom.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: When somebody last asked this screen to reload itself.
    #:
    #: **The hardest thing in the product to fix is a wall.** A browser open
    #: since a deploy three weeks ago is running the old bundle; one that has
    #: wedged shows a frozen board. The screen is high up and the nearest
    #: keyboard is three rooms away.
    #:
    #: The feed carries this; the screen remembers the value it started with
    #: and reloads when it changes. A column rather than a message queue,
    #: because the wall already polls every minute and this rides along in the
    #: answer it was going to fetch anyway.
    reload_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<Display {self.name!r} office={self.office_id}>"
