"""Which day a birthday or a work anniversary is marked on.

**Not always the day itself, which is the whole of this module.** A birthday on
a Sunday marked on the Sunday is marked to an empty office — the wall plays to
nobody and the notification is read on Monday with the date already past. So a
weekend date moves to the Friday before it.

**Before, not after.** A greeting that arrives late reads as an afterthought,
and a wall saying "happy birthday" on Monday about Saturday is worse than one
saying it on Friday about Sunday. Everybody in the room can do the arithmetic;
nobody enjoys being remembered a day late.

Pure and dateless in its inputs, so the awkward cases — a leap-day birthday, a
December-into-January weekend — can be asserted rather than waited for.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

__all__ = ["falls_on", "marked_on", "years_since", "SATURDAY", "SUNDAY"]

SATURDAY = 5
SUNDAY = 6


def falls_on(month: int, day: int, year: int) -> date | None:
    """The date this month-and-day lands on in a given year.

    **29 February lands on the 28th in a common year**, rather than being
    skipped. Somebody born on a leap day has a birthday every year; the
    calendar is what is inconvenient, and the answer every office already uses
    is to mark it the day before.

    Returns None for a day that never exists — the 31st of a thirty-day month —
    which the CHECK on the column allows and nothing should have written.
    """
    if not 1 <= month <= 12:
        return None

    last = calendar.monthrange(year, month)[1]
    if day == 29 and month == 2:
        return date(year, 2, last)
    if day > last:
        return None
    return date(year, month, day)


def marked_on(month: int, day: int, year: int) -> date | None:
    """The day it is actually celebrated, after the weekend rule.

    Saturday and Sunday both move to the Friday before. Monday would be the
    other choice and is the wrong one: see the note at the top.
    """
    actual = falls_on(month, day, year)
    if actual is None:
        return None
    if actual.weekday() == SATURDAY:
        return actual - timedelta(days=1)
    if actual.weekday() == SUNDAY:
        return actual - timedelta(days=2)
    return actual


def years_since(started: date, on: date) -> int:
    """Completed years between two dates, by the calendar rather than by 365.

    Somebody who joined on 1 March 2023 has done two years on 1 March 2025, and
    dividing days by 365.25 gets that wrong in either direction depending on
    which leap years fell in between.
    """
    years = on.year - started.year
    if (on.month, on.day) < (started.month, started.day):
        years -= 1
    return max(years, 0)
