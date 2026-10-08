"""Goals: targets, progress, and who may set them for whom."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.goals import progress
from app.models import AuditLog, Goal
from tests.conftest import org_today

WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)
ANCHOR = "2026-08-12"


@pytest.fixture
def world(make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "teammate": make_user("agent", enterprise, name="Teammate"),
        "stranger": make_user("agent", smb, name="Stranger"),
        "metric": make_metric("calls_made"),
    }


def goal_body(world, **overrides):
    body = {
        "metric_id": world["metric"].id,
        "subject_type": "user",
        "subject_id": world["teammate"].id,
        "target_value": "100",
        "period_type": "month",
        "period_anchor": ANCHOR,
    }
    return {**body, **overrides}


def audit_count(db) -> int:
    return db.scalar(select(func.count()).select_from(AuditLog)) or 0


# ── progress(), as a pure function ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("current", "target", "percent", "attained"),
    [
        (0, 100, 0.0, False),
        (50, 100, 50.0, False),
        (100, 100, 100.0, True),
        (150, 100, 150.0, True),  # not capped — beating a target is the point
        (3, 7, 42.9, False),  # one decimal place
    ],
)
def test_progress_when_higher_is_better(current, target, percent, attained):
    result = progress(Decimal(current), Decimal(target), "higher_is_better")
    assert (result.percent, result.attained) == (percent, attained)


@pytest.mark.parametrize(
    ("current", "target", "attained"),
    [
        (30, 60, True),  # under target — success
        (60, 60, True),  # exactly on it
        (90, 60, False),  # over — missed
        (0, 60, True),  # a measured zero really is under the cap
    ],
)
def test_progress_when_lower_is_better(current, target, attained):
    """Response time, cost per deal. Treating these like a count would show
    someone at 40% for beating their target by 60%."""
    assert progress(Decimal(current), Decimal(target), "lower_is_better").attained is attained


def test_an_empty_period_is_not_an_attained_lower_is_better_goal():
    """Absence is not achievement.

    Nothing recorded reads as zero, and zero is under every cap — so without
    the has_data flag, "keep average response time under 60 seconds" reports
    HIT for an agent who answered no calls at all. A goal that congratulates
    you for doing nothing is worse than no goal.
    """
    result = progress(Decimal(0), Decimal(60), "lower_is_better", has_data=False)
    assert result.attained is False
    assert result.percent == 0.0


def test_a_measured_zero_still_counts_for_lower_is_better():
    """The other direction — the guard above must not swallow a genuine zero,
    which for "escalations this month" is the best possible outcome."""
    result = progress(Decimal(0), Decimal(60), "lower_is_better", has_data=True)
    assert result.attained is True


def test_an_empty_period_is_not_attained_for_higher_is_better_either():
    result = progress(Decimal(0), Decimal(100), "higher_is_better", has_data=False)
    assert result.attained is False


def test_progress_is_capped_at_a_sane_ceiling():
    """Uncapped, one stray fact makes a bar 40,000% wide and the layout with
    it. 1000% is generous enough to be honest and bounded enough to render."""
    assert progress(Decimal(999999), Decimal(1), "higher_is_better").percent == 1000.0


def test_progress_of_zero_against_a_lower_is_better_target_does_not_divide_by_zero():
    assert progress(Decimal(0), Decimal(10), "lower_is_better").percent == 100.0


# ── Creating ─────────────────────────────────────────────────────────────────


def test_an_admin_can_set_a_goal_for_a_person(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.post("/api/goals", json=goal_body(world))
    assert response.status_code == 201
    body = response.json()
    assert body["subject_name"] == "Teammate"
    assert body["period_label"] == "August 2026"
    # Compared numerically, not as a string: an empty result is Python's
    # Decimal(0) -> "0", while a value from the database carries its
    # NUMERIC(18,4) scale -> "40.0000". Both parse to the same number, and the
    # client formats by the metric's decimal_places either way.
    assert Decimal(body["current_value"]) == 0
    assert body["percent"] == 0.0


def test_a_goal_for_a_team(client, db, world, sign_in):
    sign_in(world["admin"])
    body = client.post(
        "/api/goals",
        json=goal_body(world, subject_type="team", subject_id=world["enterprise"].id),
    ).json()
    assert body["subject_type"] == "team"
    assert body["subject_name"] == "Enterprise"


def test_the_period_defaults_to_the_current_month(client, db, world, sign_in):
    """"This month" should need no date from the client at all."""
    sign_in(world["admin"])
    payload = goal_body(world)
    del payload["period_anchor"]
    assert client.post("/api/goals", json=payload).status_code == 201


def test_a_custom_period_needs_both_dates(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post(
        "/api/goals",
        json=goal_body(world, period_type="custom", period_anchor=None, period_start="2026-08-01"),
    ).status_code == 400


def test_a_custom_period_with_both_dates_works(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.post(
        "/api/goals",
        json=goal_body(
            world,
            period_type="custom",
            period_anchor=None,
            period_start="2026-08-01",
            period_end="2026-08-31",
        ),
    )
    assert response.status_code == 201


@pytest.mark.parametrize(
    "override",
    [
        {"target_value": "0"},
        {"target_value": "-5"},
        {"subject_type": "office"},
        {"period_type": "fortnight"},
        {"metric_id": 999999},
        {"subject_id": 999999},
        {"note": "extra field"},
    ],
)
def test_invalid_goals_are_refused(client, db, world, sign_in, override):
    sign_in(world["admin"])
    assert client.post("/api/goals", json=goal_body(world, **override)).status_code in (
        400,
        404,
        422,
    )


def test_a_goal_cannot_be_set_against_an_archived_metric(client, db, world, sign_in):
    sign_in(world["admin"])
    client.post(f"/api/metrics/{world['metric'].id}/archive")
    response = client.post("/api/goals", json=goal_body(world))
    assert response.status_code == 409
    assert "archived" in response.json()["detail"]


def test_the_database_refuses_a_goal_with_two_subjects(db, org, world):
    """The CHECK constraint, not just the API. A goal for both a person and a
    team has no defined meaning, so it must not be storable."""
    from sqlalchemy.exc import IntegrityError

    db.add(
        Goal(
            organization_id=org.id,
            metric_definition_id=world["metric"].id,
            subject_type="user",
            subject_user_id=world["teammate"].id,
            subject_team_id=world["enterprise"].id,  # both — invalid
            target_value=Decimal(10),
            period_type="month",
            period_anchor=date(2026, 8, 1),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_the_database_refuses_a_goal_with_no_subject(db, org, world):
    from sqlalchemy.exc import IntegrityError

    db.add(
        Goal(
            organization_id=org.id,
            metric_definition_id=world["metric"].id,
            subject_type="user",
            target_value=Decimal(10),
            period_type="month",
            period_anchor=date(2026, 8, 1),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_the_database_refuses_a_period_that_cannot_be_resolved(db, org, world):
    """A non-custom goal with no anchor could never be turned into a window,
    and would fail on whatever page tried to render it."""
    from sqlalchemy.exc import IntegrityError

    db.add(
        Goal(
            organization_id=org.id,
            metric_definition_id=world["metric"].id,
            subject_type="user",
            subject_user_id=world["teammate"].id,
            target_value=Decimal(10),
            period_type="month",
            period_anchor=None,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


# ── Progress against real facts ──────────────────────────────────────────────


def test_progress_reflects_recorded_facts(client, db, world, make_fact, sign_in):
    make_fact(world["metric"], world["teammate"], 40, WHEN)
    sign_in(world["admin"])
    body = client.post("/api/goals", json=goal_body(world)).json()
    assert Decimal(body["current_value"]) == Decimal(40)
    assert body["percent"] == 40.0
    assert body["attained"] is False


def test_progress_updates_when_a_fact_is_added(client, db, world, make_fact, sign_in):
    """The reason progress is computed and not stored: a connector backfilling
    yesterday's data must move the number with no invalidation step."""
    sign_in(world["admin"])
    goal_id = client.post("/api/goals", json=goal_body(world)).json()["id"]

    make_fact(world["metric"], world["teammate"], 100, WHEN)
    listed = client.get("/api/goals").json()
    goal = next(g for g in listed if g["id"] == goal_id)
    assert goal["attained"] is True
    assert goal["percent"] == 100.0


