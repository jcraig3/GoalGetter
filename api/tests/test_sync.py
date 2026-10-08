"""Running a source end to end.

Driven by a stub connector rather than a real provider, deliberately: this is the
engine, and the first real connector should prove the *provider*, not this.

The two rules worth reading the tests for: **a human correction wins over a sync**,
and **a row whose person is unknown waits** rather than being invented or dropped.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app import connectors, identity, sync
from app.models import (
    DataSource,
    MetricFact,
    SourceMapping,
    SyncRun,
    UserIdentity,
)

WHEN = "2026-08-07T12:00:00Z"


class Config(BaseModel):
    pass


class Secrets(BaseModel):
    pass


class Stub:
    """A connector that **honours the window**, like a real one.

    It used to hand back every row regardless of `since`, and that one convenience
    hid a serious bug for an entire phase: the sync advanced its window past rows it
    had only quarantined, so answering "this identifier is Alice" left the rows
    permanently out of reach — and the test asserting the opposite passed, because
    this stub served them up anyway.

    A stub that cannot say "no" cannot test a window. Each row is available from its
    `Closed` timestamp onwards, which is how a real source behaves: it reports what
    happened in the span you asked about.
    """

    key = "stub"
    display_name = "Stub"
    config_schema = Config
    credential_schema = Secrets

    def __init__(self, rows=None, explode=None, truncate_after=None):
        self.rows = rows or []
        self.explode = explode
        #: Stop after this many rows and raise `Truncated`, the way a real
        #: connector does when it hits its page or row cap.
        self.truncate_after = truncate_after
        self.fetch_calls = 0
        self.since_seen = []
        self.locals_seen = []

    def test_connection(self, config, credentials):
        return connectors.ConnectionResult(ok=True, detail="fine")

    def discover(self, config, credentials, *, local=None):
        return []

    def fetch(self, config, credentials, since=None, *, local=None):
        self.fetch_calls += 1
        self.locals_seen.append(local)
        self.since_seen.append(since)
        if self.explode:
            raise self.explode
        sent = 0
        for row in self.rows:
            if since is None or _available_at(row) >= since:
                if self.truncate_after is not None and sent >= self.truncate_after:
                    # After the rows, never instead of them — which is the whole
                    # contract of `Truncated`.
                    raise connectors.Truncated(
                        "Stopped early, so this run is incomplete."
                    )
                sent += 1
                yield row


@dataclass(frozen=True)
class Timed(connectors.SourceRow):
    """A row, plus when the source would report it.

    Separate from `Closed` on purpose. A source filters on when it *learned*
    something, not on when the thing happened — so an edited deal comes back with a
    new availability and an unchanged close date. Conflating the two is how a
    connector silently stops delivering late edits, and it is the distinction every
    connector in 3b has to get right.
    """

    available_at: datetime | None = None


def _available_at(source_row) -> datetime:
    """When this row became visible. Defaults to when it happened."""
    return getattr(source_row, "available_at", None) or _parse(
        source_row.values["Closed"]
    )


def _parse(value) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def row(external_id, who, amount=100, when=WHEN, available_at=None, **extra):
    """One row a source would hand over.

    `available_at` is when the source would report it — pass it when a test
    re-delivers an edited row, because an incremental window is the reason a source
    has to re-report an edit at all.
    """
    values = {"Owner": who, "Amount": amount, "Closed": when}
    values.update(extra)
    return Timed(
        external_id=external_id,
        values=values,
        available_at=_parse(available_at) if available_at else None,
    )


@pytest.fixture
def stub(registry_slot):
    """A connector registered under `stub` for the duration of one test."""

    def _install(rows=None, explode=None, truncate_after=None):
        instance = Stub(rows=rows, explode=explode, truncate_after=truncate_after)
        connectors._REGISTRY["stub"] = instance
        return instance

    return _install


@pytest.fixture
def source(db, org):
    row = DataSource(
        organization_id=org.id, name="CRM", connector="stub", backfill_days=90
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def metric(make_metric):
    return make_metric("revenue", unit="currency", decimal_places=2)


@pytest.fixture
def mapped(db, org, source, metric):
    row = SourceMapping(
        organization_id=org.id,
        data_source_id=source.id,
        metric_definition_id=metric.id,
        value_field="Amount",
        occurred_at_field="Closed",
        subject_field="Owner",
        external_id_field=None,
    )
    db.add(row)
    db.flush()
    return row


def facts(db):
    return list(db.scalars(select(MetricFact).order_by(MetricFact.id)).all())


# ── The happy path ───────────────────────────────────────────────────────────


def test_a_matched_row_becomes_a_fact(db, org, source, mapped, stub, make_user):
    alice = make_user("agent", None, name="Alice")
    stub(rows=[row("1", alice.email, amount="1,200.50")])

    outcome = sync.run(db, org, source)

    assert outcome.status == "ok"
    assert outcome.rows_read == 1
    assert outcome.rows_written == 1
    written = facts(db)[0]
    assert written.value == Decimal("1200.50")
    assert written.subject_user_id == alice.id
    assert written.source_type == "connector"
    assert written.data_source_id == source.id


def test_the_team_and_office_are_stamped_on_the_fact(
    db, org, source, mapped, stub, make_user, make_team
):
    """A snapshot, not a lookup at read time. A win belongs to the team somebody was
    on when they earned it, and a transfer must not move last month's numbers to a
    different leaderboard."""
    from app.models import Office

    phoenix = Office(organization_id=org.id, name="Phoenix")
    db.add(phoenix)
    db.flush()
    team = make_team("Enterprise")
    team.office_id = phoenix.id
    db.flush()
    alice = make_user("agent", team, name="Alice")
    stub(rows=[row("1", alice.email)])

    sync.run(db, org, source)

    written = facts(db)[0]
    assert written.subject_team_id == team.id
    assert written.subject_office_id == phoenix.id


def test_re_reading_the_same_row_writes_nothing(db, org, source, mapped, stub, make_user):
    """Idempotency, which is what `external_id` is for. Overlapping windows are free
    precisely because of this."""
    alice = make_user("agent", None, name="Alice")
    mapped.external_id_field = "Id"
    db.flush()
    first_at = datetime(2026, 8, 8, 12, tzinfo=UTC)
    stub(rows=[row("ignored", alice.email, Id="deal-1")])
    first = sync.run(db, org, source, now=first_at)

    # Reported again — an overlapping window, which is the case this exists for.
    stub(rows=[row("ignored", alice.email, Id="deal-1",
                   available_at="2026-08-08T13:00:00Z")])
    second = sync.run(db, org, source, now=first_at + timedelta(hours=2))

    assert first.rows_written == 1
    assert second.rows_read == 1  # it really did look again
    assert second.rows_written == 0
    assert len(facts(db)) == 1


def test_a_changed_value_updates_in_place(db, org, source, mapped, stub, make_user):
    alice = make_user("agent", None, name="Alice")
    mapped.external_id_field = "Id"
    db.flush()

    first_at = datetime(2026, 8, 8, 12, tzinfo=UTC)
    stub(rows=[row("x", alice.email, amount=100, Id="deal-1")])
    sync.run(db, org, source, now=first_at)

    # The source reports the deal again, edited. It has to: an incremental window
    # asks "what have you learned since", so a connector that filters on the close
    # date rather than a modified date would never deliver this edit at all.
    stub(rows=[row("x", alice.email, amount=250, Id="deal-1",
                   available_at="2026-08-08T13:00:00Z")])
    second = sync.run(db, org, source, now=first_at + timedelta(hours=2))

    assert second.rows_written == 1
    assert len(facts(db)) == 1
    assert facts(db)[0].value == Decimal(250)


def test_the_pipeline_tells_the_connector_which_source_it_is(
    db, org, source, mapped, stub, make_user
):
    """A push connector reads its own inbox, so it needs to know which one is its
    *and* to use the session the sync is already in. Every pulling connector
    ignores both."""
    alice = make_user("agent", None, name="Alice")
    instance = stub(rows=[row("1", alice.email)])

    sync.run(db, org, source)

    seen = instance.locals_seen[0]
    assert seen.source_id == source.id
    # The sync's own session, not a new one — otherwise the connector reads on a
    # different connection from the one writing the facts.
    assert seen.db is db


def test_the_connector_uses_the_source_id_when_no_column_is_mapped(
    db, org, source, mapped, stub, make_user
):
    """A webhook knows its own event id without an admin naming a column for it."""
    alice = make_user("agent", None, name="Alice")
    stub(rows=[row("event-99", alice.email)])

    sync.run(db, org, source)

    assert facts(db)[0].external_id == "event-99"


# ── Corrections win ──────────────────────────────────────────────────────────


def test_a_corrected_fact_is_not_overwritten(db, org, source, mapped, stub, make_user):
    """**The rule decided before any of this was written.** Anything else makes the
    corrections tool theatre."""
    alice = make_user("agent", None, name="Alice")
    mapped.external_id_field = "Id"
    db.flush()

    first_at = datetime(2026, 8, 8, 12, tzinfo=UTC)
    stub(rows=[row("x", alice.email, amount=100, Id="deal-1")])
    sync.run(db, org, source, now=first_at)

    corrected = facts(db)[0]
    corrected.value = Decimal(999)
    corrected.corrected_at = first_at + timedelta(minutes=30)
    db.flush()

    stub(rows=[row("x", alice.email, amount=100, Id="deal-1",
                   available_at="2026-08-08T13:00:00Z")])
    second = sync.run(db, org, source, now=first_at + timedelta(hours=2))

    assert facts(db)[0].value == Decimal(999)
    assert second.conflicts == 1
    assert second.rows_written == 0


def test_a_conflict_makes_the_run_partial_not_ok(db, org, source, mapped, stub, make_user):
    """So it is visible. A correction that permanently contradicts its source is
    something somebody should get to see."""
    alice = make_user("agent", None, name="Alice")
    mapped.external_id_field = "Id"
    db.flush()
    first_at = datetime(2026, 8, 8, 12, tzinfo=UTC)
    stub(rows=[row("x", alice.email, Id="deal-1")])
    sync.run(db, org, source, now=first_at)
    fact = facts(db)[0]
    fact.corrected_at = first_at + timedelta(minutes=30)
    db.flush()

    stub(rows=[row("x", alice.email, amount=500, Id="deal-1",
                   available_at="2026-08-08T13:00:00Z")])
    second = sync.run(db, org, source, now=first_at + timedelta(hours=2))

    assert second.status == "partial"


# ── Quarantine ───────────────────────────────────────────────────────────────


def test_an_unknown_person_holds_the_row(db, org, source, mapped, stub):
    stub(rows=[row("1", "stranger@acme.com")])

    outcome = sync.run(db, org, source)

    assert outcome.rows_quarantined == 1
    assert outcome.rows_written == 0
    assert facts(db) == []
    assert outcome.status == "partial"


def test_mapping_the_person_then_re_syncing_writes_the_held_rows(
    db, org, source, mapped, stub, make_user
):
    """The point of quarantining rather than dropping: nothing was lost, and the
    source is re-read once the question is answered."""
    alice = make_user("agent", None, name="Alice")
    rows = [row("1", "stranger@acme.com")]
    stub(rows=rows)
    sync.run(db, org, source)

    waiting = identity.pending(db, source)[0]
    identity.map_to(db, waiting, alice.id)

    stub(rows=rows)
    second = sync.run(db, org, source)

    assert second.rows_written == 1
    assert facts(db)[0].subject_user_id == alice.id


def test_an_ignored_person_is_skipped_not_quarantined(db, org, source, mapped, stub):
    """For the `Integration User` a CRM owns half its records with. Skipped is not
    an error and not a question."""
    stub(rows=[row("1", "integration@acme.com")])
    sync.run(db, org, source)
    identity.ignore(db, identity.pending(db, source)[0])

    stub(rows=[row("1", "integration@acme.com")])
    second = sync.run(db, org, source)

    assert second.rows_skipped == 1
    assert second.rows_quarantined == 0


# ── Filters and mapping errors ───────────────────────────────────────────────


def test_a_filtered_row_is_skipped(db, org, source, mapped, stub, make_user):
    alice = make_user("agent", None, name="Alice")
    mapped.filters = [{"field": "Stage", "op": "eq", "value": "Closed Won"}]
    db.flush()
    stub(rows=[row("1", alice.email, Stage="Open")])

    outcome = sync.run(db, org, source)

    assert outcome.rows_skipped == 1
    assert facts(db) == []


def test_a_bad_column_reports_itself_without_failing_the_run(
    db, org, source, mapped, stub, make_user
):
    """A mapping pointed at the wrong column should say which column, and should
    not look like an outage."""
    alice = make_user("agent", None, name="Alice")
    mapped.value_field = "Amont"
    db.flush()
    stub(rows=[row("1", alice.email)])

    outcome = sync.run(db, org, source)

    assert outcome.status == "partial"
    assert "Amont" in outcome.error
    assert outcome.rows_skipped == 1


def test_repeated_mapping_errors_are_not_repeated_forty_thousand_times(
    db, org, source, mapped, stub, make_user
):
    """A wrong column fails on every row. An error field of identical sentences is
    no more useful than one with the first few."""
    alice = make_user("agent", None, name="Alice")
    mapped.value_field = "Amont"
    db.flush()
    stub(rows=[row(str(i), alice.email) for i in range(20)])

    outcome = sync.run(db, org, source)

    assert outcome.rows_skipped == 20
    assert outcome.error.count("Amont") <= sync.MAX_REPORTED_ERRORS


# ── One source, several metrics ──────────────────────────────────────────────


def test_one_row_can_feed_two_metrics(
    db, org, source, mapped, metric, stub, make_user, make_metric
):
    """A closed deal is both a "deals won" count and a "revenue" amount."""
    alice = make_user("agent", None, name="Alice")
    deals = make_metric("deals_won")
    db.add(
        SourceMapping(
            organization_id=org.id,
            data_source_id=source.id,
            metric_definition_id=deals.id,
            value_field=None,  # count the row as one
            occurred_at_field="Closed",
            subject_field="Owner",
            external_id_field="Id",
        )
    )
    mapped.external_id_field = "Id"
    db.flush()
    stub(rows=[row("x", alice.email, amount=5000, Id="deal-1")])

    outcome = sync.run(db, org, source)

    assert outcome.rows_written == 2
    values = sorted(f.value for f in facts(db))
    assert values == [Decimal(1), Decimal(5000)]


def test_the_provider_is_asked_once_for_several_mappings(
    db, org, source, mapped, metric, stub, make_user, make_metric
):
    """Asking twice for the same rows doubles the rate-limit cost to produce
    identical data."""
    alice = make_user("agent", None, name="Alice")
    deals = make_metric("deals_won")
    db.add(
        SourceMapping(
            organization_id=org.id,
            data_source_id=source.id,
            metric_definition_id=deals.id,
            value_field=None,
            occurred_at_field="Closed",
            subject_field="Owner",
        )
    )
    db.flush()
    instance = stub(rows=[row("1", alice.email)])

    sync.run(db, org, source)

    assert instance.fetch_calls == 1


def test_a_disabled_mapping_is_not_run(db, org, source, mapped, stub, make_user):
    alice = make_user("agent", None, name="Alice")
    mapped.enabled = False
    db.flush()
    stub(rows=[row("1", alice.email)])

    outcome = sync.run(db, org, source)

    assert facts(db) == []
    assert "No mappings" in outcome.error


def test_an_archived_metric_is_skipped_rather_than_failing(
    db, org, source, mapped, metric, stub, make_user
):
    """The admin retired the metric on purpose. The sync should not start failing
    because of a decision they made deliberately."""
    alice = make_user("agent", None, name="Alice")
    metric.archived_at = datetime.now(UTC)
    db.flush()
    stub(rows=[row("1", alice.email)])

    outcome = sync.run(db, org, source)

    assert outcome.status == "ok"
    assert facts(db) == []


# ── Failure, and what it does to the schedule ────────────────────────────────


def test_a_connector_raising_is_recorded_not_propagated(db, org, source, mapped, stub):
    """A scheduler that dies on one bad source stops syncing the good ones."""
    stub(explode=RuntimeError("the host is unreachable"))

    outcome = sync.run(db, org, source)

    assert outcome.status == "failed"
    assert "unreachable" in outcome.error
    assert source.failure_count == 1


def test_an_unknown_connector_says_so_clearly(db, org, source, mapped, registry_slot):
    """A source naming a connector this build does not ship is a deployment
    question, not a credential one."""
    connectors._REGISTRY.pop("stub", None)

    outcome = sync.run(db, org, source)

    assert outcome.status == "failed"
    assert "stub" in outcome.error


def test_repeated_failures_back_off(db, org, source, mapped, stub):
    now = datetime(2026, 8, 7, 12, tzinfo=UTC)
    stub(explode=RuntimeError("still broken"))

    delays = []
    for _ in range(4):
        sync.run(db, org, source, now=now)
        delays.append(int((source.next_run_at - now).total_seconds() // 60))
        stub(explode=RuntimeError("still broken"))

    assert delays == sorted(delays)
    assert delays[0] < delays[-1]


def test_success_clears_the_backoff(db, org, source, mapped, stub, make_user):
    alice = make_user("agent", None, name="Alice")
    now = datetime(2026, 8, 7, 12, tzinfo=UTC)
    stub(explode=RuntimeError("blip"))
    sync.run(db, org, source, now=now)
    assert source.failure_count == 1

    stub(rows=[row("1", alice.email)])
    sync.run(db, org, source, now=now)

    assert source.failure_count == 0
    assert source.next_run_at == now + timedelta(minutes=source.interval_minutes)


def test_backoff_never_polls_faster_than_the_configured_interval(
    db, org, source, mapped, stub
):
    """A nightly warehouse that failed must not be retried every five minutes just
    because the backoff curve starts there."""
    source.interval_minutes = 1440
    db.flush()
    now = datetime(2026, 8, 7, 12, tzinfo=UTC)
    stub(explode=RuntimeError("broken"))

    sync.run(db, org, source, now=now)

    assert source.next_run_at >= now + timedelta(minutes=1440)


# ── Scheduling ───────────────────────────────────────────────────────────────


def test_a_new_source_is_due_immediately(db, org, source):
    """`next_run_at IS NULL` is the state a freshly created source is in — it should
    sync promptly rather than appearing to do nothing for an hour."""
    assert source in sync.due(db)


def test_a_disabled_source_is_never_due(db, org, source):
    source.enabled = False
    db.flush()
    assert sync.due(db) == []


def test_a_source_is_not_due_before_its_next_run(db, org, source):
    now = datetime(2026, 8, 7, 12, tzinfo=UTC)
    source.next_run_at = now + timedelta(minutes=30)
    db.flush()

    assert sync.due(db, now=now) == []
    assert source in sync.due(db, now=now + timedelta(minutes=31))


def test_the_first_run_reaches_back_the_backfill_window(db, org, source, mapped, stub):
    now = datetime(2026, 8, 7, 12, tzinfo=UTC)
    instance = stub(rows=[])

    sync.run(db, org, source, now=now)

    assert instance.since_seen == [now - timedelta(days=90)]


def test_a_later_run_asks_from_the_last_successful_start(
    db, org, source, mapped, stub, make_user
):
    """From the last run's *start*, so a deal reported a minute after it closed is
    not missed by a window that began when the previous sync did. Overlap is free —
    the upsert is idempotent."""
    alice = make_user("agent", None, name="Alice")
    first_at = datetime(2026, 8, 7, 12, tzinfo=UTC)
    stub(rows=[row("1", alice.email)])
    sync.run(db, org, source, now=first_at)

    later = first_at + timedelta(hours=2)
    instance = stub(rows=[])
    sync.run(db, org, source, now=later)

    assert instance.since_seen == [first_at]


def test_a_partial_run_does_not_advance_the_window(
    db, org, source, mapped, stub, make_user
):
    """A `partial` run read rows it did not resolve. Moving past them makes them
    unreachable, which turns quarantine from a safety net into data loss."""
    alice = make_user("agent", None, name="Alice")
    first_at = datetime(2026, 8, 8, 12, tzinfo=UTC)
    stub(rows=[row("1", alice.email), row("2", "stranger@acme.com")])
    first = sync.run(db, org, source, now=first_at)
    assert first.status == "partial"  # the state under test, not an aside

    instance = stub(rows=[])
    sync.run(db, org, source, now=first_at + timedelta(hours=2))

    assert instance.since_seen == [first_at + timedelta(hours=2) - timedelta(days=90)]


def test_a_truncated_run_keeps_its_rows_and_holds_the_window(
    db, org, source, mapped, stub, make_user
):
    """**The bug this exists to stop.**

    Both engines used to hit their row cap, log a line, and return. The run then
    reported `ok`, the watermark moved past rows nobody had read, and those rows
    were never read again — silently, with two comments in the code claiming the
    truncation was "reported on the run".

    Two things have to hold together, and either alone is wrong: the rows already
    read are **kept**, and the window does **not** move.
    """
    alice = make_user("agent", None, name="Alice")
    at = datetime(2026, 8, 9, 12, tzinfo=UTC)
    stub(
        rows=[row("1", alice.email), row("2", alice.email), row("3", alice.email)],
        truncate_after=2,
    )

    first = sync.run(db, org, source, now=at)

    assert first.rows_read == 2
    assert first.rows_written == 2
    assert first.status == "partial"
    assert "incomplete" in (first.error or "")

    instance = stub(rows=[])
    sync.run(db, org, source, now=at + timedelta(hours=2))

    # Back to the start of the backfill, not forward past row three.
    assert instance.since_seen == [at + timedelta(hours=2) - timedelta(days=90)]


def test_a_clean_run_does_advance_the_window(
    db, org, source, mapped, stub, make_user
):
    """The other half. Without this, the rule above is indistinguishable from never
    advancing at all — which would re-read the whole backfill window forever."""
    alice = make_user("agent", None, name="Alice")
    first_at = datetime(2026, 8, 8, 12, tzinfo=UTC)
    stub(rows=[row("1", alice.email)])
    first = sync.run(db, org, source, now=first_at)
    assert first.status == "ok"

    instance = stub(rows=[])
    sync.run(db, org, source, now=first_at + timedelta(hours=2))

    assert instance.since_seen == [first_at]


def test_a_test_event_sent_before_the_mapping_still_gets_imported(
    db, org, source, metric, stub, make_user
):
    """The wizard's own order of operations: connect, send one event to see the
    fields, *then* map them. If the mapping-less run advanced the window, that first
    event could never become a fact and the wizard would end on an empty table."""
    alice = make_user("agent", None, name="Alice")
    sent_at = datetime(2026, 8, 8, 12, tzinfo=UTC)
    rows = [row("1", alice.email, when="2026-08-08T11:00:00Z")]
    stub(rows=rows)
    sync.run(db, org, source, now=sent_at)  # no mappings yet

    db.add(
        SourceMapping(
            organization_id=org.id,
            data_source_id=source.id,
            metric_definition_id=metric.id,
            value_field="Amount",
            occurred_at_field="Closed",
            subject_field="Owner",
        )
    )
    db.flush()
    stub(rows=rows)
    second = sync.run(db, org, source, now=sent_at + timedelta(minutes=5))

    assert second.rows_written == 1


def test_a_failed_run_does_not_advance_the_window(
    db, org, source, mapped, stub, make_user
):
    """Otherwise a failure silently skips whatever happened during it."""
    alice = make_user("agent", None, name="Alice")
    first_at = datetime(2026, 8, 7, 12, tzinfo=UTC)
    stub(rows=[row("1", alice.email)])
    sync.run(db, org, source, now=first_at)

    stub(explode=RuntimeError("blip"))
    sync.run(db, org, source, now=first_at + timedelta(hours=1))

    instance = stub(rows=[])
    sync.run(db, org, source, now=first_at + timedelta(hours=2))

    assert instance.since_seen == [first_at]


def test_run_due_syncs_everything_owed_and_survives_one_failure(
    db, org, source, mapped, stub, make_user, make_metric
):
    alice = make_user("agent", None, name="Alice")
    broken = DataSource(organization_id=org.id, name="Broken", connector="nope")
    db.add(broken)
    db.flush()
    stub(rows=[row("1", alice.email)])

    tally = sync.run_due(db)

    assert tally["sources"] == 2
    assert tally["written"] == 1
    assert tally["failed"] == 1


def test_a_run_is_recorded_either_way(db, org, source, mapped, stub):
    stub(explode=RuntimeError("nope"))
    sync.run(db, org, source)

    runs = db.scalars(select(SyncRun)).all()
    assert len(runs) == 1
    assert runs[0].finished_at is not None
    assert runs[0].trigger == "schedule"


# ── Preview: what would happen, without it happening ─────────────────────────


def test_preview_shows_the_facts_a_mapping_would_write(
    db, org, source, mapped, stub, make_user
):
    alice = make_user("agent", None, name="Alice")
    stub(rows=[row("1", alice.email, amount="1,200.50")])

    rows = sync.preview(db, org, source, mapped)

    assert len(rows) == 1
    assert rows[0].outcome == "written"
    assert rows[0].subject_name == "Alice"
    assert rows[0].value == Decimal("1200.50")


def test_preview_writes_nothing(db, org, source, mapped, stub, make_user):
    """**The whole point.** No fact, no `sync_run`, and no quarantine question — a
    preview that created a queue as a side effect of being looked at would be a
    nasty surprise."""
    alice = make_user("agent", None, name="Alice")
    stub(rows=[row("1", alice.email), row("2", "stranger@acme.com")])

    sync.preview(db, org, source, mapped)

    assert facts(db) == []
    assert db.scalars(select(SyncRun)).all() == []
    assert db.scalars(select(UserIdentity)).all() == []


def test_preview_does_not_inflate_an_existing_question(
    db, org, source, mapped, stub
):
    """The case the first version of these tests missed.

    Previewing a source that has *already* been synced walks the branch where the
    identity row exists and is unanswered — and a mutation incrementing its count
    there survived, because every other preview test started from an empty inbox.
    Looking at a mapping must not change how many rows are said to be waiting.
    """
    stub(rows=[row("1", "stranger@acme.com")])
    sync.run(db, org, source)
    question = identity.pending(db, source)[0]
    before = question.pending_rows

    stub(rows=[row("1", "stranger@acme.com")])
    sync.preview(db, org, source, mapped)

    assert question.pending_rows == before


def test_preview_still_reports_a_known_unanswered_identifier(
    db, org, source, mapped, stub
):
    """Not recording it must not mean not *seeing* it — the row is still shown as
    one that would be held."""
    stub(rows=[row("1", "stranger@acme.com")])
    sync.run(db, org, source)

    stub(rows=[row("1", "stranger@acme.com")])
    rows = sync.preview(db, org, source, mapped)

    assert rows[0].outcome == "quarantined"


def test_preview_names_who_would_be_quarantined(db, org, source, mapped, stub):
    """The useful half of a preview is the rows that would *not* work."""
    stub(rows=[row("1", "stranger@acme.com")])

    rows = sync.preview(db, org, source, mapped)

    assert rows[0].outcome == "quarantined"
    assert "stranger@acme.com" in rows[0].detail


def test_preview_shows_a_filtered_row_as_skipped(db, org, source, mapped, stub, make_user):
    """So an admin can see the filter is excluding more than they expected."""
    alice = make_user("agent", None, name="Alice")
    mapped.filters = [{"field": "Stage", "op": "eq", "value": "Closed Won"}]
    db.flush()
    stub(rows=[row("1", alice.email, Stage="Open")])

    rows = sync.preview(db, org, source, mapped)

    assert rows[0].outcome == "skipped"
    assert "filters" in rows[0].detail


def test_preview_reports_a_bad_column_per_row(db, org, source, mapped, stub, make_user):
    """Three seconds, instead of after a sync has written forty thousand wrong
    rows."""
    alice = make_user("agent", None, name="Alice")
    mapped.value_field = "Amont"
    db.flush()
    stub(rows=[row("1", alice.email)])

    rows = sync.preview(db, org, source, mapped)

    assert rows[0].outcome == "error"
    assert "Amont" in rows[0].detail


def test_preview_is_capped(db, org, source, mapped, stub, make_user):
    """Enough to recognise a mapping by, few enough that the wizard answers at
    once."""
    alice = make_user("agent", None, name="Alice")
    stub(rows=[row(str(i), alice.email) for i in range(50)])

    rows = sync.preview(db, org, source, mapped)

    assert len(rows) == sync.PREVIEW_ROWS


def test_preview_rounds_the_way_the_column_does(
    db, org, source, mapped, stub, make_user
):
    """Preview exists to be believed. A six-place multiplier against a four-place
    column would otherwise report `1250.00000000` for a number stored as
    `1250.0000`."""
    alice = make_user("agent", None, name="Alice")
    mapped.multiplier = Decimal("1.000000")
    db.flush()
    stub(rows=[row("1", alice.email, amount="1250.00")])

    rows = sync.preview(db, org, source, mapped)

    assert str(rows[0].value) == "1250.0000"


def test_preview_shows_the_newest_rows(db, org, source, mapped, stub, make_user):
    """`fetch` yields oldest-first, so taking the first ten of a ninety-day window
    would show somebody the beginning of their history when what they want to see is
    the test event they sent thirty seconds ago."""
    alice = make_user("agent", None, name="Alice")
    stub(
        rows=[
            row(str(day), alice.email, when=f"2026-08-{day:02d}T12:00:00Z")
            for day in range(1, 16)
        ]
    )
    now = datetime(2026, 8, 16, tzinfo=UTC)

    rows = sync.preview(db, org, source, mapped, limit=3, now=now)

    assert [r.source_values["Closed"] for r in rows] == [
        "2026-08-13T12:00:00Z",
        "2026-08-14T12:00:00Z",
        "2026-08-15T12:00:00Z",
    ]


def test_preview_still_shows_rows_after_a_successful_sync(
    db, org, source, mapped, stub, make_user
):
    """Preview must not use the sync's window. That window means "what have I not
    dealt with yet", which right after a sync is nothing — so a preview built on it
    shows an empty table at exactly the moment somebody is trying to work out why
    their mapping is wrong."""
    alice = make_user("agent", None, name="Alice")
    now = datetime(2026, 8, 16, tzinfo=UTC)
    rows = [row("1", alice.email, when="2026-08-15T12:00:00Z")]
    stub(rows=rows)
    assert sync.run(db, org, source, now=now).status == "ok"

    stub(rows=rows)
    previewed = sync.preview(db, org, source, mapped, now=now + timedelta(hours=1))

    assert [r.outcome for r in previewed] == ["written"]


def test_preview_asks_over_the_backfill_window(db, org, source, mapped, stub):
    """Its own window, and the one the admin chose — not all of history, which on a
    warehouse is the difference between a button press and an incident."""
    now = datetime(2026, 8, 16, tzinfo=UTC)
    instance = stub(rows=[])

    sync.preview(db, org, source, mapped, now=now)

    assert instance.since_seen == [now - timedelta(days=90)]


def test_preview_carries_the_source_row_so_it_can_be_shown(
    db, org, source, mapped, stub, make_user
):
    alice = make_user("agent", None, name="Alice")
    stub(rows=[row("1", alice.email, amount=42)])

    rows = sync.preview(db, org, source, mapped)

    assert rows[0].source_values["Amount"] == 42


# ── Nothing is written without an id to recognise it by ──────────────────────


def test_a_row_with_no_id_anywhere_is_refused_with_the_fix_in_the_message(
    db, org, source, mapped, stub, make_user
):
    """`_upsert` can only recognise a row it has seen before by its `external_id`.
    Without one it inserts, so every re-read appends another copy of the same
    measurement — and the message has to say which column to pick."""
    alice = make_user("agent", None, name="Alice")
    # `external_id=None` from the connector *and* no column named on the mapping:
    # the position a database or REST source is in unless the mapping names a key.
    stub(rows=[connectors.SourceRow(external_id=None, values={
        "Owner": alice.email, "Amount": 100, "Closed": WHEN,
    })])

    outcome = sync.run(db, org, source)

    assert outcome.rows_written == 0
    assert outcome.rows_skipped == 1
    assert "does not say which column is the row's own id" in outcome.error
    assert facts(db) == []


def test_the_connector_s_own_id_is_used_when_the_mapping_names_none(
    db, org, source, mapped, stub, make_user
):
    """A webhook knows its own delivery id, so its sources need no id column — which
    is why this is a fallback rather than a requirement on the mapping."""
    alice = make_user("agent", None, name="Alice")
    stub(rows=[row("delivery-7", alice.email)])

    outcome = sync.run(db, org, source)

    assert outcome.rows_written == 1
    assert facts(db)[0].external_id == "delivery-7"


def test_an_id_column_that_is_empty_on_a_row_names_the_column(
    db, org, source, mapped, stub, make_user
):
    """One blank cell in the key column, which is a different problem from having
    named no column at all — and a different fix."""
    alice = make_user("agent", None, name="Alice")
    mapped.external_id_field = "Id"
    db.flush()
    stub(rows=[connectors.SourceRow(external_id=None, values={
        "Owner": alice.email, "Amount": 100, "Closed": WHEN, "Id": "",
    })])

    outcome = sync.run(db, org, source)

    assert outcome.rows_written == 0
    assert "'Id' was empty on this row" in outcome.error


def test_an_unanswered_question_cannot_inflate_a_source_with_no_ids(
    db, org, source, mapped, stub, make_user
):
    """**The regression this rule exists for, and it compounds.**

    A `partial` run does not advance the watermark — deliberately, so rows held for
    a quarantine question can be re-read once it is answered. So one unanswered
    question makes the source re-read the same window on every pass. With no
    external id, every pass appended the good rows again: an hourly source quietly
    added twenty-four phantom measurements a day to a leaderboard.

    Both halves of that were individually correct, which is why it took a probe
    rather than a test to find.
    """
    alice = make_user("agent", None, name="Alice")
    rows = [
        connectors.SourceRow(external_id=None, values={
            "Owner": alice.email, "Amount": 100, "Closed": WHEN,
        }),
        connectors.SourceRow(external_id=None, values={
            "Owner": "stranger@acme.com", "Amount": 50, "Closed": WHEN,
        }),
    ]

    for pass_number in range(4):
        stub(rows=rows)
        outcome = sync.run(
            db, org, source, now=datetime(2026, 8, 21, 12 + pass_number, tzinfo=UTC)
        )
        # The window really is pinned, which is the other half of the cause.
        assert outcome.rows_read == 2, pass_number

    assert len(facts(db)) == 0


def test_ids_still_make_a_pinned_window_harmless(
    db, org, source, mapped, stub, make_user
):
    """The other side: with ids, re-reading the same window every pass writes the
    good row once and keeps asking about the unknown one. Which is the behaviour the
    pinned window was introduced for."""
    alice = make_user("agent", None, name="Alice")
    rows = [row("known", alice.email), row("unknown", "stranger@acme.com")]

    for pass_number in range(4):
        stub(rows=rows)
        sync.run(db, org, source, now=datetime(2026, 8, 21, 12 + pass_number, tzinfo=UTC))

    assert len(facts(db)) == 1


def test_preview_reports_the_missing_id_rather_than_promising_an_import(
    db, org, source, mapped, stub, make_user
):
    """Through the same check the sync uses, so the preview cannot promise something
    that would then be refused — the whole reason preview goes through the real
    calls instead of reimplementing them."""
    alice = make_user("agent", None, name="Alice")
    stub(rows=[connectors.SourceRow(external_id=None, values={
        "Owner": alice.email, "Amount": 100, "Closed": WHEN,
    })])

    rows = sync.preview(db, org, source, mapped)

    assert [r.outcome for r in rows] == ["error"]
    assert "row's own id" in rows[0].detail


# ── Sweeping away drafts ─────────────────────────────────────────────────────


def test_an_abandoned_draft_is_swept(db, org):
    """A connect flow nobody came back to. No credentials worth keeping and nothing
    imported, so there is nothing to lose."""
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    draft = DataSource(organization_id=org.id, name="Abandoned", connector="stub")
    db.add(draft)
    db.flush()
    draft.created_at = now - timedelta(days=2)
    db.flush()

    assert sync.sweep_drafts(db, now=now) == 1
    assert db.get(DataSource, draft.id) is None


def test_a_draft_from_this_morning_is_left_alone(db, org):
    """Somebody interrupted mid-setup should be able to come back after lunch."""
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    draft = DataSource(organization_id=org.id, name="In progress", connector="stub")
    db.add(draft)
    db.flush()
    draft.created_at = now - timedelta(hours=2)
    db.flush()

    assert sync.sweep_drafts(db, now=now) == 0
    assert db.get(DataSource, draft.id) is not None


def test_a_paused_source_is_never_swept_however_old(db, org):
    """**The distinction `activated_at` exists for.** A source somebody finished and
    then paused looks exactly like a draft — no enabled mapping, possibly no
    credentials — and deleting it would be destroying their work."""
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    paused = DataSource(
        organization_id=org.id,
        name="Paused months ago",
        connector="stub",
        enabled=False,
    )
    db.add(paused)
    db.flush()
    paused.created_at = now - timedelta(days=200)
    paused.activated_at = now - timedelta(days=200)
    db.flush()

    assert sync.sweep_drafts(db, now=now) == 0
    assert db.get(DataSource, paused.id) is not None


def test_a_draft_that_somehow_imported_something_is_left_alone(
    db, org, metric, make_user
):
    """Belt and braces: the foreign key would refuse the delete anyway, but finding
    that out through an integrity error at three in the morning is worse than not
    attempting it."""
    now = datetime(2026, 8, 21, 12, tzinfo=UTC)
    alice = make_user("agent", None, name="Alice")
    draft = DataSource(organization_id=org.id, name="Odd one", connector="stub")
    db.add(draft)
    db.flush()
    draft.created_at = now - timedelta(days=2)
    db.add(
        MetricFact(
            organization_id=org.id,
            metric_definition_id=metric.id,
            subject_user_id=alice.id,
            value=Decimal(1),
            occurred_at=now,
            source_type="connector",
            data_source_id=draft.id,
            external_id="x",
        )
    )
    db.flush()

    assert sync.sweep_drafts(db, now=now) == 0
    assert db.get(DataSource, draft.id) is not None


def test_the_scheduled_pass_sweeps_after_syncing_rather_than_before(
    db, org, source, mapped, stub, make_user
):
    """A draft finished a minute ago should be synced on this pass, not swept on
    it."""
    alice = make_user("agent", None, name="Alice")
    stub(rows=[row("1", alice.email)])

    tally = sync.run_due(db)

    assert tally["written"] == 1
    assert tally["drafts_swept"] == 0


# ── Reading once ─────────────────────────────────────────────────────────────


def test_a_one_off_is_due_until_it_has_run(db, org, source, mapped, stub, make_user):
    """**The setting a first test wants.** A source otherwise starts a schedule
    the moment it is saved — free against a spreadsheet, billed by the second
    against a warehouse."""
    from app.models.data_source import READ_ONCE

    alice = make_user("agent", None, name="Alice")
    stub(rows=[row("1", alice.email)])
    source.interval_minutes = READ_ONCE
    db.flush()

    assert source.id in [s.id for s in sync.due(db)]

    sync.run(db, org, source)

    assert source.id not in [s.id for s in sync.due(db)]


def test_a_one_off_that_has_run_has_no_next_run(db, org, source, mapped, stub, make_user):
    """QA-12. It used to get "now plus zero minutes", which was in the past the
    moment it was written — so the sources list said *Late — check the
    scheduler*, Home counted it overdue, and every board it fed carried a
    stale-data warning, all about a source doing exactly what it was told."""
    from app.models.data_source import READ_ONCE

    alice = make_user("agent", None, name="Alice")
    stub(rows=[row("1", alice.email)])
    source.interval_minutes = READ_ONCE
    db.flush()

    sync.run(db, org, source)

    assert source.last_run_at is not None
    assert source.next_run_at is None


def test_a_repeating_source_is_due_again(db, org, source, mapped, stub, make_user):
    """The clause must not catch everything — it is scoped to interval 0."""
    alice = make_user("agent", None, name="Alice")
    stub(rows=[row("1", alice.email)])
    source.interval_minutes = 60
    first = datetime(2026, 8, 12, 9, 0, tzinfo=UTC)
    db.flush()

    sync.run(db, org, source, now=first)

    assert source.id in [s.id for s in sync.due(db, now=first + timedelta(hours=2))]


def test_a_one_off_still_runs_when_asked(db, org, source, mapped, stub, make_user):
    """Sync now is a manual read, not a schedule — so a finished one-off runs
    again whenever somebody presses it. That is the whole point of pairing them."""
    from app.models.data_source import READ_ONCE

    alice = make_user("agent", None, name="Alice")
    stub(rows=[row("1", alice.email)])
    source.interval_minutes = READ_ONCE
    db.flush()

    sync.run(db, org, source)
    second = sync.run(db, org, source, trigger="manual")

    assert second.status in ("ok", "partial")
    assert second.trigger == "manual"


def test_the_database_refuses_an_interval_between_one_and_four(db, org):
    """Zero means once; anything else has a floor. The constraint says so rather
    than leaving it to the API to remember."""
    from sqlalchemy.exc import IntegrityError

    db.add(
        DataSource(
            organization_id=org.id, name="Too eager", connector="stub",
            interval_minutes=2,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
