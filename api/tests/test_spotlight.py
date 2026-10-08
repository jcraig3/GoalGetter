"""A screen about one person.

**The observation behind it is a workaround, not a feature request.** In a real
157-user account, nearly every hand-authored message screen was an image of one
rep, made in an image editor. People were already building this; the product had
no template for it, so the version on the wall went stale the moment somebody
else overtook them.

The property worth protecting is that the *board-sourced* form keeps itself up
to date. A spotlight naming only a board is "whoever is leading", answered
fresh every time a television refreshes.
"""

import pytest

from tests.conftest import within_this_month
from app.models import Office

WHEN = within_this_month()


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    phoenix = Office(organization_id=org.id, name="Phoenix")
    dallas = Office(organization_id=org.id, name="Dallas")
    db.add_all([phoenix, dallas])
    db.flush()

    enterprise = make_team("Enterprise")
    enterprise.office_id = phoenix.id
    smb = make_team("SMB")
    smb.office_id = dallas.id
    db.flush()

    return {
        "phoenix": phoenix,
        "dallas": dallas,
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", enterprise, name="Clark Kent"),
        "bruce": make_user("agent", smb, name="Bruce Banner"),
        "metric": make_metric("calls_made"),
    }


def make_channel(client, name="Main wall", **overrides):
    reply = client.post("/api/channels", json={"name": name, **overrides})
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
    """A display on this channel, read the way a television reads it."""
    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel_id}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    return client.get(f"/api/display/{token}").json()


def only_slide(client, channel_id):
    slides = wall(client, channel_id)["slides"]
    assert len(slides) == 1, slides
    return slides[0]


# -- Authoring ---------------------------------------------------------------


def test_a_spotlight_needs_somebody_to_be_about(client, db, world, sign_in):
    """Neither a person nor a board is a screen with nothing on it."""
    sign_in(world["admin"])
    channel = make_channel(client)

    reply = add(client, channel["id"], kind="spotlight")

    assert reply.status_code == 422
    assert "somebody to be about" in reply.json()["detail"]


def test_a_named_person_is_enough(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)

    reply = add(client, channel["id"], kind="spotlight", user_id=world["peter"].id)

    assert reply.status_code == 201, reply.json()
    assert reply.json()["screens"][-1]["label"] == "Peter Parker"


def test_a_board_alone_is_enough_and_says_what_it_does(client, db, world, sign_in):
    """**The label names the behaviour, not the board.** "Whoever leads
    Revenue" is the difference between this row and the board screen above it,
    and an editor showing both as "Revenue" is a list you cannot read.
    """
    sign_in(world["admin"])
    channel = make_channel(client)
    board = make_board(client, world, name="Revenue")

    reply = add(client, channel["id"], kind="spotlight", leaderboard_id=board)

    assert reply.status_code == 201, reply.json()
    assert reply.json()["screens"][-1]["label"] == "Whoever leads Revenue"


