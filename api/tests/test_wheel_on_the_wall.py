"""A prize-wheel win, on the wall.

Only a win is announced — a miss never is, for the same reason falling behind
on a goal stays off the wall: it is read by whoever walks past, and it is
nobody else's business. And a win is luck rather than work, so a screen set to
"important only" leaves it out.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import channels as channel_service, points, wheel
from app.models import Channel, Notification, WheelPrize
from tests.test_spending import Always


@pytest.fixture
def world(db, org, make_user):
    return {"peter": make_user("agent", name="Peter Parker")}


def set_up(db, org, world):
    points.award(
        db, org=org, user_id=world["peter"].id, points=1000, event_key="goal.achieved",
        subject_type="goal", subject_id=1, reason="Hit a goal",
    )
    settings = wheel.settings_for(db, org.id)
    settings.spin_cost, settings.enabled = 100, True
    for label, kind, pts in (("Long lunch", "prize", 0), ("+50", "points", 50), ("So close", "nothing", 0)):
        db.add(WheelPrize(organization_id=org.id, label=label, kind=kind, points=pts, weight=1))
    db.flush()


def announced(db):
    return db.scalars(select(Notification).where(Notification.event_key == "wheel.won")).all()


def test_a_real_prize_is_announced(db, org, world):
    set_up(db, org, world)

    wheel.spin(db, org, world["peter"].id, rng=Always("Long lunch"))

    [row] = announced(db)
    assert (row.title, row.about_name) == ("Won Long lunch", "Peter Parker")


def test_points_are_announced_as_points(db, org, world):
    set_up(db, org, world)

    wheel.spin(db, org, world["peter"].id, rng=Always("+50"))

    assert announced(db)[0].title == "Won 50 points"


def test_a_miss_is_never_announced(db, org, world):
    """**The property worth guarding.** "Peter spun and got nothing" is true,
    and nobody else's business."""
    set_up(db, org, world)

    wheel.spin(db, org, world["peter"].id, rng=Always("So close"))

    assert announced(db) == []


def test_it_plays_on_a_wall_as_the_prize_wheel(db, org, world):
    set_up(db, org, world)
    channel = Channel(organization_id=org.id, name="Floor")
    db.add(channel)
    db.flush()

    wheel.spin(db, org, world["peter"].id, rng=Always("Long lunch"))
    found = channel_service.celebrations(db, org, channel)

    assert [(c.occasion, c.event_key) for c in found] == [("Prize wheel", "wheel.won")]


def test_a_quiet_wall_leaves_it_out(db, org, world):
    """Luck rather than work, so "important only" does not interrupt for it."""
    set_up(db, org, world)
    channel = Channel(organization_id=org.id, name="Lobby", appearance={"milestones": "important"})
    db.add(channel)
    db.flush()

    wheel.spin(db, org, world["peter"].id, rng=Always("Long lunch"))

    assert channel_service.celebrations(db, org, channel) == []


def test_it_brings_no_walk_up_music(db, org, world):
    """Spins can come thick and fast; the wheel is the moment."""
    set_up(db, org, world)

    wheel.spin(db, org, world["peter"].id, rng=Always("Long lunch"))

    assert announced(db)[0].media_url is None
