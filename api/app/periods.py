"""Turning "this month" into two exact timestamps.

Every number this product shows is a sum over a time window, so the boundaries
of that window decide every figure downstream. Getting them wrong doesn't raise
an error — it silently reports a different number, which is the worst kind of
bug because nobody can tell it happened.

Three rules hold everywhere:

**Windows are half-open: [start, end).** The end of one period is exactly the
start of the next. A closed interval would count anything landing on the
boundary twice; a gap would lose it. Half-open is the only option that does
neither, and it is why the code never writes `<= end`.

**Boundaries are computed in the ORGANIZATION's timezone**, not the server's
and not the viewer's. A daily leaderboard has to mean the same thing to an
agent in Phoenix and their manager in New York, or two people looking at the
same screen see different numbers.

**Quarters and years are fiscal**, driven by the organization's
`fiscal_year_start_month`. A company whose year starts in April has a Q1 that
runs April–June, and reporting January–March as "Q1" would be wrong for them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import Organization

PERIOD_TYPES = (
    "day",
    "week",
    "month",
    "quarter",
    "year",
    "rolling_7",
    "rolling_30",
    "custom",
)

# Rolling windows and how many days each covers.
#
# They exist for leaderboards. A calendar-month board resets to near-empty on
# the 1st, which is demotivating and useless for the first several days of
# every month — the boards people look at most are exactly the ones a calendar
# boundary damages most. A rolling window is always populated.
#
# Unlike every other period, a rolling one INCLUDES today. A board that ignores
# what happened this morning is not a board anyone checks.
ROLLING_DAYS = {"rolling_7": 7, "rolling_30": 30}

#: Above this many days, a period is bucketed monthly rather than daily.
#: A quarter (~92 days) stays daily; a year becomes twelve points.
MONTHLY_ABOVE_DAYS = 100

_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


@dataclass(frozen=True)
class Period:
    """A resolved window. `start` and `end` are UTC instants; `end` is exclusive."""

    type: str
    start: datetime
    end: datetime
    label: str


def tz(org: Organization) -> ZoneInfo:
    """The organization's timezone. Every boundary in this product uses it."""
    return ZoneInfo(org.timezone)


#: The old private spelling, still used throughout this module.
_tz = tz


def today(org: Organization) -> date:
    """The current date where the organization is, not where the server is."""
    return datetime.now(tz(org)).date()


def local_date(org: Organization, at: datetime) -> date:
    """The organization's date at an instant. Stored times are UTC, and an
    evening in New York is already tomorrow there."""
    return at.astimezone(tz(org)).date()


def last_day(org: Organization, ends_at: datetime) -> date:
    """The last of the organization's days that something ending at `ends_at`
    runs on.

    **Midnight closes the day before.** A contest that ends at 00:00 on the
    3rd is over before anybody arrives on the 3rd, so saying it "runs until
    3 October" promises a day it does not have.
    """
    local = ends_at.astimezone(tz(org))
    if local.time() == time(0):
        return local.date() - timedelta(days=1)
    return local.date()


def _to_utc(local_date: date, tz: ZoneInfo) -> datetime:
    """Local midnight on `local_date`, as a UTC instant.

    Building the aware datetime directly rather than localising a naive one:
    ZoneInfo resolves the offset for that wall time, including the days a DST
    change makes 23 or 25 hours long.

    On the rare days where local midnight does not exist (some zones skip it at
    a DST start), Python picks a defined instant rather than raising. That is
    acceptable here because *every* boundary goes through this same function —
    so one period's end is still bit-for-bit the next period's start, and no
    fact can fall in a gap or be counted twice.
    """
    return datetime(
        local_date.year, local_date.month, local_date.day, tzinfo=tz
    ).astimezone(UTC)


def _week_start(day: date, week_starts_on: int) -> date:
    """Roll back to the most recent `week_starts_on`.

    `week_starts_on` is 0=Sunday..6=Saturday, matching the organization setting
    and JavaScript's `getDay()`. Python's `weekday()` is 0=Monday, so it is
    converted first — mixing the two conventions is the classic off-by-one that
    puts Sunday's numbers in the wrong week.
    """
    sunday_based = (day.weekday() + 1) % 7
    return day - timedelta(days=(sunday_based - week_starts_on) % 7)


