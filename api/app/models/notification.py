from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Notification(Base):
    """Something happened, addressed to one person.

    The line this table draws is worth stating, because the dashboard already
    carries something that looks similar and is not. The attention banner —
    "3 goals behind pace" — is *state*: recomputed on every load, addressed to
    nobody, and it disappears on its own when the condition clears. A
    notification is an *event*: it happened, it is addressed, and it stays
    until somebody has seen it.

    The test is "if it stops being true, should it vanish?" Yes means it is
    state and belongs on a dashboard. No means it belongs here.

    No `updated_at`: the only mutation is `read_at`, which is its own timestamp.
    """

    __tablename__ = "notification"
    __table_args__ = (
        # **The idempotency guarantee**, and the reason nothing stores a "last
        # notified status" anywhere.
        #
        # Detection is a job that runs every few minutes over goals whose
        # progress is a query, not a column. Without this it would have to
        # remember what it had already announced, which means storing derived
        # state and invalidating it from every write path. Instead the row
        # *is* the record that we announced it: the job inserts with ON
        # CONFLICT DO NOTHING and stops caring about races entirely. Two
        # workers, or one worker restarted mid-run, cannot produce two
        # announcements because the second insert is impossible rather than
        # merely unlikely. Same reasoning as the partial unique index that
        # keeps recurring goals from spawning twice.
        #
        # NULLS NOT DISTINCT is load-bearing. Postgres treats NULLs as distinct
        # in a unique index by default, so without it every event with no
        # period — a competition starting, say — would insert again on every
        # single job cycle, forever. The default is the wrong one here.
        #
        # PARTIAL, on `created_by_user_id IS NULL`. Detected events latch;
        # authored ones must repeat, because two good weeks are two shout-outs
        # and a manager praising the same person twice is the feature working.
        Index(
            "uq_notification_once",
            "organization_id",
            "user_id",
            "subject_type",
            "subject_id",
            "period_anchor",
            "event_key",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where="created_by_user_id IS NULL",
        ),
        # The unread badge, forever. A partial index only holds unread rows, so
        # it never grows past the number of genuinely unread notifications no
        # matter how much history accumulates behind it.
        Index(
            "ix_notification_unread",
            "user_id",
            "created_at",
            postgresql_where="read_at IS NULL",
        ),
        # The centre and the public feed, both of which read newest-first.
        Index("ix_notification_feed", "organization_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )

    #: Who hears about it. A notification always has exactly one recipient —
    #: an event affecting five people is five rows, so read state, preferences
    #: and the unread count are all per person without any fan-out logic.
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE")
    )

    #: Which event this is, from the catalogue in `app/events.py`. A string
    #: rather than an enum column: the catalogue gains entries as features
    #: land, and a CHECK constraint listing them would need a migration for
    #: every one while protecting against a mistake the catalogue already
    #: prevents.
    event_key: Mapped[str] = mapped_column(String(64))

    #: What it is about — ("goal", 41). Together with `period_anchor` this is
    #: what makes "announce once" expressible.
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[int] = mapped_column(BigInteger)

    #: The period the event belongs to, for anything that recurs. August's
    #: "you hit your goal" and September's are different events about the same
    #: goal, and only this tells them apart. NULL for events with no period.
    period_anchor: Mapped[date | None] = mapped_column(Date)

    #: Written at emit rather than rendered at read. The alternative is
    #: reconstructing the sentence from the subject every time it is displayed,
    #: which would silently rewrite history: rename a goal and last month's
    #: notification would start describing something that never happened.
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(String(500))
    #: Where clicking it goes. Stored, for the same reason as the title.
    link_url: Mapped[str | None] = mapped_column(String(200))

    #: Who it is ABOUT, as opposed to who it is addressed to.
    #:
    #: Not the same thing, and the public feed needs the former. A team goal
    #: being hit sends a row to every member — one event, many recipients — so
    #: a feed keyed on `user_id` would list the same achievement four times
    #: under four names, none of which is the achiever.
    #:
    #: Stored at emit like `title`, rather than resolved by joining back to the
    #: goal at read time. Same reasoning: renaming a team must not rewrite what
    #: last month's announcement said, and it keeps the public feed a single
    #: query with no branching per subject type.
    #:
    #: `about_user_id` is NULL for anything not about one person — a team goal —
    #: where `about_name` carries the team's name instead.
    about_name: Mapped[str | None] = mapped_column(String(120))
    about_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    #: Where the achiever sat WHEN THEY EARNED IT, so a wall can show its own
    #: office's wins without one floor's news scrolling past another's.
    #:
    #: Snapshots, exactly like `metric_fact.subject_team_id`. Joining to
    #: current membership instead would move last month's win to a different
    #: wall the moment somebody transferred, which is the same rewriting of
    #: history that snapshot exists to prevent.
    about_team_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("team.id", ondelete="SET NULL")
    )
    about_office_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("office.id", ondelete="SET NULL")
    )

    #: What plays on a wall screen when this is celebrated.
    #:
    #: Resolved at emit — the shout-out's override if there was one, otherwise
    #: the recipient's walk-up default — and stored here rather than looked up
    #: when it plays. Same rule as `title` and `about_name`: changing your
    #: walk-up song should soundtrack your *next* win, not retroactively
    #: re-score every one you have already had.
    media_url: Mapped[str | None] = mapped_column(String(500))
    media_start_seconds: Mapped[int | None] = mapped_column(Integer)
    media_end_seconds: Mapped[int | None] = mapped_column(Integer)

    #: NULL means the system detected it; set means a person wrote it.
    #:
    #: One column is the whole difference between an automated achievement and
    #: a manager's shout-out, which is why both ride the same table and reach
    #: the same surfaces without a second pipeline.
    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: When the celebration overlay showed this, distinct from `read_at`.
    #:
    #: Two different questions. "Have you seen it in the list" governs the
    #: badge; "have we already thrown confetti at you for this" governs the
    #: overlay, and conflating them breaks in both directions — opening the
    #: bell would cancel a celebration you never saw, and a celebration you
    #: walked away from would clear a badge you never looked at.
    #:
    #: Server-side rather than remembered in the browser, so refreshing the
    #: page or opening a second tab does not replay it.
    celebrated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: **Cleared from the bell** (12.1) — and only the bell. The same row is
    #: still the win on the Recognition page, the feed and the walls: clearing
    #: your bell is about your list, not about whether it happened. Never
    #: undone by anything but the Undo beside it; the event's own latch still
    #: decides when there is a *new* row about the same thing.
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: **Recorded, not announced** (7.2). A goal set already met is true — it
    #: belongs in the bell, the feed and the points — but it is not news: a
    #: wall announcing "goal hit" seconds after somebody typed a target reads
    #: as a glitch. Quiet rows never take over a wall, and are stored already
    #: celebrated so the in-app overlay passes them by too.
    quiet: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    #: **The number it was for, as it was said** (7.9): "$500". The hero of a
    #: takeover — the news is the figure, and it was the smallest text on the
    #: wall. Formatted when the win happened and kept, like `body`, so a
    #: currency change or a corrected fact does not rewrite last month's win.
    figure: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<Notification {self.event_key} user={self.user_id}>"
