"""One pass over a directory: read it, reconcile it, apply what was approved.

The parts are tested on their own elsewhere. What is left here is the wiring, and
the two things about it that could lose people:

* **a failed read reconciles nothing** — a partial list would archive everybody
  missing from it, and half a directory looks exactly like half the company leaving;
* **one person's problem does not stop everybody else's account being created.**
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.crypto import encrypt
from app.directory import sync as directory_sync
from app.directory.microsoft import DirectoryProblem
from app.directory.rules import Person
from app.models import DirectoryPerson, DirectoryRule, DirectoryRun, OauthClient, UserAccount

NOW = datetime(2026, 8, 26, 12, tzinfo=UTC)


@pytest.fixture
def connection(db, org):
    row = OauthClient(
        organization_id=org.id,
        provider="microsoft",
        client_id="client",
        client_secret_encrypted=encrypt("shhh"),
        tenant_id="contoso.onmicrosoft.com",
        directory_sync_enabled=True,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture
def reader(monkeypatch):
    """Stand in for Graph. The provider is tested against a fake tenant elsewhere."""

    def _install(people=None, explode=None):
        def read(db, connection):
            if explode:
                raise explode
            return list(people or [])

        monkeypatch.setitem(directory_sync.READERS, "microsoft", read)
        return read

    return _install


def person(external_id="e1", **kwargs):
    defaults = dict(
        email=f"{external_id}@acme.com",
        display_name="Sam Rivera",
        department="Sales",
        job_title="Account Executive",
        office_location="Phoenix",
    )
    defaults.update(kwargs)
    return Person(external_id=external_id, **defaults)


def rows(db, org):
    return {
        row.external_id: row
        for row in db.query(DirectoryPerson).filter_by(organization_id=org.id).all()
    }


# ── A whole pass ─────────────────────────────────────────────────────────────


def test_a_pass_reads_reconciles_and_records(db, org, connection, reader):
    reader([person("e1"), person("e2")])

    run = directory_sync.run(db, connection, now=NOW)

    assert run.status == "ok"
    assert run.people_seen == 2
    assert run.created == 2
    assert run.pending == 2
    assert len(rows(db, org)) == 2


def test_nobody_becomes_an_account_without_being_approved(db, org, connection, reader):
    """The whole design in one assertion. A pass over a two-hundred-person tenant
    creates two hundred *proposals* and zero accounts."""
    reader([person()])

    directory_sync.run(db, connection, now=NOW)

    assert db.query(UserAccount).filter_by(organization_id=org.id).count() == 0


def test_an_approved_person_becomes_an_account_on_the_next_pass(
    db, org, connection, reader
):
    """**Applying runs every pass, not only at the moment of approval.** Somebody
    approved before the rules were written has to become an account eventually
    without an admin pressing anything a second time."""
    reader([person()])
    directory_sync.run(db, connection, now=NOW)
    rows(db, org)["e1"].status = "approved"
    db.flush()

    run = directory_sync.run(db, connection, now=NOW + timedelta(days=1))

    assert run.applied == 1
    account = db.query(UserAccount).filter_by(organization_id=org.id).one()
    assert account.email == "e1@acme.com"


def test_somebody_already_given_an_account_is_not_applied_again(
    db, org, connection, reader
):
    """`applied` means *accounts created this pass*. Re-counting everybody every
    day would make a settled company report its whole staff as newly applied for
    ever, and the number would stop meaning anything."""
    reader([person()])
    directory_sync.run(db, connection, now=NOW)
    rows(db, org)["e1"].status = "approved"
    db.flush()
    directory_sync.run(db, connection, now=NOW + timedelta(days=1))

    third = directory_sync.run(db, connection, now=NOW + timedelta(days=2))

    assert third.applied == 0
    assert db.query(UserAccount).filter_by(organization_id=org.id).count() == 1


def test_the_rules_are_read_from_the_database_and_used(db, org, connection, reader, make_team):
    sales = make_team("Sales")
    db.add(
        DirectoryRule(
            organization_id=org.id, department="Sales", role="manager", team_id=sales.id
        )
    )
    reader([person()])
    directory_sync.run(db, connection, now=NOW)
    rows(db, org)["e1"].status = "approved"
    db.flush()

    directory_sync.run(db, connection, now=NOW + timedelta(days=1))

    account = db.query(UserAccount).filter_by(organization_id=org.id).one()
    assert account.org_role == "manager"
    assert account.team_id == sales.id


# ── When the read fails ──────────────────────────────────────────────────────


def test_a_failed_read_reconciles_nothing_at_all(db, org, connection, reader):
    """**The most dangerous thing this module could do.** Reconcile archives
    anybody absent, so acting on a partial or empty read would look exactly like
    the whole company leaving."""
    reader([person("e1"), person("e2")])
    directory_sync.run(db, connection, now=NOW)

    reader(explode=DirectoryProblem("Microsoft refused the connection (401)."))
    run = directory_sync.run(db, connection, now=NOW + timedelta(days=1))

    assert run.status == "failed"
    assert all(row.status == "pending" for row in rows(db, org).values())


def test_a_failed_read_says_what_the_provider_said_and_nothing_else(
    db, org, connection, reader
):
    """Microsoft's own words about a bad secret are more useful than anything we
    would write in their place — and they are passed through *whole*, not prefixed
    with a class name an admin cannot act on.

    Asserted as an exact match: `"401" in run.error` passed just as happily when
    the message was `DirectoryProblem: Microsoft refused...`, so it could not tell
    the two apart.
    """
    reader(explode=DirectoryProblem("Microsoft refused the connection (401)."))

    run = directory_sync.run(db, connection, now=NOW)

    assert run.error == "Microsoft refused the connection (401)."


def test_an_unexpected_failure_is_recorded_rather_than_escaping(
    db, org, connection, reader
):
    """A broken directory must not stop goals spawning or metrics syncing in the
    same pass — they run under one scheduler tick."""
    reader(explode=RuntimeError("something odd"))

    run = directory_sync.run(db, connection, now=NOW)

    assert run.status == "failed"
    assert "RuntimeError" in run.error


def test_a_provider_this_build_cannot_read_is_reported_not_crashed(
    db, org, connection, reader
):
    """A connection saved by a newer version, or a provider deliberately removed."""
    connection.provider = "workday"

    run = directory_sync.run(db, connection, now=NOW)

    assert run.status == "failed"
    assert "workday" in run.error


# ── One person's problem ─────────────────────────────────────────────────────


def test_somebody_who_cannot_have_an_account_does_not_block_the_others(
    db, org, connection, reader
):
    """Reported per person, like a mapping error on the metric side."""
    reader([person("e1"), person("e2", email="")])
    directory_sync.run(db, connection, now=NOW)
    for row in rows(db, org).values():
        row.status = "approved"
    db.flush()

    run = directory_sync.run(db, connection, now=NOW + timedelta(days=1))

    assert run.applied == 1
    assert run.status == "partial"
    assert "email" in run.error
    assert db.query(UserAccount).filter_by(organization_id=org.id).count() == 1


# ── Scheduling ───────────────────────────────────────────────────────────────


def test_a_connection_with_the_switch_off_is_never_read(db, org, connection):
    """**Connecting Excel must not propose two hundred accounts.** This is the one
    capability that is stored rather than derived, precisely because nothing else
    could tell us whether a company wants it."""
    connection.directory_sync_enabled = False
    db.flush()

    assert directory_sync.due(db, now=NOW) == []


def test_a_connection_never_read_is_due_immediately(db, org, connection):
    assert directory_sync.due(db, now=NOW) == [connection]


def test_a_directory_read_an_hour_ago_is_not_due_again(db, org, connection, reader):
    """Daily, not hourly. People join and leave on a scale of days, and reading
    somebody else's API twenty-four times to notice one joiner is how an
    integration gets switched off at the far end."""
    reader([])
    directory_sync.run(db, connection, now=NOW)

    assert directory_sync.due(db, now=NOW + timedelta(hours=1)) == []


def test_a_directory_read_yesterday_is_due(db, org, connection, reader):
    reader([])
    directory_sync.run(db, connection, now=NOW)

    assert directory_sync.due(db, now=NOW + timedelta(hours=25)) == [connection]


def test_a_failed_run_still_counts_as_an_attempt(db, org, connection, reader):
    """Otherwise a bad credential would be retried every scheduler tick, which is
    how an authentication endpoint gets an account locked."""
    reader(explode=DirectoryProblem("nope"))
    directory_sync.run(db, connection, now=NOW)

    assert directory_sync.due(db, now=NOW + timedelta(hours=1)) == []


def test_a_provider_with_no_reader_is_never_due(db, org, connection):
    connection.provider = "workday"
    db.flush()

    assert directory_sync.due(db, now=NOW) == []


def test_run_due_reports_what_it_did(db, org, connection, reader):
    reader([person("e1"), person("e2")])

    counted = directory_sync.run_due(db, now=NOW)

    assert counted["directories"] == 1
    assert counted["people"] == 2
    assert counted["created"] == 2
    assert counted["failed"] == 0


def test_run_due_counts_a_failure_without_stopping(db, org, connection, reader):
    reader(explode=DirectoryProblem("nope"))

    counted = directory_sync.run_due(db, now=NOW)

    assert counted["failed"] == 1
    assert db.query(DirectoryRun).filter_by(organization_id=org.id).count() == 1


# ── How often ────────────────────────────────────────────────────────────────
#
# Per connection since 3d shipped, because the two ends of the range are both
# real: a company onboarding a cohort every morning wants hourly, and one that
# hires twice a year does not want its tenant read every day to notice.


def _ran_at(db, org, when, provider="microsoft"):
    db.add(
        DirectoryRun(
            organization_id=org.id,
            provider=provider,
            trigger="schedule",
            status="ok",
            started_at=when,
            people_seen=0,
            created=0,
            archived=0,
            needs_review=0,
            pending=0,
            applied=0,
        )
    )
    db.flush()


def test_an_hourly_connection_is_due_an_hour_later(db, org, connection):
    """The whole point of making it configurable: daily is the default, not the
    rule."""
    connection.directory_sync_hours = 1
    _ran_at(db, org, NOW - timedelta(hours=2))

    assert directory_sync.due(db, now=NOW) == [connection]


def test_an_hourly_connection_is_not_due_ten_minutes_later(db, org, connection):
    connection.directory_sync_hours = 1
    _ran_at(db, org, NOW - timedelta(minutes=10))

    assert directory_sync.due(db, now=NOW) == []


def test_a_weekly_connection_is_left_alone_the_next_day(db, org, connection):
    """**The half a hardcoded daily interval got wrong.** A tenant is somebody
    else's API quota, and reading it seven times to notice one joiner is how an
    integration gets switched off at the far end."""
    connection.directory_sync_hours = 168
    _ran_at(db, org, NOW - timedelta(days=1))

    assert directory_sync.due(db, now=NOW) == []


def test_a_nonsense_interval_falls_back_to_daily(db, org, connection):
    """Clamped rather than trusted. The endpoint bounds what it writes, but a zero
    edited straight into the database would mean "read the directory on every tick
    of the job loop" — against somebody else's API, which is the one failure here
    that costs another company money."""
    connection.directory_sync_hours = 0
    _ran_at(db, org, NOW - timedelta(hours=2))

    assert directory_sync.due(db, now=NOW) == []
    assert directory_sync.interval_of(connection) == directory_sync.INTERVAL


def test_an_absurdly_long_interval_also_falls_back(db, org, connection):
    connection.directory_sync_hours = 100_000

    assert directory_sync.interval_of(connection) == directory_sync.INTERVAL


def test_a_never_synced_connection_is_due_whatever_the_interval(db, org, connection):
    """No run recorded means nothing to measure from, and waiting a week before the
    first read would look exactly like the switch not working."""
    connection.directory_sync_hours = 168

    assert directory_sync.due(db, now=NOW) == [connection]
