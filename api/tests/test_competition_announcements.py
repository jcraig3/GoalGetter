"""Telling people a contest started, and who won it.

A competition that ends without announcing its winner is not finished — it is the
moment a prize changes hands. These were missing for a while, and `advance()`'s
own docstring claimed otherwise: *"closing writes the result down, and an
announcement goes out with it."* Sixth comment/code disagreement this session,
and the first where the comment described a whole feature rather than a detail.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import competitions, events
from app.models import Competition, CompetitionParticipant, Notification, WalkupMedia

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


def notes(db, org, *, event=None):
    query = select(Notification).where(Notification.organization_id == org.id)
    if event:
        query = query.where(Notification.event_key == event)
    return list(db.scalars(query.order_by(Notification.id)).all())


# ── Starting ─────────────────────────────────────────────────────────────────


def test_starting_tells_the_entrants(db, org, world):
    make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]], state="scheduled"
    )

    competitions.advance(db, now=STARTS + timedelta(hours=1))

    told = notes(db, org, event="competition.started")
    assert {n.user_id for n in told} == {world["alice"].id, world["bob"].id}
    assert told[0].title == "August sprint has started"


def test_the_start_body_names_the_prize_and_the_deadline(db, org, world):
    make_competition(
        db, org, world,
        entrants=[world["alice"]],
        state="scheduled",
        prize="Steak dinner",
    )

    competitions.advance(db, now=STARTS + timedelta(hours=1))

    body = notes(db, org, event="competition.started")[0].body
    # `.day` rather than a `%-d` format code, which is glibc-only and would emit
    # a literal "%-d" on somebody's Mac. The 14th, not the 15th: midnight UTC is
    # 8pm the evening before in New York, where this organization is.
    assert body == "Runs until Fri 14 Aug, 8 pm. Steak dinner is on the line."


def test_the_start_body_omits_a_prize_that_is_not_set(db, org, world):
    make_competition(
        db, org, world, entrants=[world["alice"]], state="scheduled"
    )

    competitions.advance(db, now=STARTS + timedelta(hours=1))

    assert notes(db, org, event="competition.started")[0].body == "Runs until Fri 14 Aug, 8 pm."


def test_the_deadline_is_the_organizations_day_not_utcs(db, org, world):
    """QA-14. 7pm on 2 October in New York is 3 October in UTC, and the
    announcement used to say the 3rd."""
    make_competition(
        db, org, world,
        entrants=[world["alice"]],
        state="scheduled",
        ends_at=datetime(2026, 10, 2, 23, 0, tzinfo=UTC),
    )

    competitions.advance(db, now=STARTS + timedelta(hours=1))

    assert notes(db, org, event="competition.started")[0].body == "Runs until Fri 2 Oct, 7 pm."


def test_ending_at_local_midnight_names_the_last_day_it_runs(db, org, world):
    """Midnight New York time on the 16th is the end of the 15th — the contest
    is over before anybody arrives on the 16th."""
    make_competition(
        db, org, world,
        entrants=[world["alice"]],
        state="scheduled",
        ends_at=datetime(2026, 8, 16, 4, 0, tzinfo=UTC),
    )

    competitions.advance(db, now=STARTS + timedelta(hours=1))

    assert notes(db, org, event="competition.started")[0].body == "Runs until the end of Sat 15 Aug."


def test_nothing_is_announced_before_it_starts(db, org, world):
    make_competition(
        db, org, world, entrants=[world["alice"]], state="scheduled"
    )

    competitions.advance(db, now=STARTS - timedelta(hours=1))

    assert notes(db, org) == []


def test_a_restarted_job_does_not_announce_twice(db, org, world):
    """Idempotent through the unique index, so the emitters never check first —
    a check-then-insert is a race on a loop that can be restarted mid-pass."""
    competition = make_competition(
        db, org, world, entrants=[world["alice"]], state="scheduled"
    )

    competitions.advance(db, now=STARTS + timedelta(hours=1))
    competitions.announce_start(db, competition)
    competitions.announce_start(db, competition)

    assert len(notes(db, org, event="competition.started")) == 1


def test_a_draft_announces_nothing(db, org, world):
    """Nobody should learn a plan exists because their phone buzzed."""
    make_competition(db, org, world, entrants=[world["alice"]], state="draft")

    competitions.advance(db, now=AFTER)

    assert notes(db, org) == []


# ── The result ───────────────────────────────────────────────────────────────


def test_the_winner_is_announced_publicly(db, org, world, make_fact):
    """The highest-value notification in the product. Public and celebrated, so
    it reaches the wall and interrupts."""
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["bob"], 40, DURING)
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]], prize="Steak dinner"
    )

    competitions.close(db, org, competition)

    won = notes(db, org, event="competition.won")
    assert [n.user_id for n in won] == [world["alice"].id]
    assert won[0].title == "Alice won August sprint"
    assert won[0].body == "Steak dinner"
    assert won[0].about_name == "Alice"
    assert won[0].about_user_id == world["alice"].id


def test_a_win_is_public_and_a_placing_is_not(db, org, world):
    """Coming fifth is not for a screen read by whoever walks past — the same
    reasoning that keeps `goal.period_ending` off the wall."""
    assert events.is_public("competition.won") is True
    assert events.is_public("competition.finished") is False
    assert events.COMPETITION_WON.celebrate is True
    assert events.COMPETITION_STARTED.public is False


def test_everybody_else_is_told_where_they_came(db, org, world, make_fact):
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["bob"], 40, DURING)
    competition = make_competition(
        db, org, world, entrants=[world["alice"], world["bob"]]
    )

    competitions.close(db, org, competition)

    placed = notes(db, org, event="competition.finished")
    assert [n.user_id for n in placed] == [world["bob"].id]
    assert placed[0].body == "Bob finished 2nd of 2. Alice won."


def test_the_winner_is_not_also_told_they_placed(db, org, world, make_fact):
    """One announcement each. Winning and finishing are the same event from two
    sides, and hearing both would read as a mistake."""
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(db, org, world, entrants=[world["alice"]])

    competitions.close(db, org, competition)

    assert notes(db, org, event="competition.finished") == []


def test_a_shared_first_place_announces_both_winners(db, org, world, make_fact):
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["bob"], 100, DURING)
    competition = make_competition(
        db, org, world,
        entrants=[world["alice"], world["bob"]],
        tie_break="shared_rank",
    )

    competitions.close(db, org, competition)

    won = notes(db, org, event="competition.won")
    assert {n.user_id for n in won} == {world["alice"].id, world["bob"].id}
    # And nobody is told they came second in a contest with two firsts.
    assert notes(db, org, event="competition.finished") == []


def test_the_winners_walkup_music_rides_along(db, org, world, make_fact):
    """A win is a celebration, so it gets what an achievement gets — resolved at
    emit and frozen on the row, so changing your music later does not re-score a
    win you have already had."""
    db.add(
        WalkupMedia(
            user_id=world["alice"].id,
            url="https://www.youtube.com/watch?v=abcdefghijk",
            start_seconds=10,
            end_seconds=25,
        )
    )
    db.flush()
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(db, org, world, entrants=[world["alice"]])

    competitions.close(db, org, competition)

    won = notes(db, org, event="competition.won")[0]
    assert won.media_url == "https://www.youtube.com/watch?v=abcdefghijk"
    assert (won.media_start_seconds, won.media_end_seconds) == (10, 25)


def test_an_unranked_entrant_hears_nothing(db, org, world, make_fact):
    """They did not qualify, so there is no place to tell them about. "You
    finished 3rd of 2" is worse than silence."""
    make_fact(world["metric"], world["alice"], 10, DURING)
    make_fact(world["metric"], world["alice"], 10, DURING)
    make_fact(world["metric"], world["bob"], 500, DURING)
    competition = make_competition(
        db, org, world,
        entrants=[world["alice"], world["bob"]],
        min_participation=2,
    )

    competitions.close(db, org, competition)

    assert {n.user_id for n in notes(db, org)} == {world["alice"].id}


