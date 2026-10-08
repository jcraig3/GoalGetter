"""Each item's own background, on the screen that shows it.

The rule as the product owner put it: the Appearance tab sets the default, and
every leaderboard, goal and competition can have a background of its own —
which is what its screen shows.

That needed one change. Appearance resolves organization -> item -> channel ->
screen, so the room's say on names and privacy beats an item's styling. Applied
to backgrounds too, it meant a channel with a background painted over every
item on it. A background is the item's identity rather than the room's, so for
the background alone the item now beats the channel.

Read the way a television reads it: through a display token, with no session.
"""

import pytest


@pytest.fixture
def world(db, org, make_user, make_metric):
    return {"admin": make_user("admin", name="Admin"), "metric": make_metric("calls_made")}


def solid(colour):
    return {"background": {"kind": "solid", "color": colour}}


def board(client, world, appearance=None, name="Calls"):
    reply = client.post(
        "/api/leaderboards",
        json={
            "name": name, "metric_id": world["metric"].id, "period_type": "month",
            "visibility": "org", **({"appearance": appearance} if appearance else {}),
        },
    )
    assert reply.status_code == 201, reply.json()
    return reply.json()["id"]


def wall(client, *, channel_appearance=None, screens):
    channel = client.post(
        "/api/channels",
        json={"name": "Floor", **({"appearance": channel_appearance} if channel_appearance else {})},
    ).json()
    for screen in screens:
        reply = client.post(f"/api/channels/{channel['id']}/screens", json=screen)
        assert reply.status_code == 201, reply.json()
    display = client.post("/api/displays", json={"name": "TV", "channel_id": channel["id"]}).json()
    token = display["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    return client.get(f"/api/display/{token}").json()["slides"]


def colour_of(slide):
    return slide["appearance"]["background"].get("color")


def test_the_appearance_tab_sets_the_default(client, db, world, sign_in):
    sign_in(world["admin"])
    client.patch("/api/organization", json={"appearance": solid("#111111")})
    plain = board(client, world)

    slides = wall(client, screens=[{"kind": "leaderboard", "leaderboard_id": plain}])

    assert colour_of(slides[0]) == "#111111"


def test_an_item_shows_its_own_background(client, db, world, sign_in):
    sign_in(world["admin"])
    client.patch("/api/organization", json={"appearance": solid("#111111")})
    themed = board(client, world, solid("#aa0000"))

    slides = wall(client, screens=[{"kind": "leaderboard", "leaderboard_id": themed}])

    assert colour_of(slides[0]) == "#aa0000"


def test_an_item_beats_the_channel_it_is_on(client, db, world, sign_in):
    """**The change.** A channel's background used to paint over every item on
    it; now it is the default for the ones that have not chosen their own."""
    sign_in(world["admin"])
    themed = board(client, world, solid("#aa0000"), name="Themed")
    plain = board(client, world, name="Plain")

    slides = wall(
        client,
        channel_appearance=solid("#0000aa"),
        screens=[
            {"kind": "leaderboard", "leaderboard_id": themed},
            {"kind": "leaderboard", "leaderboard_id": plain},
        ],
    )

    assert [colour_of(s) for s in slides] == ["#aa0000", "#0000aa"]


def test_two_items_on_one_channel_each_keep_their_own(client, db, world, sign_in):
    sign_in(world["admin"])
    red = board(client, world, solid("#aa0000"), name="Red")
    green = board(client, world, solid("#00aa00"), name="Green")

    slides = wall(
        client,
        screens=[
            {"kind": "leaderboard", "leaderboard_id": red},
            {"kind": "leaderboard", "leaderboard_id": green},
        ],
    )

    assert [colour_of(s) for s in slides] == ["#aa0000", "#00aa00"]


def test_a_screen_can_still_override_its_item(client, db, world, sign_in):
    """An explicit choice for this one screen on this one wall is the most
    specific thing there is, so it still wins."""
    sign_in(world["admin"])
    themed = board(client, world, solid("#aa0000"))

    slides = wall(
        client,
        screens=[{
            "kind": "leaderboard", "leaderboard_id": themed,
            "appearance": solid("#00aaaa"),
        }],
    )

    assert colour_of(slides[0]) == "#00aaaa"


def test_the_room_still_wins_everything_else(client, db, world, sign_in):
    """Only the background changed order. A lobby channel asking for initials
    still beats an item that did not — that rule is about privacy, and privacy
    belongs to the room."""
    sign_in(world["admin"])
    themed = board(client, world, {"name_display": "full", **solid("#aa0000")})

    slides = wall(
        client,
        channel_appearance={"name_display": "first_initial"},
        screens=[{"kind": "leaderboard", "leaderboard_id": themed}],
    )

    assert slides[0]["appearance"]["name_display"] == "first_initial"
    assert colour_of(slides[0]) == "#aa0000"
