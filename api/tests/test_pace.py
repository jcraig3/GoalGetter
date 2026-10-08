"""Pace: am I ahead or behind for this point in the period?

Pure date arithmetic against a resolved period, so these run without a
database. The weekend cases are the point — calendar pacing passes almost
everything here and still tells every agent they slipped over the weekend.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app import pace as pace_service
from app.models import Organization
from app.pace import AHEAD, BEHIND, HIT, MISSED, NOT_STARTED, ON_TRACK, working_days
from app.periods import resolve

NY = "America/New_York"


def org(timezone=NY):
    return Organization(
        name="t", timezone=timezone, week_starts_on=1, fiscal_year_start_month=1
    )


def at(day: int, hour: int = 12) -> datetime:
    """Noon on a day in August 2026, UTC."""
    return datetime(2026, 8, day, hour, tzinfo=UTC)


def august():
    return resolve(org(), "month", date(2026, 8, 12))


def compute(now, *, percent=0.0, attained=False, aggregation="sum", current=0, period=None):
    return pace_service.compute(
        period=period or august(),
        now=now,
        timezone=NY,
        aggregation=aggregation,
        percent=percent,
        attained=attained,
        current=Decimal(current),
    )


# ── working_days ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2026, 8, 3), date(2026, 8, 8), 5),  # Mon–Fri
        (date(2026, 8, 3), date(2026, 8, 10), 5),  # a full week, weekend excluded
        (date(2026, 8, 8), date(2026, 8, 10), 0),  # Sat + Sun only
        (date(2026, 8, 3), date(2026, 8, 4), 1),
        (date(2026, 8, 3), date(2026, 8, 3), 0),  # empty range
        (date(2026, 8, 10), date(2026, 8, 3), 0),  # reversed
        (date(2026, 8, 1), date(2026, 9, 1), 21),  # August 2026
    ],
)
def test_working_days(start, end, expected):
    assert working_days(start, end) == expected


def test_working_days_matches_a_day_by_day_count_over_a_long_range():
    """The implementation short-cuts whole weeks for speed. This is the naive
    version it has to agree with — a five-year range would otherwise be the
    place an off-by-one hides."""
    from datetime import timedelta

    start, end = date(2024, 1, 1), date(2029, 1, 1)
    naive = sum(
        1
        for offset in range((end - start).days)
        if (start + timedelta(days=offset)).weekday() < 5
    )
    assert working_days(start, end) == naive


# ── Elapsed time ─────────────────────────────────────────────────────────────


def test_nothing_has_elapsed_on_the_first_morning():
    """The current day counts only once it is over, so a goal is not reported
    behind at 9am for work the day still has time to produce."""
    assert compute(at(1)).elapsed_percent == 0.0


def test_a_finished_period_is_fully_elapsed():
    assert compute(at(1) .replace(month=9)).elapsed_percent == 100.0


def test_a_future_period_has_not_started():
    assert compute(at(1).replace(month=7)).status == NOT_STARTED


def test_the_weekend_does_not_advance_the_clock():
    """The reason pace counts working days.

    Saturday, Sunday, and Monday morning all read the same: no selling time
    passed in between. Calendar pacing would move the figure by ~10 percentage
    points across the weekend and tell every agent they had fallen behind while
    the office was shut — every weekend, on a schedule.

    Friday *evening* is deliberately not in this set: the current day counts
    only once it is over, so Friday completing is a real advance.
    """
    saturday = compute(at(8)).elapsed_percent
    sunday = compute(at(9)).elapsed_percent
    monday_morning = compute(at(10, hour=13)).elapsed_percent  # 09:00 in NY
    assert saturday == sunday == monday_morning


def test_a_weekday_does_advance_the_clock():
    """The other direction — the guard above must not be satisfied by a
    function that never moves at all."""
    assert compute(at(11)).elapsed_percent > compute(at(10)).elapsed_percent


def test_elapsed_is_measured_in_the_organization_timezone():
    """01:00 UTC on the 11th is still the 10th in New York, so one fewer
    working day has passed."""
    ny = pace_service.elapsed_fraction(august(), at(11, hour=1), NY)
    utc = pace_service.elapsed_fraction(august(), at(11, hour=1), "UTC")
    assert ny < utc


def test_a_weekend_only_custom_range_does_not_divide_by_zero():
    """A Saturday-to-Sunday range contains no working time to be partway
    through. Reached only from inside the range — on the boundary days the
    "not started" and "finished" branches answer first."""
    period = resolve(
        org(), "custom", custom_start=date(2026, 8, 8), custom_end=date(2026, 8, 9)
    )
    assert compute(at(9), period=period).elapsed_percent == 100.0


# ── Status ───────────────────────────────────────────────────────────────────


def test_reaching_the_target_is_hit_regardless_of_timing():
    assert compute(at(5), percent=100.0, attained=True).status == HIT


def test_well_past_the_expected_line_is_ahead():
    # 3 of 21 working days gone (~14%), already at 60%.
    assert compute(at(6), percent=60.0).status == AHEAD


def test_well_short_of_the_expected_line_is_behind():
    # 14 of 21 working days gone (~67%), only at 20%.
    assert compute(at(21), percent=20.0).status == BEHIND


def test_near_the_expected_line_is_on_track():
    """A tolerance band, so a goal does not flicker between ahead and behind on
    every recorded fact."""
    result = compute(at(14), percent=0.0)
    assert compute(at(14), percent=result.expected_percent).status == ON_TRACK
    assert compute(at(14), percent=result.expected_percent + 4).status == ON_TRACK
    assert compute(at(14), percent=result.expected_percent - 4).status == ON_TRACK


def test_just_outside_the_band_is_not_on_track():
    result = compute(at(14), percent=0.0)
    assert compute(at(14), percent=result.expected_percent + 6).status == AHEAD
    assert compute(at(14), percent=result.expected_percent - 6).status == BEHIND


def test_a_finished_period_short_of_target_is_missed_not_behind():
    """Nothing about a closed period is "behind" any more — it did not
    happen, and calling it behind implies there is still time."""
    assert compute(at(1).replace(month=9), percent=40.0).status == MISSED


def test_needs_attention_covers_behind_and_missed_only(monkeypatch):
    for status_percent, when, expected in [
        (20.0, at(21), True),  # behind
        (40.0, at(1).replace(month=9), True),  # missed
        (60.0, at(6), False),  # ahead
        (100.0, at(6), False),  # hit
    ]:
        result = compute(when, percent=status_percent, attained=status_percent >= 100)
        assert result.needs_attention is expected, result.status


# ── Projection ───────────────────────────────────────────────────────────────


def test_projection_extrapolates_the_current_rate():
    """Asserted as a relationship rather than a magic number, so the test does
    not encode my own arithmetic about which weekday the 14th falls on."""
    result = compute(at(14), percent=50.0, current=100)
    assert result.projected is not None
    expected = round(100 / (result.elapsed_percent / 100))
    assert int(result.projected) == expected


def test_projection_grows_as_the_period_runs_out():
    """The same recorded number, later in the month, projects to less — there
    is less time left for the rate to keep producing."""
    early = compute(at(6), current=100).projected
    late = compute(at(25), current=100).projected
    assert early > late


def test_there_is_no_projection_before_the_period_starts():
    """Dividing by zero elapsed time would be an infinite projection."""
    assert compute(at(1)).projected is None


def test_the_projection_is_a_whole_number():
    """"On pace for 183.4729 calls" implies a precision this estimate does not
    have."""
    result = compute(at(14), percent=50.0, current=100)
    assert result.projected == result.projected.to_integral_value()


# ── Non-cumulative metrics ───────────────────────────────────────────────────


@pytest.mark.parametrize("aggregation", ["avg", "max", "min", "last"])
def test_a_non_cumulative_metric_gets_no_expectation_or_projection(aggregation):
    """A response time averaging 2 minutes on the 10th is not "a third of the
    way" to anything, and projecting it linearly would be nonsense."""
    result = compute(at(14), percent=50.0, aggregation=aggregation, current=100)
    assert result.expected_percent is None
    assert result.projected is None


