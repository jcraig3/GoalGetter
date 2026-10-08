"""Custom roles: a built-in role with capabilities taken away.

What has to be true: what a role takes away is refused by the server, not only
hidden; everything else the base role could do still works; a role only ever
narrows, and only while its base matches; the interface is told the narrowed
set; a narrowed admin cannot lift their own restriction; and only an admin
manages roles.
"""

import pytest

from app import roles
from app.models import CustomRole


@pytest.fixture
def team_lead(db, org):
    row = CustomRole(
        organization_id=org.id, name="Team lead", base_role="manager",
        removed=["competitions.manage", "metrics.correct"],
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def diana(db, make_user, make_team, team_lead):
    user = make_user("manager", make_team("Closers"), name="Diana Prince")
    user.custom_role_id = team_lead.id
    db.flush()
    return user


def test_the_route_map_names_what_a_request_needs():
    assert roles.capability_for("POST", "/api/competitions") == "competitions.manage"
    assert roles.capability_for("GET", "/api/competitions") is None
    assert roles.capability_for("GET", "/api/reporting/overview") == "reporting.view"
    assert roles.capability_for("POST", "/api/users/7/reset-password") == "users.reset_password"
    assert roles.capability_for("GET", "/api/admin/sso") == "integrations.manage"


def test_every_removable_capability_is_one_a_built_in_role_has():
    from app.scope import capabilities_for

    everything = set(capabilities_for("admin"))
    assert set(roles.REMOVABLE) <= everything


def test_what_a_role_takes_away_is_refused_by_the_server(client, sign_in, diana, make_metric):
    sign_in(diana)

    reply = client.post(
        "/api/competitions",
        json={"name": "Sprint", "metric_id": make_metric("calls").id,
              "starts_at": "2026-10-05T13:00:00Z", "ends_at": "2026-10-09T13:00:00Z"},
    )

    assert reply.status_code == 403
    assert reply.json()["detail"] == "Your role does not include that."


def test_everything_else_the_base_role_can_do_still_works(client, sign_in, diana):
    sign_in(diana)

    assert client.get("/api/competitions").status_code == 200
    assert client.get("/api/reporting/overview").status_code == 200


def test_the_interface_is_told_the_narrowed_set(client, sign_in, diana):
    sign_in(diana)

    capabilities = client.get("/api/auth/me").json()["capabilities"]

    assert "competitions.manage" not in capabilities
    assert "goals.manage" in capabilities


def test_a_role_stops_applying_when_the_base_changes(db, client, sign_in, diana):
    """Promoted to admin: a manager-based narrowing is not about them any more."""
    diana.org_role = "admin"
    db.flush()
    sign_in(diana)

    assert "competitions.manage" in client.get("/api/auth/me").json()["capabilities"]


# ── Managing roles ──────────────────────────────────────────────────────────


def test_an_admin_makes_a_role_and_adds_a_manager(client, sign_in, make_user):
    sign_in(make_user("admin", name="Bruce Wayne"))
    clark = make_user("manager", name="Clark Kent")

    made = client.post(
        "/api/roles", json={"name": "Coach", "base_role": "manager", "removed": ["goals.manage"]}
    ).json()
    added = client.post(f"/api/roles/{made['id']}/members", json={"user_id": clark.id}).json()

    assert [m["name"] for m in added["members"]] == ["Clark Kent"]


def test_only_people_on_the_base_role_can_join(client, sign_in, make_user, team_lead):
    sign_in(make_user("admin"))
    peter = make_user("agent", name="Peter Parker")

    reply = client.post(f"/api/roles/{team_lead.id}/members", json={"user_id": peter.id})

    assert reply.status_code == 409
    assert "Peter Parker is an agent, and this role is for managers." == reply.json()["detail"]


def test_a_role_must_take_something_away(client, sign_in, make_user):
    sign_in(make_user("admin"))

    reply = client.post("/api/roles", json={"name": "Same", "base_role": "manager", "removed": []})

    assert reply.status_code == 422


def test_a_role_cannot_take_away_what_its_base_never_had(client, sign_in, make_user):
    sign_in(make_user("admin"))

    reply = client.post(
        "/api/roles", json={"name": "Odd", "base_role": "manager", "removed": ["integrations.manage"]}
    )

    assert reply.status_code == 422


def test_the_catalogue_lists_what_each_base_can_lose(client, sign_in, make_user):
    sign_in(make_user("admin"))

    removable = client.get("/api/roles").json()["removable"]

    assert "integrations.manage" in {c["key"] for c in removable["admin"]}
    assert "integrations.manage" not in {c["key"] for c in removable["manager"]}


def test_a_narrowed_admin_cannot_lift_their_own_restriction(db, client, sign_in, org, make_user):
    make_user("admin", name="Other Admin")
    bruce = make_user("admin", name="Bruce Wayne")
    locked = CustomRole(organization_id=org.id, name="Reporting admin", base_role="admin", removed=["org.settings.edit"])
    db.add(locked)
    db.flush()
    bruce.custom_role_id = locked.id
    db.flush()
    sign_in(bruce)

    assert client.delete(f"/api/roles/{locked.id}").status_code == 403


def test_you_cannot_put_yourself_in_a_role_that_takes_settings(client, sign_in, db, org, make_user):
    bruce = make_user("admin", name="Bruce Wayne")
    sign_in(bruce)
    made = client.post(
        "/api/roles", json={"name": "Reports only", "base_role": "admin", "removed": ["org.settings.edit"]}
    ).json()

    reply = client.post(f"/api/roles/{made['id']}/members", json={"user_id": bruce.id})

    assert reply.status_code == 409


def test_deleting_a_role_returns_people_to_their_built_in_role(client, sign_in, db, diana, team_lead, make_user):
    sign_in(make_user("admin"))

    client.delete(f"/api/roles/{team_lead.id}")

    db.refresh(diana)
    assert diana.custom_role_id is None


def test_only_an_admin_manages_roles(client, sign_in, make_user):
    sign_in(make_user("manager"))

    assert client.get("/api/roles").status_code == 403
