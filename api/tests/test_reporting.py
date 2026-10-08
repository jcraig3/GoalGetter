"""The reporting tab.

Almost none of the arithmetic here is new — `pace.py` already knew whether a
goal was behind, and `goals.py` already knew what it had reached. What these
tests guard is the sentence at the end of it, and it is a different kind of
claim from "the number is right":

    a progress bar    where somebody is
    a pace marker     where somebody should be
    a coaching gap    what closing it would take

Only the third can be handed to a person, so the properties worth testing are
the ones that decide whether a manager can act on what they read: that a gap
names who it is about, that a rate is one somebody could actually work to, and
that a comparison puts like next to like.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app import competitions, reporting
from app.models import Competition, CompetitionParticipant, Goal
from tests.conftest import org_now, org_today, within_this_month

WHEN = within_this_month()


def eighty_percent_through() -> datetime:
    """A moment most of the way through the current month.

    Passed as `now` rather than left to the clock. **A test that asserts
    "behind" is a test about elapsed time**, and run on the first of the month
    there is none — every goal would come back `not_started` and the suite
    would fail on a date rather than on a change. The offset from the period is
    the thing being fixed, not the date.
    """
    # The organization's month — UTC's is a different one for a few hours
    # at the turn of every month. See `tests.conftest.org_now`.
    start = org_now().replace(
        day=1, hour=12, minute=0, second=0, microsecond=0
    )
    end = (start + timedelta(days=32)).replace(day=1)
    return start + (end - start) * 0.8


def months_back(count: int) -> datetime:
    """Midday in the middle of a month `count` months ago."""
    when = org_now().replace(day=15, hour=12, minute=0, second=0, microsecond=0)
    for _ in range(count):
        when = (when.replace(day=1) - timedelta(days=5)).replace(day=15, hour=12)
    return when


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    db.flush()
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", smb, name="Clark Kent"),
        "metric": make_metric("calls_made"),
    }


def make_goal(db, org, world, **overrides):
    fields = {
        "organization_id": org.id,
        "metric_definition_id": world["metric"].id,
        "subject_type": "user",
        "subject_user_id": world["peter"].id,
        "target_value": Decimal("100"),
        "period_type": "month",
        "period_anchor": org_today(),
    }
    fields.update(overrides)
    goal = Goal(**fields)
    db.add(goal)
    db.flush()
    return goal


def look(db, org, world, who="admin"):
    return reporting.overview(db, org, world[who], now=eighty_percent_through())


# -- The overview ------------------------------------------------------------


def test_a_goal_well_short_of_the_line_is_behind(db, org, world, make_fact):
    make_fact(world["metric"], world["peter"], 10, WHEN)
    make_goal(db, org, world)

    result = look(db, org, world)

    assert (result.total, result.behind) == (1, 1)


def test_a_goal_already_met_counts_as_on_pace(db, org, world, make_fact):
    """**Hit counts as on pace.** A finished goal is not a worry, and a page
    reporting 0% while the target was met last week would be reporting on its
    own arithmetic rather than on the team."""
    make_fact(world["metric"], world["peter"], 200, WHEN)
    make_goal(db, org, world)

    result = look(db, org, world)

    assert (result.hit, result.on_pace_percent) == (1, 100.0)


def test_nothing_visible_is_not_a_hundred_percent(db, org, world):
    """Zero of zero is 0, not 100 — a page claiming everybody is on pace
    because there are no goals is worse than an empty one."""
    assert look(db, org, world).on_pace_percent == 0.0


def test_a_goal_whose_period_has_not_started_is_left_out(db, org, world):
    make_goal(db, org, world, period_anchor=org_today() + timedelta(days=90))

    assert look(db, org, world).total == 0


def test_a_gap_says_who_it_is_about(db, org, world, make_fact):
    """**A gap with no name on it is not a coaching gap**, it is a statistic."""
    make_fact(world["metric"], world["peter"], 10, WHEN)
    make_goal(db, org, world)

    assert look(db, org, world).gaps[0].subject_name == "Peter Parker"


def test_a_team_gap_names_the_team(db, org, world, make_fact):
    make_fact(world["metric"], world["peter"], 10, WHEN)
    make_goal(
        db, org, world,
        subject_type="team", subject_user_id=None,
        subject_team_id=world["enterprise"].id,
    )

    assert look(db, org, world).gaps[0].subject_name == "Enterprise"


def test_an_organization_gap_names_the_company(db, org, world, make_fact):
    make_fact(world["metric"], world["peter"], 10, WHEN)
    make_goal(db, org, world, subject_type="organization", subject_user_id=None)

    assert look(db, org, world).gaps[0].subject_name == org.name


def test_the_rate_needed_is_per_working_day(db, org, world, make_fact):
    """**Per working day, not per calendar day.** "Twelve a day" over a
    fortnight containing two weekends is a target somebody would miss by a
    third while doing exactly what they were told."""
    make_fact(world["metric"], world["peter"], 10, WHEN)
    make_goal(db, org, world)

    gap = look(db, org, world).gaps[0]

    assert gap.rate_needed == (Decimal(90) / gap.days_left).quantize(Decimal("0.1"))


def test_the_last_day_still_has_a_day_left(db, org, world, make_fact):
    """A gap reading "0 days left" at nine in the morning is wrong in the
    discouraging direction, and divides by zero on the way."""
    make_fact(world["metric"], world["peter"], 10, WHEN)
    make_goal(db, org, world)

    end = org_now().replace(day=28, hour=9, minute=0, microsecond=0)
    result = reporting.overview(db, org, world["admin"], now=end)

    assert all(gap.days_left >= 1 for gap in result.gaps)


def test_a_metric_that_does_not_accumulate_offers_no_rate(
    db, org, world, make_metric, make_fact
):
    """An average response time is not something you do eighteen of a day."""
    speed = make_metric("response_time", aggregation="avg", direction="lower_is_better")
    make_fact(speed, world["peter"], 300, WHEN)
    make_goal(db, org, world, metric_definition_id=speed.id, target_value=Decimal("60"))

    result = look(db, org, world)

    assert all(gap.rate_needed is None for gap in result.gaps)


def test_the_worst_gaps_come_first(db, org, world, make_fact, make_metric):
    """Because the list is cut, and a cut list has to be the ones that
    matter."""
    bad = make_metric("bad")
    make_fact(world["metric"], world["peter"], 40, WHEN)
    make_fact(bad, world["peter"], 1, WHEN)
    make_goal(db, org, world)
    make_goal(db, org, world, metric_definition_id=bad.id)

    gaps = look(db, org, world).gaps

    assert [gap.metric_name for gap in gaps] == ["Bad", "Calls Made"]


def test_the_list_is_capped(db, org, world, make_metric, make_fact, monkeypatch):
    """**A list somebody reads, not a report they scroll.** Forty gaps teaches
    people to close the page."""
    monkeypatch.setattr(reporting, "MAX_GAPS", 2)
    for n in range(4):
        metric = make_metric(f"metric_{n}")
        make_fact(metric, world["peter"], 1, WHEN)
        make_goal(db, org, world, metric_definition_id=metric.id)

    result = look(db, org, world)

    assert (result.behind, len(result.gaps)) == (4, 2)


def test_a_manager_sees_their_team_and_not_the_other_one(
    db, org, world, make_fact
):
    """The denominator has to be checkable. A goal you cannot open should not
    be in the percentage you are judged on."""
    make_fact(world["metric"], world["peter"], 10, WHEN)
    make_fact(world["metric"], world["clark"], 10, WHEN)
    make_goal(db, org, world)
    make_goal(db, org, world, subject_user_id=world["clark"].id)

    result = look(db, org, world, "manager")

    assert [gap.subject_name for gap in result.gaps] == ["Peter Parker"]


def test_an_archived_goal_is_not_anybodys_problem(db, org, world, make_fact):
    make_fact(world["metric"], world["peter"], 10, WHEN)
    make_goal(db, org, world, archived_at=datetime.now(UTC))

    assert look(db, org, world).total == 0


# -- Over the wire -----------------------------------------------------------


def running_goal(db, org, world):
    """A goal on a window that straddles today whatever the date is, so the
    assertion is about pace rather than about when the suite ran."""
    today = org_today()
    return make_goal(
        db, org, world,
        period_type="custom",
        period_anchor=None,
        period_start=today - timedelta(days=40),
        period_end=today + timedelta(days=40),
    )


def test_the_overview_reaches_the_page(client, db, org, world, sign_in, make_fact):
    make_fact(world["metric"], world["peter"], 1, datetime.now(UTC) - timedelta(days=1))
    running_goal(db, org, world)
    db.commit()
    sign_in(world["admin"])

    reply = client.get("/api/reporting/overview")

    assert reply.status_code == 200, reply.json()
    assert reply.json()["gaps"][0]["subject_name"] == "Peter Parker"


def test_an_agent_is_refused(client, db, world, sign_in):
    """**A manager's endpoint, not a second way to read other people's
    numbers.** Every answer here is a list of people to talk to."""
    sign_in(world["peter"])

    assert client.get("/api/reporting/overview").status_code == 403


# -- One competition against the ones before it ------------------------------


def run(db, org, world, *, name, starts, ends, state="closed", winner=None,
        value=None, metric=None, entity_type="user"):
    competition = Competition(
        organization_id=org.id,
        name=name,
        metric_definition_id=(metric or world["metric"]).id,
        entity_type=entity_type,
        starts_at=starts,
        ends_at=ends,
        state=state,
    )
    db.add(competition)
    db.flush()
    if winner is not None:
        db.add(
            CompetitionParticipant(
                competition_id=competition.id,
                user_id=winner.id if entity_type == "user" else None,
                team_id=winner.id if entity_type == "team" else None,
                final_rank=1 if state == "closed" else None,
                final_value=Decimal(str(value)) if state == "closed" else None,
            )
        )
        db.flush()
    return competition


def live(db, org, world, **overrides):
    """A contest 50% through, whatever today is."""
    now = datetime.now(UTC)
    fields = {
        "name": "This sprint",
        "starts": now - timedelta(days=14),
        "ends": now + timedelta(days=14),
        "state": "active",
    }
    fields.update(overrides)
    return run(db, org, world, **fields)


def test_nobody_leads_while_nobody_has_scored(db, org, world):
    """QA-21: everybody at zero sorted by name, and the first name "led"."""
    competition = live(db, org, world)
    for person in (world["peter"], world["clark"]):
        db.add(CompetitionParticipant(competition_id=competition.id, user_id=person.id))
    db.flush()

    report = reporting.competition_report(db, org, competition)

    assert (report.leader_name, report.leader_value) == (None, None)


def test_it_predicts_where_the_leader_lands(db, org, world, make_fact):
    """Straight-line from the rate so far, which is the only projection this
    product claims to make."""
    competition = live(db, org, world)
    db.add(
        CompetitionParticipant(competition_id=competition.id, user_id=world["peter"].id)
    )
    make_fact(world["metric"], world["peter"], 50, datetime.now(UTC) - timedelta(days=7))
    db.flush()

    report = reporting.competition_report(db, org, competition)

    assert report.leader_value == 50
    assert report.predicted is not None and report.predicted > 50


def test_a_finished_contest_is_not_predicted(db, org, world):
    """A prediction of a number already known is noise, and the comparison
    switches to the score it actually got."""
    competition = run(
        db, org, world, name="Done",
        starts=datetime(2026, 1, 1, tzinfo=UTC), ends=datetime(2026, 1, 15, tzinfo=UTC),
        winner=world["peter"], value=80,
    )

    report = reporting.competition_report(db, org, competition)

    assert report.predicted is None
    assert report.basis == 80


def test_past_runs_are_settled_contests_on_the_same_metric(db, org, world):
    run(db, org, world, name="March", starts=datetime(2026, 3, 1, tzinfo=UTC),
        ends=datetime(2026, 3, 15, tzinfo=UTC), winner=world["peter"], value=60)
    run(db, org, world, name="April", starts=datetime(2026, 4, 1, tzinfo=UTC),
        ends=datetime(2026, 4, 15, tzinfo=UTC), winner=world["clark"], value=90)

    report = reporting.competition_report(db, org, live(db, org, world))

    assert [(r.name, r.value) for r in report.runs] == [("March", 60), ("April", 90)]


def test_a_contest_on_another_metric_is_not_compared(
    db, org, world, make_metric
):
    """**Two scores mean the same thing only if they measure the same thing.**
    Sixty calls next to sixty thousand dollars is a chart that lies."""
    other = make_metric("revenue", unit="currency")
    run(db, org, world, name="Revenue race", metric=other,
        starts=datetime(2026, 3, 1, tzinfo=UTC), ends=datetime(2026, 3, 15, tzinfo=UTC),
        winner=world["peter"], value=60)

    assert reporting.competition_report(db, org, live(db, org, world)).runs == []


def test_an_unsettled_contest_is_not_compared(db, org, world):
    """A settled result is the one number in this product that is written down
    rather than recomputed, and so the only one that cannot move under a chart
    after somebody has read it."""
    run(db, org, world, name="Ended", state="ended",
        starts=datetime(2026, 3, 1, tzinfo=UTC), ends=datetime(2026, 3, 15, tzinfo=UTC),
        winner=world["peter"], value=60)

    assert reporting.competition_report(db, org, live(db, org, world)).runs == []


def test_a_contest_that_has_not_finished_yet_is_not_history(db, org, world):
    """One ending after this one starts is a rival, not a precedent."""
    now = datetime.now(UTC)
    run(db, org, world, name="Later", starts=now, ends=now + timedelta(days=30),
        winner=world["peter"], value=500)

    assert reporting.competition_report(db, org, live(db, org, world)).runs == []


def test_the_record_and_the_deltas(db, org, world):
    run(db, org, world, name="March", starts=datetime(2026, 3, 1, tzinfo=UTC),
        ends=datetime(2026, 3, 15, tzinfo=UTC), winner=world["peter"], value=60)
    run(db, org, world, name="April", starts=datetime(2026, 4, 1, tzinfo=UTC),
        ends=datetime(2026, 4, 15, tzinfo=UTC), winner=world["clark"], value=120)
    run(db, org, world, name="May", starts=datetime(2026, 5, 1, tzinfo=UTC),
        ends=datetime(2026, 5, 15, tzinfo=UTC), winner=world["peter"], value=90)
    done = run(db, org, world, name="June", starts=datetime(2026, 6, 1, tzinfo=UTC),
               ends=datetime(2026, 6, 15, tzinfo=UTC), winner=world["peter"], value=100)

    report = reporting.competition_report(db, org, done)

    assert (report.first, report.previous, report.all_time_high) == (60, 90, 120)
    assert report.all_time_high_name == "Clark Kent"
    assert (report.vs_first, report.vs_previous, report.vs_high) == (40, 10, -20)


def test_the_comparison_set_is_capped(db, org, world, monkeypatch):
    monkeypatch.setattr(reporting, "MAX_RUNS", 2)
    for month in range(1, 6):
        run(db, org, world, name=f"M{month}",
            starts=datetime(2026, month, 1, tzinfo=UTC),
            ends=datetime(2026, month, 15, tzinfo=UTC),
            winner=world["peter"], value=month * 10)

    report = reporting.competition_report(db, org, live(db, org, world))

    assert [r.name for r in report.runs] == ["M4", "M5"]


def test_another_organizations_competition_is_not_found(
    client, db, org, world, sign_in
):
    competition = live(db, org, world)
    db.commit()
    sign_in(world["admin"])

    reply = client.get(f"/api/reporting/competitions/{competition.id + 9999}")

    assert reply.status_code == 404


def test_the_report_reaches_the_page(client, db, org, world, sign_in):
    competition = live(db, org, world)
    db.commit()
    sign_in(world["admin"])

    reply = client.get(f"/api/reporting/competitions/{competition.id}")

    assert reply.status_code == 200, reply.json()
    assert reply.json()["name"] == "This sprint"


# -- Track records -----------------------------------------------------------


def with_history(db, org, world, make_fact, hits: list[bool]):
    """A monthly goal of 100, given a past that hit in the months you say.

    `hits` is oldest first, one entry per month before this one.
    """
    for index, hit in enumerate(hits):
        when = months_back(len(hits) - index)
        make_fact(world["metric"], world["peter"], 150 if hit else 10, when)
    return make_goal(db, org, world)


def test_it_counts_how_often_the_target_was_met(db, org, world, make_fact):
    """Over the four months with numbers — not six, two of them before there
    was a goal or a number to miss (7.6, Q2-7)."""
    with_history(db, org, world, make_fact, [True, False, True, False])

    record = reporting.records(db, org, world["admin"])[0]

    assert (record.hit, record.considered, record.hit_rate) == (2, 4, 50.0)


def test_the_streak_ends_at_the_last_finished_period(db, org, world, make_fact):
    """**Not at the month in progress.** A streak that broke the moment a month
    opened would read as broken all month, which is the opposite of what a
    streak is for."""
    with_history(db, org, world, make_fact, [False, True, True, True])

    record = reporting.records(db, org, world["admin"])[0]

    assert record.current_streak == 3


def test_a_miss_last_month_ends_it(db, org, world, make_fact):
    with_history(db, org, world, make_fact, [True, True, True, False])

    assert reporting.records(db, org, world["admin"])[0].current_streak == 0


def test_the_best_run_is_remembered_after_it_breaks(db, org, world, make_fact):
    with_history(db, org, world, make_fact, [True, True, True, False, True])

    record = reporting.records(db, org, world["admin"])[0]

    assert (record.best_streak, record.current_streak) == (3, 1)


def test_the_periods_read_left_to_right(db, org, world, make_fact):
    """Oldest first, like every other timeline in the product."""
    with_history(db, org, world, make_fact, [True, False])

    seasons = reporting.records(db, org, world["admin"])[0].seasons

    assert [s.met_target for s in seasons][-2:] == [True, False]


def test_a_one_off_window_has_no_track_record(db, org, world):
    """A custom range has no defined predecessor to step back through."""
    today = org_today()
    make_goal(db, org, world, period_type="custom", period_anchor=None,
              period_start=today - timedelta(days=10),
              period_end=today + timedelta(days=10))

    assert reporting.records(db, org, world["admin"]) == []


def test_the_worst_record_is_listed_first(db, org, world, make_fact, make_metric):
    other = make_metric("emails_sent")
    with_history(db, org, world, make_fact, [True, True, True, True, True, True])
    for index in range(6):
        make_fact(other, world["peter"], 1, months_back(index + 1))
    make_goal(db, org, world, metric_definition_id=other.id)

    names = [r.metric_name for r in reporting.records(db, org, world["admin"])]

    assert names == ["Emails Sent", "Calls Made"]


def test_a_manager_sees_only_their_own_teams_records(db, org, world, make_fact):
    with_history(db, org, world, make_fact, [True])
    make_goal(db, org, world, subject_user_id=world["clark"].id)

    records = reporting.records(db, org, world["manager"])

    assert [r.subject_name for r in records] == ["Peter Parker"]


def test_one_metric_costs_one_pass_however_many_goals(
    db, org, world, make_fact, make_user
):
    """**Batched by metric, not run per goal.** Six periods times two hundred
    goals is twelve hundred aggregations for one page; every goal on the same
    metric and period shape shares the same six answers."""
    people = [make_user("agent", world["enterprise"], name=f"Agent {n}") for n in range(5)]
    for person in people:
        make_fact(world["metric"], person, 150, months_back(1))
        make_goal(db, org, world, subject_user_id=person.id)
    db.flush()

    seen: list[str] = []
    original = reporting.aggregate.run

    def counted(*args, **kwargs):
        seen.append("run")
        return original(*args, **kwargs)

    reporting.aggregate.run = counted
    try:
        records = reporting.records(db, org, world["admin"])
    finally:
        reporting.aggregate.run = original

    assert len(records) == 5
    assert len(seen) == 6


# -- The spreadsheet ---------------------------------------------------------


def csv_of(client):
    reply = client.get("/api/reporting/records.csv")
    assert reply.status_code == 200, reply.text
    return reply.text.lstrip("﻿").strip().splitlines()


def test_the_export_is_one_row_per_goal(
    client, db, org, world, sign_in, make_fact
):
    """**The question this file gets opened to answer is "who keeps missing"**,
    and that is a sort on one column. A row per period would make somebody
    build a pivot table first."""
    with_history(db, org, world, make_fact, [True, False])
    db.commit()
    sign_in(world["admin"])

    lines = csv_of(client)

    assert len(lines) == 2
    assert lines[1].startswith("Calls Made,Peter Parker")


def test_the_export_names_each_period_as_a_column(
    client, db, org, world, sign_in, make_fact
):
    with_history(db, org, world, make_fact, [True])
    db.commit()
    sign_in(world["admin"])

    header = csv_of(client)[0].split(",")

    assert header[:2] == ["Goal", "Who"]
    assert len(header) == 10 + 6


def test_a_name_a_spreadsheet_would_execute_is_defused(
    client, db, org, world, sign_in, make_fact
):
    """CSV injection: a cell starting with `=` is a formula, and quoting does
    not help because the spreadsheet strips the quotes first."""
    world["peter"].full_name = "=cmd|'/c calc'!A1"
    with_history(db, org, world, make_fact, [True])
    db.commit()
    sign_in(world["admin"])

    assert "'=cmd" in csv_of(client)[1]


def test_an_agent_cannot_download_it(client, db, world, sign_in):
    sign_in(world["peter"])

    assert client.get("/api/reporting/records.csv").status_code == 403


def test_goals_with_nothing_yet_are_too_early_to_tell():
    """A working day into the month, every goal at $0 headlined "On pace
    100%" (Q2-10). Goals with nothing yet are counted apart, and left out of
    the percentage — which has nothing to say until one has started."""
    from app.reporting import Overview

    early = Overview(total=2, not_started=2)
    assert early.on_pace_percent is None
    mixed = Overview(total=4, on_pace=1, behind=1, not_started=2)
    assert mixed.on_pace_percent == 50.0


# ── One row per series, counting only what counts (7.6, Q2-7) ────────────────


def test_a_repeating_goal_is_one_row(db, org, world, make_fact):
    """Last month's copy and this month's are the same goal, and were listed
    twice."""
    from dateutil.relativedelta import relativedelta

    make_goal(db, org, world, period_anchor=org_today() - relativedelta(months=1))
    newest = make_goal(db, org, world)

    rows = reporting.records(db, org, world["admin"])
    assert [r.goal_id for r in rows] == [newest.id]


def test_a_new_goal_with_no_history_has_nothing_to_count(db, org, world):
    """Six "misses" for months before the goal, or any number, existed."""
    make_goal(db, org, world)

    record = reporting.records(db, org, world["admin"])[0]
    assert record.considered == 0
    assert all(season.counted is False for season in record.seasons)
    assert len(record.seasons) == 6  # still drawn, as before the goal


def test_months_with_numbers_count_even_before_the_goal(db, org, world, make_fact):
    """The person was working; whether they would have met it is fair to show."""
    with_history(db, org, world, make_fact, [True])
    record = reporting.records(db, org, world["admin"])[0]
    assert (record.hit, record.considered) == (1, 1)


def test_no_forecast_from_the_first_minutes_or_for_a_cancelled_contest(db, org, world, make_fact):
    """P3-11: one $500 entry 50 minutes in "finished at $5,106". P3-10: a
    cancelled contest kept forecasting."""
    now = datetime.now(UTC)
    early = live(db, org, world, starts=now - timedelta(days=1), ends=now + timedelta(days=13))
    db.add(CompetitionParticipant(competition_id=early.id, user_id=world["peter"].id))
    make_fact(world["metric"], world["peter"], 50, now - timedelta(hours=2))
    db.flush()

    report = reporting.competition_report(db, org, early)
    assert report.predicted is None
    assert report.too_early is True

    early.state = "cancelled"
    db.flush()
    report = reporting.competition_report(db, org, early)
    assert report.predicted is None
    assert report.too_early is False
