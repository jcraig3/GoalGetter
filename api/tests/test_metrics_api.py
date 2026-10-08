"""Metric definition endpoints and the aggregation endpoint."""

from datetime import UTC, datetime

import pytest

from app.metrics_seed import DEFAULT_METRICS, seed_default_metrics
from app.models import MetricDefinition

WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin"))


@pytest.fixture
def manager(make_team, make_user):
    return make_user("manager", make_team("Enterprise"))


# ── Creating ─────────────────────────────────────────────────────────────────


def test_create_a_metric(client, admin):
    response = client.post(
        "/api/metrics",
        json={"key": "widgets_sold", "name": "Widgets Sold", "unit": "count"},
    )
    assert response.status_code == 201
    assert response.json()["key"] == "widgets_sold"


@pytest.mark.parametrize(
    "key",
    [
        "Calls Made",  # spaces and capitals
        "calls-made",  # hyphen
        "1calls",  # leading digit
        "c",  # too short
        "calls.made",  # dot
        "CALLS_MADE",  # uppercase
    ],
)
def test_invalid_keys_are_rejected(client, admin, key):
    """Keys are how connectors and spreadsheet columns address a metric, so
    anything needing quoting or escaping is refused up front."""
    response = client.post("/api/metrics", json={"key": key, "name": "X"})
    assert response.status_code == 422


def test_duplicate_key_is_a_conflict(client, admin):
    client.post("/api/metrics", json={"key": "widgets", "name": "Widgets"})
    response = client.post("/api/metrics", json={"key": "widgets", "name": "Again"})
    assert response.status_code == 409
    assert "widgets" in response.json()["detail"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("aggregation", "median"),
        ("direction", "sideways"),
        ("unit", "furlongs"),
        ("decimal_places", 9),
        ("decimal_places", -1),
    ],
)
def test_unknown_enum_values_are_rejected(client, admin, field, value):
    response = client.post(
        "/api/metrics", json={"key": "probe_metric", "name": "Probe", field: value}
    )
    assert response.status_code == 422


def test_the_database_rejects_a_bad_aggregation_even_without_the_api(db, org):
    """Defence in depth. The CHECK constraint holds even for a bulk insert, a
    data migration, or a fix typed into psql."""
    from sqlalchemy.exc import IntegrityError

    db.add(
        MetricDefinition(
            organization_id=org.id,
            key="sneaky",
            name="Sneaky",
            unit="count",
            aggregation="median",
            direction="higher_is_better",
            decimal_places=0,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


# ── Updating ─────────────────────────────────────────────────────────────────


def test_key_cannot_be_changed(client, admin):
    """Rejected loudly rather than silently ignored. Pydantic's default would
    drop the field and return 200, telling the client it renamed something it
    did not — and connectors would keep using the old key."""
    created = client.post("/api/metrics", json={"key": "widgets", "name": "W"}).json()
    response = client.patch(f"/api/metrics/{created['id']}", json={"key": "gadgets"})
    assert response.status_code == 422
    assert "not permitted" in str(response.json()["detail"])


def test_an_omitted_field_is_left_alone(client, admin):
    created = client.post(
        "/api/metrics",
        json={"key": "widgets", "name": "W", "description": "keep me", "unit": "currency"},
    ).json()
    updated = client.patch(f"/api/metrics/{created['id']}", json={"name": "W2"}).json()
    assert updated["description"] == "keep me"
    assert updated["unit"] == "currency"


def test_name_is_freely_editable(client, admin):
    created = client.post("/api/metrics", json={"key": "calls_made", "name": "Calls"}).json()
    updated = client.patch(f"/api/metrics/{created['id']}", json={"name": "Dials"}).json()
    assert (updated["name"], updated["key"]) == ("Dials", "calls_made")


# ── Archive, restore, delete ─────────────────────────────────────────────────


def test_archive_hides_from_the_default_list_but_not_from_include_archived(client, admin):
    created = client.post("/api/metrics", json={"key": "widgets", "name": "W"}).json()
    client.post(f"/api/metrics/{created['id']}/archive")

    assert created["id"] not in [m["id"] for m in client.get("/api/metrics").json()]
    listed = client.get("/api/metrics?include_archived=true").json()
    assert next(m for m in listed if m["id"] == created["id"])["archived"] is True


def test_restore_brings_it_back(client, admin):
    created = client.post("/api/metrics", json={"key": "widgets", "name": "W"}).json()
    client.post(f"/api/metrics/{created['id']}/archive")
    client.post(f"/api/metrics/{created['id']}/restore")
    assert created["id"] in [m["id"] for m in client.get("/api/metrics").json()]


def test_an_unmeasured_metric_can_be_deleted(client, admin):
    created = client.post("/api/metrics", json={"key": "mistake", "name": "Oops"}).json()
    assert client.delete(f"/api/metrics/{created['id']}").status_code == 204
    assert client.patch(f"/api/metrics/{created['id']}", json={"name": "x"}).status_code == 404


def test_a_measured_metric_cannot_be_deleted(client, admin, db, make_user, make_fact):
    """A leaderboard for last quarter must still be able to name the metric it
    ranked, so once facts exist the only correct action is archive."""
    created = client.post("/api/metrics", json={"key": "calls_made", "name": "Calls"}).json()
    metric = db.get(MetricDefinition, created["id"])
    make_fact(metric, make_user("agent"), 5, WHEN)

    response = client.delete(f"/api/metrics/{created['id']}")
    assert response.status_code == 409
    assert "Archive it instead" in response.json()["detail"]
    # And it really is still there.
    assert client.get("/api/metrics").json()


# ── Seeding ──────────────────────────────────────────────────────────────────


def test_seeding_a_fresh_organization_creates_every_default(db, org):
    assert seed_default_metrics(db, org.id) == len(DEFAULT_METRICS)


def test_seeding_twice_creates_nothing_the_second_time(db, org):
    seed_default_metrics(db, org.id)
    assert seed_default_metrics(db, org.id) == 0


def test_seeding_preserves_a_rename(db, org):
    """Matching is by key, so an admin who renamed "Calls Made" to "Dials"
    keeps their label when defaults are restored."""
    from sqlalchemy import select

    seed_default_metrics(db, org.id)
    metric = db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.organization_id == org.id, MetricDefinition.key == "calls_made"
        )
    )
    metric.name = "Dials"
    db.flush()

    seed_default_metrics(db, org.id)
    db.refresh(metric)
    assert metric.name == "Dials"


