"""Putting a celebration back on a wall, on purpose.

For the manager whose team's best moment of the week happened while the room
was in a meeting, and whose only record of it is a line in a feed somebody has
to be told to go and read.
"""

from datetime import UTC, datetime, timedelta

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
        "manager": make_user("manager", enterprise, name="Manager"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
    }


def a_win(db, org, world, event_key="competition.won", title="Won the sprint"):
    row = Notification(
        organization_id=org.id,
        user_id=world["peter"].id,
        event_key=event_key,
        subject_type="competition",
        subject_id=abs(hash(title)) % 10_000,
        title=title,
        about_name="Peter Parker",
        about_user_id=world["peter"].id,
        # Long ago, so it is well outside the "just happened" window and can
        # only reach a wall by being replayed.
        created_at=datetime.now(UTC) - timedelta(days=3),
    )
    db.add(row)
    db.flush()
    return row


def channel(client, name="Floor"):
    return client.post("/api/channels", json={"name": name}).json()


def played(client, channel_id):
    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel_id}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    return client.get(f"/api/display/{token}/celebrations").json()["celebrations"]


# -- Asking for one ----------------------------------------------------------


def test_an_admin_can_replay_a_win(client, db, org, world, sign_in):
    sign_in(world["admin"])
    win = a_win(db, org, world)
    db.commit()
    made = channel(client)

    reply = client.post(
        f"/api/channels/{made['id']}/replay", json={"notification_id": win.id}
    )

    assert reply.status_code == 202, reply.json()


def test_a_manager_cannot(client, db, org, world, sign_in):
    """A channel is what a whole office looks at all day, and so is what
    interrupts it."""
    sign_in(world["admin"])
    win = a_win(db, org, world)
    db.commit()
    made = channel(client)

    sign_in(world["manager"])
    reply = client.post(
        f"/api/channels/{made['id']}/replay", json={"notification_id": win.id}
    )

    assert reply.status_code == 403


def test_a_private_win_cannot_be_put_on_a_wall(client, db, org, world, sign_in):
    """**The same rule the feed itself obeys.** A wall is read by whoever walks
    past, so "you are behind on your goal" must not reach one — least of all
    because somebody pressed a button next to it."""
    sign_in(world["admin"])
    win = a_win(db, org, world, event_key="goal.period_ending", title="Running out")
    db.commit()
    made = channel(client)

    reply = client.post(
        f"/api/channels/{made['id']}/replay", json={"notification_id": win.id}
    )

    assert reply.status_code == 400
    assert "private" in reply.json()["detail"]


def test_another_organizations_win_is_not_found(client, db, org, world, sign_in):
    sign_in(world["admin"])
    made = channel(client)

    reply = client.post(
        f"/api/channels/{made['id']}/replay", json={"notification_id": 999_999}
    )

    assert reply.status_code == 404


# -- What a wall then does ---------------------------------------------------


def test_the_win_reaches_the_wall_again(client, db, org, world, sign_in):
    """Three days old, which is the whole point — the manager who missed it
    missed it because it was not recent."""
    sign_in(world["admin"])
    win = a_win(db, org, world)
    db.commit()
    made = channel(client)
    client.post(
        f"/api/channels/{made['id']}/replay", json={"notification_id": win.id}
    )

    shown = played(client, made["id"])

    assert [c["title"] for c in shown] == ["Won the sprint"]


def test_it_arrives_with_an_id_a_screen_has_not_seen(
    client, db, org, world, sign_in
):
    """**The bug this prevents is total silence.** A screen remembers what it
    has played; a replay carrying the win's own id would look like the one it
    already showed, and the wall would skip exactly what it was asked for."""
    sign_in(world["admin"])
    win = a_win(db, org, world)
    db.commit()
    made = channel(client)
    client.post(
        f"/api/channels/{made['id']}/replay", json={"notification_id": win.id}
    )

    shown = played(client, made["id"])

    assert shown[0]["id"].startswith("replay:")
    assert shown[0]["id"] != f"win:{win.id}"


