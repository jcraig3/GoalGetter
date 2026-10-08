from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session as DbSession

from app import audit, goal_tiers, goals as goal_service, pace as pace_service, periods
from app.pace import CUMULATIVE
from app.trend import Trend, TrendPoint
from app.appearance import Appearance
from app.db import get_db
from app.models import Goal, MetricDefinition, Organization, Team, UserAccount
from app.models.goal import SUBJECT_TYPES
from app.scope import EVERYONE, can_see_user, visible_user_ids
from app.sessions import current_user, require_role
from app.validation import OptionalName

router = APIRouter(prefix="/goals", tags=["goals"])


class LevelRead(BaseModel):
    level: int
    label: str
    value: Decimal
    reached: bool


class LevelWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Decimal = Field(gt=0)
    label: str | None = Field(default=None, max_length=40)


class GoalRead(BaseModel):
    id: int
    name: str | None
    metric_id: int
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None = None
    direction: str

    subject_type: str
    #: Null for an organization goal, which is about everyone.
    subject_id: int | None
    subject_name: str

    target_value: Decimal
    #: Levels past the target, each with whether it is reached this period.
    stretch: list[LevelRead] = []
    period_type: str
    period_label: str
    period_start: datetime
    period_end: datetime

    # Computed, never stored — see app/goals.py.
    current_value: Decimal
    percent: float
    attained: bool
    archived: bool

    # Pace. `expected_percent` and `projected` are null for metrics that do not
    # accumulate — an average is not "a third of the way" to anything.
    elapsed_percent: float
    expected_percent: float | None
    projected_value: Decimal | None
    status: str
    needs_attention: bool

    #: Only when the caller asked for it — see `trend` on the list endpoint.
    trend: Trend | None = None
    recurring: bool
    recurrence_ends_on: date | None
    #: Set on a copy the scheduler made, pointing at the goal it repeats.
    spawned_from_goal_id: int | None

    #: What this has chosen for itself, sparsely. Empty means it follows the
    #: organization; a channel or a single screen can still override. See
    #: `app/appearance.py`.
    appearance: dict = {}


class GoalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: int
    subject_type: str
    #: Which person or team. **Absent for an organization goal**, which is
    #: about everyone and so names nobody — see `models/goal.py`.
    subject_id: int | None = None
    target_value: Decimal = Field(gt=0)
    period_type: str = "month"
    period_anchor: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    name: OptionalName(120) = None
    recurring: bool = False
    recurrence_ends_on: date | None = None
    #: Up to three levels past the target, each harder than the last.
    stretch: list[LevelWrite] = Field(default_factory=list, max_length=goal_tiers.MAX_LEVELS)

    @field_validator("subject_type")
    @classmethod
    def _subject(cls, value: str) -> str:
        if value not in SUBJECT_TYPES:
            raise ValueError(f"subject_type must be one of: {', '.join(SUBJECT_TYPES)}")
        return value

    @field_validator("period_type")
    @classmethod
    def _period(cls, value: str) -> str:
        if value not in periods.PERIOD_TYPES:
            raise ValueError(
                f"Unknown period type. Expected one of: {', '.join(periods.PERIOD_TYPES)}"
            )
        return value

    #: **Replaces rather than merges.** A merging update could not express "stop
    #: setting this and follow the default", because absence would mean "leave
    #: it alone" — the opposite of what a reset needs.
    appearance: Appearance | None = None