def test_facts_outside_the_period_do_not_count(client, db, world, make_fact, sign_in):
    make_fact(world["metric"], world["teammate"], 999, WHEN.replace(month=7))
    sign_in(world["admin"])
    body = client.post("/api/goals", json=goal_body(world)).json()
    assert Decimal(body["current_value"]) == 0


def test_a_team_goal_sums_the_team(client, db, world, make_user, make_fact, sign_in):
    other = make_user("agent", world["enterprise"], name="Other")
    make_fact(world["metric"], world["teammate"], 30, WHEN)
    make_fact(world["metric"], other, 25, WHEN)
    make_fact(world["metric"], world["stranger"], 999, WHEN)  # different team

    sign_in(world["admin"])
    body = client.post(
        "/api/goals",
        json=goal_body(world, subject_type="team", subject_id=world["enterprise"].id),
    ).json()
    assert Decimal(body["current_value"]) == Decimal(55)


def test_a_team_goal_uses_the_snapshot_not_the_current_team(
    client, db, world, make_fact, sign_in
):
    """Same rule as the leaderboards: moving someone must not retroactively
    hand their past work to a different team's goal."""
    make_fact(world["metric"], world["teammate"], 40, WHEN, team=world["enterprise"])
    world["teammate"].team_id = world["smb"].id
    db.flush()

    sign_in(world["admin"])
    body = client.post(
        "/api/goals",
        json=goal_body(world, subject_type="team", subject_id=world["enterprise"].id),
    ).json()
    assert Decimal(body["current_value"]) == Decimal(40)


