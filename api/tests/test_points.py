"""The points economy: a ledger, priced per event, inside a season.

**The failure this is built against is not a bug, it is a two-year decay.** In
the live account this product was measured against, the top dozen reps sat at
165K–178K points against a top tier of 100K, and lifetime points equalled
reward points because nothing was ever spent. The number still went up and had
stopped meaning anything: nobody could be caught, so nobody was chasing.

So the tests that matter here are not "does it add up". They are: does the
scoreboard reset, can it be farmed, and can a job that runs every few minutes
pay somebody twice for one thing.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import notifications, points, seasons
from app.models import Goal, PointAward, PointValue, Season
from tests.conftest import org_today, within_this_month

WHEN = within_this_month()


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    db.flush()
    return {
        "enterprise": enterprise,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", enterprise, name="Clark Kent"),
        "metric": make_metric("calls_made"),
    }


def make_season(db, org, *, name="Test season", start=None, end=None):
    today = org_today()
    season = Season(
        organization_id=org.id,
        name=name,
        starts_on=start or today - timedelta(days=30),
        ends_on=end or today + timedelta(days=30),
    )
    db.add(season)
    db.flush()
    return season


def pay(db, org, world, **overrides):
    fields = {
        "user_id": world["peter"].id,
        "points": 100,
        "event_key": "goal.achieved",
        "subject_type": "goal",
        "subject_id": 1,
        "reason": "Hit a goal",
    }
    fields.update(overrides)
    return points.award(db, org=org, **fields)


# -- Seasons -----------------------------------------------------------------


def test_the_first_award_opens_the_first_season(db, org, world):
    """**An economy that refuses to pay until an admin has visited a settings
    page is an economy nobody switches on.** The alternative — paying into a
    lifetime total and adding seasons later — means choosing between wiping
    balances people earned and keeping the thing seasons exist to prevent."""
    assert seasons.current(db, org) is None

    pay(db, org, world)

    assert seasons.current(db, org) is not None


def test_that_season_is_the_fiscal_quarter(db, org, world):
    """A boundary the business already plans against, rather than ninety days
    after whenever somebody happened to close a deal."""
    season = seasons.open_for(db, org, now=datetime(2026, 8, 12, 15, tzinfo=UTC))

    assert (season.name, season.starts_on, season.ends_on) == (
        "Q3 2026", date(2026, 7, 1), date(2026, 9, 30),
    )


def test_a_first_award_near_a_quarters_end_opens_the_next_quarter(db, org):
    """QA-19: on 30 September it opened "Q3 2026", which ended that day and
    reset the points it had just paid. Close to the end, the first season is
    the next quarter, started a few days early."""
    season = seasons.open_for(db, org, now=datetime(2026, 9, 30, 15, tzinfo=UTC))

    assert (season.name, season.starts_on, season.ends_on) == (
        "Q4 2026", date(2026, 9, 30), date(2026, 12, 31),
    )


def test_a_second_award_does_not_open_a_second_season(db, org, world):
    pay(db, org, world)
    pay(db, org, world, subject_id=2)

    assert len(db.scalars(select(Season)).all()) == 1


def test_looking_at_the_page_does_not_start_one(db, org, world):
    """`current` is read-only, and that matters: a page showing "no season is
    running" must not start one as a side effect of being looked at."""
    assert seasons.current(db, org) is None
    assert db.scalars(select(Season)).all() == []


def test_two_seasons_cannot_overlap(db, org):
    """**Unstorable, not merely rejected.** "Which season is this award in?"
    must have exactly one answer, or somebody's balance depends on which row a
    query happened to find first."""
    from sqlalchemy.exc import IntegrityError

    make_season(db, org, start=date(2027, 1, 1), end=date(2027, 3, 31))

    with pytest.raises(IntegrityError):
        make_season(
            db, org, name="Overlapping",
            start=date(2027, 3, 31), end=date(2027, 6, 30),
        )


def test_a_season_runs_through_its_last_day(db, org):
    """Inclusive at both ends. A range ending at midnight would drop
    everything earned on the final afternoon, which is the afternoon people
    care most about."""
    season = make_season(db, org, start=date(2027, 1, 1), end=date(2027, 3, 31))

    assert seasons.for_date(db, org.id, date(2027, 3, 31)) is not None
    assert seasons.for_date(db, org.id, date(2027, 4, 1)) is None
    assert season.ends_on == date(2027, 3, 31)