class GoalUpdate(BaseModel):
    """Target, name, and period are editable. Metric and subject are not.

    Changing who a goal is for, or what it measures, makes it a different goal
    — and one whose history of "you were at 60%" now refers to something else.
    Delete and create instead, which is honest about what happened.
    """

    model_config = ConfigDict(extra="forbid")

    target_value: Decimal | None = Field(default=None, gt=0)
    name: OptionalName(120) = None
    #: Replaces the levels. Absent keeps them; an empty list removes them.
    stretch: list[LevelWrite] | None = Field(default=None, max_length=goal_tiers.MAX_LEVELS)
    recurring: bool | None = None
    recurrence_ends_on: date | None = None
    period_type: str | None = None
    period_anchor: date | None = None
    period_start: date | None = None
    period_end: date | None = None

    @field_validator("period_type")
    @classmethod
    def _period(cls, value: str | None) -> str | None:
        if value is not None and value not in periods.PERIOD_TYPES:
            raise ValueError(
                f"Unknown period type. Expected one of: {', '.join(periods.PERIOD_TYPES)}"
            )
        return value

    #: **Replaces rather than merges.** A merging update could not express "stop
    #: setting this and follow the default", because absence would mean "leave
    #: it alone" — the opposite of what a reset needs.
    appearance: Appearance | None = None


def _org(db: DbSession, actor: UserAccount) -> Organization:
    return db.get(Organization, actor.organization_id)


def _check_period(
    org: Organization,
    period_type: str,
    anchor: date | None,
    start: date | None,
    end: date | None,
) -> date | None:
    """Resolve it now, so an unresolvable goal cannot be stored, and return the
    canonical anchor.

    Without the resolve, the failure surfaces later on whatever page tries to
    render progress, as a 500 nobody can connect to the goal that caused it.

    The anchor comes back normalised to the period's start. Any date inside a
    period names that period, and storing whichever one the client happened to
    send means two goals for the same August hold different dates — which is
    how a recurring goal created on the 13th spawned a duplicate of itself for
    the month it already covered.
    """
    try:
        resolved = periods.resolve(
            org,
            period_type,
            # The organization's today, not the server's: at 8pm on the 30th
            # in New York the server is already on the 1st, and "this month"
            # became next month.
            anchor or (periods.today(org) if period_type != "custom" else None),
            custom_start=start,
            custom_end=end,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None

    if period_type == "custom":
        return None
    return resolved.start.astimezone(ZoneInfo(org.timezone)).date()


def _check_stretch(target: Decimal, levels: list[LevelWrite], direction: str) -> list[dict]:
    try:
        return goal_tiers.check(
            target, [level.model_dump() for level in levels], direction
        )
    except ValueError as problem:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(problem)) from None


def _subject_name(db: DbSession, goal: Goal) -> str:
    if goal.subject_type == "organization":
        org = db.get(Organization, goal.organization_id)
        # The company's own name, not the word "Everyone" — a target on a wall
        # reading "Acme · 62%" says whose it is, and every other subject on
        # this screen is named.
        return org.name if org else "Everyone"
    if goal.subject_type == "team":
        team = db.get(Team, goal.subject_team_id)
        return team.name if team else "Deleted team"
    user = db.get(UserAccount, goal.subject_user_id)
    return user.full_name if user else "Deleted user"


