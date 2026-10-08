"""Detection: noticing something happened, and saying it exactly once.

The whole design rests on one claim — that a unique index can replace stored
"last notified" state — so most of what is below is attempts to make the job
announce something twice.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app import events, notifications
from app.models import Goal, Notification

WHEN = datetime(2026, 8, 12, 15, 0, tzinfo=UTC)
ANCHOR = WHEN.date()


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        # On another team, and present so that a manager lookup which forgot to
        # filter by team would notify them and fail loudly.
        "other_manager": make_user("manager", smb, name="Other Manager"),
        "alice": make_user("agent", enterprise, name="Alice"),
        "bob": make_user("agent", enterprise, name="Bob"),
        "stranger": make_user("agent", smb, name="Stranger"),
        "loner": make_user("agent", None, name="Loner"),
        "metric": make_metric("calls_made"),
    }


def make_goal(db, org, world, **overrides):
    fields = {
        "organization_id": org.id,
        "metric_definition_id": world["metric"].id,
        "subject_type": "user",
        "subject_user_id": world["alice"].id,
        "target_value": Decimal(100),
        "period_type": "month",
        "period_anchor": date(2026, 8, 1),
    }
    fields.update(overrides)
    goal = Goal(**fields)
    db.add(goal)
    db.flush()
    return goal


def rows(db, event_key: str | None = None) -> list[Notification]:
    query = select(Notification).order_by(Notification.id)
    if event_key:
        query = query.where(Notification.event_key == event_key)
    return list(db.scalars(query).all())


def keys_for(db, user_id: int) -> set[str]:
    return {
        n.event_key
        for n in db.scalars(
            select(Notification).where(Notification.user_id == user_id)
        ).all()
    }


# ── Saying it once ───────────────────────────────────────────────────────────


def test_a_second_pass_announces_nothing_new(db, org, world, make_fact):
    """The claim the whole design rests on.

    Detection runs every few minutes forever. If a pass could re-announce, the
    bell would fill with the same sentence until the period ended.
    """
    make_goal(db, org, world)
    make_fact(world["metric"], world["alice"], 150, WHEN)

    first = notifications.detect(db)
    before = db.scalar(select(func.count()).select_from(Notification))

    second = notifications.detect(db)
    after = db.scalar(select(func.count()).select_from(Notification))

    assert first.emitted > 0
    assert second.emitted == 0
    assert before == after


def test_ten_passes_are_the_same_as_one(db, org, world, make_fact):
    """A restarted worker re-runs a pass it had partly finished."""
    make_goal(db, org, world)
    make_fact(world["metric"], world["alice"], 150, WHEN)

    for _ in range(10):
        notifications.detect(db)

    assert len(rows(db, "goal.achieved")) == len(_expected_recipients(world))


def test_the_same_goal_announces_again_next_period(db, org, world, make_fact):
    """August's "you hit it" and September's are different events.

    `period_anchor` is the only thing that distinguishes them, so a goal that
    recurs must be able to say the same sentence once per period.
    """
    goal = make_goal(db, org, world)
    make_fact(world["metric"], world["alice"], 150, WHEN)
    notifications.detect(db)

    goal.period_anchor = date(2026, 9, 1)
    db.flush()
    make_fact(world["metric"], world["alice"], 150, datetime(2026, 9, 10, 15, tzinfo=UTC))
    notifications.detect(db)

    anchors = {n.period_anchor for n in rows(db, "goal.achieved")}
    assert anchors == {date(2026, 8, 1), date(2026, 9, 1)}


def test_an_event_with_no_period_still_only_fires_once(db, org, world):
    """`NULLS NOT DISTINCT` on the index, tested directly.

    Postgres treats NULLs as distinct in a unique index by default, so without
    that clause an event carrying no period would insert again on every single
    job cycle, forever. It is one word in a migration and nothing else would
    have caught losing it.
    """
    for _ in range(3):
        notifications.emit(
            db,
            org_id=org.id,
            user_id=world["alice"].id,
            event=events.GOAL_ACHIEVED,
            subject_type="competition",
            subject_id=7,
            period_anchor=None,
            title="Sprint over",
        )

    assert len(rows(db)) == 1


# ── What gets announced ──────────────────────────────────────────────────────


def test_hitting_a_target_is_announced(db, org, world, make_fact):
    make_goal(db, org, world)
    make_fact(world["metric"], world["alice"], 150, WHEN)
    notifications.detect(db)
    assert "goal.achieved" in keys_for(db, world["alice"].id)


def test_falling_short_is_not_announced_as_a_win(db, org, world, make_fact):
    make_goal(db, org, world)
    make_fact(world["metric"], world["alice"], 40, WHEN)
    notifications.detect(db)
    assert "goal.achieved" not in keys_for(db, world["alice"].id)


def test_a_new_goal_announces_itself(db, org, world):
    """Assignment runs through the same idempotent path as everything else, so
    a goal spawned by the recurrence job announces itself without that job
    knowing anything about notifications."""
    make_goal(db, org, world)
    notifications.detect(db, now=WHEN)
    assert "goal.assigned" in keys_for(db, world["alice"].id)


def test_a_finished_goal_is_not_announced_as_new(db, org, world):
    """P4-1: August's goal, looked at in September, is not news."""
    make_goal(db, org, world)
    notifications.detect(db, now=datetime(2026, 9, 3, 15, tzinfo=UTC))
    assert keys_for(db, world["alice"].id) == set()


