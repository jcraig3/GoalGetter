"""A competition on a wall.

Two things to get right. **Where a contest belongs** — a competition names many
entrants, so unlike a goal there is no single team to read off it — and **what a
wall may show**, since a draft nobody has published and a cancelled contest with
no result are both a slide that says nothing.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import channels as channel_service, competitions, eligibility
from app.models import (
    Channel,
    ChannelScreen,
    Competition,
    CompetitionParticipant,
    Office,
)

STARTS = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
ENDS = datetime(2026, 8, 15, 0, 0, tzinfo=UTC)
DURING = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    phoenix = Office(organization_id=org.id, name="Phoenix")
    dallas = Office(organization_id=org.id, name="Dallas")
    # A third office with nobody in any contest. The whole point: two offices
    # competing must not put the contest on a wall belonging to a third.
    austin = Office(organization_id=org.id, name="Austin")
    db.add_all([phoenix, dallas, austin])
    db.flush()

    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    east = make_team("East")
    enterprise.office_id = phoenix.id
    smb.office_id = phoenix.id
    east.office_id = dallas.id
    db.flush()

    return {
        "phoenix": phoenix,
        "dallas": dallas,
        "austin": austin,
        "enterprise": enterprise,
        "smb": smb,
        "east": east,
        "alice": make_user("agent", enterprise, name="Alice"),
        "bob": make_user("agent", enterprise, name="Bob"),
        "carol": make_user("agent", smb, name="Carol"),
        "dan": make_user("agent", east, name="Dan"),
        "nomad": make_user("agent", None, name="Nomad"),
        "metric": make_metric("revenue", unit="currency", decimal_places=2),
    }


def make_competition(db, org, world, *, entrants, entity_type="user", **overrides):
    fields = {
        "organization_id": org.id,
        "name": "August sprint",
        "metric_definition_id": world["metric"].id,
        "entity_type": entity_type,
        "starts_at": STARTS,
        "ends_at": ENDS,
        "state": "active",
    }
    fields.update(overrides)
    competition = Competition(**fields)
    db.add(competition)
    db.flush()
    for entrant in entrants:
        db.add(
            CompetitionParticipant(
                competition_id=competition.id,
                user_id=entrant.id if entity_type == "user" else None,
                team_id=entrant.id if entity_type == "team" else None,
            )
        )
    db.flush()
    return competition


def make_channel(db, org, competition, *, scope_type="organization", **scope):
    channel = Channel(
        organization_id=org.id, name="Wall", scope_type=scope_type, **scope
    )
    db.add(channel)
    db.flush()
    db.add(
        ChannelScreen(
            channel_id=channel.id,
            position=1,
            kind="competition",
            competition_id=competition.id,
            dwell_seconds=20,
        )
    )
    db.flush()
    return channel


# ── Which offices have a stake ───────────────────────────────────────────────
#
# A competition is the only thing here with *many* subjects, so it belongs to a
# **set** of offices rather than one place. The version that collapsed a
# multi-office contest to EVERYWHERE got two offices right by accident and every
# other office wrong — EVERYWHERE fits any wall, so an uninvolved office showed
# it too.


def office_names(db, competition):
    """The involved offices as names, so a failure reads."""
    from app.models import Office

    ids = eligibility.competition_offices(db, competition)
    return sorted(
        (db.get(Office, o).name if o is not None else "no office") for o in ids
    )


def test_a_contest_within_one_team_involves_that_teams_office(db, org, world):
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]]
    )

    assert office_names(db, competition) == ["Phoenix"]
    assert eligibility.competition_teams(db, competition) == {world["enterprise"].id}


def test_a_contest_across_teams_in_one_office_involves_only_that_office(db, org, world):
    """Enterprise versus SMB is a Phoenix contest, and not Dallas's business."""
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["carol"]]
    )

    assert office_names(db, competition) == ["Phoenix"]


def test_a_contest_across_offices_involves_both_and_only_both(db, org, world):
    """**The rule this section exists for.** Phoenix versus Dallas is on in
    Phoenix and Dallas. A third office has no stake in it."""
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["dan"]]
    )

    assert office_names(db, competition) == ["Dallas", "Phoenix"]


