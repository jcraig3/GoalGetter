"""One target for a whole team or office, adjusted person by person (6.12).

Setting a monthly target for twelve people was twelve trips through the goal
form, each one choosing the same metric and the same period again. Most of a
team gets the same number; a few get a different one — the new starter, the
part-timer, the person carrying the biggest accounts. So this is a grid: one
target filled in for everybody, last period's figure beside each name to argue
the exceptions from, and a single save.

**The goals it makes are ordinary goals**, one per person, exactly as the form
would have made them. There is no "group goal" row behind them: a person's
goal is theirs, edited and archived like any other, and nothing has to
remember which ones arrived together.

**Somebody who already has this goal is shown it, not given a second one.**
The grid says what their target is now, and saving updates it — a bulk tool
that quietly doubled everybody's goals for the month would be worse than the
twelve trips.
"""

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import aggregate, audit, periods
from app.db import get_db
from app.models import Goal, MetricDefinition, Office, Organization, Team, UserAccount
from app.routers.goal_preview import _suggest
from app.routers.goals import _check_period
from app.scope import visible_user_ids, EVERYONE
from app.sessions import require_role
from app.validation import OptionalName

router = APIRouter(prefix="/goals/bulk", tags=["goals"])

#: The periods a bulk goal can cover — the ones the goal form offers. A custom
#: range has no "last period" to show beside each name, and is a one-off by
#: nature rather than something a team is set every month.
BULK_PERIODS = ("day", "week", "month", "quarter", "year")

#: Who counts as on the team for a target. An invited person has not signed in
#: yet but is working — directory sync makes most accounts that way.
WORKING = ("active", "invited")

#: More rows than this is not a team; it is a typo in the office picker.
MAX_ROWS = 500


class GroupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: int
    group_type: str
    group_id: int
    period_type: str = "month"

    @field_validator("group_type")
    @classmethod
    def _group(cls, value: str) -> str:
        if value not in ("team", "office"):
            raise ValueError("group_type must be 'team' or 'office'.")
        return value

    @field_validator("period_type")
    @classmethod
    def _period(cls, value: str) -> str:
        if value not in BULK_PERIODS:
            raise ValueError(f"period_type must be one of: {', '.join(BULK_PERIODS)}")
        return value


class Existing(BaseModel):
    goal_id: int
    target_value: Decimal


class RosterRow(BaseModel):
    user_id: int
    name: str
    team_name: str | None
    photo_digest: str | None
    #: Their figure for the last complete period, to set an exception from.
    last_value: Decimal
    #: Their goal for this metric and period already, if they have one.
    existing: Existing | None = None


class Roster(BaseModel):
    group_name: str
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None = None
    direction: str
    period_label: str
    #: The period the "last" column is from — "September 2026".
    last_period_label: str
    #: A starting point for everybody: a little past the group's typical
    #: last period. See `goal_preview._suggest`.
    suggested_target: Decimal | None
    people: list[RosterRow]


class BulkRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int
    target_value: Decimal = Field(gt=0)


class BulkWrite(GroupRequest):
    name: OptionalName(120) = None
    recurring: bool = False
    #: One per person to set. A person left out is skipped — no goal made, and
    #: an existing one left as it was.
    rows: list[BulkRow] = Field(min_length=1, max_length=MAX_ROWS)


class BulkResult(BaseModel):
    created: int
    updated: int
    unchanged: int