def test_somebody_activated_late_is_not_told_about_last_month(db, org, world, make_fact):
    """P4-1, as it happened: Alice was not active through August, is turned on
    in October, and the next pass told her August's goal was new and "100%
    gone". Only this month's goal is news; a late hit still counts."""
    world["alice"].status = "invited"
    db.flush()
    make_goal(db, org, world)  # August
    make_fact(world["metric"], world["alice"], 10, WHEN)
    october = make_goal(db, org, world, period_anchor=date(2026, 10, 1))
    notifications.detect(db, now=datetime(2026, 8, 30, 15, tzinfo=UTC))

    world["alice"].status = "active"
    db.flush()
    notifications.detect(db, now=datetime(2026, 10, 5, 23, tzinfo=UTC))

    told = db.scalars(
        select(Notification).where(Notification.user_id == world["alice"].id)
    ).all()
    assert [(n.event_key, n.subject_id) for n in told] == [("goal.assigned", october.id)]


def test_a_number_arriving_late_still_counts_as_a_hit(db, org, world, make_fact):
    """Finished goals stay in the loop for exactly this."""
    make_goal(db, org, world)
    make_fact(world["metric"], world["alice"], 150, WHEN)
    notifications.detect(db, now=datetime(2026, 9, 2, 9, tzinfo=UTC))
    assert "goal.achieved" in keys_for(db, world["alice"].id)


def test_an_archived_goal_says_nothing(db, org, world, make_fact):
    goal = make_goal(db, org, world)
    goal.archived_at = WHEN
    db.flush()
    make_fact(world["metric"], world["alice"], 150, WHEN)

    notifications.detect(db)
    assert rows(db) == []


# ── Running out of time ──────────────────────────────────────────────────────


def test_nothing_is_said_early_in_a_period(db, org, world, make_fact):
    """A latching event has exactly one shot.

    Spent on the 3rd of the month it is gone by the 25th, when it would have
    mattered. Nothing about being behind should be said until three quarters
    of the period has gone.
    """
    make_goal(db, org, world)  # August, and we look on the 4th
    make_fact(world["metric"], world["alice"], 10, datetime(2026, 8, 3, 15, tzinfo=UTC))

    notifications.detect(db, now=datetime(2026, 8, 4, 15, tzinfo=UTC))

    assert "goal.period_ending" not in keys_for(db, world["alice"].id)