def test_an_unplaced_entrant_counts_as_no_office(db, org, world):
    """Somebody with no team belongs to no office. It does not make the contest
    everybody's — it adds "nowhere" to the places involved."""
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["nomad"]]
    )

    assert office_names(db, competition) == ["Phoenix", "no office"]


def test_a_team_contest_reads_its_teams_offices(db, org, world):
    competition = make_competition(
        db, org, world,
        entrants=[world["enterprise"], world["east"]],
        entity_type="team",
    )

    assert office_names(db, competition) == ["Dallas", "Phoenix"]


def test_a_contest_with_no_entrants_involves_nowhere(db, org, world):
    competition = make_competition(db, org, world, entrants=[])

    assert eligibility.competition_offices(db, competition) == set()


def test_teams_with_no_office_involve_no_office(db, org, world, make_team):
    competition = make_competition(
        db, org, world,
        entrants=[make_team("Homeless A"), make_team("Homeless B")],
        entity_type="team",
    )

    assert office_names(db, competition) == ["no office"]


# ── Which walls may show it ──────────────────────────────────────────────────


def wall(office_id=None, team_id=None):
    return eligibility.Where(office_id=office_id, team_id=team_id)


def test_an_uninvolved_office_cannot_show_a_cross_office_contest(db, org, world):
    """The leak this replaced.

    Phoenix versus Dallas used to appear on Austin's wall, because "two offices"
    was expressed as EVERYWHERE and EVERYWHERE fits everything.
    """
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["dan"]]
    )

    assert eligibility.competition_fits(
        db, wall(office_id=world["phoenix"].id), competition
    )
    assert eligibility.competition_fits(
        db, wall(office_id=world["dallas"].id), competition
    )
    assert not eligibility.competition_fits(
        db, wall(office_id=world["austin"].id), competition
    )


def test_an_uninvolved_office_cannot_show_a_single_office_contest(db, org, world):
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["carol"]]
    )

    assert eligibility.competition_fits(
        db, wall(office_id=world["phoenix"].id), competition
    )
    for other in ("dallas", "austin"):
        assert not eligibility.competition_fits(
            db, wall(office_id=world[other].id), competition
        ), other


def test_the_company_wall_shows_everything(db, org, world):
    """An organization-wide channel is the company's own wall. It is the one
    place a contest between any two offices belongs by default."""
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["dan"]]
    )

    assert eligibility.competition_fits(db, eligibility.EVERYWHERE, competition)


def test_a_team_wall_shows_a_contest_its_team_is_in(db, org, world):
    competition = make_competition(
        db, org, world,
        entrants=[world["enterprise"], world["east"]],
        entity_type="team",
    )

    assert eligibility.competition_fits(
        db, wall(team_id=world["enterprise"].id), competition
    )


def test_a_team_wall_shows_a_contest_its_office_is_in(db, org, world):
    """SMB is not entered, but the contest is on in Phoenix and SMB is in
    Phoenix — the same reasoning as the office wall, one level down."""
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]]
    )

    assert eligibility.competition_fits(db, wall(team_id=world["smb"].id), competition)


def test_a_team_wall_in_another_office_shows_nothing(db, org, world):
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]]
    )

    assert not eligibility.competition_fits(
        db, wall(team_id=world["east"].id), competition
    )


def test_an_officeless_team_wall_shows_only_its_own_contests(db, org, world, make_team):
    """A team with no office cannot inherit a stake from one."""
    drifting = make_team("Drifting")
    phoenix_contest = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]]
    )
    own_contest = make_competition(
        db, org, world, entrants=[drifting], entity_type="team"
    )

    assert not eligibility.competition_fits(
        db, wall(team_id=drifting.id), phoenix_contest
    )
    assert eligibility.competition_fits(db, wall(team_id=drifting.id), own_contest)


