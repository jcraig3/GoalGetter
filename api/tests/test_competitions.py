"""Contests, and results that stop changing.

A competition is the only place this product stores a computed number, and it
inverts the rule everything else follows. The sharpest test here is the one
that proves both halves of that at once: correcting an old fact must change the
leaderboard for that period and must **not** change who won.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import aggregate, competitions
from app.models import Competition, CompetitionParticipant
from app.periods import Period

#: A window in the past, so "the contest is over" needs no clock tricks.
STARTS = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
ENDS = datetime(2026, 8, 15, 0, 0, tzinfo=UTC)
DURING = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
AFTER = ENDS + timedelta(days=2)


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    enterprise = make_team("Enterprise")
    smb = make_team("SMB")
    return {
        "enterprise": enterprise,
        "smb": smb,
        "admin": make_user("admin", name="Admin"),
        "alice": make_user("agent", enterprise, name="Alice"),
        "bob": make_user("agent", enterprise, name="Bob"),
        "carol": make_user("agent", smb, name="Carol"),
        "metric": make_metric("revenue", unit="currency", decimal_places=2),
    }


def make_competition(db, org, world, *, entrants, entity_type="user", **overrides):
    fields = {
        "organization_id": org.id,
        "name": "August sprint",
        "metric_definition_id": world["metric"].id,
        "entity_type": entity_type,
        "starts_at": STARTS,
        "ends_at": ENDS,
        "state": "active",
    }
    fields.update(overrides)
    competition = Competition(**fields)
    db.add(competition)
    db.flush()

    for entrant in entrants:
        db.add(
            CompetitionParticipant(
                competition_id=competition.id,
                user_id=entrant.id if entity_type == "user" else None,
                team_id=entrant.id if entity_type == "team" else None,
            )
        )
    db.flush()
    return competition


def table(db, org, competition):
    return [
        (s.entity_name, s.value, s.rank)
        for s in competitions.standings(db, org, competition)
    ]


# ── The result stops changing ────────────────────────────────────────────────


def test_a_correction_moves_the_leaderboard_and_not_the_winner(
    db, org, world, make_fact
):
    """**The most important test in Phase 2.**

    Everything else here is derived because derived numbers stay correct. A
    competition result is the opposite: a prize was handed over on the strength
    of it. Both halves have to be true at once, which is why they are asserted
    together.
    """
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["bob"], 90, DURING)

    competition = make_competition(db, org, world, entrants=[world["alice"], world["bob"]])
    competitions.close(db, org, competition)
    db.flush()

    assert table(db, org, competition)[0][0] == "Alice"

    # A late correction: Bob's deal was bigger than anybody realised.
    make_fact(world["metric"], world["bob"], 500, DURING)

    # The leaderboard for that window moves, because it always recomputes.
    rows = aggregate.run(
        db, org.id, world["admin"], world["metric"],
        Period(type="custom", start=STARTS, end=ENDS, label="August"),
    )
    assert rows[0].subject_name == "Bob"

    # The trophy does not.
    assert table(db, org, competition)[0][0] == "Alice"


def test_a_running_competition_does_recompute(db, org, world, make_fact):
    """Before it closes, standings are a live query like everything else — the
    freeze is a property of *closing*, not of being a competition."""
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(db, org, world, entrants=[world["alice"], world["bob"]])

    assert table(db, org, competition)[0] == ("Alice", Decimal("100.0000"), 1)

    make_fact(world["metric"], world["bob"], 500, DURING)
    assert table(db, org, competition)[0][0] == "Bob"


def test_closing_twice_does_not_change_the_result(db, org, world, make_fact):
    """The job can run again. It must not re-settle a finished contest."""
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(db, org, world, entrants=[world["alice"], world["bob"]])
    competitions.close(db, org, competition)
    db.flush()

    make_fact(world["metric"], world["bob"], 500, DURING)
    competitions.advance(db, now=AFTER + timedelta(days=5))

    assert table(db, org, competition)[0][0] == "Alice"


# ── Ranking within the entrants ──────────────────────────────────────────────


def test_rank_is_among_entrants_not_the_whole_organization(
    db, org, world, make_fact
):
    """Second of two is not the same as second of forty.

    Filtering rows after ranking would give the latter and call it the former.
    """
    make_fact(world["metric"], world["carol"], 9999, DURING)  # not an entrant
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["bob"], 90, DURING)

    competition = make_competition(db, org, world, entrants=[world["alice"], world["bob"]])

    assert table(db, org, competition) == [
        ("Alice", Decimal("100.0000"), 1),
        ("Bob", Decimal("90.0000"), 2),
    ]


def test_an_entrant_with_nothing_recorded_still_appears(db, org, world, make_fact):
    """Somebody who has not scored is in the contest and last, which is
    different from not being in it."""
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(db, org, world, entrants=[world["alice"], world["bob"]])

    names = [row[0] for row in table(db, org, competition)]
    assert names == ["Alice", "Bob"]


def test_facts_outside_the_window_do_not_count(db, org, world, make_fact):
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["bob"], 999, STARTS - timedelta(days=1))
    make_fact(world["metric"], world["bob"], 999, ENDS + timedelta(days=1))

    competition = make_competition(db, org, world, entrants=[world["alice"], world["bob"]])

    assert table(db, org, competition)[0] == ("Alice", Decimal("100.0000"), 1)


def test_teams_compete_as_teams(db, org, world, make_fact, make_team, make_user):
    make_fact(world["metric"], world["alice"], 60, DURING)
    make_fact(world["metric"], world["bob"], 60, DURING)
    make_fact(world["metric"], world["carol"], 100, DURING)

    # A team that is *not* in the contest, outscoring both that are. An earlier
    # version of this test entered every team that existed, so "filtered to the
    # entrants" and "not filtered at all" produced identical output and a
    # mutation removing the filter survived.
    partners = make_team("Partners")
    make_fact(world["metric"], make_user("agent", partners, name="Dana"), 9999, DURING)

    competition = make_competition(
        db, org, world,
        entrants=[world["enterprise"], world["smb"]],
        entity_type="team",
    )

    # Enterprise is two people at 60; SMB is one at 100. Partners is absent,
    # and does not take first place.
    assert table(db, org, competition) == [
        ("Enterprise", Decimal("120.0000"), 1),
        ("SMB", Decimal("100.0000"), 2),
    ]


def test_lower_is_better_flips_the_winner(db, org, world, make_fact, make_metric):
    speed = make_metric("response_time", direction="lower_is_better")
    make_fact(speed, world["alice"], 90, DURING)
    make_fact(speed, world["bob"], 45, DURING)

    competition = make_competition(
        db, org, world,
        entrants=[world["alice"], world["bob"]],
        metric_definition_id=speed.id,
    )
    competitions.close(db, org, competition)
    db.flush()

    assert table(db, org, competition)[0][0] == "Bob"


# ── The gap that matters ─────────────────────────────────────────────────────


def test_the_gap_is_to_the_place_above_not_to_first(db, org, world, make_fact):
    """"$4,100 behind 6th" is something somebody can do today. "$45,300 behind
    1st" is a reason to stop trying."""
    make_fact(world["metric"], world["alice"], 1000, DURING)
    make_fact(world["metric"], world["bob"], 900, DURING)
    make_fact(world["metric"], world["carol"], 100, DURING)

    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"], world["carol"]]
    )
    rows = competitions.standings(db, org, competition)

    assert rows[0].gap_to_next is None
    assert rows[1].gap_to_next == Decimal("100.0000")
    assert rows[2].gap_to_next == Decimal("800.0000")


