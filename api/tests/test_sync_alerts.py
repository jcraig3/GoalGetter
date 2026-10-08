"""Telling somebody when a source stops working.

**Because nothing did.** A source that started failing at three in the morning
showed a red pill on a page nobody had open, and the first anybody knew was a
leaderboard that had quietly stopped moving — which reads as "the team had a slow
week", not as "the integration is down".
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import events, sync
from app.models import DataSource, Notification, Organization, SyncRun


@pytest.fixture
def source(db, org):
    row = DataSource(organization_id=org.id, name="CRM", connector="stub")
    db.add(row)
    db.flush()
    return row


def warn(db, org: Organization, source: DataSource, *, failures: int, now=None):
    """Put the source at a failure count and run the warning."""
    source.failure_count = failures
    run = SyncRun(
        organization_id=org.id,
        data_source_id=source.id,
        started_at=now or datetime.now(UTC),
        status="failed",
        trigger="schedule",
        error="Could not reach it.",
    )
    db.add(run)
    db.flush()
    sync._warn_admins(db, org, source, run, now=now or datetime.now(UTC))
    db.flush()


def alerts(db, org) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.organization_id == org.id,
            Notification.event_key == events.SOURCE_FAILING.key,
        )
    )


def test_one_failure_tells_nobody(db, org, source, make_user):
    """**A blip is not an outage.**

    A warehouse mid-resume, a token a second from refresh, a network that
    blinked — all fail once and fix themselves. An alert per blip is an alert
    nobody reads, and then the real one arrives in a mailbox people skim.
    """
    make_user("admin")
    warn(db, org, source, failures=1)

    assert alerts(db, org) == 0


def test_three_in_a_row_reaches_the_admins(db, org, source, make_user):
    make_user("admin")
    make_user("admin")
    warn(db, org, source, failures=sync.FAILURES_BEFORE_WARNING)

    assert alerts(db, org) == 2


def test_it_says_which_source_and_why(db, org, source, make_user):
    make_user("admin")
    warn(db, org, source, failures=3)

    row = db.scalar(
        select(Notification).where(
            Notification.event_key == events.SOURCE_FAILING.key
        )
    )
    assert "CRM" in row.title
    assert "Could not reach it." in row.body
    assert row.link_url == f"/integrations/sources/{source.id}"


def test_a_source_failing_all_day_is_one_alert_a_day(db, org, source, make_user):
    """A broken thing is worth one reminder a day. One an hour is how an alert
    stops being one."""
    make_user("admin")
    morning = datetime.now(UTC).replace(hour=3, minute=0)

    for hour in range(6):
        warn(db, org, source, failures=3 + hour, now=morning + timedelta(hours=hour))

    assert alerts(db, org) == 1


def test_it_speaks_up_again_the_next_day(db, org, source, make_user):
    """Still broken tomorrow is worth saying again."""
    make_user("admin")
    today = datetime.now(UTC).replace(hour=3, minute=0)

    warn(db, org, source, failures=3, now=today)
    warn(db, org, source, failures=4, now=today + timedelta(days=1))

    assert alerts(db, org) == 2


def test_only_admins_hear_about_it(db, org, source, make_user):
    """An agent cannot fix a credential and cannot see the page that would."""
    make_user("admin")
    make_user("agent")
    make_user("manager")
    warn(db, org, source, failures=3)

    assert alerts(db, org) == 1
