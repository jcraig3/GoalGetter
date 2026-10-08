"""What may go on which wall.

One rule, in one place, because the alternative is a client that offers a
choice the server then refuses — and the version of that mistake nobody
notices is the reverse: a picker that quietly omits something the server would
have accepted.

**A channel may show anything not tied to a *different* office or team.**

Organization-wide things go anywhere: the company revenue board belongs on
every wall. Anything narrower goes only where it is related. A goal for a
Dallas agent on a Phoenix screen is not a filtering nicety — it is Dallas's
numbers in front of Phoenix, which is the whole reason a channel has an
audience.

Conflicts are refused when a screen is authored, and skipped again when it
renders. The second guard is for rows that predate the first.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import (
    Channel,
    Competition,
    CompetitionParticipant,
    Goal,
    Leaderboard,
    Office,
    Team,
    UserAccount,
)


@dataclass(frozen=True)
class Where:
    """The office and team something belongs to.

    Three states, not two, and the third is easy to miss. A company board is
    tied to nowhere because it is **about everywhere** — it belongs on any
    wall. A goal for somebody on no team is tied to nowhere because they are
    **placed nowhere** — which is the opposite, and it belongs on no office's
    wall at all.

    Collapsing the two put an unplaced person's goal on every screen in the
    building. The docstring below said otherwise for a while before anybody
    read the output.
    """

    office_id: int | None = None
    team_id: int | None = None
    #: True when this is somebody with no team, rather than something org-wide.
    unplaced: bool = False


#: About everywhere: goes on any wall.
EVERYWHERE = Where()

#: Placed nowhere: goes only on a wall with no audience.
UNPLACED = Where(unplaced=True)


def channel_where(channel: Channel) -> Where:
    if channel.scope_type == "office":
        return Where(office_id=channel.scope_office_id)
    if channel.scope_type == "team":
        return Where(team_id=channel.scope_team_id)
    return EVERYWHERE


def board_where(board: Leaderboard) -> Where:
    if board.scope_type == "office":
        return Where(office_id=board.scope_office_id)
    if board.scope_type == "team":
        return Where(team_id=board.scope_team_id)
    return EVERYWHERE


def person_where(db: DbSession, person: UserAccount | None) -> Where:
    """Where one person belongs.

    Somebody on no team is *placed nowhere*, not everywhere — they are not in
    Phoenix, so nothing about them belongs on Phoenix's wall. See `Where`,
    where collapsing those two states once put an unplaced person on every
    screen in the building.
    """
    if person is None or person.team_id is None:
        return UNPLACED
    team = db.get(Team, person.team_id)
    return Where(office_id=team.office_id if team else None, team_id=person.team_id)


def goal_where(db: DbSession, goal: Goal) -> Where:
    """Where a goal belongs.

    A goal about one person or one team belongs to that team, and to whichever
    office the team sits in. A goal about the whole company belongs everywhere
    — it is the one case where a goal is genuinely organization-wide, and it is
    exactly the screen every wall in the building should carry.
    """
    if goal.subject_type == "organization":
        return EVERYWHERE

    if goal.subject_type == "team":
        team = db.get(Team, goal.subject_team_id)
        return Where(office_id=team.office_id if team else None, team_id=goal.subject_team_id)

    return person_where(db, db.get(UserAccount, goal.subject_user_id))


def competition_teams(db: DbSession, competition: Competition) -> set[int | None]:
    """The teams with a stake in this contest.

    For a team contest that is the entrants. For a person contest it is the teams
    those people are on — `None` in the set means somebody with no team.
    """
    entrants = db.scalars(
        select(CompetitionParticipant).where(
            CompetitionParticipant.competition_id == competition.id
        )
    ).all()
    if not entrants:
        return set()

    if competition.entity_type == "team":
        return {p.team_id for p in entrants if p.team_id is not None}

    user_ids = [p.user_id for p in entrants if p.user_id is not None]
    return set(
        db.scalars(
            select(UserAccount.team_id).where(UserAccount.id.in_(user_ids))
        ).all()
    )


def competition_offices(db: DbSession, competition: Competition) -> set[int | None]:
    """Every office with a stake in this contest.

    A **set**, which is the whole point and why a competition cannot use the
    single-slot `Where` the way a goal or a board does. A goal names one subject
    and therefore sits in one place. A contest between Phoenix and Dallas sits in
    two, and "two" is not a value `Where` can hold.

    `None` in the set means a team with no office, or an entrant with no team.
    """
    team_ids = competition_teams(db, competition)
    if not team_ids:
        return set()
    offices: set[int | None] = set()
    placed = {t for t in team_ids if t is not None}
    if placed:
        offices |= set(
            db.scalars(select(Team.office_id).where(Team.id.in_(placed))).all()
        )
    if None in team_ids:
        # Somebody on no team belongs to no office either.
        offices.add(None)
    return offices


def competition_fits(
    db: DbSession, channel: Where, competition: Competition
) -> bool:
    """May this wall show this contest?

    **Only the places involved in it.** A Phoenix-versus-Dallas contest goes on
    Phoenix's wall and Dallas's wall — and not on Austin's, which has no stake in
    it and no reason to watch.

    This replaced a version that collapsed any multi-office contest to
    `EVERYWHERE`. That got the two-office case right by accident and the third
    office wrong: `EVERYWHERE` fits every wall, so Austin showed it too. The
    mistake was trying to express "these two offices" in a field that holds one
    place, when the answer is a set.

        organization-wide wall   shows everything — it is the company's own wall
        office wall              shows it if that office is involved
        team wall                shows it if that team is entered, or its office is
    """
    if channel.office_id is None and channel.team_id is None:
        return True

    if channel.office_id is not None:
        return channel.office_id in competition_offices(db, competition)

    # A team wall. Its own team being entered is the obvious case; its office
    # being involved is the same reasoning one level up — a team inside Phoenix
    # has a stake in Phoenix's contest.
    if channel.team_id in competition_teams(db, competition):
        return True
    team = db.get(Team, channel.team_id)
    if team is None or team.office_id is None:
        return False
    return team.office_id in competition_offices(db, competition)


def competition_places(db: DbSession, competition: Competition, *, picker: bool = True) -> str:
    """Where this contest is on, in words, for the screen picker.

    Names the offices rather than saying "Everyone", because "Phoenix + Dallas"
    is the actual answer and the thing that tells an admin why a contest is on
    one list and not another. A contest among people with no office at all is
    "everyone" in the picker (review §9) — "(no office)" read as a fault.
    """
    offices = competition_offices(db, competition)
    named = sorted(
        (db.get(Office, o).name for o in offices if o is not None),
        key=str.lower,
    )
    if None in offices:
        named.append("no office" if named or not picker else "everyone")
    return " + ".join(named) if named else "No entrants"


def fits(channel: Where, thing: Where) -> bool:
    """May a thing belonging *there* go on a channel for *here*?

    Refuses only on a genuine conflict. An organization-wide channel takes
    everything, an organization-wide board goes on every wall, and a team's
    goal is at home on both its team's channel and its office's — a team
    channel is not a *different* office from the one its team sits in.
    """
    # The whole rule: refuse only where both sides pin the *same* axis to
    # *different* values. Everything else is allowed, and that single default
    # covers every case worth spelling out —
    #
    #   an organization-wide channel   pins nothing, so nothing conflicts
    #   an organization-wide board     pins nothing, so it goes on any wall
    #   a team's goal on its office    different axes, no conflict to find
    #
    # An earlier version stated the first two explicitly as well. A mutation
    # proved those lines could be deleted without changing a single answer:
    # the fallthrough already said it. Fourth piece of redundant defence found
    # that way this session.
    # Placed nowhere fits only a wall that is about everywhere. Checked before
    # the axis comparisons, which would otherwise wave it through — both sides
    # look like "nothing pinned".
    if thing.unplaced:
        return channel.office_id is None and channel.team_id is None

    if channel.office_id is not None and thing.office_id is not None:
        return channel.office_id == thing.office_id

    if channel.team_id is not None and thing.team_id is not None:
        return channel.team_id == thing.team_id

    return True