def test_a_non_cumulative_metric_still_reports_elapsed_time():
    """Elapsed time is a fact about the calendar, true regardless of what is
    being measured."""
    assert compute(at(14), aggregation="avg").elapsed_percent > 0


def test_a_non_cumulative_metric_is_never_behind():
    """Without an expectation there is nothing to be behind of. Reporting one
    would be inventing a judgement the data cannot support."""
    assert compute(at(21), percent=1.0, aggregation="avg").status == ON_TRACK


def test_a_non_cumulative_metric_can_still_be_hit_or_missed():
    assert compute(at(14), attained=True, aggregation="avg").status == HIT
    assert compute(at(1).replace(month=9), aggregation="avg").status == MISSED


# ── Short windows, in hours (7.2) ────────────────────────────────────────────

from datetime import timedelta  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from app.periods import Period  # noqa: E402


def window(start_hour: float, end_hour: float, day: int = 14, end_day: int | None = None) -> Period:
    """A window on a day in August 2026, in New York time. The 14th is a Friday."""
    tz = ZoneInfo(NY)
    start = datetime(2026, 8, day, tzinfo=tz) + timedelta(hours=start_hour)
    end = datetime(2026, 8, end_day or day, tzinfo=tz) + timedelta(hours=end_hour)
    return Period(type="custom", start=start.astimezone(UTC), end=end.astimezone(UTC), label="")


