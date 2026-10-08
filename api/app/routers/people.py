"""A person's profile (Phase 9): what they have earned, and how they are doing.

One endpoint, one page. The public half — badges, wins, points, tier — goes to
anyone in the organization who may see the profile at all; the private half —
goals, totals, board ranks — only to the person and those who manage them.
**The server decides**: a viewer not entitled to the private half is not sent
it, so nothing on the page can leak it. See `app/people.py` for the rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import events, people
from app.db import get_db
from app.models import (
    Goal,
    Leaderboard,
    MetricDefinition,
    Notification,
    Office,
    Organization,
    Team,
    UserAccount,
)
from app.scope import can_see_user, has_capability
from app.sessions import current_user

router = APIRouter(prefix="/people", tags=["people"])

#: How many wins and shout-outs the page lists. Enough to be a story; the
#: Recognition feed has the rest.
WINS_SHOWN = 8
#: Boards whose numbers it shows. A person is on a handful at most.
BOARDS_SHOWN = 6


class Person(BaseModel):
    id: int
    name: str
    photo_digest: str | None = None
    job_title: str | None = None
    team_name: str | None = None
    office_name: str | None = None
    #: What they have bought and wear (6.x): a ring colour, a title.
    ring: str | None = None
    title: str | None = None


class Season(BaseModel):
    name: str
    points: int
    #: Null when they have no points yet — not last.
    rank: int | None = None
    of: int
    tier: str | None = None
    next_tier: str | None = None
    to_next_tier: int | None = None


class Badge(BaseModel):
    badge_id: int
    name: str
    icon: str
    reason: str
    earned_at: datetime
    times: int = 1


class Win(BaseModel):
    id: int
    #: "Recognition", "Goal hit", a celebration rule's name.
    occasion: str
    title: str
    body: str | None = None
    #: The number it was for, as it was announced: "$12,400".
    figure: str | None = None
    #: For a shout-out: who gave it.
    from_name: str | None = None
    created_at: datetime


class Number(BaseModel):
    board_id: int
    board_name: str
    metric_name: str
    period_label: str
    value: Decimal
    unit: str
    decimal_places: int
    unit_label: str | None = None
    rank: int
    of: int
    #: Places gained since last period; null for somebody new to the board.
    movement: int | None = None


class Place(BaseModel):
    """Where somebody stands on a board the viewer can open anyway (P4-12) —
    the place, never the number, which stays on the private half."""

    board_id: int
    board_name: str
    period_label: str
    rank: int
    of: int


class Private(BaseModel):
    """Only for the person and those who manage them."""

    goals: list[dict]
    numbers: list[Number]
    streak_days: int | None = None


class Can(BaseModel):
    """What the viewer may do from here — so the page offers only that."""

    recognise: bool = False
    give_badge: bool = False
    #: Where "Edit" goes, or null: Account for yourself, the person page
    #: under Users for whoever manages them.
    edit: str | None = None


class Profile(BaseModel):
    person: Person
    is_me: bool
    season: Season | None = None
    badges: list[Badge]
    wins: list[Win]
    #: Null unless the viewer is entitled to it.
    private: Private | None = None
    #: Board places, for a viewer without the private half: the boards they
    #: can open show them already, so a profile hiding them only read as empty.
    places: list[Place] = []
    can: Can


@router.get("/{person_id}", response_model=Profile)
def read_profile(
    person_id: int,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> Profile:
    person = db.get(UserAccount, person_id)
    # 404 rather than 403 for somebody out of reach: confirming they exist is
    # itself something the viewer was not entitled to learn.
    if person is None or not people.may_see_profile(db, actor, person):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Person not found.")

    org = db.get(Organization, actor.organization_id)
    in_reach = can_see_user(db, actor, person.id)
    is_me = actor.id == person.id

    private = _private(db, org, actor, person) if people.may_see_private(db, actor, person) else None
    return Profile(
        person=_person(db, person),
        is_me=is_me,
        season=_season(db, org, person),
        badges=_badges(db, org, person),
        wins=_wins(db, org, person),
        private=private,
        places=(
            []
            if private is not None
            else [
                Place(
                    board_id=n.board_id,
                    board_name=n.board_name,
                    period_label=n.period_label,
                    rank=n.rank,
                    of=n.of,
                )
                for n in _numbers(db, org, actor, person)[0]
            ]
        ),
        can=Can(
            recognise=not is_me and in_reach and has_capability(actor, "recognition.send"),
            # The same test `give_badge` makes: a manager or an admin, for
            # somebody they can see.
            give_badge=not is_me and in_reach and actor.org_role in ("admin", "manager"),
            edit=(
                "/account"
                if is_me
                else f"/users/{person.id}"
                if in_reach and has_capability(actor, "users.view")
                else None
            ),
        ),
    )


def _person(db: DbSession, person: UserAccount) -> Person:
    from app import photos, unlocks

    team = db.get(Team, person.team_id) if person.team_id else None
    office = db.get(Office, team.office_id) if team and team.office_id else None
    worn = unlocks.worn_by(db, [person.id]).get(person.id)
    return Person(
        id=person.id,
        name=person.full_name,
        photo_digest=photos.digest_of(db, person),
        job_title=person.job_title or None,
        team_name=team.name if team else None,
        office_name=office.name if office else None,
        ring=worn.ring if worn else None,
        title=worn.title if worn else None,
    )


def _season(db: DbSession, org: Organization, person: UserAccount) -> Season | None:
    """Points and place this season — the table everyone can already see."""
    from app import points, seasons, tiers

    season = seasons.current(db, org)
    if season is None:
        return None
    table = points.standings(db, season)
    mine = next((row for row in table if row.user_id == person.id), None)
    earned = points.balance(db, season.id, person.id)
    reached = tiers.standing_for(earned, tiers.ladder(db, org.id))
    return Season(
        name=season.name,
        points=earned,
        rank=mine.rank if mine else None,
        of=len(table),
        tier=reached.current.name if reached.current else None,
        next_tier=reached.next.name if reached.next else None,
        to_next_tier=reached.to_next,
    )


def _badges(db: DbSession, org: Organization, person: UserAccount) -> list[Badge]:
    from app import badges

    return [
        Badge(
            badge_id=held.badge_id,
            name=held.name,
            icon=held.icon,
            reason=held.reason,
            earned_at=held.earned_at,
            times=held.times,
        )
        for held in badges.held_by(db, org.id, person.id)
    ]


def _wins(db: DbSession, org: Organization, person: UserAccount) -> list[Win]:
    """Their public wins, newest first — each once, however many it reached.

    `events.is_public` decides, as on the wall: being behind on a goal is a
    conversation with a manager, not a line on somebody's profile.
    """
    from app import channels

    rows = db.scalars(
        select(Notification)
        .where(
            Notification.organization_id == org.id,
            Notification.about_user_id == person.id,
        )
        .distinct(
            Notification.event_key,
            Notification.subject_type,
            Notification.subject_id,
            Notification.period_anchor,
        )
        .order_by(
            Notification.event_key,
            Notification.subject_type,
            Notification.subject_id,
            Notification.period_anchor,
            Notification.created_at.desc(),
        )
    ).all()
    shown = sorted(
        (n for n in rows if events.is_public(n.event_key)),
        key=lambda n: (n.created_at, n.id),
        reverse=True,
    )[:WINS_SHOWN]

    givers = {
        user.id: user.full_name
        for user in db.scalars(
            select(UserAccount).where(
                UserAccount.id.in_({n.created_by_user_id for n in shown if n.created_by_user_id})
            )
        ).all()
    }
    return [
        Win(
            id=n.id,
            occasion=channels.occasion_of(n),
            title=n.title,
            body=n.body,
            figure=n.figure,
            from_name=givers.get(n.created_by_user_id) if n.event_key == events.RECOGNITION.key else None,
            created_at=n.created_at,
        )
        for n in shown
    ]


def _private(
    db: DbSession, org: Organization, actor: UserAccount, person: UserAccount
) -> Private:
    """Goals and numbers, for the person and whoever manages them."""
    from app import goals as goal_service, streaks
    from app.routers.goals import _to_read

    now = datetime.now(UTC)
    goals = []
    for goal in db.scalars(
        select(Goal)
        .where(
            Goal.organization_id == org.id,
            Goal.subject_user_id == person.id,
            Goal.archived_at.is_(None),
        )
        .order_by(Goal.period_anchor.desc(), Goal.id.desc())
    ).all():
        period = goal_service.resolve_period(org, goal)
        # Only what is still running: last month's are history, and the
        # goal's own page keeps them.
        if period.end <= now:
            continue
        goals.append(_to_read(db, org, actor, goal).model_dump(mode="json"))

    numbers, first_metric = _numbers(db, org, actor, person)

    streak = (
        streaks.current(db, org, metric_id=first_metric, user_id=person.id)
        if first_metric is not None
        else None
    )
    return Private(goals=goals, numbers=numbers, streak_days=streak or None)


def _numbers(
    db: DbSession, org: Organization, actor: UserAccount, person: UserAccount
) -> tuple[list[Number], int | None]:
    """Their places and numbers on the boards **the viewer** can open — each
    board run as the viewer, so nothing here is more than its page shows."""
    from app import leaderboards

    numbers: list[Number] = []
    first_metric: int | None = None
    for board in db.scalars(
        select(Leaderboard)
        .where(
            Leaderboard.organization_id == org.id,
            Leaderboard.archived_at.is_(None),
            Leaderboard.entity_type == "user",
        )
        .order_by(Leaderboard.name)
    ).all():
        if len(numbers) >= BOARDS_SHOWN or not leaderboards.can_view(db, actor, board):
            continue
        result = leaderboards.run(db, org, actor, board, apply_limit=False)
        entry = next((e for e in result.entries if e.entity_id == person.id), None)
        metric = db.get(MetricDefinition, board.metric_definition_id)
        if entry is None or metric is None:
            continue
        # **Nothing yet is not a place** (P3-6): "$0.00 · 39th of 137" ranks
        # somebody for doing nothing. A zero can be a real best where lower is
        # better, so only where higher is.
        if not entry.value and metric.direction != "lower_is_better":
            continue
        first_metric = first_metric or metric.id
        numbers.append(
            Number(
                board_id=board.id,
                board_name=board.name,
                metric_name=metric.name,
                period_label=result.period.label,
                value=entry.value,
                unit=metric.unit,
                decimal_places=metric.decimal_places,
                unit_label=metric.unit_label,
                rank=entry.rank,
                of=result.total_entrants,
                movement=entry.movement,
            )
        )
    return numbers, first_metric
