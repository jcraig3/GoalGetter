"""Jump to anything: the command palette's search (6.16).

One request for every kind of thing a person might type the name of — a
person, a board, a goal, a contest, a channel, and since 7.9 a team, an
office, a celebration rule, a badge and a metric — each narrowed by **exactly
the rule its own list uses**, or offered only to whoever can open that list. A palette that offered a board its list would hide
would leak the board's name, which is the thing the list's filter is there to
protect; so the boards and goals come from the lists' own queries
(`leaderboards.visible_boards`, `goals.visible_goals`), and contests from the
same `_may_see`.

A handful of each, best first: a name that *starts* with what was typed
beats one that merely contains it.
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select, true
from sqlalchemy.orm import Session as DbSession

from app.db import get_db
from app.models import (
    AchievementRule,
    Badge,
    Channel,
    Competition,
    Goal,
    Leaderboard,
    MetricDefinition,
    Office,
    Team,
    UserAccount,
)
from app.scope import EVERYONE, has_capability, visible_user_ids
from app.sessions import current_user

router = APIRouter(prefix="/search", tags=["search"])

#: Per kind. A palette is for jumping, not browsing.
EACH = 6


class Hit(BaseModel):
    id: int
    name: str
    #: The second line: a person's team, a goal's metric and period.
    detail: str | None = None
    #: A person's face.
    photo_digest: str | None = None


class Results(BaseModel):
    people: list[Hit] = []
    boards: list[Hit] = []
    goals: list[Hit] = []
    competitions: list[Hit] = []
    channels: list[Hit] = []
    teams: list[Hit] = []
    offices: list[Hit] = []
    rules: list[Hit] = []
    badges: list[Hit] = []
    metrics: list[Hit] = []


def _like(text: str) -> str:
    """`%text%`, with the wildcards somebody might type taken literally."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _first(column, text: str):
    """Names starting with the text first, then alphabetical."""
    return (case((func.lower(column).startswith(text.lower()), 0), else_=1), column)


