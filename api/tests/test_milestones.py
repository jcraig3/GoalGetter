"""How much a wall interrupts itself.

**One control with three answers, because three intentions actually exist:**
leave the rotation alone, stop for the big ones, stop for everything. A
checkbox per event type would be seven things to reason about on a page about
how a television looks.

The room decides, not the event — which is why this resolves through the
appearance chain like everything else a wall draws.
"""

import pytest

from app import events
from app.models import Notification


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    db.flush()
    return {
        "enterprise": enterprise,
        "admin": make_user("admin", name="Admin"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "metric": make_metric("calls_made"),
    }


def win(db, org, world, event_key: str, title: str = "Well done"):
    db.add(
        Notification(
            organization_id=org.id,
            user_id=world["peter"].id,
            event_key=event_key,
            subject_type="goal",
            subject_id=abs(hash(event_key)) % 10_000,
            title=title,
            about_name="Peter Parker",
            about_user_id=world["peter"].id,
        )
    )


def celebrations(client, channel_id):
    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel_id}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    return client.get(f"/api/display/{token}/celebrations").json()["celebrations"]


# -- Which events are which --------------------------------------------------


def test_nothing_interrupts_a_wall_set_to_none():
    for key in ("goal.achieved", "competition.won", "recognition", "achievement:7"):
        assert not events.interrupts(key, "none"), key


def test_important_means_contests_and_targets():
    assert events.interrupts("competition.won", "important")
    assert events.interrupts("goal.achieved", "important")


def test_important_leaves_out_the_ones_that_can_repeat():
    """**An admin can write a rule that fires on every closed deal.** A takeover
    every few minutes is how a takeover teaches people to ignore takeovers, so
    rules and shout-outs belong to a choice somebody made for that room."""
    assert not events.interrupts("achievement:7", "important")
    assert not events.interrupts("recognition", "important")


def test_all_means_all_of_them():
    for key in ("goal.achieved", "competition.won", "recognition", "achievement:7"):
        assert events.interrupts(key, "all"), key


def test_a_private_event_never_interrupts_at_any_level():
    """`public` is permission and `celebrate` is significance, and neither
    implies the other. Falling behind on a goal must never reach a screen read
    by whoever walks past."""
    for level in events.MILESTONE_LEVELS:
        assert not events.interrupts("goal.period_ending", level), level
        assert not events.interrupts("data_source.failing", level), level


def test_an_unknown_event_key_interrupts_nothing():
    """An older wall and a newer server. Silence is the safe direction."""
    for level in events.MILESTONE_LEVELS:
        assert not events.interrupts("something.new", level), level


# -- Through the chain, to a screen ------------------------------------------


def test_a_wall_celebrates_everything_by_default(client, db, org, world, sign_in):
    """Which is what it did before this was a setting."""
    sign_in(world["admin"])
    win(db, org, world, "recognition", "Nice work on that renewal")
    db.commit()
    channel = client.post("/api/channels", json={"name": "Floor"}).json()

    assert len(celebrations(client, channel["id"])) == 1


def test_a_quiet_wall_celebrates_nothing(client, db, org, world, sign_in):
    sign_in(world["admin"])
    win(db, org, world, "competition.won", "Won the sprint")
    db.commit()
    channel = client.post("/api/channels", json={"name": "Support"}).json()
    client.patch(
        f"/api/channels/{channel['id']}",
        json={"name": "Support", "appearance": {"milestones": "none"}},
    )

    assert celebrations(client, channel["id"]) == []


def test_one_wall_can_be_stricter_than_the_rest(client, db, org, world, sign_in):
    """**The point of putting it on the channel.** The reception screen is one
    wall, not the whole company."""
    sign_in(world["admin"])
    win(db, org, world, "competition.won", "Won the sprint")
    win(db, org, world, "recognition", "Nice work on that renewal")
    db.commit()

    floor = client.post("/api/channels", json={"name": "Floor"}).json()
    lobby = client.post("/api/channels", json={"name": "Lobby"}).json()
    client.patch(
        f"/api/channels/{lobby['id']}",
        json={"name": "Lobby", "appearance": {"milestones": "important"}},
    )

    assert len(celebrations(client, floor["id"])) == 2

    # A second display needs a session to create, and the helper clears it.
    sign_in(world["admin"])
    shown = celebrations(client, lobby["id"])
    assert [c["title"] for c in shown] == ["Won the sprint"]


def test_the_organization_sets_the_default(client, db, org, world, sign_in):
    sign_in(world["admin"])
    win(db, org, world, "recognition", "Nice work on that renewal")
    db.commit()
    client.patch(
        "/api/organization", json={"appearance": {"milestones": "important"}}
    )
    channel = client.post("/api/channels", json={"name": "Floor"}).json()

    assert celebrations(client, channel["id"]) == []


def test_a_channel_can_be_louder_than_the_organization(
    client, db, org, world, sign_in
):
    """Inheritance goes both ways: the sales floor opts back in to everything
    while the rest of the building stays quiet."""
    sign_in(world["admin"])
    win(db, org, world, "recognition", "Nice work on that renewal")
    db.commit()
    client.patch(
        "/api/organization", json={"appearance": {"milestones": "important"}}
    )
    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    client.patch(
        f"/api/channels/{channel['id']}",
        json={"name": "Floor", "appearance": {"milestones": "all"}},
    )

    assert len(celebrations(client, channel["id"])) == 1


def test_a_level_nobody_defined_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = client.patch(
        "/api/organization", json={"appearance": {"milestones": "sometimes"}}
    )

    assert reply.status_code == 422