def test_settling_by_the_clock_announces_the_same_way(db, org, world, make_fact):
    """`close()` announces, not `advance()`, so settling early through the API
    produces exactly what the clock would have."""
    make_fact(world["metric"], world["alice"], 100, DURING)
    competition = make_competition(db, org, world, entrants=[world["alice"]])

    competitions.advance(db, now=AFTER + timedelta(days=1))

    assert competition.state == "closed"
    assert len(notes(db, org, event="competition.won")) == 1


def test_a_cancelled_competition_announces_nothing(db, org, world, make_fact):
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_competition(db, org, world, entrants=[world["alice"]], state="cancelled")

    competitions.advance(db, now=AFTER + timedelta(days=10))

    assert notes(db, org) == []


# ── Teams ────────────────────────────────────────────────────────────────────


def test_a_team_win_reaches_every_member(db, org, world, make_fact):
    """A notification goes to a person. "Enterprise won" is news to the people
    who made it happen, not to a row in a table."""
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["carol"], 10, DURING)
    competition = make_competition(
        db, org, world,
        entrants=[world["enterprise"], world["smb"]],
        entity_type="team",
    )

    competitions.close(db, org, competition)

    won = notes(db, org, event="competition.won")
    assert {n.user_id for n in won} == {world["alice"].id, world["bob"].id}
    assert won[0].about_team_id == world["enterprise"].id
    # No one person's music for a team win.
    assert won[0].media_url is None


