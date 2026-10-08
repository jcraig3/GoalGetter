"""What reaches a television, and from which layer.

**The bug this file exists because of:** the whole appearance system — storage,
validation, four-layer inheritance, an editor, a live preview — shipped before
anything on a wall read most of it. Everything below is an assertion that a
setting arrives at the screen, because "it is in the model" and "it works" had
quietly become different statements.

The chain, and the order it resolves in:

    organization -> item -> channel -> screen
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
        "metric": make_metric("calls_made"),
    }


def make_channel(client, **overrides):
    reply = client.post("/api/channels", json={"name": "Main", **overrides})
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


def wall(client, channel_id):
    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel_id}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    return client.get(f"/api/display/{token}").json()


@pytest.fixture
def board_on_a_wall(client, db, org, world, sign_in, make_fact):
    """One leaderboard on one channel, with somebody on it."""

    def build(**screen):
        sign_in(world["admin"])
        make_fact(world["metric"], world["peter"], 10, WHEN)
        db.commit()
        channel = make_channel(client)
        board = make_board(client, world)
        client.post(
            f"/api/channels/{channel['id']}/screens",
            json={"kind": "leaderboard", "leaderboard_id": board, **screen},
        )
        return {"channel": channel["id"], "board": board}

    return build


# -- Everything the wall is sent ---------------------------------------------


def test_a_slide_arrives_with_every_field_filled(client, board_on_a_wall):
    """**`resolve` returns something complete**, so a renderer never has to ask
    "and what if this one is null?". A missing field is a wall drawing a
    default it was never told about."""
    built = board_on_a_wall()

    appearance = wall(client, built["channel"])["slides"][0]["appearance"]

    for field in (
        "primary",
        "secondary",
        "accent",
        "font",
        "font_scale",
        "panel_opacity",
        "panel_blur",
        "panel_radius",
        "ranked_layout",
        "goal_layout",
        "row_count",
        "show_values",
        "name_display",
        "end_time_format",
        "background",
    ):
        assert field in appearance, field


def test_the_brand_reaches_the_television(client, board_on_a_wall):
    """It did not, for a phase: the colour was applied by the app shell and by
    the preview, and a wall painted the built-in indigo."""
    built = board_on_a_wall()
    client.patch("/api/organization", json={"appearance": {"primary": "#ff0000"}})

    assert wall(client, built["channel"])["slides"][0]["appearance"]["primary"] == (
        "#ff0000"
    )


def test_the_slogan_and_the_logo_reach_it_too(client, board_on_a_wall):
    built = board_on_a_wall()
    client.patch(
        "/api/organization",
        json={"appearance": {"slogan": "Always be closing", "logo": "abc123"}},
    )

    appearance = wall(client, built["channel"])["slides"][0]["appearance"]
    assert appearance["slogan"] == "Always be closing"
    assert appearance["logo"] == "abc123"


def test_a_background_reaches_it_whole(client, board_on_a_wall):
    """Every part of it, not just the kind: an image with no digest and no
    dimming is a photograph nobody can read text over."""
    built = board_on_a_wall()
    client.patch(
        "/api/organization",
        json={
            "appearance": {
                "background": {
                    "kind": "image",
                    "asset": "abc123",
                    "dim": 0.5,
                    "blur": 8,
                }
            }
        },
    )

    background = wall(client, built["channel"])["slides"][0]["appearance"]["background"]
    assert background["kind"] == "image"
    assert background["asset"] == "abc123"
    assert background["dim"] == 0.5
    assert background["blur"] == 8


# -- Which layer wins --------------------------------------------------------


def test_a_channel_overrides_the_organization(client, board_on_a_wall):
    built = board_on_a_wall()
    client.patch("/api/organization", json={"appearance": {"row_count": 20}})
    client.patch(
        f"/api/channels/{built['channel']}",
        json={"name": "Main", "appearance": {"row_count": 5}},
    )

    assert wall(client, built["channel"])["slides"][0]["appearance"]["row_count"] == 5


def test_a_screen_has_the_last_word(client, board_on_a_wall):
    built = board_on_a_wall()
    client.patch(
        f"/api/channels/{built['channel']}",
        json={"name": "Main", "appearance": {"ranked_layout": "podium"}},
    )
    screens = client.get("/api/channels").json()[0]["screens"]
    client.patch(
        f"/api/channels/{built['channel']}/screens/{screens[0]['id']}",
        json={
            "kind": "leaderboard",
            "leaderboard_id": built["board"],
            "appearance": {"ranked_layout": "list"},
        },
    )

    assert wall(client, built["channel"])["slides"][0]["appearance"][
        "ranked_layout"
    ] == "list"


def test_a_channel_beats_the_board_it_shows(client, board_on_a_wall):
    """**A venue's concerns beat a thing's own identity.** "This TV is in a
    lobby, show initials only" has to win over "this board is themed red"."""
    built = board_on_a_wall()
    client.patch(
        f"/api/leaderboards/{built['board']}",
        json={"appearance": {"name_display": "full", "primary": "#ff0000"}},
    )
    client.patch(
        f"/api/channels/{built['channel']}",
        json={"name": "Main", "appearance": {"name_display": "first_initial"}},
    )

    appearance = wall(client, built["channel"])["slides"][0]["appearance"]
    assert appearance["name_display"] == "first_initial"
    # And the board keeps the part the room had no opinion about.
    assert appearance["primary"] == "#ff0000"


def test_a_layer_that_says_nothing_changes_nothing(client, board_on_a_wall):
    built = board_on_a_wall()
    client.patch("/api/organization", json={"appearance": {"primary": "#ff0000"}})
    client.patch(
        f"/api/channels/{built['channel']}", json={"name": "Main", "appearance": {}}
    )

    assert wall(client, built["channel"])["slides"][0]["appearance"]["primary"] == (
        "#ff0000"
    )


# -- Refusals ----------------------------------------------------------------


def test_a_row_count_nobody_could_read_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = client.patch(
        "/api/organization", json={"appearance": {"row_count": 400}}
    )

    assert reply.status_code == 422


def test_video_became_a_kind_once_the_file_could_be_checked(
    client, db, world, sign_in
):
    """**This was a tripwire, and it went off on purpose in 4k.** It refused
    `video` because a kind that validates, saves and then draws nothing was the
    failure 4e-iii spent a day undoing. That guarantee now lives at upload —
    `app/video.py` refuses every file a television would silently fail to play,
    HEVC from an iPhone included — so the kind is allowed, and this test says
    so instead of being deleted."""
    sign_in(world["admin"])

    reply = client.patch(
        "/api/organization",
        json={"appearance": {"background": {"kind": "video", "asset": "a" * 64}}},
    )

    assert reply.status_code == 200, reply.json()
    assert reply.json()["appearance"]["background"]["kind"] == "video"


def test_a_background_kind_that_does_not_exist_is_still_refused(
    client, db, world, sign_in
):
    """The tripwire's other half, which still holds: a kind with nothing
    behind it is refused rather than stored."""
    sign_in(world["admin"])

    reply = client.patch(
        "/api/organization",
        json={"appearance": {"background": {"kind": "hologram"}}},
    )

    assert reply.status_code == 422


def test_an_unknown_key_is_dropped_rather_than_carried(client, db, world, sign_in):
    """The database cannot validate JSON, so this module does — and a key
    nobody recognises must not live in a row for ever."""
    sign_in(world["admin"])

    body = client.patch(
        "/api/organization", json={"appearance": {"primary": "#ff0000", "wat": 1}}
    ).json()

    assert body["appearance"] == {"primary": "#ff0000"}