def _to_read(
    db: DbSession,
    org: Organization,
    actor: UserAccount,
    goal: Goal,
    *,
    with_trend: bool = False,
) -> GoalRead:
    metric = db.get(MetricDefinition, goal.metric_definition_id)
    period = goal_service.resolve_period(org, goal)
    current, has_data = goal_service.current_value(db, org, actor, goal, metric)
    result = goal_service.progress(
        current, goal.target_value, metric.direction, has_data=has_data
    )
    pace = pace_service.compute(
        period=period,
        now=datetime.now(UTC),
        timezone=org.timezone,
        aggregation=metric.aggregation,
        percent=result.percent,
        attained=result.attained,
        current=result.current,
    )

    line = (
        goal_service.trend(db, org, actor, goal, metric) if with_trend else None
    )

    return GoalRead(
        id=goal.id,
        name=goal.name,
        metric_id=metric.id,
        metric_name=metric.name,
        unit=metric.unit,
        decimal_places=metric.decimal_places,
        unit_label=metric.unit_label,
        direction=metric.direction,
        subject_type=goal.subject_type,
        subject_id=goal.subject_user_id or goal.subject_team_id,
        subject_name=_subject_name(db, goal),
        target_value=goal.target_value,
        stretch=[
            LevelRead(
                level=level.level,
                label=level.label,
                value=level.value,
                reached=goal_service.progress(
                    current, level.value, metric.direction, has_data=has_data
                ).attained,
            )
            for level in goal_tiers.levels_of(goal.stretch_targets)
        ],
        period_type=goal.period_type,
        period_label=period.label,
        period_start=period.start,
        period_end=period.end,
        current_value=result.current,
        percent=result.percent,
        attained=result.attained,
        archived=goal.archived_at is not None,
        elapsed_percent=pace.elapsed_percent,
        expected_percent=pace.expected_percent,
        projected_value=pace.projected,
        status=pace.status,
        needs_attention=pace.needs_attention,
        recurring=goal.recurring,
        recurrence_ends_on=goal.recurrence_ends_on,
        spawned_from_goal_id=goal.spawned_from_goal_id,
        appearance=goal.appearance or {},
        trend=(
            Trend(
                unit=periods.bucket_unit(period),
                cumulative=metric.aggregation in CUMULATIVE,
                points=[TrendPoint(at=p.bucket, value=p.value) for p in line],
            )
            if line is not None
            else None
        ),
    )


def visible_goals(db: DbSession, actor: UserAccount):
    """The goals this person may see, as a query — shared with search (6.16)."""
    query = select(Goal).where(Goal.organization_id == actor.organization_id)
    visible = visible_user_ids(db, actor)
    if visible is not EVERYONE:
        # Their own goals, plus goals for any team they can see through the
        # people on it. A team goal is visible when its members are.
        team_ids = db.scalars(
            select(UserAccount.team_id).where(
                UserAccount.id.in_(visible), UserAccount.team_id.is_not(None)
            )
        ).all()
        query = query.where(
            or_(
                Goal.subject_user_id.in_(visible),
                Goal.subject_team_id.in_(set(team_ids)) if team_ids else False,
            )
        )
    return query