def _add_months(day: date, months: int) -> date:
    """Advance by whole months, clamped to day 1 — only used on month starts."""
    index = (day.year * 12 + day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _fiscal_year_start(day: date, start_month: int) -> date:
    """The first day of the fiscal year containing `day`."""
    year = day.year if day.month >= start_month else day.year - 1
    return date(year, start_month, 1)


def resolve(
    org: Organization,
    period_type: str,
    anchor: date | None = None,
    *,
    custom_start: date | None = None,
    custom_end: date | None = None,
) -> Period:
    """Resolve a period type and an anchor date into UTC bounds.

    `anchor` is any date inside the wanted period — "the month containing the
    15th", not "the month starting on the 15th". Callers pass today for the
    current period and any date in the past for a historical one, without
    needing to know where the boundaries fall.
    """
    tz = _tz(org)
    today = datetime.now(tz).date()
    anchor = anchor or today

    if period_type == "day":
        start = anchor
        end = anchor + timedelta(days=1)
        label = anchor.strftime("%d %b %Y")

    elif period_type == "week":
        start = _week_start(anchor, org.week_starts_on)
        end = start + timedelta(days=7)
        label = f"Week of {start.strftime('%d %b %Y')}"

    elif period_type == "month":
        start = anchor.replace(day=1)
        end = _add_months(start, 1)
        label = f"{_MONTH_NAMES[start.month - 1]} {start.year}"

    elif period_type == "quarter":
        fy_start = _fiscal_year_start(anchor, org.fiscal_year_start_month)
        # Months elapsed since the fiscal year began, floored to a quarter.
        elapsed = (anchor.year - fy_start.year) * 12 + (anchor.month - fy_start.month)
        start = _add_months(fy_start, (elapsed // 3) * 3)
        end = _add_months(start, 3)
        label = f"Q{elapsed // 3 + 1} {_fiscal_label(fy_start, org)}"

    elif period_type == "year":
        start = _fiscal_year_start(anchor, org.fiscal_year_start_month)
        end = _add_months(start, 12)
        label = _fiscal_label(start, org)

    elif period_type in ROLLING_DAYS:
        days = ROLLING_DAYS[period_type]
        # Ends at the start of tomorrow, so today counts in full.
        end = anchor + timedelta(days=1)
        start = end - timedelta(days=days)
        label = f"Last {days} days"

    elif period_type == "custom":
        if custom_start is None or custom_end is None:
            raise ValueError("A custom period needs both a start and an end date.")
        if custom_end < custom_start:
            raise ValueError("The end date cannot be before the start date.")
        start = custom_start
        # The caller means an INCLUSIVE end date — "1st to 31st" includes the
        # 31st — so a day is added to reach the exclusive boundary. Omitting
        # this is how a custom range silently loses its final day.
        end = custom_end + timedelta(days=1)
        label = f"{start.strftime('%d %b')} – {custom_end.strftime('%d %b %Y')}"

    else:
        raise ValueError(f"Unknown period type: {period_type}")

    return Period(type=period_type, start=_to_utc(start, tz), end=_to_utc(end, tz), label=label)


def bucket_unit(period: Period) -> str:
    """How finely to slice a period for plotting.

    Chosen from the span rather than the period type, so a custom range gets a
    sensible answer without a special case — and so the rule is one line
    somebody can check rather than a table they have to trust.

    **Only days and months.** The obvious missing unit is a week, and it is
    missing on purpose: Postgres `date_trunc('week', …)` always starts weeks on
    Monday, while an organization can set `week_starts_on` to Sunday. A weekly
    bucket would then disagree with every weekly period in the product, and it
    would disagree silently — the chart would look fine and be shifted by a
    day. Days and months are unambiguous in every timezone and every locale.

    Hours are absent for the same reason and one more: a single-day period has
    no shape worth drawing, and hourly boundaries drift in half-hour-offset
    zones and on daylight-saving days. A chart of one day is a number.
    """
    return "day" if (period.end - period.start).days <= MONTHLY_ABOVE_DAYS else "month"



def bucket_starts(org: Organization, period: Period) -> list[datetime]:
    """Every bucket boundary in the period, as UTC instants.

    Generated here rather than by Postgres `generate_series`, because the step
    has to be a *local* day or month: an organization's day is 23 or 25 hours
    long twice a year, and adding a fixed interval walks off the boundary from
    the DST change onward. Stepping through local dates and converting each one
    through the same `_to_utc` every other boundary uses cannot drift.

    Generating the full list is what makes empty buckets appear. A query alone
    returns only the buckets that had facts, and a chart that silently omits
    the quiet days shows a different shape from the real one — it compresses
    the gaps out, which is precisely the information a trend is being read for.

    With monthly buckets the first boundary can fall *before* `period.start` —
    a custom range beginning on the 10th is bucketed from the 1st. That is
    deliberate: it is the bucket those facts belong to, and pretending the
    month began on the 10th would mislabel it.
    """
    tz = _tz(org)
    start_local = period.start.astimezone(tz).date()
    end_local = period.end.astimezone(tz).date()

    starts: list[datetime] = []
    if bucket_unit(period) == "day":
        day = start_local
        while day < end_local:
            starts.append(_to_utc(day, tz))
            day += timedelta(days=1)
    else:
        month = start_local.replace(day=1)
        while month < end_local:
            starts.append(_to_utc(month, tz))
            month = _add_months(month, 1)
    return starts


def _fiscal_label(fy_start: date, org: Organization) -> str:
    """"2026" for a calendar year, "FY2026/27" when the year straddles two."""
    if org.fiscal_year_start_month == 1:
        return str(fy_start.year)
    return f"FY{fy_start.year}/{str(fy_start.year + 1)[-2:]}"


def previous(org: Organization, period: Period) -> Period:
    """The period immediately before this one, for "vs last month" comparisons.

    Derived by stepping back from the start rather than by subtracting a fixed
    duration: months are 28–31 days long and DST makes some days 23 or 25
    hours, so "start minus 30 days" drifts. Landing one day before the start
    and re-resolving always lands inside the correct previous period.
    """
    if period.type == "custom":
        raise ValueError("A custom period has no defined predecessor.")

    tz = _tz(org)

    if period.type in ROLLING_DAYS:
        # Shifted back by a whole window, not by one day.
        #
        # Re-resolving from "the day before the start" would give a window
        # overlapping this one by all but a day, so a movement comparison would
        # be measuring almost the same days against themselves and report
        # nobody moving.
        days = ROLLING_DAYS[period.type]
        end_local = period.end.astimezone(tz).date() - timedelta(days=days)
        return resolve(org, period.type, end_local - timedelta(days=1))

    day_before = (period.start.astimezone(tz) - timedelta(days=1)).date()
    return resolve(org, period.type, day_before)
