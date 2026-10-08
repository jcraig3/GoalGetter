"""Bucketed aggregation — the same numbers, sliced over time.

A sparkline is read for its *shape*, and the two ways to draw a false shape are
both silent: dropping the buckets that had no facts (which closes the gaps up
and turns stop-start work into a steady line), and filling every empty bucket
with zero regardless of what the metric means (which invents cliffs in an
average that never happened). Most of what is below is about those two.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app import aggregate
from app.periods import bucket_starts, bucket_unit, resolve

# The fixture organization is America/New_York, which is UTC-4 in August and
# has a daylight-saving change in March. Both are used deliberately.
WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)
ANCHOR = WHEN.date()


@pytest.fixture
def month(org):
    return resolve(org, "month", ANCHOR)


@pytest.fixture
def world(make_team, make_user):
    enterprise = make_team("Enterprise")
    return {
        "enterprise": enterprise,
        "admin": make_user("admin", name="Admin"),
        "alice": make_user("agent", enterprise, name="Alice"),
        "bob": make_user("agent", enterprise, name="Bob"),
    }


def series(db, org, actor, metric, period, **kwargs):
    return aggregate.series(db, org, actor, metric, period, **kwargs)


def at(day: int, hour: int = 15) -> datetime:
    """An instant in August 2026, in UTC."""
    return datetime(2026, 8, day, hour, tzinfo=UTC)


# ── Bucket boundaries ────────────────────────────────────────────────────────


def test_a_month_is_bucketed_daily(org, month):
    assert bucket_unit(month) == "day"
    assert len(bucket_starts(org, month)) == 31


def test_a_year_is_bucketed_monthly(org):
    """365 daily points is not a sparkline, it is a smear."""
    year = resolve(org, "year", ANCHOR)
    assert bucket_unit(year) == "month"
    assert len(bucket_starts(org, year)) == 12


def test_a_quarter_stays_daily(org):
    """~92 days is still a readable shape, and daily is the more useful one."""
    quarter = resolve(org, "quarter", ANCHOR)
    assert bucket_unit(quarter) == "day"
    assert len(bucket_starts(org, quarter)) == 92


def test_buckets_start_at_local_midnight_not_utc_midnight(org, month):
    """The whole point of passing the timezone to `date_trunc`.

    New York is UTC-4 in August, so a local day begins at 04:00 UTC. Truncating
    in UTC would move every evening fact into the following day.
    """
    first = bucket_starts(org, month)[0]
    assert first == datetime(2026, 8, 1, 4, 0, tzinfo=UTC)


def test_buckets_follow_the_daylight_saving_shift(org):
    """March 2026 contains a DST start, so the local day stops being 5 hours
    behind UTC and starts being 4. A fixed interval would drift from there on
    and misfile every remaining day of the month."""
    march = resolve(org, "month", datetime(2026, 3, 15, tzinfo=UTC).date())
    starts = bucket_starts(org, march)

    assert len(starts) == 31
    assert starts[6] == datetime(2026, 3, 7, 5, 0, tzinfo=UTC)  # EST, before
    assert starts[9] == datetime(2026, 3, 10, 4, 0, tzinfo=UTC)  # EDT, after
    # Consecutive boundaries still meet exactly, which is what stops a fact
    # falling in a gap or landing in two buckets.
    assert all(later > earlier for earlier, later in zip(starts, starts[1:]))


# ── Empty buckets ────────────────────────────────────────────────────────────


def test_days_with_no_facts_are_still_returned(db, org, world, make_metric, make_fact, month):
    """The query returns only days that had rows. Using it directly would
    compress the quiet days out and draw a busier, steadier month than the
    real one."""
    metric = make_metric(aggregation="sum")
    make_fact(metric, world["alice"], 10, at(3))
    make_fact(metric, world["alice"], 4, at(20))

    points = series(db, org, world["admin"], metric, month)

    assert len(points) == 31
    assert [p.value for p in points if p.value] == [Decimal(10), Decimal(4)]


def test_an_empty_day_is_zero_for_a_sum(db, org, world, make_metric, make_fact, month):
    """Nobody made a call, so the honest number is zero."""
    metric = make_metric(aggregation="sum")
    make_fact(metric, world["alice"], 10, at(3))
    points = series(db, org, world["admin"], metric, month)
    assert points[0].value == Decimal(0)
    assert points[2].value == Decimal(10)


def test_an_empty_day_is_unknown_for_an_average(db, org, world, make_metric, make_fact, month):
    """The average response time on a day with no responses is not zero.

    Plotting zero would draw a dramatic daily collapse that never happened —
    the most misleading thing this module could do.
    """
    metric = make_metric(aggregation="avg")
    make_fact(metric, world["alice"], 10, at(3))
    points = series(db, org, world["admin"], metric, month)
    assert points[0].value is None
    assert points[2].value == Decimal(10)


def test_a_snapshot_carries_forward_across_empty_days(
    db, org, world, make_metric, make_fact, month
):
    """`last` metrics are running totals — pipeline size, quota attainment.

    A quiet day means the figure did not change, not that the pipeline emptied
    overnight and refilled in the morning.
    """
    metric = make_metric(aggregation="last")
    make_fact(metric, world["alice"], 100, at(3))
    make_fact(metric, world["alice"], 150, at(6))

    points = series(db, org, world["admin"], metric, month)

    assert points[0].value is None  # nothing known before the first snapshot
    assert points[2].value == Decimal(100)
    assert points[3].value == Decimal(100)  # unchanged, not zero
    assert points[4].value == Decimal(100)
    assert points[5].value == Decimal(150)
    assert points[30].value == Decimal(150)  # still standing at month end


def test_a_snapshot_takes_the_latest_value_within_a_day(
    db, org, world, make_metric, make_fact, month
):
    metric = make_metric(aggregation="last")
    make_fact(metric, world["alice"], 100, at(3, hour=13))
    make_fact(metric, world["alice"], 175, at(3, hour=21))
    assert series(db, org, world["admin"], metric, month)[2].value == Decimal(175)


# ── Timezone ─────────────────────────────────────────────────────────────────


def test_a_late_evening_fact_belongs_to_the_local_day(
    db, org, world, make_metric, make_fact, month
):
    """21:00 in New York is 01:00 the next day in UTC. Bucketing in UTC would
    file an agent's last call of the day under tomorrow, which is exactly the
    off-by-one nobody notices on a chart."""
    metric = make_metric(aggregation="sum")
    make_fact(metric, world["alice"], 7, datetime(2026, 8, 13, 1, 0, tzinfo=UTC))

    points = series(db, org, world["admin"], metric, month)

    assert points[11].value == Decimal(7)  # the 12th, locally
    assert points[12].value == Decimal(0)  # the 13th, untouched


# ── Same numbers as everything else ──────────────────────────────────────────


def test_the_series_sums_to_the_period_total(
    db, org, world, make_metric, make_fact, month
):
    """The anti-drift property, and the reason this lives in `aggregate`.

    A sparkline that ended somewhere other than the figure printed beside it
    would be worse than no sparkline at all.
    """
    metric = make_metric(aggregation="sum")
    for day, value in ((2, 5), (2, 3), (9, 11), (28, 40)):
        make_fact(metric, world["alice"], value, at(day))
        make_fact(metric, world["bob"], value, at(day))

    points = series(db, org, world["admin"], metric, month)
    expected = aggregate.total(db, org.id, world["admin"], metric, month)

    assert sum(p.value for p in points if p.value is not None) == expected


def test_a_running_total_ends_at_the_period_total(
    db, org, world, make_metric, make_fact, month
):
    metric = make_metric(aggregation="sum")
    make_fact(metric, world["alice"], 10, at(3))
    make_fact(metric, world["alice"], 15, at(20))

    line = aggregate.running_total(series(db, org, world["admin"], metric, month))

    assert line[2].value == Decimal(10)
    assert line[19].value == Decimal(25)
    assert line[-1].value == aggregate.total(db, org.id, world["admin"], metric, month)


def test_a_running_total_never_goes_down(db, org, world, make_metric, make_fact, month):
    """A cumulative line that dips is a bug people can see. This is the cheap
    invariant that catches it."""
    metric = make_metric(aggregation="sum")
    for day in (2, 5, 5, 19, 30):
        make_fact(metric, world["alice"], day, at(day))

    values = [p.value for p in aggregate.running_total(series(db, org, world["admin"], metric, month))]

    assert all(later >= earlier for earlier, later in zip(values, values[1:]))


# ── Scope ────────────────────────────────────────────────────────────────────


def test_a_series_is_scoped_like_every_other_query(
    db, org, world, make_metric, make_fact, month
):
    """An agent's own chart must not silently include their colleagues."""
    metric = make_metric(aggregation="sum")
    make_fact(metric, world["alice"], 10, at(3))
    make_fact(metric, world["bob"], 90, at(3))

    mine = series(db, org, world["alice"], metric, month)

    assert mine[2].value == Decimal(10)


def test_one_persons_line_can_be_asked_for(db, org, world, make_metric, make_fact, month):
    metric = make_metric(aggregation="sum")
    make_fact(metric, world["alice"], 10, at(3))
    make_fact(metric, world["bob"], 90, at(3))

    points = series(
        db, org, world["admin"], metric, month, subject_user_id=world["bob"].id
    )

    assert points[2].value == Decimal(90)


def test_a_team_line_uses_the_snapshot_not_current_membership(
    db, org, world, make_team, make_metric, make_fact, month
):
    """Same rule as the leaderboards: a chart of the past must not change
    because somebody transferred this morning."""
    metric = make_metric(aggregation="sum")
    smb = make_team("SMB")
    make_fact(metric, world["alice"], 10, at(3))
    make_fact(metric, world["alice"], 25, at(4), team=smb)

    points = series(
        db, org, world["admin"], metric, month, team_id=world["enterprise"].id
    )

    assert points[2].value == Decimal(10)
    assert points[3].value == Decimal(0)
