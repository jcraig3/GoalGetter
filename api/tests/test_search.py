"""The command palette's search (6.16): everything by name, narrowed by the
same rule each list uses."""

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Channel, Competition, CompetitionParticipant, Goal, Leaderboard


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    sales = make_team("Sales")
    other = make_team("Other")
    metric = make_metric("deals")
    return {
        "sales": sales,
        "other": other,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", sales, name="Mona Manager"),
        "ann": make_user("agent", sales, name="Ann Andrews"),
        "andy": make_user("agent", other, name="Andy Other"),
        "metric": metric,
    }


def find(client, q):
    response = client.get("/api/search", params={"q": q})
    assert response.status_code == 200, response.json()
    return response.json()


def board(db, org, world, name, **fields):
    row = Leaderboard(
        organization_id=org.id, name=name, metric_definition_id=world["metric"].id,
        period_type="month", visibility=fields.pop("visibility", "org"), **fields,
    )
    db.add(row)
    db.flush()
    return row


def test_people_are_found_within_what_you_may_see(client, db, org, world, sign_in):
    # Profiles closed (9.5): a manager finds only the people they manage.
    org.profiles_public = False
    db.flush()
    sign_in(world["manager"])
    assert [p["name"] for p in find(client, "an")["people"]] == ["Ann Andrews", "Mona Manager"]
    org.profiles_public = True
    db.flush()

    sign_in(world["admin"])
    names = [p["name"] for p in find(client, "an")["people"]]
    # A name starting with it comes before one merely containing it.
    assert names[:2] == ["Andy Other", "Ann Andrews"]


def test_an_agent_finds_colleagues_by_name_only_while_profiles_are_open(
    client, db, org, world, sign_in
):
    """9.3: a person opens their profile, so an agent can find a colleague —
    by name, and without being shown or matched on anybody's address."""
    sign_in(world["ann"])
    found = find(client, "andy")["people"]
    assert [(p["name"], p["detail"]) for p in found] == [("Andy Other", "Other")]
    assert find(client, world["andy"].email.split("@")[0])["people"] == []

    org.profiles_public = False
    db.flush()
    assert find(client, "an")["people"] == []


def test_boards_follow_the_boards_list(client, db, org, world, sign_in):
    board(db, org, world, "Deals everyone")
    board(db, org, world, "Deals for Other", visibility="team", scope_type="team", scope_team_id=world["other"].id)
    sign_in(world["ann"])
    assert [b["name"] for b in find(client, "deals")["boards"]] == ["Deals everyone"]

    sign_in(world["admin"])
    assert len(find(client, "deals")["boards"]) == 2


def test_goals_are_found_by_who_and_what(client, db, org, world, sign_in):
    for person in (world["ann"], world["andy"]):
        db.add(Goal(
            organization_id=org.id, metric_definition_id=world["metric"].id, subject_type="user",
            subject_user_id=person.id, target_value=10, period_type="month",
            period_anchor=datetime.now(UTC).date().replace(day=1),
        ))
    db.flush()
    sign_in(world["manager"])
    goals = find(client, "ann")["goals"]
    assert [g["name"] for g in goals] == [f"Ann Andrews — {world['metric'].name}"]
    # Another team's goal is not hers to see.
    assert find(client, "andy")["goals"] == []


def test_contests_follow_who_may_see_them(client, db, org, world, sign_in):
    now = datetime.now(UTC)
    def contest(name, state, entrants):
        row = Competition(
            organization_id=org.id, name=name, metric_definition_id=world["metric"].id,
            entity_type="user", starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=5),
            state=state,
        )
        db.add(row)
        db.flush()
        for person in entrants:
            db.add(CompetitionParticipant(competition_id=row.id, user_id=person.id))
        db.flush()
    contest("Sprint in", "active", [world["ann"]])
    contest("Sprint elsewhere", "active", [world["andy"]])
    contest("Sprint draft", "draft", [world["ann"]])

    sign_in(world["ann"])
    assert [c["name"] for c in find(client, "sprint")["competitions"]] == ["Sprint in"]


def test_channels_are_an_admins(client, db, org, world, sign_in):
    db.add(Channel(organization_id=org.id, name="Lobby wall"))
    db.flush()
    sign_in(world["manager"])
    assert find(client, "lobby")["channels"] == []
    sign_in(world["admin"])
    assert [c["name"] for c in find(client, "lobby")["channels"]] == ["Lobby wall"]


def test_wildcards_are_taken_literally(client, db, org, world, sign_in):
    board(db, org, world, "Deals")
    sign_in(world["admin"])
    assert find(client, "%")["boards"] == []


def test_teams_offices_rules_badges_and_metrics_are_found_too(client, db, org, world, sign_in):
    """7.9 (review §8): "metropolis" found nothing. Each kind is offered to whoever
    can open its list."""
    from decimal import Decimal

    from app.models import AchievementRule, Badge, Office

    metropolis = Office(organization_id=org.id, name="Metropolis")
    db.add(metropolis)
    db.flush()
    world["sales"].name = "Metropolis Sales Team"
    world["sales"].office_id = metropolis.id
    db.add(AchievementRule(
        organization_id=org.id, name="Metropolis big deal", metric_definition_id=world["metric"].id,
        comparator="gte", threshold=Decimal(5),
    ))
    db.add(Badge(organization_id=org.id, name="Metropolis star"))
    world["metric"].name = "Metropolis deals"
    db.flush()

    sign_in(world["admin"])
    found = find(client, "metropolis")
    assert [(t["name"], t["detail"]) for t in found["teams"]] == [("Metropolis Sales Team", "Metropolis")]
    assert [o["name"] for o in found["offices"]] == ["Metropolis"]
    assert [r["name"] for r in found["rules"]] == ["Metropolis big deal"]
    assert [b["name"] for b in found["badges"]] == ["Metropolis star"]
    assert [m["name"] for m in found["metrics"]] == ["Metropolis deals"]

    # An agent can open Teams, and nothing else here.
    sign_in(world["ann"])
    found = find(client, "metropolis")
    assert [t["name"] for t in found["teams"]] == ["Metropolis Sales Team"]
    assert found["offices"] == found["rules"] == found["badges"] == found["metrics"] == []


def test_a_person_is_told_apart_by_their_address(client, db, world, sign_in):
    """Review §8: "Test User" and "Test user" were two identical lines."""
    sign_in(world["admin"])
    [ann] = [p for p in find(client, "ann")["people"] if p["name"] == "Ann Andrews"]
    assert ann["detail"] == f"Sales · {world['ann'].email}"
