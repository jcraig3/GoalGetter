"""Spending points: the wallet, cosmetics, and the prize wheel.

**In the economy this was measured against, lifetime points equalled reward
points because nothing was ever spent.** The fix is somewhere to spend them —
but only if spending is something people will actually do, and the most
important test in this file is the first one: buying something never costs
anybody their place on the table. A purchase that dropped you down the
rankings is a purchase nobody makes, and then this is the dead economy again
with a shop attached.
"""

import random
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import points, seasons, tiers, unlocks, wheel
from app.models import PointAward, Tier, Unlock, Unlockable, WheelPrize, WheelSpin
from tests.conftest import org_today


@pytest.fixture
def world(db, org, make_team, make_user):
    enterprise = make_team("Enterprise")
    db.flush()
    return {
        "admin": make_user("admin", name="Admin"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", enterprise, name="Clark Kent"),
    }


def earn(db, org, user, amount, subject_id=1):
    return points.award(
        db, org=org, user_id=user.id, points=amount,
        event_key="goal.achieved", subject_type="goal",
        subject_id=subject_id, reason="Hit a goal",
    )


def item(db, org, *, name="Gold ring", kind="ring", value="#f5b301", price=300, **extra):
    row = Unlockable(
        organization_id=org.id, name=name, kind=kind, value=value, price=price, **extra
    )
    db.add(row)
    db.flush()
    return row


def rank_of(db, org, user):
    table = points.standings(db, seasons.current(db, org))
    return next((row.rank for row in table if row.user_id == user.id), None)


# -- The wallet --------------------------------------------------------------


def test_spending_never_costs_anybody_their_place(db, org, world):
    """**The property the whole of spending rests on.** Peter is ahead by 100,
    spends 400, and is still ahead — because the table ranks what was earned,
    and spending is not un-earning."""
    earn(db, org, world["peter"], 1000)
    earn(db, org, world["clark"], 900, subject_id=2)

    unlocks.buy(db, org, item(db, org, price=400), world["peter"].id)

    assert rank_of(db, org, world["peter"]) == 1
    assert points.balance(db, seasons.current(db, org).id, world["peter"].id) == 1000


def test_the_wallet_is_what_was_earned_less_what_was_spent(db, org, world):
    earn(db, org, world["peter"], 1000)

    unlocks.buy(db, org, item(db, org, price=400), world["peter"].id)

    assert points.wallet(db, org.id, world["peter"].id) == 600


def test_the_wallet_carries_across_seasons(db, org, world):
    """A season reset keeps the *ranking* catchable, and the wallet ranks
    nothing — so wiping somebody's savings every quarter would read as theft."""
    from datetime import date, timedelta

    from app.models import Season

    old = Season(
        organization_id=org.id, name="Last",
        starts_on=org_today() - timedelta(days=200),
        ends_on=org_today() - timedelta(days=110),
    )
    db.add(old)
    db.flush()
    db.add(
        PointAward(
            organization_id=org.id, season_id=old.id, user_id=world["peter"].id,
            points=800, event_key="goal.achieved", subject_type="goal",
            subject_id=9, reason="Last season",
        )
    )
    db.flush()

    assert points.wallet(db, org.id, world["peter"].id) == 800


def test_a_correction_is_not_a_spend(db, org, world):
    """A negative `manual` row un-earns points paid by mistake, so it *should*
    move the table. Only wallet movements are kept off it."""
    earn(db, org, world["peter"], 1000)
    points.award(
        db, org=org, user_id=world["peter"].id, points=-400,
        event_key=points.MANUAL, subject_type="user", subject_id=world["admin"].id,
        reason="Paid in error", awarded_by_user_id=world["admin"].id,
    )

    assert points.balance(db, seasons.current(db, org).id, world["peter"].id) == 600


def test_spending_more_than_the_wallet_holds_is_refused(db, org, world):
    earn(db, org, world["peter"], 100)

    with pytest.raises(points.NotEnough) as refused:
        unlocks.buy(db, org, item(db, org, price=300), world["peter"].id)

    assert "300" in str(refused.value) and "100" in str(refused.value)


def test_a_refused_spend_takes_nothing(db, org, world):
    earn(db, org, world["peter"], 100)

    with pytest.raises(points.NotEnough):
        unlocks.buy(db, org, item(db, org, price=300), world["peter"].id)

    assert points.wallet(db, org.id, world["peter"].id) == 100


def test_the_tier_ladder_is_drawn_over_what_was_earned(db, org, world, make_user):
    """Spending must not drag the suggested rungs down either — they are drawn
    over the same number the table ranks on."""
    for index in range(8):
        person = make_user("agent", name=f"Agent {index}")
        earn(db, org, person, 1000, subject_id=100 + index)
        if index < 4:
            db.add(Unlockable(
                organization_id=org.id, name=f"Ring {index}", kind="ring",
                value="#123456", price=900,
            ))
            db.flush()
            bought = db.scalars(select(Unlockable).where(
                Unlockable.name == f"Ring {index}")).one()
            unlocks.buy(db, org, bought, person.id)

    suggested = tiers.suggest(db, seasons.current(db, org))

    assert all(s.threshold >= 1000 for s in suggested)


# -- Cosmetics ---------------------------------------------------------------


def test_buying_one_wears_it_straight_away(db, org, world):
    """Somebody who has just bought a ring wants to see it, not to find a
    second button."""
    earn(db, org, world["peter"], 1000)

    bought = unlocks.buy(db, org, item(db, org), world["peter"].id)

    assert bought.equipped is True
    assert unlocks.worn_by(db, {world["peter"].id})[world["peter"].id].ring == "#f5b301"


def test_a_second_ring_does_not_replace_the_first_until_asked(db, org, world):
    earn(db, org, world["peter"], 1000)
    unlocks.buy(db, org, item(db, org, name="Gold", value="#f5b301"), world["peter"].id)

    unlocks.buy(db, org, item(db, org, name="Blue", value="#2255ff"), world["peter"].id)

    assert unlocks.worn_by(db, {world["peter"].id})[world["peter"].id].ring == "#f5b301"


def test_putting_one_on_takes_the_other_off(db, org, world):
    """The take-off is flushed first, or the unique index sees two worn rings
    for an instant and refuses an ordinary change of mind."""
    earn(db, org, world["peter"], 1000)
    unlocks.buy(db, org, item(db, org, name="Gold", value="#f5b301"), world["peter"].id)
    blue = unlocks.buy(
        db, org, item(db, org, name="Blue", value="#2255ff"), world["peter"].id
    )

    unlocks.equip(db, blue)

    assert unlocks.worn_by(db, {world["peter"].id})[world["peter"].id].ring == "#2255ff"


def test_a_ring_and_a_title_are_worn_together(db, org, world):
    earn(db, org, world["peter"], 1000)
    unlocks.buy(db, org, item(db, org), world["peter"].id)
    unlocks.buy(
        db, org, item(db, org, name="Closer", kind="title", value="The Closer", price=200),
        world["peter"].id,
    )

    worn = unlocks.worn_by(db, {world["peter"].id})[world["peter"].id]

    assert (worn.ring, worn.title) == ("#f5b301", "The Closer")


def test_buying_the_same_thing_twice_is_refused_before_anything_is_spent(
    db, org, world
):
    """**Checked after the lock, not before.** Checked first, a double-click
    would pass twice, spend twice, and lose the second copy to the unique
    index — points taken for nothing."""
    earn(db, org, world["peter"], 1000)
    ring = item(db, org)
    unlocks.buy(db, org, ring, world["peter"].id)

    with pytest.raises(unlocks.AlreadyOwned):
        unlocks.buy(db, org, ring, world["peter"].id)

    assert points.wallet(db, org.id, world["peter"].id) == 700


def test_a_retired_cosmetic_cannot_be_bought(db, org, world):
    earn(db, org, world["peter"], 1000)

    with pytest.raises(ValueError):
        unlocks.buy(db, org, item(db, org, enabled=False), world["peter"].id)


def test_a_retired_cosmetic_stays_on_whoever_bought_it(db, org, world):
    """Somebody paid for it. Retiring means it can no longer be *bought*, not
    that it comes off the people who have it."""
    earn(db, org, world["peter"], 1000)
    ring = item(db, org)
    unlocks.buy(db, org, ring, world["peter"].id)

    ring.enabled = False
    db.flush()

    assert unlocks.worn_by(db, {world["peter"].id})[world["peter"].id].ring == "#f5b301"


def test_what_was_paid_survives_a_price_change(db, org, world):
    earn(db, org, world["peter"], 1000)
    ring = item(db, org, price=300)
    bought = unlocks.buy(db, org, ring, world["peter"].id)

    ring.price = 50
    db.flush()

    assert bought.paid == 300


def test_one_query_dresses_a_whole_table(db, org, world):
    """Batched, never per row — a board of ten is ten lookups otherwise, on
    every poll, on every television."""
    earn(db, org, world["peter"], 1000)
    earn(db, org, world["clark"], 1000, subject_id=2)
    ring = item(db, org)
    unlocks.buy(db, org, ring, world["peter"].id)
    unlocks.buy(db, org, ring, world["clark"].id)

    worn = unlocks.worn_by(db, {world["peter"].id, world["clark"].id})

    assert set(worn) == {world["peter"].id, world["clark"].id}


def test_a_ring_must_be_a_colour(db, org):
    """Anything else in that column ends up in a `style` attribute on a public
    television."""
    assert unlocks.valid_value("ring", "#f5b301") is None
    assert unlocks.valid_value("ring", "red; background:url(x)") is not None
    assert unlocks.valid_value("title", "  ") is not None


def test_two_worn_rings_are_unstorable(db, org, world):
    earn(db, org, world["peter"], 1000)
    gold = unlocks.buy(db, org, item(db, org, name="Gold"), world["peter"].id)
    blue = unlocks.buy(db, org, item(db, org, name="Blue", value="#2255ff"), world["peter"].id)
    assert gold.equipped and not blue.equipped

    blue.equipped = True
    with pytest.raises(IntegrityError):
        db.flush()


# -- The wheel ---------------------------------------------------------------


def segment(db, org, label, kind="nothing", points_=0, weight=1, stock=None):
    row = WheelPrize(
        organization_id=org.id, label=label, kind=kind, points=points_,
        weight=weight, stock=stock,
    )
    db.add(row)
    db.flush()
    return row


def open_wheel(db, org, cost=100):
    settings = wheel.settings_for(db, org.id)
    settings.spin_cost = cost
    settings.enabled = True
    db.flush()
    return settings


class Always(random.Random):
    """A draw that lands on the segment you name."""

    def __init__(self, label):
        super().__init__()
        self.label = label

    def choices(self, population, weights=None, k=1):
        return [next(p for p in population if p.label == self.label)]


def test_a_spin_takes_the_cost(db, org, world):
    earn(db, org, world["peter"], 1000)
    open_wheel(db, org, cost=100)
    segment(db, org, "So close")

    wheel.spin(db, org, world["peter"].id, rng=Always("So close"))

    assert points.wallet(db, org.id, world["peter"].id) == 900


def test_a_points_win_lands_in_the_wallet(db, org, world):
    earn(db, org, world["peter"], 1000)
    open_wheel(db, org, cost=100)
    segment(db, org, "+50", kind="points", points_=50)
    segment(db, org, "So close", weight=9)

    wheel.spin(db, org, world["peter"].id, rng=Always("+50"))

    assert points.wallet(db, org.id, world["peter"].id) == 950


def test_a_lucky_spin_does_not_climb_the_table(db, org, world):
    """**Winnings go to the wallet and never to the table.** Otherwise spinning
    becomes a way to climb it, and the ranking starts measuring luck and
    appetite for risk rather than work."""
    earn(db, org, world["peter"], 1000)
    earn(db, org, world["clark"], 1050, subject_id=2)
    open_wheel(db, org, cost=100)
    segment(db, org, "+90", kind="points", points_=90)
    segment(db, org, "So close", weight=20)

    for _ in range(3):
        wheel.spin(db, org, world["peter"].id, rng=Always("+90"))

    assert rank_of(db, org, world["peter"]) == 2


def test_a_real_prize_waits_to_be_handed_over(db, org, world):
    """A real prize with no list behind it is a promise that gets forgotten on
    a Friday afternoon."""
    earn(db, org, world["peter"], 1000)
    open_wheel(db, org)
    segment(db, org, "Long lunch", kind="prize")

    won = wheel.spin(db, org, world["peter"].id, rng=Always("Long lunch"))

    assert won.given_at is None
    assert [s.id for s in wheel.waiting(db, org.id, None)] == [won.id]


def test_a_miss_is_finished_the_moment_it_stops(db, org, world):
    earn(db, org, world["peter"], 1000)
    open_wheel(db, org)
    segment(db, org, "So close")

    won = wheel.spin(db, org, world["peter"].id, rng=Always("So close"))

    assert won.given_at is not None
    assert wheel.waiting(db, org.id, None) == []


def test_the_last_one_in_stock_leaves_the_draw(db, org, world):
    earn(db, org, world["peter"], 1000)
    open_wheel(db, org)
    segment(db, org, "Gift card", kind="prize", stock=1)
    segment(db, org, "So close")

    wheel.spin(db, org, world["peter"].id, rng=Always("Gift card"))

    assert [c.prize.label for c in wheel.chances(db, org.id)] == ["So close"]


def test_the_odds_shown_are_the_weights_used(db, org, world):
    """**Computed, never typed**, so they cannot disagree with the draw."""
    segment(db, org, "Rare", kind="prize", weight=1)
    segment(db, org, "Common", weight=3)

    shown = {c.prize.label: c.chance for c in wheel.chances(db, org.id)}

    assert shown == {"Rare": 0.25, "Common": 0.75}


def test_the_draw_follows_the_weights(db, org, world):
    """Over enough spins the rare segment comes up about as often as it says —
    the test that the odds shown are the odds used."""
    earn(db, org, world["peter"], 100_000)
    open_wheel(db, org, cost=10)
    segment(db, org, "Rare", kind="prize", weight=1)
    segment(db, org, "Common", weight=3)

    rng = random.Random(7)
    landed = [wheel.spin(db, org, world["peter"].id, rng=rng).label for _ in range(400)]

    assert 60 <= landed.count("Rare") <= 140


def test_a_wheel_that_would_print_points_is_refused(db, org, world):
    """**A spin that pays back as much as it costs is a points printer.** Spin
    forever, and the wallet only grows."""
    open_wheel(db, org, cost=100)
    segment(db, org, "+250", kind="points", points_=250, weight=1)
    segment(db, org, "So close", weight=1)

    with pytest.raises(wheel.Unfair) as refused:
        wheel.check_fair(db, org.id)

    # Half the time +250, half the time nothing: 125 back on a 100 spin.
    assert "125" in str(refused.value)


def test_a_wheel_that_pays_back_less_than_it_costs_is_fine(db, org, world):
    """+150 on half the wheel returns 75 a spin against a cost of 100 — a
    wheel that is a good time and still takes more than it gives."""
    open_wheel(db, org, cost=100)
    segment(db, org, "+150", kind="points", points_=150, weight=1)
    segment(db, org, "So close", weight=1)

    wheel.check_fair(db, org.id)


def test_exactly_breaking_even_is_refused_too(db, org, world):
    """Break-even is the boundary on the wrong side: a wheel that returns what
    it costs lets somebody spin for free forever, for the prizes."""
    open_wheel(db, org, cost=100)
    segment(db, org, "+200", kind="points", points_=200, weight=1)
    segment(db, org, "So close", weight=1)

    with pytest.raises(wheel.Unfair):
        wheel.check_fair(db, org.id)


def test_real_prizes_do_not_count_toward_the_payout(db, org, world):
    """A long lunch is not a withdrawal from the economy."""
    open_wheel(db, org, cost=100)
    segment(db, org, "Long lunch", kind="prize", weight=5)
    segment(db, org, "+50", kind="points", points_=50, weight=1)

    wheel.check_fair(db, org.id)


def test_selling_out_can_tip_a_wheel_over_and_spinning_notices(db, org, world):
    """A sold-out gift card leaving the draw raises every other segment's share,
    and that can make a wheel that was fair yesterday print points today. The
    spin checks again, over what is actually left."""
    earn(db, org, world["peter"], 10_000)
    open_wheel(db, org, cost=100)
    segment(db, org, "Gift card", kind="prize", weight=3, stock=1)
    segment(db, org, "+150", kind="points", points_=150, weight=1)
    wheel.check_fair(db, org.id)

    wheel.spin(db, org, world["peter"].id, rng=Always("Gift card"))

    with pytest.raises(wheel.NothingToWin):
        wheel.spin(db, org, world["peter"].id, rng=Always("+150"))


def test_a_switched_off_wheel_cannot_be_spun(db, org, world):
    earn(db, org, world["peter"], 1000)
    segment(db, org, "So close")

    with pytest.raises(wheel.NothingToWin):
        wheel.spin(db, org, world["peter"].id)


def test_an_empty_wheel_cannot_be_spun(db, org, world):
    """Otherwise it is a way to lose points to an animation."""
    earn(db, org, world["peter"], 1000)
    open_wheel(db, org)

    with pytest.raises(wheel.NothingToWin):
        wheel.spin(db, org, world["peter"].id)


def test_a_spin_that_cannot_be_paid_for_draws_nothing(db, org, world):
    earn(db, org, world["peter"], 50)
    open_wheel(db, org, cost=100)
    segment(db, org, "Gift card", kind="prize", stock=1)

    with pytest.raises(points.NotEnough):
        wheel.spin(db, org, world["peter"].id, rng=Always("Gift card"))

    assert db.scalars(select(WheelSpin)).all() == []
    assert db.scalars(select(WheelPrize)).one().stock == 1


def test_what_was_won_survives_the_segment_being_renamed(db, org, world):
    earn(db, org, world["peter"], 1000)
    open_wheel(db, org)
    lunch = segment(db, org, "Long lunch", kind="prize")

    won = wheel.spin(db, org, world["peter"].id, rng=Always("Long lunch"))
    lunch.label = "Short lunch"
    db.flush()

    assert won.label == "Long lunch"


def test_the_system_randomness_is_not_pythons_default(db, org):
    """Python's default generator is predictable from enough of its output, and
    a draw that pays out points is exactly the thing somebody would study."""
    assert isinstance(wheel._SYSTEM, random.SystemRandom)
