"""Wall displays, and the only unauthenticated endpoint in the product.

The token in the URL is the entire credential, so what it does *not* reach
matters as much as what it does.
"""

from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import within_this_month
from sqlalchemy import select

from app.models import AuditLog, Channel, ChannelScreen, Display, Leaderboard

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
    db.flush()

    channel = Channel(organization_id=org.id, name="Phoenix wall")
    db.add(channel)
    db.flush()

    return {
        "channel": channel,
        "phoenix": phoenix,
        "dallas": dallas,
        "enterprise": enterprise,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "teammate": make_user("agent", enterprise, name="Teammate"),
        "metric": make_metric("calls_made"),
    }


def make_display(client, world, sign_in, **overrides):
    sign_in(world["admin"])
    body = {"name": "Wall screen", "channel_id": world["channel"].id, **overrides}
    response = client.post("/api/displays", json=body)
    assert response.status_code == 201, response.json()
    return response.json()


def put_on_channel(db, world, board_id, **overrides):
    """Add a board to the fixture channel.

    A channel is authored now, so a board reaching a wall is something a test
    has to *do* rather than something that follows from a flag.
    """
    screen = ChannelScreen(
        channel_id=world["channel"].id,
        position=overrides.pop("position", 0),
        kind="leaderboard",
        dwell_seconds=20,
        leaderboard_id=board_id,
        **overrides,
    )
    db.add(screen)
    db.flush()
    return screen


def token_of(created: dict) -> str:
    return created["url"].rsplit("/", 1)[-1]


def make_board(client, world, sign_in, **overrides):
    sign_in(world["admin"])
    response = client.post(
        "/api/leaderboards",
        json={
            "name": "Board",
            "metric_id": world["metric"].id,
            "period_type": "month",
            "visibility": "org",
            "is_tv_enabled": True,
            **overrides,
        },
    )
    assert response.status_code == 201, response.json()
    return response.json()["id"]


# ── Issuing ──────────────────────────────────────────────────────────────────


def test_creating_a_display_returns_its_url(client, db, world, sign_in):
    created = make_display(client, world, sign_in)
    assert "/display/" in created["url"]
    assert len(token_of(created)) > 30


def test_two_displays_never_share_a_token(client, db, world, sign_in):
    """The token is the whole credential, so a collision would be one screen
    showing another office's channel."""
    first = make_display(client, world, sign_in)
    second = make_display(client, world, sign_in, name="Second screen")
    assert token_of(first) != token_of(second)


def test_the_url_stays_retrievable(client, db, world, sign_in):
    """Deliberately unlike every other token here.

    A TV gets set up days after the link was issued, by whoever is standing
    next to it. Hashing made that impossible and the practical result was
    links written down somewhere far less safe than this table.
    """
    created = make_display(client, world, sign_in)
    listed = client.get("/api/displays").json()
    assert listed[0]["url"] == created["url"]

    # And it still works — a listed URL that did not open anything would be
    # worse than not listing it.
    assert client.get(f"/api/display/{token_of(listed[0])}").status_code == 200


def test_an_agent_cannot_read_the_links(client, db, world, sign_in):
    """The reason the readable token is affordable is that only an admin can
    list them. If that slipped, every agent would hold every channel."""
    sign_in(world["admin"])
    make_display(client, world, sign_in)
    sign_in(world["agent"] if "agent" in world else world["teammate"])
    assert client.get("/api/displays").status_code == 403


def test_only_an_admin_can_issue_one(client, db, world, sign_in):
    """A display URL is a standing credential anyone in the room can read off
    the screen."""
    sign_in(world["manager"])
    assert client.post("/api/displays", json={"name": "Nope"}).status_code == 403
    sign_in(world["teammate"])
    assert client.get("/api/displays").status_code == 403


