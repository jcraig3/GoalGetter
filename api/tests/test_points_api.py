"""Balances, seasons and prices over the wire.

The scoping decision worth testing here is the one that goes the other way
from everything else in this product: **everybody sees the whole season
table**. A points league narrowed to what each viewer may see would show an
agent four people and call it a league, and an economy only works if there is
one board everybody is on. What stays narrow is everything behind the number —
a statement is your own, and awarding by hand is scoped like any other write.
"""

from datetime import date, timedelta

import pytest

from app import points, seasons
from app.models import Season
from tests.conftest import org_today


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    db.flush()
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", smb, name="Clark Kent"),
        "metric": make_metric("calls_made"),
    }


def give(db, org, user, amount, *, subject_id=1, reason="Hit a goal"):
    return points.award(
        db, org=org, user_id=user.id, points=amount,
        event_key="goal.achieved", subject_type="goal",
        subject_id=subject_id, reason=reason,
    )


# -- My balance --------------------------------------------------------------


def test_nothing_awarded_yet_says_so_rather_than_showing_zero(
    client, db, world, sign_in
):
    """A zero would look like a balance somebody spent."""
    sign_in(world["peter"])

    body = client.get("/api/points/me").json()

    assert body["season"] is None
    assert body["points"] == 0


def test_my_balance_and_my_rank(client, db, org, world, sign_in):
    give(db, org, world["peter"], 300)
    give(db, org, world["clark"], 500, subject_id=2)
    db.commit()
    sign_in(world["peter"])

    body = client.get("/api/points/me").json()

    assert body["points"] == 300
    assert body["rank"] == 2


def test_my_statement_says_where_it_came_from(client, db, org, world, sign_in):
    give(db, org, world["peter"], 300, reason="Hit Calls this month")
    db.commit()
    sign_in(world["peter"])

    lines = client.get("/api/points/me").json()["statement"]

    assert [line["reason"] for line in lines] == ["Hit Calls this month"]


def test_the_lifetime_figure_is_there_and_is_not_the_ranking(
    client, db, org, world, sign_in
):
    """A fact about somebody's history, worth showing on their own profile the
    way a career total is. The moment it becomes the scoreboard, the
    scoreboard is unwinnable again for everybody who joined last year."""
    old = Season(
        organization_id=org.id, name="Last",
        starts_on=org_today() - timedelta(days=200),
        ends_on=org_today() - timedelta(days=110),
    )
    db.add(old)
    db.flush()
    from app.models import PointAward

    db.add(
        PointAward(
            organization_id=org.id, season_id=old.id, user_id=world["peter"].id,
            points=9000, event_key="goal.achieved", subject_type="goal",
            subject_id=99, reason="Last season",
        )
    )
    give(db, org, world["peter"], 300)
    db.commit()
    sign_in(world["peter"])

    body = client.get("/api/points/me").json()

    assert body["points"] == 300
    assert body["lifetime"] == 9300


# -- The table ---------------------------------------------------------------


def test_an_agent_sees_the_whole_table(client, db, org, world, sign_in):
    """**Deliberately the opposite of every other ranked thing here.** A league
    narrowed per viewer is not a league."""
    give(db, org, world["peter"], 300)
    give(db, org, world["clark"], 500, subject_id=2)
    db.commit()
    sign_in(world["peter"])

    body = client.get("/api/points/standings").json()

    assert [row["name"] for row in body["standings"]] == [
        "Clark Kent",
        "Peter Parker",
    ]


def test_no_season_is_an_empty_table_not_an_error(client, db, world, sign_in):
    sign_in(world["peter"])

    body = client.get("/api/points/standings").json()

    assert body == {"season": None, "standings": []}


def test_a_past_season_can_be_read_back(client, db, org, world, sign_in):
    give(db, org, world["peter"], 300)
    db.commit()
    season = seasons.current(db, org)
    sign_in(world["peter"])

    body = client.get(f"/api/points/standings?season_id={season.id}").json()

    assert body["standings"][0]["points"] == 300


