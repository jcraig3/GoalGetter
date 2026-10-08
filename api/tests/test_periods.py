"""Period boundary math.

The highest-value tests in the suite. These functions are pure, and a wrong
boundary raises no error — it silently reports a different number, and every
figure downstream inherits it.
"""

from datetime import date, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.models import Organization
from app.periods import PERIOD_TYPES, previous, resolve

NY = ZoneInfo("America/New_York")


def make_org(timezone="America/New_York", week_starts_on=1, fiscal_year_start_month=1):
    """Not persisted. `resolve` only reads attributes, so a transient instance
    keeps these tests free of a database round trip."""
    return Organization(
        name="t",
        timezone=timezone,
        week_starts_on=week_starts_on,
        fiscal_year_start_month=fiscal_year_start_month,
    )


def local_date(moment, tz=NY) -> date:
    return moment.astimezone(tz).date()


# ── Week start ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("week_starts_on", "expected"),
    [
        (1, date(2026, 8, 10)),  # Monday
        (0, date(2026, 8, 9)),  # Sunday
        (3, date(2026, 8, 12)),  # Wednesday — the anchor itself
        (4, date(2026, 8, 6)),  # Thursday — rolls back six days
    ],
)
def test_week_start_honours_the_org_setting(week_starts_on, expected):
    """`week_starts_on` is 0=Sunday..6=Saturday, but Python's weekday() is
    0=Monday. Mixing the two conventions is the classic off-by-one that files
    Sunday's numbers under the wrong week."""
    org = make_org(week_starts_on=week_starts_on)
    period = resolve(org, "week", date(2026, 8, 12))  # a Wednesday
    assert local_date(period.start) == expected


def test_week_is_seven_days():
    org = make_org(week_starts_on=1)
    period = resolve(org, "week", date(2026, 8, 12))
    assert local_date(period.end) - local_date(period.start) == timedelta(days=7)


def test_anchor_on_the_week_start_stays_put():
    """An anchor already on the boundary must not roll back a full week."""
    org = make_org(week_starts_on=1)
    period = resolve(org, "week", date(2026, 8, 10))
    assert local_date(period.start) == date(2026, 8, 10)


# ── Fiscal quarters and years ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("anchor", "expected"),
    [
        (date(2026, 4, 1), "Q1"),  # first day of the fiscal year
        (date(2026, 6, 30), "Q1"),  # last day of Q1
        (date(2026, 7, 1), "Q2"),  # first day of Q2
        (date(2026, 12, 31), "Q3"),
        (date(2027, 1, 1), "Q4"),  # calendar year rolls, fiscal quarter does not
        (date(2027, 3, 31), "Q4"),  # last day of the fiscal year
        (date(2027, 4, 1), "Q1"),  # and around again
    ],
)
def test_fiscal_quarters_when_the_year_starts_in_april(anchor, expected):
    org = make_org(fiscal_year_start_month=4)
    assert resolve(org, "quarter", anchor).label.startswith(expected)


def test_calendar_quarters_when_the_year_starts_in_january():
    org = make_org(fiscal_year_start_month=1)
    assert resolve(org, "quarter", date(2026, 2, 15)).label.startswith("Q1")
    assert resolve(org, "quarter", date(2026, 8, 12)).label.startswith("Q3")


def test_every_quarter_spans_three_months():
    org = make_org(fiscal_year_start_month=4)
    for month in range(1, 13):
        period = resolve(org, "quarter", date(2026, month, 15))
        start, end = local_date(period.start), local_date(period.end)
        months = (end.year - start.year) * 12 + (end.month - start.month)
        assert months == 3, f"month {month} produced a {months}-month quarter"


def test_fiscal_year_label_shows_both_years_only_when_it_straddles():
    assert resolve(make_org(fiscal_year_start_month=4), "year", date(2026, 8, 1)).label == "FY2026/27"
    assert resolve(make_org(fiscal_year_start_month=1), "year", date(2026, 8, 1)).label == "2026"


def test_fiscal_year_before_its_start_month_belongs_to_the_previous_year():
    org = make_org(fiscal_year_start_month=4)
    # March 2027 is inside the fiscal year that began April 2026.
    assert local_date(resolve(org, "year", date(2027, 3, 1)).start) == date(2026, 4, 1)


# ── Half-open contiguity ─────────────────────────────────────────────────────


