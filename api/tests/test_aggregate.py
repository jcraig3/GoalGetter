"""The aggregation and ranking query.

Every leaderboard, dashboard tile, goal progress bar, and competition standing
is this code with different arguments, so a bug here is wrong everywhere at
once.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app import aggregate
from app.periods import resolve

# Mid-month, mid-week, well away from every boundary — so a test that fails is
# failing on the thing it names, not on period edges (which test_periods covers).
WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)
ANCHOR = WHEN.date()


@pytest.fixture
def month(org):
    return resolve(org, "month", ANCHOR)


@pytest.fixture
def world(make_team, make_user):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "alice": make_user("agent", enterprise, name="Alice"),
        "bob": make_user("agent", enterprise, name="Bob"),
        "carol": make_user("agent", smb, name="Carol"),
        "dave": make_user("agent", None, name="Dave"),
    }


def run(db, org, actor, metric, month, **kwargs):
    return aggregate.run(db, org.id, actor, metric, month, **kwargs)


def total(db, org, actor, metric, month, **kwargs):
    return aggregate.total(db, org.id, actor, metric, month, **kwargs)


# ── Aggregation functions ────────────────────────────────────────────────────


def test_sum_adds_values(db, org, world, make_metric, make_fact, month):
    metric = make_metric(aggregation="sum")
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["alice"], 5, WHEN)
    rows = run(db, org, world["admin"], metric, month)
    assert [(r.subject_name, r.value) for r in rows] == [("Alice", Decimal(15))]


def test_count_counts_rows_and_ignores_values(db, org, world, make_metric, make_fact, month):
    """The point of `count`: facts that are events with no meaningful
    magnitude. Summing the values instead would quietly return 999."""
    metric = make_metric(aggregation="count")
    make_fact(metric, world["alice"], 999, WHEN)
    make_fact(metric, world["alice"], 999, WHEN)
    assert run(db, org, world["admin"], metric, month)[0].value == Decimal(2)


def test_avg_is_the_mean(db, org, world, make_metric, make_fact, month):
    metric = make_metric(aggregation="avg")
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["alice"], 20, WHEN)
    assert run(db, org, world["admin"], metric, month)[0].value == Decimal(15)


@pytest.mark.parametrize(("aggregation", "expected"), [("max", 30), ("min", 5)])
def test_max_and_min(db, org, world, make_metric, make_fact, month, aggregation, expected):
    metric = make_metric(aggregation=aggregation)
    for value in (5, 30, 12):
        make_fact(metric, world["alice"], value, WHEN)
    assert run(db, org, world["admin"], metric, month)[0].value == Decimal(expected)


def test_last_takes_the_most_recent_fact_not_the_sum(db, org, world, make_metric, make_fact, month):
    """Snapshot metrics — pipeline size, quota attainment — arrive as running
    totals. Summing them is the classic integration bug this exists to avoid:
    the answer would be 600 instead of 350."""
    metric = make_metric(aggregation="last")
    make_fact(metric, world["alice"], 100, WHEN.replace(day=3))
    make_fact(metric, world["alice"], 150, WHEN.replace(day=7))
    make_fact(metric, world["alice"], 350, WHEN.replace(day=11))
    assert run(db, org, world["admin"], metric, month)[0].value == Decimal(350)


def test_last_is_per_subject_not_global(db, org, world, make_metric, make_fact, month):
    """Each person's own latest, not one winner's. Getting this wrong drops
    everyone but the most recently-active person off the board."""
    metric = make_metric(aggregation="last")
    make_fact(metric, world["alice"], 10, WHEN.replace(day=3))
    make_fact(metric, world["bob"], 20, WHEN.replace(day=11))
    rows = run(db, org, world["admin"], metric, month)
    assert {r.subject_name: r.value for r in rows} == {
        "Alice": Decimal(10),
        "Bob": Decimal(20),
    }


# ── Direction and ranking ────────────────────────────────────────────────────


def test_higher_is_better_ranks_descending(db, org, world, make_metric, make_fact, month):
    metric = make_metric(direction="higher_is_better")
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["bob"], 30, WHEN)
    rows = run(db, org, world["admin"], metric, month)
    assert [r.subject_name for r in rows] == ["Bob", "Alice"]


def test_lower_is_better_ranks_ascending(db, org, world, make_metric, make_fact, month):
    """Response time. Assuming bigger-is-better here produces a leaderboard
    that celebrates the worst performer — and raises no error while doing it."""
    metric = make_metric(direction="lower_is_better")
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["bob"], 30, WHEN)
    rows = run(db, org, world["admin"], metric, month)
    assert [r.subject_name for r in rows] == ["Alice", "Bob"]
    assert rows[0].rank == 1


def test_direction_is_the_only_difference_between_those_two(
    db, org, world, make_metric, make_fact, month
):
    """Same data, flipped setting, exactly reversed order — which proves the
    ordering comes from `direction` and not from insertion order or ids."""
    metric = make_metric(direction="higher_is_better")
    for user, value in ((world["alice"], 10), (world["bob"], 30), (world["carol"], 20)):
        make_fact(metric, user, value, WHEN)

    ascending = [r.subject_name for r in run(db, org, world["admin"], metric, month)]
    metric.direction = "lower_is_better"
    db.flush()
    descending = [r.subject_name for r in run(db, org, world["admin"], metric, month)]

    assert ascending == list(reversed(descending))


def test_rank_skips_after_a_tie(db, org, world, make_metric, make_fact, month):
    """1, 2, 2, 4 — nobody is third. How sales contests actually work."""
    metric = make_metric()
    for user, value in (
        (world["alice"], 50),
        (world["bob"], 30),
        (world["carol"], 30),
        (world["dave"], 10),
    ):
        make_fact(metric, user, value, WHEN)
    assert [r.rank for r in run(db, org, world["admin"], metric, month)] == [1, 2, 2, 4]


def test_dense_rank_does_not_skip(db, org, world, make_metric, make_fact, month):
    metric = make_metric()
    for user, value in (
        (world["alice"], 50),
        (world["bob"], 30),
        (world["carol"], 30),
        (world["dave"], 10),
    ):
        make_fact(metric, user, value, WHEN)
    rows = run(db, org, world["admin"], metric, month, dense_rank=True)
    assert [r.rank for r in rows] == [1, 2, 2, 3]


def test_rows_come_back_in_rank_order(db, org, world, make_metric, make_fact, month):
    metric = make_metric()
    for user, value in ((world["alice"], 1), (world["bob"], 99), (world["carol"], 50)):
        make_fact(metric, user, value, WHEN)
    ranks = [r.rank for r in run(db, org, world["admin"], metric, month)]
    assert ranks == sorted(ranks)


# ── Grouping ─────────────────────────────────────────────────────────────────


def test_group_by_team_sums_the_teams_members(db, org, world, make_metric, make_fact, month):
    metric = make_metric()
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["bob"], 15, WHEN)
    make_fact(metric, world["carol"], 7, WHEN)
    rows = run(db, org, world["admin"], metric, month, group_by="team")
    assert {r.subject_name: r.value for r in rows} == {
        "Enterprise": Decimal(25),
        "SMB": Decimal(7),
    }


def test_unassigned_people_are_excluded_from_team_grouping(
    db, org, world, make_metric, make_fact, month
):
    """"Unassigned" is not a team and must not appear as one — but those people
    still rank on the per-person board."""
    metric = make_metric()
    make_fact(metric, world["dave"], 100, WHEN)
    make_fact(metric, world["alice"], 10, WHEN)

    teams = run(db, org, world["admin"], metric, month, group_by="team")
    assert [r.subject_name for r in teams] == ["Enterprise"]

    people = run(db, org, world["admin"], metric, month)
    assert "Dave" in [r.subject_name for r in people]


def test_team_grouping_uses_the_snapshot_not_the_current_team(
    db, org, world, make_metric, make_fact, month
):
    """The reason `subject_team_id` is a column and not a join.

    Alice's history was made while she was on Enterprise. Moving her to SMB
    must not retroactively hand her past work to SMB.
    """
    metric = make_metric()
    make_fact(metric, world["alice"], 40, WHEN, team=world["enterprise"])

    world["alice"].team_id = world["smb"].id
    db.flush()

    rows = run(db, org, world["admin"], metric, month, group_by="team")
    assert {r.subject_name: r.value for r in rows} == {"Enterprise": Decimal(40)}


def test_joining_a_team_brings_work_recorded_with_no_team(
    db, org, world, make_metric, make_fact, month
):
    """Data first, teams second — the order a real deployment happens in.

    Dave's numbers arrived while he was on no team. "No team" was never a
    team, so the first one he joins takes them: nothing is rewritten, and the
    team board is not empty for everything loaded before teams existed (QA-1).
    """
    metric = make_metric()
    make_fact(metric, world["dave"], 30, WHEN)
    make_fact(metric, world["dave"], 12, WHEN)

    world["dave"].team_id = world["smb"].id
    db.flush()

    rows = run(db, org, world["admin"], metric, month, group_by="team")
    assert {r.subject_name: r.value for r in rows} == {"SMB": Decimal(42)}


def test_joining_a_team_takes_the_teams_office_too(
    db, org, world, make_metric, make_fact, month
):
    from app.models import Office

    office = Office(organization_id=org.id, name="Metropolis")
    db.add(office)
    db.flush()
    world["smb"].office_id = office.id
    db.flush()

    metric = make_metric()
    fact = make_fact(metric, world["dave"], 30, WHEN)

    world["dave"].team_id = world["smb"].id
    db.flush()

    assert (fact.subject_team_id, fact.subject_office_id) == (world["smb"].id, office.id)


def test_a_team_put_in_an_office_brings_work_recorded_with_no_office(
    db, org, world, make_metric, make_fact, month
):
    from app.models import Office

    metric = make_metric()
    make_fact(metric, world["carol"], 9, WHEN)

    office = Office(organization_id=org.id, name="Gotham")
    db.add(office)
    db.flush()
    world["smb"].office_id = office.id
    db.flush()

    rows = run(db, org, world["admin"], metric, month, group_by="office")
    assert {r.subject_name: r.value for r in rows} == {"Gotham": Decimal(9)}


def test_leaving_a_team_and_joining_another_keeps_the_first_teams_work(
    db, org, world, make_metric, make_fact, month
):
    """Only blanks are filled. Alice's Enterprise work stays Enterprise's, and
    only what she recorded while on no team goes with her to SMB."""
    metric = make_metric()
    make_fact(metric, world["alice"], 40, WHEN)

    world["alice"].team_id = None
    db.flush()
    make_fact(metric, world["alice"], 5, WHEN)

    world["alice"].team_id = world["smb"].id
    db.flush()

    rows = run(db, org, world["admin"], metric, month, group_by="team")
    assert {r.subject_name: r.value for r in rows} == {
        "Enterprise": Decimal(40),
        "SMB": Decimal(5),
    }


def test_team_id_filter_narrows_to_one_team(db, org, world, make_metric, make_fact, month):
    metric = make_metric()
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["carol"], 7, WHEN)
    rows = run(db, org, world["admin"], metric, month, team_id=world["smb"].id)
    assert [r.subject_name for r in rows] == ["Carol"]


# ── Scope ────────────────────────────────────────────────────────────────────


def test_an_agent_sees_only_their_own_row(db, org, world, make_metric, make_fact, month):
    metric = make_metric()
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["carol"], 99, WHEN)
    rows = run(db, org, world["alice"], metric, month)
    assert [r.subject_name for r in rows] == ["Alice"]


def test_a_manager_does_not_see_another_team(db, org, world, make_metric, make_fact, month):
    metric = make_metric()
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["carol"], 99, WHEN)
    names = [r.subject_name for r in run(db, org, world["manager"], metric, month)]
    assert "Alice" in names
    assert "Carol" not in names


def test_a_managers_own_team_total_is_complete_not_partial(
    db, org, world, make_metric, make_fact, month
):
    """A property worth pinning down, because it falls out of how scope is
    defined rather than being designed in.

    A manager's visible set is their whole team plus unassigned agents, and the
    team grouping excludes people with no team — so the one team row they see
    covers every member of it, and matches what an admin sees exactly.
    """
    metric = make_metric()
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["bob"], 15, WHEN)
    make_fact(metric, world["carol"], 99, WHEN)
    make_fact(metric, world["dave"], 50, WHEN)

    def enterprise(actor):
        rows = run(db, org, actor, metric, month, group_by="team")
        return next(r.value for r in rows if r.subject_name == "Enterprise")

    assert enterprise(world["manager"]) == enterprise(world["admin"]) == Decimal(25)


def test_scope_filters_the_query_so_ranks_are_recomputed(
    db, org, world, make_metric, make_fact, month
):
    """Scope is not a post-filter. If it were, Alice would keep rank 2 with the
    top row simply removed — leaving a board whose first row says "2"."""
    metric = make_metric()
    make_fact(metric, world["carol"], 99, WHEN)  # invisible to the manager
    make_fact(metric, world["alice"], 10, WHEN)

    rows = run(db, org, world["manager"], metric, month)
    assert rows[0].subject_name == "Alice"
    assert rows[0].rank == 1


# ── total() ──────────────────────────────────────────────────────────────────


def test_total_matches_the_sum_of_rows_for_a_sum_metric(
    db, org, world, make_metric, make_fact, month
):
    metric = make_metric(aggregation="sum")
    for user, value in ((world["alice"], 10), (world["bob"], 15), (world["carol"], 7)):
        make_fact(metric, user, value, WHEN)
    rows = run(db, org, world["admin"], metric, month)
    assert sum(r.value for r in rows) == total(db, org, world["admin"], metric, month)


def test_total_matches_the_team_rows_when_grouping_by_team(
    db, org, world, make_metric, make_fact, month
):
    """The bug this test exists for: `total` returned an organization-wide
    figure while the team rows excluded unassigned people, so the parts did not
    add up to the whole and it read as an arithmetic error on screen."""
    metric = make_metric()
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["carol"], 7, WHEN)
    make_fact(metric, world["dave"], 100, WHEN)  # unassigned — in no team row

    rows = run(db, org, world["admin"], metric, month, group_by="team")
    assert sum(r.value for r in rows) == total(
        db, org, world["admin"], metric, month, group_by="team"
    )


def test_total_ignores_limit(db, org, world, make_metric, make_fact, month):
    """A top-3 board must still report the true total, not the total of the
    three rows shown."""
    metric = make_metric()
    for user, value in (
        (world["alice"], 10),
        (world["bob"], 20),
        (world["carol"], 30),
        (world["dave"], 40),
    ):
        make_fact(metric, user, value, WHEN)
    rows = run(db, org, world["admin"], metric, month, limit=2)
    assert len(rows) == 2
    assert total(db, org, world["admin"], metric, month) == Decimal(100)


def test_total_of_an_avg_metric_is_not_the_sum_of_averages(
    db, org, world, make_metric, make_fact, month
):
    """Alice averages 10, Bob averages 30, but the overall average is 15 — not
    20, and certainly not 40. This is why total() runs its own query rather
    than adding up the breakdown."""
    metric = make_metric(aggregation="avg")
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["bob"], 30, WHEN)
    assert total(db, org, world["admin"], metric, month) == Decimal(15)


def test_total_respects_scope(db, org, world, make_metric, make_fact, month):
    metric = make_metric()
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["carol"], 99, WHEN)
    assert total(db, org, world["manager"], metric, month) == Decimal(10)


# ── Period filtering and empty results ───────────────────────────────────────


def test_facts_outside_the_period_are_excluded(db, org, world, make_metric, make_fact, month):
    metric = make_metric()
    make_fact(metric, world["alice"], 10, WHEN)
    make_fact(metric, world["alice"], 999, WHEN.replace(month=7))
    make_fact(metric, world["alice"], 999, WHEN.replace(month=9))
    assert run(db, org, world["admin"], metric, month)[0].value == Decimal(10)


def test_the_period_boundary_is_half_open(db, org, world, make_metric, make_fact, month):
    """A fact at exactly `start` counts; one at exactly `end` does not — which
    is what stops a boundary fact being counted in two consecutive periods."""
    metric = make_metric()
    make_fact(metric, world["alice"], 7, month.start)
    make_fact(metric, world["alice"], 999, month.end)
    assert run(db, org, world["admin"], metric, month)[0].value == Decimal(7)


def test_no_facts_returns_no_rows_and_a_zero_total(db, org, world, make_metric, month):
    """A real state — a new deployment, a quiet week — not an error. Returning
    None here would crash every caller that formats the total."""
    metric = make_metric()
    assert run(db, org, world["admin"], metric, month) == []
    assert total(db, org, world["admin"], metric, month) == Decimal(0)


def test_another_metric_does_not_leak_in(db, org, world, make_metric, make_fact, month):
    calls, emails = make_metric("calls"), make_metric("emails")
    make_fact(calls, world["alice"], 10, WHEN)
    make_fact(emails, world["alice"], 999, WHEN)
    assert run(db, org, world["admin"], calls, month)[0].value == Decimal(10)


def test_another_organizations_facts_do_not_leak_in(
    db, org, world, make_metric, make_fact, month
):
    """`organization_id` is in the WHERE clause, not merely implied by the
    other joins."""
    from app.models import MetricFact, Organization

    metric = make_metric()
    make_fact(metric, world["alice"], 10, WHEN)

    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    db.add(
        MetricFact(
            organization_id=other.id,
            metric_definition_id=metric.id,
            subject_user_id=world["alice"].id,
            value=Decimal(999),
            occurred_at=WHEN,
            source_type="manual",
            created_at=datetime.now(UTC),
        )
    )
    db.flush()

    assert run(db, org, world["admin"], metric, month)[0].value == Decimal(10)
    assert total(db, org, world["admin"], metric, month) == Decimal(10)


def test_values_stay_decimal_all_the_way_out(db, org, world, make_metric, make_fact, month):
    """Converting to float anywhere would undo the exactness NUMERIC was chosen
    for. 0.1 + 0.2 is a float classic; here it must be exactly 0.3."""
    metric = make_metric(unit="currency", decimal_places=4)
    make_fact(metric, world["alice"], "0.1", WHEN)
    make_fact(metric, world["alice"], "0.2", WHEN)
    value = run(db, org, world["admin"], metric, month)[0].value
    assert isinstance(value, Decimal)
    assert value == Decimal("0.3")


# ── Offices ──────────────────────────────────────────────────────────────────


@pytest.fixture
def offices(db, org, world, make_team, make_user):
    """Two offices, each with a team, plus a team in no office."""
    from app.models import Office

    phoenix = Office(organization_id=org.id, name="Phoenix")
    dallas = Office(organization_id=org.id, name="Dallas")
    db.add_all([phoenix, dallas])
    db.flush()

    world["enterprise"].office_id = phoenix.id
    world["smb"].office_id = dallas.id
    db.flush()
    return {"phoenix": phoenix, "dallas": dallas}


def test_group_by_office_rolls_up_its_teams(db, org, world, offices, make_metric, make_fact, month):
    metric = make_metric()
    make_fact(metric, world["alice"], 10, WHEN, office_id=offices["phoenix"].id)
    make_fact(metric, world["bob"], 15, WHEN, office_id=offices["phoenix"].id)
    make_fact(metric, world["carol"], 7, WHEN, office_id=offices["dallas"].id)

    rows = run(db, org, world["admin"], metric, month, group_by="office")
    assert {r.subject_name: r.value for r in rows} == {
        "Phoenix": Decimal(25),
        "Dallas": Decimal(7),
    }


def test_facts_with_no_office_are_excluded_from_an_office_board(
    db, org, world, offices, make_metric, make_fact, month
):
    """"No office" is not an office, exactly as "unassigned" is not a team."""
    metric = make_metric()
    make_fact(metric, world["dave"], 100, WHEN)  # no team, so no office
    make_fact(metric, world["alice"], 10, WHEN, office_id=offices["phoenix"].id)

    rows = run(db, org, world["admin"], metric, month, group_by="office")
    assert [r.subject_name for r in rows] == ["Phoenix"]


def test_an_office_filter_narrows_a_person_board(
    db, org, world, offices, make_metric, make_fact, month
):
    metric = make_metric()
    make_fact(metric, world["alice"], 10, WHEN, office_id=offices["phoenix"].id)
    make_fact(metric, world["carol"], 7, WHEN, office_id=offices["dallas"].id)

    rows = run(db, org, world["admin"], metric, month, office_id=offices["phoenix"].id)
    assert [r.subject_name for r in rows] == ["Alice"]


def test_office_grouping_uses_the_snapshot_not_the_teams_current_office(
    db, org, world, offices, make_metric, make_fact, month
):
    """The reason `subject_office_id` is a column.

    A team moving office during a restructure must not hand every past fact to
    the new office — "which office won Q1" has to keep its answer.
    """
    metric = make_metric()
    make_fact(metric, world["alice"], 40, WHEN, office_id=offices["phoenix"].id)

    world["enterprise"].office_id = offices["dallas"].id
    db.flush()

    rows = run(db, org, world["admin"], metric, month, group_by="office")
    assert {r.subject_name: r.value for r in rows} == {"Phoenix": Decimal(40)}


def test_an_office_total_matches_its_rows(db, org, world, offices, make_metric, make_fact, month):
    metric = make_metric()
    make_fact(metric, world["alice"], 10, WHEN, office_id=offices["phoenix"].id)
    make_fact(metric, world["carol"], 7, WHEN, office_id=offices["dallas"].id)
    make_fact(metric, world["dave"], 100, WHEN)  # no office

    rows = run(db, org, world["admin"], metric, month, group_by="office")
    assert sum(r.value for r in rows) == total(
        db, org, world["admin"], metric, month, group_by="office"
    )


# ── `last`, which was declared and never implemented ────────────────────────


def test_last_takes_the_most_recent_value(db, org, world, make_metric, make_fact, month):
    """**Not the largest — the newest.** `max` would be wrong for exactly the
    metric this exists for: a running total that can go down. It was in
    `AGGREGATIONS` and missing from `_aggregate_column`, so every leaderboard
    query on such a metric raised `KeyError: last`."""
    metric = make_metric(aggregation="last")
    make_fact(metric, world["alice"], 100, WHEN - timedelta(days=2))
    make_fact(metric, world["alice"], 250, WHEN - timedelta(days=1))
    make_fact(metric, world["alice"], 180, WHEN)

    rows = run(db, org, world["admin"], metric, month)

    assert [(r.subject_name, r.value) for r in rows] == [("Alice", Decimal(180))]


def test_last_is_per_person_not_per_board(db, org, world, make_metric, make_fact, month):
    metric = make_metric(aggregation="last")
    make_fact(metric, world["alice"], 10, WHEN - timedelta(days=1))
    make_fact(metric, world["alice"], 20, WHEN)
    make_fact(metric, world["bob"], 90, WHEN - timedelta(days=1))

    rows = run(db, org, world["admin"], metric, month)

    assert {(r.subject_name, r.value) for r in rows} == {
        ("Alice", Decimal(20)),
        ("Bob", Decimal(90)),
    }


def test_last_survives_a_value_going_down(db, org, world, make_metric, make_fact, month):
    """The case `max` gets wrong. A snapshot source rewrites one fact per person
    each sync, and a month-to-date total resets when the month turns over."""
    metric = make_metric(aggregation="last")
    make_fact(metric, world["alice"], 900, WHEN - timedelta(days=1))
    make_fact(metric, world["alice"], 12, WHEN)

    rows = run(db, org, world["admin"], metric, month)

    assert [r.value for r in rows] == [Decimal(12)]
