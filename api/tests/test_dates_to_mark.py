"""Birthdays and work anniversaries, end to end.

`test_occasions.py` covers which day a date lands on. This covers what happens
on that day: who is told, what it says, and — the part worth guarding — that it
happens exactly once a year however the weekend rule moves it about.
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app import notifications
from app.models import Notification

#: A Monday, so nothing in here is accidentally testing the weekend rule.
MONDAY = datetime(2026, 6, 15, 12, tzinfo=UTC)


@pytest.fixture
def world(db, org, make_team, make_user):
    enterprise = make_team("Enterprise")
    db.flush()
    return {
        "admin": make_user("admin", name="Admin"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", enterprise, name="Clark Kent"),
    }


def marked(db, event_key: str) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification).where(Notification.event_key == event_key)
        ).all()
    )


# -- Birthdays ---------------------------------------------------------------


def test_a_birthday_today_is_marked(db, org, world):
    world["peter"].birthday_month = 6
    world["peter"].birthday_day = 15
    db.flush()

    notifications.detect_occasions(db, now=MONDAY)

    rows = marked(db, "person.birthday")
    assert len(rows) == 1
    assert rows[0].about_name == "Peter Parker"
    assert rows[0].title == "Happy birthday"


def test_a_birthday_on_another_day_is_not(db, org, world):
    world["peter"].birthday_month = 6
    world["peter"].birthday_day = 16
    db.flush()

    notifications.detect_occasions(db, now=MONDAY)

    assert marked(db, "person.birthday") == []


def test_nobody_is_marked_twice_in_a_year(db, org, world):
    """The sweep runs on a loop that can restart, so the second pass has to be
    silent rather than merely harmless."""
    world["peter"].birthday_month = 6
    world["peter"].birthday_day = 15
    db.flush()

    notifications.detect_occasions(db, now=MONDAY)
    notifications.detect_occasions(db, now=MONDAY)

    assert len(marked(db, "person.birthday")) == 1


def test_the_weekend_rule_does_not_let_it_fire_twice(db, org, world):
    """**Anchored on the year, not on the day it is marked.** A birthday moved
    off a weekend lands on a different date in different years, and anchoring
    on that date would let the same birthday fire again the moment the rule
    shifted it."""
    # 2026-06-14 is a Sunday, marked on Friday the 12th.
    world["peter"].birthday_month = 6
    world["peter"].birthday_day = 14
    db.flush()
    friday = datetime(2026, 6, 12, 12, tzinfo=UTC)

    notifications.detect_occasions(db, now=friday)
    # The actual day, which the rule moved away from.
    notifications.detect_occasions(db, now=datetime(2026, 6, 14, 12, tzinfo=UTC))

    assert len(marked(db, "person.birthday")) == 1


def test_it_comes_round_again_the_next_year(db, org, world):
    world["peter"].birthday_month = 6
    world["peter"].birthday_day = 15
    db.flush()

    notifications.detect_occasions(db, now=MONDAY)
    # 2027-06-15 is a Tuesday.
    notifications.detect_occasions(db, now=datetime(2027, 6, 15, 12, tzinfo=UTC))

    assert len(marked(db, "person.birthday")) == 2


def test_somebody_hidden_is_not_marked(db, org, world):
    """A hidden person is off every board by definition, and a birthday
    announcement is the loudest board there is."""
    world["peter"].birthday_month = 6
    world["peter"].birthday_day = 15
    world["peter"].hidden_at = datetime.now(UTC)
    db.flush()

    notifications.detect_occasions(db, now=MONDAY)

    assert marked(db, "person.birthday") == []


def test_nobody_with_no_birthday_set_is_considered(db, org, world):
    """Which is almost everybody, and the reason the query filters rather than
    walking the roster."""
    report = notifications.detect_occasions(db, now=MONDAY)

    assert report.people == 0


# -- Work anniversaries ------------------------------------------------------


def test_an_anniversary_says_how_many_years(db, org, world):
    world["peter"].started_on = date(2023, 6, 15)
    db.flush()

    notifications.detect_occasions(db, now=MONDAY)

    rows = marked(db, "person.work_anniversary")
    assert len(rows) == 1
    assert rows[0].title == "3 years today"


def test_one_year_is_singular(db, org, world):
    """"1 years today" is the kind of thing a room reads out loud."""
    world["peter"].started_on = date(2025, 6, 15)
    db.flush()

    notifications.detect_occasions(db, now=MONDAY)

    assert marked(db, "person.work_anniversary")[0].title == "1 year today"


def test_the_first_day_is_not_an_anniversary(db, org, world):
    """**"Zero years today" is a sentence about somebody's first morning**, and
    they have enough happening."""
    world["peter"].started_on = date(2026, 6, 15)
    db.flush()

    notifications.detect_occasions(db, now=MONDAY)

    assert marked(db, "person.work_anniversary") == []


def test_a_birthday_and_an_anniversary_on_one_day_are_two_things(db, org, world):
    world["peter"].birthday_month = 6
    world["peter"].birthday_day = 15
    world["peter"].started_on = date(2024, 6, 15)
    db.flush()

    notifications.detect_occasions(db, now=MONDAY)

    assert len(marked(db, "person.birthday")) == 1
    assert len(marked(db, "person.work_anniversary")) == 1


# -- What a wall does with them ----------------------------------------------


def test_both_can_be_shown_to_a_room(db, org, world):
    """A birthday on a wall is normal in an office. Being behind on a goal is
    not, which is what `public` is for."""
    from app import events

    assert events.is_public("person.birthday")
    assert events.is_public("person.work_anniversary")


def test_neither_outranks_a_win_somebody_earned(db, org, world):
    """**The one public event nobody earned.** A reception screen set to
    "important only" wants contest wins, and a birthday is not one."""
    from app import events

    assert not events.interrupts("person.birthday", "important")
    assert events.interrupts("person.birthday", "all")


# -- Setting them ------------------------------------------------------------


def test_somebody_can_set_their_own_birthday(client, db, world, sign_in):
    sign_in(world["peter"])

    reply = client.patch(
        f"/api/users/{world['peter'].id}/profile",
        json={"birthday_month": 6, "birthday_day": 15},
    )

    assert reply.status_code == 200, reply.json()
    assert reply.json()["birthday_month"] == 6


def test_half_a_birthday_is_refused(client, db, world, sign_in):
    """A month with no day is a date nothing can mark."""
    sign_in(world["peter"])

    reply = client.patch(
        f"/api/users/{world['peter'].id}/profile", json={"birthday_month": 6}
    )

    assert reply.status_code == 422
    assert "both" in reply.json()["detail"]


def test_a_day_that_is_not_a_day_is_refused(client, db, world, sign_in):
    sign_in(world["peter"])

    reply = client.patch(
        f"/api/users/{world['peter'].id}/profile",
        json={"birthday_month": 6, "birthday_day": 40},
    )

    assert reply.status_code == 422


def test_an_agent_cannot_set_their_own_start_date(client, db, world, sign_in):
    """**The split is the point.** A birthday is theirs; a start date is a
    company fact about when somebody joined, and an agent inventing their own
    would be a number on a wall nobody checked."""
    sign_in(world["peter"])

    reply = client.patch(
        f"/api/users/{world['peter'].id}", json={"started_on": "2020-01-01"}
    )

    assert reply.status_code == 403


def test_an_admin_can_set_a_start_date(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = client.patch(
        f"/api/users/{world['peter'].id}", json={"started_on": "2023-06-15"}
    )

    assert reply.status_code == 200, reply.json()
    assert reply.json()["started_on"] == "2023-06-15"
