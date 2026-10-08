"""Stretch targets: levels past a goal's target.

What has to be true: the target is still the target; each level crossed is
announced once per period and paid once; nothing past an unreached level is
claimed; a level has to be harder than the one before it — above for a count,
below for something where lower is better; and a recurring goal carries its
levels into the next period.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import announcements, events, goal_tiers, notifications, points
from app.jobs import spawn_due_goals
from app.models import Goal, Notification, PointAward

WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)

LEVELS = [{"value": "150", "label": "Stretch"}, {"value": "200", "label": "Crushed it"}]


@pytest.fixture
def world(db, org, make_user, make_metric):
    return {
        "admin": make_user("admin", name="Bruce Wayne"),
        "peter": make_user("agent", name="Peter Parker"),
        "metric": make_metric("calls_made"),
    }


def goal_for(db, org, world, **extra):
    fields = {
        "organization_id": org.id, "metric_definition_id": world["metric"].id,
        "subject_type": "user", "subject_user_id": world["peter"].id,
        "target_value": Decimal(100), "period_type": "month",
        "period_anchor": date(2026, 8, 1), "stretch_targets": LEVELS, **extra,
    }
    goal = Goal(**fields)
    db.add(goal)
    db.flush()
    return goal


def keys(db):
    return sorted(n.event_key for n in db.scalars(select(Notification)).all())


# ── Detection ───────────────────────────────────────────────────────────────


def test_reaching_the_first_level_announces_it(db, org, world, make_fact):
    goal_for(db, org, world)
    make_fact(world["metric"], world["peter"], 160, WHEN)

    notifications.detect(db, now=WHEN)

    assert "goal.stretch.1" in keys(db)
    assert "goal.stretch.2" not in keys(db), "nothing past an unreached level"
    stretch = db.scalar(select(Notification).where(Notification.event_key == "goal.stretch.1"))
    assert stretch.title == "Calls Made: Stretch reached"


def test_the_target_alone_is_just_the_target(db, org, world, make_fact):
    goal_for(db, org, world)
    make_fact(world["metric"], world["peter"], 120, WHEN)

    notifications.detect(db, now=WHEN)

    assert not [k for k in keys(db) if k.startswith("goal.stretch")]
    assert "goal.achieved" in keys(db)


def test_every_level_is_said_once_however_often_the_job_runs(db, org, world, make_fact):
    goal_for(db, org, world)
    make_fact(world["metric"], world["peter"], 250, WHEN)

    notifications.detect(db, now=WHEN)
    notifications.detect(db, now=WHEN)

    assert [k for k in keys(db) if k.startswith("goal.stretch")] == ["goal.stretch.1", "goal.stretch.2"]


def test_each_level_pays_on_top_of_the_target(db, org, world, make_fact):
    goal_for(db, org, world)
    make_fact(world["metric"], world["peter"], 250, WHEN)

    notifications.detect(db, now=WHEN)
    notifications.detect(db, now=WHEN)

    paid = sorted(
        (a.event_key, a.points) for a in db.scalars(select(PointAward)).all()
    )
    assert paid == [("goal.achieved", 100), ("goal.stretch.1", 50), ("goal.stretch.2", 50)]


def test_lower_is_better_stretches_downward(db, org, world, make_metric, make_fact):
    handle_time = make_metric("handle_time", aggregation="avg", direction="lower_is_better")
    goal_for(
        db, org, world, metric_definition_id=handle_time.id, target_value=Decimal(300),
        stretch_targets=[{"value": "240", "label": "Stretch"}],
    )
    make_fact(handle_time, world["peter"], 200, WHEN)

    notifications.detect(db, now=WHEN)

    assert "goal.stretch.1" in keys(db)


def test_stretch_is_public_and_celebrated():
    for event in events.GOAL_STRETCH:
        assert event.public and event.celebrate and event.major
        assert event.key in events.PUBLIC_EVENT_KEYS


def test_a_teams_channel_asks_for_all_levels_at_once(db, org, world, make_fact):
    """One choice, "stretch targets hit", covers every level."""
    from app.models import AnnouncementDestination

    destination = AnnouncementDestination(organization_id=org.id, name="Floor", events=["goal.stretch"])
    row = Notification(event_key="goal.stretch.2")
    assert announcements._wanted(destination, row)
    assert "goal.stretch" in announcements.DEFAULT_CHOICES


def test_stretch_levels_have_default_points():
    assert all(points.DEFAULTS[e.key] == 50 for e in events.GOAL_STRETCH)


# ── Checking levels ─────────────────────────────────────────────────────────


def test_levels_must_climb_above_the_target():
    with pytest.raises(ValueError, match="above the target"):
        goal_tiers.check(Decimal(100), [{"value": 90}], "higher_is_better")
    with pytest.raises(ValueError, match="above the level before it"):
        goal_tiers.check(Decimal(100), [{"value": 150}, {"value": 140}], "higher_is_better")


def test_lower_is_better_levels_must_fall():
    assert goal_tiers.check(Decimal(300), [{"value": 240}], "lower_is_better")[0]["value"] == "240"
    with pytest.raises(ValueError, match="below the target"):
        goal_tiers.check(Decimal(300), [{"value": 320}], "lower_is_better")


def test_a_level_nobody_named_gets_a_name():
    stored = goal_tiers.check(Decimal(100), [{"value": 150}, {"value": 200, "label": " "}], "higher_is_better")
    assert [s["label"] for s in stored] == ["Stretch", "Stretch 2"]


def test_no_more_than_three():
    with pytest.raises(ValueError, match="at most 3"):
        goal_tiers.check(Decimal(1), [{"value": v} for v in (2, 3, 4, 5)], "higher_is_better")


# ── Recurrence ──────────────────────────────────────────────────────────────


def test_a_recurring_goal_carries_its_levels_forward(db, org, world):
    root = goal_for(db, org, world, recurring=True)

    spawn_due_goals(db, now=datetime(2026, 9, 3, 15, tzinfo=UTC))

    child = db.scalar(select(Goal).where(Goal.spawned_from_goal_id == root.id))
    assert child.stretch_targets == LEVELS


# ── The API ─────────────────────────────────────────────────────────────────


def test_a_goal_is_made_with_levels_and_reads_them_back(client, sign_in, world):
    sign_in(world["admin"])

    made = client.post(
        "/api/goals",
        json={
            "metric_id": world["metric"].id, "subject_type": "user",
            "subject_id": world["peter"].id, "target_value": 100,
            "stretch": [{"value": 150}, {"value": 200, "label": "Crushed it"}],
        },
    ).json()

    assert [(s["label"], float(s["value"]), s["reached"]) for s in made["stretch"]] == [
        ("Stretch", 150.0, False), ("Crushed it", 200.0, False),
    ]


def test_a_level_easier_than_the_target_is_refused_in_words(client, sign_in, world):
    sign_in(world["admin"])

    reply = client.post(
        "/api/goals",
        json={
            "metric_id": world["metric"].id, "subject_type": "user",
            "subject_id": world["peter"].id, "target_value": 100, "stretch": [{"value": 80}],
        },
    )

    assert reply.status_code == 400
    assert "above the target" in reply.json()["detail"]


def test_raising_the_target_past_a_level_is_refused(client, sign_in, db, org, world):
    sign_in(world["admin"])
    goal = goal_for(db, org, world)

    reply = client.patch(f"/api/goals/{goal.id}", json={"target_value": 175})

    assert reply.status_code == 400


def test_levels_can_be_removed(client, sign_in, db, org, world):
    sign_in(world["admin"])
    goal = goal_for(db, org, world)

    client.patch(f"/api/goals/{goal.id}", json={"stretch": []})

    db.refresh(goal)
    assert goal.stretch_targets == []