def test_a_lower_is_better_goal_is_attained_by_being_under(
    client, db, world, make_metric, make_fact, sign_in
):
    metric = make_metric("response_time", aggregation="avg", direction="lower_is_better")
    make_fact(metric, world["teammate"], 20, WHEN)
    sign_in(world["admin"])
    body = client.post(
        "/api/goals", json=goal_body(world, metric_id=metric.id, target_value="60")
    ).json()
    assert body["attained"] is True


# ── Permissions ──────────────────────────────────────────────────────────────


def test_a_manager_can_set_a_goal_for_their_own_team(client, db, world, sign_in):
    sign_in(world["manager"])
    assert client.post(
        "/api/goals",
        json=goal_body(world, subject_type="team", subject_id=world["enterprise"].id),
    ).status_code == 201


def test_a_manager_cannot_set_a_goal_for_another_team(client, db, world, sign_in):
    sign_in(world["manager"])
    response = client.post(
        "/api/goals",
        json=goal_body(world, subject_type="team", subject_id=world["smb"].id),
    )
    assert response.status_code == 403
    assert "your own team" in response.json()["detail"]


def test_a_manager_cannot_set_a_goal_for_someone_outside_their_scope(client, db, world, sign_in):
    sign_in(world["manager"])
    assert client.post(
        "/api/goals", json=goal_body(world, subject_id=world["stranger"].id)
    ).status_code == 404


def test_an_agent_cannot_set_goals(client, db, world, sign_in):
    sign_in(world["teammate"])
    assert client.post("/api/goals", json=goal_body(world)).status_code == 403


def test_an_agent_sees_their_own_goal_but_not_a_colleagues(client, db, world, sign_in):
    """A goal names a person, so the list is itself information about who
    exists and what is expected of them."""
    sign_in(world["admin"])
    client.post("/api/goals", json=goal_body(world))
    client.post("/api/goals", json=goal_body(world, subject_id=world["stranger"].id))

    sign_in(world["teammate"])
    names = {g["subject_name"] for g in client.get("/api/goals").json()}
    assert names == {"Teammate"}