# ── Ties ─────────────────────────────────────────────────────────────────────


def test_whoever_got_there_first_wins_a_tie(db, org, world, make_fact):
    """A contest with a prize needs a decisive winner. "You tied" is the answer
    nobody accepts.

    **Bob** scores first here, on purpose. The first version had Alice reaching
    first, and Alice is also created first and sorts first alphabetically — so
    a sort that ignored the timestamp entirely still put her on top and the
    test passed. Same shape as the walk-up-music fixture bug earlier this
    session: the right answer and the wrong one looked identical.
    """
    make_fact(world["metric"], world["bob"], 100, DURING)
    make_fact(world["metric"], world["alice"], 100, DURING + timedelta(days=1))

    competition = make_competition(db, org, world, entrants=[world["alice"], world["bob"]])
    competitions.close(db, org, competition)
    db.flush()

    rows = competitions.standings(db, org, competition)
    assert [r.entity_name for r in rows] == ["Bob", "Alice"]
    assert [r.rank for r in rows] == [1, 2]


def test_scoring_after_the_whistle_does_not_make_you_later(db, org, world, make_fact):
    """`reached_at` looks only inside the window.

    Bob got to 100 first and then kept selling. If the tie-break query let
    those later facts in, his "reached" time would drift past Alice's and he
    would lose a tie he won.
    """
    make_fact(world["metric"], world["bob"], 100, DURING)
    make_fact(world["metric"], world["alice"], 100, DURING + timedelta(days=1))
    make_fact(world["metric"], world["bob"], 999, ENDS + timedelta(days=1))

    competition = make_competition(db, org, world, entrants=[world["alice"], world["bob"]])
    competitions.close(db, org, competition)
    db.flush()

    rows = competitions.standings(db, org, competition)
    assert [r.entity_name for r in rows] == ["Bob", "Alice"]
    # And the after-the-whistle sale did not count toward his total either.
    assert rows[0].value == Decimal("100.0000")


