"""What a count is a count of: "48,210 deals" (§8).

What has to be true: a labelled count says its noun, singular for one; money,
percentages and unlabelled counts are untouched; a metric stores the label
trimmed and empty as nothing; and an announcement's {value} carries it.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app import notifications, units
from app.models import AchievementRule, Notification


@pytest.mark.parametrize(
    "plural, one",
    [("deals", "deal"), ("replies", "reply"), ("glasses", "glass"), ("NPS", "NPS"),
     ("people", "people"), ("Calls", "Call")],
)
def test_one_of_them_reads_in_the_singular(plural, one):
    assert units.singular(plural) == one


def test_a_labelled_count_says_what_it_counts():
    assert units.with_noun("48,210", Decimal(48210), "count", "deals") == "48,210 deals"
    assert units.with_noun("1", Decimal(1), "count", "deals") == "1 deal"
    assert units.with_noun("0", Decimal(0), "count", "deals") == "0 deals"


def test_everything_else_is_left_as_it_was():
    assert units.with_noun("8,450.00", Decimal(8450), "currency", "deals") == "8,450.00"
    assert units.with_noun("48,210", Decimal(48210), "count", None) == "48,210"


def test_the_label_is_stored_trimmed_and_empty_as_nothing(client, make_user, sign_in):
    sign_in(make_user("admin"))
    created = client.post(
        "/api/metrics",
        json={"key": "deals_won", "name": "Deals won", "unit": "count", "unit_label": "  deals "},
    ).json()
    assert created["unit_label"] == "deals"

    cleared = client.patch(f"/api/metrics/{created['id']}", json={"unit_label": "  "}).json()
    assert cleared["unit_label"] is None

    assert client.patch(
        f"/api/metrics/{created['id']}", json={"unit_label": "x" * 33}
    ).status_code == 422


def test_an_announcement_says_the_noun(db, org, make_user, make_metric, make_fact):
    alice = make_user("agent", name="Alice")
    calls = make_metric("calls_made")
    calls.unit_label = "calls"
    db.add(
        AchievementRule(
            organization_id=org.id,
            name="Busy day",
            metric_definition_id=calls.id,
            comparator="gte",
            threshold=Decimal(40),
            scope="everyone",
            message="{first_name} made {value}!",
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )
    )
    make_fact(calls, alice, 42, datetime(2026, 8, 12, 15, tzinfo=UTC))
    db.flush()

    notifications.detect_rules(db)

    row = db.query(Notification).one()
    assert row.body == "Alice made 42 calls!"
