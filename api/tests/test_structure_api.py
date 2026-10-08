"""Teams and offices.

Office → Team → Agent is two fixed levels across separate tables. An office
cannot contain an office, so there is nothing to recurse and no cycle to
prevent — these tests pin down the guards that replaced the old hierarchy's
machinery.
"""

from datetime import UTC, datetime

import pytest

WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin"))


@pytest.fixture
def agent(make_user):
    return make_user("agent")


# ── Teams ────────────────────────────────────────────────────────────────────


def test_create_rename_and_list_a_team(client, admin):
    created = client.post("/api/teams", json={"name": "Enterprise"})
    assert created.status_code == 201
    team_id = created.json()["id"]

    renamed = client.patch(f"/api/teams/{team_id}", json={"name": "Enterprise EMEA"})
    assert renamed.json()["name"] == "Enterprise EMEA"
    assert "Enterprise EMEA" in [t["name"] for t in client.get("/api/teams").json()]


def test_a_team_made_after_the_data_counts_its_members_work(
    client, db, org, admin, make_user, make_metric, make_fact
):
    """QA-1, as it happened: data loaded, then the team built, then people
    added from the Teams tab. The team's board must not be empty."""
    from app import aggregate
    from app.periods import resolve

    metric = make_metric()
    alice, bob = make_user("agent"), make_user("agent")
    make_fact(metric, alice, 10, WHEN)
    make_fact(metric, bob, 15, WHEN)

    team_id = client.post("/api/teams", json={"name": "Metropolis Sales"}).json()["id"]
    added = client.post(
        "/api/users/bulk",
        json={"ids": [alice.id, bob.id], "action": "assign_team", "team_id": team_id},
    )
    assert added.status_code == 200

    month = resolve(org, "month", WHEN.date())
    rows = aggregate.run(db, org.id, admin, metric, month, group_by="team")
    assert [(r.subject_name, int(r.value)) for r in rows] == [("Metropolis Sales", 25)]


def test_member_counts_come_back_with_the_list(client, db, admin, make_user, make_team):
    """One grouped outer join, not a count query per team — the N+1 that shows
    up the moment there are twenty teams on screen."""
    team = make_team("Enterprise")
    make_user("agent", team)
    make_user("agent", team)
    row = next(t for t in client.get("/api/teams").json() if t["id"] == team.id)
    assert row["member_count"] == 2


def test_hidden_members_are_not_counted(client, db, admin, make_user, make_team):
    team = make_team("Enterprise")
    make_user("agent", team)
    departed = make_user("agent", team)
    departed.hidden_at = datetime.now(UTC)
    db.flush()
    row = next(t for t in client.get("/api/teams").json() if t["id"] == team.id)
    assert row["member_count"] == 1


def test_archiving_hides_a_team_from_the_default_list(client, admin, make_team):
    team = make_team("Old")
    client.post(f"/api/teams/{team.id}/archive")
    assert team.id not in [t["id"] for t in client.get("/api/teams").json()]
    assert team.id in [t["id"] for t in client.get("/api/teams?include_archived=true").json()]


def test_restoring_brings_a_team_back(client, admin, make_team):
    team = make_team("Old")
    client.post(f"/api/teams/{team.id}/archive")
    client.post(f"/api/teams/{team.id}/restore")
    assert team.id in [t["id"] for t in client.get("/api/teams").json()]


def test_an_empty_team_can_be_deleted(client, admin, make_team):
    team = make_team("Mistake")
    assert client.delete(f"/api/teams/{team.id}").status_code == 204
    assert client.patch(f"/api/teams/{team.id}", json={"name": "x"}).status_code == 404


def test_a_team_with_members_cannot_be_deleted(client, admin, make_team, make_user):
    team = make_team("Enterprise")
    make_user("agent", team)
    make_user("agent", team)
    response = client.delete(f"/api/teams/{team.id}")
    assert response.status_code == 409
    assert "2 people are" in response.json()["detail"]


def test_a_team_named_by_history_cannot_be_deleted(
    client, admin, make_team, make_user, make_metric, make_fact, db
):
    """`metric_fact.subject_team_id` is a snapshot, so past facts keep naming
    this team even after everyone has moved off it. That is the whole point of
    the snapshot — deleting the team would leave last quarter's leaderboard
    naming nobody.
    """
    team = make_team("Enterprise")
    person = make_user("agent", team)
    make_fact(make_metric(), person, 10, WHEN, team=team)

    # Move the last member off, so the member guard is not what refuses.
    person.team_id = None
    db.flush()

    response = client.delete(f"/api/teams/{team.id}")
    assert response.status_code == 409
    assert "recorded measurements" in response.json()["detail"]


def test_archive_remains_available_when_delete_is_blocked(
    client, admin, make_team, make_user
):
    """The guard has to leave a way forward, or it is just a dead end."""
    team = make_team("Enterprise")
    make_user("agent", team)
    assert client.delete(f"/api/teams/{team.id}").status_code == 409
    assert client.post(f"/api/teams/{team.id}/archive").status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", "/api/teams", {"name": "Nope"}),
        ("patch", "/api/teams/{id}", {"name": "Nope"}),
        ("post", "/api/teams/{id}/archive", None),
        ("delete", "/api/teams/{id}", None),
    ],
)
def test_an_agent_cannot_mutate_teams(client, db, agent, sign_in, make_team, method, path, body):
    team = make_team("Enterprise")
    sign_in(agent)
    resolved = path.format(id=team.id)
    response = getattr(client, method)(resolved, json=body) if body else getattr(client, method)(resolved)
    assert response.status_code == 403


