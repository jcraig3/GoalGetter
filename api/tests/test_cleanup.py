"""What a deleted thing takes with it (7.5, Q2-6)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import events, notifications
from app.models import Competition, CompetitionParticipant, Goal, MetricFact, Notification


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    team = make_team("Sales")
    return {
        "team": team,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", team, name="Mona"),
        "ann": make_user("agent", team, name="Ann"),
        "bob": make_user("agent", team, name="Bob"),
        "metric": make_metric("deals"),
    }


def about(db, subject_type, subject_id):
    return db.scalars(
        select(Notification).where(
            Notification.subject_type == subject_type, Notification.subject_id == subject_id
        )
    ).all()


def test_a_deleted_contest_takes_its_notifications(client, db, org, world, sign_in):
    now = datetime.now(UTC)
    contest = Competition(
        organization_id=org.id, name="Sprint", metric_definition_id=world["metric"].id,
        entity_type="user", starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=2),
        state="cancelled",
    )
    db.add(contest)
    db.flush()
    db.add(CompetitionParticipant(competition_id=contest.id, user_id=world["ann"].id))
    for person in (world["ann"], world["bob"]):
        notifications.emit(
            db, org_id=org.id, user_id=person.id, event=events.COMPETITION_STARTED,
            subject_type="competition", subject_id=contest.id, title="Sprint has started",
        )
    db.flush()
    assert len(about(db, "competition", contest.id)) == 2

    sign_in(world["admin"])
    assert client.delete(f"/api/competitions/{contest.id}").status_code == 204
    assert about(db, "competition", contest.id) == []


def test_a_removed_comment_takes_its_notification(client, db, world, sign_in):
    sign_in(world["manager"])
    client.post("/api/recognition", json={"user_id": world["ann"].id, "message": "Great save"})
    entry = client.get("/api/achievements").json()[0]
    sign_in(world["bob"])
    comment = client.post(f"/api/feed/{entry['id']}/comments", json={"body": "Well done"}).json()["comments"][0]
    assert len(about(db, "feed_comment", comment["id"])) >= 1

    client.delete(f"/api/feed/comments/{comment['id']}")
    assert about(db, "feed_comment", comment["id"]) == []


def test_a_team_shout_out_goes_from_every_bell(client, db, world, sign_in):
    """One row per member; deleting the one it was opened from left the rest."""
    sign_in(world["manager"])
    client.post("/api/recognition", json={"team_id": world["team"].id, "message": "Record week"})
    copies = db.scalars(select(Notification).where(Notification.event_key == "recognition")).all()
    assert len(copies) >= 2

    entry = client.get("/api/achievements").json()[0]
    assert client.delete(f"/api/recognition/{entry['id']}").status_code == 204
    assert db.scalars(select(Notification).where(Notification.event_key == "recognition")).all() == []


def test_a_deleted_correction_takes_the_win_it_made(client, db, org, world, sign_in, make_fact):
    fact = make_fact(world["metric"], world["ann"], 900, datetime.now(UTC))
    notifications.emit(
        db, org_id=org.id, user_id=world["ann"].id, event=events.achievement("achievement:1"),
        subject_type="metric_fact", subject_id=fact.id, title="Big deal",
    )
    db.flush()
    sign_in(world["admin"])
    assert client.delete(f"/api/metric-facts/{fact.id}").status_code == 204
    assert about(db, "metric_fact", fact.id) == []
    assert db.get(MetricFact, fact.id) is None


def test_a_deleted_goal_takes_its_notifications(client, db, org, world, sign_in):
    goal = Goal(
        organization_id=org.id, metric_definition_id=world["metric"].id, subject_type="user",
        subject_user_id=world["ann"].id, target_value=Decimal(10), period_type="month",
        period_anchor=datetime.now(UTC).date().replace(day=1),
    )
    db.add(goal)
    db.flush()
    notifications.emit(
        db, org_id=org.id, user_id=world["ann"].id, event=events.GOAL_ASSIGNED,
        subject_type="goal", subject_id=goal.id, title="New goal",
    )
    db.flush()
    sign_in(world["admin"])
    assert client.delete(f"/api/goals/{goal.id}").status_code == 204
    assert about(db, "goal", goal.id) == []


def test_other_things_notifications_are_left_alone(client, db, org, world, sign_in):
    """Only what is about the deleted thing goes."""
    notifications.emit(
        db, org_id=org.id, user_id=world["ann"].id, event=events.GOAL_ASSIGNED,
        subject_type="goal", subject_id=999_999, title="Somebody else's goal",
    )
    db.flush()
    from app import cleanup

    assert cleanup.forget(db, org.id, *cleanup.about("goal", 123)) == 0
    assert len(about(db, "goal", 999_999)) == 1