@router.post("/roster", response_model=Roster)
def roster(
    payload: GroupRequest,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> Roster:
    """Everybody the target would be set for, with what they did last time."""
    org = db.get(Organization, actor.organization_id)
    metric = _metric(db, actor, payload.metric_id)
    group_name, people = _people(db, actor, payload.group_type, payload.group_id)

    anchor = _check_period(org, payload.period_type, None, None, None)
    current = periods.resolve(org, payload.period_type, periods.today(org))
    last = periods.previous(org, current)

    # One query for everybody's last period, not one per person.
    values = {
        row.subject_id: row.value
        for row in aggregate.run(
            db, org.id, actor, metric, last, group_by="user", visible=EVERYONE
        )
    }
    existing = _existing(db, org, metric, payload.period_type, anchor, [p.id for p in people])
    teams = {
        t.id: t.name
        for t in db.scalars(
            select(Team).where(Team.id.in_({p.team_id for p in people if p.team_id}))
        ).all()
    }

    # Suggested from the people who did something: a new starter's zero is
    # not evidence about what the team does.
    measured = [values[p.id] for p in people if values.get(p.id)]
    suggested = None
    if measured:
        typical = sorted(measured)[len(measured) // 2]
        suggested = _suggest(typical, metric.direction, metric.decimal_places)

    return Roster(
        group_name=group_name,
        metric_name=metric.name,
        unit=metric.unit,
        decimal_places=metric.decimal_places,
        unit_label=metric.unit_label,
        direction=metric.direction,
        period_label=current.label,
        last_period_label=last.label,
        suggested_target=suggested,
        people=[
            RosterRow(
                user_id=p.id,
                name=p.full_name,
                team_name=teams.get(p.team_id),
                photo_digest=p.photo_digest,
                last_value=values.get(p.id, Decimal(0)),
                existing=(
                    Existing(goal_id=existing[p.id].id, target_value=existing[p.id].target_value)
                    if p.id in existing
                    else None
                ),
            )
            for p in people
        ],
    )


@router.post("", response_model=BulkResult, status_code=status.HTTP_201_CREATED)
def set_for_group(
    payload: BulkWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> BulkResult:
    """A goal for each person in the grid, all or nothing."""
    org = db.get(Organization, actor.organization_id)
    metric = _metric(db, actor, payload.metric_id)
    group_name, people = _people(db, actor, payload.group_type, payload.group_id)
    anchor = _check_period(org, payload.period_type, None, None, None)

    members = {p.id for p in people}
    chosen: dict[int, Decimal] = {}
    for row in payload.rows:
        # Refused rather than dropped: a name in the request that is not in
        # the group means the grid and the group disagree, and saving part of
        # it would leave somebody believing they set a target they did not.
        if row.user_id not in members:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Somebody in the grid is not in {group_name} any more. Reload it and try again.",
            )
        chosen[row.user_id] = row.target_value

    existing = _existing(db, org, metric, payload.period_type, anchor, list(chosen))
    created = updated = unchanged = 0
    for user_id, target in chosen.items():
        goal = existing.get(user_id)
        if goal is not None:
            if goal.target_value == target:
                unchanged += 1
            else:
                goal.target_value = target
                updated += 1
            continue
        db.add(
            Goal(
                organization_id=org.id,
                metric_definition_id=metric.id,
                subject_type="user",
                subject_user_id=user_id,
                target_value=target,
                period_type=payload.period_type,
                period_anchor=anchor,
                name=payload.name,
                created_by_user_id=actor.id,
                recurring=payload.recurring,
            )
        )
        created += 1

    # One entry for the whole grid: it was one decision, and twelve entries
    # would bury the rest of the log.
    audit.record(
        db,
        actor=actor,
        action="goal.bulk_set",
        request=request,
        metric=metric.key,
        group=f"{payload.group_type}:{group_name}",
        period=payload.period_type,
        created=created,
        updated=updated,
    )
    db.commit()
    return BulkResult(created=created, updated=updated, unchanged=unchanged)


def _metric(db: DbSession, actor: UserAccount, metric_id: int) -> MetricDefinition:
    metric = db.get(MetricDefinition, metric_id)
    if metric is None or metric.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found.")
    if metric.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{metric.name}' is archived. Restore it before setting goals against it.",
        )
    return metric


def _people(
    db: DbSession, actor: UserAccount, group_type: str, group_id: int
) -> tuple[str, list[UserAccount]]:
    """The group's name and the working people in it, by name.

    A manager sets targets for their own team, as with a single goal; an
    office is several teams, so it is an admin's.
    """
    if group_type == "team":
        team = db.get(Team, group_id)
        if team is None or team.organization_id != actor.organization_id or team.archived_at:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
        if actor.org_role != "admin" and team.id != actor.team_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only set goals for your own team.",
            )
        name = team.name
        where = UserAccount.team_id == team.id
    else:
        office = db.get(Office, group_id)
        if office is None or office.organization_id != actor.organization_id or office.archived_at:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Office not found.")
        if actor.org_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an admin can set goals for a whole office.",
            )
        name = office.name
        where = UserAccount.team_id.in_(
            select(Team.id).where(Team.office_id == office.id, Team.archived_at.is_(None))
        )

    people = list(
        db.scalars(
            select(UserAccount)
            .where(
                UserAccount.organization_id == actor.organization_id,
                where,
                UserAccount.hidden_at.is_(None),
                UserAccount.status.in_(WORKING),
            )
            .order_by(UserAccount.full_name)
        ).all()
    )
    visible = visible_user_ids(db, actor)
    if visible is not EVERYONE:
        people = [p for p in people if p.id in visible]
    return name, people


def _existing(
    db: DbSession,
    org: Organization,
    metric: MetricDefinition,
    period_type: str,
    anchor,
    user_ids: list[int],
) -> dict[int, Goal]:
    """Each person's live goal for this metric and period, if any — the
    newest, should somebody have made two by hand."""
    if not user_ids:
        return {}
    rows = db.scalars(
        select(Goal)
        .where(
            Goal.organization_id == org.id,
            Goal.metric_definition_id == metric.id,
            Goal.subject_type == "user",
            Goal.subject_user_id.in_(user_ids),
            Goal.period_type == period_type,
            Goal.period_anchor == anchor,
            Goal.archived_at.is_(None),
        )
        .order_by(Goal.id)
    ).all()
    return {goal.subject_user_id: goal for goal in rows}
