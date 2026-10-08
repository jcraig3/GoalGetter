"""The one query behind leaderboards, dashboards, goal progress, and standings.

Written once so those four features cannot drift apart. Every one of them is
this query with different arguments — a different metric, window, grouping, or
scope — not a different query that happens to look similar.

Two rules it exists to enforce:

**Scope filters the query, never the results.** Fetching everyone and dropping
rows in Python makes counts, "no results" states, and ranks all subtly wrong,
and any path that forgets the filter leaks silently. Pushing it into the WHERE
clause makes the safe version the default one.

**Ranking happens in the database.** Postgres is already holding the aggregated
rows, so `RANK()` is free there. Sorting in Python means transferring the whole
set and reimplementing tie handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, Select, and_, cast, desc, func, literal, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session as DbSession

from app import derived, periods
from app.models import (
    MetricDefinition,
    MetricFact,
    Office,
    Organization,
    Team,
    UserAccount,
)
from app.periods import Period
from app.scope import EVERYONE, VisibleUsers, visible_user_ids

GROUP_BY = ("user", "team", "office")


class _Default:
    """Sentinel for "work the visible set out from the actor".

    A distinct object rather than None, because None is already meaningful
    here — it is EVERYONE. Without this, a caller asking for an unscoped query
    and a caller forgetting to pass anything would be indistinguishable, and
    the unsafe one is the easier mistake to make.
    """


DEFAULT = _Default()


@dataclass
class Row:
    subject_id: int
    subject_name: str
    value: Decimal
    rank: int
    team_id: int | None = None
    team_name: str | None = None


def _aggregate_column(aggregation: str):
    """The SQL function for a metric's aggregation.

    `count` counts ROWS and ignores values — that is the point of it, for
    metrics whose facts are events with no meaningful magnitude. Writing
    `sum(value)` for a count metric would quietly return something else.
    """
    column = MetricFact.value
    if aggregation == "last":
        # **The most recent value, not the largest.** Postgres has no `last()`
        # aggregate, so this is the standard spelling: order the group by time and
        # take the first. `max(value)` would be wrong for exactly the metric this
        # exists for — a running total that can go down.
        #
        # This was declared in `AGGREGATIONS` and never implemented, so a metric
        # using it raised `KeyError: last` on every leaderboard query. Snapshot
        # sources need it: one fact per person, rewritten each sync.
        return func.array_agg(
            aggregate_order_by(column, MetricFact.occurred_at.desc())
        )[1]

    return {
        "sum": func.sum(column),
        "count": func.count(),
        "avg": func.avg(column),
        "max": func.max(column),
        "min": func.min(column),
    }[aggregation]


def _base_filters(org_id: int, metric: MetricDefinition, period: Period):
    return [
        MetricFact.organization_id == org_id,
        MetricFact.metric_definition_id == metric.id,
        # Half-open: >= start, < end. The end of one period is the start of the
        # next, so `<=` would count a boundary fact in both.
        MetricFact.occurred_at >= period.start,
        MetricFact.occurred_at < period.end,
    ]


def _scored(
    db: DbSession,
    org_id: int,
    actor: UserAccount,
    metric: MetricDefinition,
    period: Period,
    group_by: str,
    team_id: int | None,
    visible: VisibleUsers | _Default = DEFAULT,
    office_id: int | None = None,
    team_ids: list[int] | None = None,
) -> Select:
    """A subquery of (subject_id, score), before ranking or naming."""
    if derived.is_derived(metric):
        # **A ratio of the two scores, per subject** — each part aggregated
        # its own way over exactly the same rows and scope, then divided.
        # Subjects with nothing to divide by have no rate at all, rather than
        # a rate of zero: no deals is not a 0% close rate.
        numerator, denominator = derived.components(db, metric)
        parts = dict(
            db=db, org_id=org_id, actor=actor, period=period, group_by=group_by,
            team_id=team_id, visible=visible, office_id=office_id, team_ids=team_ids,
        )
        top = _scored(metric=numerator, **parts).subquery()
        bottom = _scored(metric=denominator, **parts).subquery()
        # Cast before dividing: two counts are integers, and integer division
        # would make every close rate under 100% zero.
        rate = func.round(
            cast(func.coalesce(top.c.score, 0), Numeric)
            * derived.scale(metric)
            / cast(bottom.c.score, Numeric),
            4,
        )
        return (
            select(bottom.c.subject_id.label("subject_id"), rate.label("score"))
            .select_from(bottom.outerjoin(top, top.c.subject_id == bottom.c.subject_id))
            .where(bottom.c.score > 0)
        )

    # Every grouping key is a column ON metric_fact — the snapshots — never a
    # join to current state. That is what keeps a past board answering the same
    # way after somebody moves team or a team moves office.
    key = {
        "user": MetricFact.subject_user_id,
        "team": MetricFact.subject_team_id,
        "office": MetricFact.subject_office_id,
    }[group_by]

    filters = _base_filters(org_id, metric, period)

    # Scope. EVERYONE means "no filter" — an admin, or a caller that has
    # already authorised the whole set some other way.
    #
    # Passing `visible` explicitly is how a published leaderboard shows every
    # entrant to an agent who would otherwise see only themselves. It is a
    # deliberate hole, and it is spelled out at the call site rather than
    # hidden behind a boolean, so it cannot be switched on by accident.
    resolved = visible_user_ids(db, actor) if isinstance(visible, _Default) else visible
    if resolved is not EVERYONE:
        filters.append(MetricFact.subject_user_id.in_(resolved))

    if team_id is not None:
        filters.append(MetricFact.subject_team_id == team_id)

    if office_id is not None:
        filters.append(MetricFact.subject_office_id == office_id)

    # An explicit entrant set, for a competition between named teams.
    #
    # `visible` already does this for people, and the ranking has to be
    # computed *within* the entrants — filtering rows afterwards would rank
    # each team against the whole organization and then hide the others,
    # which is a different and wrong number.
    if team_ids is not None:
        filters.append(MetricFact.subject_team_id.in_(team_ids))

    if group_by in ("team", "office"):
        # Rows with no team, or no office, are excluded rather than grouped
        # under a NULL heading: "unassigned" is not a team and "no office" is
        # not an office. They still count on the per-person board.
        filters.append(key.is_not(None))

    if metric.aggregation == "last":
        # A snapshot metric — pipeline size, quota attainment — where the facts
        # are running totals rather than increments. Summing them is nonsense,
        # so the most recent one per subject wins.
        #
        # ROW_NUMBER over a partition rather than DISTINCT ON, because it works
        # unchanged for both groupings.
        ranked = (
            select(
                key.label("subject_id"),
                MetricFact.value.label("score"),
                func.row_number()
                .over(partition_by=key, order_by=desc(MetricFact.occurred_at))
                .label("recency"),
            )
            .where(and_(*filters))
            .subquery()
        )
        return select(ranked.c.subject_id, ranked.c.score).where(ranked.c.recency == 1)

    return (
        select(key.label("subject_id"), _aggregate_column(metric.aggregation).label("score"))
        .where(and_(*filters))
        .group_by(key)
    )


def run(
    db: DbSession,
    org_id: int,
    actor: UserAccount,
    metric: MetricDefinition,
    period: Period,
    *,
    group_by: str = "user",
    team_id: int | None = None,
    office_id: int | None = None,
    dense_rank: bool = False,
    limit: int | None = None,
    visible: VisibleUsers | _Default = DEFAULT,
    team_ids: list[int] | None = None,
) -> list[Row]:
    scored = _scored(
        db, org_id, actor, metric, period, group_by, team_id, visible, office_id,
        team_ids,
    ).subquery()

    # `lower_is_better` flips the sort. Getting this wrong doesn't error — it
    # produces a leaderboard that celebrates the worst performer, which is why
    # `direction` is read here rather than assumed anywhere.
    ordering = (
        scored.c.score.asc()
        if metric.direction == "lower_is_better"
        else scored.c.score.desc()
    )

    # RANK gives 1, 2, 2, 4 — two tied for 2nd and nobody 3rd, which is how
    # sales contests actually work and the honest default. DENSE_RANK gives
    # 1, 2, 2, 3 and is available per board.
    rank_fn = func.dense_rank() if dense_rank else func.rank()

    if group_by == "user":
        query = (
            select(
                scored.c.subject_id,
                UserAccount.full_name,
                UserAccount.team_id,
                Team.name,
                scored.c.score,
                rank_fn.over(order_by=ordering).label("rank"),
            )
            .join(UserAccount, UserAccount.id == scored.c.subject_id)
            .outerjoin(Team, Team.id == UserAccount.team_id)
            # **Hidden people are not ranked.** This join existed only to put a
            # name and a team beside a score, so for a long time hiding somebody
            # took them off the roster and left them sitting on every leaderboard
            # — which is the one place the word "hidden" has to mean something.
            #
            # On this branch alone, and that is the whole design. Team and office
            # standings group on `metric_fact.subject_team_id` and
            # `subject_office_id`, snapshots written when the fact arrived, so
            # they never reach this join: a hidden person's numbers keep counting
            # toward their team's total while the person themselves disappears.
            # Removing them from the totals as well would silently rewrite last
            # week's team figures.
            .where(UserAccount.hidden_at.is_(None))
        )
    elif group_by == "team":
        query = (
            select(
                scored.c.subject_id,
                Team.name,
                # Two placeholders so every branch returns the same column
                # count and order — the alternative is separate unpacking
                # loops that drift apart the first time a column is added.
                Team.id,
                Team.name,
                scored.c.score,
                rank_fn.over(order_by=ordering).label("rank"),
            ).join(Team, Team.id == scored.c.subject_id)
        )
    else:
        query = (
            select(
                scored.c.subject_id,
                Office.name,
                # An office has no parent team, so the team columns are null.
                literal(None),
                literal(None),
                scored.c.score,
                rank_fn.over(order_by=ordering).label("rank"),
            ).join(Office, Office.id == scored.c.subject_id)
        )

    query = query.order_by("rank", scored.c.subject_id)
    if limit is not None:
        query = query.limit(limit)

    return [
        Row(
            subject_id=subject_id,
            subject_name=name,
            team_id=team_id_,
            team_name=team_name,
            # Decimal all the way out. Converting to float here would undo the
            # exactness NUMERIC was chosen for.
            value=Decimal(score if score is not None else 0),
            rank=rank,
        )
        for subject_id, name, team_id_, team_name, score, rank in db.execute(query).all()
    ]


@dataclass
class Point:
    """One bucket of a series. `value` is None where there is no honest number."""

    bucket: datetime
    value: Decimal | None


# What an empty bucket means depends entirely on the aggregation, and getting
# it wrong draws a chart that is confidently false.
#
# For `sum` and `count`, a day with no facts genuinely is zero — nobody made a
# call. For `avg`, `max`, and `min` it is not: the average response time on a
# day with no responses is not zero, it is unknown, and plotting zero invents a
# dramatic dip that never happened. For `last` — a snapshot metric like
# pipeline size — the value simply did not change, so it carries forward; zero
# would show the pipeline emptying every night and refilling every morning.
ZERO_WHEN_EMPTY = ("sum", "count")
CARRIED_WHEN_EMPTY = ("last",)


def series(
    db: DbSession,
    org: Organization,
    actor: UserAccount,
    metric: MetricDefinition,
    period: Period,
    *,
    subject_user_id: int | None = None,
    team_id: int | None = None,
    office_id: int | None = None,
    visible: VisibleUsers | _Default = DEFAULT,
) -> list[Point]:
    """The same number as `run` and `total`, sliced over time.

    Deliberately in this module and built from the same `_base_filters` and
    `_aggregate_column`: a sparkline that ended somewhere other than the figure
    printed next to it would be worse than no sparkline, and the only reliable
    way to prevent that is for both to be the same query with one extra
    GROUP BY.

    Bucketing happens in the ORGANIZATION's timezone, via `date_trunc`'s third
    argument, for the same reason every period boundary does — a day has to
    mean the same day to everyone looking at the chart. Truncating in UTC would
    put an evening call in Phoenix on the following day.
    """
    if derived.is_derived(metric):
        # Per bucket, the same division as the total — so the line ends at the
        # figure printed beside it. A bucket with nothing to divide by is a gap.
        numerator, denominator = derived.components(db, metric)
        parts = dict(
            subject_user_id=subject_user_id, team_id=team_id, office_id=office_id,
            visible=visible,
        )
        tops = series(db, org, actor, numerator, period, **parts)
        bottoms = series(db, org, actor, denominator, period, **parts)
        return [
            Point(
                bucket=top.bucket,
                value=(
                    round((top.value or Decimal(0)) * derived.scale(metric) / bottom.value, 4)
                    if bottom.value
                    else None
                ),
            )
            for top, bottom in zip(tops, bottoms)
        ]

    unit = periods.bucket_unit(period)
    bucket = func.date_trunc(unit, MetricFact.occurred_at, org.timezone).label("bucket")

    filters = _base_filters(org.id, metric, period)

    resolved = visible_user_ids(db, actor) if isinstance(visible, _Default) else visible
    if resolved is not EVERYONE:
        filters.append(MetricFact.subject_user_id.in_(resolved))
    if subject_user_id is not None:
        filters.append(MetricFact.subject_user_id == subject_user_id)
    if team_id is not None:
        filters.append(MetricFact.subject_team_id == team_id)
    if office_id is not None:
        filters.append(MetricFact.subject_office_id == office_id)

    if metric.aggregation == "last":
        # The latest fact *within each bucket*, mirroring how `_scored` takes
        # the latest within the whole period.
        ranked = (
            select(
                bucket,
                MetricFact.value.label("score"),
                func.row_number()
                .over(partition_by=bucket, order_by=desc(MetricFact.occurred_at))
                .label("recency"),
            )
            .where(and_(*filters))
            .subquery()
        )
        query = select(ranked.c.bucket, ranked.c.score).where(ranked.c.recency == 1)
    else:
        query = (
            select(bucket, _aggregate_column(metric.aggregation))
            .where(and_(*filters))
            .group_by(bucket)
        )

    found = {row[0]: row[1] for row in db.execute(query).all()}

    # Walk every bucket the period contains, not just the ones with rows. The
    # query returns only days that had facts; using it directly would close the
    # gaps up and show a steady line where the truth is a stop-start one.
    points: list[Point] = []
    carried: Decimal | None = None
    for start in periods.bucket_starts(org, period):
        if start in found:
            raw = found[start]
            value = Decimal(raw) if raw is not None else None
            carried = value
        elif metric.aggregation in ZERO_WHEN_EMPTY:
            value = Decimal(0)
        elif metric.aggregation in CARRIED_WHEN_EMPTY:
            # None until the first snapshot arrives — before that there is
            # nothing to carry, and zero would be a claim we cannot make.
            value = carried
        else:
            value = None
        points.append(Point(bucket=start, value=value))
    return points


def running_total(points: list[Point]) -> list[Point]:
    """Turn per-bucket values into the cumulative line.

    Only meaningful for `sum` and `count` — see `pace.CUMULATIVE`, which draws
    the same distinction for the same reason. A running total of daily averages
    is not a number that means anything, so callers check the aggregation
    before calling this rather than it being applied automatically.
    """
    out: list[Point] = []
    total_so_far = Decimal(0)
    for point in points:
        if point.value is not None:
            total_so_far += point.value
        out.append(Point(bucket=point.bucket, value=total_so_far))
    return out


def total(
    db: DbSession,
    org_id: int,
    actor: UserAccount,
    metric: MetricDefinition,
    period: Period,
    *,
    group_by: str = "user",
    team_id: int | None = None,
    office_id: int | None = None,
    visible: VisibleUsers | _Default = DEFAULT,
) -> Decimal:
    """The overall figure across exactly the same rows the breakdown covers.

    Computed with its own query rather than by summing the breakdown, because
    those two are not the same number for `avg`, `max`, `min`, or `last` — the
    average of per-person averages is not the overall average, and summing
    per-person maxima is meaningless. It also has to survive `limit`, which
    truncates the rows but must not change the total.

    `group_by` is taken because a team breakdown excludes people on no team.
    Without applying the same exclusion here, the total would exceed the sum of
    the teams by exactly the unassigned agents' contribution — a discrepancy
    that reads as an arithmetic bug on screen.
    """
    if derived.is_derived(metric):
        # The overall rate: everybody's wins over everybody's deals — not the
        # average of each person's rate. See `app/derived.py`.
        numerator, denominator = derived.components(db, metric)
        parts = dict(group_by=group_by, team_id=team_id, office_id=office_id, visible=visible)
        bottom = total(db, org_id, actor, denominator, period, **parts)
        if not bottom:
            return Decimal(0)
        top = total(db, org_id, actor, numerator, period, **parts)
        return round(top * derived.scale(metric) / bottom, 4)

    filters = _base_filters(org_id, metric, period)

    resolved = visible_user_ids(db, actor) if isinstance(visible, _Default) else visible
    if resolved is not EVERYONE:
        filters.append(MetricFact.subject_user_id.in_(resolved))
    if team_id is not None:
        filters.append(MetricFact.subject_team_id == team_id)
    if office_id is not None:
        filters.append(MetricFact.subject_office_id == office_id)
    if group_by == "team":
        filters.append(MetricFact.subject_team_id.is_not(None))
    if group_by == "office":
        filters.append(MetricFact.subject_office_id.is_not(None))

    if metric.aggregation == "last":
        # No meaningful overall "last": one arbitrary person's latest snapshot
        # is not a company figure. Summing the per-subject latest values is, so
        # that is what this returns.
        rows = run(
            db,
            org_id,
            actor,
            metric,
            period,
            group_by=group_by,
            team_id=team_id,
            office_id=office_id,
            visible=visible,
        )
        return sum((row.value for row in rows), Decimal(0))

    result = db.scalar(select(_aggregate_column(metric.aggregation)).where(and_(*filters)))
    return Decimal(result) if result is not None else Decimal(0)
