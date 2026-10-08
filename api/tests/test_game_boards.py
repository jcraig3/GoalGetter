"""Game boards: the track engine, finish lines, and the piece each person moves.

**Position is percent-to-target**, and the tests that matter are the ones about
what the target is. With a finish line, reaching it is finishing. Without one,
the race is measured against whoever is leading — and nobody has "finished",
because there was never a line to cross. Lower-is-better metrics run the other
way: faster is further along.
"""

from decimal import Decimal

import pytest

from app import game_boards
from app.models import GameToken


# -- The engine --------------------------------------------------------------


def race(value, finish_line=None, leader=100, lower=False):
    return game_boards.progress(
        Decimal(str(value)),
        finish_line=Decimal(str(finish_line)) if finish_line is not None else None,
        leader=Decimal(str(leader)),
        lower_is_better=lower,
    )


def test_a_piece_sits_at_its_share_of_the_finish_line():
    assert race(25, finish_line=50).fraction == 0.5


def test_reaching_the_line_is_finishing():
    standing = race(50, finish_line=50)

    assert (standing.fraction, standing.finished) == (1.0, True)


def test_going_past_the_line_does_not_run_off_the_board():
    assert race(80, finish_line=50).fraction == 1.0


def test_with_no_finish_line_it_is_measured_against_the_leader():
    assert race(30, leader=60).fraction == 0.5


def test_the_leader_is_not_a_finisher_when_there_is_no_line():
    """**Nobody should read the front-runner as having crossed a line that was
    never drawn.** The wall labels that end "Leader" for the same reason."""
    standing = race(60, leader=60)

    assert (standing.fraction, standing.finished) == (1.0, False)


def test_lower_is_better_runs_the_other_way():
    """40 seconds against a 60-second target has finished; 90 is two thirds of
    the way there."""
    assert race(40, finish_line=60, lower=True).finished is True
    assert round(race(90, finish_line=60, lower=True).fraction, 3) == 0.667


def test_a_target_of_nothing_puts_everybody_on_the_start_line():
    assert race(10, leader=0).fraction == 0.0


# -- Finish lines ------------------------------------------------------------


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    team = make_team("Enterprise")
    other = make_team("SMB")
    db.flush()
    return {
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", team, name="Manager"),
        "peter": make_user("agent", team, name="Peter Parker"),
        "clark": make_user("agent", other, name="Clark Kent"),
        "metric": make_metric("deals"),
    }


def board(client, world, **extra):
    reply = client.post(
        "/api/leaderboards",
        json={"name": "Deals", "metric_id": world["metric"].id,
              "period_type": "month", "visibility": "org", **extra},
    )
    assert reply.status_code == 201, reply.json()
    return reply.json()


def test_a_leaderboard_can_have_a_finish_line(client, db, world, sign_in):
    sign_in(world["admin"])

    made = board(client, world, finish_line="50")

    assert Decimal(made["finish_line"]) == 50


def test_a_finish_line_of_nothing_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = client.post(
        "/api/leaderboards",
        json={"name": "Deals", "metric_id": world["metric"].id, "finish_line": "0"},
    )

    assert reply.status_code == 422


def test_a_running_competitions_finish_line_can_be_moved(
    client, db, org, world, sign_in
):
    """**It is where the flag is drawn, not who wins** — the standings are the
    same with or without it — so it can change mid-contest like the name and
    the prize can."""
    from datetime import UTC, datetime, timedelta

    from app.models import Competition

    competition = Competition(
        organization_id=org.id, name="Sprint", metric_definition_id=world["metric"].id,
        entity_type="user", state="active",
        starts_at=datetime.now(UTC) - timedelta(days=1),
        ends_at=datetime.now(UTC) + timedelta(days=6),
    )
    db.add(competition)
    db.commit()
    sign_in(world["admin"])

    reply = client.patch(f"/api/competitions/{competition.id}", json={"finish_line": "20"})

    assert reply.status_code == 200, reply.json()


# -- On the wall -------------------------------------------------------------


