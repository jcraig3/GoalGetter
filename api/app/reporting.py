"""What a manager should do something about, said as a number they can act on.

**Almost none of this is new maths.** `pace.py` already knows whether a goal is
behind, `goals.py` already knows what it has reached, and `dashboard.py`
already knows whether the data underneath is arriving. What was missing is the
sentence at the end of it: *behind* is a colour, and "needs eighteen a day from
here" is a conversation.

The distinction this module exists for:

    a progress bar    where somebody is
    a pace marker     where somebody should be
    a coaching gap    what closing it would take

Only the third is something a manager can hand to a person, and it is the only
one of the three nothing computed before.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import aggregate, competitions as competition_service
from app import goals as goal_service, pace as pace_service, periods, scope
from app.models import (
    Competition,
    CompetitionParticipant,
    Goal,
    MetricDefinition,
    Organization,
    Team,
    UserAccount,
)
from app.scope import can_see_user

__all__ = [
    "CompetitionReport",
    "Gap",
    "Overview",
    "Record",
    "Run",
    "Season",
    "competition_report",
    "overview",
    "records",
]


@dataclass
class Gap:
    """One goal that is behind, and what catching up would take."""

    goal_id: int
    goal_name: str
    subject_name: str
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None

    current: Decimal
    target: Decimal
    #: How far off the pace, in percentage points. The number that decides the
    #: order, because a goal three points behind on the second of the month is
    #: noise and thirty points behind on the twenty-fifth is not.
    behind_by: float

    #: Working days left in the period, counting today.
    days_left: int
    #: What they have averaged per working day so far.
    rate_so_far: Decimal | None
    #: What they need per working day from here. None when the period is over,
    #: or when the metric does not accumulate and a rate means nothing.
    rate_needed: Decimal | None


@dataclass
class Overview:
    """Everything the reporting page opens with."""

    #: Goals considered — the ones this person can see, in periods that are
    #: currently running.
    total: int = 0
    on_pace: int = 0
    behind: int = 0
    hit: int = 0
    #: Nothing recorded yet, with too little of the period gone to call it
    #: behind (Q2-10). Neither on pace nor a worry — yet.
    not_started: int = 0
    gaps: list[Gap] = field(default_factory=list)

    @property
    def on_pace_percent(self) -> float | None:
        """**Hit counts as on pace.** A finished goal is not a worry, and a
        page that showed 60% while a third of the goals were already met would
        be reporting on its own arithmetic rather than on the team.

        **Goals with nothing yet are left out** (Q2-10): a working day into the
        month, every goal at $0 headlined "On pace 100%". None when nothing has
        started — too early to tell."""
        if self.total == 0:
            return 0.0
        judged = self.total - self.not_started
        if judged <= 0:
            return None
        return round((self.on_pace + self.hit) / judged * 100, 1)


#: How many coaching gaps to name.
#:
#: **A list somebody reads, not a report they scroll.** Eight is a stand-up;
#: forty is a spreadsheet, and a page that shows forty teaches people to close
#: it. They are ordered worst-first, so the eight are the eight that matter.
MAX_GAPS = 8


def overview(
    db: DbSession, org: Organization, actor: UserAccount, *, now: datetime | None = None
) -> Overview:
    """Where every goal this person can see currently stands.

    Scoped like everything else: an admin sees the organization, a manager
    sees their team. A goal nobody can see is not counted rather than counted
    anonymously — a denominator including goals you cannot open is a percentage
    you cannot check.
    """
    now = now or datetime.now(UTC)
    today = now.astimezone(periods.tz(org)).date()

    out = Overview()
    rows = db.scalars(
        select(Goal).where(
            Goal.organization_id == org.id, Goal.archived_at.is_(None)
        )
    ).all()

    for goal in rows:
        if not _may_see(db, actor, goal):
            continue

        metric = db.get(MetricDefinition, goal.metric_definition_id)
        if metric is None:
            continue

        period = goal_service.resolve_period(org, goal)
        # A goal whose period has not started is not yet anybody's problem, and
        # one whose period is over belongs to history rather than to a page
        # about what to do this week.
        if not (period.start <= now <= period.end):
            continue

        current, has_data = goal_service.current_value(db, org, actor, goal, metric)
        result = goal_service.progress(
            current, goal.target_value, metric.direction, has_data=has_data
        )
        pace = pace_service.compute(
            period=period,
            now=now,
            timezone=org.timezone,
            aggregation=metric.aggregation,
            percent=result.percent,
            attained=result.attained,
            current=result.current,
        )

        out.total += 1
        if pace.status == pace_service.HIT:
            out.hit += 1
        elif pace.status == pace_service.NOT_STARTED:
            out.not_started += 1
        elif pace.needs_attention:
            out.behind += 1
            out.gaps.append(
                _gap(db, goal, metric, period, result, pace, today, org)
            )
        else:
            out.on_pace += 1

    # Worst first, so a shortened list is the list that matters.
    out.gaps.sort(key=lambda gap: gap.behind_by, reverse=True)
    out.gaps = out.gaps[:MAX_GAPS]
    return out


def _gap(
    db: DbSession, goal, metric, period, result, pace, today: date, org: Organization
) -> Gap:
    """One behind-goal, turned into something to say to somebody.

    **The rate is per working day, not per calendar day.** "Twelve a day" over
    a fortnight that contains two weekends is a target somebody would miss by
    a third while doing exactly what they were told.
    """
    end_local = period.end.astimezone(periods.tz(org)).date()
    # Today counts: the day is not over, and a gap that says "0 days left" at
    # nine in the morning on the last day is wrong in the discouraging
    # direction.
    days_left = max(pace_service.working_days(today, end_local), 1)

    start_local = period.start.astimezone(periods.tz(org)).date()
    days_done = pace_service.working_days(start_local, today)

    cumulative = metric.aggregation in pace_service.CUMULATIVE
    remaining = goal.target_value - result.current

    return Gap(
        goal_id=goal.id,
        goal_name=goal.name or metric.name,
        subject_name=_subject_name(db, org, goal),
        metric_name=metric.name,
        unit=metric.unit,
        decimal_places=metric.decimal_places,
        unit_label=metric.unit_label,
        current=result.current,
        target=goal.target_value,
        behind_by=round((pace.expected_percent or 0) - result.percent, 1),
        days_left=days_left,
        rate_so_far=(
            (result.current / days_done).quantize(Decimal("0.1"))
            if cumulative and days_done > 0
            else None
        ),
        rate_needed=(
            (remaining / days_left).quantize(Decimal("0.1"))
            if cumulative and remaining > 0
            else None
        ),
    )


def _subject_name(db: DbSession, org: Organization, goal: Goal) -> str:
    """Whose goal it is.

    **A gap with no name on it is not a coaching gap**, it is a statistic — so
    this is resolved here rather than left to the caller, even though it costs
    a lookup per behind-goal. There are at most `MAX_GAPS` of them by the time
    anybody reads it.
    """
    if goal.subject_type == "organization":
        return org.name
    if goal.subject_type == "team":
        team = db.get(Team, goal.subject_team_id)
        return team.name if team else "Deleted team"
    person = db.get(UserAccount, goal.subject_user_id)
    return person.full_name if person else "Deleted user"


def _may_see(db: DbSession, actor: UserAccount, goal: Goal) -> bool:
    """The same rule the goal list obeys, asked one goal at a time."""
    if goal.subject_type == "organization":
        return True
    if goal.subject_user_id is not None:
        return can_see_user(db, actor, goal.subject_user_id)
    return actor.org_role == "admin" or goal.subject_team_id == actor.team_id

# -- A competition, against the ones before it -------------------------------


#: How many earlier contests to put beside this one.
MAX_RUNS = 8


@dataclass
class Run:
    """One comparable contest that has already finished."""

    competition_id: int
    name: str
    ended_on: date
    winner_name: str
    value: Decimal


@dataclass
class CompetitionReport:
    """Where a contest is going, read against where the last ones landed."""

    competition_id: int
    name: str
    state: str
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None
    entity_type: str

    leader_name: str | None = None
    leader_value: Decimal | None = None

    #: How much of the window has gone, as working time.
    elapsed_percent: float = 0.0
    #: Where the leader lands if their rate holds. None once it is over — a
    #: finished contest has a score, and a prediction of a known number is
    #: noise — and None for a metric that does not accumulate.
    predicted: Decimal | None = None
    #: Too little of the window gone to forecast from (P3-11).
    too_early: bool = False

    #: Earlier comparable contests, oldest first.
    runs: list[Run] = field(default_factory=list)

    all_time_high: Decimal | None = None
    all_time_high_name: str | None = None
    first: Decimal | None = None
    previous: Decimal | None = None

    @property
    def basis(self) -> Decimal | None:
        """The number the comparisons are made from.

        The prediction while it runs, the result once it is over. **A
        comparison has to be like for like**: putting a half-finished score
        next to three finished ones says every contest is getting worse.
        """
        if self.state in ("ended", "closed"):
            return self.leader_value
        return self.predicted

    @property
    def vs_first(self) -> Decimal | None:
        return _diff(self.basis, self.first)

    @property
    def vs_previous(self) -> Decimal | None:
        return _diff(self.basis, self.previous)

    @property
    def vs_high(self) -> Decimal | None:
        return _diff(self.basis, self.all_time_high)


def _diff(current: Decimal | None, before: Decimal | None) -> Decimal | None:
    if current is None or before is None:
        return None
    return current - before


#: How much of a contest's window must be gone before it is forecast.
EARLIEST_FORECAST = 0.25


def competition_report(
    db: DbSession,
    org: Organization,
    competition: Competition,
    *,
    now: datetime | None = None,
) -> CompetitionReport:
    """One contest, with the contests it can be judged against.

    **"Past runs" means comparable contests, not repeats of this one.** A
    competition here is an event somebody scheduled rather than a recurring
    window — there is no link from a contest to the one it succeeds, and a
    duplicate is deliberately a draft of its own. So the comparison set is
    every settled contest in this organization on the *same metric* and the
    *same kind of entrant*, which is what makes two scores mean the same
    thing. Each one is named in the answer, so a manager can see exactly what
    is being compared rather than trusting a line.
    """
    now = now or datetime.now(UTC)
    metric = db.get(MetricDefinition, competition.metric_definition_id)

    report = CompetitionReport(
        competition_id=competition.id,
        name=competition.name,
        state=competition.state,
        metric_name=metric.name if metric else "",
        unit=metric.unit if metric else "",
        decimal_places=metric.decimal_places if metric else 0,
        unit_label=metric.unit_label if metric else None,
        entity_type=competition.entity_type,
    )
    if metric is None:
        return report

    table = competition_service.standings(db, org, competition)
    # **Nobody leads while nobody has scored.** Everybody at zero sorts by
    # name, and the first name was reported as "Leading" (QA-21).
    if table and any(row.value for row in table):
        report.leader_name = table[0].entity_name
        report.leader_value = table[0].value

    window = competition_service.window(competition)
    elapsed = pace_service.elapsed_fraction(window, now, org.timezone)
    report.elapsed_percent = round(elapsed * 100, 1)

    # **No forecast from the first few minutes** (P3-11): one $500 entry 50
    # minutes in "finished at $5,106". Nor for a cancelled contest, which
    # will not finish at all (P3-10).
    report.too_early = (
        competition.state not in ("ended", "closed", "cancelled")
        and elapsed < EARLIEST_FORECAST
    )
    if (
        report.leader_value is not None
        and metric.aggregation in pace_service.CUMULATIVE
        and competition.state not in ("ended", "closed", "cancelled")
        and elapsed >= EARLIEST_FORECAST
    ):
        report.predicted = (
            report.leader_value / Decimal(str(elapsed))
        ).quantize(Decimal("1"))

    report.runs = _past_runs(db, org, competition)
    if report.runs:
        report.first = report.runs[0].value
        report.previous = report.runs[-1].value
        best = max(report.runs, key=lambda run: run.value)
        report.all_time_high = best.value
        report.all_time_high_name = best.winner_name

    return report


def _past_runs(db: DbSession, org: Organization, competition: Competition) -> list[Run]:
    """Settled contests on the same metric, oldest first.

    Only `closed` ones: a settled result is the single number in this product
    that is written down rather than recomputed, and it is the only score that
    cannot move under the chart after somebody reads it.
    """
    rows = db.scalars(
        select(Competition)
        .where(
            Competition.organization_id == competition.organization_id,
            Competition.id != competition.id,
            Competition.metric_definition_id == competition.metric_definition_id,
            Competition.entity_type == competition.entity_type,
            Competition.state == "closed",
            Competition.ends_at <= competition.starts_at,
        )
        .order_by(Competition.ends_at.desc())
        .limit(MAX_RUNS)
    ).all()

    runs: list[Run] = []
    for past in rows:
        winner = db.scalar(
            select(CompetitionParticipant).where(
                CompetitionParticipant.competition_id == past.id,
                CompetitionParticipant.final_rank == 1,
            )
        )
        if winner is None or winner.final_value is None:
            continue
        entity_id = winner.user_id or winner.team_id or 0
        runs.append(
            Run(
                competition_id=past.id,
                name=past.name,
                ended_on=periods.last_day(org, past.ends_at),
                winner_name=competition_service.name_of(db, past, entity_id),
                value=winner.final_value,
            )
        )

    runs.reverse()
    return runs


# -- What has been hit before ------------------------------------------------


@dataclass
class Season:
    """One finished period of a goal, and whether it landed."""

    label: str
    value: Decimal
    met_target: bool
    #: False for a period before the series began with nothing recorded
    #: (7.6): shown, but not a miss.
    counted: bool = True


@dataclass
class Record:
    """A goal's track record over the periods before this one."""

    goal_id: int
    goal_name: str
    subject_name: str
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None
    target: Decimal

    #: Oldest first, so the row reads left to right like every other timeline.
    seasons: list[Season] = field(default_factory=list)

    @property
    def counted(self) -> list[Season]:
        return [season for season in self.seasons if season.counted]

    @property
    def considered(self) -> int:
        return len(self.counted)

    @property
    def hit(self) -> int:
        return sum(1 for season in self.counted if season.met_target)

    @property
    def hit_rate(self) -> float:
        if not self.counted:
            return 0.0
        return round(self.hit / len(self.counted) * 100, 1)

    @property
    def current_streak(self) -> int:
        """Consecutive hits ending at the most recent finished period.

        **The streak a person is actually on.** It stops at the last period
        that has finished rather than the one in progress, because a streak
        that broke the moment a month opened would read as broken all month.
        """
        count = 0
        for season in reversed(self.counted):
            if not season.met_target:
                break
            count += 1
        return count

    @property
    def best_streak(self) -> int:
        best = run = 0
        for season in self.counted:
            run = run + 1 if season.met_target else 0
            best = max(best, run)
        return best