def test_seeding_restores_a_deleted_default(db, org):
    """Deliberate: "restore defaults" that leaves out the one you deleted is
    not restoring defaults. Archiving is how you opt out permanently, because
    the key still exists and the seeder skips it."""
    from sqlalchemy import select

    seed_default_metrics(db, org.id)
    metric = db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.organization_id == org.id, MetricDefinition.key == "emails_sent"
        )
    )
    db.delete(metric)
    db.flush()

    assert seed_default_metrics(db, org.id) == 1


def test_seeding_skips_an_archived_default(db, org):
    from sqlalchemy import select

    seed_default_metrics(db, org.id)
    metric = db.scalar(
        select(MetricDefinition).where(
            MetricDefinition.organization_id == org.id, MetricDefinition.key == "emails_sent"
        )
    )
    metric.archived_at = datetime.now(UTC)
    db.flush()

    assert seed_default_metrics(db, org.id) == 0


def test_every_default_metric_is_valid(db, org):
    """Guards the seed list against the CHECK constraints. A typo here would
    otherwise only surface when someone ran setup on a fresh deployment."""
    from app.models.metric_definition import AGGREGATIONS, DIRECTIONS, UNITS
    from app.routers.metrics import KEY_PATTERN

    for key, _name, unit, aggregation, direction, decimals in DEFAULT_METRICS:
        assert KEY_PATTERN.match(key), key
        assert unit in UNITS
        assert aggregation in AGGREGATIONS
        assert direction in DIRECTIONS
        assert 0 <= decimals <= 4

    seed_default_metrics(db, org.id)
    db.flush()  # the CHECK constraints run here


def test_default_keys_are_unique():
    keys = [row[0] for row in DEFAULT_METRICS]
    assert len(keys) == len(set(keys))


# ── Permissions ──────────────────────────────────────────────────────────────


def test_a_manager_cannot_create_a_metric(client, db, manager, sign_in):
    sign_in(manager)
    assert client.post("/api/metrics", json={"key": "x_metric", "name": "X"}).status_code == 403


def test_a_manager_can_read_metrics(client, db, org, manager, sign_in, make_metric):
    """Every role reads definitions: an agent's dashboard needs to know that
    Revenue Closed is currency with 2 decimals in order to format it. This
    returns what is measured, never anyone's numbers."""
    make_metric("calls_made")
    sign_in(manager)
    assert client.get("/api/metrics").status_code == 200


def test_an_agent_can_read_metrics(client, make_user, sign_in, make_metric):
    make_metric("calls_made")
    sign_in(make_user("agent"))
    assert client.get("/api/metrics").status_code == 200


def test_signed_out_requests_are_rejected(client, make_metric):
    make_metric("calls_made")
    assert client.get("/api/metrics").status_code == 401


def test_another_organizations_metric_is_not_found(client, admin, db):
    """404, not 403 — confirming it exists would itself leak information."""
    from app.models import Organization

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = MetricDefinition(
        organization_id=other.id, key="secret", name="Secret",
        unit="count", aggregation="sum", direction="higher_is_better", decimal_places=0,
    )
    db.add(theirs)
    db.flush()

    assert client.patch(f"/api/metrics/{theirs.id}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/api/metrics/{theirs.id}").status_code == 404
    assert theirs.id not in [m["id"] for m in client.get("/api/metrics").json()]


# ── POST /api/metrics/query ──────────────────────────────────────────────────


@pytest.fixture
def measured(db, org, make_metric, make_user, make_team, make_fact):
    team = make_team("Enterprise")
    alice = make_user("agent", team, name="Alice")
    bob = make_user("agent", team, name="Bob")
    metric = make_metric("calls_made")
    make_fact(metric, alice, 10, WHEN)
    make_fact(metric, bob, 30, WHEN)
    return {"metric": metric, "alice": alice, "bob": bob, "team": team}


