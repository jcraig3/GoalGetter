"""Team identity (6.7): a colour, a short name and a logo, on the wall.

What has to be true: they are kept and checked; empty means none; a team row
on a wall carries them, with the logo where a face would be; a person's row is
untouched; and a logo in use is listed in Assets and cannot be removed.
"""

import io
from datetime import UTC, datetime

import pytest
from PIL import Image


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin", name="Admin"))


def logo(client) -> str:
    out = io.BytesIO()
    Image.new("RGBA", (300, 300), (37, 99, 235, 0)).save(out, format="PNG")
    return client.post(
        "/api/assets", content=out.getvalue(),
        headers={"content-type": "image/png", "x-file-name": "Enterprise.png"},
    ).json()["digest"]


def test_a_team_keeps_its_colour_short_name_and_logo(client, admin):
    mark = logo(client)
    made = client.post(
        "/api/teams",
        json={"name": "Enterprise Sales", "color": "#2563EB", "short_name": "  ENT  ", "logo": mark},
    )
    assert made.status_code == 201, made.json()
    assert (made.json()["color"], made.json()["short_name"], made.json()["logo"]) == ("#2563eb", "ENT", mark)

    cleared = client.patch(f"/api/teams/{made.json()['id']}", json={"short_name": "", "logo": None}).json()
    assert (cleared["short_name"], cleared["logo"], cleared["color"]) == (None, None, "#2563eb")


def test_a_colour_that_is_not_one_is_refused(client, admin):
    assert client.post("/api/teams", json={"name": "SMB", "color": "blue"}).status_code == 422


def test_a_logo_that_is_not_the_organizations_is_refused(client, admin):
    assert client.post("/api/teams", json={"name": "SMB", "logo": "a" * 64}).status_code == 422


def test_a_team_board_on_the_wall_carries_the_teams_look(client, db, admin, make_user, make_metric, make_fact):
    from app.models import Team

    mark = logo(client)
    ent = client.post(
        "/api/teams", json={"name": "Enterprise", "color": "#2563eb", "short_name": "ENT", "logo": mark}
    ).json()
    smb = client.post("/api/teams", json={"name": "SMB", "color": "#dc2626", "short_name": "SMB"}).json()
    metric = make_metric("calls_made")
    for team_id, value in ((ent["id"], 40), (smb["id"], 25)):
        person = make_user("agent")
        person.team_id = team_id
        db.flush()
        make_fact(metric, person, value, datetime.now(UTC), team=db.get(Team, team_id))
    db.commit()

    board = client.post(
        "/api/leaderboards",
        json={"name": "Teams", "metric_id": metric.id, "period_type": "month",
              "visibility": "org", "entity_type": "team"},
    ).json()
    slide = client.get(f"/api/leaderboards/{board['id']}/slide").json()
    rows = {row["entity_name"]: row for row in slide["entries"]}

    assert (rows["Enterprise"]["colour"], rows["Enterprise"]["short_name"]) == ("#2563eb", "ENT")
    assert rows["Enterprise"]["photo_digest"] == mark
    assert (rows["SMB"]["colour"], rows["SMB"]["photo_digest"]) == ("#dc2626", None)
    assert rows["Enterprise"]["is_team"] and rows["SMB"]["is_team"]

    # And Assets knows the logo is in use.
    listed = next(a for a in client.get("/api/assets").json() if a["digest"] == mark)
    assert listed["used_in"] == [{"label": "Logo of team “Enterprise”", "link": "/teams"}]
    assert client.delete(f"/api/assets/{mark}").status_code == 409


def test_a_person_board_is_not_mistaken_for_one(client, db, admin, make_user, make_metric, make_fact):
    """Every row carries `colour` and `short_name`, null on a person's — so the
    wall reads `is_team`, and a person's photograph stays a photograph."""
    metric = make_metric("calls_made")
    person = make_user("agent")
    make_fact(metric, person, 10, datetime.now(UTC))
    db.commit()
    board = client.post(
        "/api/leaderboards",
        json={"name": "People", "metric_id": metric.id, "period_type": "month", "visibility": "org"},
    ).json()
    row = client.get(f"/api/leaderboards/{board['id']}/slide").json()["entries"][0]
    assert row["is_team"] is False
