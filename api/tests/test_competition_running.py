"""Changing a competition while it runs, with a reason (6.14).

The prize, a later end, and late entrants — each recorded with the reason
given and shown on the contest's page. Everything else stays locked.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, Competition, CompetitionParticipant

NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
def world(make_team, make_user, make_metric):
    team = make_team("Sales")
    return {
        "admin": make_user("admin", name="Admin Person"),
        "ann": make_user("agent", team, name="Ann"),
        "bob": make_user("agent", team, name="Bob"),
        "cat": make_user("agent", team, name="Cat"),
        "metric": make_metric("deals"),
    }


@pytest.fixture
def running(db, org, world):
    contest = Competition(
        organization_id=org.id, name="October sprint", prize="Steak dinner",
        metric_definition_id=world["metric"].id, entity_type="user",
        starts_at=NOW - timedelta(days=3), ends_at=NOW + timedelta(days=4), state="active",
    )
    db.add(contest)
    db.flush()
    for person in (world["ann"], world["bob"]):
        db.add(CompetitionParticipant(competition_id=contest.id, user_id=person.id))
    db.flush()
    return contest


def detail(client, contest):
    return client.get(f"/api/competitions/{contest.id}").json()


def test_the_end_can_move_later_with_a_reason(client, db, world, running, sign_in):
    sign_in(world["admin"])
    later = running.ends_at + timedelta(days=7)

    response = client.patch(
        f"/api/competitions/{running.id}",
        json={"ends_at": later.isoformat(), "note": "The floor asked for another week"},
    )

    assert response.status_code == 200, response.json()
    assert datetime.fromisoformat(response.json()["ends_at"]) == later
    changes = detail(client, running)["changes"]
    assert len(changes) == 1
    assert changes[0]["what"].startswith("The end moved from ")
    assert changes[0]["note"] == "The floor asked for another week"
    assert changes[0]["who"] == "Admin Person"


def test_never_earlier(client, db, world, running, sign_in):
    """Ending early hands it to whoever is ahead today."""
    sign_in(world["admin"])
    response = client.patch(
        f"/api/competitions/{running.id}",
        json={"ends_at": (running.ends_at - timedelta(days=1)).isoformat(), "note": "Wrap it up"},
    )
    assert response.status_code == 400
    assert "cut short" in response.json()["detail"]


def test_not_without_a_reason(client, db, world, running, sign_in):
    sign_in(world["admin"])
    response = client.patch(
        f"/api/competitions/{running.id}",
        json={"ends_at": (running.ends_at + timedelta(days=1)).isoformat(), "note": "  "},
    )
    assert response.status_code == 400
    assert "Say why" in response.json()["detail"]


def test_the_prize_change_says_what_it_was(client, db, world, running, sign_in):
    sign_in(world["admin"])
    client.patch(
        f"/api/competitions/{running.id}",
        json={"prize": "Weekend away", "note": "Sponsor upgraded it"},
    )
    what = detail(client, running)["changes"][0]["what"]
    assert what == "The prize changed from “Steak dinner” to “Weekend away”."


def test_a_form_sending_everything_back_needs_no_reason_for_what_it_left_alone(
    client, db, world, running, sign_in
):
    sign_in(world["admin"])
    response = client.patch(
        f"/api/competitions/{running.id}",
        json={
            "name": "October sprint!",
            "prize": "Steak dinner",
            "starts_at": running.starts_at.isoformat(),
            "ends_at": running.ends_at.isoformat(),
        },
    )
    assert response.status_code == 200, response.json()
    assert detail(client, running)["changes"] == []


def test_the_rules_stay_locked(client, db, world, running, sign_in):
    sign_in(world["admin"])
    response = client.patch(
        f"/api/competitions/{running.id}",
        json={"starts_at": (running.starts_at + timedelta(days=1)).isoformat(), "note": "Oops"},
    )
    assert response.status_code == 409
    assert "starts_at" in response.json()["detail"]


def test_a_late_entrant_joins_with_a_reason(client, db, world, running, sign_in):
    sign_in(world["admin"])
    response = client.post(
        f"/api/competitions/{running.id}/participants",
        json={"entity_id": world["cat"].id, "note": "Started on Monday"},
    )
    assert response.status_code == 201, response.json()
    changes = detail(client, running)["changes"]
    assert changes[0]["what"] == "Cat joined after it started."
    assert changes[0]["note"] == "Started on Monday"
    assert db.scalar(select(AuditLog).where(AuditLog.action == "competition.joined_late")) is not None


def test_a_finished_contest_takes_nobody(client, db, world, running, sign_in):
    running.state = "ended"
    db.flush()
    sign_in(world["admin"])
    response = client.post(
        f"/api/competitions/{running.id}/participants",
        json={"entity_id": world["cat"].id, "note": "Please"},
    )
    assert response.status_code == 409
    extended = client.patch(
        f"/api/competitions/{running.id}",
        json={"ends_at": (running.ends_at + timedelta(days=1)).isoformat(), "note": "More"},
    )
    assert extended.status_code == 409


def test_the_page_knows_what_may_change(client, db, world, running, sign_in):
    sign_in(world["admin"])
    read = detail(client, running)["competition"]
    assert read["running_editable"] is True
    assert read["rules_editable"] is False


def test_a_moved_end_is_said_the_way_the_pages_say_dates(org):
    """Q2-29: "Fri 2 Oct, 11 pm", not "11:00 PM"."""
    from app.routers.competitions import _when

    # 03:00 UTC is 11 pm the evening before in New York.
    assert _when(org, datetime(2026, 10, 3, 3, 0, tzinfo=UTC)) == "Fri 2 Oct, 11 pm"
    assert _when(org, datetime(2026, 10, 2, 14, 26, tzinfo=UTC)) == "Fri 2 Oct, 10:26 am"
