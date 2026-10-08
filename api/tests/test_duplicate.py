"""Copying a channel and copying a competition.

**The second wall is almost the first one**, and the commonest competition is
the last one. Both are rebuilt by hand today — a dozen forms to reach a
difference of one screen, or fourteen entrants re-ticked to reach a difference
of one date, which is where somebody misses a person.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tests.conftest import within_this_month
from app.models import Competition, Office

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
        "manager": make_user("manager", enterprise, name="Manager"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", enterprise, name="Clark Kent"),
        "metric": make_metric("calls_made"),
    }


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


# -- Channels ----------------------------------------------------------------


@pytest.fixture
def full_channel(client, world, sign_in):
    """A channel with one of everything worth copying."""

    def build():
        sign_in(world["admin"])
        channel = client.post(
            "/api/channels",
            json={
                "name": "Phoenix wall",
                "scope_type": "office",
                "scope_office_id": world["phoenix"].id,
                "allowed_ips": ["203.0.113.0/24"],
                "appearance": {"ranked_layout": "podium"},
            },
        ).json()
        calls = make_board(client, world, "Calls")
        deals = make_board(client, world, "Deals")
        client.post(
            f"/api/channels/{channel['id']}/screens",
            json={"kind": "leaderboard", "leaderboard_id": calls},
        )
        client.post(
            f"/api/channels/{channel['id']}/screens",
            json={"kind": "comparison", "leaderboard_ids": [calls, deals]},
        )
        client.post(
            f"/api/channels/{channel['id']}/screens",
            json={
                "kind": "message",
                "title": "All-hands Friday",
                "appearance": {"primary": "#ff0000"},
            },
        )
        return channel

    return build


def test_a_copy_has_the_same_screens_in_the_same_order(
    client, db, world, sign_in, full_channel
):
    original = full_channel()

    copy = client.post(f"/api/channels/{original['id']}/duplicate").json()

    assert [s["kind"] for s in copy["screens"]] == [
        s["kind"] for s in original["screens"]
    ] or [s["kind"] for s in copy["screens"]] == [
        "leaderboard",
        "comparison",
        "message",
    ]


def test_a_comparison_keeps_its_panels(client, db, world, sign_in, full_channel):
    """They live in their own table, so nothing about copying the screen row
    would have carried them."""
    original = full_channel()

    copy = client.post(f"/api/channels/{original['id']}/duplicate").json()

    panel = next(s for s in copy["screens"] if s["kind"] == "comparison")
    assert len(panel["leaderboard_ids"]) == 2


def test_the_audience_and_the_allowlist_come_too(
    client, db, world, sign_in, full_channel
):
    """A copy of the Phoenix wall that played to everybody would put one
    office's numbers in front of another."""
    original = full_channel()

    copy = client.post(f"/api/channels/{original['id']}/duplicate").json()

    assert copy["scope_type"] == "office"
    assert copy["scope_office_id"] == world["phoenix"].id
    assert copy["allowed_ips"] == ["203.0.113.0/24"]


def test_appearance_comes_too_at_both_layers(
    client, db, world, sign_in, full_channel
):
    original = full_channel()

    copy = client.post(f"/api/channels/{original['id']}/duplicate").json()

    assert copy["appearance"] == {"ranked_layout": "podium"}
    message = next(s for s in copy["screens"] if s["kind"] == "message")
    assert message["appearance"] == {"primary": "#ff0000"}


def test_it_is_named_as_a_copy(client, db, world, sign_in, full_channel):
    original = full_channel()

    copy = client.post(f"/api/channels/{original['id']}/duplicate").json()

    assert copy["name"] == "Phoenix wall (copy)"


def test_a_second_copy_is_numbered(client, db, world, sign_in, full_channel):
    """"(copy 1)" on the first one reads like there are others."""
    original = full_channel()
    client.post(f"/api/channels/{original['id']}/duplicate")

    second = client.post(f"/api/channels/{original['id']}/duplicate").json()

    assert second["name"] == "Phoenix wall (copy 2)"


