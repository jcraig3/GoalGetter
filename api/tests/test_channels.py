"""Authored channels: what plays on a wall, and in what order.

The two things worth guarding are that a wall can never show a board its
audience could not already see, and that a screen which cannot render is
skipped rather than blanking the room.
"""

from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import within_this_month
from sqlalchemy import func, select

from app.models import AuditLog, Channel, ChannelScreen, Display, Goal

#: Inside the current month, whatever month that is. A literal here read
#: correctly in August and silently excluded itself from every "this month"
#: board on the first of September. See `conftest.within_this_month`.
WHEN = within_this_month()


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    from app.models import Office

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
        "smb": smb,
        "enterprise": enterprise,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "alice": make_user("agent", enterprise, name="Alice"),
        "metric": make_metric("calls_made"),
    }


def make_channel(client, name="Phoenix wall"):
    response = client.post("/api/channels", json={"name": name})
    assert response.status_code == 201, response.json()
    return response.json()


def make_board(client, world, name="Calls", **overrides):
    response = client.post(
        "/api/leaderboards",
        json={
            "name": name,
            "metric_id": world["metric"].id,
            "period_type": "month",
            "visibility": "org",
            **overrides,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def add(client, channel_id, **payload):
    return client.post(f"/api/channels/{channel_id}/screens", json=payload)


# ── Authoring ────────────────────────────────────────────────────────────────


def test_an_admin_can_create_a_channel(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    assert channel["name"] == "Phoenix wall"
    assert channel["screens"] == []
    assert channel["display_count"] == 0


def test_a_manager_cannot(client, db, world, sign_in):
    """A channel is what a whole office looks at all day."""
    sign_in(world["manager"])
    assert client.post("/api/channels", json={"name": "Mine"}).status_code == 403


def test_screens_are_appended_in_order(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    for name in ("First", "Second", "Third"):
        add(client, channel["id"], kind="leaderboard",
            leaderboard_id=make_board(client, world, name=name))

    body = client.get("/api/channels").json()[0]
    assert [s["label"] for s in body["screens"]] == ["First", "Second", "Third"]
    assert [s["position"] for s in body["screens"]] == [0, 1, 2]


def test_reordering_rewrites_the_whole_order(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    ids = []
    for name in ("A", "B", "C"):
        ids.append(
            add(client, channel["id"], kind="leaderboard",
                leaderboard_id=make_board(client, world, name=name)).json()["screens"][-1]["id"]
        )

    body = client.post(
        f"/api/channels/{channel['id']}/order",
        json={"screen_ids": [ids[2], ids[0], ids[1]]},
    ).json()

    assert [s["label"] for s in body["screens"]] == ["C", "A", "B"]


def test_a_screen_left_out_of_a_reorder_survives(client, db, world, sign_in):
    """A stale editor tab must not be able to delete a screen by omission."""
    sign_in(world["admin"])
    channel = make_channel(client)
    first = add(client, channel["id"], kind="leaderboard",
                leaderboard_id=make_board(client, world, name="A")).json()["screens"][-1]["id"]
    add(client, channel["id"], kind="leaderboard",
        leaderboard_id=make_board(client, world, name="B"))

    body = client.post(
        f"/api/channels/{channel['id']}/order", json={"screen_ids": [first]}
    ).json()

    assert [s["label"] for s in body["screens"]] == ["A", "B"]


def test_an_unknown_id_in_a_reorder_is_ignored(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    add(client, channel["id"], kind="leaderboard",
        leaderboard_id=make_board(client, world, name="A"))

    response = client.post(
        f"/api/channels/{channel['id']}/order", json={"screen_ids": [999999]}
    )
    assert response.status_code == 200
    assert len(response.json()["screens"]) == 1


# ── What may go on a wall ────────────────────────────────────────────────────


def test_a_private_board_is_refused_at_authoring_time(client, db, world, sign_in):
    """Told now, rather than discovering a blank slide on a wall later."""
    sign_in(world["admin"])
    channel = make_channel(client)
    board = make_board(client, world, name="Secret", visibility="private")

    response = add(client, channel["id"], kind="leaderboard", leaderboard_id=board)

    assert response.status_code == 400
    assert "everyone" in response.json()["detail"]


def test_a_goal_can_be_a_screen(client, db, org, world, sign_in):
    """The most useful screen there is: a target with a pace marker is what a
    room can act on before the period closes."""
    goal = Goal(
        organization_id=org.id,
        metric_definition_id=world["metric"].id,
        subject_type="user",
        subject_user_id=world["alice"].id,
        target_value=100,
        period_type="month",
        period_anchor=WHEN.date().replace(day=1),
        name="Alice's calls",
    )
    db.add(goal)
    db.flush()

    sign_in(world["admin"])
    channel = make_channel(client)
    body = add(client, channel["id"], kind="goal", goal_id=goal.id).json()

    # Named *and* attributed. Three people with a "Calls Made" goal are three
    # identical rows otherwise, and this list is where you pick between them.
    assert body["screens"][0]["label"] == "Alice's calls — Alice"


def test_an_image_url_is_validated(client, db, world, sign_in):
    """The same allowlist as walk-up media: a wall must never fetch an
    arbitrary URL."""
    sign_in(world["admin"])
    channel = make_channel(client)

    assert add(client, channel["id"], kind="image",
               url="https://cdn.example.com/party.gif").status_code == 201
    assert add(client, channel["id"], kind="image",
               url="javascript:alert(1)").status_code == 422


def test_a_message_needs_something_to_say(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    assert add(client, channel["id"], kind="message", body="only a body").status_code == 422
    assert add(client, channel["id"], kind="message", title="Well done all").status_code == 201


def test_an_unknown_kind_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    assert add(client, channel["id"], kind="hologram").status_code == 422


def test_changing_a_screens_kind_clears_the_old_payload(client, db, world, sign_in):
    """Otherwise the board id stays behind and the label goes on naming a board
    nobody is showing."""
    sign_in(world["admin"])
    channel = make_channel(client)
    screen = add(client, channel["id"], kind="leaderboard",
                 leaderboard_id=make_board(client, world)).json()["screens"][-1]

    body = client.patch(
        f"/api/channels/{channel['id']}/screens/{screen['id']}",
        json={"kind": "message", "title": "Team meeting at 3"},
    ).json()

    assert body["screens"][0]["kind"] == "message"
    assert body["screens"][0]["leaderboard_id"] is None
    assert body["screens"][0]["label"] == "Team meeting at 3"


# ── Archiving ────────────────────────────────────────────────────────────────


def test_a_channel_a_tv_is_playing_cannot_be_deleted(
    client, db, org, world, sign_in
):
    """The guard that a confirmation dialog cannot replace.

    The foreign key cascades, so this would take the *display rows* with it —
    a link somebody already opened on a television would stop working and leave
    no record it had existed. The person clicking cannot see that from where
    they are standing.
    """
    sign_in(world["admin"])
    channel = make_channel(client)
    client.post("/api/displays", json={"name": "TV", "channel_id": channel["id"]})

    response = client.delete(f"/api/channels/{channel['id']}")

    assert response.status_code == 400
    # Reads correctly for one as well as several — "1 TV still plays this
    # channel", not "1 TV still play" — and says TV, not "screen" (Q2-23).
    assert response.json()["detail"].startswith("1 TV still plays")


def test_an_unused_channel_can_be_deleted(client, db, world, sign_in):
    """There is no archive for channels: nothing historical points at one, so
    deleting is the only retirement it needs."""
    sign_in(world["admin"])
    channel = make_channel(client)
    add(client, channel["id"], kind="achievements")

    assert client.delete(f"/api/channels/{channel['id']}").status_code == 204
    assert client.get("/api/channels").json() == []


def test_deleting_takes_the_screens_with_it(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    add(client, channel["id"], kind="achievements")
    before = db.scalar(select(func.count()).select_from(ChannelScreen))

    client.delete(f"/api/channels/{channel['id']}")
    db.expire_all()

    assert db.scalar(select(func.count()).select_from(ChannelScreen)) == before - 1


def test_a_revoked_display_does_not_block_deleting(client, db, world, sign_in):
    """It is not showing anything, so there is nothing to strand."""
    sign_in(world["admin"])
    channel = make_channel(client)
    display = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel["id"]}
    ).json()
    client.post(f"/api/displays/{display['id']}/revoke")

    assert client.delete(f"/api/channels/{channel['id']}").status_code == 204


def test_creating_and_deleting_are_audited(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    client.delete(f"/api/channels/{channel['id']}")

    actions = [
        row.action for row in db.scalars(select(AuditLog).order_by(AuditLog.id)).all()
    ]
    assert "channel.created" in actions
    assert "channel.deleted" in actions


def test_channels_do_not_cross_organizations(client, db, world, sign_in):
    from app.models import Organization

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    db.add(Channel(organization_id=other.id, name="Theirs"))
    db.commit()

    sign_in(world["admin"])
    assert client.get("/api/channels").json() == []


def test_display_count_shows_what_is_attached(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    client.post("/api/displays", json={"name": "One", "channel_id": channel["id"]})
    client.post("/api/displays", json={"name": "Two", "channel_id": channel["id"]})

    assert client.get("/api/channels").json()[0]["display_count"] == 2


# ── Audience ─────────────────────────────────────────────────────────────────


def test_a_channel_defaults_to_everyone(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    assert channel["scope_type"] == "organization"
    assert channel["audience_label"] == "Everyone"


def test_a_channel_can_be_scoped_to_an_office(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.post(
        "/api/channels",
        json={
            "name": "Phoenix floor",
            "scope_type": "office",
            "scope_office_id": world["phoenix"].id,
        },
    )
    assert response.status_code == 201, response.json()
    assert response.json()["audience_label"] == "Phoenix"


def test_a_screen_inherits_the_channels_audience(client, db, world, sign_in):
    """The point of putting it on the channel: a wall is right by default."""
    sign_in(world["admin"])
    channel = client.post(
        "/api/channels",
        json={
            "name": "Phoenix floor",
            "scope_type": "office",
            "scope_office_id": world["phoenix"].id,
        },
    ).json()

    body = add(client, channel["id"], kind="achievements").json()
    assert body["screens"][0]["scope_type"] is None
    assert body["screens"][0]["audience_label"] == "Phoenix"


def test_a_screen_can_override_the_audience(client, db, world, sign_in):
    """The deliberate exception: the company board on a floor that otherwise
    shows only itself."""
    sign_in(world["admin"])
    channel = client.post(
        "/api/channels",
        json={
            "name": "Phoenix floor",
            "scope_type": "office",
            "scope_office_id": world["phoenix"].id,
        },
    ).json()

    body = add(
        client, channel["id"], kind="achievements", scope_type="organization"
    ).json()
    assert body["screens"][0]["audience_label"] == "Everyone"


def test_a_board_about_another_office_is_refused(client, db, world, sign_in):
    """"Nothing shows up and I do not know why" is the worst way to learn
    this, so it is refused when it is authored."""
    sign_in(world["admin"])
    channel = client.post(
        "/api/channels",
        json={
            "name": "Phoenix floor",
            "scope_type": "office",
            "scope_office_id": world["phoenix"].id,
        },
    ).json()
    dallas_board = make_board(
        client, world, name="Dallas calls",
        scope_type="office", scope_office_id=world["dallas"].id,
    )

    response = add(client, channel["id"], kind="leaderboard", leaderboard_id=dallas_board)

    assert response.status_code == 400
    assert "different office" in response.json()["detail"]


def test_an_unknown_office_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post(
        "/api/channels",
        json={"name": "x", "scope_type": "office", "scope_office_id": 999999},
    ).status_code == 404


def test_a_scope_without_its_pointer_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post(
        "/api/channels", json={"name": "x", "scope_type": "office"}
    ).status_code == 404


# ── The separation, end to end ───────────────────────────────────────────────


def wall(client, db, world, channel_id):
    """A display on this channel, read the way a television reads it."""
    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel_id}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    return client.get(f"/api/display/{token}").json()


def test_one_offices_numbers_do_not_spill_onto_anothers_wall(
    client, db, org, world, sign_in, make_fact, make_user
):
    """The whole reason the audience exists.

    An organization-wide board on a Phoenix channel shows Phoenix's rows only.
    Without this, a Dallas rep's name scrolls past on a wall in Phoenix.
    """
    dallas_rep = make_user("agent", world["smb"], name="Dallas Rep")
    make_fact(world["metric"], world["alice"], 10, WHEN, office_id=world["phoenix"].id)
    make_fact(world["metric"], dallas_rep, 99, WHEN, office_id=world["dallas"].id)

    sign_in(world["admin"])
    channel = client.post(
        "/api/channels",
        json={
            "name": "Phoenix floor",
            "scope_type": "office",
            "scope_office_id": world["phoenix"].id,
        },
    ).json()
    add(client, channel["id"], kind="leaderboard",
        leaderboard_id=make_board(client, world, name="Everyone"))

    body = wall(client, db, world, channel["id"])

    names = [e["entity_name"] for e in body["slides"][0]["entries"]]
    assert names == ["Alice"]


def test_an_override_lets_the_company_board_through(
    client, db, org, world, sign_in, make_fact, make_user
):
    """The deliberate exception — "unless specifically set up to do so"."""
    dallas_rep = make_user("agent", world["smb"], name="Dallas Rep")
    make_fact(world["metric"], world["alice"], 10, WHEN, office_id=world["phoenix"].id)
    make_fact(world["metric"], dallas_rep, 99, WHEN, office_id=world["dallas"].id)

    sign_in(world["admin"])
    channel = client.post(
        "/api/channels",
        json={
            "name": "Phoenix floor",
            "scope_type": "office",
            "scope_office_id": world["phoenix"].id,
        },
    ).json()
    add(client, channel["id"], kind="leaderboard",
        leaderboard_id=make_board(client, world, name="Company wide"),
        scope_type="organization")

    body = wall(client, db, world, channel["id"])

    names = {e["entity_name"] for e in body["slides"][0]["entries"]}
    assert names == {"Alice", "Dallas Rep"}


def test_recent_wins_are_filtered_by_office_too(
    client, db, org, world, sign_in, make_user
):
    """The clearest leak before this existed: the wins panel showed the whole
    organization, so Dallas watched Phoenix's news scroll past."""
    from app import events, notifications

    dallas_rep = make_user("agent", world["smb"], name="Dallas Rep")
    for person in (world["alice"], dallas_rep):
        notifications.emit(
            db,
            org_id=org.id,
            user_id=person.id,
            event=events.RECOGNITION,
            subject_type="user",
            subject_id=person.id,
            title=f"{person.full_name} did well",
            about_name=person.full_name,
            about_user_id=person.id,
            created_by_user_id=world["admin"].id,
            **notifications.where_of(db, person.id),
        )
    db.commit()

    sign_in(world["admin"])
    channel = client.post(
        "/api/channels",
        json={
            "name": "Phoenix floor",
            "scope_type": "office",
            "scope_office_id": world["phoenix"].id,
        },
    ).json()
    add(client, channel["id"], kind="achievements")

    body = wall(client, db, world, channel["id"])

    shown = [a["about_name"] for a in body["slides"][0]["achievements"]]
    assert shown == ["Alice"]


def test_a_win_stays_on_the_wall_it_was_earned_on(
    client, db, org, world, sign_in, make_user
):
    """Snapshotted, not joined. Somebody transferring to Dallas must not take
    last month's Phoenix win with them onto the Dallas wall."""
    from app import events, notifications

    notifications.emit(
        db,
        org_id=org.id,
        user_id=world["alice"].id,
        event=events.RECOGNITION,
        subject_type="user",
        subject_id=world["alice"].id,
        title="Great save",
        about_name="Alice",
        about_user_id=world["alice"].id,
        created_by_user_id=world["admin"].id,
        **notifications.where_of(db, world["alice"].id),
    )
    # And then she moves.
    world["alice"].team_id = world["smb"].id
    db.commit()

    sign_in(world["admin"])
    phoenix_channel = client.post(
        "/api/channels",
        json={
            "name": "Phoenix floor",
            "scope_type": "office",
            "scope_office_id": world["phoenix"].id,
        },
    ).json()
    add(client, phoenix_channel["id"], kind="achievements")

    body = wall(client, db, world, phoenix_channel["id"])

    assert [a["about_name"] for a in body["slides"][0]["achievements"]] == ["Alice"]


def test_a_wall_never_relabels_a_board(db):
    """`_entrants_filter` directly, because the API cannot reach this.

    A board pinned to Dallas on a Phoenix wall is refused when it is authored,
    so the two can only pin the same axis when they agree. The rule is still
    worth stating: **the board's own scope wins**, because a board titled
    "Dallas calls" quietly showing Phoenix numbers would be actively
    misleading — worse than the spillover the audience exists to prevent.

    Tested here rather than left as an unreachable branch nobody has an opinion
    about.
    """
    from app.leaderboards import _entrants_filter
    from app.models import Leaderboard

    board = Leaderboard(scope_type="office", scope_office_id=7)
    assert _entrants_filter(board, {"office_id": 99, "team_id": None})["office_id"] == 7

    # An axis the board leaves open is the wall's to fill, which is the case
    # that actually happens.
    open_board = Leaderboard(scope_type="organization")
    narrowed = _entrants_filter(open_board, {"office_id": 99, "team_id": None})
    assert narrowed["office_id"] == 99

    # Different axes simply both apply.
    team_board = Leaderboard(scope_type="team", scope_team_id=3)
    both = _entrants_filter(team_board, {"office_id": 99, "team_id": None})
    assert (both["team_id"], both["office_id"]) == (3, 99)


def test_an_unnamed_goal_is_named_after_its_metric(client, db, org, world, sign_in):
    """Most goals have no name of their own.

    The label used to fall through to "Deleted goal" for any of them, so a
    perfectly live screen read as broken — and three of five goals in the dev
    data were in exactly that state.
    """
    goal = Goal(
        organization_id=org.id,
        metric_definition_id=world["metric"].id,
        subject_type="user",
        subject_user_id=world["alice"].id,
        target_value=100,
        period_type="month",
        period_anchor=WHEN.date().replace(day=1),
    )
    db.add(goal)
    db.flush()

    sign_in(world["admin"])
    channel = make_channel(client)
    body = add(client, channel["id"], kind="goal", goal_id=goal.id).json()

    assert body["screens"][0]["label"] == "Calls Made — Alice"


def test_a_team_goal_names_the_team(client, db, org, world, sign_in):
    goal = Goal(
        organization_id=org.id,
        metric_definition_id=world["metric"].id,
        subject_type="team",
        subject_team_id=world["enterprise"].id,
        target_value=100,
        period_type="month",
        period_anchor=WHEN.date().replace(day=1),
    )
    db.add(goal)
    db.flush()

    sign_in(world["admin"])
    channel = make_channel(client)
    body = add(client, channel["id"], kind="goal", goal_id=goal.id).json()

    assert body["screens"][0]["label"] == "Calls Made — Enterprise"


# ── Only what belongs here ───────────────────────────────────────────────────


def make_goal_for(db, org, world, *, user=None, team=None, name=None):
    goal = Goal(
        organization_id=org.id,
        metric_definition_id=world["metric"].id,
        subject_type="team" if team else "user",
        subject_user_id=None if team else user.id,
        subject_team_id=team.id if team else None,
        target_value=100,
        period_type="month",
        period_anchor=WHEN.date().replace(day=1),
        name=name,
    )
    db.add(goal)
    db.flush()
    return goal


def phoenix_channel(client, world):
    return client.post(
        "/api/channels",
        json={
            "name": "Phoenix floor",
            "scope_type": "office",
            "scope_office_id": world["phoenix"].id,
        },
    ).json()


def test_a_goal_from_another_office_is_refused(
    client, db, org, world, sign_in, make_user
):
    """The hole this closes.

    A goal names its own subject, so the audience filter has nothing to narrow
    — a Dallas agent's goal on a Phoenix channel rendered Dallas numbers on a
    Phoenix wall, at full size, with their name on it.
    """
    dallas_rep = make_user("agent", world["smb"], name="Dallas Rep")
    goal = make_goal_for(db, org, world, user=dallas_rep)

    sign_in(world["admin"])
    channel = phoenix_channel(client, world)
    response = add(client, channel["id"], kind="goal", goal_id=goal.id)

    assert response.status_code == 400
    assert "different office or team" in response.json()["detail"]


def test_a_goal_from_this_office_is_fine(client, db, org, world, sign_in):
    goal = make_goal_for(db, org, world, user=world["alice"])

    sign_in(world["admin"])
    channel = phoenix_channel(client, world)

    assert add(client, channel["id"], kind="goal", goal_id=goal.id).status_code == 201


def test_a_team_goal_belongs_to_its_teams_office(client, db, org, world, sign_in):
    """Enterprise sits in Phoenix, so its goal is at home on the Phoenix wall."""
    goal = make_goal_for(db, org, world, team=world["enterprise"])

    sign_in(world["admin"])
    channel = phoenix_channel(client, world)

    assert add(client, channel["id"], kind="goal", goal_id=goal.id).status_code == 201


def test_anything_goes_on_an_organization_wide_channel(
    client, db, org, world, sign_in, make_user
):
    """Org-wide is related to everything — reception shows every floor."""
    dallas_rep = make_user("agent", world["smb"], name="Dallas Rep")
    goal = make_goal_for(db, org, world, user=dallas_rep)

    sign_in(world["admin"])
    channel = make_channel(client, name="Reception")

    assert add(client, channel["id"], kind="goal", goal_id=goal.id).status_code == 201


def test_the_picker_only_offers_what_belongs(
    client, db, org, world, sign_in, make_user
):
    """The picker and the validation are the same rule, served once.

    Two copies would drift, and the quiet version of that is a picker omitting
    something the server would have accepted.
    """
    dallas_rep = make_user("agent", world["smb"], name="Dallas Rep")
    make_goal_for(db, org, world, user=world["alice"], name="Phoenix goal")
    make_goal_for(db, org, world, user=dallas_rep, name="Dallas goal")

    sign_in(world["admin"])
    make_board(client, world, name="Everyone")
    make_board(client, world, name="Phoenix board",
               scope_type="office", scope_office_id=world["phoenix"].id)
    make_board(client, world, name="Dallas board",
               scope_type="office", scope_office_id=world["dallas"].id)

    channel = phoenix_channel(client, world)
    offered = client.get(f"/api/channels/{channel['id']}/eligible").json()

    assert [b["name"] for b in offered["leaderboards"]] == ["Everyone", "Phoenix board"]
    assert [g["name"] for g in offered["goals"]] == ["Phoenix goal — Alice"]


def test_a_template_asks_what_a_channel_for_everyone_may_show(client, db, org, world, sign_in):
    """Before the channel exists (7.9): the template's confirm step lists its
    slides first. Everything published to everyone, from every office."""
    sign_in(world["admin"])
    make_board(client, world, name="Everyone")
    make_board(client, world, name="Phoenix board",
               scope_type="office", scope_office_id=world["phoenix"].id)

    offered = client.get("/api/channels/eligible").json()

    assert [b["name"] for b in offered["leaderboards"]] == ["Everyone", "Phoenix board"]
    assert client.get("/api/channels").json() == []


def test_the_picker_says_where_each_thing_belongs(client, db, org, world, sign_in):
    """"Everyone" beside a board is the difference between a filtered list and
    one that looks arbitrary."""
    sign_in(world["admin"])
    make_board(client, world, name="Everyone")

    channel = phoenix_channel(client, world)
    offered = client.get(f"/api/channels/{channel['id']}/eligible").json()

    assert offered["leaderboards"][0]["belongs_to"] == "Everyone"


def test_a_wall_skips_a_goal_that_belongs_somewhere_else(
    client, db, org, world, sign_in, make_user
):
    """Belt and braces for rows written before the check existed.

    Inserted straight into the table, because the API now refuses it.
    """
    dallas_rep = make_user("agent", world["smb"], name="Dallas Rep")
    goal = make_goal_for(db, org, world, user=dallas_rep)

    sign_in(world["admin"])
    channel = phoenix_channel(client, world)
    db.add(
        ChannelScreen(
            channel_id=channel["id"], position=0, kind="goal",
            dwell_seconds=20, goal_id=goal.id,
        )
    )
    db.commit()

    body = wall(client, db, world, channel["id"])
    assert body["slides"] == []


def test_a_team_channel_refuses_another_teams_goal(
    client, db, org, world, sign_in, make_user
):
    """A wall for one team, in a shared room. Nothing covered a team-scoped
    channel until a mutation removed the team comparison and every test still
    passed."""
    smb_rep = make_user("agent", world["smb"], name="SMB Rep")
    goal = make_goal_for(db, org, world, user=smb_rep)

    sign_in(world["admin"])
    channel = client.post(
        "/api/channels",
        json={
            "name": "Enterprise pod",
            "scope_type": "team",
            "scope_team_id": world["enterprise"].id,
        },
    ).json()

    response = add(client, channel["id"], kind="goal", goal_id=goal.id)
    assert response.status_code == 400


def test_a_team_channel_takes_its_own_teams_goal(client, db, org, world, sign_in):
    goal = make_goal_for(db, org, world, user=world["alice"])

    sign_in(world["admin"])
    channel = client.post(
        "/api/channels",
        json={
            "name": "Enterprise pod",
            "scope_type": "team",
            "scope_team_id": world["enterprise"].id,
        },
    ).json()

    assert add(client, channel["id"], kind="goal", goal_id=goal.id).status_code == 201


def test_a_team_channel_still_takes_the_company_board(client, db, org, world, sign_in):
    """Org-wide goes anywhere — that is the one thing the rule must not
    tighten."""
    sign_in(world["admin"])
    board = make_board(client, world, name="Everyone")
    channel = client.post(
        "/api/channels",
        json={
            "name": "Enterprise pod",
            "scope_type": "team",
            "scope_team_id": world["enterprise"].id,
        },
    ).json()

    assert add(
        client, channel["id"], kind="leaderboard", leaderboard_id=board
    ).status_code == 201


def test_a_goal_for_somebody_on_no_team_stays_off_office_walls(
    client, db, org, world, sign_in, make_user
):
    """"Tied to nowhere" has two meanings and they are opposites.

    A company board is tied to nowhere because it is *about everywhere*. An
    unplaced person is tied to nowhere because they are *placed nowhere* — and
    they are not in Phoenix, so their number does not belong on Phoenix's wall.
    Collapsing the two put them on every screen in the building.
    """
    loner = make_user("agent", None, name="Loner")
    goal = make_goal_for(db, org, world, user=loner)

    sign_in(world["admin"])
    office = phoenix_channel(client, world)
    everywhere = make_channel(client, name="Reception")

    assert add(client, office["id"], kind="goal", goal_id=goal.id).status_code == 400
    assert add(client, everywhere["id"], kind="goal", goal_id=goal.id).status_code == 201


# ── Where a screen may be watched from ───────────────────────────────────────


def locked_channel(client, ips=("203.0.113.0/24",)):
    return client.post(
        "/api/channels", json={"name": "Locked", "allowed_ips": list(ips)}
    ).json()


def token_for(client, channel_id):
    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel_id}
    ).json()
    return created["url"].rsplit("/", 1)[-1]


def test_a_channel_is_watchable_from_anywhere_by_default(client, db, world, sign_in):
    """The only safe default. A deployment behind a NAT nobody wrote down would
    otherwise blank every screen the moment somebody saved a channel."""
    sign_in(world["admin"])
    channel = make_channel(client)
    assert channel["allowed_ips"] == []
    assert "slides" in wall(client, db, world, channel["id"])


def test_an_allowlist_refuses_a_screen_from_outside(client, db, world, sign_in):
    """The point of the feature: a photographed URL is useless off the
    network."""
    sign_in(world["admin"])
    token = token_for(client, locked_channel(client)["id"])

    client.cookies.clear()
    response = client.get(f"/api/display/{token}")

    assert response.status_code == 403
    # An error somebody can act on, not a silent 404 that sends an admin
    # hunting a link that is not broken.
    assert "outside the network" in response.json()["detail"]


def test_a_forged_header_cannot_get_past_it(client, db, world, sign_in):
    """Anybody can set `X-Forwarded-For`. Believed on a direct connection, the
    allowlist would look like protection and provide none."""
    sign_in(world["admin"])
    token = token_for(client, locked_channel(client)["id"])

    client.cookies.clear()
    assert client.get(
        f"/api/display/{token}", headers={"x-forwarded-for": "203.0.113.9"}
    ).status_code == 403


def test_a_bad_entry_is_refused_rather_than_dropped(client, db, world, sign_in):
    """A silently ignored entry means a screen somebody thinks is protected is
    not — the opposite of the trusted-proxy setting, where a typo must not stop
    the application booting."""
    sign_in(world["admin"])
    response = client.post(
        "/api/channels",
        json={"name": "Bad", "allowed_ips": ["203.0.113.4", "not-an-address"]},
    )

    assert response.status_code == 422
    assert "not an address or range" in response.json()["detail"]


def test_entries_are_trimmed_and_blanks_dropped(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = client.post(
        "/api/channels",
        json={"name": "Spaced", "allowed_ips": ["  203.0.113.4 ", "", "10.0.0.0/8"]},
    ).json()

    assert channel["allowed_ips"] == ["203.0.113.4", "10.0.0.0/8"]


def test_clearing_it_opens_the_channel_again(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = locked_channel(client)

    reopened = client.patch(
        f"/api/channels/{channel['id']}",
        json={"name": "Locked", "allowed_ips": []},
    ).json()

    assert reopened["allowed_ips"] == []


def test_a_revoked_token_is_still_a_404_not_a_403(client, db, world, sign_in):
    """The allowlist is the one place a refusal says why. Everything about the
    *token* stays indistinguishable, so probing still tells you nothing."""
    sign_in(world["admin"])
    channel = locked_channel(client)
    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel["id"]}
    ).json()
    client.post(f"/api/displays/{created['id']}/revoke")
    token = created["url"].rsplit("/", 1)[-1]

    client.cookies.clear()
    assert client.get(f"/api/display/{token}").status_code == 404


def test_an_unnamed_goal_on_the_wall_leads_with_whose_it_is(client, db, org, world, sign_in):
    """"Sales Feed Amount Today" in the biggest type, with the person in the
    smallest underneath, told a room nothing about whose target it was."""
    goal = Goal(
        organization_id=org.id,
        metric_definition_id=world["metric"].id,
        subject_type="user",
        subject_user_id=world["alice"].id,
        target_value=100,
        period_type="month",
        period_anchor=WHEN.date().replace(day=1),
    )
    db.add(goal)
    db.flush()
    sign_in(world["admin"])
    channel = make_channel(client)
    add(client, channel["id"], kind="goal", goal_id=goal.id)

    slide = wall(client, db, world, channel["id"])["slides"][0]

    assert slide["title"] == "Alice — Calls Made"
    assert "Alice" not in slide["subtitle"]


def test_a_named_goal_keeps_its_name_and_says_whose_underneath(
    client, db, org, world, sign_in
):
    goal = Goal(
        organization_id=org.id,
        metric_definition_id=world["metric"].id,
        subject_type="user",
        subject_user_id=world["alice"].id,
        target_value=100,
        period_type="month",
        period_anchor=WHEN.date().replace(day=1),
        name="Road to 100",
    )
    db.add(goal)
    db.flush()
    sign_in(world["admin"])
    channel = make_channel(client)
    add(client, channel["id"], kind="goal", goal_id=goal.id)

    slide = wall(client, db, world, channel["id"])["slides"][0]

    assert slide["title"] == "Road to 100"
    assert slide["subtitle"].startswith("Alice · ")


# ── Previewing a slide before it is saved ────────────────────────────────────


def preview(client, channel_id, **payload):
    return client.post(f"/api/channels/{channel_id}/screens/preview", json=payload)


def test_a_slide_previews_as_the_wall_draws_it_and_is_not_saved(
    client, db, world, sign_in
):
    sign_in(world["admin"])
    channel = make_channel(client)
    board = make_board(client, world, name="Calls this month")

    response = preview(client, channel["id"], kind="leaderboard", leaderboard_id=board)

    assert response.status_code == 200, response.json()
    assert response.json()["kind"] == "leaderboard"
    assert response.json()["title"] == "Calls this month"
    assert "appearance" in response.json()
    assert db.scalar(select(func.count(ChannelScreen.id))) == 0


def test_a_comparison_previews_and_leaves_no_panels_behind(client, db, world, sign_in):
    from app.models import ChannelScreenBoard

    sign_in(world["admin"])
    channel = make_channel(client)
    boards = [make_board(client, world, name=name) for name in ("Calls", "Emails")]

    response = preview(client, channel["id"], kind="comparison", leaderboard_ids=boards)

    assert response.status_code == 200, response.json()
    assert db.scalar(select(func.count(ChannelScreenBoard.channel_screen_id))) == 0
    assert db.scalar(select(func.count(ChannelScreen.id))) == 0


def test_a_preview_refuses_what_saving_refuses(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    secret = make_board(client, world, name="Secret", visibility="private")

    assert preview(
        client, channel["id"], kind="leaderboard", leaderboard_id=secret
    ).status_code == 400
    assert preview(client, channel["id"], kind="message", body="no title").status_code == 422


def test_a_message_previews(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)

    response = preview(client, channel["id"], kind="message", title="Well done all")

    assert response.json()["title"] == "Well done all"


def test_only_an_admin_can_preview_a_slide(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    sign_in(world["manager"])

    assert preview(client, channel["id"], kind="message", title="Hi").status_code == 403


def test_recent_wins_carry_the_figure_and_stop_calling_old_news_recent(
    client, db, org, world, sign_in
):
    """7.9: "Alice — Big deal" said neither the number nor that it was news.
    Each win brings its figure, and a list whose newest is over a day old is
    "Latest wins", not "Recent wins"."""
    from datetime import UTC, datetime, timedelta

    from app import events, notifications
    from app.models import Notification

    notifications.emit(
        db,
        org_id=org.id,
        user_id=world["alice"].id,
        event=events.RECOGNITION,
        subject_type="user",
        subject_id=world["alice"].id,
        title="Big deal",
        about_name="Alice",
        about_user_id=world["alice"].id,
        figure="$500",
        **notifications.where_of(db, world["alice"].id),
    )
    db.commit()

    sign_in(world["admin"])
    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    add(client, channel["id"], kind="achievements")

    slide = wall(client, db, world, channel["id"])["slides"][0]
    assert slide["title"] == "Recent wins"
    assert slide["achievements"][0]["figure"] == "$500"

    row = db.query(Notification).filter_by(title="Big deal").one()
    row.created_at = datetime.now(UTC) - timedelta(days=3)
    db.commit()

    sign_in(world["admin"])
    assert wall(client, db, world, channel["id"])["slides"][0]["title"] == "Latest wins"


def test_the_editor_gets_every_slide_drawn_as_the_tvs_draw_it(client, db, org, world, sign_in):
    """8.5: thumbnails and "Play rotation" in the channel editor."""
    sign_in(world["admin"])
    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    board = make_board(client, world, name="Everyone")
    add(client, channel["id"], kind="leaderboard", leaderboard_id=board)
    add(client, channel["id"], kind="message", title="Pizza at four", body="In the kitchen")

    slides = client.get(f"/api/channels/{channel['id']}/slides").json()

    assert [s["slide"]["kind"] for s in slides] == ["leaderboard", "message"]
    assert slides[1]["slide"]["title"] == "Pizza at four"


def test_a_delete_can_say_which_channels_lose_it(client, db, org, world, sign_in):
    """8.6: deleting a board takes its slides off every TV, silently — the
    foreign keys cascade. The confirm asks this first."""
    sign_in(world["admin"])
    board = make_board(client, world, name="Everyone")
    floor = client.post("/api/channels", json={"name": "Sales floor"}).json()
    lobby = client.post("/api/channels", json={"name": "Lobby"}).json()
    add(client, floor["id"], kind="leaderboard", leaderboard_id=board)
    add(client, floor["id"], kind="leaderboard", leaderboard_id=board, dwell_seconds=30)
    add(client, lobby["id"], kind="leaderboard", leaderboard_id=board)

    using = client.get("/api/channels/using", params={"kind": "leaderboard", "id": board}).json()

    assert [(u["channel_name"], u["slides"]) for u in using] == [("Lobby", 1), ("Sales floor", 2)]
    assert client.get("/api/channels/using", params={"kind": "goal", "id": 999}).json() == []


def test_an_empty_calendar_board_brings_last_periods_top_three(
    client, db, org, world, sign_in, make_fact
):
    """10.1: on the first of the month a list board was a blank TV. With
    nothing this month, the slide carries last month's top three."""
    from app import periods

    this = periods.resolve(org, "month", periods.today(org))
    last = periods.previous(org, this)
    make_fact(world["metric"], world["alice"], 40, last.start + timedelta(days=3))
    db.commit()
    sign_in(world["admin"])
    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    add(client, channel["id"], kind="leaderboard", leaderboard_id=make_board(client, world, name="Monthly"))

    slide = wall(client, db, world, channel["id"])["slides"][0]

    assert slide["previous"]["label"] == last.label
    assert [(e["entity_name"], float(e["value"])) for e in slide["previous"]["entries"]] == [("Alice", 40.0)]

    # Something this month: no fallback.
    make_fact(world["metric"], world["alice"], 5, within_this_month())
    db.commit()
    sign_in(world["admin"])
    assert wall(client, db, world, channel["id"])["slides"][0]["previous"] is None


def test_a_slide_whose_board_is_archived_says_so(client, db, org, world, sign_in):
    """P3-2: it left the rotation and the editor called it "Nothing to show
    yet". It says archived, so it can be restored from there."""
    sign_in(world["admin"])
    board = make_board(client, world, name="Everyone")
    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    add(client, channel["id"], kind="leaderboard", leaderboard_id=board)

    client.post(f"/api/leaderboards/{board}/archive")
    screens = next(c for c in client.get("/api/channels").json() if c["id"] == channel["id"])["screens"]
    assert screens[0]["archived"] is True

    client.post(f"/api/leaderboards/{board}/restore")
    screens = next(c for c in client.get("/api/channels").json() if c["id"] == channel["id"])["screens"]
    assert screens[0]["archived"] is False


def test_a_slide_says_when_its_numbers_are_from_once_they_are_old(
    client, db, org, world, sign_in, make_fact
):
    """10.6: a TV showed September's numbers under "Last 30 days" with no hint.
    Over a day old, the slide says when they are from; fresh, it says nothing."""
    make_fact(world["metric"], world["alice"], 10, datetime.now(UTC) - timedelta(days=3))
    db.commit()
    sign_in(world["admin"])
    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    board = make_board(client, world, name="Rolling", period_type="rolling_30")
    add(client, channel["id"], kind="leaderboard", leaderboard_id=board)

    assert wall(client, db, world, channel["id"])["slides"][0]["as_of"]

    make_fact(world["metric"], world["alice"], 1, datetime.now(UTC) - timedelta(hours=2))
    db.commit()
    sign_in(world["admin"])
    assert wall(client, db, world, channel["id"])["slides"][0]["as_of"] is None


def test_a_screen_docker_has_hidden_is_told_why(client, db, world, sign_in, monkeypatch):
    """P6-1: on Docker Desktop every screen arrives as Docker's gateway, so the
    list cannot be checked. Still refused, and said so in words."""
    from app.routers import display_feed

    sign_in(world["admin"])
    token = token_for(client, locked_channel(client)["id"])
    client.cookies.clear()
    monkeypatch.setattr(display_feed, "real_client_ip", lambda *a, **k: "172.21.0.1")
    monkeypatch.setattr(display_feed, "hidden_by_docker", lambda address: address == "172.21.0.1")

    response = client.get(f"/api/display/{token}")
    assert response.status_code == 403
    assert "cannot see screens' addresses" in response.json()["detail"]


# ── Picture and video screens that fill the TV (Phase 26) ────────────────────


def _stored(db, org, content_type, data):
    from app import assets

    return assets.keep(db, org.id, data, content_type=content_type).sha256


def test_a_picture_from_the_library_fills_the_screen(client, db, org, world, sign_in):
    sign_in(world["admin"])
    picture = _stored(db, org, "image/png", b"png-bytes")
    db.commit()
    channel = make_channel(client)
    shown = preview(client, channel["id"], kind="image", url=f"image:{picture}").json()
    assert (shown["media_kind"], shown["media_digest"], shown["fit"]) == ("image", picture, "cover")
    shown = preview(client, channel["id"], kind="image", url=f"image:{picture}", fit="contain").json()
    assert shown["fit"] == "contain"


def test_a_youtube_screen_starts_where_told_and_plays_as_long_as_told(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    reply = add(
        client, channel["id"], kind="video", url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        media_start_seconds=40, dwell_seconds=60,
    )
    assert reply.status_code == 201, reply.text
    screen = reply.json()["screens"][-1]
    assert (screen["media_start_seconds"], screen["dwell_seconds"]) == (40, 60)


def test_a_long_video_may_play_for_up_to_an_hour(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    url = "https://youtu.be/dQw4w9WgXcQ"
    assert add(client, channel["id"], kind="video", url=url, dwell_seconds=3600).status_code == 201
    assert add(client, channel["id"], kind="video", url=url, dwell_seconds=3601).status_code == 422


def test_a_video_from_the_library(client, db, org, world, sign_in):
    sign_in(world["admin"])
    clip = _stored(db, org, "video/mp4", b"mp4-bytes")
    db.commit()
    channel = make_channel(client)
    shown = preview(client, channel["id"], kind="video", url=f"video:{clip}", media_start_seconds=5).json()
    assert (shown["media_kind"], shown["media_digest"], shown["media_start_seconds"]) == ("video", clip, 5)


def test_the_right_sort_of_thing_for_each_screen(client, db, org, world, sign_in):
    sign_in(world["admin"])
    picture = _stored(db, org, "image/png", b"png-bytes")
    db.commit()
    channel = make_channel(client)
    youtube = "https://youtu.be/dQw4w9WgXcQ"
    assert "Video kind" in add(client, channel["id"], kind="image", url=youtube).json()["detail"]
    assert "Picture kind" in add(client, channel["id"], kind="video", url="https://x.example/a.png").json()["detail"]
    assert add(client, channel["id"], kind="video", url=f"image:{picture}").status_code == 422


def test_the_preview_says_where_the_background_comes_from(client, db, world, sign_in):
    sign_in(world["admin"])
    board = make_board(client, world, name="Sales floor")
    client.patch(
        f"/api/leaderboards/{board}",
        json={"appearance": {"background": {"kind": "solid", "color": "#112233"}}},
    )
    channel = make_channel(client)
    shown = preview(client, channel["id"], kind="leaderboard", leaderboard_id=board).json()
    assert shown["background_from"] == "the leaderboard “Sales floor”"
    assert shown["inherited"]["background"]["color"] == "#112233"
    # With a background of its own, the inherited one is still what it would
    # fall back to.
    own = preview(
        client, channel["id"], kind="leaderboard", leaderboard_id=board,
        appearance={"background": {"kind": "solid", "color": "#445566"}},
    ).json()
    assert own["appearance"]["background"]["color"] == "#445566"
    assert own["inherited"]["background"]["color"] == "#112233"


def test_with_nothing_set_anywhere_the_background_comes_from_nowhere(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    shown = preview(client, channel["id"], kind="message", title="Hello").json()
    assert shown["background_from"] == ""
