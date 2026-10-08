"""What people actually call somebody.

**A setting that had been offered and inert since 4c.** The Appearance tab
lists "Their nickname" as a way to write names on a wall, and there was nothing
behind it — choosing it silently fell back to the full name. The same class of
thing as the light theme that was written and unreachable.

So most of this file is about the wall: storing a nickname is easy, and the
point was never the column.
"""

import pytest

from tests.conftest import within_this_month
from app.models import Notification

WHEN = within_this_month()


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    db.flush()
    return {
        "enterprise": enterprise,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", enterprise, name="Clark Kent"),
        "metric": make_metric("calls_made"),
    }


def set_nickname(client, user, nickname):
    return client.patch(
        f"/api/users/{user.id}/profile", json={"nickname": nickname}
    )


def make_board(client, world, **overrides):
    reply = client.post(
        "/api/leaderboards",
        json={
            "name": "Calls",
            "metric_id": world["metric"].id,
            "period_type": "month",
            "visibility": "org",
            **overrides,
        },
    )
    assert reply.status_code == 201, reply.json()
    return reply.json()["id"]


def wall(client, channel_id):
    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel_id}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    return client.get(f"/api/display/{token}").json()


# -- Setting one -------------------------------------------------------------


def test_somebody_can_set_their_own(client, db, world, sign_in):
    sign_in(world["peter"])

    reply = set_nickname(client, world["peter"], "Spidey")

    assert reply.status_code == 200, reply.json()
    assert reply.json()["nickname"] == "Spidey"


def test_a_manager_can_set_it_for_somebody(client, db, world, sign_in):
    """**Most people here will never sign in.** The accounts exist because a
    directory sync created them, so "they can set their own" is not an answer
    for the majority — the same reasoning that widened photographs."""
    sign_in(world["manager"])

    assert set_nickname(client, world["peter"], "Spidey").status_code == 200


def test_an_agent_cannot_set_somebody_elses(client, db, world, sign_in):
    """Which is where the prank would be."""
    sign_in(world["clark"])

    reply = set_nickname(client, world["peter"], "Smelly")

    assert reply.status_code == 403
    # The endpoint carries a birthday too now, so the refusal names the whole
    # rather than one of its fields.
    assert "details" in reply.json()["detail"]


def test_an_empty_nickname_clears_it(client, db, world, sign_in):
    sign_in(world["peter"])
    set_nickname(client, world["peter"], "Spidey")

    assert set_nickname(client, world["peter"], "").json()["nickname"] == ""


def test_spaces_are_not_a_nickname(client, db, world, sign_in):
    """Otherwise a wall set to nicknames would draw a blank where a name was."""
    sign_in(world["peter"])

    assert set_nickname(client, world["peter"], "   ").json()["nickname"] == ""


def test_a_nickname_longer_than_a_nickname_is_refused(client, db, world, sign_in):
    """It is what a floor shouts across a room, not a second biography."""
    sign_in(world["peter"])

    assert set_nickname(client, world["peter"], "x" * 80).status_code == 422


# -- On a wall, which is the point -------------------------------------------


@pytest.fixture
def board_on_a_wall(client, db, org, world, sign_in, make_fact):
    def build():
        sign_in(world["admin"])
        make_fact(world["metric"], world["peter"], 40, WHEN)
        db.commit()
        channel = client.post("/api/channels", json={"name": "Floor"}).json()
        client.post(
            f"/api/channels/{channel['id']}/screens",
            json={"kind": "leaderboard", "leaderboard_id": make_board(client, world)},
        )
        client.patch(
            "/api/organization", json={"appearance": {"name_display": "nickname"}}
        )
        return channel["id"]

    return build


def test_a_wall_set_to_nicknames_uses_them(
    client, db, world, sign_in, board_on_a_wall
):
    """The whole reason the column exists."""
    channel = board_on_a_wall()
    sign_in(world["admin"])
    set_nickname(client, world["peter"], "Spidey")

    slide = wall(client, channel)["slides"][0]

    assert slide["entries"][0]["entity_name"] == "Spidey"