def test_query_returns_ranked_rows(client, admin, measured):
    response = client.post(
        "/api/metrics/query",
        json={"metric_id": measured["metric"].id, "period": {"type": "month", "anchor": "2026-08-12"}},
    )
    assert response.status_code == 200
    body = response.json()
    assert [(r["rank"], r["subject_name"]) for r in body["rows"]] == [(1, "Bob"), (2, "Alice")]
    assert body["total"] == "40.0000"


def test_query_values_are_json_strings_not_numbers(client, admin, measured):
    """JavaScript numbers are IEEE doubles. Serialising NUMERIC as a number
    would discard the precision the column was chosen for, in the last step."""
    body = client.post(
        "/api/metrics/query",
        json={"metric_id": measured["metric"].id, "period": {"type": "month", "anchor": "2026-08-12"}},
    ).json()
    assert isinstance(body["rows"][0]["value"], str)
    assert isinstance(body["total"], str)


def test_query_echoes_the_metric_format(client, admin, measured):
    """The client needs unit and decimal_places to format the value, and
    fetching them separately would be a guaranteed second round trip."""
    body = client.post(
        "/api/metrics/query", json={"metric_id": measured["metric"].id}
    ).json()
    assert set(body["metric"]) >= {"unit", "decimal_places", "direction", "aggregation"}


def test_query_by_team(client, admin, measured):
    body = client.post(
        "/api/metrics/query",
        json={
            "metric_id": measured["metric"].id,
            "group_by": "team",
            "period": {"type": "month", "anchor": "2026-08-12"},
        },
    ).json()
    assert [(r["subject_name"], r["value"]) for r in body["rows"]] == [("Enterprise", "40.0000")]


def test_an_agent_querying_sees_only_themselves(client, db, measured, sign_in):
    sign_in(measured["alice"])
    body = client.post(
        "/api/metrics/query",
        json={"metric_id": measured["metric"].id, "period": {"type": "month", "anchor": "2026-08-12"}},
    ).json()
    assert [r["subject_name"] for r in body["rows"]] == ["Alice"]
    assert body["total"] == "10.0000"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"metric_id": 999999}, 404),
        ({"metric_id": 1, "period": {"type": "fortnight"}}, 422),
        ({"metric_id": 1, "period": {"type": "custom"}}, 400),
        ({"metric_id": 1, "period": {"type": "custom", "start": "2026-08-31", "end": "2026-08-01"}}, 400),
        # "office" used to stand in for an unknown grouping here. It is a
        # real one now, so this needs a value that is genuinely not.
        ({"metric_id": 1, "group_by": "region"}, 422),
        ({"metric_id": 1, "limit": 100000}, 422),
        ({"metric_id": 1, "limit": 0}, 422),
        ({"metric_id": 1, "sort": "desc"}, 422),  # unknown field
        ({"metric_id": 1, "team_id": 999999}, 404),
    ],
)
def test_query_rejects_bad_input(client, admin, measured, payload, expected):
    payload = {**payload}
    if payload.get("metric_id") == 1:
        payload["metric_id"] = measured["metric"].id
    assert client.post("/api/metrics/query", json=payload).status_code == expected


def test_query_of_an_empty_period_is_not_an_error(client, admin, measured):
    """A quiet week is a real state the UI must render, not a failure."""
    body = client.post(
        "/api/metrics/query",
        json={"metric_id": measured["metric"].id, "period": {"type": "month", "anchor": "2020-01-15"}},
    ).json()
    assert body["rows"] == []
    assert body["total"] == "0"


def test_a_count_that_sums_like_money_is_flagged_for_an_admin(
    client, db, org, admin, make_metric, make_user, make_fact
):
    """QA-39: "Closed Deals", a count, summed to 57K because its mapping read
    the amount column. Nothing said so."""
    from app.models import DataSource, SourceMapping

    deals = make_metric("closed_deals")
    person = make_user("agent")
    make_fact(deals, person, 38177.34, WHEN)
    make_fact(deals, person, 4490.77, WHEN)
    source = DataSource(organization_id=org.id, name="Sales tracker", connector="microsoft_excel")
    db.add(source)
    db.flush()
    db.add(SourceMapping(organization_id=org.id, data_source_id=source.id,
                         metric_definition_id=deals.id, subject_field="email",
                         value_field="amount"))
    db.flush()

    row = next(m for m in client.get("/api/metrics").json() if m["id"] == deals.id)

    assert row["looks_like_amounts"] is True
    assert row["sources"] == ["Sales tracker"]


def test_an_agent_is_not_told_what_feeds_a_metric(client, db, make_metric, make_user, sign_in):
    deals = make_metric("closed_deals")
    sign_in(make_user("agent"))

    row = next(m for m in client.get("/api/metrics").json() if m["id"] == deals.id)

    assert (row["sources"], row["looks_like_amounts"]) == ([], False)
