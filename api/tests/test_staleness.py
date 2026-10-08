"""When the numbers have stopped arriving (7.3): one story, told the same on
the source card, in the Inbox and on Home."""

from datetime import UTC, datetime, timedelta

import pytest

from app import staleness
from app.models import DataSource, MetricFact

#: Gaps of a day or more than a week, so the working-day arithmetic (the
#: module's, tested on its own below) is never on a knife edge.
NOW = datetime.now(UTC)


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    team = make_team("Sales")
    other = make_team("Other")
    return {
        "team": team,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", team, name="Mona"),
        "ann": make_user("agent", team, name="Ann"),
        "far": make_user("agent", other, name="Far"),
        "loner": make_user("agent", None, name="Loner"),
        "metric": make_metric("deals"),
    }


def source(db, org, **kwargs):
    fields = {
        "organization_id": org.id,
        "name": "Closed Deals sheet",
        "connector": "webhook",
        "activated_at": NOW - timedelta(days=60),
        "last_status": "ok",
        "interval_minutes": 60,
        **kwargs,
    }
    row = DataSource(**fields)
    db.add(row)
    db.flush()
    return row


def row(db, org, world, src, when):
    fact = MetricFact(
        organization_id=org.id,
        metric_definition_id=world["metric"].id,
        subject_user_id=world["ann"].id,
        value=1,
        occurred_at=when,
        source_type="connector",
        data_source_id=src.id,
    )
    db.add(fact)
    db.flush()
    return fact


def test_a_source_quiet_for_over_a_week_is_stale(db, org, world):
    src = source(db, org)
    row(db, org, world, src, NOW - timedelta(days=9))
    found = staleness.quiet_sources(db, org, NOW)
    assert [q.source.name for q in found] == ["Closed Deals sheet"]
    assert found[0].working_days >= staleness.STALE_WORKING_DAYS


def test_yesterday_is_not_stale(db, org, world):
    src = source(db, org)
    row(db, org, world, src, NOW - timedelta(days=1))
    assert staleness.quiet_sources(db, org, NOW) == []


def test_a_weekend_is_not_a_quiet_spell():
    """Friday's numbers read on Monday: no working day has gone by without."""
    from app.models import Organization

    org = Organization(name="t", timezone="UTC", week_starts_on=1, fiscal_year_start_month=1)
    friday = datetime(2026, 10, 2, 15, tzinfo=UTC)
    monday = datetime(2026, 10, 5, 10, tzinfo=UTC)
    assert staleness.quiet_days(org, friday, monday) == 0


def test_paused_failing_and_read_once_sources_are_not_watched(db, org, world):
    for kwargs in ({"enabled": False}, {"last_status": "failed"}, {"interval_minutes": 0}):
        src = source(db, org, name=str(kwargs), **kwargs)
        row(db, org, world, src, NOW - timedelta(days=20))
    assert staleness.quiet_sources(db, org, NOW) == []


def test_the_card_says_when_the_newest_row_was(client, db, org, world, sign_in):
    src = source(db, org)
    row(db, org, world, src, NOW - timedelta(days=9))
    sign_in(world["admin"])
    listed = next(s for s in client.get("/api/data-sources").json() if s["id"] == src.id)
    assert listed["newest_row_at"] is not None
    assert listed["stale_working_days"] >= staleness.STALE_WORKING_DAYS


def test_the_inbox_says_it(client, db, org, world, sign_in):
    src = source(db, org)
    row(db, org, world, src, NOW - timedelta(days=9))
    sign_in(world["admin"])
    items = client.get("/api/inbox").json()["items"]
    quiet = [i for i in items if i["kind"] == "source_quiet"]
    assert len(quiet) == 1
    assert quiet[0]["title"].startswith("No new numbers from Closed Deals sheet since ")
    assert quiet[0]["link"] == f"/integrations/sources/{src.id}"


def test_home_names_the_data_not_the_people(client, db, org, world, sign_in):
    """"400 people have recorded nothing" blamed the floor for a sheet that
    stopped being updated (Q2-5)."""
    src = source(db, org)
    row(db, org, world, src, NOW - timedelta(days=9))
    sign_in(world["admin"])
    attention = client.get("/api/dashboard").json()["attention"]
    kinds = [a["kind"] for a in attention]
    assert "data_stale" in kinds and "quiet_people" not in kinds
    stale = next(a for a in attention if a["kind"] == "data_stale")
    assert stale["message"].startswith("No new numbers since ")
    assert "Closed Deals sheet" in stale["message"]
    assert stale["link"] == f"/integrations/sources/{src.id}"

    # A manager is told too, with nowhere to be sent — the fix is an admin's.
    sign_in(world["manager"])
    manager = next(a for a in client.get("/api/dashboard").json()["attention"] if a["kind"] == "data_stale")
    assert manager["link"] == ""


def test_a_managers_quiet_count_is_their_own_team(client, db, org, world, sign_in):
    """Their scope takes in every agent on no team too, which made the banner
    say 413 to a manager of 93 (7.1)."""
    sign_in(world["manager"])
    attention = client.get("/api/dashboard").json()["attention"]
    quiet = next(a for a in attention if a["kind"] == "quiet_people")
    # Ann, on Mona's team — not the loner on no team, nor Far on another.
    assert quiet["count"] == 1


def test_a_source_named_by_its_key_is_called_what_the_page_calls_it(db, org, world):
    """"No new numbers from microsoft_excel" said the stored key aloud."""
    from app import connectors

    src = source(db, org, name="webhook")
    assert staleness.name_of(src) == connectors.get("webhook").display_name
    assert staleness.name_of(source(db, org, name="Closed Deals sheet")) == "Closed Deals sheet"


def test_system_health_says_each_source_and_its_newest_row(db, org, world):
    """P3-3: "Data last recorded 11 days ago" was a third date beside the
    banner's. Health now says it by source, in the banner's words."""
    from datetime import UTC, datetime

    from app import dashboard
    from app.models.data_source import READ_ONCE

    quiet = source(db, org, name="Excel")
    row(db, org, world, quiet, datetime.now(UTC) - timedelta(days=12))
    once = source(db, org, name="Snowflake", interval_minutes=READ_ONCE)
    row(db, org, world, once, datetime.now(UTC) - timedelta(days=2))

    found = {s["name"]: s for s in dashboard.health(db, org).sources}

    assert found["Excel"]["quiet"] is True and found["Excel"]["read_once"] is False
    assert found["Snowflake"]["read_once"] is True and found["Snowflake"]["quiet"] is False
    assert found["Excel"]["newest"]  # "Wed 23 Sep", in the org's time