def test_an_agent_sees_their_teams_goal(client, db, world, sign_in):
    """Being measured against a target you cannot see is the opposite of what
    this product is for."""
    sign_in(world["admin"])
    client.post(
        "/api/goals",
        json=goal_body(world, subject_type="team", subject_id=world["enterprise"].id),
    )
    sign_in(world["teammate"])
    assert [g["subject_name"] for g in client.get("/api/goals").json()] == ["Enterprise"]


def test_a_manager_does_not_see_another_teams_goals(client, db, world, sign_in):
    sign_in(world["admin"])
    client.post("/api/goals", json=goal_body(world, subject_id=world["stranger"].id))
    client.post("/api/goals", json=goal_body(world))

    sign_in(world["manager"])
    names = {g["subject_name"] for g in client.get("/api/goals").json()}
    assert "Stranger" not in names
    assert "Teammate" in names


def test_mine_filters_to_you_and_your_team(client, db, world, make_user, sign_in):
    other = make_user("agent", world["enterprise"], name="Other")
    sign_in(world["admin"])
    client.post("/api/goals", json=goal_body(world))
    client.post("/api/goals", json=goal_body(world, subject_id=other.id))
    client.post(
        "/api/goals",
        json=goal_body(world, subject_type="team", subject_id=world["enterprise"].id),
    )

    sign_in(world["teammate"])
    names = {g["subject_name"] for g in client.get("/api/goals?mine=true").json()}
    assert names == {"Teammate", "Enterprise"}


def test_another_organizations_goal_is_not_found(client, db, org, world, sign_in):
    from app.models import Organization

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = Goal(
        organization_id=other.id,
        metric_definition_id=world["metric"].id,
        subject_type="user",
        subject_user_id=world["teammate"].id,
        target_value=Decimal(10),
        period_type="month",
        period_anchor=date(2026, 8, 1),
    )
    db.add(theirs)
    db.flush()

    sign_in(world["admin"])
    assert client.patch(f"/api/goals/{theirs.id}", json={"target_value": "5"}).status_code == 404
    assert client.delete(f"/api/goals/{theirs.id}").status_code == 404


# ── Editing, archiving, deleting ─────────────────────────────────────────────


def test_the_target_can_be_moved(client, db, world, sign_in):
    sign_in(world["admin"])
    goal_id = client.post("/api/goals", json=goal_body(world)).json()["id"]
    body = client.patch(f"/api/goals/{goal_id}", json={"target_value": "250"}).json()
    assert Decimal(body["target_value"]) == Decimal(250)


def test_the_metric_and_subject_cannot_be_changed(client, db, world, sign_in):
    """Changing either makes it a different goal — and one whose history of
    "you were at 60%" now refers to something else."""
    sign_in(world["admin"])
    goal_id = client.post("/api/goals", json=goal_body(world)).json()["id"]
    for field in ("metric_id", "subject_id", "subject_type"):
        assert client.patch(f"/api/goals/{goal_id}", json={field: 1}).status_code == 422


def test_changing_the_period_moves_the_progress_with_it(client, db, world, make_fact, sign_in):
    make_fact(world["metric"], world["teammate"], 40, WHEN.replace(month=7))
    sign_in(world["admin"])
    goal_id = client.post("/api/goals", json=goal_body(world)).json()["id"]

    body = client.patch(
        f"/api/goals/{goal_id}", json={"period_anchor": "2026-07-15"}
    ).json()
    assert body["period_label"] == "July 2026"
    assert Decimal(body["current_value"]) == Decimal(40)


def test_switching_to_a_custom_period_clears_the_anchor(client, db, world, sign_in):
    """The CHECK constraint requires exactly one shape. Leaving a stale anchor
    behind would make the update fail with a message nobody can act on."""
    sign_in(world["admin"])
    goal_id = client.post("/api/goals", json=goal_body(world)).json()["id"]
    response = client.patch(
        f"/api/goals/{goal_id}",
        json={"period_type": "custom", "period_start": "2026-08-01", "period_end": "2026-08-10"},
    )
    assert response.status_code == 200
    assert db.get(Goal, goal_id).period_anchor is None


