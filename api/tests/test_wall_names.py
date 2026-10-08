"""How names are written on a wall.

**`first_initial` is a privacy setting, not a typographic one.** It exists so a
wall can hang where customers walk past, which means it has to be applied on
the server: trimming the string in a browser has still sent every surname to a
television whose address bar is visible in the room, and to anyone who
photographs it.

It also has to be applied in *one* place. A screen careful about surnames on
the leaderboard and careless about them in the celebration that takes over the
top of it is not careful at all.
"""

import pytest

from tests.conftest import within_this_month
from app.models import Office

WHEN = within_this_month()


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    phoenix = Office(organization_id=org.id, name="Phoenix")
    db.add(phoenix)
    db.flush()

    enterprise = make_team("Enterprise")
    enterprise.office_id = phoenix.id
    db.flush()

    return {
        "phoenix": phoenix,
        "enterprise": enterprise,
        "admin": make_user("admin", name="Admin"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", enterprise, name="Clark Kent"),
        "metric": make_metric("calls_made"),
    }


def make_channel(client, **overrides):
    reply = client.post("/api/channels", json={"name": "Lobby", **overrides})
    assert reply.status_code == 201, reply.json()
    return reply.json()


def make_board(client, world, name="Calls", **overrides):
    reply = client.post(
        "/api/leaderboards",
        json={
            "name": name,
            "metric_id": world["metric"].id,
            "period_type": "month",
            "visibility": "org",
            **overrides,
        },
    )
    assert reply.status_code == 201, reply.json()
    return reply.json()["id"]


def add(client, channel_id, **payload):
    return client.post(f"/api/channels/{channel_id}/screens", json=payload)


def wall(client, channel_id):
    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel_id}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    return client.get(f"/api/display/{token}").json()


def set_names(client, style, on="organization", channel_id=None):
    if on == "organization":
        reply = client.patch(
            "/api/organization", json={"appearance": {"name_display": style}}
        )
    else:
        reply = client.patch(
            f"/api/channels/{channel_id}",
            json={"name": "Lobby", "appearance": {"name_display": style}},
        )
    assert reply.status_code == 200, reply.json()


def test_full_names_by_default(client, db, org, world, sign_in, make_fact):
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 10, WHEN)
    db.commit()
    channel = make_channel(client)
    add(client, channel["id"], kind="leaderboard", leaderboard_id=make_board(client, world))

    slide = wall(client, channel["id"])["slides"][0]

    assert slide["entries"][0]["entity_name"] == "Peter Parker"


def test_a_lobby_wall_can_drop_the_surname(client, db, org, world, sign_in, make_fact):
    """The whole reason the setting exists."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 10, WHEN)
    db.commit()
    set_names(client, "first_initial")
    channel = make_channel(client)
    add(client, channel["id"], kind="leaderboard", leaderboard_id=make_board(client, world))

    slide = wall(client, channel["id"])["slides"][0]

    assert slide["entries"][0]["entity_name"] == "Peter P."


def test_the_surname_never_leaves_the_building(
    client, db, org, world, sign_in, make_fact
):
    """**The property, stated as a property.** Not "the screen displays an
    initial" — the full name is not in the response at all, so photographing
    the wall or reading its address bar gives nothing up."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 10, WHEN)
    db.commit()
    set_names(client, "first_initial")
    channel = make_channel(client)
    add(client, channel["id"], kind="leaderboard", leaderboard_id=make_board(client, world))

    body = wall(client, channel["id"])

    assert "Parker" not in str(body)


def test_a_team_name_is_never_trimmed(client, db, org, world, sign_in, make_fact):
    """"Enterprise" becoming "E." is a bug wearing a privacy setting's
    clothes."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 10, WHEN)
    db.commit()
    set_names(client, "first")
    channel = make_channel(client)
    board = make_board(client, world, entity_type="team")
    add(client, channel["id"], kind="leaderboard", leaderboard_id=board)

    slide = wall(client, channel["id"])["slides"][0]

    assert slide["entries"][0]["entity_name"] == "Enterprise"


def test_a_channel_can_be_stricter_than_the_organization(
    client, db, org, world, sign_in, make_fact
):
    """The lobby screen is one channel, not the whole company."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 10, WHEN)
    db.commit()
    channel = make_channel(client)
    set_names(client, "first_initial", on="channel", channel_id=channel["id"])
    add(client, channel["id"], kind="leaderboard", leaderboard_id=make_board(client, world))

    slide = wall(client, channel["id"])["slides"][0]

    assert slide["entries"][0]["entity_name"] == "Peter P."


def test_a_spotlight_follows_it_everywhere_on_the_screen(
    client, db, org, world, sign_in, make_fact
):
    """A caption reading "Peter P." under a heading reading "Peter Parker"
    publishes exactly what the setting exists to withhold."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 10, WHEN)
    db.commit()
    set_names(client, "first_initial")
    channel = make_channel(client)
    add(client, channel["id"], kind="spotlight", leaderboard_id=make_board(client, world))

    slide = wall(client, channel["id"])["slides"][0]

    assert slide["person"]["name"] == "Peter P."
    assert slide["title"] == "Peter P."


def test_a_title_somebody_typed_is_left_alone(
    client, db, org, world, sign_in, make_fact
):
    """"Rep of the month" must not become "Rep"."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 10, WHEN)
    db.commit()
    set_names(client, "first")
    channel = make_channel(client)
    add(
        client,
        channel["id"],
        kind="spotlight",
        title="Rep of the month",
        leaderboard_id=make_board(client, world),
    )

    slide = wall(client, channel["id"])["slides"][0]

    assert slide["title"] == "Rep of the month"
    assert slide["person"]["name"] == "Peter"


def test_every_panel_of_a_comparison_obeys_it(
    client, db, org, world, sign_in, make_fact, make_metric
):
    sign_in(world["admin"])
    deals = make_metric("deals_closed")
    make_fact(world["metric"], world["peter"], 10, WHEN)
    make_fact(deals, world["peter"], 3, WHEN)
    db.commit()
    set_names(client, "first_initial")
    channel = make_channel(client)
    calls = make_board(client, world, "Calls")
    other = client.post(
        "/api/leaderboards",
        json={
            "name": "Deals",
            "metric_id": deals.id,
            "period_type": "month",
            "visibility": "org",
        },
    ).json()["id"]
    add(client, channel["id"], kind="comparison", leaderboard_ids=[calls, other])

    slide = wall(client, channel["id"])["slides"][0]

    for panel in slide["panels"]:
        assert panel["entries"][0]["entity_name"] == "Peter P."


def test_recent_wins_obey_it_too(client, db, org, world, sign_in):
    from app.models import Notification

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
    set_names(client, "first_initial")
    channel = make_channel(client)
    add(client, channel["id"], kind="achievements")

    slide = wall(client, channel["id"])["slides"][0]

    assert slide["achievements"][0]["about_name"] == "Peter P."


def test_the_celebration_over_the_top_obeys_it(client, db, org, world, sign_in):
    """**The case the docstring warns about.** A wall careful on the
    leaderboard and careless in the banner that interrupts it is not careful."""
    from app.models import Notification

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
    set_names(client, "first_initial")
    channel = make_channel(client)

    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel["id"]}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    body = client.get(f"/api/display/{token}/celebrations").json()

    assert body["celebrations"], body
    assert body["celebrations"][0]["about_name"] == "Peter P."
