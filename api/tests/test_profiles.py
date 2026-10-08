"""A person's profile (Phase 9): the public half for everyone, the private half
for the person and whoever manages them — decided on the server."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import events, notifications
from app.models import Goal, Leaderboard, Organization
from tests.conftest import within_this_month


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    sales = make_team("Sales")
    other = make_team("Other")
    return {
        "sales": sales,
        "other": other,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", sales, name="Mona Manager"),
        "elsewhere": make_user("manager", other, name="Olly Other"),
        "ann": make_user("agent", sales, name="Ann Andrews"),
        "bob": make_user("agent", sales, name="Bob Brown"),
        "metric": make_metric("deals"),
    }


def with_a_goal_and_a_board(db, org, world, make_fact):
    from app import periods

    anchor = periods.resolve(org, "month", periods.today(org)).start.astimezone(periods.tz(org)).date()
    db.add(Goal(
        organization_id=org.id, metric_definition_id=world["metric"].id, subject_type="user",
        subject_user_id=world["ann"].id, target_value=Decimal(10), period_type="month",
        period_anchor=anchor,
    ))
    db.add(Leaderboard(
        organization_id=org.id, name="Deals board", metric_definition_id=world["metric"].id,
        period_type="month", visibility="org",
    ))
    make_fact(world["metric"], world["ann"], 7, within_this_month())
    db.flush()


def profile(client, person):
    return client.get(f"/api/people/{person.id}")


# ── Who sees what ────────────────────────────────────────────────────────────


def test_a_colleague_sees_the_public_half_and_not_the_private(
    client, db, org, world, sign_in, make_fact
):
    with_a_goal_and_a_board(db, org, world, make_fact)
    sign_in(world["bob"])

    body = profile(client, world["ann"]).json()

    assert body["person"]["name"] == "Ann Andrews"
    assert body["private"] is None
    # Nothing to do from here: an agent cannot recognise, give a badge or edit.
    assert body["can"] == {"recognise": False, "give_badge": False, "edit": None}


def test_the_person_sees_their_own_private_half(client, db, org, world, sign_in, make_fact):
    with_a_goal_and_a_board(db, org, world, make_fact)
    sign_in(world["ann"])

    body = profile(client, world["ann"]).json()

    assert body["is_me"] is True
    assert [g["metric_name"] for g in body["private"]["goals"]] == [world["metric"].name]
    assert [(n["board_name"], float(n["value"]), n["rank"]) for n in body["private"]["numbers"]] == [
        ("Deals board", 7.0, 1),
    ]
    assert body["can"]["edit"] == "/account"


def test_their_manager_sees_it_and_may_act(client, db, org, world, sign_in, make_fact):
    with_a_goal_and_a_board(db, org, world, make_fact)
    sign_in(world["manager"])

    body = profile(client, world["ann"]).json()

    assert body["private"] is not None
    assert body["can"] == {"recognise": True, "give_badge": True, "edit": f"/users/{world['ann'].id}"}


def test_a_manager_of_another_team_sees_only_the_public_half(
    client, db, org, world, sign_in, make_fact
):
    with_a_goal_and_a_board(db, org, world, make_fact)
    sign_in(world["elsewhere"])

    body = profile(client, world["ann"]).json()

    assert body["private"] is None
    assert body["can"] == {"recognise": False, "give_badge": False, "edit": None}


def test_an_admin_sees_everyone_in_full(client, db, org, world, sign_in, make_fact):
    with_a_goal_and_a_board(db, org, world, make_fact)
    sign_in(world["admin"])

    assert profile(client, world["ann"]).json()["private"] is not None


def test_a_hidden_account_has_no_profile(client, db, world, sign_in):
    world["bob"].hidden_at = datetime.now(UTC)
    db.flush()
    sign_in(world["admin"])

    assert profile(client, world["bob"]).status_code == 404


def test_another_organizations_person_is_not_found(client, db, world, sign_in, make_user):
    stranger_org = Organization(name="Elsewhere", timezone="UTC", week_starts_on=1)
    db.add(stranger_org)
    db.flush()
    world["bob"].organization_id = stranger_org.id
    db.flush()
    sign_in(world["ann"])

    assert profile(client, world["bob"]).status_code == 404


# ── What the public half says ────────────────────────────────────────────────


def test_wins_carry_the_announced_figure_and_who_gave_a_shout_out(
    client, db, org, world, sign_in
):
    notifications.emit(
        db, org_id=org.id, user_id=world["ann"].id, event=events.RECOGNITION,
        subject_type="user", subject_id=world["ann"].id, title="Great close",
        about_name="Ann Andrews", about_user_id=world["ann"].id,
        created_by_user_id=world["manager"].id,
    )
    notifications.emit(
        db, org_id=org.id, user_id=world["ann"].id, event=events.GOAL_ACHIEVED,
        subject_type="goal", subject_id=1, title="Deals achieved", figure="$12,400",
        about_name="Ann Andrews", about_user_id=world["ann"].id,
        period_anchor=datetime.now(UTC).date(),
    )
    # Private: being behind is a conversation, not a line on a profile.
    notifications.emit(
        db, org_id=org.id, user_id=world["ann"].id, event=events.GOAL_PERIOD_ENDING,
        subject_type="goal", subject_id=2, title="Running out of time",
        about_name="Ann Andrews", about_user_id=world["ann"].id,
        period_anchor=datetime.now(UTC).date() - timedelta(days=1),
    )
    db.commit()
    sign_in(world["bob"])

    wins = profile(client, world["ann"]).json()["wins"]

    by_title = {w["title"]: w for w in wins}
    assert set(by_title) == {"Great close", "Deals achieved"}
    assert by_title["Great close"]["from_name"] == "Mona Manager"
    assert by_title["Great close"]["occasion"] == "Recognition"
    assert by_title["Deals achieved"]["figure"] == "$12,400"


# ── The organization's switch (9.5) ─────────────────────────────────────────


def test_with_profiles_off_a_colleague_cannot_open_one(client, db, org, world, sign_in):
    org.profiles_public = False
    db.flush()

    sign_in(world["bob"])
    assert profile(client, world["ann"]).status_code == 404
    assert profile(client, world["bob"]).status_code == 200

    sign_in(world["manager"])
    assert profile(client, world["ann"]).status_code == 200


def test_names_are_links_only_where_every_link_would_open(client, db, org, world, sign_in):
    sign_in(world["bob"])
    assert "people.view" in client.get("/api/auth/me").json()["capabilities"]

    org.profiles_public = False
    db.flush()
    assert "people.view" not in client.get("/api/auth/me").json()["capabilities"]
    # A manager's org-wide board names people outside their team, so no links.
    sign_in(world["manager"])
    assert "people.view" not in client.get("/api/auth/me").json()["capabilities"]
    sign_in(world["admin"])
    assert "people.view" in client.get("/api/auth/me").json()["capabilities"]


def test_the_season_says_points_place_and_tier(client, db, org, world, sign_in):
    """The season table is public already; the profile says one row of it."""
    from app import points
    from app.models import Season, Tier
    from tests.conftest import org_today

    db.add(Season(
        organization_id=org.id, name="Q4",
        starts_on=org_today() - timedelta(days=10), ends_on=org_today() + timedelta(days=10),
    ))
    db.add_all([
        Tier(organization_id=org.id, name="Silver", threshold=50),
        Tier(organization_id=org.id, name="Gold", threshold=200),
    ])
    db.flush()
    for person, amount in (("ann", 120), ("bob", 300)):
        points.award(
            db, org=org, user_id=world[person].id, points=amount, event_key="manual",
            subject_type="user", subject_id=world[person].id, reason="Test",
        )
    db.commit()
    sign_in(world["bob"])

    season = profile(client, world["ann"]).json()["season"]

    assert season == {
        "name": "Q4", "points": 120, "rank": 2, "of": 2,
        "tier": "Silver", "next_tier": "Gold", "to_next_tier": 80,
    }


def test_an_admin_turns_profiles_off_and_a_null_leaves_them_alone(client, db, org, world, sign_in):
    sign_in(world["admin"])

    assert client.get("/api/organization").json()["profiles_public"] is True
    assert client.patch("/api/organization", json={"profiles_public": False}).json()["profiles_public"] is False
    assert client.patch("/api/organization", json={"profiles_public": None}).json()["profiles_public"] is False

    sign_in(world["ann"])
    assert client.patch("/api/organization", json={"profiles_public": True}).status_code == 403


def test_a_board_where_they_have_nothing_is_not_a_place(client, db, org, world, sign_in, make_fact):
    """P3-6: "$0.00 · 39th of 137" ranked somebody for doing nothing."""
    with_a_goal_and_a_board(db, org, world, make_fact)
    make_fact(world["metric"], world["bob"], 0, within_this_month())
    db.commit()
    sign_in(world["bob"])

    assert profile(client, world["bob"]).json()["private"]["numbers"] == []


# ── Places on the public half (P4-12) ────────────────────────────────────────


def test_a_colleague_sees_the_place_but_not_the_number(client, db, org, world, sign_in, make_fact):
    """The board shows both to anybody who can open it; the profile shows the
    place, and keeps the number on the private half."""
    with_a_goal_and_a_board(db, org, world, make_fact)
    sign_in(world["bob"])

    body = profile(client, world["ann"]).json()

    assert body["private"] is None
    assert [(p["board_name"], p["rank"]) for p in body["places"]] == [("Deals board", 1)]
    assert "value" not in body["places"][0]


def test_no_place_from_a_board_the_viewer_cannot_open(client, db, org, world, sign_in, make_fact):
    with_a_goal_and_a_board(db, org, world, make_fact)
    board = db.scalar(select(Leaderboard))
    board.visibility = "private"
    board.created_by_user_id = world["admin"].id
    db.flush()
    sign_in(world["bob"])
    assert profile(client, world["ann"]).json()["places"] == []


def test_the_private_half_needs_no_places_beside_it(client, db, org, world, sign_in, make_fact):
    with_a_goal_and_a_board(db, org, world, make_fact)
    sign_in(world["ann"])
    body = profile(client, world["ann"]).json()
    assert body["private"]["numbers"]
    assert body["places"] == []