def test_shared_rank_lets_them_tie(db, org, world, make_fact):
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["bob"], 100, DURING + timedelta(days=1))

    competition = make_competition(
        db, org, world,
        entrants=[world["alice"], world["bob"]],
        tie_break="shared_rank",
    )
    competitions.close(db, org, competition)
    db.flush()

    assert [r.rank for r in competitions.standings(db, org, competition)] == [1, 1]


# ── Not qualifying ───────────────────────────────────────────────────────────


def test_too_few_data_points_leaves_an_entrant_unranked(db, org, world, make_fact):
    """Stops one lucky data point winning an average-based contest. Unranked
    rather than last, because those mean different things."""
    make_fact(world["metric"], world["alice"], 10, DURING)
    make_fact(world["metric"], world["alice"], 10, DURING)
    make_fact(world["metric"], world["alice"], 10, DURING)
    make_fact(world["metric"], world["bob"], 500, DURING)

    competition = make_competition(
        db, org, world,
        entrants=[world["alice"], world["bob"]],
        min_participation=3,
    )
    competitions.close(db, org, competition)
    db.flush()

    assert [r.entity_name for r in competitions.standings(db, org, competition)] == ["Alice"]


# ── The lifecycle ────────────────────────────────────────────────────────────


def test_a_scheduled_competition_starts_on_time(db, org, world):
    competition = make_competition(
        db, org, world, entrants=[world["alice"]], state="scheduled"
    )

    competitions.advance(db, now=STARTS + timedelta(hours=1))
    assert competition.state == "active"


def test_a_scheduled_competition_does_not_start_early(db, org, world):
    """The other half of the previous test, and the half that was missing.

    "It starts when the clock says so" needs both directions to mean anything —
    a job that started everything it found would have passed the first test.
    """
    competition = make_competition(
        db, org, world, entrants=[world["alice"]], state="scheduled"
    )

    competitions.advance(db, now=STARTS - timedelta(hours=1))
    assert competition.state == "scheduled"


def test_it_ends_but_does_not_settle_immediately(db, org, world, make_fact):
    """The gap between `ended` and `closed` is the settlement window: a deal
    closed at 4:55pm that syncs at 5:10pm should still count."""
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(db, org, world, entrants=[world["alice"]])

    competitions.advance(db, now=ENDS + timedelta(hours=1))

    assert competition.state == "ended"
    assert competition.closed_at is None


def test_a_late_fact_inside_the_settlement_window_still_counts(
    db, org, world, make_fact
):
    """The whole reason the window exists."""
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["bob"], 90, DURING)
    competition = make_competition(db, org, world, entrants=[world["alice"], world["bob"]])

    competitions.advance(db, now=ENDS + timedelta(hours=1))
    # A sync lands two hours after the whistle, carrying work done before it.
    make_fact(world["metric"], world["bob"], 500, DURING)
    competitions.advance(db, now=ENDS + timedelta(hours=25))

    assert competition.state == "closed"
    assert table(db, org, competition)[0][0] == "Bob"


def test_settling_closes_it_for_good(db, org, world, make_fact):
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(db, org, world, entrants=[world["alice"]])

    competitions.advance(db, now=ENDS + timedelta(hours=25))

    assert competition.state == "closed"
    assert competition.closed_at is not None
    assert competitions.standings(db, org, competition)[0].final is True


def test_a_zero_hour_window_settles_at_the_whistle(db, org, world, make_fact):
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(
        db, org, world, entrants=[world["alice"]], settlement_hours=0
    )

    competitions.advance(db, now=ENDS + timedelta(seconds=1))
    assert competition.state == "closed"


def test_a_cancelled_competition_is_left_alone(db, org, world, make_fact):
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(
        db, org, world, entrants=[world["alice"]], state="cancelled"
    )

    competitions.advance(db, now=AFTER + timedelta(days=10))

    assert competition.state == "cancelled"
    assert db.scalar(
        select(CompetitionParticipant.final_rank).where(
            CompetitionParticipant.competition_id == competition.id
        )
    ) is None


def test_a_draft_never_starts_on_its_own(db, org, world):
    """A draft is being configured. Nobody should discover it went live."""
    competition = make_competition(
        db, org, world, entrants=[world["alice"]], state="draft"
    )

    competitions.advance(db, now=AFTER)
    assert competition.state == "draft"
