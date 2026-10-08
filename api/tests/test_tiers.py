"""The ladder, and where to put its rungs.

**A tier read against a number that only grows is a tier everybody eventually
has.** The account this was measured against had a top tier at 100,000 points
and a top dozen reps between 165,000 and 178,000: all of them Platinum for over
a year, with nothing above it and nobody below able to tell the difference
between second place and twelfth.

So the properties worth testing are the two ways a rung goes wrong — too high
to aim at, too low to mean anything — and the suggestion that exists to stop an
admin choosing either by typing a round number into a form.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app import points, seasons, tiers
from app.models import Tier


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    db.flush()
    return {
        "enterprise": enterprise,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "metric": make_metric("calls_made"),
    }


def rung(db, org, name, threshold):
    row = Tier(organization_id=org.id, name=name, threshold=threshold)
    db.add(row)
    db.flush()
    return row


def standard(db, org):
    return [
        rung(db, org, "Bronze", 100),
        rung(db, org, "Silver", 500),
        rung(db, org, "Gold", 1000),
    ]


def give(db, org, user, amount, subject_id):
    return points.award(
        db, org=org, user_id=user.id, points=amount,
        event_key="goal.achieved", subject_type="goal",
        subject_id=subject_id, reason="Hit a goal",
    )


# -- Reading the ladder ------------------------------------------------------


def test_the_rungs_come_back_lowest_first(db, org):
    rung(db, org, "Gold", 1000)
    rung(db, org, "Bronze", 100)

    assert [t.name for t in tiers.ladder(db, org.id)] == ["Bronze", "Gold"]


def test_a_balance_holds_the_highest_rung_it_reaches(db, org):
    rungs = standard(db, org)

    assert tiers.tier_for(750, rungs).name == "Silver"


def test_exactly_on_a_rung_holds_it(db, org):
    """Off-by-one on a threshold is the kind of thing somebody notices at
    999 points and never forgets."""
    rungs = standard(db, org)

    assert tiers.tier_for(1000, rungs).name == "Gold"


def test_below_the_first_rung_is_nothing_rather_than_the_first(db, org):
    rungs = standard(db, org)

    assert tiers.tier_for(50, rungs) is None


def test_no_ladder_means_nobody_holds_anything(db, org):
    assert tiers.tier_for(50_000, []) is None


def test_the_distance_to_the_next_rung(db, org):
    """**The only part of a ladder that changes behaviour.** The badge rewards
    what already happened; the distance is the reason to do something this
    week."""
    rungs = standard(db, org)

    reached = tiers.standing_for(750, rungs)

    assert (reached.current.name, reached.next.name, reached.to_next) == (
        "Silver",
        "Gold",
        250,
    )


def test_the_top_rung_has_nothing_after_it(db, org):
    rungs = standard(db, org)

    reached = tiers.standing_for(5000, rungs)

    assert reached.next is None and reached.to_next is None


def test_somebody_below_the_bottom_is_told_what_to_aim_at(db, org):
    """Nothing held, but a target — which is exactly who a ladder is for."""
    rungs = standard(db, org)

    reached = tiers.standing_for(10, rungs)

    assert reached.current is None
    assert (reached.next.name, reached.to_next) == ("Bronze", 90)


# -- What the table refuses --------------------------------------------------


def test_two_rungs_cannot_sit_at_the_same_height(db, org):
    """Not a ladder — two names for one thing, and `tier_for` would have to
    pick between them."""
    rung(db, org, "Bronze", 100)

    with pytest.raises(IntegrityError):
        rung(db, org, "Also bronze", 100)


def test_a_rung_at_zero_is_refused(db, org):
    """It would be held by everybody who has never scored, which is the "says
    nothing" failure in its purest form."""
    with pytest.raises(IntegrityError):
        rung(db, org, "Participation", 0)


# -- Suggestions from the real distribution ----------------------------------


