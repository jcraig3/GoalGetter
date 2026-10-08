"""A goal the whole company pulls toward.

**The one shape a goal could not express.** A target belonged to one person or
one team, so "half a million this quarter, all of us" had to be faked as a team
goal for a team that did not exist, or drawn by hand on a message screen and
updated by somebody every morning.

The two properties worth guarding: everybody can read it — a shared figure that
each person sees their own slice of is not a shared figure — and only an admin
can set one, because it appears on every wall in the building.
"""

from datetime import timedelta
from decimal import Decimal

import pytest

from tests.conftest import within_this_month
from app.models import Office

WHEN = within_this_month()


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    phoenix = Office(organization_id=org.id, name="Phoenix")
    db.add(phoenix)
    db.flush()

    enterprise = make_team("Enterprise")
    enterprise.office_id = phoenix.id
    smb = make_team("SMB")
    db.flush()

    return {
        "phoenix": phoenix,
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", smb, name="Clark Kent"),
        "metric": make_metric("calls_made"),
    }


def make_goal(client, world, **overrides):
    body = {
        "metric_id": world["metric"].id,
        "subject_type": "organization",
        "target_value": "100",
        "period_type": "month",
        **overrides,
    }
    return client.post("/api/goals", json=body)


# -- Setting one -------------------------------------------------------------


def test_an_admin_can_set_one(client, db, world, sign_in):
    sign_in(world["admin"])

    reply = make_goal(client, world)

    assert reply.status_code == 201, reply.json()
    assert reply.json()["subject_type"] == "organization"


def test_it_names_nobody(client, db, world, sign_in):
    """**Both subject columns stay null.** An organization goal is not about a
    row in another table; inventing a sentinel id would make every query that
    joins a subject have to know about it."""
    sign_in(world["admin"])

    body = make_goal(client, world).json()

    assert body["subject_id"] is None


def test_it_is_named_after_the_company(client, db, org, world, sign_in):
    """Not the word "Everyone" — a target on a wall reading "Acme · 62%" says
    whose it is, and every other subject on that screen is named."""
    sign_in(world["admin"])

    body = make_goal(client, world).json()

    assert body["subject_name"] == org.name


def test_a_manager_cannot(client, db, world, sign_in):
    """It appears on every wall and everybody can read it. That is the same bar
    as publishing a board to everyone."""
    sign_in(world["manager"])

    reply = make_goal(client, world)

    assert reply.status_code == 403
    assert "whole organization" in reply.json()["detail"]


def test_a_subject_id_sent_by_mistake_is_ignored(client, db, world, sign_in):
    """A form that switched from "a person" to "everyone" without clearing its
    state must not silently create a goal about that person."""
    sign_in(world["admin"])

    body = make_goal(client, world, subject_id=world["peter"].id).json()

    assert body["subject_id"] is None


# -- What it measures --------------------------------------------------------


def test_it_counts_everybody(client, db, org, world, sign_in, make_fact):
    """Across teams, and across people on no team — the whole point is one
    figure the floor adds to together."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 40, WHEN)
    make_fact(world["metric"], world["clark"], 25, WHEN)
    db.commit()

    body = make_goal(client, world, target_value="100").json()

    assert Decimal(body["current_value"]) == Decimal(65)


def test_an_agent_sees_the_whole_figure_not_their_slice(
    client, db, org, world, sign_in, make_fact
):
    """**The shared number is the feature.** An agent who sees only their own
    contribution is looking at a personal goal with a company's name on it, and
    the wall beside them says something different."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 40, WHEN)
    make_fact(world["metric"], world["clark"], 25, WHEN)
    db.commit()
    goal = make_goal(client, world).json()

    sign_in(world["peter"])
    body = client.get(f"/api/goals/{goal['id']}").json()["goal"]

    assert Decimal(body["current_value"]) == Decimal(65)


