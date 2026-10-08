"""Resolving a goal into progress.

Progress is never stored. It is the same `aggregate` query the leaderboards
run, narrowed to one subject — so a goal and a leaderboard showing the same
month can never disagree about someone's number. The alternative, a
`current_value` column, would be wrong the moment a connector backfilled
yesterday's data and would need invalidating from every write path.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session as DbSession

from app import aggregate, periods, scope
from app.models import Goal, MetricDefinition, Organization, UserAccount
from app.pace import CUMULATIVE
from app.periods import Period


@dataclass
class Progress:
    current: Decimal
    target: Decimal
    #: False when the period contains no facts at all for this subject.
    has_data: bool
    # 0-1000 rather than capped at 100: beating a target is the point, and a
    # bar that stops at 100% cannot tell "just made it" from "doubled it".
    # Callers cap the *bar width*, never the number.
    percent: float
    attained: bool


def resolve_period(org: Organization, goal: Goal) -> Period:
    """The goal's window, re-resolved from how it was chosen.

    Not stored as instants: "August 2026" has to keep meaning the same thing as
    the leaderboard for August 2026, including after someone changes the
    organization's timezone.
    """
    return periods.resolve(
        org,
        goal.period_type,
        goal.period_anchor,
        custom_start=goal.period_start,
        custom_end=goal.period_end,
    )


def current_value(
    db: DbSession, org: Organization, actor: UserAccount, goal: Goal, metric: MetricDefinition
) -> tuple[Decimal, bool]:
    """What the subject has done in the goal's period, and whether anything was
    recorded at all.

    The second value matters for `lower_is_better`. Nothing recorded reads as
    zero, and zero is under every cap — so without it, "keep average response
    time under 60 seconds" reports as HIT for an agent who answered no calls.
    Absence is not achievement, and a goal that congratulates you for doing
    nothing is worse than no goal.

    Scope still applies. A goal is not a way to read a number you are not
    entitled to: an agent querying a team goal they are not on gets the part
    they can see, which for an agent is only themselves.
    """
    period = resolve_period(org, goal)

    if goal.subject_type == "organization":
        # **Everyone's numbers, to everyone.** A goal the whole floor is
        # pulling toward is meaningless if each person sees only their own
        # slice of it — the shared figure *is* the feature. The same
        # deliberate hole a published leaderboard uses, spelled out at the call
        # site rather than hidden behind a flag.
        return (
            aggregate.total(
                db, org.id, actor, metric, period, visible=scope.EVERYONE
            ),
            True,
        )

    if goal.subject_type == "team":
        rows = aggregate.run(
            db,
            org.id,
            actor,
            metric,
            period,
            group_by="team",
            team_id=goal.subject_team_id,
        )
    else:
        rows = aggregate.run(db, org.id, actor, metric, period)
        rows = [row for row in rows if row.subject_id == goal.subject_user_id]

    # No rows is a real answer — nothing recorded yet — not a missing value.
    # Returning None here would make every caller handle a case that means zero.
    return (rows[0].value, True) if rows else (Decimal(0), False)


def trend(
    db: DbSession, org: Organization, actor: UserAccount, goal: Goal, metric: MetricDefinition
) -> list[aggregate.Point]:
    """The goal's number over time, for a sparkline.

    Deliberately the sibling of `current_value` and filtered identically — the
    last point of this line has to be the number the progress bar shows, or the
    chart contradicts the figure printed next to it. Same reason scope is
    applied here too: a chart is as much of a read as a total is.

    **Cumulative for `sum` and `count`, per-bucket for everything else**, which
    is the same distinction `pace` draws and for the same reason. A goal of
    "500 calls this month" is chasing a running total, so the line that answers
    "will I make it" is the climbing one. An average response time is not
    chasing anything — a running total of daily averages is not a number.
    """
    period = resolve_period(org, goal)

    if goal.subject_type == "organization":
        points = aggregate.series(
            db, org, actor, metric, period, visible=scope.EVERYONE
        )
    elif goal.subject_type == "team":
        points = aggregate.series(
            db, org, actor, metric, period, team_id=goal.subject_team_id
        )
    else:
        points = aggregate.series(
            db, org, actor, metric, period, subject_user_id=goal.subject_user_id
        )

    return aggregate.running_total(points) if metric.aggregation in CUMULATIVE else points


def contributors(
    db: DbSession, org: Organization, actor: UserAccount, goal: Goal, metric: MetricDefinition
) -> list[aggregate.Row]:
    """Who made up a team goal's number, ranked.

    The question a manager actually has when a team goal is behind is not "by
    how much" — the bar already says that — but "who". Empty for a personal
    goal, where the answer is the one person named on it.

    Scoped like everything else, so an agent opening a team goal sees the
    contribution they are entitled to see, which for an agent is their own.
    That makes the list shorter than the total above it, which is correct: the
    total is the team's, and the breakdown is what this viewer may read.
    """
    if goal.subject_type == "organization":
        # **Every team, not every person.** Four hundred rows under a company
        # target is a directory, not an answer; "which floor is carrying this"
        # is the question somebody actually has.
        return aggregate.run(
            db,
            org.id,
            actor,
            metric,
            resolve_period(org, goal),
            group_by="team",
            visible=scope.EVERYONE,
        )

    if goal.subject_type != "team":
        return []

    return aggregate.run(
        db,
        org.id,
        actor,
        metric,
        resolve_period(org, goal),
        group_by="user",
        team_id=goal.subject_team_id,
    )


@dataclass
class PastPeriod:
    """One earlier period of the same metric and subject."""

    label: str
    value: Decimal
    #: Against **today's** target, not whatever was set at the time. See
    #: `history` for why that is the honest comparison to draw.
    met_target: bool


#: How many earlier periods a detail page looks back over. Six is a half-year
#: of months, two quarters of weeks — enough to see a trend, few enough that
#: each one is a distinct bar rather than a smear.
HISTORY_PERIODS = 6


def history(
    db: DbSession, org: Organization, actor: UserAccount, goal: Goal, metric: MetricDefinition
) -> list[PastPeriod]:
    """The same metric and subject over the periods before this one.

    This answers the question that decides whether a goal is any good: **is
    the target realistic?** A team that has closed 30, 28 and 33 deals in the
    last three months has a lot to say about a target of 90, and none of it is
    visible on a progress bar.

    **Measured against today's target, deliberately, and labelled as such.** It
    is not a record of goals that existed then — most of these periods had no
    goal at all, and a recurring goal's copies could each have carried a
    different target. Comparing every period to one line is the only reading
    that is consistent across the row; anything else would put bars of
    different meanings side by side.

    Empty for a custom period, which has no defined predecessor to step back
    through.
    """
    if goal.period_type == "custom":
        return []

    past: list[PastPeriod] = []
    period = resolve_period(org, goal)

    for _ in range(HISTORY_PERIODS):
        period = periods.previous(org, period)

        if goal.subject_type == "organization":
            # The whole floor's number, the same deliberate hole
            # `current_value` opens for the same reason — and always a real
            # answer, so `has_data` is never in question.
            value, has_data = (
                aggregate.total(
                    db, org.id, actor, metric, period, visible=scope.EVERYONE
                ),
                True,
            )
        else:
            if goal.subject_type == "team":
                rows = aggregate.run(
                    db, org.id, actor, metric, period, group_by="team",
                    team_id=goal.subject_team_id,
                )
            else:
                rows = aggregate.run(db, org.id, actor, metric, period)
                rows = [row for row in rows if row.subject_id == goal.subject_user_id]

            value = rows[0].value if rows else Decimal(0)
            has_data = bool(rows)

        result = progress(
            value, goal.target_value, metric.direction, has_data=has_data
        )
        past.append(
            PastPeriod(label=period.label, value=value, met_target=result.attained)
        )

    # Oldest first, so the row reads left to right like every other timeline.
    past.reverse()
    return past


def progress(
    current: Decimal, target: Decimal, direction: str, *, has_data: bool = True
) -> Progress:
    """Turn a value and a target into something a bar can render.

    `direction` decides what "attained" means. For `lower_is_better` — average
    response time, cost per deal — being *under* the target is success, and
    treating it like a count would show someone at 40% for beating their target
    by 60%.
    """
    if direction == "lower_is_better":
        # Inverted: at or below target is 100%. Above target degrades toward 0.
        # A zero current value is a perfect score, not a division by zero.
        percent = 100.0 if current <= 0 else min(float(target / current) * 100, 1000.0)
        # An empty period is not a success. Nothing recorded reads as zero, and
        # zero is under every cap — so this is the difference between "answered
        # every call in 20 seconds" and "answered no calls".
        attained = has_data and current <= target
        if not has_data:
            percent = 0.0
    else:
        percent = min(float(current / target) * 100, 1000.0) if target else 0.0
        attained = current >= target

    return Progress(
        current=current,
        target=target,
        has_data=has_data,
        # One decimal place. Anything finer is noise on a progress bar, and the
        # exact figures are `current` and `target` right beside it.
        percent=round(percent, 1),
        attained=attained,
    )