def test_archive_hides_it_and_restore_brings_it_back(client, db, world, sign_in):
    sign_in(world["admin"])
    goal_id = client.post("/api/goals", json=goal_body(world)).json()["id"]

    client.post(f"/api/goals/{goal_id}/archive")
    assert goal_id not in [g["id"] for g in client.get("/api/goals").json()]
    assert goal_id in [g["id"] for g in client.get("/api/goals?include_archived=true").json()]

    client.post(f"/api/goals/{goal_id}/restore")
    assert goal_id in [g["id"] for g in client.get("/api/goals").json()]


def test_delete_removes_it(client, db, world, sign_in):
    sign_in(world["admin"])
    goal_id = client.post("/api/goals", json=goal_body(world)).json()["id"]
    assert client.delete(f"/api/goals/{goal_id}").status_code == 204
    assert db.get(Goal, goal_id) is None


# ── Audit ────────────────────────────────────────────────────────────────────


def test_creating_and_deleting_are_audited(client, db, world, sign_in):
    sign_in(world["admin"])
    goal_id = client.post("/api/goals", json=goal_body(world)).json()["id"]
    assert db.scalar(select(AuditLog).order_by(AuditLog.id.desc())).action == "goal.created"

    client.delete(f"/api/goals/{goal_id}")
    latest = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert latest.action == "goal.deleted"
    assert latest.details["subject"] == "Teammate"


def test_moving_a_target_is_audited_but_a_rename_is_not(client, db, world, sign_in):
    """Moving the target changes what "attained" meant for everyone looking at
    it. Renaming does not."""
    sign_in(world["admin"])
    goal_id = client.post("/api/goals", json=goal_body(world)).json()["id"]

    before = audit_count(db)
    client.patch(f"/api/goals/{goal_id}", json={"name": "Q3 push"})
    assert audit_count(db) == before

    client.patch(f"/api/goals/{goal_id}", json={"target_value": "500"})
    latest = db.scalar(select(AuditLog).order_by(AuditLog.id.desc()))
    assert latest.action == "goal.retargeted"
    assert Decimal(latest.details["target_value"]["to"]) == Decimal(500)


def test_a_refused_goal_writes_nothing(client, db, world, sign_in):
    sign_in(world["manager"])
    before = audit_count(db)
    assert client.post(
        "/api/goals", json=goal_body(world, subject_id=world["stranger"].id)
    ).status_code == 404
    assert audit_count(db) == before
    assert db.scalar(select(func.count()).select_from(Goal)) == 0


def test_a_lower_is_better_goal_with_no_data_does_not_report_hit(
    client, db, world, make_metric, sign_in
):
    """The end-to-end version of the same rule, found by creating this goal
    against real data and seeing it come back HIT with nothing recorded."""
    metric = make_metric("resp_time", aggregation="avg", direction="lower_is_better")
    sign_in(world["admin"])
    body = client.post(
        "/api/goals", json=goal_body(world, metric_id=metric.id, target_value="60")
    ).json()
    assert body["attained"] is False
    assert body["status"] != "hit"


def test_a_lower_is_better_goal_reports_hit_once_data_arrives(
    client, db, world, make_metric, make_fact, sign_in
):
    metric = make_metric("resp_time2", aggregation="avg", direction="lower_is_better")
    make_fact(metric, world["teammate"], 20, WHEN)
    sign_in(world["admin"])
    body = client.post(
        "/api/goals", json=goal_body(world, metric_id=metric.id, target_value="60")
    ).json()
    assert body["attained"] is True


def test_changing_the_period_kind_lands_on_the_current_one(client, db, world, sign_in):
    """Found while verifying the edit form: a goal went August → Q3 → July.

    The old anchor was being reinterpreted under the new type — August's
    1 August becomes Q3's 1 July — so switching back to month landed a month
    earlier. Changing the *kind* of period without naming one now means the
    current one of that kind.
    """
    from datetime import date

    sign_in(world["admin"])
    goal_id = client.post("/api/goals", json=goal_body(world)).json()["id"]
    today = org_today()

    quarter = client.patch(f"/api/goals/{goal_id}", json={"period_type": "quarter"}).json()
    month = client.patch(f"/api/goals/{goal_id}", json={"period_type": "month"}).json()

    assert quarter["period_type"] == "quarter"
    # Back to the month we are actually in, not whatever the quarter's start
    # happened to fall in.
    assert month["period_label"] == today.strftime("%B %Y")


