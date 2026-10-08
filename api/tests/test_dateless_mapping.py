"""A source that cannot say when anything happened.

**The shape every leaderboard tool before this one asks for.** Spinify's SQL
integration takes two columns, Email and Score, and runs every fifteen minutes —
no date anywhere. So a warehouse that has fed one of those holds views shaped
exactly that way: one row per person, a number that moves.

Refusing them meant telling somebody to write SQL that invents a date. The rule
instead is that a fact with no date column is **dated by when its number last
changed**, which covers both shapes without asking anybody which one they have:

* a deal row, written once and never touched, keeps the day it first arrived;
* a running total moves to today when it changes, and stays there when re-read.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app import sync
from app.models import MetricFact


@pytest.fixture
def dateless(db, org, make_metric, make_user):
    """A source whose mapping has no date column."""
    from app.models import DataSource

    metric = make_metric("sales_today")
    source = DataSource(organization_id=org.id, name="Totals", connector="stub")
    db.add(source)
    db.flush()
    user = make_user("agent")
    mapping = sync_mapping(db, org, source, metric)
    return source, metric, user, mapping


def sync_mapping(db, org, source, metric):
    from app.models import SourceMapping

    row = SourceMapping(
        organization_id=org.id,
        data_source_id=source.id,
        metric_definition_id=metric.id,
        subject_field="email",
        occurred_at_field=None,
        external_id_field="email",
        value_field="score",
        multiplier=1,
        filters=[],
    )
    db.add(row)
    db.flush()
    return row


def facts(db, org):
    from sqlalchemy import select

    return list(db.scalars(select(MetricFact).where(MetricFact.organization_id == org.id)))


def read(db, org, source, mapping, metric, values, *, now):
    """One row through the real write path."""
    import app.connectors as connectors
    from app.models import SyncRun

    run = SyncRun(
        organization_id=org.id,
        data_source_id=source.id,
        started_at=now,
        status="ok",
        trigger="schedule",
    )
    db.add(run)
    db.flush()
    sync._apply(
        db,
        org,
        source,
        mapping,
        metric,
        connectors.SourceRow(values=values, external_id=None),
        run,
        now=now,
    )
    db.flush()
    return run


def test_a_row_is_dated_the_day_it_first_arrived(db, org, dateless):
    """The best anybody can do from a source that does not say."""
    source, metric, user, mapping = dateless
    EMAIL = user.email
    monday = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)

    read(db, org, source, mapping, metric, {"email": EMAIL, "score": 1}, now=monday)

    [fact] = facts(db, org)
    assert fact.occurred_at == monday
    assert fact.value == 1


def test_a_number_that_changes_moves_to_the_day_it_changed(db, org, dateless):
    """`sales_today` going 1 → 2 is still today, and says so."""
    source, metric, user, mapping = dateless
    EMAIL = user.email
    morning = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
    afternoon = datetime(2026, 3, 2, 16, 0, tzinfo=UTC)

    read(db, org, source, mapping, metric, {"email": EMAIL, "score": 1}, now=morning)
    read(db, org, source, mapping, metric, {"email": EMAIL, "score": 2}, now=afternoon)

    [fact] = facts(db, org)
    assert fact.value == 2
    assert fact.occurred_at == afternoon


def test_re_reading_an_unchanged_row_does_not_drag_its_date_forward(db, org, dateless):
    """**The rule that makes periods keep working.**

    Dating by "the time of the last read" would pull every fact forward on every
    sync, so nothing would ever age out and somebody who stopped selling in March
    would still be on April's leaderboard.
    """
    source, metric, user, mapping = dateless
    EMAIL = user.email
    march = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
    april = march + timedelta(days=40)

    read(db, org, source, mapping, metric, {"email": EMAIL, "score": 3}, now=march)
    run = read(db, org, source, mapping, metric, {"email": EMAIL, "score": 3}, now=april)

    [fact] = facts(db, org)
    assert fact.occurred_at == march
    # And it was not counted as a write, because nothing was written.
    assert run.rows_written == 0


def test_a_date_column_still_wins_when_there_is_one(db, org, dateless, make_metric):
    """Nothing about the normal path changes."""
    source, metric, user, mapping = dateless
    EMAIL = user.email
    mapping.occurred_at_field = "closed_on"
    db.flush()
    now = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)

    read(
        db, org, source, mapping, metric,
        {"email": EMAIL, "score": 1, "closed_on": "2026-01-15"},
        now=now,
    )

    [fact] = facts(db, org)
    assert fact.occurred_at.date() == datetime(2026, 1, 15).date()


# ── A dateless mapping has to be able to find its own facts ──────────────────


def test_a_dateless_mapping_without_a_row_id_is_refused(client, db, org, sign_in, make_user, make_metric):
    """**Not a style rule — the dating depends on it.**

    With no date, a fact is dated by when its number last changed, which means
    finding the fact written last time and comparing. Without a row id there is
    nothing to find it by, so every read inserts a new one: the totals multiply
    and the date is always the day of the read.
    """
    from app.models import DataSource

    sign_in(make_user("admin"))
    metric = make_metric("sales")
    source = DataSource(organization_id=org.id, name="Totals", connector="stub")
    db.add(source)
    db.flush()
    db.commit()

    reply = client.post(
        f"/api/data-sources/{source.id}/mappings",
        json={
            "metric_id": metric.id,
            "subject_field": "email",
            "occurred_at_field": None,
            "external_id_field": None,
            "value_field": "score",
        },
    )

    assert reply.status_code == 422
    assert "identifies each row" in str(reply.json())


def test_a_dateless_mapping_with_a_row_id_is_accepted(client, db, org, sign_in, make_user, make_metric):
    """The shape that actually works, and it must not be blocked."""
    from app.models import DataSource

    sign_in(make_user("admin"))
    metric = make_metric("sales")
    source = DataSource(organization_id=org.id, name="Totals", connector="stub")
    db.add(source)
    db.flush()
    db.commit()

    reply = client.post(
        f"/api/data-sources/{source.id}/mappings",
        json={
            "metric_id": metric.id,
            "subject_field": "email",
            "occurred_at_field": None,
            "external_id_field": "email",
            "value_field": "score",
        },
    )

    assert reply.status_code in (200, 201)


# ── Keeping a day's figure before it is overwritten ──────────────────────────


def test_without_snapshotting_yesterday_is_lost(db, org, dateless):
    """**The limitation this exists to remove.**

    `sales_today` is 3 this afternoon and 1 tomorrow morning. One fact per
    person means tomorrow's read overwrites today's, and the week is
    unrecoverable — every leaderboard can only ever show the current figure.
    """
    source, metric, user, mapping = dateless
    EMAIL = user.email
    today = datetime(2026, 3, 2, 17, 0, tzinfo=UTC)
    tomorrow = datetime(2026, 3, 3, 9, 0, tzinfo=UTC)

    read(db, org, source, mapping, metric, {"email": EMAIL, "score": 3}, now=today)
    read(db, org, source, mapping, metric, {"email": EMAIL, "score": 1}, now=tomorrow)

    rows = facts(db, org)
    assert len(rows) == 1
    assert rows[0].value == 1  # Monday's 3 is gone.


def test_snapshotting_keeps_a_fact_per_day(db, org, dateless):
    """A week becomes the sum of seven, from a source that has no dates at all."""
    source, metric, user, mapping = dateless
    EMAIL = user.email
    mapping.snapshot_daily = True
    db.flush()
    today = datetime(2026, 3, 2, 17, 0, tzinfo=UTC)
    tomorrow = datetime(2026, 3, 3, 9, 0, tzinfo=UTC)

    read(db, org, source, mapping, metric, {"email": EMAIL, "score": 3}, now=today)
    read(db, org, source, mapping, metric, {"email": EMAIL, "score": 1}, now=tomorrow)

    rows = sorted(facts(db, org), key=lambda f: f.occurred_at)
    assert [f.value for f in rows] == [3, 1]
    assert rows[0].occurred_at.date() == today.date()
    assert rows[1].occurred_at.date() == tomorrow.date()


def test_snapshotting_still_updates_within_the_same_day(db, org, dateless):
    """Two reads on one day are one fact, or a leaderboard counts the morning
    and the afternoon as two separate days of work."""
    source, metric, user, mapping = dateless
    EMAIL = user.email
    mapping.snapshot_daily = True
    db.flush()
    morning = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
    afternoon = datetime(2026, 3, 2, 17, 0, tzinfo=UTC)

    read(db, org, source, mapping, metric, {"email": EMAIL, "score": 1}, now=morning)
    read(db, org, source, mapping, metric, {"email": EMAIL, "score": 5}, now=afternoon)

    rows = facts(db, org)
    assert len(rows) == 1
    assert rows[0].value == 5


def test_snapshotting_is_off_unless_asked_for(db, org, dateless):
    """**For a row-per-event source it would be actively wrong**: a deal keyed by
    deal id plus the date becomes a new deal every day, and one sale turns into
    thirty. Nothing in the data tells the two shapes apart reliably."""
    source, metric, user, mapping = dateless

    assert mapping.snapshot_daily is False
