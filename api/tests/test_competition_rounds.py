"""Competitions that run again every day, week or month.

What has to be true: each round is a real contest with its own window and its
own frozen result; a round is made once however often the job runs; the next
round is waiting as soon as the current one starts; a neglected series is not
back-filled with contests nobody saw; the wall clock holds across a daylight
saving change; and editing the upcoming round is how the series changes.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select

from app import competition_rounds as rounds
from app.models import Competition, CompetitionParticipant

# New York: 9am on Monday 5 October 2026 is 13:00 UTC (daylight time).
STARTS = datetime(2026, 10, 5, 13, 0, tzinfo=UTC)
ENDS = STARTS + timedelta(days=5)


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    return {
        "admin": make_user("admin", name="Bruce Wayne"),
        "peter": make_user("agent", name="Peter Parker"),
        "clark": make_user("agent", name="Clark Kent"),
        "metric": make_metric("calls"),
    }


def series(db, org, world, *, repeat="weekly", state="active", **extra):
    fields = {
        "organization_id": org.id, "name": "Weekly sprint", "prize": "Lunch",
        "metric_definition_id": world["metric"].id, "entity_type": "user",
        "starts_at": STARTS, "ends_at": ENDS, "state": state, "repeat": repeat,
        **extra,
    }
    root = Competition(**fields)
    db.add(root)
    db.flush()
    for person in (world["peter"], world["clark"]):
        db.add(CompetitionParticipant(competition_id=root.id, user_id=person.id))
    db.flush()
    return root


def later_rounds(db, root):
    return db.scalars(
        select(Competition)
        .where(Competition.spawned_from_competition_id == root.id)
        .order_by(Competition.round)
    ).all()


# ── Making rounds ───────────────────────────────────────────────────────────


def test_the_next_round_waits_as_soon_as_the_first_starts(db, org, world):
    root = series(db, org, world)

    made = rounds.spawn_due(db, now=STARTS + timedelta(hours=1))

    assert made == 1
    [second] = later_rounds(db, root)
    assert second.round == 1
    assert (second.starts_at, second.ends_at) == (STARTS + timedelta(weeks=1), ENDS + timedelta(weeks=1))
    assert second.state == "scheduled"


def test_nothing_is_made_before_the_first_round_starts(db, org, world):
    root = series(db, org, world, state="scheduled")

    rounds.spawn_due(db, now=STARTS - timedelta(days=1))

    assert later_rounds(db, root) == []


def test_a_round_is_made_once_however_often_the_job_runs(db, org, world):
    root = series(db, org, world)

    rounds.spawn_due(db, now=STARTS + timedelta(hours=1))
    rounds.spawn_due(db, now=STARTS + timedelta(hours=2))

    assert len(later_rounds(db, root)) == 1


def test_a_round_copies_the_entrants_and_the_prize(db, org, world):
    root = series(db, org, world)

    rounds.spawn_due(db, now=STARTS + timedelta(hours=1))

    [second] = later_rounds(db, root)
    entrants = db.scalars(
        select(CompetitionParticipant.user_id).where(CompetitionParticipant.competition_id == second.id)
    ).all()
    assert sorted(entrants) == sorted([world["peter"].id, world["clark"].id])
    assert second.prize == "Lunch"


def test_editing_the_upcoming_round_carries_forward(db, org, world, make_user):
    """The last round is the pattern: change next week's, and the week after follows."""
    root = series(db, org, world)
    rounds.spawn_due(db, now=STARTS + timedelta(hours=1))
    [second] = later_rounds(db, root)
    second.prize = "Pizza"
    diana = make_user("agent", name="Diana Prince")
    db.add(CompetitionParticipant(competition_id=second.id, user_id=diana.id))
    db.flush()

    rounds.spawn_due(db, now=second.starts_at + timedelta(hours=1))

    third = later_rounds(db, root)[1]
    assert third.prize == "Pizza"
    assert diana.id in db.scalars(
        select(CompetitionParticipant.user_id).where(CompetitionParticipant.competition_id == third.id)
    ).all()


def test_a_neglected_series_is_not_back_filled(db, org, world):
    """A month without the job does not produce four contests nobody saw."""
    root = series(db, org, world)

    rounds.spawn_due(db, now=STARTS + timedelta(weeks=5, hours=1))

    assert [r.round for r in later_rounds(db, root)] == [5, 6]


def test_between_rounds_only_the_next_one_is_made(db, org, world):
    """Saturday: this week's round has ended and next week's is waiting."""
    root = series(db, org, world)

    rounds.spawn_due(db, now=STARTS + timedelta(weeks=3, days=5, hours=6))

    assert [r.round for r in later_rounds(db, root)] == [4]