def test_an_unknown_channel_is_a_404(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post(
        "/api/displays", json={"name": "x", "channel_id": 999999}
    ).status_code == 404


def test_a_display_needs_a_channel(client, db, world, sign_in):
    """No default. Through Phase 1 a missing office meant "everything"; a
    channel is something somebody built, so there is nothing to fall back to."""
    sign_in(world["admin"])
    assert client.post("/api/displays", json={"name": "x"}).status_code == 422


# ── The feed ─────────────────────────────────────────────────────────────────


def test_the_feed_needs_no_session(client, db, world, make_fact, sign_in):
    """The whole point: a TV has no keyboard and nobody to log it in."""
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    put_on_channel(db, world, make_board(client, world, sign_in))
    created = make_display(client, world, sign_in)

    client.cookies.clear()
    response = client.get(f"/api/display/{token_of(created)}")
    assert response.status_code == 200
    assert response.json()["slides"][0]["entries"][0]["entity_name"] == "Teammate"


def test_a_revoked_token_stops_working_immediately(client, db, world, sign_in):
    created = make_display(client, world, sign_in)
    display_id = created["id"]

    client.cookies.clear()
    assert client.get(f"/api/display/{token_of(created)}").status_code == 200

    sign_in(world["admin"])
    client.post(f"/api/displays/{display_id}/revoke")

    client.cookies.clear()
    assert client.get(f"/api/display/{token_of(created)}").status_code == 404


def test_a_revoked_display_can_leave_the_list(client, db, world, sign_in):
    """QA-17: revoked rows stayed forever and buried the live ones."""
    created = make_display(client, world, sign_in)
    client.post(f"/api/displays/{created['id']}/revoke")

    assert client.delete(f"/api/displays/{created['id']}").status_code == 204
    assert created["id"] not in [d["id"] for d in client.get("/api/displays").json()]


@pytest.mark.parametrize("token", ["made-up", "x", "a" * 64])
def test_an_unknown_token_is_a_404(client, db, world, token):
    """404 for missing, revoked and malformed alike — a screen cannot act on
    the difference, and distinguishing them tells a prober what is real."""
    client.cookies.clear()
    assert client.get(f"/api/display/{token}").status_code == 404


def test_only_what_is_on_the_channel_appears(client, db, world, make_fact, sign_in):
    """A board reaching a wall is now something somebody *did*, not something
    that followed from a flag."""
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    on = make_board(client, world, sign_in, name="On the wall", is_tv_enabled=True)
    make_board(client, world, sign_in, name="Not on the wall", is_tv_enabled=True)
    put_on_channel(db, world, on)
    created = make_display(client, world, sign_in)

    client.cookies.clear()
    titles = [s["title"] for s in client.get(f"/api/display/{token_of(created)}").json()["slides"]]
    assert titles == ["On the wall"]


def test_screens_play_in_the_order_they_were_arranged(
    client, db, world, make_fact, sign_in
):
    """The whole point of authoring one. Phase 1 ordered by name, which nobody
    chose."""
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    first = make_board(client, world, sign_in, name="Zulu")
    second = make_board(client, world, sign_in, name="Alpha")
    put_on_channel(db, world, first, position=0)
    put_on_channel(db, world, second, position=1)
    created = make_display(client, world, sign_in)

    client.cookies.clear()
    titles = [s["title"] for s in client.get(f"/api/display/{token_of(created)}").json()["slides"]]
    assert titles == ["Zulu", "Alpha"]


def test_a_screen_that_cannot_render_is_skipped_not_blanked(
    client, db, world, make_fact, sign_in
):
    """A wall going black in front of an office reads as the product being
    broken. One missing slide out of several reads as nothing at all."""
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    good = make_board(client, world, sign_in, name="Still here")
    doomed = make_board(client, world, sign_in, name="Archived later")
    put_on_channel(db, world, good, position=0)
    put_on_channel(db, world, doomed, position=1)

    sign_in(world["admin"])
    client.post(f"/api/leaderboards/{doomed}/archive")
    created = make_display(client, world, sign_in)

    client.cookies.clear()
    body = client.get(f"/api/display/{token_of(created)}").json()
    assert [s["title"] for s in body["slides"]] == ["Still here"]


def test_a_private_board_cannot_be_put_on_a_wall(client, db, world, sign_in):
    """A wall screen has no audience control — anyone walking past reads it.
    So only a board already published to everyone is eligible."""
    sign_in(world["admin"])
    response = client.post(
        "/api/leaderboards",
        json={
            "name": "Secret", "metric_id": world["metric"].id, "period_type": "month",
            "visibility": "private", "is_tv_enabled": True,
        },
    )
    assert response.status_code == 400
    assert "anyone walking past" in response.json()["detail"]


def test_the_database_refuses_a_tv_enabled_private_board(db, org, world):
    """The CHECK constraint, not just the API — a future endpoint cannot open
    the wall screens by forgetting the rule."""
    from sqlalchemy.exc import IntegrityError

    db.add(
        Leaderboard(
            organization_id=org.id, name="Secret",
            metric_definition_id=world["metric"].id, entity_type="user",
            scope_type="organization", period_type="month",
            visibility="private", rank_method="rank", is_tv_enabled=True,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_the_feed_names_its_channel(client, db, world, sign_in):
    created = make_display(client, world, sign_in)
    client.cookies.clear()
    body = client.get(f"/api/display/{token_of(created)}").json()
    assert body["channel_name"] == "Phoenix wall"


def test_a_private_board_on_a_channel_still_never_reaches_the_wall(
    client, db, world, make_fact, sign_in
):
    """The safety property that survived from Phase 1.

    A wall has no audience control at all, so only a board published to the
    whole organization may appear on one. Checked when the slide is built as
    well as by the CHECK constraint, so relaxing either alone cannot open the
    screens.
    """
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    board = make_board(client, world, sign_in, name="Team only", is_tv_enabled=False)
    sign_in(world["admin"])
    client.patch(f"/api/leaderboards/{board}", json={"visibility": "private"})
    put_on_channel(db, world, board)
    created = make_display(client, world, sign_in)

    client.cookies.clear()
    assert client.get(f"/api/display/{token_of(created)}").json()["slides"] == []


def test_the_feed_carries_no_personal_identifiers(client, db, world, make_fact, sign_in):
    """It returns names, ranks and scores. An email address on a wall screen
    would be a genuine leak, and the token is readable by anyone in the room."""
    make_fact(world["metric"], world["teammate"], 10, WHEN)
    put_on_channel(db, world, make_board(client, world, sign_in))
    created = make_display(client, world, sign_in)

    client.cookies.clear()
    body = client.get(f"/api/display/{token_of(created)}").text
    assert "@" not in body
    assert world["teammate"].email not in body


def test_the_token_reaches_nothing_else(client, db, world, sign_in):
    """It is not a session. Holding one must not open any other endpoint."""
    created = make_display(client, world, sign_in)
    client.cookies.clear()

    # Even presenting it as a cookie, which is the obvious thing to try.
    client.cookies.set("gg_session", token_of(created))
    for path in ("/api/auth/me", "/api/users", "/api/leaderboards", "/api/metric-facts"):
        assert client.get(path).status_code in (401, 403), path


def test_last_seen_is_recorded_but_throttled(client, db, world, sign_in):
    """The column exists so an admin can tell a live screen from one unplugged
    months ago. Writing on every poll would be a database write every few
    seconds per screen, forever, to answer a question nobody asks daily."""
    created = make_display(client, world, sign_in)
    display_id = created["id"]
    client.cookies.clear()

    client.get(f"/api/display/{token_of(created)}")
    row = db.get(Display, display_id)
    db.refresh(row)
    first = row.last_seen_at
    assert first is not None

    client.get(f"/api/display/{token_of(created)}")
    db.refresh(row)
    assert row.last_seen_at == first  # throttled

    row.last_seen_at = datetime.now(UTC) - timedelta(hours=1)
    db.flush()
    client.get(f"/api/display/{token_of(created)}")
    db.refresh(row)
    assert row.last_seen_at > first


def test_an_empty_channel_is_not_an_error(client, db, world, sign_in):
    """A channel nobody has filled in yet. The screen has to render something
    rather than showing an error to a room."""
    created = make_display(client, world, sign_in)
    client.cookies.clear()
    body = client.get(f"/api/display/{token_of(created)}").json()
    assert body["slides"] == []
    assert body["refresh_seconds"] > 0


def test_another_organizations_display_is_not_found(client, db, org, world, sign_in):
    from app.models import Organization

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = Display(
        organization_id=other.id, name="Theirs", token="x" * 32,
        channel_id=world["channel"].id
    )
    db.add(theirs)
    db.flush()

    sign_in(world["admin"])
    assert client.post(f"/api/displays/{theirs.id}/revoke").status_code == 404
    assert client.delete(f"/api/displays/{theirs.id}").status_code == 404


# ── Audit ────────────────────────────────────────────────────────────────────


def test_issuing_and_revoking_are_audited(client, db, world, sign_in):
    """The question after a screen goes missing is "what did it have access
    to", and that needs a record of when it was issued and by whom."""
    created = make_display(client, world, sign_in)
    assert db.scalar(
        select(AuditLog).order_by(AuditLog.id.desc())
    ).action == "display.created"

    client.post(f"/api/displays/{created['id']}/revoke")
    assert db.scalar(
        select(AuditLog).order_by(AuditLog.id.desc())
    ).action == "display.revoked"


def test_the_audit_row_does_not_contain_the_token(client, db, world, sign_in):
    created = make_display(client, world, sign_in)
    latest = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert token_of(created) not in str(latest.details)


def test_a_screen_reports_its_sound_held_back_and_back_again(client, db, world, sign_in):
    """Phase 24: nobody clicks a TV, so the screen says when its browser held
    a celebration's sound back, and TVs & Channels shows it."""
    created = make_display(client, world, sign_in)
    token = token_of(created)
    client.cookies.clear()
    assert client.post(f"/api/display/{token}/sound", json={"blocked": True}).status_code == 204
    sign_in(world["admin"])
    listed = {d["id"]: d for d in client.get("/api/displays").json()}
    assert listed[created["id"]]["sound_blocked"] is True
    client.cookies.clear()
    client.post(f"/api/display/{token}/sound", json={"blocked": False})
    sign_in(world["admin"])
    listed = {d["id"]: d for d in client.get("/api/displays").json()}
    assert listed[created["id"]]["sound_blocked"] is False


def test_a_sound_report_needs_a_real_token(client, db, world):
    assert client.post("/api/display/nope/sound", json={"blocked": True}).status_code == 404