def test_the_picker_names_the_offices_involved(db, org, world):
    """"Phoenix + Dallas" rather than "Everyone" — the actual answer, and what
    tells an admin why a contest is on one list and not another's."""
    both = make_competition(db, org, world, entrants=[world["alice"], world["dan"]])
    one = make_competition(db, org, world, entrants=[world["alice"], world["bob"]])
    none = make_competition(db, org, world, entrants=[])

    assert eligibility.competition_places(db, both) == "Dallas + Phoenix"
    assert eligibility.competition_places(db, one) == "Phoenix"
    assert eligibility.competition_places(db, none) == "No entrants"



# ── What reaches the wall ────────────────────────────────────────────────────


def test_a_running_contest_renders_its_standings(db, org, world, make_fact):
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["bob"], 40, DURING)
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]], prize="Steak dinner"
    )
    channel = make_channel(db, org, competition)

    slides = channel_service.build(db, org, channel)

    assert len(slides) == 1
    slide = slides[0]
    assert slide.kind == "competition"
    assert slide.title == "August sprint"
    assert slide.prize == "Steak dinner"
    # The same keys a leaderboard entry uses, so the wall renders one shape
    # rather than two.
    assert [e["entity_name"] for e in slide.entries] == ["Alice", "Bob"]
    assert slide.total_entrants == 2
    assert slide.final is False
    # There is still something to count down to.
    assert slide.ends_at is not None


def test_a_settled_contest_shows_its_frozen_table_and_no_countdown(
    db, org, world, make_fact
):
    """The wall reads the same `standings()` the app does, so it cannot disagree
    with the trophy. And "0s left" beside a final result is noise."""
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["bob"], 40, DURING)
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]]
    )
    competitions.close(db, org, competition)
    db.flush()
    channel = make_channel(db, org, competition)

    slide = channel_service.build(db, org, channel)[0]

    assert slide.final is True
    assert slide.ends_at is None
    assert slide.entries[0]["entity_name"] == "Alice"

    # A correction afterwards moves nothing on the wall either.
    make_fact(world["metric"], world["bob"], 5000, DURING)
    assert channel_service.build(db, org, channel)[0].entries[0]["entity_name"] == "Alice"


@pytest.mark.parametrize("state", ["draft", "cancelled"])
def test_a_draft_or_cancelled_contest_is_skipped(db, org, world, make_fact, state):
    """Both would be a slide saying nothing. Skipped, never blanked — the wall
    moves past it."""
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(
        db, org, world, entrants=[world["alice"]], state=state
    )
    channel = make_channel(db, org, competition)

    assert channel_service.build(db, org, channel) == []


def test_a_contest_with_nothing_recorded_is_skipped(db, org, world):
    """An empty table on a wall is worse than one fewer slide in the rotation."""
    competition = make_competition(db, org, world, entrants=[])
    channel = make_channel(db, org, competition)

    assert channel_service.build(db, org, channel) == []


def test_deleting_a_competition_removes_its_screen(db, org, world, make_fact):
    """The screen goes with it, rather than lingering as a slide that cannot
    render.

    Written the other way round first — set `competition_id` to NULL and expect
    the renderer to skip it — and the CHECK constraint refused the update. That is
    the constraint doing its job: a competition screen with no competition is not
    a state the database will hold, so the renderer's `is None` guard is defence
    for something unreachable, exactly as the comment on the board and goal
    columns says.
    """
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(db, org, world, entrants=[world["alice"]])
    channel = make_channel(db, org, competition)
    assert len(channel_service.build(db, org, channel)) == 1

    db.delete(competition)
    db.flush()

    assert channel_service.build(db, org, channel) == []
    assert db.scalars(select(ChannelScreen).where(
        ChannelScreen.channel_id == channel.id
    )).all() == []


def test_the_table_is_capped_but_the_count_is_not(db, org, world, make_fact, make_user):
    """Eight rows and "of 14" — the point of the slide is the top of the field,
    and it shares the space with a prize and a countdown."""
    people = [
        make_user("agent", world["enterprise"], name=f"Person {i:02d}")
        for i in range(12)
    ]
    for index, person in enumerate(people):
        make_fact(world["metric"], person, 100 - index, DURING)
    competition = make_competition(db, org, world, entrants=people)
    channel = make_channel(db, org, competition)

    slide = channel_service.build(db, org, channel)[0]

    assert len(slide.entries) == channel_service.WALL_ROWS
    assert slide.total_entrants == 12


