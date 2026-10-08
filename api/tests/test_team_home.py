"""A manager's own team on their home page (6.13)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app import periods
from app.models import Goal
from tests.conftest import within_this_month


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    sales = make_team("Sales")
    other = make_team("Other")
    return {
        "sales": sales,
        "manager": make_user("manager", sales, name="Mona Manager"),
        "ann": make_user("agent", sales, name="Ann"),
        "bob": make_user("agent", sales, name="Bob"),
        "cat": make_user("agent", sales, name="Cat"),
        "far": make_user("agent", other, name="Far"),
        "deals": make_metric("deals"),
        "calls": make_metric("calls"),
    }


def goal_for(db, org, person, metric, target):
    anchor = periods.resolve(org, "month", periods.today(org)).start.astimezone(periods.tz(org)).date()
    goal = Goal(
        organization_id=org.id, metric_definition_id=metric.id, subject_type="user",
        subject_user_id=person.id, target_value=Decimal(target), period_type="month",
        period_anchor=anchor,
    )
    db.add(goal)
    db.flush()
    return goal


def test_an_agent_has_no_team_home(client, world, sign_in):
    sign_in(world["ann"])
    assert client.get("/api/dashboard/team").json() is None


def test_the_team_ranked_on_its_busiest_metric(client, db, org, world, sign_in, make_fact):
    when = within_this_month()
    make_fact(world["deals"], world["ann"], 5, when)
    make_fact(world["deals"], world["bob"], 9, when)
    make_fact(world["deals"], world["far"], 50, when)
    make_fact(world["calls"], world["ann"], 1, when)
    sign_in(world["manager"])

    body = client.get("/api/dashboard/team").json()

    assert body["team_name"] == "Sales"
    # Deals has three facts lately, calls one: deals is the default.
    assert [m["name"] for m in body["metrics"]][:2] == [world["deals"].name, world["calls"].name]
    assert body["metric_id"] == world["deals"].id
    # Only the team, ranked; somebody on another team is not on it.
    assert [(m["name"], m["rank"]) for m in body["members"]] == [
        ("Bob", 1), ("Ann", 2), ("Cat", 3), ("Mona Manager", 3),
    ]
    me = next(m for m in body["members"] if m["name"] == "Mona Manager")
    assert me["is_me"]


def test_another_metric_can_be_chosen(client, db, org, world, sign_in, make_fact):
    make_fact(world["calls"], world["cat"], 7, within_this_month())
    sign_in(world["manager"])
    body = client.get(f"/api/dashboard/team?metric_id={world['calls'].id}").json()
    assert body["metric_id"] == world["calls"].id
    assert body["members"][0]["name"] == "Cat"


def test_goals_sit_beside_the_numbers_and_say_who_is_behind(
    client, db, org, world, sign_in, make_fact
):
    when = within_this_month()
    make_fact(world["deals"], world["ann"], 1, when)
    make_fact(world["deals"], world["bob"], 30, when)
    make_fact(world["deals"], world["cat"], 2, when)
    goal_for(db, org, world["ann"], world["deals"], 100_000)
    goal_for(db, org, world["bob"], world["deals"], 20)
    sign_in(world["manager"])

    body = client.get("/api/dashboard/team").json()
    rows = {m["name"]: m for m in body["members"]}
    assert Decimal(rows["Bob"]["goal"]["target"]) == 20
    assert rows["Bob"]["goal"]["status"] == "hit"
    assert rows["Cat"]["goal"] is None
    assert {n["name"]: n["kind"] for n in body["shout_outs"]}["Bob"] == "hit"

    # Well into the month — fixed, because early on anybody near zero is still
    # on track, and at the very end it is missed — one deal of a hundred
    # thousand is behind, and says by how much.
    from app import team_home

    period = periods.resolve(org, "month", periods.today(org))
    late = period.start + (period.end - period.start) * 2 / 3
    home = team_home.build(db, org, world["manager"], world["sales"], now=late)
    ann = next(n for n in home.nudges if n.name == "Ann")
    assert ann.kind == "behind"
    assert (ann.value, ann.target) == (1, 100_000)
    assert 30_000 < ann.expected < 90_000


def test_quiet_people_are_named_with_how_long(client, db, org, world, sign_in, make_fact, make_user):
    make_fact(world["deals"], world["ann"], 3, datetime.now(UTC) - timedelta(days=12))
    make_fact(world["deals"], world["bob"], 3, datetime.now(UTC) - timedelta(days=1))
    # Enough people recording that two quiet ones are people, not a feed.
    for n in range(3):
        busy = make_user("agent", world["sales"], name=f"Busy {n}")
        make_fact(world["deals"], busy, 1, datetime.now(UTC) - timedelta(days=1))
    sign_in(world["manager"])

    body = client.get("/api/dashboard/team").json()

    quiet = {n["name"]: n["days"] for n in body["nudges"] if n["kind"] == "quiet"}
    assert quiet["Ann"] == 12
    assert quiet["Cat"] is None  # never recorded anything
    assert "Bob" not in quiet
    # The manager is never told to nudge themselves.
    assert "Mona Manager" not in quiet


def test_the_leader_is_worth_a_word(client, db, org, world, sign_in, make_fact):
    make_fact(world["deals"], world["cat"], 11, within_this_month())
    sign_in(world["manager"])
    body = client.get("/api/dashboard/team").json()
    assert [(n["name"], n["kind"]) for n in body["shout_outs"]] == [("Cat", "leading")]


def test_a_tie_at_the_top_names_nobody(client, db, org, world, sign_in, make_fact):
    make_fact(world["deals"], world["cat"], 4, within_this_month())
    make_fact(world["deals"], world["ann"], 4, within_this_month())
    sign_in(world["manager"])
    assert client.get("/api/dashboard/team").json()["shout_outs"] == []


def test_an_unknown_period_is_refused(client, world, sign_in):
    sign_in(world["manager"])
    assert client.get("/api/dashboard/team?period_type=custom").status_code == 422


def test_most_of_the_team_quiet_at_once_is_the_data_not_the_people(
    client, db, org, world, sign_in, make_fact
):
    make_fact(world["deals"], world["ann"], 3, datetime.now(UTC) - timedelta(days=9))
    make_fact(world["deals"], world["bob"], 3, datetime.now(UTC) - timedelta(days=8))
    sign_in(world["manager"])
    body = client.get("/api/dashboard/team").json()
    assert [(n["kind"], Decimal(n["value"]), n["days"]) for n in body["nudges"]] == [
        ("team_quiet", 3, 8)
    ]


def test_nobody_has_a_rank_until_somebody_scores(client, db, world, sign_in):
    sign_in(world["manager"])
    body = client.get("/api/dashboard/team").json()
    assert {m["rank"] for m in body["members"]} == {0}


def test_last_period_can_be_shown(client, db, org, world, sign_in, make_fact):
    """8.2: a month with nothing in it yet offers the one before."""
    this = periods.resolve(org, "month", periods.today(org))
    last = periods.previous(org, this)
    make_fact(world["deals"], world["ann"], 4, last.start + timedelta(days=2))
    sign_in(world["manager"])

    now = client.get(f"/api/dashboard/team?metric_id={world['deals'].id}").json()
    before = client.get(f"/api/dashboard/team?metric_id={world['deals'].id}&previous=true").json()

    assert all(float(m["value"]) == 0 for m in now["members"])
    assert before["period_label"] == last.label
    assert before["members"][0]["name"] == "Ann"