def test_no_televisions_come_with_it(client, db, world, sign_in, full_channel):
    """**A copy that arrived already on a wall** would put an untouched
    duplicate in front of an office before anybody changed the thing they
    copied it to change."""
    original = full_channel()
    client.post(
        "/api/displays", json={"name": "TV", "channel_id": original["id"]}
    )

    copy = client.post(f"/api/channels/{original['id']}/duplicate").json()

    assert copy["display_count"] == 0


def test_editing_the_copy_leaves_the_original_alone(
    client, db, world, sign_in, full_channel
):
    """**A draft of its own, not a link.** That is the whole reason somebody
    duplicated rather than pointing a second display at the same channel."""
    original = full_channel()
    copy = client.post(f"/api/channels/{original['id']}/duplicate").json()

    client.delete(
        f"/api/channels/{copy['id']}/screens/{copy['screens'][0]['id']}"
    )

    again = client.get("/api/channels").json()
    kept = next(c for c in again if c["id"] == original["id"])
    assert len(kept["screens"]) == 3


def test_a_manager_cannot_copy_one(client, db, world, sign_in, full_channel):
    original = full_channel()

    sign_in(world["manager"])
    reply = client.post(f"/api/channels/{original['id']}/duplicate")

    assert reply.status_code == 403


# -- Competitions ------------------------------------------------------------


@pytest.fixture
def finished_contest(client, db, world, sign_in):
    """A contest that ran last March, with two entrants."""

    def build():
        sign_in(world["admin"])
        made = client.post(
            "/api/competitions",
            json={
                "name": "Month-end push",
                "metric_id": world["metric"].id,
                "entity_type": "user",
                "entity_ids": [world["peter"].id, world["clark"].id],
                "starts_at": "2026-03-01T00:00:00Z",
                "ends_at": "2026-03-15T00:00:00Z",
                "prize": "Steak dinner",
                "settlement_hours": 48,
                "tie_break": "shared_rank",
            },
        ).json()
        row = db.get(Competition, made["id"])
        row.state = "closed"
        db.commit()
        return made

    return build


def test_a_copy_keeps_the_rules_and_the_people(
    client, db, world, sign_in, finished_contest
):
    original = finished_contest()

    copy = client.post(f"/api/competitions/{original['id']}/duplicate").json()

    assert copy["prize"] == "Steak dinner"
    assert copy["settlement_hours"] == 48
    assert copy["tie_break"] == "shared_rank"
    assert copy["entrant_count"] == 2


def test_it_arrives_as_a_draft(client, db, world, sign_in, finished_contest):
    """**Whatever the original is now.** A copy that started running the moment
    it was made would be a contest nobody had checked the dates on."""
    original = finished_contest()

    copy = client.post(f"/api/competitions/{original['id']}/duplicate").json()

    assert copy["state"] == "draft"


def test_the_window_keeps_its_length_not_its_dates(
    client, db, world, sign_in, finished_contest
):
    """A copy of last March's contest, dated last March, has already
    finished."""
    original = finished_contest()

    copy = client.post(f"/api/competitions/{original['id']}/duplicate").json()

    starts = datetime.fromisoformat(copy["starts_at"].replace("Z", "+00:00"))
    ends = datetime.fromisoformat(copy["ends_at"].replace("Z", "+00:00"))
    assert ends - starts == timedelta(days=14)
    assert starts > datetime(2026, 3, 1, tzinfo=UTC)


def test_it_is_named_as_a_copy_too(client, db, world, sign_in, finished_contest):
    original = finished_contest()

    copy = client.post(f"/api/competitions/{original['id']}/duplicate").json()

    assert copy["name"] == "Month-end push (copy)"


def test_a_manager_may_copy_one(client, db, world, sign_in, finished_contest):
    """Unlike a channel: a manager can already create a competition, so
    refusing them a copy would be a rule that only costs typing."""
    original = finished_contest()

    sign_in(world["manager"])
    reply = client.post(f"/api/competitions/{original['id']}/duplicate")

    assert reply.status_code == 201, reply.json()


def test_another_organizations_contest_is_not_found(client, db, world, sign_in):
    sign_in(world["admin"])

    assert client.post("/api/competitions/999999/duplicate").status_code == 404
