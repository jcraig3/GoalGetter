"""Badges: something you are, rather than something you have.

**A badge is the part of the economy that survives a season reset.** Points go
to zero every quarter, deliberately — and something has to be left over, or the
reset takes everything anybody built. A tier is not that thing either: a tier
is read from the current balance, so it resets too.

The counting is where this goes quietly wrong, and it goes wrong in ways that
look like nothing at all: counted from the wrong table it undercounts near the
end of a quarter, or silently never fires for a rule set to zero points. Those
are what most of these tests are about.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import badges, notifications, points, seasons
from app.models import AchievementRule, Badge, BadgeAward
from tests.conftest import org_today, org_now


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
        "metric": make_metric("deal_value", unit="currency"),
    }


def make_rule(db, org, world, *, threshold=100, points_each=10, **overrides):
    fields = {
        "organization_id": org.id,
        "name": "Big deal",
        "metric_definition_id": world["metric"].id,
        "comparator": "gte",
        "threshold": threshold,
        "scope": "everyone",
        "message": "",
        "points": points_each,
        # A rule never celebrates work done before it existed, so it has to
        # pre-date the facts these tests file.
        "created_at": datetime.now(UTC) - timedelta(days=200),
    }
    fields.update(overrides)
    rule = AchievementRule(**fields)
    db.add(rule)
    db.flush()
    return rule


def make_badge(db, org, world, rule=None, **overrides):
    fields = {
        "organization_id": org.id,
        "name": "Closer",
        "description": "Three big deals in a month",
        "kind": "count" if rule else "manual",
        "achievement_rule_id": rule.id if rule else None,
        "threshold": 3 if rule else None,
        "counted_over": "month" if rule else None,
    }
    fields.update(overrides)
    badge = Badge(**fields)
    db.add(badge)
    db.flush()
    return badge


def this_month(day=10, hour=12):
    """A moment inside the current month, in the past whatever today is."""
    now = datetime.now(UTC)
    when = now.replace(day=1, hour=hour, minute=0, second=0, microsecond=0)
    return min(when + timedelta(days=day - 1), now - timedelta(minutes=1))


def holders(db, org, badge_name="Closer"):
    rows = db.execute(
        select(BadgeAward.user_id).join(Badge, Badge.id == BadgeAward.badge_id)
        .where(Badge.name == badge_name)
    ).all()
    return {row[0] for row in rows}


# -- Earning one by counting -------------------------------------------------


def test_enough_firings_earns_it(db, org, world, make_fact):
    rule = make_rule(db, org, world)
    make_badge(db, org, world, rule)
    for _ in range(3):
        make_fact(world["metric"], world["peter"], 500, this_month())

    badges.detect(db)

    assert world["peter"].id in holders(db, org)


def test_one_short_earns_nothing(db, org, world, make_fact):
    rule = make_rule(db, org, world)
    make_badge(db, org, world, rule)
    for _ in range(2):
        make_fact(world["metric"], world["peter"], 500, this_month())

    badges.detect(db)

    assert holders(db, org) == set()


def test_only_facts_that_clear_the_bar_count(db, org, world, make_fact):
    """The badge counts the rule's *firings*, not the metric's rows — so a
    badge saying three and a wall that announced one would be two numbers
    about the same work disagreeing in public."""
    rule = make_rule(db, org, world, threshold=100)
    make_badge(db, org, world, rule)
    make_fact(world["metric"], world["peter"], 500, this_month())
    for _ in range(5):
        make_fact(world["metric"], world["peter"], 10, this_month())

    badges.detect(db)

    assert holders(db, org) == set()


def test_a_rule_worth_no_points_still_earns_its_badge(db, org, world, make_fact):
    """**Counted from the facts, not from the ledger.** A rule set to zero —
    "celebrate it, do not pay for it" — writes no ledger rows at all, and a
    badge counting those would never fire for one."""
    rule = make_rule(db, org, world, points_each=0)
    make_badge(db, org, world, rule)
    for _ in range(3):
        make_fact(world["metric"], world["peter"], 500, this_month())

    badges.detect(db)

    assert world["peter"].id in holders(db, org)


def test_work_before_the_rule_existed_does_not_count(db, org, world, make_fact):
    """The same guard the announcement obeys, and the reason both read it from
    one place: a connector syncing six months of history must not hand out
    badges for it."""
    rule = make_rule(db, org, world, created_at=datetime.now(UTC))
    make_badge(db, org, world, rule)
    for _ in range(3):
        make_fact(
            world["metric"], world["peter"], 500,
            datetime.now(UTC) - timedelta(days=2),
        )

    badges.detect(db)

    assert holders(db, org) == set()


def test_each_person_is_counted_separately(db, org, world, make_fact):
    rule = make_rule(db, org, world)
    make_badge(db, org, world, rule)
    for _ in range(3):
        make_fact(world["metric"], world["peter"], 500, this_month())
    make_fact(world["metric"], world["clark"], 500, this_month())

    badges.detect(db)

    assert holders(db, org) == {world["peter"].id}


def test_running_detection_twice_awards_once(db, org, world, make_fact):
    rule = make_rule(db, org, world)
    make_badge(db, org, world, rule)
    for _ in range(3):
        make_fact(world["metric"], world["peter"], 500, this_month())

    badges.detect(db)
    badges.detect(db)

    assert len(db.scalars(select(BadgeAward)).all()) == 1


def test_a_hidden_person_earns_nothing(db, org, world, make_fact):
    rule = make_rule(db, org, world)
    make_badge(db, org, world, rule)
    world["peter"].hidden_at = datetime.now(UTC)
    for _ in range(3):
        make_fact(world["metric"], world["peter"], 500, this_month())

    badges.detect(db)

    assert holders(db, org) == set()


# -- Windows -----------------------------------------------------------------


def test_a_month_badge_counts_from_the_first(db, org, world):
    today = org_today()

    assert badges.window_start(db, org, "month", today) == today.replace(day=1)


def test_a_week_badge_uses_the_organizations_own_week(db, org, world):
    """**Through `periods`, not recomputed here.** A floor whose week begins on
    Sunday should not have its badges counted Monday to Sunday — the classic
    off-by-one that puts Sunday's numbers in the wrong week."""
    org.week_starts_on = 0  # Sunday
    today = date(2027, 3, 3)  # a Wednesday

    assert badges.window_start(db, org, "week", today) == date(2027, 2, 28)


