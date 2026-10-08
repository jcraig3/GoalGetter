"""Withdrawing facts whose row is gone from the source.

**The one rule:** for a source read whole every time, the source is the truth. A
deal deleted from a spreadsheet stops counting; a deal moved back out of *Closed
Won* stops counting.

This deletes rows, so the guards get more tests than the feature does. Each of
the three exists because getting it wrong destroys real data rather than
displaying it wrongly:

  the connector must say it reads everything — absence only means deleted when
  presence was guaranteed;
  the pass must be clean — a truncated read or a mapping error means rows were
  not accounted for;
  a corrected fact is never touched — a human already beat the source once.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from pydantic import BaseModel

from app import connectors, sync
from app.models import DataSource, MetricFact, SourceMapping


class Blank(BaseModel):
    """Sync builds these from the stored config, so they cannot be `None`."""

WHEN = "2026-08-12T15:00:00Z"


class Sheet:
    """A connector that hands back everything, every time — like a workbook."""

    key = "sheet"
    display_name = "Sheet"
    reads_everything = True
    config_schema = Blank
    credential_schema = Blank
    setup_steps = ()

    def __init__(self, rows):
        self.rows = rows

    def test_connection(self, config, credentials):  # pragma: no cover
        return connectors.ConnectionResult(ok=True, detail="fine")

    def discover(self, config, credentials, *, local=None):  # pragma: no cover
        return []

    def fetch(self, config, credentials, since=None, *, local=None):
        yield from self.rows


class Window(Sheet):
    """The same, but reading a window — so it must never withdraw anything."""

    key = "window"
    reads_everything = False


def row(external_id, who, amount=100):
    return connectors.SourceRow(
        external_id=external_id,
        values={"Owner": who, "Amount": amount, "Closed": WHEN},
    )


@pytest.fixture
def install(registry_slot):
    def _install(connector):
        connectors._REGISTRY[connector.key] = connector
        return connector

    return _install


@pytest.fixture
def source(db, org):
    def _make(key="sheet"):
        row = DataSource(
            organization_id=org.id, name="Deals", connector=key, backfill_days=90
        )
        db.add(row)
        db.flush()
        return row

    return _make


@pytest.fixture
def mapped(db, org):
    def _make(source, metric, **overrides):
        body = dict(
            organization_id=org.id,
            data_source_id=source.id,
            metric_definition_id=metric.id,
            value_field="Amount",
            occurred_at_field="Closed",
            subject_field="Owner",
            external_id_field=None,
        )
        body.update(overrides)
        row = SourceMapping(**body)
        db.add(row)
        db.flush()
        return row

    return _make


def amounts(db):
    return sorted(
        float(f.value) for f in db.scalars(select(MetricFact)).all()
    )


# ── The rule ─────────────────────────────────────────────────────────────────


def test_a_deleted_row_takes_its_fact_with_it(
    db, org, install, source, mapped, make_metric, make_user
):
    """The headline. A deal removed from the spreadsheet stops counting."""
    alice = make_user("agent", None, name="Alice")
    sheet = install(Sheet([row("1", alice.email, 100), row("2", alice.email, 200)]))
    src, metric = source(), make_metric("revenue")
    mapped(src, metric)

    sync.run(db, org, src)
    assert amounts(db) == [100.0, 200.0]

    sheet.rows = [row("1", alice.email, 100)]
    run = sync.run(db, org, src)

    assert amounts(db) == [100.0]
    assert run.rows_removed == 1
    # Withdrawing is part of a clean run, not an error it survives.
    assert run.status == "ok", run.error


def test_a_deal_that_stops_matching_the_filter_stops_counting(
    db, org, install, source, mapped, make_metric, make_user
):
    """**The second half of the rule, and the less obvious one.** The row is
    still in the sheet — it just is not a won deal any more. Leaving the fact
    would mean a leaderboard permanently crediting a deal that fell through."""
    alice = make_user("agent", None, name="Alice")
    sheet = install(
        Sheet([
            connectors.SourceRow(
                external_id="1",
                values={
                    "Owner": alice.email,
                    "Amount": 100,
                    "Closed": WHEN,
                    "Stage": "Closed Won",
                },
            )
        ])
    )
    src, metric = source(), make_metric("revenue")
    mapped(src, metric, filters=[{"field": "Stage", "op": "eq", "value": "Closed Won"}])

    sync.run(db, org, src)
    assert amounts(db) == [100.0]

    sheet.rows[0].values["Stage"] = "Negotiation"
    run = sync.run(db, org, src)

    assert amounts(db) == []
    assert run.rows_removed == 1


def test_an_unchanged_sheet_withdraws_nothing(
    db, org, install, source, mapped, make_metric, make_user
):
    """A row confirmed unchanged is not a write — and must still count as one the
    pass stood behind, or a quiet source would delete itself."""
    alice = make_user("agent", None, name="Alice")
    install(Sheet([row("1", alice.email, 100)]))
    src, metric = source(), make_metric("revenue")
    mapped(src, metric)

    sync.run(db, org, src)
    run = sync.run(db, org, src)

    assert amounts(db) == [100.0]
    assert run.rows_removed == 0


# ── The guards ───────────────────────────────────────────────────────────────


def test_a_windowed_connector_never_withdraws(
    db, org, install, source, mapped, make_metric, make_user
):
    """**The guard that matters most.** A source reading the last 90 days would
    otherwise delete every fact older than its window on every single pass."""
    alice = make_user("agent", None, name="Alice")
    sheet = install(Window([row("1", alice.email, 100), row("2", alice.email, 200)]))
    src, metric = source("window"), make_metric("revenue")
    mapped(src, metric)

    sync.run(db, org, src)
    sheet.rows = [row("1", alice.email, 100)]
    run = sync.run(db, org, src)

    assert amounts(db) == [100.0, 200.0]
    assert run.rows_removed == 0


def test_a_corrected_fact_survives(
    db, org, install, source, mapped, make_metric, make_user
):
    """A human already beat the source once in `_upsert`. Tidying a spreadsheet
    must not undo somebody's correction."""
    alice = make_user("agent", None, name="Alice")
    sheet = install(Sheet([row("1", alice.email, 100)]))
    src, metric = source(), make_metric("revenue")
    mapped(src, metric)

    sync.run(db, org, src)
    fact = db.scalars(select(MetricFact)).one()
    fact.corrected_at = datetime.now(UTC)
    db.flush()

    sheet.rows = []
    run = sync.run(db, org, src)

    assert amounts(db) == [100.0]
    assert run.rows_removed == 0


