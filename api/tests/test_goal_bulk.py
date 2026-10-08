"""One target for a team or office, adjusted person by person (6.12)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import periods
from app.models import AuditLog, Goal, Office, Organization


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    phoenix = Office(organization_id=org.id, name="Phoenix")
    db.add(phoenix)
    db.flush()
    sales = make_team("Sales")
    sales.office_id = phoenix.id
    support = make_team("Support")
    support.office_id = phoenix.id
    other = make_team("Elsewhere")
    db.flush()
    return {
        "office": phoenix,
        "sales": sales,
        "support": support,
        "other": other,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", sales, name="Mona Manager"),
        "ann": make_user("agent", sales, name="Ann"),
        "bob": make_user("agent", sales, name="Bob"),
        "cat": make_user("agent", support, name="Cat"),
        "gone": make_user("agent", sales, name="Gone", status="deactivated"),
        "far": make_user("agent", other, name="Far"),
        "metric": make_metric("deals"),
    }


def last_month(org: Organization) -> datetime:
    """Inside last month, wherever the calendar is."""
    current = periods.resolve(org, "month", periods.today(org))
    return periods.previous(org, current).start.astimezone(UTC) + timedelta(days=3)


def roster(client, world, **overrides):
    body = {
        "metric_id": world["metric"].id,
        "group_type": "team",
        "group_id": world["sales"].id,
        "period_type": "month",
        **overrides,
    }
    return client.post("/api/goals/bulk/roster", json=body)


def save(client, world, rows, **overrides):
    body = {
        "metric_id": world["metric"].id,
        "group_type": "team",
        "group_id": world["sales"].id,
        "period_type": "month",
        "rows": rows,
        **overrides,
    }
    return client.post("/api/goals/bulk", json=body)


def test_the_roster_is_the_working_team_with_last_months_figures(
    client, db, org, world, sign_in, make_fact
):
    make_fact(world["metric"], world["ann"], 30, last_month(org))
    make_fact(world["metric"], world["bob"], 10, last_month(org))
    sign_in(world["admin"])

    body = roster(client, world).json()

    rows = {row["name"]: row for row in body["people"]}
    # Deactivated people and other teams are not in it.
    assert sorted(rows) == ["Ann", "Bob", "Mona Manager"]
    assert Decimal(rows["Ann"]["last_value"]) == 30
    assert Decimal(rows["Mona Manager"]["last_value"]) == 0
    assert body["group_name"] == "Sales"
    # A little past the typical figure among people who did something.
    assert Decimal(body["suggested_target"]) == 30


def test_an_office_is_all_its_teams(client, db, world, sign_in):
    sign_in(world["admin"])
    body = roster(client, world, group_type="office", group_id=world["office"].id).json()
    assert sorted(p["name"] for p in body["people"]) == ["Ann", "Bob", "Cat", "Mona Manager"]
    assert {p["team_name"] for p in body["people"]} == {"Sales", "Support"}


def test_saving_makes_one_ordinary_goal_each(client, db, org, world, sign_in):
    sign_in(world["admin"])
    response = save(
        client, world,
        [{"user_id": world["ann"].id, "target_value": "40"},
         {"user_id": world["bob"].id, "target_value": "25"}],
        name="October push",
        recurring=True,
    )
    assert response.status_code == 201, response.json()
    assert response.json() == {"created": 2, "updated": 0, "unchanged": 0}

    goals = db.scalars(select(Goal).where(Goal.metric_definition_id == world["metric"].id)).all()
    by_person = {g.subject_user_id: g for g in goals}
    assert by_person[world["ann"].id].target_value == 40
    assert by_person[world["bob"].id].target_value == 25
    assert all(g.name == "October push" and g.recurring for g in goals)
    # The same period the goal form would have used.
    expected = periods.resolve(org, "month", periods.today(org)).start.astimezone(
        periods.tz(org)
    ).date()
    assert {g.period_anchor for g in goals} == {expected}

    # The ordinary goals list shows them like any other.
    listed = client.get("/api/goals").json()
    assert {g["subject_name"] for g in listed} >= {"Ann", "Bob"}

    # One audit entry for the whole grid.
    entries = db.scalars(select(AuditLog).where(AuditLog.action == "goal.bulk_set")).all()
    assert len(entries) == 1


def test_somebody_who_has_the_goal_is_updated_not_doubled(client, db, world, sign_in):
    sign_in(world["admin"])
    save(client, world, [{"user_id": world["ann"].id, "target_value": "40"}])

    shown = roster(client, world).json()
    ann = next(p for p in shown["people"] if p["name"] == "Ann")
    assert Decimal(ann["existing"]["target_value"]) == 40

    again = save(
        client, world,
        [{"user_id": world["ann"].id, "target_value": "50"},
         {"user_id": world["bob"].id, "target_value": "20"}],
    ).json()
    assert again == {"created": 1, "updated": 1, "unchanged": 0}
    ann_goals = db.scalars(select(Goal).where(Goal.subject_user_id == world["ann"].id)).all()
    assert [g.target_value for g in ann_goals] == [50]

    same = save(client, world, [{"user_id": world["ann"].id, "target_value": "50"}]).json()
    assert same == {"created": 0, "updated": 0, "unchanged": 1}


def test_somebody_not_in_the_group_refuses_the_lot(client, db, world, sign_in):
    sign_in(world["admin"])
    response = save(
        client, world,
        [{"user_id": world["ann"].id, "target_value": "40"},
         {"user_id": world["far"].id, "target_value": "40"}],
    )
    assert response.status_code == 400
    assert db.scalars(select(Goal)).all() == []


def test_a_manager_sets_their_own_team_only(client, db, world, sign_in):
    sign_in(world["manager"])
    assert roster(client, world).status_code == 200
    assert roster(client, world, group_id=world["other"].id).status_code == 403
    assert (
        roster(client, world, group_type="office", group_id=world["office"].id).status_code
        == 403
    )


def test_an_agent_cannot(client, db, world, sign_in):
    sign_in(world["ann"])
    assert roster(client, world).status_code == 403


def test_a_target_must_be_positive_and_a_period_ordinary(client, db, world, sign_in):
    sign_in(world["admin"])
    assert save(client, world, [{"user_id": world["ann"].id, "target_value": "0"}]).status_code == 422
    assert roster(client, world, period_type="custom").status_code == 422