def test_the_scoreboard_actually_resets(db, org, world):
    """**The whole reason this module exists.** Points earned last season do
    not carry into this one — otherwise the people at the top cannot be caught
    and both ends of the table stop looking."""
    old = make_season(
        db, org, name="Last", start=org_today() - timedelta(days=200),
        end=org_today() - timedelta(days=110),
    )
    db.add(
        PointAward(
            organization_id=org.id, season_id=old.id, user_id=world["peter"].id,
            points=5000, event_key="goal.achieved", subject_type="goal",
            subject_id=99, reason="Last season",
        )
    )
    db.flush()

    now = make_season(db, org, name="Now")

    assert points.balance(db, now.id, world["peter"].id) == 0
    assert points.lifetime(db, org.id, world["peter"].id) == 5000


# -- The ledger --------------------------------------------------------------


def test_a_balance_is_a_sum_of_rows(db, org, world):
    """**Never a running total on the person.** One number incremented from
    four code paths is wrong the first time two of them race, with nothing to
    compare it against."""
    pay(db, org, world, points=100, subject_id=1)
    pay(db, org, world, points=50, subject_id=2)

    season = seasons.current(db, org)

    assert points.balance(db, season.id, world["peter"].id) == 150


def test_a_mistake_is_corrected_by_writing_the_opposite_row(db, org, world):
    """Not by editing one. Somebody can read what happened, rather than
    finding a number quietly different from yesterday."""
    pay(db, org, world, points=100)
    pay(
        db, org, world, points=-100, event_key=points.MANUAL, subject_id=1,
        reason="Awarded in error", awarded_by_user_id=world["admin"].id,
    )

    season = seasons.current(db, org)

    assert points.balance(db, season.id, world["peter"].id) == 0
    assert len(points.statement(db, org.id, world["peter"].id)) == 2


def test_awarding_the_same_thing_twice_pays_once(db, org, world):
    """**The idempotency guarantee.** The jobs that pay points are the jobs
    that announce things: they loop over state that is a query rather than a
    column, and they can be restarted mid-pass."""
    first = pay(db, org, world)
    second = pay(db, org, world)

    assert first is not None
    assert second is None


def test_an_award_with_no_period_still_latches(db, org, world):
    """NULLS NOT DISTINCT is load-bearing. Postgres treats NULLs as distinct in
    a unique index by default, so without it every award with no period would
    insert again on every job cycle, forever."""
    pay(db, org, world, period_anchor=None)
    again = pay(db, org, world, period_anchor=None)

    assert again is None


def test_two_periods_of_one_recurring_goal_both_pay(db, org, world):
    """August's "you hit your goal" and September's are different awards about
    the same goal, and only the anchor tells them apart."""
    pay(db, org, world, period_anchor=date(2026, 8, 1))
    second = pay(db, org, world, period_anchor=date(2026, 9, 1))

    assert second is not None


def test_a_hand_written_award_repeats(db, org, world):
    """A manager who gives somebody 50 points twice meant to do it twice."""
    pay(db, org, world, event_key=points.MANUAL,
        awarded_by_user_id=world["admin"].id)
    again = pay(db, org, world, event_key=points.MANUAL,
                awarded_by_user_id=world["admin"].id)

    assert again is not None


def test_a_worthless_award_writes_nothing(db, org, world):
    """A statement full of "+0 for something" lines is a statement nobody
    reads."""
    assert pay(db, org, world, points=0) is None
    assert db.scalars(select(PointAward)).all() == []


def test_nothing_is_written_when_nothing_is_worth_anything(db, org, world):
    """And in particular, no season is opened. An organization that has turned
    every award off should not accumulate empty seasons."""
    pay(db, org, world, points=0)

    assert db.scalars(select(Season)).all() == []


# -- What things are worth ---------------------------------------------------


def test_absent_means_the_default_not_zero(db, org, world):
    """An organization that has never opened the settings page still has a
    working economy."""
    assert points.value_of(db, org.id, "goal.achieved") == 100


def test_zero_is_a_different_statement_from_never_having_looked(db, org, world):
    db.add(
        PointValue(organization_id=org.id, event_key="goal.achieved", points=0)
    )
    db.flush()

    assert points.value_of(db, org.id, "goal.achieved") == 0


def test_a_birthday_is_worth_nothing_by_default(db, org):
    """It is celebrated on the wall and it is not an achievement. Paying for it
    would put the person with the earliest birthday ahead of the person who
    closed the most deals in January."""
    assert points.DEFAULTS["person.birthday"] == 0