@router.get("", response_model=list[GoalRead])
def list_goals(
    mine: bool = Query(default=False, description="Only goals that apply to you"),
    needs_attention: bool = Query(
        default=False, description="Only goals behind pace or already missed"
    ),
    include_archived: bool = Query(default=False),
    trend: bool = Query(
        default=False,
        description=(
            "Include a sparkline per goal. Off by default because it costs one "
            "extra query per goal, and most callers are listing, not plotting."
        ),
    ),
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[GoalRead]:
    """Goals the actor may see.

    Scope filters the query. A goal names a person, so the list of goals is
    itself information about who exists and what is expected of them — an agent
    seeing every colleague's target would be a leak even without the numbers.
    """
    query = visible_goals(db, actor)
    if not include_archived:
        query = query.where(Goal.archived_at.is_(None))

    if mine:
        query = query.where(
            or_(
                Goal.subject_user_id == actor.id,
                Goal.subject_team_id == actor.team_id
                if actor.team_id is not None
                else False,
            )
        )

    org = _org(db, actor)
    rows = db.scalars(query.order_by(Goal.period_anchor.desc(), Goal.id.desc())).all()
    results = [_to_read(db, org, actor, goal, with_trend=trend) for goal in rows]

    if needs_attention:
        # Filtered after building, not in SQL: "behind" depends on today's date
        # against a period resolved in the organization's timezone, which is
        # not a column. The set is small — goals are set by people, not
        # generated — so this costs nothing that matters.
        results = [g for g in results if g.needs_attention]
    return results


class ContributorRead(BaseModel):
    user_id: int
    full_name: str
    value: Decimal
    rank: int


class PastPeriodRead(BaseModel):
    label: str
    value: Decimal
    #: Against the goal's CURRENT target, not one that existed at the time.
    met_target: bool


class GoalDetail(BaseModel):
    """Everything the detail page needs, in one request.

    Composed on the server for the same reason the dashboard is: the client
    assembling this would mean three round trips whose answers have to agree
    about which period they are describing, and a client that asked for the
    contributor breakdown of a goal it may not read would have to handle the
    403 rather than simply never being offered it.
    """

    goal: GoalRead
    #: Who made up a team goal's number. Empty for a personal goal, where the
    #: answer is the one person named on it.
    contributors: list[ContributorRead]
    #: Earlier periods of the same metric and subject, oldest first.
    history: list[PastPeriodRead]


@router.get("/{goal_id}", response_model=GoalDetail)
def read_goal(
    goal_id: int,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> GoalDetail:
    """One goal, in enough depth to act on it.

    The list answers "how far along"; this answers the two questions the list
    physically cannot. **Who** is making up a team's number, and **whether the
    target was ever realistic** — which only earlier periods can say.

    The trend is always included here, unlike on the list, where it is opt-in.
    A detail page is exactly the place the extra query is worth paying for.
    """
    goal = _owned(db, actor, goal_id, allow_archived=True)
    org = _org(db, actor)
    metric = db.get(MetricDefinition, goal.metric_definition_id)

    return GoalDetail(
        goal=_to_read(db, org, actor, goal, with_trend=True),
        contributors=[
            ContributorRead(
                user_id=row.subject_id,
                full_name=row.subject_name,
                value=row.value,
                rank=row.rank,
            )
            for row in goal_service.contributors(db, org, actor, goal, metric)
        ],
        history=[
            PastPeriodRead(label=p.label, value=p.value, met_target=p.met_target)
            for p in goal_service.history(db, org, actor, goal, metric)
        ],
    )


def _new_goal(db: DbSession, actor: UserAccount, payload: GoalCreate) -> tuple[Goal, MetricDefinition, Organization]:
    """A goal from the form, checked — shared by saving and previewing it."""
    metric = db.get(MetricDefinition, payload.metric_id)
    if metric is None or metric.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found.")
    if metric.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{metric.name}' is archived. Restore it before setting goals against it.",
        )

    if payload.recurring and payload.period_type == "custom":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A custom date range cannot repeat — there is no rule for what "
                "the next one would be. Choose a week, month, quarter, or year."
            ),
        )

    org = _org(db, actor)
    canonical_anchor = _check_period(
        org,
        payload.period_type,
        payload.period_anchor,
        payload.period_start,
        payload.period_end,
    )

    stretch = _check_stretch(payload.target_value, payload.stretch, metric.direction)

    goal = Goal(
        stretch_targets=stretch,
        # Sparse on disk: a field nobody chose stays absent, so a later
        # change to the organization's default still reaches this one.
        appearance=(payload.appearance or Appearance()).model_dump(
            exclude_none=True
        ),
        organization_id=actor.organization_id,
        metric_definition_id=metric.id,
        subject_type=payload.subject_type,
        target_value=payload.target_value,
        period_type=payload.period_type,
        # Defaulted here rather than in the schema so "this month" needs no
        # date from the client at all.
        period_anchor=canonical_anchor,
        period_start=payload.period_start if payload.period_type == "custom" else None,
        period_end=payload.period_end if payload.period_type == "custom" else None,
        name=payload.name,
        created_by_user_id=actor.id,
        recurring=payload.recurring,
        recurrence_ends_on=payload.recurrence_ends_on,
    )

    if payload.subject_type == "organization":
        # **Admins only.** A goal on every wall in the building, that everybody
        # can read whatever their scope, is a company-wide statement — the same
        # bar as publishing a board to everyone.
        if actor.org_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Only an admin can set a goal for the whole organization. "
                    "It appears on every wall and everybody can read it."
                ),
            )
        # Both subject columns stay null; the CHECK says so.

    elif payload.subject_type == "user":
        subject = db.get(UserAccount, payload.subject_id)
        if (
            subject is None
            or subject.organization_id != actor.organization_id
            or subject.hidden_at is not None
            or not can_see_user(db, actor, subject.id)
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        goal.subject_user_id = subject.id
    else:
        team = db.get(Team, payload.subject_id)
        if (
            team is None
            or team.organization_id != actor.organization_id
            or team.archived_at is not None
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
        # A manager may set goals for their own team only. Without this they
        # could set targets for a team they have nothing to do with.
        if actor.org_role != "admin" and team.id != actor.team_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only set goals for your own team.",
            )
        goal.subject_team_id = team.id
    return goal, metric, org


@router.post("/draft-slide")
def preview_goal(
    payload: GoalCreate,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> dict | None:
    """The form's goal with its real progress, before it is saved (8.7).

    Added inside a savepoint that is always rolled back, and drawn by the
    TVs' renderer, as the board form's preview is. Null when there is
    nothing to draw yet.
    """
    from app import channels as channel_service

    savepoint = db.begin_nested()
    try:
        goal, _metric, org = _new_goal(db, actor, payload)
        db.add(goal)
        db.flush()
        return channel_service.draw_unsaved(db, org, actor, kind="goal", goal_id=goal.id)
    finally:
        savepoint.rollback()


@router.post("", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
def create_goal(
    payload: GoalCreate,
    request: Request,
    # Managers set goals — that is the job the role exists for. Scope narrows
    # it to their own people below.
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> GoalRead:
    goal, metric, org = _new_goal(db, actor, payload)

    db.add(goal)
    audit.record(
        db,
        actor=actor,
        action="goal.created",
        request=request,
        target=db.get(UserAccount, goal.subject_user_id) if goal.subject_user_id else None,
        metric=metric.key,
        target_value=str(payload.target_value),
        period=payload.period_type,
    )
    db.commit()
    return _to_read(db, org, actor, goal)


@router.patch("/{goal_id}", response_model=GoalRead)
def update_goal(
    goal_id: int,
    payload: GoalUpdate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> GoalRead:
    goal = _owned(db, actor, goal_id)
    org = _org(db, actor)
    fields = payload.model_dump(exclude_unset=True)
    if "appearance" in fields:
        fields["appearance"] = (
            payload.appearance or Appearance()
        ).model_dump(exclude_none=True)

    period_type = fields.get("period_type", goal.period_type)
    canonical_anchor = goal.period_anchor
    if {"period_type", "period_anchor", "period_start", "period_end"} & fields.keys():
        # Changing the KIND of period without naming one means the current one.
        #
        # Otherwise the old anchor is reinterpreted under the new type and the
        # goal silently moves: August → quarter re-anchors to 1 July (Q3's
        # start), and switching back to month then lands on July rather than
        # August. Nobody editing "this month" to "this quarter" and back expects
        # to end up in a different month.
        changing_type = fields.get("period_type", goal.period_type) != goal.period_type
        fallback = (
            datetime.now(UTC).astimezone(ZoneInfo(org.timezone)).date()
            if changing_type
            else goal.period_anchor
        )
        canonical_anchor = _check_period(
            org,
            period_type,
            fields.get("period_anchor", fallback),
            fields.get("period_start", goal.period_start),
            fields.get("period_end", goal.period_end),
        )

    if fields.get("recurring", goal.recurring) and (
        fields.get("period_type", goal.period_type) == "custom"
        or goal.spawned_from_goal_id is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Only an original goal with a repeating period can recur. A "
                "custom range has no next one, and a spawned copy never spawns "
                "further."
            ),
        )

    if "stretch" in fields or "target_value" in fields:
        # Checked against the target they will sit on together: raising the
        # target past a stretch level would leave a "stretch" easier than it.
        metric = db.get(MetricDefinition, goal.metric_definition_id)
        wanted = (
            payload.stretch
            if "stretch" in fields
            else [LevelWrite(value=level.value, label=level.label)
                  for level in goal_tiers.levels_of(goal.stretch_targets)]
        )
        goal.stretch_targets = _check_stretch(
            fields.get("target_value", goal.target_value), wanted or [], metric.direction
        )
        fields.pop("stretch", None)

    changes: dict[str, object] = {}
    if "target_value" in fields and fields["target_value"] != goal.target_value:
        # Moving the target changes what "attained" meant for everyone looking
        # at it, so it is recorded.
        changes["target_value"] = audit.changed(
            str(goal.target_value), str(fields["target_value"])
        )

    for field, value in fields.items():
        setattr(goal, field, value)

    # Keep the period columns consistent with the type, or the CHECK rejects it
    # with a message nobody can act on.
    if goal.period_type == "custom":
        goal.period_anchor = None
    else:
        goal.period_start = goal.period_end = None
        goal.period_anchor = canonical_anchor

    if changes:
        metric = db.get(MetricDefinition, goal.metric_definition_id)
        audit.record(
            db,
            actor=actor,
            action="goal.retargeted",
            request=request,
            target=db.get(UserAccount, goal.subject_user_id) if goal.subject_user_id else None,
            metric=metric.key,
            **changes,
        )

    db.commit()
    return _to_read(db, org, actor, goal)


@router.post("/{goal_id}/archive", response_model=GoalRead)
def archive_goal(
    goal_id: int,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> GoalRead:
    """Retire a goal without erasing that it was set.

    "You hit 4 of 5 goals last quarter" needs the ones that are no longer
    current, so archive is the normal end of a goal's life and delete is for
    mistakes.
    """
    goal = _owned(db, actor, goal_id, allow_archived=True)
    goal.archived_at = datetime.now(UTC)
    db.commit()
    return _to_read(db, _org(db, actor), actor, goal)


@router.post("/{goal_id}/restore", response_model=GoalRead)
def restore_goal(
    goal_id: int,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> GoalRead:
    goal = _owned(db, actor, goal_id, allow_archived=True)
    goal.archived_at = None
    db.commit()
    return _to_read(db, _org(db, actor), actor, goal)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(
    goal_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> None:
    """For a goal created by mistake. Archive is the normal path.

    A hard delete — and the audit row records the metric, subject, and target,
    so it stays reconstructable. Its notifications ("New goal", "achieved") go
    with it (7.5): they link to a goal that is gone.
    """
    from app import cleanup

    goal = _owned(db, actor, goal_id, allow_archived=True)
    cleanup.forget(db, actor.organization_id, *cleanup.about("goal", goal.id))
    metric = db.get(MetricDefinition, goal.metric_definition_id)
    audit.record(
        db,
        actor=actor,
        action="goal.deleted",
        request=request,
        target=db.get(UserAccount, goal.subject_user_id) if goal.subject_user_id else None,
        metric=metric.key if metric else None,
        target_value=str(goal.target_value),
        subject=_subject_name(db, goal),
    )
    db.delete(goal)
    db.commit()


def _owned(
    db: DbSession, actor: UserAccount, goal_id: int, *, allow_archived: bool = False
) -> Goal:
    goal = db.get(Goal, goal_id)
    if goal is None or goal.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found.")
    if goal.archived_at is not None and not allow_archived:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found.")

    # **An organization goal is readable by everybody in it.** That is what it
    # is for: a shared figure each person sees their own slice of is not a
    # shared figure, and the wall beside them would be saying something else.
    if goal.subject_type == "organization":
        return goal

    # Same 404-not-403 rule as everywhere else.
    if goal.subject_user_id is not None:
        if not can_see_user(db, actor, goal.subject_user_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found.")
    elif actor.org_role != "admin" and goal.subject_team_id != actor.team_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found.")

    return goal