def test_an_explicit_anchor_still_wins_when_changing_the_period_kind(client, db, world, sign_in):
    """The re-anchoring is a fallback for "you did not say", not an override."""
    sign_in(world["admin"])
    goal_id = client.post("/api/goals", json=goal_body(world)).json()["id"]
    body = client.patch(
        f"/api/goals/{goal_id}",
        json={"period_type": "month", "period_anchor": "2026-03-10"},
    ).json()
    assert body["period_label"] == "March 2026"


def test_editing_only_the_target_leaves_the_period_alone(client, db, world, sign_in):
    """The other direction — the fix must not re-anchor edits that never
    touched the period."""
    sign_in(world["admin"])
    created = client.post(
        "/api/goals", json=goal_body(world, period_anchor="2026-03-10")
    ).json()
    updated = client.patch(
        f"/api/goals/{created['id']}", json={"target_value": "999"}
    ).json()
    assert updated["period_label"] == created["period_label"] == "March 2026"


# ── Sparklines ───────────────────────────────────────────────────────────────


def make_goal(client, world, sign_in, **overrides):
    sign_in(world["admin"])
    response = client.post("/api/goals", json=goal_body(world, **overrides))
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def test_a_goal_has_no_trend_unless_asked(client, db, world, sign_in):
    """One extra query per goal, and most callers are listing rather than
    plotting — so the cost is opt-in and visible at the call site."""
    make_goal(client, world, sign_in)
    assert client.get("/api/goals").json()[0]["trend"] is None


def test_a_goal_trend_ends_at_the_value_beside_it(
    client, db, world, sign_in, make_fact
):
    """The last point of the line IS the number on the progress bar.

    If those two ever disagree, the chart is the one people will believe, and
    it will be the wrong one.
    """
    make_fact(world["metric"], world["teammate"], 30, WHEN)
    make_fact(world["metric"], world["teammate"], 45, WHEN)
    make_goal(client, world, sign_in)

    body = client.get("/api/goals?trend=true").json()[0]

    assert body["trend"]["cumulative"] is True
    assert body["trend"]["unit"] == "day"
    assert Decimal(body["trend"]["points"][-1]["value"]) == Decimal(
        body["current_value"]
    )


def test_a_goal_trend_covers_every_day_of_the_period(
    client, db, world, sign_in, make_fact
):
    """Including the days nothing happened. A line that skipped them would
    show a steadier month than the real one."""
    make_fact(world["metric"], world["teammate"], 30, WHEN)
    make_goal(client, world, sign_in)

    points = client.get("/api/goals?trend=true").json()[0]["trend"]["points"]

    assert len(points) == 31  # August
    assert Decimal(points[0]["value"]) == Decimal(0)
    assert Decimal(points[-1]["value"]) == Decimal(30)


def test_a_goal_trend_is_scoped_like_the_goal(client, db, world, sign_in, make_fact):
    """A chart is as much of a read as a total is. A stranger's contribution
    must not appear in a line drawn for somebody who cannot see them."""
    make_fact(world["metric"], world["teammate"], 30, WHEN)
    make_goal(client, world, sign_in, subject_type="team",
              subject_id=world["enterprise"].id)

    sign_in(world["teammate"])
    body = client.get("/api/goals?mine=true&trend=true").json()[0]

    assert Decimal(body["trend"]["points"][-1]["value"]) == Decimal(
        body["current_value"]
    )


# ── The detail page ──────────────────────────────────────────────────────────


def detail(client, goal_id: int):
    response = client.get(f"/api/goals/{goal_id}")
    assert response.status_code == 200, response.json()
    return response.json()