def test_a_season_badge_with_no_season_has_no_window(db, org, world):
    """**And must not open one.** That is the ledger's job; a background pass
    quietly starting the economy's clock because somebody defined a badge would
    be a surprising thing for it to do."""
    assert badges.window_start(db, org, "season", org_today()) is None
    assert db.scalars(select(seasons.Season)).all() == []


def test_a_season_badge_is_skipped_rather_than_crashing(
    db, org, world, make_fact
):
    rule = make_rule(db, org, world)
    make_badge(db, org, world, rule, counted_over="season")
    for _ in range(3):
        make_fact(world["metric"], world["peter"], 500, this_month())

    report = badges.detect(db)

    assert report.skipped == 1
    assert holders(db, org) == set()


def test_last_months_work_does_not_earn_this_months_badge(
    db, org, world, make_fact
):
    rule = make_rule(db, org, world)
    make_badge(db, org, world, rule)
    last_month = org_now().replace(day=1, hour=12) - timedelta(days=5)
    for _ in range(3):
        make_fact(world["metric"], world["peter"], 500, last_month)

    badges.detect(db)

    assert holders(db, org) == set()


# -- What it pays ------------------------------------------------------------


def balance_of(db, org, user):
    season = seasons.current(db, org)
    return points.balance(db, season.id, user.id) if season else 0


def test_a_badge_can_pay_points(db, org, world, make_fact):
    rule = make_rule(db, org, world, points_each=0)
    badge = make_badge(db, org, world, rule, points=250)
    for _ in range(3):
        make_fact(world["metric"], world["peter"], 500, this_month())

    badges.detect(db)

    assert balance_of(db, org, world["peter"]) == 250


def test_a_badge_pays_nothing_by_default(db, org, world, make_fact):
    """**A badge is mostly not about points.** It is the part that survives a
    season reset, and making it pay well would turn it back into a balance."""
    rule = make_rule(db, org, world, points_each=0)
    make_badge(db, org, world, rule)
    for _ in range(3):
        make_fact(world["metric"], world["peter"], 500, this_month())

    badges.detect(db)

    assert balance_of(db, org, world["peter"]) == 0


def test_re_running_detection_does_not_pay_twice(db, org, world, make_fact):
    rule = make_rule(db, org, world, points_each=0)
    make_badge(db, org, world, rule, points=250)
    for _ in range(3):
        make_fact(world["metric"], world["peter"], 500, this_month())

    badges.detect(db)
    badges.detect(db)

    assert balance_of(db, org, world["peter"]) == 250


# -- Pinning one on by hand --------------------------------------------------


def test_a_manual_badge_can_be_given(db, org, world):
    badge = make_badge(db, org, world, name="Good egg")

    given = badges.earn(
        db, org, badge, world["peter"].id, period_anchor=None,
        reason="Covered a shift", awarded_by_user_id=world["admin"].id,
    )

    assert given is not None