def test_a_mapping_error_stops_the_withdrawal(
    db, org, install, source, mapped, make_metric, make_user
):
    """A row that could not be read was not accounted for, so its absence from
    the kept set is ignorance rather than deletion. Withdrawing on that basis
    would destroy real facts over a typo in a column name."""
    alice = make_user("agent", None, name="Alice")
    sheet = install(Sheet([row("1", alice.email, 100), row("2", alice.email, 200)]))
    src, metric = source(), make_metric("revenue")
    m = mapped(src, metric)

    sync.run(db, org, src)
    assert amounts(db) == [100.0, 200.0]

    # The column disappears — which is what a renamed header looks like.
    m.value_field = "Nope"
    sheet.rows = [row("1", alice.email, 100)]
    run = sync.run(db, org, src)

    assert amounts(db) == [100.0, 200.0]
    assert run.rows_removed == 0


def test_another_sources_facts_are_never_touched(
    db, org, install, source, mapped, make_metric, make_user
):
    """Scoped by `data_source_id`, so two sheets feeding one metric do not
    withdraw each other's rows."""
    alice = make_user("agent", None, name="Alice")
    first = install(Sheet([row("1", alice.email, 100)]))
    metric = make_metric("revenue")
    one = source()
    mapped(one, metric)
    sync.run(db, org, one)

    class Second(Sheet):
        key = "sheet2"

    second = install(Second([row("9", alice.email, 900)]))
    two = source("sheet2")
    mapped(two, metric)
    sync.run(db, org, two)
    assert amounts(db) == [100.0, 900.0]

    # The first sheet empties. Only its own fact goes.
    first.rows = []
    second.rows = [row("9", alice.email, 900)]
    sync.run(db, org, one)

    assert amounts(db) == [900.0]