@pytest.mark.parametrize("period_type", ["day", "week", "month", "quarter", "year"])
def test_end_of_one_period_is_the_start_of_the_next(period_type):
    """The single most important property here.

    A closed interval would count a fact landing exactly on the boundary in
    both periods; a gap would lose it entirely. Only half-open `[start, end)`
    with an exact join does neither.
    """
    org = make_org(fiscal_year_start_month=4)
    period = resolve(org, period_type, date(2026, 8, 12))
    following = resolve(org, period_type, local_date(period.end))
    assert period.end == following.start


@pytest.mark.parametrize("period_type", ["day", "week", "month", "quarter", "year"])
def test_a_year_of_consecutive_periods_never_gaps_or_overlaps(period_type):
    """Walks a full year rather than checking one boundary, so a rule that only
    breaks in December or across a leap day cannot hide."""
    org = make_org(fiscal_year_start_month=4)
    period = resolve(org, period_type, date(2026, 1, 1))
    for _ in range(400 if period_type == "day" else 60):
        following = resolve(org, period_type, local_date(period.end))
        assert period.end == following.start
        assert following.start < following.end
        period = following


# ── Daylight saving ──────────────────────────────────────────────────────────
#
# The proof that boundaries are computed in local time rather than as a fixed
# UTC offset. A naive implementation gives every day exactly 24 hours.


def test_spring_forward_day_is_twenty_three_hours():
    org = make_org()
    period = resolve(org, "day", date(2026, 3, 8))  # US DST begins
    assert period.end - period.start == timedelta(hours=23)


def test_fall_back_day_is_twenty_five_hours():
    org = make_org()
    period = resolve(org, "day", date(2026, 11, 1))  # US DST ends
    assert period.end - period.start == timedelta(hours=25)


def test_a_month_containing_a_dst_change_is_not_a_whole_number_of_days():
    org = make_org()
    march = resolve(org, "month", date(2026, 3, 15))
    assert march.end - march.start == timedelta(days=31, hours=-1)


def test_a_timezone_without_dst_has_uniform_days():
    """Phoenix does not observe DST — the contrast is what shows the 23/25-hour
    results above come from the zone and not from arithmetic."""
    org = make_org(timezone="America/Phoenix")
    for day in (date(2026, 3, 8), date(2026, 11, 1)):
        period = resolve(org, "day", day)
        assert period.end - period.start == timedelta(hours=24)


def test_southern_hemisphere_dst_runs_the_other_way():
    """Sydney's clocks go forward in October, not March. A rule hard-coded to
    the northern calendar passes every test above and fails this one."""
    org = make_org(timezone="Australia/Sydney")
    forward = resolve(org, "day", date(2026, 10, 4))
    assert forward.end - forward.start == timedelta(hours=23)


# ── Custom ranges ────────────────────────────────────────────────────────────


def test_custom_range_includes_its_end_date():
    """Callers mean an inclusive end — "1st to 31st" includes the 31st. Failing
    to add the extra day silently loses the final day of every custom range."""
    org = make_org()
    period = resolve(org, "custom", custom_start=date(2026, 8, 1), custom_end=date(2026, 8, 31))
    assert period.end - period.start == timedelta(days=31)


def test_custom_range_of_a_single_day_is_one_day():
    org = make_org()
    period = resolve(org, "custom", custom_start=date(2026, 8, 5), custom_end=date(2026, 8, 5))
    assert period.end - period.start == timedelta(days=1)


def test_custom_range_requires_both_ends():
    org = make_org()
    with pytest.raises(ValueError, match="both a start and an end"):
        resolve(org, "custom", custom_start=date(2026, 8, 1))


def test_custom_range_rejects_a_reversed_range():
    org = make_org()
    with pytest.raises(ValueError, match="cannot be before"):
        resolve(org, "custom", custom_start=date(2026, 8, 31), custom_end=date(2026, 8, 1))


def test_unknown_period_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown period type"):
        resolve(make_org(), "fortnight", date(2026, 8, 1))


def test_every_declared_period_type_resolves():
    """Guards against PERIOD_TYPES and resolve() drifting apart — a type
    advertised by the API but unhandled would 500 rather than 422."""
    org = make_org()
    for period_type in PERIOD_TYPES:
        kwargs = (
            {"custom_start": date(2026, 8, 1), "custom_end": date(2026, 8, 2)}
            if period_type == "custom"
            else {}
        )
        period = resolve(org, period_type, date(2026, 8, 12), **kwargs)
        assert period.start < period.end
        assert period.label