def test_the_wall_clock_holds_across_daylight_saving(db, org, world):
    """9am New York in October is 13:00 UTC; in November it is 14:00."""
    root = series(db, org, world)

    rounds.spawn_due(db, now=STARTS + timedelta(weeks=4, hours=2))

    after = next(r for r in later_rounds(db, root) if r.round == 5)
    assert after.starts_at == datetime(2026, 11, 9, 14, 0, tzinfo=UTC)


def test_monthly_on_the_31st_runs_on_the_last_day_of_a_short_month(db, org, world):
    start = datetime(2026, 1, 31, 14, 0, tzinfo=UTC)
    root = series(db, org, world, repeat="monthly", starts_at=start, ends_at=start + timedelta(hours=8))

    rounds.spawn_due(db, now=start + timedelta(hours=1))

    assert later_rounds(db, root)[0].starts_at.date() == date(2026, 2, 28)


def test_it_stops_at_its_last_day(db, org, world):
    root = series(db, org, world, repeat_until=date(2026, 10, 10))

    rounds.spawn_due(db, now=STARTS + timedelta(hours=1))

    assert later_rounds(db, root) == []


def test_an_unpublished_series_makes_nothing(db, org, world):
    root = series(db, org, world, state="draft")

    rounds.spawn_due(db, now=STARTS + timedelta(hours=1))

    assert later_rounds(db, root) == []


def test_switching_repeating_off_stops_it(db, org, world):
    root = series(db, org, world)
    rounds.spawn_due(db, now=STARTS + timedelta(hours=1))
    root.repeat = None
    db.flush()

    rounds.spawn_due(db, now=STARTS + timedelta(weeks=1, hours=1))

    assert len(later_rounds(db, root)) == 1, "the round already made is kept"


def test_a_round_is_its_own_contest(db, org, world, make_fact):
    """Settling one round does not touch the next: each has its own table."""
    root = series(db, org, world)
    rounds.spawn_due(db, now=STARTS + timedelta(hours=1))
    [second] = later_rounds(db, root)

    assert second.id != root.id
    assert second.state == "scheduled"
    assert root.state == "active"


# ── Fitting ─────────────────────────────────────────────────────────────────


def test_a_fortnight_cannot_repeat_weekly(org):
    assert rounds.fits(org, STARTS, STARTS + timedelta(days=7), "weekly")
    assert not rounds.fits(org, STARTS, STARTS + timedelta(days=14), "weekly")


# ── The API ─────────────────────────────────────────────────────────────────


def body(world, **extra):
    return {
        "name": "Weekly sprint", "metric_id": world["metric"].id,
        "starts_at": STARTS.isoformat(), "ends_at": ENDS.isoformat(),
        "entity_ids": [world["peter"].id, world["clark"].id], **extra,
    }


def test_a_contest_can_be_made_to_repeat(client, sign_in, world):
    sign_in(world["admin"])

    made = client.post("/api/competitions", json=body(world, repeat="weekly")).json()

    assert made["repeat"] == "weekly"
    assert made["round_number"] == 1
    assert made["series_id"] == made["id"]


def test_one_that_is_too_long_to_repeat_is_refused_in_words(client, sign_in, world):
    sign_in(world["admin"])

    reply = client.post(
        "/api/competitions",
        json=body(world, repeat="daily"),
    )

    assert reply.status_code == 400
    assert "cannot repeat daily" in reply.json()["detail"]


def test_repeating_is_set_on_the_series_from_any_round(client, sign_in, db, org, world):
    sign_in(world["admin"])
    root = series(db, org, world)
    rounds.spawn_due(db, now=STARTS + timedelta(hours=1))
    [second] = later_rounds(db, root)

    client.put(f"/api/competitions/{second.id}/repeat", json={"repeat": None})

    assert root.repeat is None


def test_a_settled_contest_can_start_repeating(client, sign_in, db, org, world):
    """Repeating decides future rounds, not this one's rules."""
    sign_in(world["admin"])
    root = series(db, org, world, repeat=None, state="closed")

    reply = client.put(f"/api/competitions/{root.id}/repeat", json={"repeat": "weekly"})

    assert reply.status_code == 200
    assert root.repeat == "weekly"


def test_the_rounds_are_listed_with_their_winners(client, sign_in, db, org, world):
    sign_in(world["admin"])
    root = series(db, org, world, state="closed")
    db.execute(
        CompetitionParticipant.__table__.update()
        .where(
            CompetitionParticipant.competition_id == root.id,
            CompetitionParticipant.user_id == world["clark"].id,
        )
        .values(final_rank=1)
    )
    rounds.spawn_due(db, now=STARTS + timedelta(days=6))

    listed = client.get(f"/api/competitions/{root.id}/rounds").json()

    assert [(r["round_number"], r["winner"]) for r in listed] == [(1, "Clark Kent"), (2, None)]
