"""Phase 28: sign-in for admins and managers only; offices and teams from
Microsoft 365's Office and Department; people in an office with no team."""

import pytest

from app.models import Office, Team
from app.security import hash_password

PASSWORD = "correct horse battery staple"


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin", name="Admin"))


def _login(client, user):
    return client.post("/api/auth/login", json={"email": user.email, "password": PASSWORD})


def test_only_admins_and_managers_sign_in_when_switched_on(client, db, org, make_user, sign_in):
    agent, manager = make_user("agent"), make_user("manager")
    for user in (agent, manager):
        user.password_hash = hash_password(PASSWORD)
    db.flush()
    sign_in(agent)
    assert client.get("/api/auth/me").status_code == 200

    org.sign_in_leaders_only = True
    db.flush()

    # Their open session ends, and a new one is refused with the reason.
    assert client.get("/api/auth/me").status_code == 401
    refused = _login(client, agent)
    assert refused.status_code == 403
    assert "admins and managers" in refused.json()["detail"]
    assert _login(client, manager).status_code == 200


def test_the_switch_is_a_setting(client, admin):
    assert client.patch("/api/organization", json={"sign_in_leaders_only": True}).json()[
        "sign_in_leaders_only"
    ] is True


def test_offices_and_departments_sort_people(client, db, org, admin, make_user):
    a, b, c = make_user("agent"), make_user("agent"), make_user("agent")
    a.office_location, a.department = "Phoenix", "Sales"
    b.office_location, b.department = "phoenix ", "Support"
    c.office_location = "Dallas"
    db.flush()

    places = client.get("/api/admin/directory/places").json()
    assert [(v["value"], v["people"]) for v in places["offices"]] == [("Dallas", 1), ("Phoenix", 2)]

    # A new office named after the value; a new team from the department.
    client.put("/api/admin/directory/places/office", json={"value": "Phoenix", "target_id": None})
    out = client.put("/api/admin/directory/places/department", json={"value": "Sales", "target_id": None})
    assert out.status_code == 200, out.text

    phoenix = db.query(Office).filter_by(organization_id=org.id, name="Phoenix").one()
    sales = db.query(Team).filter_by(organization_id=org.id, name="Sales").one()
    for user in (a, b):
        db.refresh(user)
    assert a.team_id == sales.id and sales.office_id == phoenix.id
    assert b.team_id is None and b.office_id == phoenix.id

    # B is in Phoenix with no team: counted, and listed to place.
    office = next(o for o in client.get("/api/offices").json() if o["id"] == phoenix.id)
    assert (office["agent_count"], office["unteamed_count"]) == (2, 1)
    assert [p["id"] for p in client.get(f"/api/offices/{phoenix.id}/unteamed").json()] == [b.id]