# ── previous() ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("anchor", "expected"),
    [
        (date(2026, 3, 15), "February 2026"),
        (date(2026, 1, 15), "December 2025"),  # crosses the calendar year
        (date(2026, 3, 31), "February 2026"),  # from a 31-day month into a 28-day one
    ],
)
def test_previous_month(anchor, expected):
    org = make_org()
    assert previous(org, resolve(org, "month", anchor)).label == expected


def test_previous_quarter_crosses_the_fiscal_year():
    org = make_org(fiscal_year_start_month=4)
    assert previous(org, resolve(org, "quarter", date(2026, 4, 5))).label == "Q4 FY2025/26"


@pytest.mark.parametrize("period_type", ["day", "week", "month", "quarter", "year"])
def test_previous_ends_exactly_where_the_current_period_starts(period_type):
    """The same contiguity rule, approached from the other direction — which is
    what makes "vs last month" comparisons trustworthy."""
    org = make_org(fiscal_year_start_month=4)
    period = resolve(org, period_type, date(2026, 8, 12))
    assert previous(org, period).end == period.start


def test_previous_of_a_custom_period_is_refused():
    """There is no defined predecessor to an arbitrary range, and inventing one
    would silently compare against a window the user never asked for."""
    org = make_org()
    period = resolve(org, "custom", custom_start=date(2026, 8, 1), custom_end=date(2026, 8, 7))
    with pytest.raises(ValueError, match="no defined predecessor"):
        previous(org, period)


def test_previous_across_a_dst_boundary_still_joins_exactly():
    """Stepping back by a fixed 30 days would drift by an hour here."""
    org = make_org()
    april = resolve(org, "month", date(2026, 4, 15))
    march = previous(org, april)
    assert march.end == april.start
    assert march.label == "March 2026"


# ── Rolling windows ──────────────────────────────────────────────────────────
#
# For leaderboards. A calendar-month board resets to near-empty on the 1st,
# which is demotivating and useless for the first several days of every month.


@pytest.mark.parametrize(("period_type", "days"), [("rolling_7", 7), ("rolling_30", 30)])
def test_a_rolling_window_covers_exactly_its_length(period_type, days):
    org = make_org()
    period = resolve(org, period_type, date(2026, 8, 12))
    assert period.end - period.start == timedelta(days=days)


def test_a_rolling_window_includes_today():
    """A board that ignores what happened this morning is not a board anyone
    checks. Every other period type counts a day only once it is over."""
    org = make_org()
    period = resolve(org, "rolling_7", date(2026, 8, 12))
    assert local_date(period.end) == date(2026, 8, 13)  # exclusive end = tomorrow


def test_a_rolling_window_is_never_empty_at_a_month_boundary():
    """The whole reason it exists. On the 1st, a calendar month covers one day
    and a rolling window still covers seven."""
    org = make_org()
    calendar = resolve(org, "month", date(2026, 9, 1))
    rolling = resolve(org, "rolling_7", date(2026, 9, 1))
    assert rolling.start < calendar.start


def test_the_previous_rolling_window_does_not_overlap():
    """Stepping back one day and re-resolving — which is right for calendar
    periods — would give a window overlapping this one by six days out of
    seven, so a movement comparison would measure almost the same days against
    themselves and report nobody moving."""
    org = make_org()
    period = resolve(org, "rolling_7", date(2026, 8, 12))
    earlier = previous(org, period)
    assert earlier.end == period.start
    assert earlier.end - earlier.start == timedelta(days=7)


def test_rolling_windows_are_labelled_plainly():
    org = make_org()
    assert resolve(org, "rolling_7", date(2026, 8, 12)).label == "Last 7 days"
    assert resolve(org, "rolling_30", date(2026, 8, 12)).label == "Last 30 days"


# ── Saying a date to people ──────────────────────────────────────────────────


def test_an_evening_end_is_that_evenings_date_not_utcs():
    """QA-14: 7pm on 2 October in New York is already the 3rd in UTC."""
    from datetime import UTC, datetime

    from app.periods import last_day

    assert last_day(make_org(), datetime(2026, 10, 2, 23, 0, tzinfo=UTC)) == date(2026, 10, 2)


def test_ending_at_local_midnight_is_the_day_before():
    """Over before anybody arrives, so that day is not one it runs on. Midnight
    in New York is 04:00 UTC in summer and 05:00 in winter."""
    from datetime import UTC, datetime

    from app.periods import last_day

    org = make_org()
    assert last_day(org, datetime(2026, 8, 16, 4, 0, tzinfo=UTC)) == date(2026, 8, 15)
    assert last_day(org, datetime(2026, 12, 16, 5, 0, tzinfo=UTC)) == date(2026, 12, 15)