def test_somebody_without_one_keeps_their_name(
    client, db, world, sign_in, board_on_a_wall
):
    """**Falling back is the honest answer, not a blank.** Most people will
    never set one, and a board of empty cells is worse than a board of names."""
    channel = board_on_a_wall()

    slide = wall(client, channel)["slides"][0]

    assert slide["entries"][0]["entity_name"] == "Peter Parker"


def test_a_spotlight_uses_it_too(client, db, org, world, sign_in, make_fact):
    """One place, like every other name rule — a screen that used a nickname on
    the board and a full name on the spotlight beside it is two products."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 40, WHEN)
    db.commit()
    set_nickname(client, world["peter"], "Spidey")
    client.patch(
        "/api/organization", json={"appearance": {"name_display": "nickname"}}
    )
    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    client.post(
        f"/api/channels/{channel['id']}/screens",
        json={"kind": "spotlight", "leaderboard_id": make_board(client, world)},
    )

    slide = wall(client, channel["id"])["slides"][0]

    assert slide["person"]["name"] == "Spidey"
    assert slide["title"] == "Spidey"


def test_recent_wins_use_it(client, db, org, world, sign_in):
    sign_in(world["admin"])
    db.add(
        Notification(
            organization_id=org.id,
            user_id=world["peter"].id,
            event_key="goal.achieved",
            subject_type="goal",
            subject_id=1,
            title="Calls achieved",
            about_name="Peter Parker",
            about_user_id=world["peter"].id,
        )
    )
    db.commit()
    set_nickname(client, world["peter"], "Spidey")
    client.patch(
        "/api/organization", json={"appearance": {"name_display": "nickname"}}
    )
    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    client.post(
        f"/api/channels/{channel['id']}/screens", json={"kind": "achievements"}
    )

    slide = wall(client, channel["id"])["slides"][0]

    assert slide["achievements"][0]["about_name"] == "Spidey"


def test_the_celebration_over_the_top_uses_it(client, db, org, world, sign_in):
    """The case the `display_name` docstring has warned about since 4c: a wall
    careful on the leaderboard and careless in the banner that interrupts it is
    not careful at all."""
    sign_in(world["admin"])
    db.add(
        Notification(
            organization_id=org.id,
            user_id=world["peter"].id,
            event_key="goal.achieved",
            subject_type="goal",
            subject_id=1,
            title="Calls achieved",
            about_name="Peter Parker",
            about_user_id=world["peter"].id,
        )
    )
    db.commit()
    set_nickname(client, world["peter"], "Spidey")
    client.patch(
        "/api/organization", json={"appearance": {"name_display": "nickname"}}
    )
    channel = client.post("/api/channels", json={"name": "Floor"}).json()

    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel["id"]}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    body = client.get(f"/api/display/{token}/celebrations").json()

    assert body["celebrations"][0]["about_name"] == "Spidey"


def test_a_team_never_gets_one(client, db, org, world, sign_in, make_fact):
    """A team has no nickname, and looking one up by a team id would find
    whichever person happens to share that number."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 40, WHEN)
    db.commit()
    client.patch(
        "/api/organization", json={"appearance": {"name_display": "nickname"}}
    )
    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    client.post(
        f"/api/channels/{channel['id']}/screens",
        json={
            "kind": "leaderboard",
            "leaderboard_id": make_board(client, world, entity_type="team"),
        },
    )

    slide = wall(client, channel["id"])["slides"][0]

    assert slide["entries"][0]["entity_name"] == "Enterprise"


def test_another_style_ignores_nicknames_entirely(
    client, db, world, sign_in, board_on_a_wall
):
    """And queries for none. `first_initial` is a transformation of the name
    already in hand, so a wall asking for it looks nothing up."""
    channel = board_on_a_wall()
    sign_in(world["admin"])
    set_nickname(client, world["peter"], "Spidey")
    client.patch(
        "/api/organization", json={"appearance": {"name_display": "first_initial"}}
    )

    slide = wall(client, channel)["slides"][0]

    assert slide["entries"][0]["entity_name"] == "Peter P."
