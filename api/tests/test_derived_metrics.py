"""Derived metrics: close rate = deals won ÷ deals created.

What has to be true: a derived metric is worked out from its parts inside the
same aggregation everything uses, so it ranks, scopes and totals correctly; a
team's rate is its wins over its deals, never an average of people's rates;
nobody with no deals has a 0% close rate — they have none; a percent reads as a
percent; and nothing can be recorded against a derived metric directly.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app import aggregate, derived
from app.models import MetricDefinition
from app.periods import Period
from app.scope import EVERYONE

AUGUST = Period(
    type="month",
    start=datetime(2026, 8, 1, tzinfo=UTC), end=datetime(2026, 9, 1, tzinfo=UTC), label="August 2026"
)
WHEN = datetime(2026, 8, 12, 15, tzinfo=UTC)


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    closers = make_team("Closers")
    won = make_metric("deals_won", aggregation="count")
    created = make_metric("deals_created", aggregation="count")
    rate = MetricDefinition(
        organization_id=org.id, key="close_rate", name="Close rate", unit="percent",
        aggregation="ratio", decimal_places=1,
        numerator_metric_id=won.id, denominator_metric_id=created.id,
    )
    db.add(rate)
    db.flush()
    return {
        "closers": closers,
        "admin": make_user("admin", name="Bruce Wayne"),
        "peter": make_user("agent", closers, name="Peter Parker"),
        "clark": make_user("agent", closers, name="Clark Kent"),
        "diana": make_user("agent", name="Diana Prince"),
        "won": won, "created": created, "rate": rate,
    }


def deals(make_fact, world, person, *, created, won):
    for _ in range(created):
        make_fact(world["created"], person, 1, WHEN)
    for _ in range(won):
        make_fact(world["won"], person, 1, WHEN)


def board(db, org, world, **extra):
    return {
        row.subject_name: row.value
        for row in aggregate.run(db, org.id, world["admin"], world["rate"], AUGUST, visible=EVERYONE, **extra)
    }


def test_each_person_has_their_rate_as_a_percent(db, org, world, make_fact):
    deals(make_fact, world, world["peter"], created=20, won=7)
    deals(make_fact, world, world["clark"], created=10, won=5)

    assert board(db, org, world) == {"Clark Kent": Decimal("50.0000"), "Peter Parker": Decimal("35.0000")}


def test_it_ranks_like_any_other_metric(db, org, world, make_fact):
    deals(make_fact, world, world["peter"], created=20, won=7)
    deals(make_fact, world, world["clark"], created=10, won=5)

    rows = aggregate.run(db, org.id, world["admin"], world["rate"], AUGUST, visible=EVERYONE)

    assert [(r.subject_name, r.rank) for r in rows] == [("Clark Kent", 1), ("Peter Parker", 2)]


def test_no_deals_is_no_rate_not_zero(db, org, world, make_fact):
    """Diana created nothing: she is off the board, not bottom of it at 0%."""
    deals(make_fact, world, world["peter"], created=4, won=1)

    assert "Diana Prince" not in board(db, org, world)


def test_deals_but_no_wins_is_zero(db, org, world, make_fact):
    deals(make_fact, world, world["diana"], created=5, won=0)

    assert board(db, org, world)["Diana Prince"] == Decimal(0)


def test_a_team_rate_is_its_wins_over_its_deals(db, org, world, make_fact):
    """Not the average of 35% and 50% (42.5%): 12 won of 30 is 40%."""
    deals(make_fact, world, world["peter"], created=20, won=7)
    deals(make_fact, world, world["clark"], created=10, won=5)

    assert board(db, org, world, group_by="team") == {"Closers": Decimal("40.0000")}


def test_the_overall_figure_is_the_same_kind_of_ratio(db, org, world, make_fact):
    deals(make_fact, world, world["peter"], created=20, won=7)
    deals(make_fact, world, world["clark"], created=10, won=5)

    total = aggregate.total(db, org.id, world["admin"], world["rate"], AUGUST, visible=EVERYONE)

    assert total == Decimal("40.0000")


def test_scope_applies_to_both_parts(db, org, world, make_fact):
    """An agent sees their own rate, worked out from their own facts only."""
    deals(make_fact, world, world["peter"], created=20, won=7)
    deals(make_fact, world, world["clark"], created=10, won=5)

    rows = aggregate.run(db, org.id, world["peter"], world["rate"], AUGUST)

    assert [(r.subject_name, r.value) for r in rows] == [("Peter Parker", Decimal("35.0000"))]


def test_a_non_percent_ratio_is_not_scaled(db, org, world, make_metric, make_fact):
    revenue = make_metric("revenue", unit="currency")
    calls = make_metric("calls", aggregation="count")
    per_call = MetricDefinition(
        organization_id=org.id, key="revenue_per_call", name="Revenue per call", unit="currency",
        aggregation="ratio", numerator_metric_id=revenue.id, denominator_metric_id=calls.id,
    )
    db.add(per_call)
    db.flush()
    make_fact(revenue, world["peter"], 1000, WHEN)
    for _ in range(4):
        make_fact(calls, world["peter"], 1, WHEN)

    rows = aggregate.run(db, org.id, world["admin"], per_call, AUGUST, visible=EVERYONE)

    assert rows[0].value == Decimal("250.0000")


def test_the_trend_divides_per_bucket(db, org, world, make_fact):
    deals(make_fact, world, world["peter"], created=4, won=1)

    points = aggregate.series(db, org, world["admin"], world["rate"], AUGUST, visible=EVERYONE)

    values = [p.value for p in points if p.value is not None]
    assert values == [Decimal("25.0000")]
    assert any(p.value is None for p in points), "a day with no deals is a gap, not 0%"


def test_facts_behind_it_are_its_parts():
    rate = MetricDefinition(id=9, aggregation="ratio", numerator_metric_id=1, denominator_metric_id=2)
    assert derived.fact_metric_ids(None, rate) == [1, 2]


# ── The API ─────────────────────────────────────────────────────────────────


def test_a_ratio_is_made_from_two_metrics(client, sign_in, world):
    sign_in(world["admin"])

    made = client.post(
        "/api/metrics",
        json={
            "key": "win_rate", "name": "Win rate", "unit": "percent", "aggregation": "ratio",
            "numerator_metric_id": world["won"].id, "denominator_metric_id": world["created"].id,
        },
    )

    assert made.status_code == 201, made.text
    assert made.json()["numerator_metric_id"] == world["won"].id


@pytest.mark.parametrize(
    "parts, words",
    [
        ({}, "needs two metrics"),
        ({"same": True}, "divided by itself"),
        ({"of_ratio": True}, "itself worked out"),
    ],
)
def test_a_bad_ratio_is_refused_in_words(client, sign_in, world, parts, words):
    sign_in(world["admin"])
    body = {"key": "bad_rate", "name": "Bad", "aggregation": "ratio"}
    if parts.get("same"):
        body |= {"numerator_metric_id": world["won"].id, "denominator_metric_id": world["won"].id}
    if parts.get("of_ratio"):
        body |= {"numerator_metric_id": world["rate"].id, "denominator_metric_id": world["won"].id}

    reply = client.post("/api/metrics", json=body)

    assert reply.status_code == 400
    assert words in reply.json()["detail"]


def test_nothing_is_recorded_against_a_ratio(client, sign_in, world):
    sign_in(world["admin"])

    reply = client.post(
        "/api/metric-facts",
        json={"metric_id": world["rate"].id, "subject_user_id": world["peter"].id, "value": 1,
              "occurred_at": WHEN.isoformat()},
    )

    assert reply.status_code == 409
    assert "worked out from two other metrics" in reply.json()["detail"]


def test_a_part_cannot_be_deleted_out_from_under_it(client, sign_in, world):
    sign_in(world["admin"])

    reply = client.delete(f"/api/metrics/{world['won'].id}")

    assert reply.status_code == 409
    assert "Close rate" in reply.json()["detail"]


def test_a_metric_with_data_cannot_become_a_ratio(client, sign_in, world, make_fact):
    sign_in(world["admin"])
    make_fact(world["won"], world["peter"], 1, WHEN)

    reply = client.patch(
        f"/api/metrics/{world['won'].id}",
        json={"aggregation": "ratio", "numerator_metric_id": world["created"].id,
              "denominator_metric_id": world["rate"].id},
    )

    assert reply.status_code == 409


def test_a_goal_on_a_ratio_measures_the_ratio(client, sign_in, db, org, world, make_fact):
    """End to end through the goal path: 7 of 20 against a 30% target is hit."""
    sign_in(world["admin"])
    deals(make_fact, world, world["peter"], created=20, won=7)
    from datetime import date

    made = client.post(
        "/api/goals",
        json={
            "metric_id": world["rate"].id, "subject_type": "user",
            "subject_id": world["peter"].id, "target_value": 30, "period_type": "month",
            "period_anchor": date(2026, 8, 1).isoformat(),
        },
    ).json()

    assert Decimal(made["current_value"]) == Decimal(35)
    assert made["attained"] is True