def test_running_out_of_time_is_never_said_once_it_has_run_out(db, org, world, make_fact):
    """P4-1: "100% of August gone" is not a warning anybody can act on."""
    make_goal(db, org, world)
    make_fact(world["metric"], world["alice"], 10, WHEN)
    notifications.detect(db, now=datetime(2026, 9, 1, 12, tzinfo=UTC))
    assert "goal.period_ending" not in keys_for(db, world["alice"].id)


def test_running_out_of_time_is_announced_once_the_period_is_nearly_gone(
    db, org, world, make_fact
):
    """The same goal, the same shortfall, late in the month."""
    make_goal(db, org, world)
    make_fact(world["metric"], world["alice"], 10, WHEN)

    notifications.detect(db, now=datetime(2026, 8, 28, 15, tzinfo=UTC))

    assert "goal.period_ending" in keys_for(db, world["alice"].id)


def test_running_out_of_time_is_announced_late_not_early(db, org, world, make_fact):
    """A latching event has one shot, so it has to be spent when somebody can
    still act on it.

    Fired on the 3rd it would be gone by the 25th, when it matters. The
    threshold is three quarters through the period.
    """
    # A day period, so "elapsed" is unambiguous: this test is about the
    # threshold, not about how working days are counted.
    make_goal(db, org, world, period_type="day", period_anchor=date(2026, 8, 12))
    make_fact(world["metric"], world["alice"], 10, WHEN)

    # 17:00 in New York: most of the working day gone, the day not yet over.
    notifications.detect(db, now=datetime(2026, 8, 12, 21, tzinfo=UTC))

    # Over 75% of the working hours elapsed, so it fires; what matters is that
    # it fires at all and only once.
    warned = [n for n in rows(db) if n.event_key == "goal.period_ending"]
    assert len(warned) == len(_expected_recipients(world))


def test_a_goal_already_hit_is_never_told_it_is_running_out(db, org, world, make_fact):
    """The most irritating possible notification."""
    make_goal(db, org, world, period_type="day", period_anchor=date(2026, 8, 12))
    make_fact(world["metric"], world["alice"], 500, WHEN)

    notifications.detect(db)

    assert "goal.period_ending" not in keys_for(db, world["alice"].id)
    assert "goal.achieved" in keys_for(db, world["alice"].id)


# ── Who hears about it ───────────────────────────────────────────────────────


def _expected_recipients(world) -> list[int]:
    """Alice, and the manager of her team."""
    return [world["alice"].id, world["manager"].id]


def test_a_personal_goal_reaches_the_person_and_their_manager(
    db, org, world, make_fact
):
    make_goal(db, org, world)
    make_fact(world["metric"], world["alice"], 150, WHEN)
    notifications.detect(db)

    told = {n.user_id for n in rows(db, "goal.achieved")}
    assert told == set(_expected_recipients(world))


def test_nobody_outside_the_team_hears_about_it(db, org, world, make_fact):
    """A notification must never introduce somebody to a person they could not
    already see."""
    make_goal(db, org, world)
    make_fact(world["metric"], world["alice"], 150, WHEN)
    notifications.detect(db)

    told = {n.user_id for n in rows(db)}
    assert world["stranger"].id not in told
    assert world["bob"].id not in told
    # Managers are resolved from the subject's team, not from the role alone.
    assert world["other_manager"].id not in told


def test_a_team_goal_reaches_the_whole_team(db, org, world, make_fact):
    """A target set for a team is one every member is working toward. Telling
    only the manager would make it the manager's goal."""
    make_goal(
        db, org, world,
        subject_type="team",
        subject_user_id=None,
        subject_team_id=world["enterprise"].id,
    )
    make_fact(world["metric"], world["alice"], 150, WHEN)
    notifications.detect(db)

    told = {n.user_id for n in rows(db, "goal.achieved")}
    assert told == {world["alice"].id, world["bob"].id, world["manager"].id}