def test_the_breakdown_is_by_team(client, db, org, world, sign_in, make_fact):
    """Four hundred rows under a company target is a directory, not an answer.
    "Which floor is carrying this" is the question somebody actually has."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 40, WHEN)
    make_fact(world["metric"], world["clark"], 25, WHEN)
    db.commit()
    goal = make_goal(client, world).json()

    body = client.get(f"/api/goals/{goal['id']}").json()

    names = {row["full_name"] for row in body["contributors"]}
    assert names == {"Enterprise", "SMB"}


def test_nothing_recorded_yet_is_zero_rather_than_an_error(
    client, db, world, sign_in
):
    sign_in(world["admin"])

    body = make_goal(client, world).json()

    assert Decimal(body["current_value"]) == Decimal(0)


# -- On a wall ---------------------------------------------------------------


def test_it_belongs_on_every_wall(client, db, org, world, sign_in, make_fact):
    """**The one goal that is genuinely organization-wide.** A goal about a
    person or a team is refused on another office's channel; this is the case
    that is not."""
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 40, WHEN)
    db.commit()
    goal = make_goal(client, world).json()
    channel = client.post(
        "/api/channels",
        json={
            "name": "Phoenix wall",
            "scope_type": "office",
            "scope_office_id": world["phoenix"].id,
        },
    ).json()

    reply = client.post(
        f"/api/channels/{channel['id']}/screens",
        json={"kind": "goal", "goal_id": goal["id"]},
    )

    assert reply.status_code == 201, reply.json()


def test_it_draws_the_company_figure_on_the_wall(
    client, db, org, world, sign_in, make_fact
):
    sign_in(world["admin"])
    make_fact(world["metric"], world["peter"], 40, WHEN)
    make_fact(world["metric"], world["clark"], 25, WHEN)
    db.commit()
    goal = make_goal(client, world).json()
    channel = client.post("/api/channels", json={"name": "Main"}).json()
    client.post(
        f"/api/channels/{channel['id']}/screens",
        json={"kind": "goal", "goal_id": goal["id"]},
    )

    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel["id"]}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    slide = client.get(f"/api/display/{token}").json()["slides"][0]

    assert Decimal(slide["current_value"]) == Decimal(65)
    # "Acme — Revenue" — whose, first. Every other goal screen names its
    # subject, and this one names the company.
    assert slide["title"].startswith(f"{org.name} — ")


# -- Who hears about it ------------------------------------------------------


def test_everybody_is_told(client, db, org, world, sign_in):
    """A target the whole floor is pulling toward that only reaches managers is
    a target the floor learns about from a wall."""
    from sqlalchemy import select

    from app import notifications
    from app.models import Notification

    sign_in(world["admin"])
    make_goal(client, world)
    # Notifications come from the sweep, not from the write — the same path a
    # goal spawned by the recurrence job takes.
    notifications.detect(db)

    told = db.scalars(
        select(Notification.user_id).where(
            Notification.event_key == "goal.assigned"
        )
    ).all()

    assert set(told) >= {
        world["peter"].id,
        world["clark"].id,
        world["manager"].id,
    }


def test_the_company_name_is_not_put_through_the_name_style(
    client, db, org, world, sign_in
):
    """"Acme" becoming "A." is the team-name bug in a different hat. The
    notification carries no `about_user_id`, which is what keeps it away."""
    from sqlalchemy import select

    from app import notifications
    from app.models import Notification

    sign_in(world["admin"])
    make_goal(client, world)
    notifications.detect(db)

    row = db.scalars(
        select(Notification).where(Notification.event_key == "goal.assigned")
    ).first()

    assert row.about_name == org.name
    assert row.about_user_id is None


# -- The history panel -------------------------------------------------------


def test_the_preview_argues_from_the_company_history(
    client, db, org, world, sign_in
):
    """A history that did not match how the goal is computed would argue for a
    target the goal could never report against."""
    sign_in(world["admin"])

    reply = client.post(
        "/api/goals/preview",
        json={
            "metric_id": world["metric"].id,
            "subject_type": "organization",
            "period_type": "month",
        },
    )

    assert reply.status_code == 200, reply.json()
    assert reply.json()["subject_name"] == org.name


def test_a_manager_cannot_see_that_history_either(client, db, world, sign_in):
    """Showing a manager a figure for a goal they are not allowed to set is an
    answer to a question they may not ask."""
    sign_in(world["manager"])

    reply = client.post(
        "/api/goals/preview",
        json={
            "metric_id": world["metric"].id,
            "subject_type": "organization",
            "period_type": "month",
        },
    )

    assert reply.status_code == 403


def test_the_past_periods_are_the_whole_companys(client, db, org, world, sign_in, make_fact):
    """**It read as all zeros.** The history walk had a branch for a team and a
    branch for a person, and an organization goal fell into the second — where
    it filtered rows down to `subject_user_id`, which for this shape is null.
    So the one goal whose history is easiest to compute was the one that never
    showed any, and a manager reading "you have never hit this" would have been
    reading a bug.
    """
    last_month = (WHEN.replace(day=1) - timedelta(days=5)).replace(day=15)
    make_fact(world["metric"], world["peter"], 70, last_month)
    make_fact(world["metric"], world["clark"], 40, last_month)

    sign_in(world["admin"])
    goal = make_goal(client, world).json()
    reply = client.get(f"/api/goals/{goal['id']}")

    assert reply.status_code == 200, reply.json()
    assert reply.json()["history"][-1]["value"] == "110.0000"
