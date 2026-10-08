"""Which day a birthday or a work anniversary is marked on.

**Not always the day itself, which is the whole of the module.** A birthday on
a Sunday marked on the Sunday is marked to an empty office: the wall plays to
nobody and the notification is read on Monday with the date already past.

Every case here is a date somebody would otherwise wait a year to find out
about.
"""

from datetime import date

from app import occasions


# -- Where a date lands ------------------------------------------------------


def test_an_ordinary_date_is_itself():
    assert occasions.falls_on(6, 14, 2026) == date(2026, 6, 14)


def test_a_leap_day_lands_on_the_28th_in_a_common_year():
    """**Somebody born on a leap day has a birthday every year.** The calendar
    is what is inconvenient, and marking it the day before is what every office
    already does."""
    assert occasions.falls_on(2, 29, 2027) == date(2027, 2, 28)


def test_a_leap_day_is_itself_in_a_leap_year():
    assert occasions.falls_on(2, 29, 2028) == date(2028, 2, 29)


def test_a_day_that_never_exists_is_nothing():
    """The 31st of a thirty-day month. The CHECK allows it and nothing should
    have written it, so the answer is None rather than a guess."""
    assert occasions.falls_on(4, 31, 2026) is None


def test_a_month_that_is_not_a_month_is_nothing():
    assert occasions.falls_on(13, 1, 2026) is None


# -- The weekend rule --------------------------------------------------------


def test_a_weekday_is_marked_on_the_day():
    # 2026-06-15 is a Monday.
    assert occasions.marked_on(6, 15, 2026) == date(2026, 6, 15)


def test_a_saturday_moves_to_the_friday_before():
    # 2026-06-13 is a Saturday.
    assert occasions.marked_on(6, 13, 2026) == date(2026, 6, 12)


def test_a_sunday_moves_to_the_friday_before():
    """**Before, not after.** A greeting that arrives late reads as an
    afterthought, and everybody in the room can do the arithmetic."""
    # 2026-06-14 is a Sunday.
    assert occasions.marked_on(6, 14, 2026) == date(2026, 6, 12)


def test_a_friday_stays_where_it_is():
    # 2026-06-12 is a Friday.
    assert occasions.marked_on(6, 12, 2026) == date(2026, 6, 12)


def test_a_weekend_at_the_start_of_a_month_moves_into_the_one_before():
    """1 August 2026 is a Saturday, so it is marked on 31 July."""
    assert occasions.marked_on(8, 1, 2026) == date(2026, 7, 31)


def test_a_weekend_at_the_start_of_a_year_moves_into_the_one_before():
    """The case that catches arithmetic doing its own month subtraction.
    1 January 2028 is a Saturday."""
    assert occasions.marked_on(1, 1, 2028) == date(2027, 12, 31)


def test_a_leap_day_that_lands_on_a_weekend_moves_too():
    """Both rules at once, which is where an ordering mistake hides.
    29 February 2032 is a Sunday."""
    assert occasions.marked_on(2, 29, 2032) == date(2032, 2, 27)


# -- Counting years ----------------------------------------------------------


def test_the_first_anniversary_is_a_year_later():
    assert occasions.years_since(date(2025, 3, 1), date(2026, 3, 1)) == 1


def test_the_day_before_is_still_the_year_before():
    """Counted by the calendar rather than by 365 days: dividing by 365.25 gets
    this wrong in either direction depending on which leap years fell in
    between."""
    assert occasions.years_since(date(2025, 3, 1), date(2026, 2, 28)) == 0


def test_somebody_who_started_today_has_done_none():
    assert occasions.years_since(date(2026, 3, 1), date(2026, 3, 1)) == 0


def test_a_start_date_in_the_future_is_not_negative():
    """A typo in an import should not put "-2 years" on a wall."""
    assert occasions.years_since(date(2030, 1, 1), date(2026, 1, 1)) == 0


def test_a_leap_day_start_counts_from_the_28th():
    """Somebody who joined on 29 February 2024 has done one year on
    28 February 2025, which is the day their anniversary is marked."""
    assert occasions.years_since(date(2024, 2, 29), date(2025, 2, 28)) == 0
    assert occasions.years_since(date(2024, 2, 29), date(2025, 3, 1)) == 1