def records(
    db: DbSession, org: Organization, actor: UserAccount, *, now: datetime | None = None
) -> list[Record]:
    """Every visible goal's track record, worst first.

    **Measured against today's target, like `goals.history`, and for the same
    reason**: most of these periods had no goal at all, and a recurring goal's
    copies could each have carried a different target. One line across the row
    is the only reading that is consistent.

    Goals on a custom period are left out — a one-off window has no defined
    predecessor to step back through.

    The queries are batched by metric rather than run per goal. Walking six
    periods for each of two hundred goals is twelve hundred aggregations for a
    page; every goal on one metric and one period type shares the same six
    answers, so the cost is set by how many metrics an organization has rather
    than by how many goals.
    """
    rows = db.scalars(
        select(Goal).where(
            Goal.organization_id == org.id,
            Goal.archived_at.is_(None),
            Goal.period_type != "custom",
        )
    ).all()

    # **One row per series** (7.6, Q2-7): a repeating goal is a copy per
    # period, and listing each copy put the same person and metric on the page
    # twice. A series is the subject, the metric and the period type; the
    # newest goal in it speaks for it, and the earliest says when it began.
    series: dict[tuple, list[Goal]] = {}
    for goal in rows:
        if not _may_see(db, actor, goal):
            continue
        key = (
            goal.subject_type, goal.subject_user_id, goal.subject_team_id,
            goal.metric_definition_id, goal.period_type,
        )
        series.setdefault(key, []).append(goal)

    began: dict[int, object] = {}
    groups: dict[tuple, list[Goal]] = {}
    for copies in series.values():
        newest = max(copies, key=lambda g: (g.period_anchor, g.id))
        began[newest.id] = min(g.period_anchor for g in copies)
        key = (newest.metric_definition_id, newest.period_type, newest.period_anchor)
        groups.setdefault(key, []).append(newest)

    out: list[Record] = []
    for (metric_id, _, _), members in groups.items():
        metric = db.get(MetricDefinition, metric_id)
        if metric is None:
            continue
        out.extend(_records_for(db, org, actor, metric, members, began))

    # Worst first: a page about track records is a page about the ones that
    # keep missing. Name breaks the tie so the order is stable between loads.
    out.sort(key=lambda record: (record.hit_rate, record.goal_name))
    return out