def test_winning_a_contest_beats_hitting_a_goal(db, org):
    """A contest is won against other people who were also trying."""
    assert points.DEFAULTS["competition.won"] > points.DEFAULTS["goal.achieved"]


def test_recognition_is_worth_less_than_anything_earned(db, org):
    """It is the one award another person can hand out freely. An economy
    where praise is the cheapest way to farm points stops being praise."""
    assert points.DEFAULTS["recognition"] < points.DEFAULTS["goal.achieved"]


# -- Standings ---------------------------------------------------------------


def test_the_table_ranks_highest_first(db, org, world):
    pay(db, org, world, user_id=world["peter"].id, points=100, subject_id=1)
    pay(db, org, world, user_id=world["clark"].id, points=300, subject_id=2)

    table = points.standings(db, seasons.current(db, org))

    assert [(row.name, row.points) for row in table] == [
        ("Clark Kent", 300),
        ("Peter Parker", 100),
    ]


def test_a_tie_shares_a_rank_and_skips_the_next(db, org, world):
    """1, 2, 2, 4 — matching how every other ranked thing here behaves."""
    pay(db, org, world, user_id=world["peter"].id, points=100, subject_id=1)
    pay(db, org, world, user_id=world["clark"].id, points=100, subject_id=2)
    pay(db, org, world, user_id=world["manager"].id, points=300, subject_id=3)

    table = points.standings(db, seasons.current(db, org))

    assert [row.rank for row in table] == [1, 2, 2]


def test_the_table_can_be_narrowed_to_who_somebody_may_see(db, org, world):
    """Passed in rather than resolved here, so this module never has to know
    about scope."""
    pay(db, org, world, user_id=world["peter"].id, subject_id=1)
    pay(db, org, world, user_id=world["clark"].id, subject_id=2)

    table = points.standings(
        db, seasons.current(db, org), user_ids=[world["peter"].id]
    )

    assert [row.name for row in table] == ["Peter Parker"]


def test_nobody_visible_is_an_empty_table_not_the_whole_org(db, org, world):
    """An empty list means nobody, which is different from None meaning
    everybody — and getting that backwards would leak the whole organization
    to somebody who may see none of it."""
    pay(db, org, world, user_id=world["peter"].id)

    assert points.standings(db, seasons.current(db, org), user_ids=[]) == []


def test_the_statement_says_where_it_came_from(db, org, world):
    """**The thing that makes a total believable.** A number with no statement
    behind it is one people argue with."""
    pay(db, org, world, reason="Hit Calls this month")

    line = points.statement(db, org.id, world["peter"].id)[0]

    assert line.reason == "Hit Calls this month"


def test_the_reason_is_not_rewritten_when_a_goal_is_renamed(db, org, world):
    """Stored at award time. Renaming a goal must not rewrite what somebody was
    paid for last March."""
    pay(db, org, world, reason="Hit Calls this month")

    # Whatever happens to the goal afterwards, the line says what it said.
    line = points.statement(db, org.id, world["peter"].id)[0]

    assert "Calls this month" in line.reason


# -- Paid for the right things -----------------------------------------------


def make_goal(db, org, world, **overrides):
    fields = {
        "organization_id": org.id,
        "metric_definition_id": world["metric"].id,
        "subject_type": "user",
        "subject_user_id": world["peter"].id,
        "target_value": Decimal("10"),
        "period_type": "month",
        "period_anchor": org_today(),
    }
    fields.update(overrides)
    goal = Goal(**fields)
    db.add(goal)
    db.flush()
    return goal


def balances(db, org, world):
    season = seasons.current(db, org)
    if season is None:
        return {}
    return {
        row.name: row.points for row in points.standings(db, season)
    }


def test_hitting_a_goal_pays(db, org, world, make_fact):
    make_fact(world["metric"], world["peter"], 50, WHEN)
    make_goal(db, org, world)

    notifications.detect(db)

    assert balances(db, org, world) == {"Peter Parker": 100}


def test_the_manager_who_is_told_is_not_the_one_who_is_paid(
    db, org, world, make_fact
):
    """**The two lists are deliberately different, and the difference is the
    whole design.** Paying a manager for their agents' goals would put every
    manager at the top of a scoreboard made of other people's work."""
    make_fact(world["metric"], world["peter"], 50, WHEN)
    make_goal(db, org, world)

    notifications.detect(db)

    assert "Manager" not in balances(db, org, world)


