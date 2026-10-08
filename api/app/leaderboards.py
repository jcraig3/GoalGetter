"""Running a saved leaderboard.

Two questions, deliberately separate:

    may this person LOOK at this board?   — the board's `visibility`
    who APPEARS on it?                    — the board's `scope`

Everywhere else in this product, the viewer narrows the rows: an agent sees
only their own numbers. A leaderboard is the one place that rule is relaxed on
purpose, because a board showing an agent a single row — theirs — is not a
leaderboard. Public ranking is the mechanism.

So the control moves from *who you are* to *what the publisher chose to
publish*, and it stops at the board. A person's detail, goals, and raw facts
stay scoped exactly as before; only ranks and scores on a published board are
open.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import aggregate, periods
from app.models import Leaderboard, MetricDefinition, Organization, Team, UserAccount
from app.periods import Period
from app.scope import EVERYONE


def _faces(db: DbSession, user_ids: list[int]) -> dict[int, str]:
    """The photo hash for each of these people, where they have one.

    Joined to `stored_asset` for the hash alone — the bytes are deferred on that
    model precisely so a query like this stays cheap.
    """
    from app.models import StoredAsset

    rows = db.execute(
        select(UserAccount.id, StoredAsset.sha256)
        .join(
            StoredAsset,
            StoredAsset.id
            == func.coalesce(
                UserAccount.custom_photo_image_id, UserAccount.tenant_photo_image_id
            ),
        )
        .where(UserAccount.id.in_(user_ids))
    ).all()
    return {user_id: digest for user_id, digest in rows}


@dataclass
class Entry:
    rank: int
    entity_id: int
    entity_name: str
    team_name: str | None
    value: Decimal
    #: Places gained since the previous period. None for a new entrant — which
    #: is not the same as "did not move", and showing 0 would claim otherwise.
    movement: int | None
    #: The face to draw, on a board of people. Always None on a team or office
    #: board: a team does not have one, and falling back to a member's would
    #: pick an arbitrary person to represent everybody.
    photo_digest: str | None = None


@dataclass
class BoardResult:
    period: Period
    entries: list[Entry]
    #: The viewer's own row, even when it falls outside `display_limit`.
    #: Being 14th on a top-10 board is exactly when a person most wants to know
    #: where they are.
    viewer_entry: Entry | None
    total_entrants: int


def can_view(db: DbSession, actor: UserAccount, board: Leaderboard) -> bool:
    """Whether `actor` may open this board at all."""
    if board.organization_id != actor.organization_id:
        return False
    if actor.org_role == "admin":
        return True

    if board.visibility == "org":
        # Everyone signed in, including agents. This is the deliberate hole.
        return True

    if board.visibility == "team":
        # Anyone on the team it covers. A manager of that team qualifies by the
        # same test, since a manager is on their team.
        return actor.team_id is not None and actor.team_id == board.scope_team_id

    # private — the person who made it, and admins, handled above.
    return board.created_by_user_id == actor.id


def _entrants_filter(
    board: Leaderboard, narrow: dict[str, int | None] | None = None
) -> dict[str, int | None]:
    """Which rows count: one team's, one office's, or the whole organization.

    `narrow` is a wall's audience, applied on top. It only fills axes the board
    leaves open — a board already pinned to a team keeps that team, because the
    board's own definition is the more specific statement of intent.

    A board pinned to a *different* office than the wall cannot arise here: the
    channel editor refuses that combination when it is authored, which is a far
    better place to say so than an empty screen in front of a room.
    """
    chosen = {
        "team_id": board.scope_team_id if board.scope_type == "team" else None,
        "office_id": board.scope_office_id if board.scope_type == "office" else None,
    }
    for axis, value in (narrow or {}).items():
        if value is not None and chosen.get(axis) is None:
            chosen[axis] = value
    return chosen


def _rank_map(rows: list[aggregate.Row]) -> dict[int, int]:
    return {row.subject_id: row.rank for row in rows}


def run(
    db: DbSession,
    org: Organization,
    actor: UserAccount,
    board: Leaderboard,
    *,
    anchor: date | None = None,
    apply_limit: bool = True,
    narrow: dict[str, int | None] | None = None,
) -> BoardResult:
    """Compute the board. Assumes `can_view` has already passed.

    `apply_limit=False` returns every entrant. Export uses it: `display_limit`
    is a drawing decision, and a truncated spreadsheet is the kind of thing
    that gets pasted into a report without anyone noticing what is missing.
    """
    metric = db.get(MetricDefinition, board.metric_definition_id)
    period = periods.resolve(org, board.period_type, anchor)

    common = {
        "group_by": board.entity_type,
        **_entrants_filter(board, narrow),
        "dense_rank": board.rank_method == "dense_rank",
        # EVERYONE, explicitly. `can_view` has already authorised the whole
        # board; narrowing by the viewer here would show an agent a board of
        # one row and quietly call it a ranking.
        "visible": EVERYONE,
    }

    rows = aggregate.run(db, org.id, actor, metric, period, **common)

    # Movement needs the same board over the preceding window. Computed rather
    # than stored: a stored rank would be wrong the moment a connector
    # backfilled a day, exactly like a stored score.
    previous_ranks: dict[int, int] = {}
    try:
        earlier = periods.previous(org, period)
        previous_ranks = _rank_map(
            aggregate.run(db, org.id, actor, metric, earlier, **common)
        )
    except ValueError:
        # No defined predecessor. Every entrant then reads as new, which is
        # honest — there is nothing to have moved from.
        pass

    entries = [
        Entry(
            rank=row.rank,
            entity_id=row.subject_id,
            entity_name=row.subject_name,
            team_name=row.team_name,
            value=row.value,
            # Positive means moved UP, because rank 5 -> 2 is a gain of three
            # and nobody says "improved by minus three".
            movement=(
                previous_ranks[row.subject_id] - row.rank
                if row.subject_id in previous_ranks
                else None
            ),
        )
        for row in rows
    ]

    # **One query for every face, not one per row.** A board of forty people
    # would otherwise be forty round trips to draw forty avatars, and the wall
    # redraws on a timer.
    if board.entity_type == "user" and entries:
        faces = _faces(db, [e.entity_id for e in entries])
        for entry in entries:
            entry.photo_digest = faces.get(entry.entity_id)

    # "You" is a different row on each kind of board. An office board is
    # highlighted by the viewer's office, which they reach through their team —
    # matching a user id against office ids would highlight nothing, or worse,
    # the wrong office.
    if board.entity_type == "team":
        viewer_id = actor.team_id
    elif board.entity_type == "office":
        team = db.get(Team, actor.team_id) if actor.team_id else None
        viewer_id = team.office_id if team else None
    else:
        viewer_id = actor.id
    viewer_entry = next((e for e in entries if e.entity_id == viewer_id), None)

    shown = (
        entries[: board.display_limit]
        if apply_limit and board.display_limit
        else entries
    )

    return BoardResult(
        period=period,
        entries=shown,
        # Only worth returning when they are not already on screen.
        viewer_entry=(
            viewer_entry if viewer_entry and viewer_entry not in shown else None
        ),
        total_entrants=len(entries),
    )