def test_an_agent_can_read_teams(client, db, agent, sign_in, make_team):
    """Structure and names only — visible so people understand the
    organization. Performance data within it follows the scope rules."""
    make_team("Enterprise")
    sign_in(agent)
    assert client.get("/api/teams").status_code == 200


def test_another_organizations_team_is_not_found(client, db, admin):
    from app.models import Organization, Team

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = Team(organization_id=other.id, name="Theirs")
    db.add(theirs)
    db.flush()

    assert client.patch(f"/api/teams/{theirs.id}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/teams/{theirs.id}").status_code == 404


# ── Offices ──────────────────────────────────────────────────────────────────


def test_create_an_office_and_assign_a_team_to_it(client, admin):
    office = client.post("/api/offices", json={"name": "Phoenix"})
    assert office.status_code == 201
    office_id = office.json()["id"]

    team = client.post("/api/teams", json={"name": "Enterprise", "office_id": office_id})
    assert team.status_code == 201
    assert team.json()["office_name"] == "Phoenix"


def test_an_office_rolls_up_its_teams_and_their_agents(client, db, admin, make_user):
    """Two levels counted with two separate subqueries, not one join chain.

    Joining office → team → user in a single pass multiplies rows: this office
    would report 5 teams rather than 2, because each team row repeats once per
    agent. The classic fan-out trap in SQL aggregation, and the numbers here
    are deliberately unequal (2 teams, 5 agents) so a swap or a multiplication
    cannot coincidentally produce the right answer.
    """
    from app.models import Team

    office_id = client.post("/api/offices", json={"name": "Phoenix"}).json()["id"]
    enterprise_id = client.post(
        "/api/teams", json={"name": "Enterprise", "office_id": office_id}
    ).json()["id"]
    smb_id = client.post("/api/teams", json={"name": "SMB", "office_id": office_id}).json()["id"]

    enterprise, smb = db.get(Team, enterprise_id), db.get(Team, smb_id)
    for _ in range(3):
        make_user("agent", enterprise)
    for _ in range(2):
        make_user("agent", smb)

    # A team in no office, with agents, must not leak into the rollup.
    make_user("agent", None)

    row = next(o for o in client.get("/api/offices").json() if o["id"] == office_id)
    assert (row["team_count"], row["agent_count"]) == (2, 5)


def test_an_office_with_teams_cannot_be_deleted(client, admin):
    office_id = client.post("/api/offices", json={"name": "Phoenix"}).json()["id"]
    client.post("/api/teams", json={"name": "Enterprise", "office_id": office_id})

    response = client.delete(f"/api/offices/{office_id}")
    assert response.status_code == 409
    assert "1" in response.json()["detail"]


def test_an_empty_office_can_be_deleted(client, admin):
    office_id = client.post("/api/offices", json={"name": "Empty"}).json()["id"]
    assert client.delete(f"/api/offices/{office_id}").status_code == 204


def test_assigning_a_team_to_a_nonexistent_office_is_a_404(client, admin):
    assert client.post(
        "/api/teams", json={"name": "Enterprise", "office_id": 999999}
    ).status_code == 404


def test_explicit_null_office_id_unassigns_while_omitting_it_does_not(client, admin):
    office_id = client.post("/api/offices", json={"name": "Phoenix"}).json()["id"]
    team_id = client.post(
        "/api/teams", json={"name": "Enterprise", "office_id": office_id}
    ).json()["id"]

    assert client.patch(f"/api/teams/{team_id}", json={"name": "E2"}).json()["office_id"] == office_id
    assert client.patch(f"/api/teams/{team_id}", json={"office_id": None}).json()["office_id"] is None


def test_a_team_cannot_join_an_archived_office(client, admin):
    office_id = client.post("/api/offices", json={"name": "Closed"}).json()["id"]
    client.post(f"/api/offices/{office_id}/archive")
    assert client.post(
        "/api/teams", json={"name": "Enterprise", "office_id": office_id}
    ).status_code == 404


def test_a_manager_can_read_offices_but_not_create_them(client, db, make_user, make_team, sign_in):
    manager = make_user("manager", make_team("Enterprise"))
    sign_in(manager)
    assert client.get("/api/offices").status_code == 200
    assert client.post("/api/offices", json={"name": "Nope"}).status_code == 403


def test_an_office_named_by_history_cannot_be_deleted(
    client, admin, db, make_user, make_metric, make_fact
):
    """The office snapshot means facts point at an office directly, so an
    office whose teams have all moved away can still be named by history."""
    from app.models import Office, Team

    office_id = client.post("/api/offices", json={"name": "Phoenix"}).json()["id"]
    team_id = client.post(
        "/api/teams", json={"name": "Enterprise", "office_id": office_id}
    ).json()["id"]

    team = db.get(Team, team_id)
    person = make_user("agent", team)
    make_fact(make_metric(), person, 10, WHEN, office_id=office_id)

    # Move the team out, so the team guard is not what refuses.
    client.patch(f"/api/teams/{team_id}", json={"office_id": None})

    response = client.delete(f"/api/offices/{office_id}")
    assert response.status_code == 409
    assert "recorded measurements" in response.json()["detail"]
    assert db.get(Office, office_id) is not None


def test_an_office_with_no_history_still_deletes(client, admin):
    office_id = client.post("/api/offices", json={"name": "Empty"}).json()["id"]
    assert client.delete(f"/api/offices/{office_id}").status_code == 204