def test_a_team_goal_is_measured_as_the_team_not_as_one_member(
    db, org, world, make_fact
):
    """The bug this nearly shipped with.

    `current_value` resolves scope from an actor, and an agent's scope is
    themselves — so evaluating a team goal as one of its members computes that
    member's contribution and announces it as the team's. Here neither Alice nor
    Bob clears 100 alone; together they do.
    """
    make_goal(
        db, org, world,
        subject_type="team",
        subject_user_id=None,
        subject_team_id=world["enterprise"].id,
    )
    make_fact(world["metric"], world["alice"], 60, WHEN)
    make_fact(world["metric"], world["bob"], 60, WHEN)

    notifications.detect(db)

    assert "goal.achieved" in keys_for(db, world["alice"].id)


def test_a_hidden_person_hears_nothing(db, org, world, make_fact):
    world["alice"].hidden_at = WHEN
    db.flush()
    make_goal(db, org, world)
    make_fact(world["metric"], world["alice"], 150, WHEN)

    notifications.detect(db)
    assert rows(db) == []


def test_someone_on_no_team_still_hears_about_their_own_goal(db, org, world, make_fact):
    """No team means no manager to copy in, not no notification."""
    make_goal(db, org, world, subject_user_id=world["loner"].id)
    make_fact(world["metric"], world["loner"], 150, WHEN)

    notifications.detect(db)

    told = {n.user_id for n in rows(db, "goal.achieved")}
    assert told == {world["loner"].id}


# ── The backstop ─────────────────────────────────────────────────────────────


def test_nobody_can_be_buried(db, org, world):
    """Not a rate limit — every event fires once per goal per period, so normal
    volume is bounded. This is for the day an import creates four hundred."""
    for n in range(events.DAILY_CAP + 5):
        notifications.emit(
            db,
            org_id=org.id,
            user_id=world["alice"].id,
            event=events.GOAL_ASSIGNED,
            subject_type="goal",
            subject_id=n,
            period_anchor=ANCHOR,
            title=f"Goal {n}",
        )

    assert len(rows(db)) == events.DAILY_CAP


def test_the_cap_only_counts_the_last_day(db, org, world):
    old = notifications.emit(
        db,
        org_id=org.id,
        user_id=world["alice"].id,
        event=events.GOAL_ASSIGNED,
        subject_type="goal",
        subject_id=1,
        period_anchor=ANCHOR,
        title="Ancient",
    )
    assert old
    stale = rows(db)[0]
    stale.created_at = datetime.now(UTC) - timedelta(days=2)
    db.flush()

    for n in range(2, events.DAILY_CAP + 2):
        notifications.emit(
            db,
            org_id=org.id,
            user_id=world["alice"].id,
            event=events.GOAL_ASSIGNED,
            subject_type="goal",
            subject_id=n,
            period_anchor=ANCHOR,
            title=f"Goal {n}",
        )

    # The old one does not count against today, so today's full allowance fits.
    assert len(rows(db)) == events.DAILY_CAP + 1


# ── Authored events are exempt from latching ─────────────────────────────────


def test_a_shout_out_can_be_sent_twice(db, org, world):
    """The partial index, tested directly.

    Detected events latch; authored ones must repeat. Two good weeks are two
    shout-outs, and a manager praising the same person twice is the feature
    working rather than a duplicate to swallow.
    """
    for _ in range(2):
        notifications.emit(
            db,
            org_id=org.id,
            user_id=world["alice"].id,
            event=events.RECOGNITION,
            subject_type="user",
            subject_id=world["alice"].id,
            period_anchor=None,
            title="Great save on the Henderson account",
            created_by_user_id=world["manager"].id,
        )

    assert len(rows(db, "recognition")) == 2


# ── The public/private boundary ──────────────────────────────────────────────