def test_both_together_reads_as_a_person_on_a_board(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    board = make_board(client, world, name="Revenue")

    reply = add(
        client,
        channel["id"],
        kind="spotlight",
        user_id=world["peter"].id,
        leaderboard_id=board,
    )

    assert reply.json()["screens"][-1]["label"] == "Peter Parker — Revenue"


def test_a_team_board_has_no_one_person_to_spotlight(client, db, world, sign_in):
    """Refused at authoring rather than skipped at render, so the admin hears
    about it instead of watching the rotation step over a screen."""
    sign_in(world["admin"])
    channel = make_channel(client)
    board = make_board(client, world, name="Teams", entity_type="team")

    reply = add(client, channel["id"], kind="spotlight", leaderboard_id=board)

    assert reply.status_code == 400
    assert "ranks teams" in reply.json()["detail"]


def test_a_private_board_cannot_feed_one(client, db, world, sign_in):
    """The Phase 1 safety property: a wall has no audience control at all."""
    sign_in(world["admin"])
    channel = make_channel(client)
    board = make_board(client, world, name="Quiet", visibility="private")

    reply = add(client, channel["id"], kind="spotlight", leaderboard_id=board)

    assert reply.status_code == 400


def test_one_offices_person_does_not_go_on_anothers_wall(client, db, world, sign_in):
    """The same hole as a goal: a spotlight names its own subject, so the
    audience filter has nothing to bite on."""
    sign_in(world["admin"])
    channel = make_channel(
        client, scope_type="office", scope_office_id=world["phoenix"].id
    )

    reply = add(client, channel["id"], kind="spotlight", user_id=world["bruce"].id)

    assert reply.status_code == 400
    assert "different office or team" in reply.json()["detail"]


def test_changing_a_spotlight_into_something_else_drops_the_person(
    client, db, world, sign_in
):
    """Otherwise the id sits behind a message screen and the label goes on
    naming somebody nobody is showing."""
    sign_in(world["admin"])
    channel = make_channel(client)
    screen = add(
        client, channel["id"], kind="spotlight", user_id=world["peter"].id
    ).json()["screens"][-1]

    body = client.patch(
        f"/api/channels/{channel['id']}/screens/{screen['id']}",
        json={"kind": "message", "title": "Well done all"},
    ).json()

    assert body["screens"][-1]["user_id"] is None


def test_the_picker_offers_only_people_this_wall_may_show(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(
        client, scope_type="office", scope_office_id=world["phoenix"].id
    )

    people = client.get(f"/api/channels/{channel['id']}/eligible").json()["people"]

    names = [p["name"] for p in people]
    assert "Peter Parker" in names
    assert "Bruce Banner" not in names


# -- On the wall -------------------------------------------------------------


def test_a_board_spotlight_follows_whoever_is_leading(
    client, db, org, world, sign_in, make_fact
):
    """**This is the whole feature.** A screen naming a person is an uploaded
    image with extra steps; one naming a board is right every refresh."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["clark"], 90, WHEN)
    make_fact(world["metric"], world["peter"], 10, WHEN)
    db.commit()

    channel = make_channel(client)
    add(client, channel["id"], kind="spotlight", leaderboard_id=make_board(client, world))

    assert only_slide(client, channel["id"])["person"]["name"] == "Clark Kent"


def test_it_changes_when_the_lead_changes(client, db, org, world, sign_in, make_fact):
    sign_in(world["admin"])
    make_fact(world["metric"], world["clark"], 90, WHEN)
    db.commit()
    channel = make_channel(client)
    add(client, channel["id"], kind="spotlight", leaderboard_id=make_board(client, world))
    assert only_slide(client, channel["id"])["person"]["name"] == "Clark Kent"

    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 500, WHEN)
    db.commit()

    assert only_slide(client, channel["id"])["person"]["name"] == "Peter Parker"


def test_a_named_person_stays_named_however_the_board_moves(
    client, db, org, world, sign_in, make_fact
):
    """Which is what it is for: the new starter you are encouraging, not
    whoever happens to be winning."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["clark"], 900, WHEN)
    make_fact(world["metric"], world["peter"], 4, WHEN)
    db.commit()

    channel = make_channel(client)
    add(
        client,
        channel["id"],
        kind="spotlight",
        user_id=world["peter"].id,
        leaderboard_id=make_board(client, world),
    )

    slide = only_slide(client, channel["id"])
    assert slide["person"]["name"] == "Peter Parker"
    assert slide["stats"][0]["rank"] == 2


def test_somebody_outside_the_display_limit_can_still_be_spotlighted(
    client, db, org, world, sign_in, make_fact
):
    """`display_limit` is a drawing decision for the board. A spotlight on
    somebody fortieth is exactly the case a manager wants."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["clark"], 900, WHEN)
    make_fact(world["metric"], world["peter"], 1, WHEN)
    db.commit()

    channel = make_channel(client)
    board = make_board(client, world, display_limit=1)
    add(
        client,
        channel["id"],
        kind="spotlight",
        user_id=world["peter"].id,
        leaderboard_id=board,
    )

    slide = only_slide(client, channel["id"])
    assert slide["stats"][0]["rank"] == 2


def test_an_empty_board_is_skipped_rather_than_drawn_blank(client, db, world, sign_in):
    """A wall going black in front of an office reads as the product being
    broken; one fewer slide reads as nothing at all."""
    sign_in(world["admin"])
    channel = make_channel(client)
    add(client, channel["id"], kind="spotlight", leaderboard_id=make_board(client, world))

    assert wall(client, channel["id"])["slides"] == []


def test_a_person_with_no_board_still_renders(client, db, world, sign_in):
    """The employee-of-the-month card: a face and a name, no numbers."""
    sign_in(world["admin"])
    channel = make_channel(client)
    add(client, channel["id"], kind="spotlight", user_id=world["peter"].id)

    slide = only_slide(client, channel["id"])
    assert slide["person"]["name"] == "Peter Parker"
    assert slide["stats"] == []
    # Nothing to count a streak from, which is not the same as a streak of 0.
    assert slide["streak_days"] is None


def test_it_carries_the_face_the_board_would_have_drawn(
    client, db, org, world, sign_in, make_fact
):
    from app import photos

    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 10, WHEN)
    photos.set_custom(db, world["peter"], _png())
    db.commit()

    channel = make_channel(client)
    add(client, channel["id"], kind="spotlight", leaderboard_id=make_board(client, world))

    assert only_slide(client, channel["id"])["person"]["photo_digest"]


def test_a_board_spotlight_inherits_that_boards_look(
    client, db, org, world, sign_in, make_fact
):
    """Shark Week being blue covers the person on the Shark Week board too,
    rather than stopping at the table."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 10, WHEN)
    db.commit()

    channel = make_channel(client)
    board = make_board(client, world)
    client.patch(
        f"/api/leaderboards/{board}", json={"appearance": {"primary": "#ff0000"}}
    )
    add(client, channel["id"], kind="spotlight", leaderboard_id=board)

    assert only_slide(client, channel["id"])["appearance"]["primary"] == "#ff0000"


def _png() -> bytes:
    """A real PNG, big enough to pass the upload rules. See `app/images.py`."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (256, 256), (255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()