def test_a_manual_badge_can_be_given_twice(db, org, world):
    """A manager pinning the same badge on somebody twice meant to."""
    badge = make_badge(db, org, world, name="Good egg")
    for _ in range(2):
        badges.earn(
            db, org, badge, world["peter"].id, period_anchor=None,
            awarded_by_user_id=world["admin"].id,
        )

    assert len(db.scalars(select(BadgeAward)).all()) == 2


# -- What somebody holds -----------------------------------------------------


def test_holding_one_badge_four_times_reads_as_one_badge(db, org, world):
    """**Collapsed, with a count.** A profile listing "Closer" four times reads
    as a bug; the number is the interesting part anyway — it is the difference
    between a good month and a habit."""
    badge = make_badge(db, org, world, name="Closer")
    for month in range(4):
        badges.earn(
            db, org, badge, world["peter"].id,
            period_anchor=date(2027, month + 1, 1),
        )

    held = badges.held_by(db, org.id, world["peter"].id)

    assert len(held) == 1
    assert held[0].times == 4


def test_somebody_with_none_holds_none(db, org, world):
    assert badges.held_by(db, org.id, world["peter"].id) == []


# -- How close somebody is ---------------------------------------------------


def test_progress_says_what_is_left(db, org, world, make_fact):
    """**The half of a badge that changes behaviour.** The badge rewards what
    already happened; "one more this month" is the reason to do something
    today."""
    rule = make_rule(db, org, world)
    make_badge(db, org, world, rule)
    for _ in range(2):
        make_fact(world["metric"], world["peter"], 500, this_month())

    progress = badges.progress_for(db, org, world["peter"].id)

    assert [(p.have, p.need, p.remaining) for p in progress] == [(2, 3, 1)]


def test_a_badge_nobody_has_started_is_not_listed(db, org, world, make_fact):
    """A list of everything somebody could theoretically earn is a catalogue,
    and nobody reads a catalogue."""
    rule = make_rule(db, org, world)
    make_badge(db, org, world, rule)

    assert badges.progress_for(db, org, world["peter"].id) == []


def test_a_badge_already_earned_is_not_listed_as_progress(
    db, org, world, make_fact
):
    rule = make_rule(db, org, world)
    make_badge(db, org, world, rule)
    for _ in range(3):
        make_fact(world["metric"], world["peter"], 500, this_month())

    assert badges.progress_for(db, org, world["peter"].id) == []


def test_the_closest_badge_comes_first(db, org, world, make_fact):
    rule = make_rule(db, org, world)
    make_badge(db, org, world, rule, name="Three", threshold=3)
    make_badge(db, org, world, rule, name="Ten", threshold=10)
    for _ in range(2):
        make_fact(world["metric"], world["peter"], 500, this_month())

    progress = badges.progress_for(db, org, world["peter"].id)

    assert [p.name for p in progress] == ["Three", "Ten"]


# -- What the table refuses --------------------------------------------------


def test_a_counted_badge_needs_something_to_count(db, org, world):
    """Or the columns silently mean nothing."""
    with pytest.raises(IntegrityError):
        make_badge(db, org, world, kind="count", threshold=None,
                   counted_over=None, achievement_rule_id=None)


def test_a_manual_badge_cannot_carry_a_threshold(db, org, world):
    rule = make_rule(db, org, world)
    with pytest.raises(IntegrityError):
        make_badge(db, org, world, kind="manual", threshold=3,
                   counted_over="month", achievement_rule_id=rule.id)


def test_two_badges_cannot_share_a_name(db, org, world):
    make_badge(db, org, world, name="Closer")

    with pytest.raises(IntegrityError):
        make_badge(db, org, world, name="Closer")


# -- Against the announcement it counts --------------------------------------


def test_the_badge_and_the_wall_count_the_same_work(
    db, org, world, make_fact
):
    """**The reason the predicate lives in one module.** A badge saying ten
    while the wall announced eight is worse than either being wrong alone,
    because then neither can be trusted."""
    rule = make_rule(db, org, world, threshold=100)
    make_badge(db, org, world, rule, threshold=3)
    for value in (500, 50, 600, 20, 700):
        make_fact(world["metric"], world["peter"], value, this_month())

    announced = notifications.detect_rules(db)
    badges.detect(db)
    progress = badges.progress_for(db, org, world["peter"].id)

    # Three cleared the bar: three announcements, and the badge earned on
    # exactly those three with nothing left partway.
    assert announced.emitted == 3
    assert world["peter"].id in holders(db, org)
    assert progress == []
