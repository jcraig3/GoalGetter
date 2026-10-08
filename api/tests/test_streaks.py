"""Days in a row with a number on the board.

**A streak is the one statistic on a spotlight that is about the person rather
than about the period.** "Fourteenth this month" resets on the first and says
nothing about effort; "nine days running" survives the reset, which is why it
is the number people chase.

Every test passes `today` explicitly. A streak is the kind of thing that works
in the afternoon and breaks at midnight, and a test that reads the clock would
only ever catch that by being run at the wrong moment.
"""

from datetime import UTC, date, datetime, timedelta

import pytest

from app import streaks

#: A fixed "today", so nothing here depends on when it runs.
TODAY = date(2026, 9, 25)


def at(day: date, hour: int = 12) -> datetime:
    """That hour on that day, New York time, as an instant.

    New York because that is the organization in `conftest`, and the whole
    point of these tests is that the day is decided where the company is.
    """
    from zoneinfo import ZoneInfo

    return datetime(
        day.year, day.month, day.day, hour, tzinfo=ZoneInfo("America/New_York")
    )


@pytest.fixture
def person(make_user):
    return make_user("agent", name="Peter Parker")


@pytest.fixture
def metric(make_metric):
    return make_metric("calls_made")


def count(db, org, metric, person, today=TODAY) -> int:
    return streaks.current(
        db, org, metric_id=metric.id, user_id=person.id, today=today
    )


def test_nobody_with_no_numbers_has_a_streak(db, org, metric, person):
    assert count(db, org, metric, person) == 0


def test_one_day_is_a_streak_of_one(db, org, metric, person, make_fact):
    make_fact(metric, person, 5, at(TODAY))
    db.flush()

    assert count(db, org, metric, person) == 1


def test_consecutive_days_add_up(db, org, metric, person, make_fact):
    for back in range(4):
        make_fact(metric, person, 5, at(TODAY - timedelta(days=back)))
    db.flush()

    assert count(db, org, metric, person) == 4


def test_yesterday_still_counts_as_current(db, org, metric, person, make_fact):
    """**And it has to.** Numbers arrive during the day — at nine in the
    morning nobody has today's yet — so requiring today would reset every
    streak in the building overnight and restore it by lunch."""
    make_fact(metric, person, 5, at(TODAY - timedelta(days=1)))
    make_fact(metric, person, 5, at(TODAY - timedelta(days=2)))
    db.flush()

    assert count(db, org, metric, person) == 2


def test_the_day_before_yesterday_does_not(db, org, metric, person, make_fact):
    """The honest answer is that the streak is over, not merely paused."""
    make_fact(metric, person, 5, at(TODAY - timedelta(days=2)))
    make_fact(metric, person, 5, at(TODAY - timedelta(days=3)))
    db.flush()

    assert count(db, org, metric, person) == 0


def test_a_gap_stops_the_count_where_it_falls(db, org, metric, person, make_fact):
    for back in (0, 1, 3, 4, 5):
        make_fact(metric, person, 5, at(TODAY - timedelta(days=back)))
    db.flush()

    assert count(db, org, metric, person) == 2


def test_several_numbers_in_one_day_are_still_one_day(
    db, org, metric, person, make_fact
):
    """A streak counts days, not rows. Twenty calls on Monday is one Monday."""
    for hour in (9, 11, 16):
        make_fact(metric, person, 5, at(TODAY, hour))
    db.flush()

    assert count(db, org, metric, person) == 1


def test_somebody_elses_days_do_not_count(db, org, metric, person, make_fact, make_user):
    other = make_user("agent", name="Clark Kent")
    make_fact(metric, other, 5, at(TODAY))
    make_fact(metric, other, 5, at(TODAY - timedelta(days=1)))
    db.flush()

    assert count(db, org, metric, person) == 0


def test_another_metric_does_not_count(
    db, org, metric, person, make_fact, make_metric
):
    """A streak is per metric. Calling every day is not the same as selling
    every day, and one standing in for the other would be a number that reads
    as effort and is not."""
    other = make_metric("deals_closed")
    make_fact(other, person, 5, at(TODAY))
    db.flush()

    assert count(db, org, metric, person) == 0


def test_the_day_is_decided_where_the_company_is(db, org, metric, person, make_fact):
    """A call logged at 9pm in New York is Thursday's, not Friday's.

    Stored in UTC that instant falls on the next date, so a naive
    implementation counts it against the wrong day and breaks the streak it
    should have extended.
    """
    late = at(TODAY - timedelta(days=1), 21)
    # Nine in the evening on the 24th in New York is one in the morning on the
    # 25th in UTC. The assertion is the setup, not the point: without it a
    # later change to the fixture's timezone would make this test pass for the
    # wrong reason.
    assert late.astimezone(UTC).date() == date(2026, 9, 25)

    make_fact(metric, person, 5, late)
    make_fact(metric, person, 5, at(TODAY - timedelta(days=2)))
    db.flush()

    # Both fall on the 23rd and 24th locally, so the streak ends yesterday and
    # is two days long. Counted by UTC date it would read as one.
    assert count(db, org, metric, person) == 2


def test_a_streak_longer_than_the_lookback_is_capped_not_wrong(
    db, org, metric, person, make_fact
):
    """The cap bounds the scan so a wall refreshing every thirty seconds
    cannot turn into a table sweep. Past a year the number means the same
    thing anyway."""
    for back in range(streaks.LOOKBACK_DAYS + 10):
        make_fact(metric, person, 5, at(TODAY - timedelta(days=back)))
    db.flush()

    assert count(db, org, metric, person) == streaks.LOOKBACK_DAYS + 1
