"""Am I ahead or behind for this point in the period?

Progress alone cannot answer that. "40% of target" is excellent on the 3rd of
the month and alarming on the 28th, and a number that means opposite things
depending on the date is a number nobody acts on.

Two decisions shape everything here.

**Elapsed time is counted in WORKING DAYS, not calendar days.**

A month goal checked on Monday morning has had two calendar days pass since
Friday and zero selling days. Calendar pacing would tell every agent they had
fallen behind over the weekend, every weekend — and a pace marker that cries
wolf on a fixed schedule gets ignored within a fortnight, taking the honest
warnings with it.

**Except for a short window, which is counted in working HOURS** (7.2). A
sprint from 9am to 5pm, or a goal for today, is over before a single working
day can be counted — whole days made the sprint "100% gone" the moment it
began and today's goal "not started" until it was over. Under two days,
elapsed time is the working hours (09:00–18:00, weekdays) gone out of those in
the window — or plain clock time, for a window wholly out of hours.

**Pace only applies to metrics that accumulate.**

`sum` and `count` grow through a period, so "half the time gone, half the
target reached" is meaningful. An `avg` does not: a response time averaging
2 minutes on the 10th is not "a third of the way" to anything, and projecting
it linearly would produce nonsense. For those, elapsed time is still reported —
it is a fact about the calendar — but no expectation and no projection is
offered, because there is no honest one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.periods import Period

# Aggregations whose value grows monotonically through a period. Only these can
# be paced or projected.
CUMULATIVE = ("sum", "count")

# How far from the expected line still counts as on track, in percentage
# points. Without a band, a goal flickers between "ahead" and "behind" on every
# recorded fact, which reads as instability rather than information.
TOLERANCE = 5.0

# Statuses, worst to best, so a caller can sort by urgency.
MISSED = "missed"
BEHIND = "behind"
ON_TRACK = "on_track"
AHEAD = "ahead"
HIT = "hit"
NOT_STARTED = "not_started"


@dataclass
class Pace:
    """Where the period is, and where the number should be by now."""

    elapsed_percent: float
    #: None when the metric does not accumulate — see the module docstring.
    expected_percent: float | None
    #: Where this lands if the current rate holds. None for the same reason.
    projected: Decimal | None
    status: str

    @property
    def needs_attention(self) -> bool:
        return self.status in (BEHIND, MISSED)


def working_days(start: date, end: date) -> int:
    """Weekdays in [start, end).

    Monday to Friday, with no holiday calendar. That is an assumption, not a
    fact about any particular company — a deployment whose team works Sunday to
    Thursday would be paced wrongly, and public holidays count as working days
    here. Both are worth making configurable once someone has a real calendar
    to configure it against; inventing the schema now would be guessing at the
    shape of a problem nobody has reported.
    """
    if end <= start:
        return 0

    total_days = (end - start).days
    whole_weeks, remainder = divmod(total_days, 7)
    count = whole_weeks * 5

    # Walk only the leftover days, so a five-year custom range costs the same
    # as a one-week one.
    for offset in range(remainder):
        if (start + timedelta(days=offset)).weekday() < 5:
            count += 1
    return count


#: The working day a short window is measured in. See the module docstring.
WORK_START = time(9)
WORK_END = time(18)

#: Shorter than this, a window is measured in working hours, not days.
SHORT_WINDOW = timedelta(days=2)


def working_seconds(start: datetime, end: datetime, tz: ZoneInfo) -> float:
    """Working time (09:00–18:00, weekdays, local) between two instants."""
    if end <= start:
        return 0.0
    total = 0.0
    day = start.astimezone(tz).date()
    last = end.astimezone(tz).date()
    while day <= last:
        if day.weekday() < 5:
            opens = datetime.combine(day, WORK_START, tz)
            closes = datetime.combine(day, WORK_END, tz)
            overlap = min(closes, end) - max(opens, start)
            total += max(0.0, overlap.total_seconds())
        day += timedelta(days=1)
    return total


def elapsed_fraction(period: Period, now: datetime, timezone: str) -> float:
    """How much of the period's working time has passed, 0-1.

    Measured in the organization's timezone, like every other period
    calculation — an agent in Phoenix and their manager in New York must see
    the same pace for the same goal.
    """
    tz = ZoneInfo(timezone)
    if now >= period.end:
        return 1.0
    if now <= period.start:
        return 0.0

    if period.end - period.start < SHORT_WINDOW:
        # A sprint, or today: in working hours (7.2).
        total = working_seconds(period.start, period.end, tz)
        if total <= 0:
            # Wholly out of hours — an evening sprint, a weekend day — so the
            # clock is the only measure there is.
            return (now - period.start) / (period.end - period.start)
        return min(working_seconds(period.start, now, tz) / total, 1.0)

    start = period.start.astimezone(tz).date()
    end_local = period.end.astimezone(tz)
    # A window ending partway through a day — a contest closing at 5pm on
    # Friday — has that day to work in, so it counts (7.2). One ending at
    # midnight does not reach into the next.
    end = end_local.date() + (timedelta(days=1) if end_local.time() != time(0) else timedelta(0))
    today = now.astimezone(tz).date()

    if today <= start:
        return 0.0

    total = working_days(start, end)
    if total == 0:
        # A custom range covering only a weekend. It has no working time to be
        # partway through, so it is either over or not started — and `today` is
        # inside it, so treat it as fully elapsed rather than dividing by zero.
        return 1.0

    # `today` is counted as elapsed only once it is over, so a goal is not
    # reported as behind at 9am for work the day still has time to produce.
    return min(working_days(start, today) / total, 1.0)


def compute(
    *,
    period: Period,
    now: datetime,
    timezone: str,
    aggregation: str,
    percent: float,
    attained: bool,
    current: Decimal,
) -> Pace:
    elapsed = elapsed_fraction(period, now, timezone)
    elapsed_percent = round(elapsed * 100, 1)

    if aggregation not in CUMULATIVE:
        # Elapsed time is still a fact worth showing; an expectation is not.
        return Pace(
            elapsed_percent=elapsed_percent,
            expected_percent=None,
            projected=None,
            status=HIT if attained else (MISSED if elapsed >= 1.0 else ON_TRACK),
        )

    expected_percent = round(elapsed * 100, 1)

    projected: Decimal | None = None
    # Not once it is over: "on pace for" a finished period is a projection of
    # something that already happened (Q2-13). Nor from nothing: "on pace for
    # $0.00" is a sum, not a forecast.
    if 0 < elapsed < 1 and current > 0:
        # Straight-line extrapolation of the rate so far. Quantised to whole
        # units: presenting "on pace for 183.4729 calls" implies a precision
        # this estimate does not have.
        projected = (current / Decimal(str(elapsed))).quantize(Decimal("1"))

    if attained:
        status = HIT
    elif elapsed >= 1.0:
        # The period is over and the target was not reached. Nothing about this
        # is "behind" any more — it did not happen.
        status = MISSED
    elif elapsed <= 0.0:
        status = NOT_STARTED
    elif percent >= expected_percent + TOLERANCE:
        status = AHEAD
    elif percent < expected_percent - TOLERANCE:
        status = BEHIND
    elif percent <= 0:
        # **Nothing at all is not "on track"** (Q2-10). Inside the band early
        # in a period — a working day gone, $0 of $250,000 — the tolerance
        # would call it on track, which reads as reassurance about a number
        # that has not moved.
        status = NOT_STARTED
    else:
        status = ON_TRACK

    return Pace(
        elapsed_percent=elapsed_percent,
        expected_percent=expected_percent,
        projected=projected,
        status=status,
    )
