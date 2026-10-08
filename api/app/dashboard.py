"""What each role needs to see first.

Three different questions wearing one page:

    agent    "how am I doing, and where do I stand?"
    manager  "who on my team needs me today?"
    admin    "is this thing working?"

The first two are motivation, the third is operations. Mixing them produces a
page that answers none of them — an agent does not care that a metric has no
data, and an admin looking for a broken sync does not want to scroll past their
own call count to find it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from app import aggregate, periods
from app import leaderboards as board_service
from app.pace import CUMULATIVE
from app.models import (
    DataSource,
    SyncRun,
    Display,
    Goal,
    Leaderboard,
    MetricDefinition,
    MetricFact,
    Organization,
    Team,
    UserAccount,
)
from app.models.data_source import READ_ONCE
from app.scope import EVERYONE, visible_user_ids

# How long without a recorded fact before a person counts as quiet.
#
# Seven days rather than a shorter window on purpose: a leaderboard that
# flagged everyone who took a Friday off would be crying wolf, and the warning
# people ignore is worse than no warning.
QUIET_DAYS = 7

# A display that has not polled in this long is probably a screen someone
# unplugged. It polls every minute, so an hour is already ~60 missed attempts.
DISPLAY_OFFLINE_HOURS = 2


@dataclass
class Placement:
    """Where the viewer stands on one board they can see."""

    board_id: int
    board_name: str
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None
    period_label: str
    rank: int
    total_entrants: int
    value: Decimal
    movement: int | None
    #: The viewer's own line over the board's period. Not the leader's and not
    #: the board's total — the question a placement answers is "how am I
    #: doing", so the shape beside it has to be theirs.
    trend: list[aggregate.Point] = field(default_factory=list)
    trend_unit: str = "day"
    trend_cumulative: bool = False


@dataclass
class Attention:
    """One thing worth doing something about.

    `kind` is a stable identifier the client styles and links from; `message`
    is the sentence. Keeping them apart means the wording can change without
    breaking a lookup, and the client never parses prose to decide what to do.
    """

    kind: str
    message: str
    count: int
    link: str
    #: What it is about, for putting it away until that changes (12.2). Empty
    #: for a plain count, which comes back only when it grows.
    fingerprint: str = ""

    def mark(self):
        from app import dismissals

        return dismissals.Mark(
            key=self.kind,
            fingerprint=self.fingerprint,
            count=None if self.fingerprint else self.count,
        )


@dataclass
class Health:
    """Whether the data underneath everything else is actually arriving."""

    last_fact_at: datetime | None
    facts_last_7_days: int
    active_people: int
    people_without_a_team: int
    metrics_without_data: int
    displays_offline: int

    #: Sources whose last run failed outright.
    #:
    #: **Not covered by `metrics_without_data`**, which was the closest thing here
    #: before and is not the same question: a metric fed by two sources still has
    #: recent data when one of them has been failing for a week. A broken sync is
    #: invisible on a leaderboard — it looks exactly like a quiet week.
    sources_failing: int = 0
    #: Sources that should have run by now and have not.
    #:
    #: A separate count from failing, because the fixes differ: a failing source
    #: has an error to read, and an overdue one usually means the scheduler is not
    #: running at all — which no per-source error would ever say.
    sources_overdue: int = 0
    #: One source's own words, so the card can say *what* broke rather than only
    #: that something did. The most recently failed, since that is the one somebody
    #: is most likely to be asking about.
    source_error: str | None = None
    #: Each source and its newest row (P3-3): "Excel — no new rows since Thu
    #: 3 Sep", "Snowflake — read once, newest row Wed 23 Sep". One date with
    #: no source beside it was the third version of the stale-data story.
    sources: list[dict] = field(default_factory=list)


#: How far past its due time a source has to be before it counts as overdue.
#:
#: One interval of slack: a source checked hourly is not a problem at sixty-one
#: minutes, because the job pass that would have run it is itself hourly. Without
#: the grace period this would flicker for every source on every tick, which is a
#: number an admin learns to ignore.
OVERDUE_GRACE = timedelta(minutes=90)


@dataclass
class Summary:
    placements: list[Placement] = field(default_factory=list)
    attention: list[Attention] = field(default_factory=list)
    health: Health | None = None


def placements(db: DbSession, org: Organization, actor: UserAccount) -> list[Placement]:
    """The viewer's own position on every board they can open.

    Run through the same board service the leaderboard pages use, so a rank
    here and a rank there cannot disagree. Boards where the viewer does not
    appear are skipped rather than shown as "unranked" — a row saying you are
    nowhere is discouraging and tells you nothing you can act on.
    """
    boards = db.scalars(
        select(Leaderboard).where(
            Leaderboard.organization_id == org.id,
            Leaderboard.archived_at.is_(None),
        )
    ).all()

    found: list[Placement] = []
    for board in boards:
        if not board_service.can_view(db, actor, board):
            continue

        result = board_service.run(db, org, actor, board, apply_limit=False)
        # `viewer_entry` is only populated when the viewer falls outside the
        # limit, so the unlimited run plus a direct search covers both cases.
        viewer_id = (
            actor.team_id if board.entity_type == "team" else actor.id
        )
        if board.entity_type == "office":
            team = db.get(Team, actor.team_id) if actor.team_id else None
            viewer_id = team.office_id if team else None

        entry = next((e for e in result.entries if e.entity_id == viewer_id), None)
        if entry is None:
            continue

        metric = db.get(MetricDefinition, board.metric_definition_id)

        # **Nothing yet is not a place.** A source that writes a row for
        # everybody it lists puts people on a board at zero, and Home ranked an
        # admin who never sells "39th of 137 · $0.00" — the same nowhere this
        # card already declines to show, with a number attached (review §3).
        if entry.value == 0 and metric.direction == "higher_is_better":
            continue

        # The viewer's own line, filtered by whichever thing the board ranks.
        # `visible=EVERYONE` is safe and necessary here for exactly the reason
        # it is on the board itself: the entry above proves they are entitled
        # to this number, and an agent's default scope is only themselves — so
        # a team or office board would otherwise plot a line covering less than
        # the rank printed beside it.
        subject = {
            "user": {"subject_user_id": viewer_id},
            "team": {"team_id": viewer_id},
            "office": {"office_id": viewer_id},
        }[board.entity_type]
        points = aggregate.series(
            db, org, actor, metric, result.period, visible=EVERYONE, **subject
        )
        cumulative = metric.aggregation in CUMULATIVE

        found.append(
            Placement(
                board_id=board.id,
                board_name=board.name,
                metric_name=metric.name,
                unit=metric.unit,
                decimal_places=metric.decimal_places,
                unit_label=metric.unit_label,
                period_label=result.period.label,
                rank=entry.rank,
                total_entrants=result.total_entrants,
                value=entry.value,
                movement=entry.movement,
                trend=aggregate.running_total(points) if cumulative else points,
                trend_unit=periods.bucket_unit(result.period),
                trend_cumulative=cumulative,
            )
        )

    # Best position first: the one worth showing at the top of a dashboard is
    # the one they are doing well on.
    found.sort(key=lambda p: p.rank)
    return found


def quiet_people(db: DbSession, actor: UserAccount) -> int:
    """Active people with nothing recorded recently, within the actor's scope.

    The most useful early warning a manager gets. Someone with no data for a
    week is either on leave, missing from a sync, or has stopped — and all
    three are worth knowing before the month closes.
    """
    since = datetime.now(UTC) - timedelta(days=QUIET_DAYS)

    recent = select(MetricFact.subject_user_id).where(
        MetricFact.organization_id == actor.organization_id,
        MetricFact.occurred_at >= since,
    )

    query = select(func.count()).select_from(UserAccount).where(
        UserAccount.organization_id == actor.organization_id,
        UserAccount.hidden_at.is_(None),
        UserAccount.status == "active",
        UserAccount.org_role == "agent",
        UserAccount.id.not_in(recent),
    )

    visible = visible_user_ids(db, actor)
    if visible is not EVERYONE:
        query = query.where(UserAccount.id.in_(visible))
    # **A manager's own team** (7.1): their scope also takes in every agent on
    # no team, which made the banner say 413 to a manager of 93.
    if actor.org_role == "manager" and actor.team_id is not None:
        query = query.where(UserAccount.team_id == actor.team_id)

    return int(db.scalar(query) or 0)


def _goals_needing_attention(db: DbSession, org: Organization, actor: UserAccount) -> int:
    """Goals behind pace or already missed, within scope.

    Computed rather than queried: "behind" depends on today's date against a
    period resolved in the organization's timezone, which is not a column.
    """
    from app import goals as goal_service
    from app import pace as pace_service

    query = select(Goal).where(
        Goal.organization_id == org.id, Goal.archived_at.is_(None)
    )

    visible = visible_user_ids(db, actor)
    if visible is not EVERYONE:
        team_ids = db.scalars(
            select(UserAccount.team_id).where(
                UserAccount.id.in_(visible), UserAccount.team_id.is_not(None)
            )
        ).all()
        query = query.where(
            or_(
                Goal.subject_user_id.in_(visible),
                Goal.subject_team_id.in_(set(team_ids)) if team_ids else False,
            )
        )

    count = 0
    for goal in db.scalars(query).all():
        metric = db.get(MetricDefinition, goal.metric_definition_id)
        period = goal_service.resolve_period(org, goal)
        current, has_data = goal_service.current_value(db, org, actor, goal, metric)
        progress = goal_service.progress(
            current, goal.target_value, metric.direction, has_data=has_data
        )
        result = pace_service.compute(
            period=period,
            now=datetime.now(UTC),
            timezone=org.timezone,
            aggregation=metric.aggregation,
            percent=progress.percent,
            attained=progress.attained,
            current=progress.current,
        )
        if result.needs_attention:
            count += 1
    return count


def attention(db: DbSession, org: Organization, actor: UserAccount) -> list[Attention]:
    """Things worth doing something about, ordered by who can act on them."""
    items: list[Attention] = []

    behind = _goals_needing_attention(db, org, actor)
    if behind:
        items.append(
            Attention(
                kind="goals_behind",
                message=f"{behind} {'goal is' if behind == 1 else 'goals are'} behind pace",
                count=behind,
                link="/goals",
            )
        )

    if actor.org_role in ("admin", "manager"):
        # **The data first, when it is the data** (7.3, Q2-5). Most of a
        # floor going quiet together is a feed that stopped — say which, and
        # when — rather than "400 people have recorded nothing".
        from app import staleness

        stopped = staleness.quiet_sources(db, org, datetime.now(UTC))
        quiet = quiet_people(db, actor)
        if stopped:
            newest = max(q.newest for q in stopped)
            names = ", ".join(staleness.name_of(q.source) for q in stopped[:2])
            if len(stopped) > 2:
                names += f" and {len(stopped) - 2} more"
            items.append(
                Attention(
                    kind="data_stale",
                    message=(
                        f"No new numbers since {staleness.say_date(org, newest)} · {names}"
                        + (" · Check it" if actor.org_role == "admin" else "")
                    ),
                    count=len(stopped),
                    # Which feeds, and their newest rows: a new row, or another
                    # feed going quiet, is the sync that brings it back.
                    fingerprint=";".join(
                        f"{q.source.id}@{q.newest.isoformat()}"
                        for q in sorted(stopped, key=lambda q: q.source.id)
                    )[:300],
                    # Nowhere to send a manager: the fix is an admin's, and it
                    # is in the admin's Inbox.
                    link=(
                        f"/integrations/sources/{stopped[0].source.id}"
                        if actor.org_role == "admin" and len(stopped) == 1
                        else "/integrations" if actor.org_role == "admin" else ""
                    ),
                )
            )
        elif quiet:
            items.append(
                Attention(
                    kind="quiet_people",
                    message=(
                        f"{quiet} {'person has' if quiet == 1 else 'people have'} "
                        f"recorded nothing in {QUIET_DAYS} days"
                    ),
                    count=quiet,
                    link="/users",
                )
            )

    if actor.org_role == "admin":
        unassigned = int(
            db.scalar(
                select(func.count())
                .select_from(UserAccount)
                .where(
                    UserAccount.organization_id == org.id,
                    UserAccount.hidden_at.is_(None),
                    UserAccount.org_role == "agent",
                    UserAccount.team_id.is_(None),
                )
            )
            or 0
        )
        if unassigned:
            items.append(
                Attention(
                    kind="unassigned_agents",
                    message=(
                        f"{unassigned} {'agent is' if unassigned == 1 else 'agents are'} "
                        "on no team, so they are missing from every team board"
                    ),
                    count=unassigned,
                    # Straight to the list it is counting, not to everybody.
                    link="/users?team=none&role=agent",
                )
            )

    return items


def _live_sources(org: Organization):
    """Sources that are actually running.

    Drafts and removed sources are excluded for the same reason they are excluded
    from the sources list: a connect flow nobody finished has nothing to report, and
    reporting it as broken turns an abandoned click into an alarm.
    """
    return (
        DataSource.organization_id == org.id,
        DataSource.archived_at.is_(None),
        DataSource.activated_at.is_not(None),
    )


def _failing_sources(db: DbSession, org: Organization) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(DataSource)
            .where(*_live_sources(org), DataSource.last_status == "failed")
        )
        or 0
    )


def _overdue_sources(db: DbSession, org: Organization, *, now: datetime) -> int:
    """Sources whose next run was due and has not happened.

    A source that has *never* run is not overdue — it has just been switched on,
    and the first pass is minutes away. Only one that was scheduled and missed
    counts, which is what makes this mean "the scheduler is not running".
    """
    return int(
        db.scalar(
            select(func.count())
            .select_from(DataSource)
            .where(
                *_live_sources(org),
                # A one-off has no schedule to miss. Its next run is cleared
                # once it has read, and this says so too, for any written
                # before that was true.
                DataSource.interval_minutes != READ_ONCE,
                DataSource.next_run_at.is_not(None),
                DataSource.next_run_at < now - OVERDUE_GRACE,
            )
        )
        or 0
    )


def _worst_source_error(db: DbSession, org: Organization) -> str | None:
    """The most recent failure's own words.

    One error rather than all of them: three sources broken by the same expired
    credential produce three copies of one sentence, and a card is not the place to
    read a list. The Integrations page has the list.
    """
    return db.scalar(
        select(SyncRun.error)
        .join(DataSource, DataSource.id == SyncRun.data_source_id)
        .where(
            *_live_sources(org),
            SyncRun.status == "failed",
            SyncRun.error.is_not(None),
        )
        .order_by(SyncRun.started_at.desc())
        .limit(1)
    )


def _source_newness(db: DbSession, org: Organization) -> list[dict]:
    """Every source in use, with its newest row and whether it has gone quiet."""
    from app import staleness
    from app.models import DataSource

    now = datetime.now(UTC)
    out = []
    for source in db.scalars(
        select(DataSource)
        .where(
            DataSource.organization_id == org.id,
            DataSource.archived_at.is_(None),
            DataSource.activated_at.is_not(None),
        )
        .order_by(DataSource.name)
    ).all():
        newest = staleness.newest_row(db, source.id)
        days = staleness.quiet_days(org, newest, now)
        out.append(
            {
                "name": staleness.name_of(source),
                "newest": staleness.say_date(org, newest) if newest else None,
                "read_once": source.interval_minutes == staleness.READ_ONCE,
                "quiet": staleness.is_watched(source)
                and days is not None
                and days >= staleness.STALE_WORKING_DAYS,
            }
        )
    return out


def health(db: DbSession, org: Organization) -> Health:
    """Is data still arriving?

    The question this exists for is the one from the integrations doc: a
    leaderboard showing three-day-old figures because a sync has been failing
    looks exactly like a leaderboard showing current ones. Silently stale data
    is the fastest way to lose trust in the tool, so the staleness has to be
    visible somewhere a person actually looks.
    """
    since = datetime.now(UTC) - timedelta(days=7)

    metrics_with_data = select(MetricFact.metric_definition_id).where(
        MetricFact.organization_id == org.id
    )

    return Health(
        sources=_source_newness(db, org),
        last_fact_at=db.scalar(
            select(func.max(MetricFact.occurred_at)).where(
                MetricFact.organization_id == org.id
            )
        ),
        facts_last_7_days=int(
            db.scalar(
                select(func.count())
                .select_from(MetricFact)
                .where(
                    MetricFact.organization_id == org.id,
                    MetricFact.occurred_at >= since,
                )
            )
            or 0
        ),
        active_people=int(
            db.scalar(
                select(func.count())
                .select_from(UserAccount)
                .where(
                    UserAccount.organization_id == org.id,
                    UserAccount.hidden_at.is_(None),
                    UserAccount.status == "active",
                )
            )
            or 0
        ),
        people_without_a_team=int(
            db.scalar(
                select(func.count())
                .select_from(UserAccount)
                .where(
                    UserAccount.organization_id == org.id,
                    UserAccount.hidden_at.is_(None),
                    UserAccount.org_role == "agent",
                    UserAccount.team_id.is_(None),
                )
            )
            or 0
        ),
        metrics_without_data=int(
            db.scalar(
                select(func.count())
                .select_from(MetricDefinition)
                .where(
                    MetricDefinition.organization_id == org.id,
                    MetricDefinition.archived_at.is_(None),
                    MetricDefinition.id.not_in(metrics_with_data),
                )
            )
            or 0
        ),
        sources_failing=_failing_sources(db, org),
        sources_overdue=_overdue_sources(db, org, now=datetime.now(UTC)),
        source_error=_worst_source_error(db, org),
        displays_offline=int(
            db.scalar(
                select(func.count())
                .select_from(Display)
                .where(
                    Display.organization_id == org.id,
                    Display.revoked_at.is_(None),
                    or_(
                        Display.last_seen_at.is_(None),
                        Display.last_seen_at
                        < datetime.now(UTC) - timedelta(hours=DISPLAY_OFFLINE_HOURS),
                    ),
                )
            )
            or 0
        ),
    )


def build(db: DbSession, org: Organization, actor: UserAccount) -> Summary:
    return Summary(
        placements=placements(db, org, actor),
        attention=attention(db, org, actor),
        # Operations, not motivation. An agent has no use for it and no way to
        # act on it.
        health=health(db, org) if actor.org_role == "admin" else None,
    )
