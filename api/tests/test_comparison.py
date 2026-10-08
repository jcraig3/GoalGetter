"""Two to four boards side by side on one slide.

**The question a comparison answers is one no single board can.** "Who is
calling and who is closing" is two boards, and a rotation showing them ninety
seconds apart makes the room hold one in their head while they wait for the
other. Side by side, the person who is top of one and bottom of the other is
visible in a glance.

The properties worth guarding: a panel is still a board on a wall, so it
obeys every rule a board screen does; and losing one board does not blank the
screen.
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
        "calls": make_metric("calls_made"),
        "deals": make_metric("deals_closed"),
    }


def make_channel(client, name="Main wall", **overrides):
    reply = client.post("/api/channels", json={"name": name, **overrides})
    assert reply.status_code == 201, reply.json()
    return reply.json()


def make_board(client, world, name, metric="calls", **overrides):
    reply = client.post(
        "/api/leaderboards",
        json={
            "name": name,
            "metric_id": world[metric].id,
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


# -- Authoring ---------------------------------------------------------------


def test_two_boards_make_a_comparison(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    calls = make_board(client, world, "Calls")
    deals = make_board(client, world, "Deals", metric="deals")

    reply = add(
        client, channel["id"], kind="comparison", leaderboard_ids=[calls, deals]
    )

    assert reply.status_code == 201, reply.json()
    assert reply.json()["screens"][-1]["label"] == "Calls vs Deals"


def test_one_board_is_a_leaderboard_screen(client, db, world, sign_in):
    """Said plainly, because the person has already chosen a screen kind and
    needs to know they want the other one."""
    sign_in(world["admin"])
    channel = make_channel(client)

    reply = add(
        client,
        channel["id"],
        kind="comparison",
        leaderboard_ids=[make_board(client, world, "Calls")],
    )

    assert reply.status_code == 422
    assert "leaderboard screen" in reply.json()["detail"]


def test_five_is_too_many_to_read_across_a_room(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    ids = [make_board(client, world, f"Board {n}") for n in range(5)]

    reply = add(client, channel["id"], kind="comparison", leaderboard_ids=ids)

    assert reply.status_code == 422


def test_the_same_board_twice_is_refused(client, db, world, sign_in):
    """Two identical columns is a mistake every time, not a layout."""
    sign_in(world["admin"])
    channel = make_channel(client)
    calls = make_board(client, world, "Calls")

    reply = add(
        client, channel["id"], kind="comparison", leaderboard_ids=[calls, calls]
    )

    assert reply.status_code == 422
    assert "twice" in reply.json()["detail"]


def test_a_private_board_cannot_be_a_panel(client, db, world, sign_in):
    """Putting a board in a column does not make it public. The message names
    the board, because the admin picked four and needs to know which one."""
    sign_in(world["admin"])
    channel = make_channel(client)
    reply = add(
        client,
        channel["id"],
        kind="comparison",
        leaderboard_ids=[
            make_board(client, world, "Calls"),
            make_board(client, world, "Quiet", visibility="private"),
        ],
    )

    assert reply.status_code == 400
    assert "Quiet" in reply.json()["detail"]


def test_the_order_chosen_is_the_order_drawn(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    calls = make_board(client, world, "Calls")
    deals = make_board(client, world, "Deals", metric="deals")

    reply = add(
        client, channel["id"], kind="comparison", leaderboard_ids=[deals, calls]
    )

    assert reply.json()["screens"][-1]["leaderboard_ids"] == [deals, calls]
    assert reply.json()["screens"][-1]["label"] == "Deals vs Calls"


def test_editing_replaces_the_panels_wholesale(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    calls = make_board(client, world, "Calls")
    deals = make_board(client, world, "Deals", metric="deals")
    other = make_board(client, world, "Meetings")
    screen = add(
        client, channel["id"], kind="comparison", leaderboard_ids=[calls, deals]
    ).json()["screens"][-1]

    body = client.patch(
        f"/api/channels/{channel['id']}/screens/{screen['id']}",
        json={"kind": "comparison", "leaderboard_ids": [deals, other]},
    ).json()

    assert body["screens"][-1]["leaderboard_ids"] == [deals, other]


def test_changing_it_into_something_else_drops_the_panels(
    client, db, world, sign_in
):
    """**The trap here is the autoflush, not the delete.** Clearing the panels
    after the new kind is set flushes a half-edited row and fails the CHECK, so
    the clear happens while the row is still consistent."""
    sign_in(world["admin"])
    channel = make_channel(client)
    screen = add(
        client,
        channel["id"],
        kind="comparison",
        leaderboard_ids=[
            make_board(client, world, "Calls"),
            make_board(client, world, "Deals", metric="deals"),
        ],
    ).json()["screens"][-1]

    body = client.patch(
        f"/api/channels/{channel['id']}/screens/{screen['id']}",
        json={"kind": "message", "title": "Well done all"},
    )

    assert body.status_code == 200, body.json()
    assert body.json()["screens"][-1]["leaderboard_ids"] == []


# -- On the wall -------------------------------------------------------------


def test_every_panel_carries_its_own_board(
    client, db, org, world, sign_in, make_fact
):
    sign_in(world["admin"])
    make_fact(world["calls"], world["peter"], 40, WHEN)
    make_fact(world["deals"], world["clark"], 7, WHEN)
    db.commit()

    channel = make_channel(client)
    add(
        client,
        channel["id"],
        kind="comparison",
        leaderboard_ids=[
            make_board(client, world, "Calls"),
            make_board(client, world, "Deals", metric="deals"),
        ],
    )

    slide = wall(client, channel["id"])["slides"][0]
    assert [p["title"] for p in slide["panels"]] == ["Calls", "Deals"]
    assert slide["panels"][0]["entries"][0]["entity_name"] == "Peter Parker"
    assert slide["panels"][1]["entries"][0]["entity_name"] == "Clark Kent"


def test_a_panel_keeps_its_own_units(client, db, org, world, sign_in, make_fact):
    """Two boards on one slide are still two metrics. A shared format would
    print seven deals as $7.00 or forty calls as 40 dollars."""
    sign_in(world["admin"])
    make_fact(world["calls"], world["peter"], 40, WHEN)
    make_fact(world["deals"], world["peter"], 7, WHEN)
    db.commit()

    channel = make_channel(client)
    calls = make_board(client, world, "Calls")
    client.patch(f"/api/metrics/{world['deals'].id}", json={"unit": "currency"})
    deals = make_board(client, world, "Deals", metric="deals")
    add(client, channel["id"], kind="comparison", leaderboard_ids=[calls, deals])

    panels = wall(client, channel["id"])["slides"][0]["panels"]
    assert panels[0]["unit"] != panels[1]["unit"]


def test_losing_one_board_does_not_blank_the_screen(
    client, db, org, world, sign_in, make_fact
):
    """**A comparison of three that has become a comparison of two is still the
    comparison.** Blanking it would punish the room for an edit made
    elsewhere."""
    sign_in(world["admin"])
    make_fact(world["calls"], world["peter"], 40, WHEN)
    db.commit()

    channel = make_channel(client)
    calls = make_board(client, world, "Calls")
    deals = make_board(client, world, "Deals", metric="deals")
    add(client, channel["id"], kind="comparison", leaderboard_ids=[calls, deals])

    client.delete(f"/api/leaderboards/{deals}")

    slide = wall(client, channel["id"])["slides"][0]
    assert [p["title"] for p in slide["panels"]] == ["Calls"]


def test_losing_every_board_skips_it_rather_than_blanking_the_wall(
    client, db, org, world, sign_in
):
    sign_in(world["admin"])
    channel = make_channel(client)
    calls = make_board(client, world, "Calls")
    deals = make_board(client, world, "Deals", metric="deals")
    add(client, channel["id"], kind="comparison", leaderboard_ids=[calls, deals])

    client.delete(f"/api/leaderboards/{calls}")
    client.delete(f"/api/leaderboards/{deals}")

    assert wall(client, channel["id"])["slides"] == []


def test_a_title_of_its_own_wins_over_the_board_names(
    client, db, org, world, sign_in, make_fact
):
    sign_in(world["admin"])
    make_fact(world["calls"], world["peter"], 40, WHEN)
    db.commit()

    channel = make_channel(client)
    add(
        client,
        channel["id"],
        kind="comparison",
        title="Activity vs results",
        leaderboard_ids=[
            make_board(client, world, "Calls"),
            make_board(client, world, "Deals", metric="deals"),
        ],
    )

    assert wall(client, channel["id"])["slides"][0]["title"] == "Activity vs results"