def floor(db, org, make_user, amounts):
    """A board with one person per amount given."""
    for index, amount in enumerate(amounts):
        person = make_user("agent", name=f"Agent {index}")
        give(db, org, person, amount, index + 1)
    return seasons.current(db, org)


def test_too_few_people_is_no_suggestion_at_all(db, org, world, make_user):
    """**With four people the 95th percentile is "the highest score"**, and a
    ladder built from it has a top rung exactly one person can stand on —
    which is the failure this exists to prevent, arrived at by way of the
    thing meant to prevent it."""
    season = floor(db, org, make_user, [100, 200, 300, 400])

    assert tiers.suggest(db, season) == []


def test_rungs_are_drawn_from_what_people_actually_scored(
    db, org, world, make_user
):
    season = floor(db, org, make_user, [100, 200, 300, 400, 500, 600, 700, 800])

    suggested = tiers.suggest(db, season)

    assert [s.name for s in suggested] == ["Bronze", "Silver", "Gold", "Platinum"]
    assert all(100 <= s.threshold <= 800 for s in suggested)


def test_the_rungs_climb(db, org, world, make_user):
    season = floor(db, org, make_user, [100, 200, 300, 400, 500, 600, 700, 800])

    thresholds = [s.threshold for s in tiers.suggest(db, season)]

    assert thresholds == sorted(thresholds)
    assert len(set(thresholds)) == len(thresholds)


def test_the_top_rung_is_worth_something(db, org, world, make_user):
    """**A tier a third of the floor holds is a participation award.** The
    point of the highest one is that seeing somebody wearing it tells you
    something."""
    season = floor(db, org, make_user, list(range(100, 2100, 100)))  # 20 people

    top = tiers.suggest(db, season)[-1]

    assert top.would_hold <= 3


def test_the_bottom_rung_is_not_everybody(db, org, world, make_user):
    """A rung everybody who turns up holds fails quietly rather than loudly,
    and it fails all the same."""
    season = floor(db, org, make_user, list(range(100, 2100, 100)))

    bottom = tiers.suggest(db, season)[0]

    assert bottom.would_hold < 20


def test_a_flat_floor_still_produces_a_ladder(db, org, world, make_user):
    """Half a floor on exactly the same number puts two percentiles on one
    value. Two rungs at one height is not a ladder, and the table refuses it
    anyway."""
    season = floor(db, org, make_user, [100] * 10)

    thresholds = [s.threshold for s in tiers.suggest(db, season)]

    assert len(set(thresholds)) == len(thresholds)


def test_it_is_a_distribution_of_people_not_of_awards(
    db, org, world, make_user
):
    """**Somebody who earned 900 in one win and somebody who earned it in
    thirty are the same height on this ladder.** Percentiles over raw award
    rows would put the second one much higher."""
    grinder = make_user("agent", name="Grinder")
    for n in range(30):
        give(db, org, grinder, 30, 500 + n)
    for index, amount in enumerate([900] * 8):
        give(db, org, make_user("agent", name=f"Closer {index}"), amount, index)

    season = seasons.current(db, org)
    suggested = tiers.suggest(db, season)

    # Everybody has 900, so every rung sits there — one point apart where the
    # nudge had to separate them, and nowhere near 30.
    assert all(s.threshold >= 900 for s in suggested)


def test_a_person_corrected_back_to_nothing_is_not_in_the_sample(
    db, org, world, make_user
):
    """They are not on the board, so they must not be in the distribution the
    board's ladder is drawn from."""
    season = floor(db, org, make_user, [100, 200, 300, 400, 500, 600, 700, 800])
    ghost = make_user("agent", name="Ghost")
    give(db, org, ghost, 5000, 900)
    points.award(
        db, org=org, user_id=ghost.id, points=-5000, event_key=points.MANUAL,
        subject_type="user", subject_id=world["admin"].id, reason="Undo",
        awarded_by_user_id=world["admin"].id,
    )

    top = tiers.suggest(db, season)[-1]

    assert top.threshold <= 800
