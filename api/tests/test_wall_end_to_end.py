"""One channel with every kind of screen on it.

**A pass over the whole rotation, not over one builder at a time.** Each screen
kind has its own tests; this is the one that would catch a slide shape that is
fine alone and wrong beside the others — a field added to one renderer and not
to the payload, a kind that stops being skipped when it should be, a rotation
that drops a screen nobody notices because five others still draw.

It is also the shortest description of what a wall can show.
"""

import io

import pytest
from PIL import Image

from tests.conftest import within_this_month
from app.models import Notification, Office

WHEN = within_this_month()

#: Every kind a channel can hold, and what it needs to be worth drawing.
EXPECTED_KINDS = [
    "leaderboard",
    "goal",
    "competition",
    "spotlight",
    "comparison",
    "achievements",
    "message",
    "image",
]


def png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (800, 450), (20, 40, 80)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    phoenix = Office(organization_id=org.id, name="Phoenix")
    db.add(phoenix)
    db.flush()
    enterprise = make_team("Enterprise")
    enterprise.office_id = phoenix.id
    db.flush()

    return {
        "enterprise": enterprise,
        "admin": make_user("admin", name="Admin"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", enterprise, name="Clark Kent"),
        "calls": make_metric("calls_made"),
        "deals": make_metric("deals_closed"),
    }


@pytest.fixture
def everything(client, db, org, world, sign_in, make_fact):
    """A channel with one of every screen on it, and data behind each."""
    sign_in(world["admin"])
    make_fact(world["calls"], world["peter"], 40, WHEN)
    make_fact(world["calls"], world["clark"], 25, WHEN)
    make_fact(world["deals"], world["clark"], 7, WHEN)
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

    channel = client.post("/api/channels", json={"name": "Everything"}).json()

    def board(name, metric):
        return client.post(
            "/api/leaderboards",
            json={
                "name": name,
                "metric_id": world[metric].id,
                "period_type": "month",
                "visibility": "org",
            },
        ).json()["id"]

    calls = board("Calls", "calls")
    deals = board("Deals", "deals")

    goal = client.post(
        "/api/goals",
        json={
            "metric_id": world["calls"].id,
            "subject_type": "user",
            "subject_id": world["peter"].id,
            "target_value": "100",
            "period_type": "month",
        },
    ).json()

    contest = client.post(
        "/api/competitions",
        json={
            "name": "Month-end push",
            "metric_id": world["calls"].id,
            "entity_type": "user",
            "entity_ids": [world["peter"].id, world["clark"].id],
            "starts_at": "2026-01-01T00:00:00Z",
            "ends_at": "2099-01-01T00:00:00Z",
            "settlement_hours": 24,
            "tie_break": "earliest_to_reach",
        },
    ).json()
    client.post(f"/api/competitions/{contest['id']}/publish")

    def add(**payload):
        reply = client.post(f"/api/channels/{channel['id']}/screens", json=payload)
        assert reply.status_code == 201, (payload.get("kind"), reply.json())

    add(kind="leaderboard", leaderboard_id=calls)
    add(kind="goal", goal_id=goal["id"])
    add(kind="competition", competition_id=contest["id"])
    add(kind="spotlight", leaderboard_id=calls)
    add(kind="comparison", leaderboard_ids=[calls, deals])
    add(kind="achievements")
    add(kind="message", title="All-hands Friday", body="Doors at 4.")
    add(kind="image", url="https://example.com/banner.png")

    return {"channel": channel["id"], "board": calls}


def wall(client, channel_id):
    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel_id}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    return client.get(f"/api/display/{token}").json()


def test_every_kind_reaches_the_wall(client, everything):
    """The count is the assertion. A screen that silently fails to render
    leaves a rotation one shorter and nobody standing in the room knows why."""
    slides = wall(client, everything["channel"])["slides"]

    assert [slide["kind"] for slide in slides] == EXPECTED_KINDS


def test_every_slide_carries_a_complete_appearance(client, everything):
    """Including the kinds that do not obviously need one. A message screen
    still sits on the organization's background in its font."""
    slides = wall(client, everything["channel"])["slides"]

    for slide in slides:
        assert slide["appearance"]["font"], slide["kind"]
        assert slide["appearance"]["background"] is not None, slide["kind"]


def test_every_slide_has_something_to_draw(client, everything):
    """Each kind's own payload, present and non-empty — the check that a
    builder has not quietly started returning an empty shell."""
    by_kind = {s["kind"]: s for s in wall(client, everything["channel"])["slides"]}

    assert by_kind["leaderboard"]["entries"]
    assert by_kind["goal"]["target_value"]
    assert by_kind["competition"]["entries"]
    assert by_kind["spotlight"]["person"]
    assert by_kind["comparison"]["panels"]
    assert by_kind["achievements"]["achievements"]
    assert by_kind["message"]["body"]
    assert by_kind["image"]["url"]


def test_the_whole_rotation_follows_one_setting(client, everything):
    """A house style is set once. A screen that ignored it would be the one
    slide in six that looks like a different product."""
    client.patch(
        "/api/organization",
        json={"appearance": {"primary": "#ff0000", "name_display": "first"}},
    )

    slides = wall(client, everything["channel"])["slides"]

    assert all(s["appearance"]["primary"] == "#ff0000" for s in slides)
    for slide in slides:
        for entry in slide["entries"]:
            assert " " not in entry["entity_name"], slide["kind"]


def test_one_screen_can_differ_from_the_rest(client, everything):
    """Two screens in one rotation can legitimately disagree — which is why
    the appearance is resolved per slide and not per channel."""
    client.patch(
        "/api/organization", json={"appearance": {"ranked_layout": "list"}}
    )
    client.patch(
        f"/api/leaderboards/{everything['board']}",
        json={"appearance": {"ranked_layout": "podium"}},
    )

    by_kind = {s["kind"]: s for s in wall(client, everything["channel"])["slides"]}

    assert by_kind["leaderboard"]["appearance"]["ranked_layout"] == "podium"
    assert by_kind["goal"]["appearance"]["ranked_layout"] == "list"


def test_a_wall_survives_the_things_behind_it_being_deleted(
    client, db, everything, world, sign_in
):
    """**Skipped, never blanked.** Deleting the board takes three screens with
    it — the board, the spotlight drawn from it and one panel of the
    comparison — and the rotation keeps running."""
    sign_in(world["admin"])
    client.delete(f"/api/leaderboards/{everything['board']}")

    slides = wall(client, everything["channel"])["slides"]

    kinds = [s["kind"] for s in slides]
    assert "leaderboard" not in kinds
    assert "spotlight" not in kinds
    # The comparison keeps the board it still has.
    assert "comparison" in kinds
    assert len(slides) == len(EXPECTED_KINDS) - 2


def test_an_empty_channel_is_not_an_error(client, db, world, sign_in):
    """A wall being set up has no screens yet, and it is pointed at a
    television before anybody finishes."""
    sign_in(world["admin"])
    channel = client.post("/api/channels", json={"name": "New"}).json()

    body = wall(client, channel["id"])

    assert body["slides"] == []
    assert body["channel_name"] == "New"