def test_a_personal_goal_has_no_contributor_list(
    client, db, world, sign_in, make_fact
):
    """The answer would be the one person already named on it.

    Facts for other people exist here on purpose: without them an empty list
    proves nothing, because there would be nobody to wrongly include.
    """
    make_fact(world["metric"], world["teammate"], 30, WHEN)
    make_fact(world["metric"], world["manager"], 12, WHEN)
    make_fact(world["metric"], world["stranger"], 99, WHEN)

    goal_id = make_goal(client, world, sign_in)
    assert detail(client, goal_id)["contributors"] == []


def test_a_team_goal_names_who_made_up_the_number(
    client, db, world, sign_in, make_fact
):
    """The question when a team goal is behind is not "by how much" — the bar
    says that — but "who"."""
    make_fact(world["metric"], world["teammate"], 30, WHEN)
    make_fact(world["metric"], world["manager"], 12, WHEN)
    # On another team, and outscoring both. Present so that a breakdown which
    # forgot to filter by team would rank them first and fail loudly.
    make_fact(world["metric"], world["stranger"], 99, WHEN)

    goal_id = make_goal(
        client, world, sign_in, subject_type="team", subject_id=world["enterprise"].id
    )

    body = detail(client, goal_id)
    names = [(c["full_name"], Decimal(c["value"]), c["rank"]) for c in body["contributors"]]

    assert names == [("Teammate", Decimal(30), 1), ("Manager", Decimal(12), 2)]


def test_the_contributors_add_up_to_the_goals_own_number(
    client, db, world, sign_in, make_fact
):
    """A breakdown that did not sum to the total above it would be the most
    obvious possible bug and the hardest to unsee."""
    make_fact(world["metric"], world["teammate"], 30, WHEN)
    make_fact(world["metric"], world["manager"], 12, WHEN)
    goal_id = make_goal(
        client, world, sign_in, subject_type="team", subject_id=world["enterprise"].id
    )

    body = detail(client, goal_id)
    parts = sum(Decimal(c["value"]) for c in body["contributors"])

    assert parts == Decimal(body["goal"]["current_value"])


def test_an_agent_sees_only_their_own_contribution(
    client, db, world, sign_in, make_fact
):
    """Scoped like everything else. The total stays the team's — that is what
    the goal is — but the breakdown is only what this viewer may read."""
    make_fact(world["metric"], world["teammate"], 30, WHEN)
    make_fact(world["metric"], world["manager"], 12, WHEN)
    goal_id = make_goal(
        client, world, sign_in, subject_type="team", subject_id=world["enterprise"].id
    )

    sign_in(world["teammate"])
    body = detail(client, goal_id)

    assert [c["full_name"] for c in body["contributors"]] == ["Teammate"]


def test_a_stranger_cannot_open_the_goal_at_all(client, db, world, sign_in):
    """404 rather than 403, like every other scope refusal here — a 403 would
    confirm the goal exists."""
    goal_id = make_goal(client, world, sign_in)
    sign_in(world["stranger"])
    assert client.get(f"/api/goals/{goal_id}").status_code == 404


def test_history_covers_the_periods_before_this_one(
    client, db, world, sign_in, make_fact
):
    """The question that decides whether a target is any good."""
    make_fact(world["metric"], world["teammate"], 40, datetime(2026, 7, 10, 15, tzinfo=UTC))
    make_fact(world["metric"], world["teammate"], 25, datetime(2026, 6, 10, 15, tzinfo=UTC))
    goal_id = make_goal(client, world, sign_in)

    history = detail(client, goal_id)["history"]

    # Six months back, oldest first, so it reads left to right.
    assert [h["label"] for h in history] == [
        "February 2026", "March 2026", "April 2026",
        "May 2026", "June 2026", "July 2026",
    ]
    assert Decimal(history[-1]["value"]) == Decimal(40)
    assert Decimal(history[-2]["value"]) == Decimal(25)


