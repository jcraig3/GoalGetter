"""How current the numbers are.

Two properties worth being suspicious about: that an agent can read this at all —
they are the ones who notice their deal is missing — and that reading it tells
them nothing about what the organization has plugged in.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import DataSource, MetricFact, SourceMapping


@pytest.fixture
def metric(make_metric):
    return make_metric("revenue", unit="currency", decimal_places=2)


@pytest.fixture
def agent(make_user):
    return make_user("agent", None, name="Alice")


@pytest.fixture
def signed_in(client, db, agent, sign_in):
    sign_in(agent)
    db.commit()
    return client


def make_source(db, org, **overrides):
    row = DataSource(
        organization_id=org.id,
        name=overrides.pop("name", "CRM"),
        connector=overrides.pop("connector", "webhook"),
        **overrides,
    )
    db.add(row)
    db.flush()
    return row


def feed(db, org, source, metric, *, enabled=True):
    db.add(
        SourceMapping(
            organization_id=org.id,
            data_source_id=source.id,
            metric_definition_id=metric.id,
            subject_field="owner",
            occurred_at_field="closed_at",
            value_field="amount",
            enabled=enabled,
        )
    )
    db.flush()


def fact(db, org, metric, user, *, when, source=None, source_type="connector"):
    db.add(
        MetricFact(
            organization_id=org.id,
            metric_definition_id=metric.id,
            subject_user_id=user.id,
            value=Decimal(100),
            occurred_at=when,
            source_type=source_type,
            data_source_id=source.id if source else None,
            external_id=f"e{when.isoformat()}",
        )
    )
    db.flush()


def only(body, metric):
    return next(row for row in body if row["metric_id"] == metric.id)


# ── Who may read it ──────────────────────────────────────────────────────────


def test_an_agent_may_read_it(signed_in, db, org, metric, agent):
    """**The point of it being its own endpoint.** The people being ranked are the
    ones who notice a missing deal, and "the sync is broken" is a much better
    answer for them than silence."""
    source = make_source(db, org)
    feed(db, org, source, metric)
    db.commit()

    response = signed_in.get("/api/data-freshness")

    assert response.status_code == 200
    assert only(response.json(), metric)["imported"] is True


def test_it_says_nothing_about_what_is_plugged_in(signed_in, db, org, metric):
    """Every agent can read this, so it must not describe the stack. A status
    word and some timestamps — no names, no connector types, no configuration."""
    source = make_source(db, org, name="Acme Salesforce Production", connector="webhook")
    feed(db, org, source, metric)
    db.commit()

    body = signed_in.get("/api/data-freshness").text

    assert "Acme Salesforce Production" not in body
    assert "webhook" not in body
    # And the shape is exactly what the client's `isLate` reads.
    row = only(signed_in.get("/api/data-freshness").json(), metric)
    assert set(row["sources"][0]) == {
        "last_status",
        "last_run_at",
        "next_run_at",
        "interval_minutes",
        "enabled",
    }


def test_signing_out_closes_it(client, metric):
    assert client.get("/api/data-freshness").status_code == 401


def test_another_organizations_metrics_are_not_listed(signed_in, db, metric):
    from app.models import MetricDefinition, Organization

    other = Organization(name="Rival", timezone="UTC")
    db.add(other)
    db.flush()
    db.add(
        MetricDefinition(
            organization_id=other.id,
            key="their_revenue",
            name="Their Revenue",
            aggregation="sum",
            direction="higher_is_better",
        )
    )
    db.commit()

    listed = {row["metric_id"] for row in signed_in.get("/api/data-freshness").json()}

    assert listed == {metric.id}


# ── What it reports ──────────────────────────────────────────────────────────


def test_a_hand_entered_metric_is_not_imported(signed_in, db, org, metric, agent):
    """Nobody promised it would refresh, so the client must be able to tell it
    apart — warning that a manually corrected figure is stale invents a problem."""
    fact(db, org, metric, agent, when=datetime(2026, 8, 1, tzinfo=UTC), source_type="manual")
    db.commit()

    row = only(signed_in.get("/api/data-freshness").json(), metric)

    assert row["imported"] is False
    assert row["sources"] == []


def test_the_timestamp_is_when_it_happened_not_when_it_arrived(
    signed_in, db, org, metric, agent
):
    """A reader asking "how current is this?" means the data, not the plumbing."""
    source = make_source(db, org)
    feed(db, org, source, metric)
    fact(db, org, metric, agent, when=datetime(2026, 8, 7, 12, tzinfo=UTC), source=source)
    db.commit()

    row = only(signed_in.get("/api/data-freshness").json(), metric)

    assert row["latest_fact_at"].startswith("2026-08-07T12:00")


def test_the_newest_measurement_wins(signed_in, db, org, metric, agent):
    source = make_source(db, org)
    feed(db, org, source, metric)
    fact(db, org, metric, agent, when=datetime(2026, 8, 1, tzinfo=UTC), source=source)
    fact(db, org, metric, agent, when=datetime(2026, 8, 9, tzinfo=UTC), source=source)
    db.commit()

    row = only(signed_in.get("/api/data-freshness").json(), metric)

    assert row["latest_fact_at"].startswith("2026-08-09")


def test_a_hand_entered_correction_does_not_pass_for_a_sync(
    signed_in, db, org, metric, agent
):
    """Otherwise somebody typing a number by hand would make a dead feed look
    alive — which is the exact failure this endpoint exists to reveal."""
    source = make_source(db, org)
    feed(db, org, source, metric)
    fact(db, org, metric, agent, when=datetime(2026, 8, 1, tzinfo=UTC), source=source)
    fact(
        db, org, metric, agent,
        when=datetime(2026, 8, 19, tzinfo=UTC), source_type="manual",
    )
    db.commit()

    row = only(signed_in.get("/api/data-freshness").json(), metric)

    assert row["latest_fact_at"].startswith("2026-08-01")
    # …but "Data as of" counts it (Q2-12): the figure on the page includes it.
    assert row["latest_any_at"].startswith("2026-08-19")


def test_a_disabled_mapping_is_not_a_feed(signed_in, db, org, metric):
    """Every source passes through this state in the middle of the connect flow.
    A half-built mapping must not make a metric look overdue."""
    source = make_source(db, org)
    feed(db, org, source, metric, enabled=False)
    db.commit()

    row = only(signed_in.get("/api/data-freshness").json(), metric)

    assert row["imported"] is False


def test_a_removed_source_is_not_a_feed(signed_in, db, org, metric):
    """Archiving disables the source, and the client reads "every feed disabled" as
    *importing is paused* — so without this, removing a source would put a warning
    about pausing on a leaderboard working perfectly well from whatever replaced
    it."""
    source = make_source(db, org)
    source.enabled = False
    source.archived_at = datetime.now(UTC)
    feed(db, org, source, metric)
    db.commit()

    row = only(signed_in.get("/api/data-freshness").json(), metric)

    assert row["imported"] is False
    assert row["sources"] == []


def test_a_replacement_source_is_judged_on_its_own(signed_in, db, org, metric):
    """The case that makes the rule above matter: one integration removed, another
    feeding the same metric. The live one decides."""
    removed = make_source(db, org, name="Old")
    removed.enabled = False
    removed.archived_at = datetime.now(UTC)
    feed(db, org, removed, metric)
    feed(db, org, make_source(db, org, name="New"), metric)
    db.commit()

    row = only(signed_in.get("/api/data-freshness").json(), metric)

    assert len(row["sources"]) == 1
    assert row["sources"][0]["enabled"] is True


def test_the_scheduling_facts_come_through(signed_in, db, org, metric):
    """What the client's lateness check reads. Passed through rather than judged
    here: `sourceWizard.isLate` already decides what overdue means, and a second
    definition would agree right up until somebody adjusted one."""
    due = datetime(2026, 8, 19, 12, tzinfo=UTC)
    source = make_source(db, org, interval_minutes=15)
    source.last_status = "failed"
    source.last_run_at = due - timedelta(minutes=15)
    source.next_run_at = due
    feed(db, org, source, metric)
    db.commit()

    reported = only(signed_in.get("/api/data-freshness").json(), metric)["sources"][0]

    assert reported["last_status"] == "failed"
    assert reported["interval_minutes"] == 15
    assert reported["next_run_at"].startswith("2026-08-19T12:00")
    assert reported["enabled"] is True


def test_a_paused_source_reports_as_paused(signed_in, db, org, metric):
    """How the client says "importing is paused, so these numbers stopped
    updating" — which is a different sentence from "a feed is overdue", and
    blaming the scheduler for a decision somebody made on purpose is worse than
    saying nothing."""
    source = make_source(db, org)
    source.enabled = False
    feed(db, org, source, metric)
    db.commit()

    reported = only(signed_in.get("/api/data-freshness").json(), metric)["sources"][0]

    assert reported["enabled"] is False


def test_every_feed_behind_a_metric_is_listed(signed_in, db, org, metric):
    """Two sources feeding one metric is the case the detect-and-warn rule exists
    for, and the client needs both to tell "one is paused" from "all are"."""
    for name in ("CRM", "Warehouse"):
        feed(db, org, make_source(db, org, name=name), metric)
    db.commit()

    row = only(signed_in.get("/api/data-freshness").json(), metric)

    assert len(row["sources"]) == 2


def test_an_archived_metric_is_left_out(signed_in, db, org, metric, make_metric):
    """Nothing reads it any more, so its freshness is not a question anybody has."""
    live = make_metric("deals_won")
    metric.archived_at = datetime.now(UTC)
    db.commit()

    listed = {row["metric_id"] for row in signed_in.get("/api/data-freshness").json()}

    assert listed == {live.id}


def test_a_metric_nothing_has_ever_written_to_is_still_listed(signed_in, db, org, metric):
    """A null timestamp is an answer — "nothing has been imported yet" — and
    leaving the metric out would make the client unable to say it."""
    source = make_source(db, org)
    feed(db, org, source, metric)
    db.commit()

    row = only(signed_in.get("/api/data-freshness").json(), metric)

    assert row["latest_fact_at"] is None
    assert row["imported"] is True


def test_the_query_count_does_not_grow_with_the_number_of_metrics(
    signed_in, db, org, make_metric
):
    """A page renders immediately on load, so this cannot be a query per metric.

    Measured at two sizes rather than against a fixed ceiling: the property is
    that the count does not *grow*, and a threshold passes just as happily for an
    implementation that is one query short of it.
    """
    from sqlalchemy import event

    def count_selects() -> int:
        seen: list[str] = []

        def record(conn, cursor, statement, *args):
            if statement.lstrip().upper().startswith("SELECT"):
                seen.append(statement)

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            signed_in.get("/api/data-freshness")
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return len(seen)

    feed(db, org, make_source(db, org, name="S0"), make_metric("metric_0"))
    db.commit()
    with_one = count_selects()

    for i in range(1, 8):
        feed(db, org, make_source(db, org, name=f"S{i}"), make_metric(f"metric_{i}"))
    db.commit()
    with_eight = count_selects()

    assert with_eight == with_one, f"{with_one} then {with_eight}"