def wall(client, board_id, appearance=None):
    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    client.post(
        f"/api/channels/{channel['id']}/screens",
        json={"kind": "leaderboard", "leaderboard_id": board_id,
              **({"appearance": appearance} if appearance else {})},
    )
    display = client.post("/api/displays", json={"name": "TV", "channel_id": channel["id"]}).json()
    token = display["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    return client.get(f"/api/display/{token}").json()["slides"][0]


def test_the_wall_is_told_how_far_along_everybody_is(
    client, db, world, sign_in, make_fact
):
    from tests.conftest import within_this_month

    make_fact(world["metric"], world["peter"], 40, within_this_month())
    make_fact(world["metric"], world["clark"], 20, within_this_month())
    db.commit()
    sign_in(world["admin"])
    made = board(client, world, finish_line="40")

    slide = wall(client, made["id"], {"ranked_layout": "race"})

    assert slide["appearance"]["ranked_layout"] == "race"
    assert Decimal(slide["finish_line"]) == 40
    assert [(e["progress"], e["finished"]) for e in slide["entries"]] == [
        (1.0, True),
        (0.5, False),
    ]


def test_each_person_brings_their_own_piece(client, db, world, sign_in, make_fact):
    from tests.conftest import within_this_month

    make_fact(world["metric"], world["peter"], 40, within_this_month())
    make_fact(world["metric"], world["clark"], 20, within_this_month())
    db.add(GameToken(user_id=world["peter"].id, family="race", token="car"))
    db.commit()
    sign_in(world["admin"])
    made = board(client, world)

    entries = wall(client, made["id"], {"ranked_layout": "race"})["entries"]

    # Clark has not chosen, so his own face — sent as nothing chosen.
    assert [e["token"] for e in entries] == ["car", None]


def test_race_is_a_ranked_layout_an_appearance_accepts(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = client.patch(
        "/api/organization", json={"appearance": {"ranked_layout": "race"}}
    )

    assert reply.status_code == 200, reply.json()


# -- Choosing a piece --------------------------------------------------------


def test_everybody_starts_with_their_own_face(client, db, world, sign_in):
    sign_in(world["peter"])

    families = client.get("/api/me/tokens").json()

    assert families == [
        {"family": "race", "token": "face", "options": ["face", "car", "truck", "bike"]},
        {"family": "regatta", "token": "face", "options": ["face", "sailboat", "speedboat", "duck"]},
        {"family": "climb", "token": "face", "options": ["face", "climber", "goat", "balloon"]},
        {"family": "space", "token": "face", "options": ["face", "rocket", "ufo", "comet"]},
    ]


def test_choosing_a_piece(client, db, world, sign_in):
    sign_in(world["peter"])

    reply = client.put("/api/me/tokens", json={"family": "race", "token": "car"})

    assert reply.json()[0]["token"] == "car"


def test_going_back_to_your_face_stores_nothing(client, db, world, sign_in):
    """The default is the absence of a choice, so it stays the default if the
    default ever changes."""
    sign_in(world["peter"])
    client.put("/api/me/tokens", json={"family": "race", "token": "car"})

    client.put("/api/me/tokens", json={"family": "race", "token": "face"})

    assert db.get(GameToken, (world["peter"].id, "race")) is None


def test_a_piece_that_is_not_on_offer_is_refused(client, db, world, sign_in):
    sign_in(world["peter"])

    reply = client.put("/api/me/tokens", json={"family": "race", "token": "spaceship"})

    assert reply.status_code == 422
    assert "car" in reply.json()["detail"]


def test_a_manager_sets_one_for_their_own_person(client, db, world, sign_in):
    sign_in(world["manager"])

    reply = client.put(
        f"/api/me/tokens?user_id={world['peter'].id}", json={"family": "race", "token": "bike"}
    )

    assert reply.json()[0]["token"] == "bike"


def test_a_manager_cannot_for_somebody_outside_their_team(client, db, world, sign_in):
    sign_in(world["manager"])

    reply = client.put(
        f"/api/me/tokens?user_id={world['clark'].id}", json={"family": "race", "token": "bike"}
    )

    assert reply.status_code == 404


def test_an_agent_cannot_choose_for_somebody_else(client, db, world, sign_in):
    sign_in(world["peter"])

    reply = client.put(
        f"/api/me/tokens?user_id={world['clark'].id}", json={"family": "race", "token": "bike"}
    )

    assert reply.status_code == 403


# -- More families (6.8) -----------------------------------------------------


@pytest.mark.parametrize("layout", ["regatta", "climb", "space"])
def test_each_new_board_is_a_ranked_layout(client, db, world, sign_in, layout):
    sign_in(world["admin"])
    reply = client.patch("/api/organization", json={"appearance": {"ranked_layout": layout}})
    assert reply.status_code == 200, reply.json()


def test_a_board_sends_the_pieces_for_its_own_family(client, db, world, sign_in, make_fact):
    """A car on the race, a sailboat on the regatta — one choice per family."""
    from tests.conftest import within_this_month

    make_fact(world["metric"], world["peter"], 40, within_this_month())
    db.add(GameToken(user_id=world["peter"].id, family="race", token="car"))
    db.add(GameToken(user_id=world["peter"].id, family="regatta", token="sailboat"))
    db.commit()
    sign_in(world["admin"])
    made = board(client, world)

    regatta = wall(client, made["id"], {"ranked_layout": "regatta"})["entries"]
    sign_in(world["admin"])
    race = wall(client, made["id"], {"ranked_layout": "race"})["entries"]

    assert (regatta[0]["token"], race[0]["token"]) == ("sailboat", "car")


def test_choosing_a_piece_for_a_new_family(client, db, world, sign_in):
    sign_in(world["peter"])
    reply = client.put("/api/me/tokens", json={"family": "space", "token": "rocket"})
    found = {f["family"]: f["token"] for f in reply.json()}
    assert (found["space"], found["race"]) == ("rocket", "face")
    assert client.put("/api/me/tokens", json={"family": "space", "token": "sailboat"}).status_code == 422