def test_history_never_includes_the_current_period(
    client, db, world, sign_in, make_fact
):
    """It would sit beside a partial month masquerading as a finished one."""
    make_fact(world["metric"], world["teammate"], 99, WHEN)
    goal_id = make_goal(client, world, sign_in)

    history = detail(client, goal_id)["history"]

    assert "August 2026" not in [h["label"] for h in history]
    assert all(Decimal(h["value"]) == 0 for h in history)


def test_history_is_judged_against_the_current_target(
    client, db, world, sign_in, make_fact
):
    """Not against whatever was set at the time, which for most of these
    periods was nothing at all. One line across the whole row is the only
    reading that stays consistent."""
    make_fact(world["metric"], world["teammate"], 150, datetime(2026, 7, 10, 15, tzinfo=UTC))
    goal_id = make_goal(client, world, sign_in, target_value="100")

    july = next(h for h in detail(client, goal_id)["history"] if h["label"] == "July 2026")
    assert july["met_target"] is True


def test_a_team_goals_history_is_that_team_only(client, db, world, sign_in, make_fact):
    """Another team's past months must not inflate this one's record — the
    whole point of the row is to say whether *this* team can hit the target."""
    july = datetime(2026, 7, 10, 15, tzinfo=UTC)
    make_fact(world["metric"], world["teammate"], 40, july)
    make_fact(world["metric"], world["stranger"], 500, july)

    goal_id = make_goal(
        client, world, sign_in, subject_type="team", subject_id=world["enterprise"].id
    )

    history = detail(client, goal_id)["history"]
    assert Decimal(next(h for h in history if h["label"] == "July 2026")["value"]) == 40


def test_an_empty_past_period_is_not_a_success(
    client, db, world, sign_in, make_metric
):
    """The `lower_is_better` trap, in the history row.

    Nothing recorded reads as zero, and zero is under every cap — so a month
    where the team answered no calls at all would otherwise show as having
    comfortably met "keep average response time under 60 seconds". Absence is
    not achievement.
    """
    metric = make_metric("response_time", aggregation="avg", direction="lower_is_better")
    goal_id = make_goal(client, world, sign_in, metric_id=metric.id, target_value="60")

    history = detail(client, goal_id)["history"]

    assert history  # there are periods to judge
    assert all(h["met_target"] is False for h in history)


def test_a_custom_period_has_no_history(client, db, world, sign_in):
    """There is no rule for what comes before an arbitrary range."""
    goal_id = make_goal(
        client, world, sign_in,
        period_type="custom", period_anchor=None,
        period_start="2026-08-01", period_end="2026-08-20",
    )
    assert detail(client, goal_id)["history"] == []


def test_the_detail_always_carries_a_trend(client, db, world, sign_in, make_fact):
    """Opt-in on the list, always here — a detail page is exactly where the
    extra query is worth paying for."""
    make_fact(world["metric"], world["teammate"], 30, WHEN)
    goal_id = make_goal(client, world, sign_in)

    body = detail(client, goal_id)
    assert body["goal"]["trend"] is not None
    assert Decimal(body["goal"]["trend"]["points"][-1]["value"]) == Decimal(
        body["goal"]["current_value"]
    )


def test_an_archived_goal_can_still_be_opened(client, db, world, sign_in):
    """"You hit 4 of 5 goals last quarter" needs the ones no longer current."""
    goal_id = make_goal(client, world, sign_in)
    client.post(f"/api/goals/{goal_id}/archive")
    assert detail(client, goal_id)["goal"]["archived"] is True


# ── Real numbers in the form (8.7) ───────────────────────────────────────────


def test_the_form_can_draw_its_goal_with_real_progress_and_save_nothing(
    client, db, world, sign_in, make_fact
):
    from tests.conftest import within_this_month

    make_fact(world["metric"], world["teammate"], 40, within_this_month())
    sign_in(world["admin"])
    before = db.scalar(select(func.count()).select_from(Goal))
    body = goal_body(world)
    body.pop("period_anchor")

    slide = client.post("/api/goals/draft-slide", json=body).json()

    assert slide["kind"] == "goal"
    assert float(slide["current_value"]) == 40
    assert db.scalar(select(func.count()).select_from(Goal)) == before
