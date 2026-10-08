"""The admin's inbox: what needs an admin right now, in one place (6.2).

Before this, each of these lived where it happened — a failing source on the
Integrations page, people waiting on the Users page's second tab, a dark TV on
TVs & Channels, a season ending nowhere at all — and an admin found them by
visiting each page in turn, or by being told by somebody on the floor.

**Worked out, not stored.** Like the setup checklist (`app/setup_steps.py`),
every item is a question about the data asked when the inbox is opened, so it
cannot say something is wrong after it has been fixed, and there is nothing to
mark as read: fixing it is how an item leaves. An admin may put one away for
now, until it changes or tomorrow (12.2) — `app/dismissals.py`. The counts it
shares with Home come from the same queries, so the two cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from app import dashboard, dismissals, pairing, seasons, staleness
from app.models.data_source import READ_ONCE
from app.models import (
    DataSource,
    DirectoryPerson,
    Display,
    DisplayPairing,
    Organization,
    SyncRun,
)

#: How close a season's end has to be before the inbox mentions it.
SEASON_WARNING_DAYS = 7

#: A TV created this recently and never seen is still being set up, not dark.
NEW_TV_GRACE = timedelta(hours=1)


@dataclass
class Action:
    """A button on the item that does the fix itself, where one press can."""

    label: str
    method: str
    path: str


@dataclass
class Item:
    #: Stable, for the client to key and test on. Never parsed for meaning.
    kind: str
    #: `problem`: something is broken. `todo`: something is waiting on an
    #: admin. `heads_up`: nothing is wrong yet.
    severity: str
    title: str
    detail: str | None
    link: str
    #: When it started, where that is known: last good run, last seen.
    since: datetime | None = None
    action: Action | None = None
    #: Which item this is across requests — "source_quiet:12" — for putting it
    #: away (12.2). `kind` alone would put every quiet source away at once.
    key: str = ""
    #: What it is about right now; a dismissal holds while this is unchanged.
    #: Not sent: the server works it out again when an item is dismissed.
    fingerprint: str = ""
    #: For an item that is a count: back only when it grows.
    count: int | None = None

    def mark(self) -> dismissals.Mark:
        return dismissals.Mark(key=self.key, fingerprint=self.fingerprint, count=self.count)


SEVERITY_ORDER = {"problem": 0, "todo": 1, "heads_up": 2}


@dataclass
class Inbox:
    items: list[Item] = field(default_factory=list)


def build(db: DbSession, org: Organization, *, now: datetime | None = None) -> Inbox:
    now = now or datetime.now(UTC)
    items = [
        *_failing_sources(db, org),
        *_overdue_sources(db, org, now),
        *_quiet_sources(db, org, now),
        *_disconnected_tvs(db, org, now),
        *_dark_tvs(db, org, now),
        *_directory_waiting(db, org),
        *_season_ending(db, org, now),
        *_hosting_change_undone(db),
    ]
    items.sort(key=lambda item: SEVERITY_ORDER[item.severity])
    return Inbox(items=items)


def _failing_sources(db: DbSession, org: Organization) -> list[Item]:
    rows = db.scalars(
        select(DataSource)
        .where(*dashboard._live_sources(org), DataSource.last_status == "failed")
        .order_by(DataSource.name)
    ).all()
    out = []
    for source in rows:
        error = db.scalar(
            select(SyncRun.error)
            .where(SyncRun.data_source_id == source.id, SyncRun.status == "failed")
            .order_by(SyncRun.started_at.desc())
            .limit(1)
        )
        out.append(
            Item(
                kind="source_failing",
                severity="problem",
                title=f"{source.name} is failing",
                # Its own words: an expired password reads differently from a
                # missing column, and the fix is in the sentence.
                detail=error or "Its last read failed.",
                link=f"/integrations/sources/{source.id}",
                since=source.last_run_at,
                key=f"source_failing:{source.id}",
                # The reason, not the run: failing again the same way every
                # fifteen minutes is not a change worth coming back for.
                fingerprint=(error or "")[:300],
            )
        )
    return out


def _overdue_sources(db: DbSession, org: Organization, now: datetime) -> list[Item]:
    rows = db.scalars(
        select(DataSource)
        .where(
            *dashboard._live_sources(org),
            DataSource.interval_minutes != READ_ONCE,
            DataSource.next_run_at.is_not(None),
            DataSource.next_run_at < now - dashboard.OVERDUE_GRACE,
            # A failing one is already in the inbox, with its reason.
            or_(DataSource.last_status.is_(None), DataSource.last_status != "failed"),
        )
        .order_by(DataSource.name)
    ).all()
    return [
        Item(
            kind="source_overdue",
            severity="problem",
            title=f"{source.name} has stopped reading",
            detail=(
                "It was due to read and has not. When several are late together, "
                "the scheduler is usually not running."
            ),
            link=f"/integrations/sources/{source.id}",
            since=source.last_run_at,
            key=f"source_overdue:{source.id}",
            fingerprint=_when(source.last_run_at),
        )
        for source in rows
    ]


def _quiet_sources(db: DbSession, org: Organization, now: datetime) -> list[Item]:
    """Sources reading cleanly with nothing new in them (7.3, Q2-5) — the
    commonest way a wall goes stale, and the one no error ever reports."""
    return [
        Item(
            kind="source_quiet",
            severity="problem",
            title=f"No new numbers from {staleness.name_of(quiet.source)} since {staleness.say_date(org, quiet.newest)}",
            detail=(
                f"It syncs cleanly, but nothing new has arrived in {quiet.working_days} "
                "working days. Has whatever feeds it stopped being updated?"
            ),
            link=f"/integrations/sources/{quiet.source.id}",
            since=quiet.newest,
            key=f"source_quiet:{quiet.source.id}",
            # A new newest row is the sync that changes it.
            fingerprint=_when(quiet.newest),
        )
        for quiet in staleness.quiet_sources(db, org, now)
    ]


def _disconnected_tvs(db: DbSession, org: Organization, now: datetime) -> list[Item]:
    """Revoked screens that are on and showing a pairing code (6.1), each
    with a one-press Reconnect."""
    rows = db.scalars(
        select(Display)
        .join(DisplayPairing, DisplayPairing.previous_display_id == Display.id)
        .where(
            Display.organization_id == org.id,
            Display.revoked_at.is_not(None),
            DisplayPairing.display_id.is_(None),
            DisplayPairing.created_at >= pairing.expired_before(now),
        )
        .distinct()
        .order_by(Display.name)
    ).all()
    return [
        Item(
            kind="tv_disconnected",
            severity="todo",
            title=f"{display.name} is showing a pairing code",
            detail=(
                "It was disconnected and is on, waiting. Reconnect it to the "
                "channel it had, or remove it from the list on TVs & Channels."
            ),
            link="/channels",
            since=display.revoked_at,
            key=f"tv_disconnected:{display.id}",
            fingerprint=_when(display.revoked_at),
            action=Action(
                label="Reconnect",
                method="POST",
                path=f"/api/displays/{display.id}/reconnect",
            ),
        )
        for display in rows
    ]


def _dark_tvs(db: DbSession, org: Organization, now: datetime) -> list[Item]:
    """Connected screens that have stopped checking in."""
    cutoff = now - timedelta(hours=dashboard.DISPLAY_OFFLINE_HOURS)
    rows = db.scalars(
        select(Display)
        .where(
            Display.organization_id == org.id,
            Display.revoked_at.is_(None),
            or_(
                Display.last_seen_at < cutoff,
                # Never seen, and not just made: a link nobody opened.
                (Display.last_seen_at.is_(None)) & (Display.created_at < now - NEW_TV_GRACE),
            ),
        )
        .order_by(Display.name)
    ).all()
    return [
        Item(
            kind="tv_offline",
            severity="heads_up",
            title=(
                f"{display.name} has stopped checking in"
                if display.last_seen_at
                else f"{display.name} has never been opened"
            ),
            detail=(
                "Switched off, or off the network. Nothing is wrong if the room "
                "is closed."
                if display.last_seen_at
                else "Its link was made but no screen has loaded it yet."
            ),
            link="/channels",
            since=display.last_seen_at or display.created_at,
            key=f"tv_offline:{display.id}",
            # Seen again and gone dark again is a new story.
            fingerprint=_when(display.last_seen_at),
        )
        for display in rows
    ]


def _directory_waiting(db: DbSession, org: Organization) -> list[Item]:
    count = int(
        db.scalar(
            select(func.count())
            .select_from(DirectoryPerson)
            .where(
                DirectoryPerson.organization_id == org.id,
                DirectoryPerson.status == "pending",
            )
        )
        or 0
    )
    if not count:
        return []
    return [
        Item(
            kind="directory_waiting",
            severity="todo",
            title=(
                f"{count} {'person' if count == 1 else 'people'} from your directory "
                f"{'is' if count == 1 else 'are'} waiting to be placed"
            ),
            detail="Approve them, with the role and team the rules suggest, or decline.",
            link="/users?tab=directory",
            key="directory_waiting",
            count=count,
        )
    ]


def _season_ending(db: DbSession, org: Organization, now: datetime) -> list[Item]:
    season = seasons.current(db, org, now=now)
    if season is None or season.closed_at is not None:
        return []
    today = seasons._today(org, now)
    left = (season.ends_on - today).days
    if left > SEASON_WARNING_DAYS:
        return []
    following = seasons.upcoming(db, org, now=now)
    when = "today" if left == 0 else "tomorrow" if left == 1 else f"in {left} days"
    return [
        Item(
            kind="season_ending",
            severity="heads_up",
            title=f"{season.name} ends {when}",
            detail=(
                f"Points reset when it does. {following.name} is set up to follow."
                if following
                else "Points reset when it does, and the next quarter opens as its "
                "own season with the first award. Rename or reshape it under "
                "Points setup."
            ),
            link="/points/setup",
            key=f"season_ending:{season.id}",
        )
    ]


def _hosting_change_undone(db: DbSession) -> list[Item]:
    """A hosting change nobody kept, undone by itself (P7-5): the admin who
    walked away should find out why it's gone. Until the next change."""
    from app import hosting_config

    current = hosting_config.current(db, sync_first=False)
    if current.trial_expired_at is None:
        return []
    tried = current.undo_to.host if current.undo_to and current.undo_to.https_on else "plain HTTP"
    back = current.host if current.https_on else "plain HTTP"
    return [
        Item(
            kind="hosting_change_undone",
            severity="heads_up",
            title=f"The change to {tried} wasn't kept, so it was undone",
            detail=f"GoalGetter is back on {back}. Try it again under Settings → Hosting → Change.",
            link="/settings?tab=hosting",
            since=current.trial_expired_at,
            key="hosting_change_undone",
            fingerprint=_when(current.trial_expired_at),
        )
    ]


def _when(at: datetime | None) -> str:
    return at.isoformat() if at else ""