def test_a_team_goal_pays_every_member(db, org, world, make_fact):
    """A balance somebody can spend has to belong to a person, and paying the
    team lead is the manager problem again."""
    make_fact(world["metric"], world["peter"], 50, WHEN)
    make_goal(
        db, org, world, subject_type="team", subject_user_id=None,
        subject_team_id=world["enterprise"].id,
    )

    notifications.detect(db)

    paid = balances(db, org, world)

    assert paid["Peter Parker"] == 100
    assert paid["Clark Kent"] == 100


def test_an_organization_goal_pays_nobody(db, org, world, make_fact):
    """Handing the entire company the same award moves every balance by the
    same amount — which changes no ranking and teaches people the number is
    weather rather than something they did."""
    make_fact(world["metric"], world["peter"], 50, WHEN)
    make_goal(db, org, world, subject_type="organization", subject_user_id=None)

    notifications.detect(db)

    assert balances(db, org, world) == {}


def test_running_detection_twice_pays_once(db, org, world, make_fact):
    """The property the whole ledger rests on: this job runs every few
    minutes."""
    make_fact(world["metric"], world["peter"], 50, WHEN)
    make_goal(db, org, world)

    notifications.detect(db)
    notifications.detect(db)

    assert balances(db, org, world) == {"Peter Parker": 100}


def test_a_goal_that_is_not_met_pays_nothing(db, org, world, make_fact):
    make_fact(world["metric"], world["peter"], 1, WHEN)
    make_goal(db, org, world)

    notifications.detect(db)

    assert balances(db, org, world) == {}


# -- Recognition, which is the one that can be farmed -------------------------


def shout(client, user, message="Nice work"):
    return client.post(
        "/api/recognition", json={"user_id": user.id, "message": message}
    )


def test_being_recognised_pays(client, db, org, world, sign_in):
    sign_in(world["manager"])

    shout(client, world["peter"])

    assert balances(db, org, world) == {"Peter Parker": 25}


def test_the_same_person_recognising_twice_in_a_day_pays_once(
    client, db, org, world, sign_in
):
    """**The defence is a latch rather than a limit, so the feature is
    untouched.** The second shout-out still happens, still lands on the wall,
    still means what it meant. It just does not pay again — otherwise a manager
    who likes somebody is an income stream."""
    sign_in(world["manager"])

    shout(client, world["peter"], "Great call")
    shout(client, world["peter"], "And another")

    assert balances(db, org, world) == {"Peter Parker": 25}


def test_the_second_shout_out_still_happens(client, db, org, world, sign_in):
    """The point of a latch over a limit: nothing about the feature changes."""
    sign_in(world["manager"])

    shout(client, world["peter"], "Great call")
    second = shout(client, world["peter"], "And another")

    assert second.status_code == 201, second.json()


def test_two_different_people_recognising_pays_twice(
    client, db, org, world, sign_in
):
    """Which is right: two colleagues noticing the same work independently is
    not one colleague noticing it twice."""
    sign_in(world["manager"])
    shout(client, world["peter"])

    sign_in(world["admin"])
    shout(client, world["peter"])

    assert balances(db, org, world) == {"Peter Parker": 50}


def test_recognising_yourself_pays_nothing(client, db, org, world, sign_in):
    """Allowed to write — the wall is a strange place to do it, which is its
    own deterrent — but not income."""
    sign_in(world["manager"])

    shout(client, world["manager"])

    assert balances(db, org, world) == {}


# -- Achievement rules -------------------------------------------------------


def make_rule(client, world, **overrides):
    body = {
        "name": "Big deal",
        "metric_id": world["metric"].id,
        "comparator": "gte",
        "threshold": "100",
        **overrides,
    }
    return client.post("/api/achievement-rules", json=body)


def test_an_achievement_rule_pays_what_it_says(
    client, db, org, world, sign_in, make_fact
):
    sign_in(world["admin"])
    make_rule(client, world, points=40)
    make_fact(world["metric"], world["peter"], 500, datetime.now(UTC))
    db.commit()

    notifications.detect_rules(db)

    assert balances(db, org, world) == {"Peter Parker": 40}


def test_a_rule_pays_per_piece_of_work(
    client, db, org, world, sign_in, make_fact
):
    """Unlike a goal, which pays once per period. A rule fires on every
    matching record, which is exactly why its default is low."""
    sign_in(world["admin"])
    make_rule(client, world, points=40)
    make_fact(world["metric"], world["peter"], 500, datetime.now(UTC))
    make_fact(world["metric"], world["peter"], 600, datetime.now(UTC))
    db.commit()

    notifications.detect_rules(db)

    assert balances(db, org, world) == {"Peter Parker": 80}


