"""The recurring-goal spawner.

Idempotency is the whole point, so most of these run the job twice and assert
the second run changed nothing.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import jobs
from app.models import Goal

AUGUST = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)
SEPTEMBER = datetime(2026, 9, 15, 15, 0, tzinfo=UTC)
OCTOBER = datetime(2026, 10, 15, 15, 0, tzinfo=UTC)


@pytest.fixture
def make_goal(db, org, make_metric, make_user, make_team):
    metric = make_metric("calls_made")
    person = make_user("agent", make_team("Enterprise"), name="Teammate")

    def _make(**overrides):
        # Merged rather than passed alongside **overrides, so overriding any
        # default is not a duplicate-keyword TypeError.
        fields = {
            "organization_id": org.id,
            "metric_definition_id": metric.id,
            "subject_type": "user",
            "subject_user_id": person.id,
            "target_value": Decimal(200),
            "period_type": "month",
            "period_anchor": date(2026, 8, 1),
            "recurring": True,
            **overrides,
        }
        goal = Goal(**fields)
        db.add(goal)
        db.flush()
        return goal

    return _make


def goal_count(db) -> int:
    return db.scalar(select(func.count()).select_from(Goal)) or 0


# ── Spawning ─────────────────────────────────────────────────────────────────


def test_nothing_spawns_while_the_original_covers_the_current_period(db, make_goal):
    make_goal()
    report = jobs.spawn_due_goals(db, AUGUST)
    assert (report.created, report.skipped) == (0, 1)
    assert goal_count(db) == 1


def test_a_copy_appears_once_the_period_moves_on(db, make_goal):
    root = make_goal()
    report = jobs.spawn_due_goals(db, SEPTEMBER)
    assert report.created == 1

    child = db.scalar(select(Goal).where(Goal.spawned_from_goal_id == root.id))
    assert child.period_anchor == date(2026, 9, 1)
    assert child.target_value == root.target_value
    assert child.subject_user_id == root.subject_user_id


def test_the_copy_does_not_itself_recur(db, make_goal):
    """The chain stays one level deep. A copy that spawned further would fork
    the chain and break the "one spawn per source per period" guarantee."""
    root = make_goal()
    jobs.spawn_due_goals(db, SEPTEMBER)
    child = db.scalar(select(Goal).where(Goal.spawned_from_goal_id == root.id))
    assert child.recurring is False


def test_every_copy_points_at_the_original_not_the_previous_copy(db, make_goal):
    """Which is what makes "has this period been spawned?" one indexed lookup
    rather than a recursive walk."""
    root = make_goal()
    jobs.spawn_due_goals(db, SEPTEMBER)
    jobs.spawn_due_goals(db, OCTOBER)

    children = db.scalars(select(Goal).where(Goal.spawned_from_goal_id == root.id)).all()
    assert len(children) == 2
    assert {c.period_anchor for c in children} == {date(2026, 9, 1), date(2026, 10, 1)}


def test_the_target_is_copied_not_referenced(db, make_goal):
    """Raising next month's target must not silently rewrite what last month
    was judged against."""
    root = make_goal()
    jobs.spawn_due_goals(db, SEPTEMBER)
    child = db.scalar(select(Goal).where(Goal.spawned_from_goal_id == root.id))

    root.target_value = Decimal(999)
    db.flush()
    db.refresh(child)
    assert child.target_value == Decimal(200)


# ── Idempotency ──────────────────────────────────────────────────────────────


def test_running_twice_creates_one_copy(db, make_goal):
    make_goal()
    first = jobs.spawn_due_goals(db, SEPTEMBER)
    second = jobs.spawn_due_goals(db, SEPTEMBER)

    assert first.created == 1
    assert second.created == 0
    assert goal_count(db) == 2


def test_running_repeatedly_through_a_period_creates_one_copy(db, make_goal):
    """The job runs hourly. A month of that must not produce a month of goals —
    the anchor is the period's start date, not today's, so every run inside
    September computes the same value."""
    make_goal()
    for day in (1, 5, 15, 28, 30):
        jobs.spawn_due_goals(db, SEPTEMBER.replace(day=day))
    assert goal_count(db) == 2


def test_the_database_refuses_a_duplicate_spawn_directly(db, make_goal):
    """The guarantee is the unique index, not the job checking first. A
    check-then-insert is a race: two workers both see nothing and both write."""
    from sqlalchemy.exc import IntegrityError

    root = make_goal()
    jobs.spawn_due_goals(db, SEPTEMBER)

    db.add(
        Goal(
            organization_id=root.organization_id,
            metric_definition_id=root.metric_definition_id,
            subject_type="user",
            subject_user_id=root.subject_user_id,
            target_value=Decimal(1),
            period_type="month",
            period_anchor=date(2026, 9, 1),
            spawned_from_goal_id=root.id,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_ordinary_duplicate_goals_are_still_allowed(db, make_goal):
    """The index is partial on purpose. Two manual goals for the same person,
    metric, and month with different targets — a minimum and a stretch — are a
    real thing people set."""
    make_goal(recurring=False)
    make_goal(recurring=False, target_value=Decimal(500))
    assert goal_count(db) == 2


# ── Catching up, and stopping ────────────────────────────────────────────────


def test_a_long_gap_spawns_only_the_current_period(db, make_goal):
    """Six months of missed runs must not produce six back-dated goals nobody
    saw. Targets for periods that already closed are noise, and inventing the
    history of what was asked for is worse than a gap in it."""
    make_goal()
    report = jobs.spawn_due_goals(db, datetime(2027, 2, 15, tzinfo=UTC))

    assert report.created == 1
    anchors = db.scalars(select(Goal.period_anchor)).all()
    assert set(anchors) == {date(2026, 8, 1), date(2027, 2, 1)}


def test_recurrence_stops_after_its_end_date(db, make_goal):
    make_goal(recurrence_ends_on=date(2026, 8, 31))
    report = jobs.spawn_due_goals(db, SEPTEMBER)
    assert (report.created, report.ended) == (0, 1)


def test_recurrence_continues_up_to_its_end_date(db, make_goal):
    make_goal(recurrence_ends_on=date(2026, 12, 31))
    assert jobs.spawn_due_goals(db, SEPTEMBER).created == 1


def test_archiving_the_original_stops_it_recurring(db, make_goal):
    """How you turn a recurring goal off without deleting its history."""
    root = make_goal()
    root.archived_at = datetime.now(UTC)
    db.flush()
    assert jobs.spawn_due_goals(db, SEPTEMBER).created == 0


def test_a_non_recurring_goal_never_spawns(db, make_goal):
    make_goal(recurring=False)
    assert jobs.spawn_due_goals(db, SEPTEMBER).created == 0


def test_deleting_the_original_removes_its_copies(db, make_goal):
    """ON DELETE CASCADE. An orphaned copy would keep appearing with no way to
    stop it — the only control is on the original."""
    root = make_goal()
    jobs.spawn_due_goals(db, SEPTEMBER)
    assert goal_count(db) == 2

    db.delete(root)
    db.flush()
    assert goal_count(db) == 0


# ── Periods other than months ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("period_type", "anchor", "later", "expected"),
    [
        ("week", date(2026, 8, 3), datetime(2026, 8, 12, tzinfo=UTC), date(2026, 8, 10)),
        ("quarter", date(2026, 7, 1), datetime(2026, 11, 5, tzinfo=UTC), date(2026, 10, 1)),
        ("year", date(2026, 1, 1), datetime(2027, 5, 5, tzinfo=UTC), date(2027, 1, 1)),
    ],
)
def test_the_cadence_follows_the_period_type(db, make_goal, period_type, anchor, later, expected):
    """No separate frequency field — a monthly goal repeats monthly. Storing
    the cadence twice would let the two disagree."""
    make_goal(period_type=period_type, period_anchor=anchor)
    jobs.spawn_due_goals(db, later)
    child = db.scalar(select(Goal).where(Goal.spawned_from_goal_id.is_not(None)))
    assert child.period_anchor == expected


def test_the_anchor_is_resolved_in_the_organization_timezone(db, org, make_goal):
    """1 September 00:30 UTC is still August in New York, so the September copy
    is not due yet."""
    make_goal()
    assert jobs.spawn_due_goals(db, datetime(2026, 9, 1, 0, 30, tzinfo=UTC)).created == 0
    assert jobs.spawn_due_goals(db, datetime(2026, 9, 1, 12, 0, tzinfo=UTC)).created == 1


# ── Dry run and reporting ────────────────────────────────────────────────────


def test_a_dry_run_changes_nothing(db, make_goal):
    make_goal()
    report = jobs.spawn_due_goals(db, SEPTEMBER, dry_run=True)
    assert report.created == 1
    assert goal_count(db) == 1
    assert report.details


def test_run_all_reports_what_it_did(db, make_goal):
    make_goal()
    report = jobs.run_all(db)
    assert isinstance(report, jobs.SpawnReport)


def test_a_goal_anchored_mid_period_does_not_spawn_a_copy_of_itself(db, make_goal):
    """The bug this test exists for.

    The API defaults `period_anchor` to today, so a goal created on the 13th
    stores 2026-08-13 while the job normalises to the period start, 2026-08-01.
    Two different dates naming the same month — so the "already covered" check
    compared unequal values and spawned a duplicate August goal on the first
    run.

    The unit fixtures all used 2026-08-01, the already-normalised form, which
    is exactly why they missed it. Only creating a goal through the real API
    exposed it.
    """
    make_goal(period_anchor=date(2026, 8, 13))
    report = jobs.spawn_due_goals(db, AUGUST)
    assert report.created == 0
    assert goal_count(db) == 1


def test_the_stored_anchor_is_normalised_to_the_period_start(client, db, org, make_metric,
                                                             make_user, sign_in):
    """Canonical storage, so two goals for "August" always agree on how August
    is written down."""
    metric = make_metric("calls_made")
    admin = make_user("admin")
    person = make_user("agent")
    sign_in(admin)

    created = client.post(
        "/api/goals",
        json={
            "metric_id": metric.id,
            "subject_type": "user",
            "subject_id": person.id,
            "target_value": "100",
            "period_type": "month",
            "period_anchor": "2026-08-13",
        },
    ).json()
    assert db.get(Goal, created["id"]).period_anchor == date(2026, 8, 1)