def ny(day: int, hour: float) -> datetime:
    return (datetime(2026, 8, day, tzinfo=ZoneInfo(NY)) + timedelta(hours=hour)).astimezone(UTC)


def test_a_nine_to_five_sprint_at_noon_is_partway_through():
    """The Friday sprint template: whole days made it 100% gone at 9am (Q2-1)."""
    elapsed = pace_service.elapsed_fraction(window(9, 17), ny(14, 12), NY)
    assert elapsed == pytest.approx(3 / 8)


def test_a_goal_for_today_moves_through_the_day():
    """A day period: "not started" until it was over, never behind or ahead
    while it ran (Q2-1). Measured in working hours, 9 to 6."""
    today = resolve(org(), "day", date(2026, 8, 14))
    assert pace_service.elapsed_fraction(today, ny(14, 8), NY) == 0.0
    assert pace_service.elapsed_fraction(today, ny(14, 12), NY) == pytest.approx(3 / 9)
    assert pace_service.elapsed_fraction(today, ny(14, 19), NY) == 1.0
    # And so it can be behind before the day is out.
    result = compute(ny(14, 16), percent=10.0, period=today)
    assert result.status == BEHIND


def test_an_evening_sprint_runs_on_the_clock():
    """Wholly out of working hours: plain clock time, not a division by zero."""
    elapsed = pace_service.elapsed_fraction(window(19, 23), ny(14, 21), NY)
    assert elapsed == pytest.approx(0.5)


def test_a_contest_ending_at_five_on_its_last_day_counts_that_day():
    """Monday 9am to Friday 5pm. On Friday morning four of five working days
    are gone, not all of them — the whole of Friday used to read as over."""
    contest = window(9, 17, day=10, end_day=14)
    assert pace_service.elapsed_fraction(contest, ny(14, 10), NY) == pytest.approx(4 / 5)
    assert pace_service.elapsed_fraction(contest, ny(14, 17.5), NY) == 1.0


def test_nothing_with_time_gone_is_not_on_track():
    """$0 of $250,000 a working day in is inside the tolerance band, and used to
    read "On track" (Q2-10)."""
    result = compute(at(4), percent=0.0)
    assert 0 < result.expected_percent < pace_service.TOLERANCE
    assert result.status == NOT_STARTED
    assert compute(at(4), percent=2.0, current=5).status == ON_TRACK


def test_a_finished_period_projects_nothing():
    """"Period over · on pace for $0.00" (Q2-13)."""
    assert compute(at(1).replace(month=9), current=100).projected is None


def test_nothing_projects_nothing():
    """"On pace for $0.00" is arithmetic, not a forecast."""
    assert compute(at(14), current=0).projected is None