def test_another_organizations_season_is_not_found(client, db, world, sign_in):
    sign_in(world["admin"])

    assert client.get("/api/points/standings?season_id=999999").status_code == 404


# -- Seasons -----------------------------------------------------------------


def test_an_admin_sets_up_a_season(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = client.post(
        "/api/points/seasons",
        json={"name": "Q1 2028", "starts_on": "2028-01-01", "ends_on": "2028-03-31"},
    )

    assert reply.status_code == 201, reply.json()


def test_overlapping_seasons_are_refused_in_words(client, db, world, sign_in):
    """An admin drawing up next year's calendar will hit this, and "seasons
    cannot overlap" is the whole of what they need to know."""
    sign_in(world["admin"])
    client.post(
        "/api/points/seasons",
        json={"name": "Q1", "starts_on": "2028-01-01", "ends_on": "2028-03-31"},
    )

    reply = client.post(
        "/api/points/seasons",
        json={"name": "Also Q1", "starts_on": "2028-03-31", "ends_on": "2028-06-30"},
    )

    assert reply.status_code == 409
    assert "overlap" in reply.json()["detail"]


def test_two_seasons_that_touch_without_overlapping_are_fine(
    client, db, world, sign_in
):
    """The common case: one ends on the 31st and the next starts on the 1st."""
    sign_in(world["admin"])
    client.post(
        "/api/points/seasons",
        json={"name": "Q1", "starts_on": "2028-01-01", "ends_on": "2028-03-31"},
    )

    reply = client.post(
        "/api/points/seasons",
        json={"name": "Q2", "starts_on": "2028-04-01", "ends_on": "2028-06-30"},
    )

    assert reply.status_code == 201, reply.json()


def test_a_season_cannot_end_before_it_starts(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = client.post(
        "/api/points/seasons",
        json={"name": "Backwards", "starts_on": "2028-06-30", "ends_on": "2028-01-01"},
    )

    assert reply.status_code == 422


def test_shrinking_a_season_past_its_awards_is_refused(
    client, db, org, world, sign_in
):
    """**Shrinking one strands the awards outside its new dates**, where they
    count toward no table. Refused rather than silently orphaning them."""
    # A season already a month in, made here rather than left to the first
    # award: near a quarter's end that one starts today (QA-19).
    db.add(Season(organization_id=org.id, name="Running",
                  starts_on=org_today() - timedelta(days=30),
                  ends_on=org_today() + timedelta(days=60)))
    db.flush()
    give(db, org, world["peter"], 300)
    db.commit()
    season = seasons.current(db, org)
    sign_in(world["admin"])

    reply = client.patch(
        f"/api/points/seasons/{season.id}",
        json={
            "name": season.name,
            "starts_on": str(season.starts_on),
            "ends_on": str(org_today() - timedelta(days=1)),
        },
    )

    assert reply.status_code == 409
    assert "already been awarded" in reply.json()["detail"]


def test_renaming_a_season_is_fine(client, db, org, world, sign_in):
    give(db, org, world["peter"], 300)
    db.commit()
    season = seasons.current(db, org)
    sign_in(world["admin"])

    reply = client.patch(
        f"/api/points/seasons/{season.id}",
        json={
            "name": "The big push",
            "starts_on": str(season.starts_on),
            "ends_on": str(season.ends_on),
        },
    )

    assert reply.status_code == 200, reply.json()
    assert reply.json()["name"] == "The big push"


def test_widening_a_season_is_fine(client, db, org, world, sign_in):
    give(db, org, world["peter"], 300)
    db.commit()
    season = seasons.current(db, org)
    sign_in(world["admin"])

    reply = client.patch(
        f"/api/points/seasons/{season.id}",
        json={
            "name": season.name,
            "starts_on": str(season.starts_on - timedelta(days=10)),
            "ends_on": str(season.ends_on + timedelta(days=10)),
        },
    )

    assert reply.status_code == 200, reply.json()


def test_a_manager_cannot_set_up_a_season(client, db, world, sign_in):
    """It resets the scoreboard for the whole organization."""
    sign_in(world["manager"])

    reply = client.post(
        "/api/points/seasons",
        json={"name": "Mine", "starts_on": "2028-01-01", "ends_on": "2028-03-31"},
    )

    assert reply.status_code == 403


def test_everybody_can_see_which_seasons_exist(client, db, world, sign_in):
    """The shape of the game, not a setting."""
    sign_in(world["admin"])
    client.post(
        "/api/points/seasons",
        json={"name": "Q1", "starts_on": "2028-01-01", "ends_on": "2028-03-31"},
    )

    sign_in(world["peter"])

    assert client.get("/api/points/seasons").status_code == 200


# -- Prices ------------------------------------------------------------------


def test_the_defaults_show_before_anybody_tunes_them(client, db, world, sign_in):
    sign_in(world["admin"])

    body = client.get("/api/points/values").json()

    assert body["values"]["goal.achieved"] == 100


def test_an_admin_can_reprice_things(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = client.put(
        "/api/points/values", json={"values": {"goal.achieved": 250}}
    )

    assert reply.status_code == 200, reply.json()
    assert reply.json()["values"]["goal.achieved"] == 250


def test_repricing_does_not_move_what_was_already_awarded(
    client, db, org, world, sign_in
):
    """**A ledger row records what was paid at the time.** Re-pricing history
    would mean somebody's balance moving overnight for work they did last
    month, which is the fastest way to stop people believing the number."""
    give(db, org, world["peter"], 100)
    db.commit()
    sign_in(world["admin"])

    client.put("/api/points/values", json={"values": {"goal.achieved": 999}})

    assert client.get("/api/points/standings").json()["standings"][0][
        "points"
    ] == 100


def test_pricing_something_that_is_not_a_thing_is_refused(
    client, db, world, sign_in
):
    sign_in(world["admin"])

    reply = client.put(
        "/api/points/values", json={"values": {"nonsense.event": 10}}
    )

    assert reply.status_code == 422


def test_a_negative_price_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = client.put(
        "/api/points/values", json={"values": {"goal.achieved": -5}}
    )

    assert reply.status_code == 422


def test_an_agent_cannot_read_the_price_list(client, db, world, sign_in):
    sign_in(world["peter"])

    assert client.get("/api/points/values").status_code == 403


# -- Awarding by hand --------------------------------------------------------


def test_a_manager_awards_points_to_their_own_person(
    client, db, org, world, sign_in
):
    sign_in(world["manager"])

    reply = client.post(
        "/api/points/awards",
        json={"user_id": world["peter"].id, "points": 50, "reason": "Covered a shift"},
    )

    assert reply.status_code == 201, reply.json()
    assert reply.json()["points"] == 50


def test_a_manager_cannot_award_outside_their_team(
    client, db, org, world, sign_in
):
    sign_in(world["manager"])

    reply = client.post(
        "/api/points/awards",
        json={"user_id": world["clark"].id, "points": 50, "reason": "Nice"},
    )

    assert reply.status_code == 404


def test_a_mistake_is_corrected_with_a_negative_award(
    client, db, org, world, sign_in
):
    """A ledger row is never edited, so the fix is the opposite row — and
    somebody can read what happened."""
    sign_in(world["admin"])
    client.post(
        "/api/points/awards",
        json={"user_id": world["peter"].id, "points": 500, "reason": "Oops"},
    )

    reply = client.post(
        "/api/points/awards",
        json={"user_id": world["peter"].id, "points": -500, "reason": "Awarded in error"},
    )

    assert reply.status_code == 201, reply.json()
    assert client.get("/api/points/standings").json()["standings"] == []


def test_awarding_by_hand_repeats(client, db, org, world, sign_in):
    """A manager who does this twice meant to."""
    sign_in(world["admin"])
    body = {"user_id": world["peter"].id, "points": 50, "reason": "Covered a shift"}
    client.post("/api/points/awards", json=body)
    client.post("/api/points/awards", json=body)

    assert client.get("/api/points/standings").json()["standings"][0][
        "points"
    ] == 100


def test_an_award_of_nothing_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = client.post(
        "/api/points/awards",
        json={"user_id": world["peter"].id, "points": 0, "reason": "Nothing"},
    )

    assert reply.status_code == 422


def test_an_agent_cannot_award_points(client, db, world, sign_in):
    sign_in(world["peter"])

    reply = client.post(
        "/api/points/awards",
        json={"user_id": world["clark"].id, "points": 50, "reason": "Mate"},
    )

    assert reply.status_code == 403


def test_awarding_by_hand_is_audited(client, db, org, world, sign_in):
    """The one award with no rule behind it, so "who gave them 500 points"
    needs an answer that does not depend on the ledger row still being there."""
    from sqlalchemy import select

    from app.models import AuditLog

    sign_in(world["admin"])
    client.post(
        "/api/points/awards",
        json={"user_id": world["peter"].id, "points": 500, "reason": "Huge save"},
    )

    actions = db.scalars(select(AuditLog.action)).all()

    assert "points.awarded" in actions


# -- The ladder --------------------------------------------------------------


def ladder(client, rungs):
    return client.put("/api/points/tiers", json={"tiers": rungs})


STANDARD = [
    {"name": "Bronze", "threshold": 100},
    {"name": "Silver", "threshold": 500},
    {"name": "Gold", "threshold": 1000},
]


def test_an_admin_sets_up_the_ladder(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = ladder(client, STANDARD)

    assert reply.status_code == 200, reply.json()
    assert [t["name"] for t in reply.json()["tiers"]] == ["Bronze", "Silver", "Gold"]


def test_the_ladder_comes_back_lowest_first_however_it_was_sent(
    client, db, world, sign_in
):
    sign_in(world["admin"])

    reply = ladder(client, list(reversed(STANDARD)))

    assert [t["threshold"] for t in reply.json()["tiers"]] == [100, 500, 1000]


def test_replacing_the_ladder_replaces_it(client, db, world, sign_in):
    """Wholesale rather than row by row, so an admin shuffling rungs never
    passes through a state the unique index forbids."""
    sign_in(world["admin"])
    ladder(client, STANDARD)

    reply = ladder(client, [{"name": "Only one", "threshold": 250}])

    assert [t["name"] for t in reply.json()["tiers"]] == ["Only one"]


def test_two_rungs_at_the_same_height_are_refused_in_words(
    client, db, world, sign_in
):
    sign_in(world["admin"])

    reply = ladder(
        client,
        [{"name": "Bronze", "threshold": 100}, {"name": "Silver", "threshold": 100}],
    )

    assert reply.status_code == 422
    assert "same number of points" in reply.json()["detail"]


def test_two_rungs_with_the_same_name_are_refused(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = ladder(
        client,
        [{"name": "Gold", "threshold": 100}, {"name": "Gold", "threshold": 500}],
    )

    assert reply.status_code == 422


def test_a_rung_at_zero_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])

    assert ladder(client, [{"name": "Everyone", "threshold": 0}]).status_code == 422


def test_everybody_can_read_the_ladder(client, db, world, sign_in):
    """What the rungs are is the shape of the game, not a setting."""
    sign_in(world["admin"])
    ladder(client, STANDARD)

    sign_in(world["peter"])

    assert client.get("/api/points/tiers").status_code == 200


def test_an_agent_cannot_move_the_rungs(client, db, world, sign_in):
    sign_in(world["peter"])

    assert ladder(client, STANDARD).status_code == 403


def test_moving_a_rung_moves_who_is_standing_on_it_immediately(
    client, db, org, world, sign_in
):
    """A tier is read from a balance at the moment somebody looks, so nothing
    about anybody's points changes and no history is rewritten."""
    give(db, org, world["peter"], 600)
    db.commit()
    sign_in(world["admin"])
    ladder(client, STANDARD)

    sign_in(world["peter"])
    assert client.get("/api/points/me").json()["tier"] == "Silver"

    sign_in(world["admin"])
    ladder(client, [{"name": "Gold", "threshold": 600}])

    sign_in(world["peter"])
    assert client.get("/api/points/me").json()["tier"] == "Gold"


def test_my_balance_says_what_is_next_and_how_far(
    client, db, org, world, sign_in
):
    """**The only part of a ladder that changes behaviour.**"""
    give(db, org, world["peter"], 600)
    db.commit()
    sign_in(world["admin"])
    ladder(client, STANDARD)

    sign_in(world["peter"])
    body = client.get("/api/points/me").json()

    assert (body["tier"], body["next_tier"], body["to_next_tier"]) == (
        "Silver",
        "Gold",
        400,
    )


def test_no_ladder_is_not_an_error_anywhere(client, db, org, world, sign_in):
    """Tiers are optional in a way seasons are not."""
    give(db, org, world["peter"], 600)
    db.commit()
    sign_in(world["peter"])

    body = client.get("/api/points/me").json()

    assert body["tier"] is None and body["to_next_tier"] is None
    assert client.get("/api/points/standings").json()["standings"][0]["tier"] is None


def test_the_table_carries_each_persons_rung(client, db, org, world, sign_in):
    give(db, org, world["peter"], 600)
    give(db, org, world["clark"], 120, subject_id=2)
    db.commit()
    sign_in(world["admin"])
    ladder(client, STANDARD)

    rows = client.get("/api/points/standings").json()["standings"]

    assert [(r["name"], r["tier"]) for r in rows] == [
        ("Peter Parker", "Silver"),
        ("Clark Kent", "Bronze"),
    ]


# -- Suggestions -------------------------------------------------------------


def test_too_few_people_says_why_rather_than_suggesting_nothing(
    client, db, org, world, sign_in
):
    """An empty list reads as "no ladder needed", which is the opposite of
    what it means."""
    give(db, org, world["peter"], 600)
    db.commit()
    sign_in(world["admin"])

    body = client.get("/api/points/tiers/suggest").json()

    assert body["suggestions"] == []
    assert body["scoring_people"] == 1
    assert body["minimum"] >= 2


def test_suggestions_come_from_the_real_distribution(
    client, db, org, world, sign_in, make_user
):
    for index, amount in enumerate(range(100, 900, 100)):
        give(db, org, make_user("agent", name=f"Agent {index}"), amount,
             subject_id=index + 10)
    db.commit()
    sign_in(world["admin"])

    body = client.get("/api/points/tiers/suggest").json()

    assert len(body["suggestions"]) == 4
    assert all(s["would_hold"] >= 1 for s in body["suggestions"])


def test_a_suggestion_says_how_many_would_hold_it(
    client, db, org, world, sign_in, make_user
):
    """The number that tells an admin whether the rung is worth anything,
    which is the whole reason the suggestion exists."""
    for index, amount in enumerate(range(100, 2100, 100)):
        give(db, org, make_user("agent", name=f"Agent {index}"), amount,
             subject_id=index + 10)
    db.commit()
    sign_in(world["admin"])

    top = client.get("/api/points/tiers/suggest").json()["suggestions"][-1]

    assert top["would_hold"] <= 3


def test_no_season_is_not_an_error(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = client.get("/api/points/tiers/suggest")

    assert reply.status_code == 200
    assert reply.json()["scoring_people"] == 0


def test_an_agent_cannot_ask_for_suggestions(client, db, world, sign_in):
    sign_in(world["peter"])

    assert client.get("/api/points/tiers/suggest").status_code == 403