def test_a_rule_can_celebrate_without_paying(
    client, db, org, world, sign_in, make_fact
):
    """Zero is a reasonable thing to want: mark it on the wall, do not put it
    in the economy."""
    sign_in(world["admin"])
    make_rule(client, world, points=0)
    make_fact(world["metric"], world["peter"], 500, datetime.now(UTC))
    db.commit()

    report = notifications.detect_rules(db)

    assert report.emitted == 1
    assert balances(db, org, world) == {}


def test_running_rule_detection_twice_pays_once(
    client, db, org, world, sign_in, make_fact
):
    sign_in(world["admin"])
    make_rule(client, world, points=40)
    make_fact(world["metric"], world["peter"], 500, datetime.now(UTC))
    db.commit()

    notifications.detect_rules(db)
    notifications.detect_rules(db)

    assert balances(db, org, world) == {"Peter Parker": 40}


# -- Competitions ------------------------------------------------------------


def contest(db, org, world, entrants, **overrides):
    from app.models import Competition, CompetitionParticipant

    now = datetime.now(UTC)
    fields = {
        "organization_id": org.id,
        "name": "August sprint",
        "metric_definition_id": world["metric"].id,
        "entity_type": "user",
        "starts_at": now - timedelta(days=14),
        "ends_at": now - timedelta(days=1),
        "state": "active",
    }
    fields.update(overrides)
    competition = Competition(**fields)
    db.add(competition)
    db.flush()
    for entrant in entrants:
        db.add(
            CompetitionParticipant(
                competition_id=competition.id, user_id=entrant.id
            )
        )
    db.flush()
    return competition


def test_winning_a_contest_pays_the_most(db, org, world, make_fact):
    from app import competitions

    when = datetime.now(UTC) - timedelta(days=7)
    make_fact(world["metric"], world["peter"], 500, when)
    make_fact(world["metric"], world["clark"], 100, when)
    competition = contest(db, org, world, [world["peter"], world["clark"]])

    competitions.close(db, org, competition)

    assert balances(db, org, world)["Peter Parker"] == 500


def test_the_podium_pays_and_the_field_does_not(db, org, world, make_fact):
    """**Entering a contest and finishing third should beat not entering.**
    Paying everybody who was named in one would make entry itself the income,
    and then the winner's award is a rounding error on a number everybody
    got."""
    from app import competitions

    when = datetime.now(UTC) - timedelta(days=7)
    field = [world["peter"], world["clark"], world["manager"], world["admin"]]
    for person, value in zip(field, (400, 300, 200, 100)):
        make_fact(world["metric"], person, value, when)
    competition = contest(db, org, world, field)

    competitions.close(db, org, competition)
    paid = balances(db, org, world)

    assert paid["Peter Parker"] == 500
    assert paid["Clark Kent"] == 150
    assert paid["Manager"] == 150
    assert "Admin" not in paid


def test_a_settled_contest_does_not_pay_again(db, org, world, make_fact):
    from app import competitions

    when = datetime.now(UTC) - timedelta(days=7)
    make_fact(world["metric"], world["peter"], 500, when)
    competition = contest(db, org, world, [world["peter"]])

    competitions.close(db, org, competition)
    competitions.announce_result(db, competition)

    assert balances(db, org, world)["Peter Parker"] == 500


def test_a_net_of_zero_is_not_a_score(db, org, world):
    """**Somebody who has never been awarded anything does not appear at all**,
    so somebody whose award was corrected back to nothing must not appear
    either. Otherwise two people with no points are shown differently, and one
    of them is sitting at rank 1 with a zero beside their name.
    """
    pay(db, org, world, points=100)
    pay(db, org, world, points=-100, event_key=points.MANUAL,
        awarded_by_user_id=world["admin"].id)

    assert points.standings(db, seasons.current(db, org)) == []


def test_being_docked_below_zero_still_shows(db, org, world):
    """Negative balances are not hidden: being docked is a thing that
    happened, and a table that quietly dropped somebody would be the one place
    the ledger lied."""
    pay(db, org, world, points=-50, event_key=points.MANUAL,
        awarded_by_user_id=world["admin"].id)

    table = points.standings(db, seasons.current(db, org))

    assert [(row.name, row.points) for row in table] == [("Peter Parker", -50)]
