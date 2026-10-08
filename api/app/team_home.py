"""A manager's own team, on their home page (6.13).

The home page answered "where do I stand?" for everybody, and a manager's job
is a different question: how is my team doing, and who should I talk to
today. This answers it in one request:

  * **The team, ranked** on one metric for the period — the team's busiest
    unless they choose another — with each person's goal beside their number,
    so a manager sees the board and the targets in the same glance.
  * **Who needs a nudge**: behind pace on a goal, or nothing recorded for a
    week. Each with the reason in words, because "Ann" in a list says
    nothing about what to say to her.
  * **Who is worth a word**: hit their goal, or top of the team. Recognition
    is easiest when the screen has already noticed.

Scoped to the manager's own team — the one they set goals for — and to an
admin who sits on a team, who has the same question about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import aggregate, goals as goal_service, pace as pace_service, periods
from app.dashboard import QUIET_DAYS
from app.models import Goal, MetricDefinition, MetricFact, Organization, Team, UserAccount

#: How far back "the team's busiest metric" looks.
BUSY_DAYS = 90

#: The periods the card can show. A year is too slow to manage day to day.
TEAM_PERIODS = ("day", "week", "month", "quarter")

WORKING = ("active", "invited")


@dataclass
class TeamGoal:
    goal_id: int
    target: Decimal
    percent: float
    expected_percent: float | None
    status: str


@dataclass
class Member:
    user_id: int
    name: str
    photo_digest: str | None
    value: Decimal
    rank: int
    goal: TeamGoal | None = None
    #: Days since anything was recorded for them, on any metric. None when
    #: nothing ever has been.
    quiet_days: int | None = None
    is_me: bool = False


@dataclass
class Note:
    """Somebody worth a word, and why — as figures rather than a sentence, so
    the page writes them the way it writes every other number.

    `behind` and `missed` carry the value and target (and, while behind, the
    expected figure by now); `quiet` the days, None for never; `hit` and
    `leading` the value. `team_quiet` is the whole team at once — `value` is
    how many, `days` the usual gap — and names the team rather than a person."""

    user_id: int
    name: str
    kind: str
    value: Decimal | None = None
    target: Decimal | None = None
    expected: Decimal | None = None
    days: int | None = None


@dataclass
class TeamHome:
    team_id: int
    team_name: str
    metrics: list[dict] = field(default_factory=list)
    metric_id: int | None = None
    metric_name: str = ""
    unit: str = "count"
    decimal_places: int = 0
    unit_label: str | None = None
    direction: str = "higher_is_better"
    period_type: str = "month"
    period_label: str = ""
    members: list[Member] = field(default_factory=list)
    nudges: list[Note] = field(default_factory=list)
    shout_outs: list[Note] = field(default_factory=list)


def team_of(db: DbSession, actor: UserAccount) -> Team | None:
    """The team this person manages from their home page, if any."""
    if actor.org_role not in ("manager", "admin") or actor.team_id is None:
        return None
    team = db.get(Team, actor.team_id)
    return team if team is not None and team.archived_at is None else None


def build(
    db: DbSession,
    org: Organization,
    actor: UserAccount,
    team: Team,
    *,
    metric_id: int | None = None,
    period_type: str = "month",
    now: datetime | None = None,
    previous: bool = False,
) -> TeamHome:
    now = now or datetime.now(UTC)
    people = list(
        db.scalars(
            select(UserAccount)
            .where(
                UserAccount.organization_id == org.id,
                UserAccount.team_id == team.id,
                UserAccount.hidden_at.is_(None),
                UserAccount.status.in_(WORKING),
            )
            .order_by(UserAccount.full_name)
        ).all()
    )
    ids = [p.id for p in people]
    home = TeamHome(team_id=team.id, team_name=team.name, period_type=period_type)

    home.metrics = _metrics(db, org, ids, now)
    chosen = next((m for m in home.metrics if m["id"] == metric_id), None) or (
        home.metrics[0] if home.metrics else None
    )
    last_seen = _last_seen(db, org, ids)

    metric = db.get(MetricDefinition, chosen["id"]) if chosen else None
    if metric is None:
        home.members = [
            Member(
                user_id=p.id, name=p.full_name, photo_digest=p.photo_digest,
                value=Decimal(0), rank=0, quiet_days=_days(last_seen.get(p.id), now),
                is_me=p.id == actor.id,
            )
            for p in people
        ]
        home.nudges = _quiet_nudges(home.members, actor)
        return home

    home.metric_id = metric.id
    home.metric_name = metric.name
    home.unit = metric.unit
    home.decimal_places = metric.decimal_places
    home.unit_label = metric.unit_label
    home.direction = metric.direction

    period = periods.resolve(org, period_type, periods.today(org))
    # The one before, for a card whose current period has nothing in it yet
    # (8.2): "No numbers for October yet — show September".
    if previous:
        period = periods.previous(org, period)
    home.period_label = period.label
    values = {
        row.subject_id: row.value
        for row in aggregate.run(db, org.id, actor, metric, period, group_by="user")
        if row.subject_id in set(ids)
    }

    # Ranked within the team, the way the metric reads: lower first for a
    # metric where lower is better. Ties share a rank, as on every board.
    order = sorted(
        people,
        key=lambda p: (
            values.get(p.id, Decimal(0)) if metric.direction == "lower_is_better"
            else -values.get(p.id, Decimal(0)),
            p.full_name,
        ),
    )
    goals = _goals(db, org, metric, period_type, period, ids)
    members: list[Member] = []
    previous: Decimal | None = None
    rank = 0
    for position, person in enumerate(order, start=1):
        value = values.get(person.id, Decimal(0))
        if value != previous:
            rank = position
            previous = value
        members.append(
            Member(
                user_id=person.id,
                name=person.full_name,
                photo_digest=person.photo_digest,
                value=value,
                rank=rank,
                goal=_progress(db, org, actor, metric, goals.get(person.id), now),
                quiet_days=_days(last_seen.get(person.id), now),
                is_me=person.id == actor.id,
            )
        )
    # **Nobody has anything yet**: no ranks at all, rather than everybody
    # "1st" on a board of zeros.
    if all(member.value == 0 for member in members):
        for member in members:
            member.rank = 0
    home.members = members

    nudges: list[Note] = []
    shouts: list[Note] = []
    for member in members:
        if member.is_me:
            continue
        goal = member.goal
        if goal and goal.status in (pace_service.BEHIND, pace_service.MISSED):
            behind = goal.status == pace_service.BEHIND
            nudges.append(
                Note(
                    member.user_id, member.name, "behind" if behind else "missed",
                    value=member.value,
                    target=goal.target,
                    expected=(
                        (goal.target * Decimal(str(goal.expected_percent)) / 100)
                        if behind and goal.expected_percent is not None
                        else None
                    ),
                )
            )
        elif goal and goal.status == pace_service.HIT:
            shouts.append(Note(member.user_id, member.name, "hit", value=member.value))
    # Quiet comes after behind: a person behind pace is the more specific
    # thing to say, and the same person is not listed twice.
    named = {n.user_id for n in nudges}
    nudges += [n for n in _quiet_nudges(members, actor) if n.user_id not in named]

    leader = members[0] if members else None
    if (
        leader is not None
        and not leader.is_me
        and leader.value > 0
        and leader.user_id not in {s.user_id for s in shouts}
        and (len(members) < 2 or members[1].value != leader.value)
    ):
        shouts.append(Note(leader.user_id, leader.name, "leading", value=leader.value))
    home.nudges = nudges
    home.shout_outs = shouts
    return home


def _metrics(db: DbSession, org: Organization, ids: list[int], now: datetime) -> list[dict]:
    """Metrics the team has recorded lately, busiest first — then the rest of
    the organization's, so a new team can still choose one."""
    busy: dict[int, int] = {}
    if ids:
        busy = dict(
            db.execute(
                select(MetricFact.metric_definition_id, func.count())
                .where(
                    MetricFact.organization_id == org.id,
                    MetricFact.subject_user_id.in_(ids),
                    MetricFact.occurred_at >= now - timedelta(days=BUSY_DAYS),
                )
                .group_by(MetricFact.metric_definition_id)
            ).all()
        )
    metrics = db.scalars(
        select(MetricDefinition).where(
            MetricDefinition.organization_id == org.id,
            MetricDefinition.archived_at.is_(None),
        )
    ).all()
    ordered = sorted(metrics, key=lambda m: (-busy.get(m.id, 0), m.name.lower()))
    return [{"id": m.id, "name": m.name, "recorded": busy.get(m.id, 0)} for m in ordered]