def test_only_celebratory_events_are_public(db):
    """A wall screen has no viewer — it is read by whoever walks past. Being
    behind on a goal is a conversation with your manager, not something to put
    on a permanent display in front of the floor.

    Two assertions on purpose. The **rule** is that nothing reaches a wall unless
    it is worth celebrating, and it should hold for events nobody has written
    yet. The **list** is a tripwire: making an event public is a decision about
    what a room full of people sees, so it should cost a deliberate edit here
    rather than passing quietly. Adding `competition.won` tripped it, which is
    the wire working.
    """
    for key, event in events.CATALOGUE.items():
        if event.public:
            assert event.celebrate, f"{key} is public but not a celebration"

    assert set(events.PUBLIC_EVENT_KEYS) == {
        "goal.achieved",
        # Stretch levels past a target: more than the target, and celebrated
        # the same way. One key per level so each latches on its own.
        "goal.stretch.1",
        "goal.stretch.2",
        "goal.stretch.3",
        "recognition",
        "competition.won",
        # The two nobody earns. Public because an office marks them out loud,
        # and not `major` — a screen set to "important only" wants the wins
        # people worked for.
        "person.birthday",
        "person.work_anniversary",
        # Added in 4l, deliberately: a prize-wheel win is on the wall — and
        # only a win; a miss is never announced. Luck rather than work, so not
        # `major` either.
        "wheel.won",
    }
    assert not events.CATALOGUE["goal.period_ending"].public
    assert not events.CATALOGUE["goal.assigned"].public
    # Starting is a heads-up to the entrants, and coming fifth is nobody else's
    # business — the wall gets the standings screen instead.
    assert not events.CATALOGUE["competition.started"].public
    assert not events.CATALOGUE["competition.finished"].public


def test_the_public_list_is_derived_from_the_catalogue(db):
    """Not written out twice. A second copy agrees on the day it is written and
    disagrees six months later."""
    assert set(events.PUBLIC_EVENT_KEYS) == {
        key for key, event in events.CATALOGUE.items() if event.public
    }


# ── Money in announcements (Q2-2) ────────────────────────────────────────────


def test_money_in_an_announcement_says_it_is_money():
    from decimal import Decimal

    from app.models import MetricDefinition
    from app.notifications import format_value

    money = MetricDefinition(unit="currency", decimal_places=2, unit_label=None)
    assert format_value(Decimal("500"), money) == "$500"
    assert format_value(Decimal("6200.00"), money) == "$6,200"
    assert format_value(Decimal("499.5"), money) == "$499.50"
    assert format_value(Decimal("-40"), money) == "-$40"
    assert format_value(Decimal("500"), money, "GBP") == "£500"
    assert format_value(Decimal("500"), money, "CHF") == "CHF 500"

    deals = MetricDefinition(unit="count", decimal_places=0, unit_label="deals")
    assert format_value(Decimal("1"), deals) == "1 deal"


# ── A goal set already met (Q2-11) ───────────────────────────────────────────


def _hit(db) -> Notification:
    return rows(db, events.GOAL_ACHIEVED.key)[0]


def test_a_goal_set_over_numbers_already_there_is_recorded_quietly(db, org, world, make_fact):
    """Somebody sets a target their person has already passed: true, so it is
    recorded and paid — but not news, so no wall takes over for it."""
    from app import channels as channel_service
    from app.models import Channel

    fact = make_fact(world["metric"], world["alice"], 150, WHEN)
    fact.created_at = datetime.now(UTC) - timedelta(hours=2)
    goal = make_goal(db, org, world)
    goal.created_at = datetime.now(UTC) - timedelta(hours=1)
    db.flush()

    notifications.detect(db)

    hit = _hit(db)
    assert hit.quiet is True
    # Already "celebrated", so the in-app overlay passes it by.
    assert hit.celebrated_at is not None
    channel = Channel(organization_id=org.id, name="Wall")
    db.add(channel)
    db.flush()
    assert channel_service.celebrations(db, org, channel) == []


def test_a_goal_met_by_a_new_number_is_announced(db, org, world, make_fact):
    goal = make_goal(db, org, world)
    goal.created_at = datetime.now(UTC) - timedelta(hours=1)
    fact = make_fact(world["metric"], world["alice"], 150, WHEN)
    fact.created_at = datetime.now(UTC)
    db.flush()

    notifications.detect(db)

    hit = _hit(db)
    assert hit.quiet is False
    assert hit.celebrated_at is None