def test_a_phoenix_contest_does_not_reach_a_dallas_wall(db, org, world, make_fact):
    """The hole a competition opens, same as a goal: it names its own entrants, so
    the audience filter has nothing to narrow."""
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]]
    )
    dallas_wall = make_channel(
        db, org, competition, scope_type="office", scope_office_id=world["dallas"].id
    )

    assert channel_service.build(db, org, dallas_wall) == []


def test_a_phoenix_contest_reaches_the_phoenix_wall(db, org, world, make_fact):
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]]
    )
    phoenix_wall = make_channel(
        db, org, competition, scope_type="office", scope_office_id=world["phoenix"].id
    )

    assert len(channel_service.build(db, org, phoenix_wall)) == 1


def test_a_cross_office_contest_reaches_both_walls(db, org, world, make_fact):
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["dan"], 90, DURING)
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["dan"]]
    )

    for office in (world["phoenix"], world["dallas"]):
        wall = make_channel(
            db, org, competition, scope_type="office", scope_office_id=office.id
        )
        assert len(channel_service.build(db, org, wall)) == 1, office.name

    # And not the third office. Asserted at the render level, not just through
    # `competition_fits` — a rule that says no while the wall still draws it is
    # the failure that matters.
    austin = make_channel(
        db, org, competition, scope_type="office", scope_office_id=world["austin"].id
    )
    assert channel_service.build(db, org, austin) == []


# ── Authoring ────────────────────────────────────────────────────────────────


def test_the_editor_refuses_a_draft_competition(client, db, org, world, sign_in, make_user):
    """An admin hears about it now rather than watching a rotation skip past."""
    admin = make_user("admin", name="Admin")
    competition = make_competition(
        db, org, world, entrants=[world["alice"]], state="draft"
    )
    channel = Channel(
        organization_id=org.id, name="Wall", scope_type="organization"
    )
    db.add(channel)
    db.flush()
    db.commit()
    sign_in(admin)

    response = client.post(
        f"/api/channels/{channel.id}/screens",
        json={"kind": "competition", "competition_id": competition.id},
    )

    assert response.status_code == 400
    assert "Publish it first" in response.json()["detail"]


def test_the_editor_refuses_the_wrong_office(client, db, org, world, sign_in, make_user):
    admin = make_user("admin", name="Admin")
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]]
    )
    channel = Channel(
        organization_id=org.id,
        name="Dallas wall",
        scope_type="office",
        scope_office_id=world["dallas"].id,
    )
    db.add(channel)
    db.flush()
    db.commit()
    sign_in(admin)

    response = client.post(
        f"/api/channels/{channel.id}/screens",
        json={"kind": "competition", "competition_id": competition.id},
    )

    assert response.status_code == 400


def test_the_editor_refuses_an_uninvolved_office(
    client, db, org, world, sign_in, make_user
):
    """A Phoenix-versus-Dallas contest offered to Austin is refused, and the
    message says where it *is* on so the admin does not have to guess."""
    admin = make_user("admin", name="Admin")
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["dan"]], state="scheduled"
    )
    channel = Channel(
        organization_id=org.id,
        name="Austin wall",
        scope_type="office",
        scope_office_id=world["austin"].id,
    )
    db.add(channel)
    db.flush()
    db.commit()
    sign_in(admin)

    response = client.post(
        f"/api/channels/{channel.id}/screens",
        json={"kind": "competition", "competition_id": competition.id},
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Dallas + Phoenix" in detail


def test_the_picker_offers_a_contest_only_to_involved_offices(
    client, db, org, world, sign_in, make_user
):
    """The picker and the validation are the same rule, so a contest Austin
    cannot author is a contest Austin is never offered."""
    admin = make_user("admin", name="Admin")
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["dan"]], state="scheduled"
    )
    walls = {}
    for key in ("phoenix", "dallas", "austin"):
        ch = Channel(
            organization_id=org.id,
            name=f"{key} wall",
            scope_type="office",
            scope_office_id=world[key].id,
        )
        db.add(ch)
        db.flush()
        walls[key] = ch.id
    db.commit()
    sign_in(admin)

    offered = {
        key: [c["id"] for c in client.get(f"/api/channels/{cid}/eligible").json()["competitions"]]
        for key, cid in walls.items()
    }

    assert competition.id in offered["phoenix"]
    assert competition.id in offered["dallas"]
    assert competition.id not in offered["austin"]