def test_the_losing_team_is_told_too(db, org, world, make_fact):
    make_fact(world["metric"], world["alice"], 100, DURING)
    make_fact(world["metric"], world["carol"], 10, DURING)
    competition = make_competition(
        db, org, world,
        entrants=[world["enterprise"], world["smb"]],
        entity_type="team",
    )

    competitions.close(db, org, competition)

    placed = notes(db, org, event="competition.finished")
    assert {n.user_id for n in placed} == {world["carol"].id}
    assert placed[0].body == "SMB finished 2nd of 2. Enterprise won."


def test_a_team_contest_tells_the_members_it_started(db, org, world):
    make_competition(
        db, org, world,
        entrants=[world["enterprise"]],
        entity_type="team",
        state="scheduled",
    )

    competitions.advance(db, now=STARTS + timedelta(hours=1))

    told = notes(db, org, event="competition.started")
    assert {n.user_id for n in told} == {world["alice"].id, world["bob"].id}


def test_a_hidden_member_is_not_told(db, org, world):
    """Same recipient rule as everywhere else that picks people."""
    world["bob"].hidden_at = datetime.now(UTC)
    db.flush()
    make_competition(
        db, org, world,
        entrants=[world["enterprise"]],
        entity_type="team",
        state="scheduled",
    )

    competitions.advance(db, now=STARTS + timedelta(hours=1))

    assert {n.user_id for n in notes(db, org)} == {world["alice"].id}


def test_somebody_on_an_unaccepted_invitation_hears_nothing(
    db, org, world, make_fact, make_user
):
    """Found by running the real thing, not by a failing test.

    `audience()` filtered on status and the per-entrant lookup did not, so an
    invited-but-never-signed-in account was told it finished third in a contest
    that nothing had ever told it had started. Two functions computing the same
    thing, which is the shape of bug this codebase keeps turning up.

    Both directions are asserted here, because fixing only the result half would
    have left the pair inconsistent the other way round.
    """
    newcomer = make_user("agent", world["enterprise"], name="Newcomer")
    newcomer.status = "invited"
    db.flush()

    make_fact(world["metric"], world["alice"], 100, DURING)
    scheduled = make_competition(
        db, org, world,
        entrants=[world["alice"], newcomer],
        state="scheduled",
    )

    competitions.advance(db, now=STARTS + timedelta(hours=1))
    assert newcomer.id not in {n.user_id for n in notes(db, org)}

    competitions.close(db, org, scheduled)
    assert newcomer.id not in {n.user_id for n in notes(db, org)}
    # Alice still hears about both, so the filter has not simply muted everybody.
    assert {n.event_key for n in notes(db, org) if n.user_id == world["alice"].id} == {
        "competition.started",
        "competition.won",
    }


# ── A team id is not a person's id ───────────────────────────────────────────


def test_a_team_win_never_borrows_a_persons_music(db, org, world, make_fact):
    """The bug that no natural fixture can produce here.

    `walkup_for()` takes a user id. Team ids come from a different sequence that
    also starts at 1, so in a fresh organization team 3 and user 3 both exist —
    and passing the team's id would play *that person's* song for their team's
    win. Nothing raises; it is simply the wrong music.

    The shared test database has run its sequences thousands apart, so the
    collision cannot be arranged by creating rows. Instead the guard is asserted
    directly: a user id that definitely **does** have media, handed to a *team*
    competition, must still come back with nothing.
    """
    db.add(
        WalkupMedia(
            user_id=world["alice"].id,
            url="https://www.youtube.com/watch?v=abcdefghijk",
            start_seconds=1,
            end_seconds=9,
        )
    )
    db.flush()

    team_contest = make_competition(
        db, org, world, entrants=[world["enterprise"]], entity_type="team"
    )
    user_contest = make_competition(
        db, org, world, entrants=[world["alice"]], entity_type="user"
    )

    # Same id, and the only difference is what kind of contest is asking.
    assert competitions._win_media(db, team_contest, world["alice"].id) == {}
    assert competitions._win_media(db, user_contest, world["alice"].id) == {
        "media_url": "https://www.youtube.com/watch?v=abcdefghijk",
        "media_start_seconds": 1,
        "media_end_seconds": 9,
    }


# ── Ordinals ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("rank", "expected"),
    [
        (1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"),
        (11, "11th"), (12, "12th"), (13, "13th"),
        (21, "21st"), (22, "22nd"), (23, "23rd"), (101, "101st"),
    ],
)
def test_place_names_a_rank(rank, expected):
    """The 11th/12th/13th exception, which a last-digit lookup gets wrong.

    Duplicated in `competitionClock.ts` on purpose: a notification body is
    written here and read there, and sharing one formatting rule over HTTP would
    be worse than two tested copies.
    """
    assert competitions._place(rank) == expected
