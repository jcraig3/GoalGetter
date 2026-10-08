"""Historical preview behind guided goal creation."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.routers.goal_preview import LOOKBACK, _suggest
from tests.conftest import org_now


@pytest.fixture
def world(make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "teammate": make_user("agent", enterprise, name="Teammate"),
        "stranger": make_user("agent", smb, name="Stranger"),
        "metric": make_metric("calls_made"),
    }


def body(world, **overrides):
    return {
        "metric_id": world["metric"].id,
        "subject_type": "user",
        "subject_id": world["teammate"].id,
        "period_type": "month",
        **overrides,
    }


def months_ago(count: int) -> datetime:
    """Roughly `count` months back, mid-month so it cannot land on a boundary."""
    return org_now().replace(day=15, hour=12) - timedelta(days=30 * count)


# ── The suggestion ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("average", "expected"),
    [
        (Decimal(100), Decimal(110)),  # 110 -> nearest 10
        (Decimal(720), Decimal(800)),  # 792 -> nearest 50
        (Decimal(5_000), Decimal(5_500)),  # 5500 -> nearest 500
        # The step comes from the stretched value, not the average: 215,600
        # is over the 200k boundary, so it rounds to the nearest 10,000.
        (Decimal(196_000), Decimal(220_000)),
        (Decimal(2_000_000), Decimal(2_200_000)),  # -> nearest 10000
    ],
)
def test_a_suggestion_is_a_number_a_person_would_say_out_loud(average, expected):
    """"231.4" reads as a calculation and "240" reads as a decision. A target is
    a thing people say to each other."""
    assert _suggest(average, "higher_is_better", 0) == expected


def test_a_currency_suggestion_is_rounded_too():
    """An earlier version kept full precision for money, on the reasoning that
    money is exact — and produced a suggested revenue target of $216,026.54.
    The unit was never what mattered; the magnitude is."""
    result = _suggest(Decimal("196387.765"), "higher_is_better", 2)
    assert result == Decimal("220000.00")


def test_a_suggestion_stretches_past_the_average():
    """A target set to the average is a target for what already happens."""
    assert _suggest(Decimal(100), "higher_is_better", 0) > Decimal(100)


def test_a_lower_is_better_suggestion_goes_the_other_way():
    assert _suggest(Decimal(100), "lower_is_better", 0) < Decimal(100)


def test_a_suggestion_is_never_zero():
    """The target > 0 constraint would reject it the moment it was accepted."""
    assert _suggest(Decimal("0.01"), "higher_is_better", 0) > 0
    assert _suggest(Decimal("0.01"), "lower_is_better", 0) > 0


# ── History ──────────────────────────────────────────────────────────────────


def test_the_preview_returns_the_lookback_window(client, db, world, sign_in):
    sign_in(world["admin"])
    result = client.post("/api/goals/preview", json=body(world)).json()
    assert len(result["history"]) == LOOKBACK


def test_history_is_oldest_first(client, db, world, sign_in):
    """So a chart reads left to right without the client reversing it."""
    sign_in(world["admin"])
    starts = [h["start"] for h in client.post("/api/goals/preview", json=body(world)).json()["history"]]
    assert starts == sorted(starts)


def test_the_current_period_is_excluded(client, db, world, make_fact, sign_in):
    """It is partway through, so counting it would drag the average down by
    however much of it is left and suggest a target below what the person
    actually achieves."""
    make_fact(world["metric"], world["teammate"], 5, datetime.now(UTC))
    sign_in(world["admin"])
    result = client.post("/api/goals/preview", json=body(world)).json()

    assert all(Decimal(h["value"]) == 0 for h in result["history"])
    assert result["average"] is None


def test_recorded_history_produces_an_average_and_a_best(client, db, world, make_fact, sign_in):
    for months, value in ((1, 100), (2, 200), (3, 300)):
        make_fact(world["metric"], world["teammate"], value, months_ago(months))

    sign_in(world["admin"])
    result = client.post("/api/goals/preview", json=body(world)).json()
    assert Decimal(result["average"]) == Decimal(200)
    assert Decimal(result["best"]) == Decimal(300)
    assert result["suggested_target"] is not None


def test_empty_periods_are_excluded_from_the_average(client, db, world, make_fact, sign_in):
    """Someone who joined three months ago has empty periods before that.
    Averaging those in as zeros halves their target for a reason that has
    nothing to do with their performance."""
    make_fact(world["metric"], world["teammate"], 300, months_ago(1))
    sign_in(world["admin"])
    result = client.post("/api/goals/preview", json=body(world)).json()

    assert Decimal(result["average"]) == Decimal(300)  # not 300/6


def test_no_history_at_all_offers_no_suggestion(client, db, world, sign_in):
    """Better than suggesting a number invented from nothing."""
    sign_in(world["admin"])
    result = client.post("/api/goals/preview", json=body(world)).json()
    assert result["average"] is None
    assert result["best"] is None
    assert result["suggested_target"] is None


def test_the_best_period_is_the_lowest_for_a_lower_is_better_metric(
    client, db, world, make_metric, make_fact, sign_in
):
    metric = make_metric("resp", aggregation="avg", direction="lower_is_better")
    for months, value in ((1, 30), (2, 90)):
        make_fact(metric, world["teammate"], value, months_ago(months))

    sign_in(world["admin"])
    result = client.post("/api/goals/preview", json=body(world, metric_id=metric.id)).json()
    assert Decimal(result["best"]) == Decimal(30)


def test_a_team_preview_sums_its_members(client, db, world, make_user, make_fact, sign_in):
    other = make_user("agent", world["enterprise"])
    make_fact(world["metric"], world["teammate"], 100, months_ago(1))
    make_fact(world["metric"], other, 50, months_ago(1))

    sign_in(world["admin"])
    result = client.post(
        "/api/goals/preview",
        json=body(world, subject_type="team", subject_id=world["enterprise"].id),
    ).json()
    assert Decimal(result["average"]) == Decimal(150)


@pytest.mark.parametrize("period_type", ["day", "week", "month", "quarter", "year"])
def test_every_repeating_period_can_be_previewed(client, db, world, sign_in, period_type):
    """Guards the preview against the goal form offering a period it cannot
    build history for."""
    sign_in(world["admin"])
    response = client.post("/api/goals/preview", json=body(world, period_type=period_type))
    assert response.status_code == 200
    assert len(response.json()["history"]) == LOOKBACK


def test_a_custom_range_cannot_be_previewed(client, db, world, sign_in):
    """There is no "previous custom range" to walk back through."""
    sign_in(world["admin"])
    assert client.post(
        "/api/goals/preview", json=body(world, period_type="custom")
    ).status_code == 422


# ── Permissions ──────────────────────────────────────────────────────────────


def test_an_agent_cannot_preview(client, db, world, sign_in):
    """The preview is someone's performance history — the same data the goal
    itself is scoped by."""
    sign_in(world["teammate"])
    assert client.post("/api/goals/preview", json=body(world)).status_code == 403


def test_a_manager_cannot_preview_someone_outside_their_scope(client, db, world, sign_in):
    sign_in(world["manager"])
    assert client.post(
        "/api/goals/preview", json=body(world, subject_id=world["stranger"].id)
    ).status_code == 404


def test_a_manager_cannot_preview_another_team(client, db, world, sign_in):
    sign_in(world["manager"])
    assert client.post(
        "/api/goals/preview",
        json=body(world, subject_type="team", subject_id=world["smb"].id),
    ).status_code == 404


def test_a_manager_can_preview_their_own_team(client, db, world, sign_in):
    sign_in(world["manager"])
    assert client.post(
        "/api/goals/preview",
        json=body(world, subject_type="team", subject_id=world["enterprise"].id),
    ).status_code == 200


def test_an_unknown_metric_or_subject_is_a_404(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post("/api/goals/preview", json=body(world, metric_id=999999)).status_code == 404
    assert client.post("/api/goals/preview", json=body(world, subject_id=999999)).status_code == 404


def test_unknown_fields_are_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    assert client.post("/api/goals/preview", json=body(world, lookback=99)).status_code == 422


def test_preview_does_not_collide_with_the_goal_id_route(client, db, world, sign_in):
    """`/goals/preview` and `/goals/{goal_id}` share a prefix. If the routers
    were registered the other way round, "preview" would be parsed as an id."""
    sign_in(world["admin"])
    assert client.post("/api/goals/preview", json=body(world)).status_code == 200