def test_a_replay_plays_even_on_a_quiet_wall(client, db, org, world, sign_in):
    """`milestones` is about which wins are worth interrupting a room for on
    their own. A replay is somebody deciding this one is, which is a stronger
    signal than any default — and a wall that ignored an explicit instruction
    would read as broken."""
    sign_in(world["admin"])
    win = a_win(db, org, world)
    db.commit()
    made = channel(client)
    client.patch(
        f"/api/channels/{made['id']}",
        json={"name": "Floor", "appearance": {"milestones": "none"}},
    )
    client.post(
        f"/api/channels/{made['id']}/replay", json={"notification_id": win.id}
    )

    assert len(played(client, made["id"])) == 1


def test_it_obeys_the_name_style_like_everything_else(
    client, db, org, world, sign_in
):
    """A replay that formatted names differently would be a privacy setting
    applied in one place and not the other."""
    sign_in(world["admin"])
    win = a_win(db, org, world)
    db.commit()
    client.patch(
        "/api/organization", json={"appearance": {"name_display": "first_initial"}}
    )
    made = channel(client)
    client.post(
        f"/api/channels/{made['id']}/replay", json={"notification_id": win.id}
    )

    assert played(client, made["id"])[0]["about_name"] == "Peter P."


def test_another_channel_does_not_play_it(client, db, org, world, sign_in):
    """A replay is aimed at a room."""
    sign_in(world["admin"])
    win = a_win(db, org, world)
    db.commit()
    floor = channel(client, "Floor")
    lobby = channel(client, "Lobby")
    client.post(
        f"/api/channels/{floor['id']}/replay", json={"notification_id": win.id}
    )

    assert played(client, lobby["id"]) == []


def test_it_stops_being_offered_after_a_while(client, db, org, world, sign_in):
    """**A replay is an instruction, not news.** Somebody pressed a button
    meaning "now", and a television that was switched off has not missed a
    moment worth chasing."""
    from app import channels as channel_service
    from app.models import Channel

    sign_in(world["admin"])
    win = a_win(db, org, world)
    db.commit()
    made = channel(client)
    client.post(
        f"/api/channels/{made['id']}/replay", json={"notification_id": win.id}
    )

    later = datetime.now(UTC) + timedelta(
        seconds=events.REPLAY_WINDOW_SECONDS + 60
    )
    found = channel_service.celebrations(
        db, org, db.get(Channel, made["id"]), now=later
    )

    assert found == []


# -- Refusals ----------------------------------------------------------------


def test_a_replay_has_to_name_a_win(client, db, org, world, sign_in):
    """There was a "test card" here — a replay with no win behind it, for
    checking a television. It had exactly one caller, a button nobody wanted,
    and an unreachable branch is worse than a missing one."""
    sign_in(world["admin"])
    made = channel(client)

    reply = client.post(f"/api/channels/{made['id']}/replay", json={})

    assert reply.status_code == 422


# -- Housekeeping ------------------------------------------------------------


def test_asking_again_sweeps_what_has_expired(client, db, org, world, sign_in):
    """Swept where somebody is already writing, rather than by a job: the table
    is only ever read for the last two minutes, so anything older is dead
    weight."""
    from sqlalchemy import func, select

    from app.models import CelebrationReplay

    sign_in(world["admin"])
    win = a_win(db, org, world)
    db.commit()
    made = channel(client)
    client.post(
        f"/api/channels/{made['id']}/replay", json={"notification_id": win.id}
    )

    stale = db.scalars(select(CelebrationReplay)).first()
    stale.created_at = datetime.now(UTC) - timedelta(days=1)
    db.commit()

    client.post(
        f"/api/channels/{made['id']}/replay", json={"notification_id": win.id}
    )

    assert db.scalar(select(func.count()).select_from(CelebrationReplay)) == 1