def _last_seen(db: DbSession, org: Organization, ids: list[int]) -> dict[int, datetime]:
    if not ids:
        return {}
    return dict(
        db.execute(
            select(MetricFact.subject_user_id, func.max(MetricFact.occurred_at))
            .where(MetricFact.organization_id == org.id, MetricFact.subject_user_id.in_(ids))
            .group_by(MetricFact.subject_user_id)
        ).all()
    )


def _days(seen: datetime | None, now: datetime) -> int | None:
    if seen is None:
        return None
    if seen.tzinfo is None:
        seen = seen.replace(tzinfo=UTC)
    return max(0, (now - seen).days)


def _goals(db, org, metric, period_type, period, ids) -> dict[int, Goal]:
    """Each person's live goal for this metric over this period."""
    if not ids:
        return {}
    anchor = period.start.astimezone(periods.tz(org)).date()
    rows = db.scalars(
        select(Goal)
        .where(
            Goal.organization_id == org.id,
            Goal.metric_definition_id == metric.id,
            Goal.subject_type == "user",
            Goal.subject_user_id.in_(ids),
            Goal.period_type == period_type,
            Goal.period_anchor == anchor,
            Goal.archived_at.is_(None),
        )
        .order_by(Goal.id)
    ).all()
    return {goal.subject_user_id: goal for goal in rows}