def _records_for(
    db: DbSession,
    org: Organization,
    actor: UserAccount,
    metric: MetricDefinition,
    members: list[Goal],
    began: dict | None = None,
) -> list[Record]:
    """Every goal sharing one metric and one period shape, in six passes.

    **Only periods that count** (7.6, Q2-7): one a goal in the series covered,
    or one the subject recorded something in. A goal set today for somebody
    with no history read "0 of 6" — six misses for months before the goal,
    or the data, existed."""
    wanted = {goal.subject_type for goal in members}
    period = goal_service.resolve_period(org, members[0])

    labels: list[str] = []
    starts: list = []
    by_user: list[dict[int, Decimal]] = []
    by_team: list[dict[int, Decimal]] = []
    whole: list[Decimal] = []

    for _ in range(goal_service.HISTORY_PERIODS):
        period = periods.previous(org, period)
        labels.append(period.label)
        starts.append(period.start.astimezone(periods.tz(org)).date())
        by_user.append(
            {r.subject_id: r.value for r in aggregate.run(db, org.id, actor, metric, period)}
            if "user" in wanted
            else {}
        )
        by_team.append(
            {
                r.subject_id: r.value
                for r in aggregate.run(
                    db, org.id, actor, metric, period, group_by="team"
                )
            }
            if "team" in wanted
            else {}
        )
        whole.append(
            aggregate.total(db, org.id, actor, metric, period, visible=scope.EVERYONE)
            if "organization" in wanted
            else Decimal(0)
        )

    out: list[Record] = []
    for goal in members:
        record = Record(
            goal_id=goal.id,
            goal_name=goal.name or metric.name,
            subject_name=_subject_name(db, org, goal),
            metric_name=metric.name,
            unit=metric.unit,
            decimal_places=metric.decimal_places,
            unit_label=metric.unit_label,
            target=goal.target_value,
        )
        for index, label in enumerate(labels):
            if goal.subject_type == "organization":
                value, has_data = whole[index], True
            elif goal.subject_type == "team":
                found = by_team[index].get(goal.subject_team_id)
                value, has_data = (found or Decimal(0)), found is not None
            else:
                found = by_user[index].get(goal.subject_user_id)
                value, has_data = (found or Decimal(0)), found is not None

            series_began = (began or {}).get(goal.id, goal.period_anchor)
            covered = series_began is not None and starts[index] >= series_began
            result = goal_service.progress(
                value, goal.target_value, metric.direction, has_data=has_data
            )
            record.seasons.append(
                Season(
                    label=label,
                    value=value,
                    met_target=result.attained,
                    counted=covered or has_data,
                )
            )

        record.seasons.reverse()
        out.append(record)
    return out