@router.get("", response_model=Results)
def search(
    q: str = Query(min_length=1, max_length=80),
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> Results:
    from app.routers.competitions import _may_see
    from app.routers.goals import visible_goals
    from app.routers.leaderboards import visible_boards

    text = " ".join(q.split())
    if not text:
        return Results()
    like = _like(text)
    out = Results()

    # People open their profile (9.3). **Who is found is who can be opened**:
    # with profiles open, everybody — an agent finding a colleague is the
    # point; with them closed, only those the viewer manages, as before.
    from app.models import Organization

    manages = has_capability(actor, "users.view")
    org = db.get(Organization, actor.organization_id)
    open_profiles = org is not None and org.profiles_public
    if open_profiles or manages:
        # An address is found and shown only to somebody who manages people;
        # a colleague is found by name.
        matches = (
            or_(UserAccount.full_name.ilike(like), UserAccount.email.ilike(like))
            if manages
            else UserAccount.full_name.ilike(like)
        )
        query = (
            select(UserAccount, Team.name)
            .outerjoin(Team, Team.id == UserAccount.team_id)
            .where(
                UserAccount.organization_id == actor.organization_id,
                UserAccount.hidden_at.is_(None),
                matches,
            )
            .order_by(*_first(UserAccount.full_name, text))
        )
        if not open_profiles:
            visible = visible_user_ids(db, actor)
            if visible is not EVERYONE:
                query = query.where(UserAccount.id.in_(visible))
        # The team **and** the address (review §8): "Test User" and "Test user"
        # are two accounts, and only the address tells them apart.
        out.people = [
            Hit(
                id=user.id,
                name=user.full_name,
                detail=" · ".join(part for part in (team, user.email if manages else None) if part),
                photo_digest=user.photo_digest,
            )
            for user, team in db.execute(query.limit(EACH)).all()
        ]

    boards = db.scalars(
        visible_boards(actor)
        .where(Leaderboard.archived_at.is_(None), Leaderboard.name.ilike(like))
        .order_by(*_first(Leaderboard.name, text))
        .limit(EACH)
    ).all()
    out.boards = [Hit(id=b.id, name=b.name) for b in boards]

    # A goal is mostly known by who it is for and what it measures; its own
    # name is optional. So any of the three matches.
    subject = func.coalesce(UserAccount.full_name, Team.name, "")
    goals = db.execute(
        visible_goals(db, actor)
        .add_columns(MetricDefinition.name, subject)
        .join(MetricDefinition, MetricDefinition.id == Goal.metric_definition_id)
        .outerjoin(UserAccount, UserAccount.id == Goal.subject_user_id)
        .outerjoin(Team, Team.id == Goal.subject_team_id)
        .where(
            Goal.archived_at.is_(None),
            or_(Goal.name.ilike(like), MetricDefinition.name.ilike(like), subject.ilike(like)),
        )
        .order_by(Goal.period_anchor.desc(), Goal.id.desc())
        .limit(EACH)
    ).all()
    # Said by period — "October 2026" — because a repeating goal is the same
    # person and metric every month, and two identical lines are a guess.
    from app import goals as goal_service
    from app.models import Organization

    org = db.get(Organization, actor.organization_id)
    out.goals = []
    for goal, metric, who in goals:
        when = goal_service.resolve_period(org, goal).label
        out.goals.append(
            Hit(
                id=goal.id,
                name=goal.name or (f"{who} — {metric}" if who else metric),
                detail=f"{metric} · {when}" if goal.name else when,
            )
        )

    contests = db.scalars(
        select(Competition)
        .where(
            Competition.organization_id == actor.organization_id,
            Competition.name.ilike(like),
            # Drafts are hidden from agents, as on the contests list.
            Competition.state != "draft" if actor.org_role == "agent" else true(),
        )
        .order_by(*_first(Competition.name, text))
        .limit(EACH * 4)
    ).all()
    out.competitions = [
        Hit(id=c.id, name=c.name, detail=c.state)
        for c in contests
        if _may_see(db, actor, c)
    ][:EACH]

    if actor.org_role == "admin":
        channels = db.scalars(
            select(Channel)
            .where(Channel.organization_id == actor.organization_id, Channel.name.ilike(like))
            .order_by(*_first(Channel.name, text))
            .limit(EACH)
        ).all()
        out.channels = [Hit(id=c.id, name=c.name) for c in channels]

    # Teams: everybody can open the Teams page. "metropolis" found nothing (§8).
    teams = db.execute(
        select(Team, Office.name)
        .outerjoin(Office, Office.id == Team.office_id)
        .where(
            Team.organization_id == actor.organization_id,
            Team.archived_at.is_(None),
            Team.name.ilike(like),
        )
        .order_by(*_first(Team.name, text))
        .limit(EACH)
    ).all()
    out.teams = [Hit(id=t.id, name=t.name, detail=office) for t, office in teams]

    if has_capability(actor, "offices.manage"):
        out.offices = [
            Hit(id=o.id, name=o.name)
            for o in db.scalars(
                select(Office)
                .where(
                    Office.organization_id == actor.organization_id,
                    Office.archived_at.is_(None),
                    Office.name.ilike(like),
                )
                .order_by(*_first(Office.name, text))
                .limit(EACH)
            ).all()
        ]

    if has_capability(actor, "integrations.manage"):
        out.rules = [
            Hit(id=r.id, name=r.name, detail=None if r.enabled else "Off")
            for r in db.scalars(
                select(AchievementRule)
                .where(
                    AchievementRule.organization_id == actor.organization_id,
                    AchievementRule.name.ilike(like),
                )
                .order_by(*_first(AchievementRule.name, text))
                .limit(EACH)
            ).all()
        ]

    if has_capability(actor, "org.settings.edit"):
        out.badges = [
            Hit(id=b.id, name=b.name)
            for b in db.scalars(
                select(Badge)
                .where(Badge.organization_id == actor.organization_id, Badge.name.ilike(like))
                .order_by(*_first(Badge.name, text))
                .limit(EACH)
            ).all()
        ]

    if has_capability(actor, "metrics.manage"):
        out.metrics = [
            Hit(id=m.id, name=m.name)
            for m in db.scalars(
                select(MetricDefinition)
                .where(
                    MetricDefinition.organization_id == actor.organization_id,
                    MetricDefinition.archived_at.is_(None),
                    MetricDefinition.name.ilike(like),
                )
                .order_by(*_first(MetricDefinition.name, text))
                .limit(EACH)
            ).all()
        ]

    return out