def _progress(db, org, actor, metric, goal: Goal | None, now: datetime) -> TeamGoal | None:
    if goal is None:
        return None
    current, has_data = goal_service.current_value(db, org, actor, goal, metric)
    progress = goal_service.progress(current, goal.target_value, metric.direction, has_data=has_data)
    pace = pace_service.compute(
        period=goal_service.resolve_period(org, goal),
        now=now,
        timezone=org.timezone,
        aggregation=metric.aggregation,
        percent=progress.percent,
        attained=progress.attained,
        current=progress.current,
    )
    return TeamGoal(
        goal_id=goal.id,
        target=goal.target_value,
        percent=progress.percent,
        expected_percent=pace.expected_percent,
        status=pace.status,
    )


#: When this share of the team has gone quiet at once, it is the data that
#: stopped, not the people.
QUIET_SHARE = 0.5


def _quiet_nudges(members: list[Member], actor: UserAccount) -> list[Note]:
    """Who has recorded nothing for a week.

    **Most of the team at once is one note, not ninety.** Nobody's floor goes
    silent together; a sync does. Listing everybody would bury the people who
    really are quiet under a problem with the data feed, so the note says that
    instead — and names nobody, because nobody did anything wrong.
    """
    others = [m for m in members if not m.is_me]
    quiet = [
        m for m in others if m.quiet_days is None or m.quiet_days >= QUIET_DAYS
    ]
    if len(quiet) >= 3 and len(quiet) > len(others) * QUIET_SHARE:
        gaps = sorted(m.quiet_days for m in quiet if m.quiet_days is not None)
        return [
            Note(
                0, "", "team_quiet",
                value=Decimal(len(quiet)),
                days=gaps[0] if gaps else None,
            )
        ]
    return [Note(m.user_id, m.name, "quiet", days=m.quiet_days) for m in quiet]

