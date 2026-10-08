"""Preview on a TV: something unsaved, on one screen, for a moment (5j).

What has to be true: it reaches the one screen it was sent to and no other,
even on the same channel; it is marked as a preview; it ends on its own; it
is built by the same checks saving makes; nothing it came from is saved; and
only an admin can send one.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import display_previews
from app.models import AchievementRule, ChannelScreen, DisplayPreview, Notification


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    db.flush()
    return {
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "revenue": make_metric("revenue_closed", unit="currency", decimal_places=2),
    }


def channel(client, name="Floor"):
    return client.post("/api/channels", json={"name": name}).json()


def tv(client, channel_id, name="Lobby TV"):
    created = client.post(
        "/api/displays", json={"name": name, "channel_id": channel_id}
    ).json()
    return created["id"], created["url"].rsplit("/", 1)[-1]


def playing(client, token):
    return client.get(f"/api/display/{token}/celebrations").json()["celebrations"]


def rule_body(world, **overrides):
    return {
        "name": "Big deal closed",
        "metric_id": world["revenue"].id,
        "threshold": "5000",
        **overrides,
    }


def test_a_slide_reaches_the_one_tv_it_was_sent_to(client, db, world, sign_in):
    sign_in(world["admin"])
    floor = channel(client)
    lobby_id, lobby = tv(client, floor["id"], "Lobby TV")
    _, kitchen = tv(client, floor["id"], "Kitchen TV")

    reply = client.post(
        f"/api/channels/{floor['id']}/screens/preview/tv/{lobby_id}",
        json={"kind": "message", "title": "Pizza at four"},
    )
    assert reply.status_code == 202, reply.json()
    assert reply.json()["display_name"] == "Lobby TV"

    client.cookies.clear()
    shown = playing(client, lobby)
    assert len(shown) == 1
    assert shown[0]["preview"] is True
    assert shown[0]["slide"]["title"] == "Pizza at four"
    assert shown[0]["ends_at"] - shown[0]["starts_at"] == display_previews.SLIDE_SECONDS * 1000
    # The same channel, another screen: nothing.
    assert playing(client, kitchen) == []
    # And the slide itself was never added to the channel.
    assert db.scalar(select(func.count(ChannelScreen.id))) == 0


def test_a_rules_celebration_plays_on_the_tv_and_announces_nothing(
    client, db, world, sign_in
):
    sign_in(world["admin"])
    floor = channel(client)
    lobby_id, lobby = tv(client, floor["id"])

    reply = client.post(
        f"/api/achievement-rules/preview/tv/{lobby_id}",
        json=rule_body(world, message="{first_name} closed {value}!"),
    )
    assert reply.status_code == 202, reply.json()

    client.cookies.clear()
    shown = playing(client, lobby)
    assert shown[0]["preview"] is True
    assert shown[0]["slide"] is None
    assert shown[0]["body"] == "Admin closed $5,000!"
    assert db.scalars(select(AchievementRule)).all() == []
    assert db.scalars(select(Notification)).all() == []


def test_a_preview_ends_on_its_own(client, db, world, sign_in):
    sign_in(world["admin"])
    floor = channel(client)
    lobby_id, lobby = tv(client, floor["id"])
    client.post(
        f"/api/channels/{floor['id']}/screens/preview/tv/{lobby_id}",
        json={"kind": "message", "title": "Pizza at four"},
    )
    row = db.scalar(select(DisplayPreview))
    row.starts_at = datetime.now(UTC) - timedelta(seconds=display_previews.SLIDE_SECONDS + 1)
    db.commit()

    client.cookies.clear()
    assert playing(client, lobby) == []


def test_a_preview_refuses_what_saving_refuses(client, db, world, sign_in):
    sign_in(world["admin"])
    floor = channel(client)
    lobby_id, _ = tv(client, floor["id"])

    assert client.post(
        f"/api/channels/{floor['id']}/screens/preview/tv/{lobby_id}",
        json={"kind": "message", "body": "no title"},
    ).status_code == 422
    assert client.post(
        f"/api/achievement-rules/preview/tv/{lobby_id}",
        json=rule_body(world, message="{squad}"),
    ).status_code == 422
    assert db.scalar(select(func.count(DisplayPreview.id))) == 0


def test_a_revoked_tv_cannot_be_sent_to(client, db, world, sign_in):
    sign_in(world["admin"])
    floor = channel(client)
    lobby_id, _ = tv(client, floor["id"])
    client.post(f"/api/displays/{lobby_id}/revoke")

    assert client.post(
        f"/api/channels/{floor['id']}/screens/preview/tv/{lobby_id}",
        json={"kind": "message", "title": "Hello"},
    ).status_code == 404


def test_only_an_admin_can_send_one(client, db, world, sign_in):
    sign_in(world["admin"])
    floor = channel(client)
    lobby_id, _ = tv(client, floor["id"])
    sign_in(world["manager"])

    assert client.post(
        f"/api/channels/{floor['id']}/screens/preview/tv/{lobby_id}",
        json={"kind": "message", "title": "Hello"},
    ).status_code == 403
    assert client.post(
        f"/api/achievement-rules/preview/tv/{lobby_id}", json=rule_body(world)
    ).status_code == 403