def test_the_editor_accepts_a_published_contest_that_fits(
    client, db, org, world, sign_in, make_user
):
    admin = make_user("admin", name="Admin")
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]], state="scheduled"
    )
    channel = Channel(
        organization_id=org.id,
        name="Phoenix wall",
        scope_type="office",
        scope_office_id=world["phoenix"].id,
    )
    db.add(channel)
    db.flush()
    db.commit()
    sign_in(admin)

    response = client.post(
        f"/api/channels/{channel.id}/screens",
        json={"kind": "competition", "competition_id": competition.id},
    )

    assert response.status_code == 201
    # The endpoint returns the whole channel, so the rotation and the new screen
    # arrive together — the editor never has to reconcile two shapes.
    assert [s["kind"] for s in response.json()["screens"]] == ["competition"]


def test_another_organizations_competition_is_not_found(
    client, db, org, world, sign_in, make_user
):
    from app.models import Organization

    admin = make_user("admin", name="Admin")
    other = Organization(name="Rival", timezone="UTC")
    db.add(other)
    db.flush()
    competition = Competition(
        organization_id=other.id,
        name="Theirs",
        metric_definition_id=world["metric"].id,
        entity_type="user",
        starts_at=STARTS,
        ends_at=ENDS,
        state="active",
    )
    channel = Channel(organization_id=org.id, name="Wall", scope_type="organization")
    db.add_all([competition, channel])
    db.flush()
    db.commit()
    sign_in(admin)

    response = client.post(
        f"/api/channels/{channel.id}/screens",
        json={"kind": "competition", "competition_id": competition.id},
    )

    assert response.status_code == 404


def test_the_editor_names_a_competition_slide_after_the_contest(db, org, world):
    """QA-11: it fell through to the catch-all and read as "competition"."""
    from app.routers.channels import _label

    competition = make_competition(db, org, world, entrants=[world["alice"]])
    channel = make_channel(db, org, competition)
    screen = db.scalar(select(ChannelScreen).where(ChannelScreen.channel_id == channel.id))

    assert _label(db, screen) == "August sprint"



def test_a_contest_among_people_with_no_office_is_everyone_in_the_picker(
    db, org, world, make_user
):
    """Review §9: "· everyone", not "(no office)", which read as a fault. The
    refusal still says where its entrants are."""
    loose = make_user("agent", name="Loose")
    contest = make_competition(db, org, world, entrants=[loose])
    mixed = make_competition(db, org, world, entrants=[loose, world["alice"]])

    assert eligibility.competition_places(db, contest) == "everyone"
    assert eligibility.competition_places(db, contest, picker=False) == "no office"
    assert eligibility.competition_places(db, mixed) == "Phoenix + no office"


def test_a_contest_slide_carries_faces_as_a_board_does(db, org, world, make_fact):
    """8.5: every contest layout on the wall drew initials — the rows never
    carried a photo."""
    import io

    from PIL import Image

    from app import photos

    buffer = io.BytesIO()
    Image.new("RGB", (256, 256), (0, 128, 0)).save(buffer, format="PNG")
    stored = photos.set_custom(db, world["alice"], buffer.getvalue())
    competition = make_competition(db, org, world, entrants=[world["alice"], world["bob"]])
    make_fact(world["metric"], world["alice"], 5, STARTS + timedelta(days=1))
    make_fact(world["metric"], world["bob"], 2, STARTS + timedelta(days=1))
    channel = make_channel(db, org, competition)
    screen = db.scalars(select(ChannelScreen).where(ChannelScreen.channel_id == channel.id)).one()

    slide = channel_service.slide_for(db, org, channel, screen)

    faces = {e["entity_name"]: e["photo_digest"] for e in slide.entries}
    assert faces == {"Alice": stored.sha256, "Bob": None}
