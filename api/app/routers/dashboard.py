from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app import dashboard as service, dismissals, setup_steps, shared_notices
from app.db import get_db
from app.models import Organization, UserAccount
from app.sessions import current_user
from app.trend import Trend, TrendPoint

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class PlacementRead(BaseModel):
    board_id: int
    board_name: str
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None = None
    period_label: str
    rank: int
    total_entrants: int
    value: Decimal
    movement: int | None
    trend: Trend


def _placement(placement: service.Placement) -> "PlacementRead":
    """Fold the three flat trend fields into the shared `Trend` shape.

    They are separate on the dataclass because a dataclass is what the service
    layer speaks, and nested on the wire because that is what the sparkline
    component takes — the same object a goal hands it, so one component serves
    both without a branch.
    """
    fields = {k: v for k, v in vars(placement).items() if not k.startswith("trend")}
    return PlacementRead(
        **fields,
        trend=Trend(
            unit=placement.trend_unit,
            cumulative=placement.trend_cumulative,
            points=[TrendPoint(at=p.bucket, value=p.value) for p in placement.trend],
        ),
    )


class AttentionRead(BaseModel):
    #: A stable identifier the client styles and links from, separate from the
    #: sentence, so wording can change without breaking a lookup.
    kind: str
    message: str
    count: int
    link: str


def _attention(a: service.Attention) -> AttentionRead:
    return AttentionRead(kind=a.kind, message=a.message, count=a.count, link=a.link)


class AttentionKind(BaseModel):
    kind: str


class HealthRead(BaseModel):
    #: Each source and its newest row (P3-3).
    sources: list[dict] = []
    last_fact_at: datetime | None
    facts_last_7_days: int
    active_people: int
    people_without_a_team: int
    metrics_without_data: int
    displays_offline: int
    sources_failing: int
    sources_overdue: int
    source_error: str | None


class SetupStepRead(BaseModel):
    key: str
    label: str
    done: bool
    link: str
    detail: str


class DashboardRead(BaseModel):
    role: str
    placements: list[PlacementRead]
    attention: list[AttentionRead]
    #: Banners this person put away (12.2), until they change or tomorrow.
    #: Sent so Home can offer them back rather than lose them.
    attention_dismissed: list[AttentionRead] = []
    #: Admin only. Null for everyone else, rather than an empty object — there
    #: is a difference between "nothing wrong" and "not your concern", and the
    #: client renders the panel only when it is the former.
    health: HealthRead | None
    #: The first-wall checklist, for an admin; null for anybody else, who has
    #: no step on it they could take. See `app/setup_steps.py`.
    setup: list[SetupStepRead] | None = None


@router.get("", response_model=DashboardRead)
def read_dashboard(
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> DashboardRead:
    """One request for the whole home page.

    Composed server-side rather than by the client making four calls: what
    belongs on the page depends on the role, and letting the client decide
    would mean it asking for things it is not entitled to and handling the 403
    — which is a worse contract than the server simply answering the question
    "what should this person see first".
    """
    org = db.get(Organization, actor.organization_id)
    summary = service.build(db, org, actor)
    shown, away = dismissals.split(
        db, org, actor, "home", summary.attention, service.Attention.mark
    )

    return DashboardRead(
        role=actor.org_role,
        placements=[_placement(p) for p in summary.placements],
        attention=[_attention(a) for a in shown],
        attention_dismissed=[_attention(a) for a in away],
        health=HealthRead(**vars(summary.health)) if summary.health else None,
        setup=(
            [SetupStepRead(**vars(s)) for s in setup_steps.steps(db, org)]
            if actor.org_role == "admin"
            else None
        ),
    )


@router.post("/attention/dismiss", status_code=status.HTTP_204_NO_CONTENT)
def dismiss_attention(
    payload: AttentionKind,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> None:
    """Put a Home banner away as it is now, until it changes or tomorrow
    (12.2). Worked out again here, so what is remembered is what is true."""
    org = db.get(Organization, actor.organization_id)
    item = next((a for a in service.attention(db, org, actor) if a.kind == payload.kind), None)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That is already gone.")
    dismissals.dismiss(db, org, actor, "home", item.mark())
    # And the Inbox's items about the same sources (P4-9).
    shared_notices.put_away_together(db, org, actor, "home", item.kind)
    db.commit()


@router.post("/attention/restore", status_code=status.HTTP_204_NO_CONTENT)
def restore_attention(
    payload: AttentionKind,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> None:
    """Bring a put-away banner back now."""
    dismissals.restore(db, actor, "home", payload.kind)
    shared_notices.bring_back_together(db, actor, "home", payload.kind)
    db.commit()


class TeamGoalRead(BaseModel):
    goal_id: int
    target: Decimal
    percent: float
    expected_percent: float | None
    status: str


class MemberRead(BaseModel):
    user_id: int
    name: str
    photo_digest: str | None
    value: Decimal
    rank: int
    goal: TeamGoalRead | None
    quiet_days: int | None
    is_me: bool


class NoteRead(BaseModel):
    user_id: int
    name: str
    kind: str
    value: Decimal | None
    target: Decimal | None
    expected: Decimal | None
    days: int | None


class MetricChoice(BaseModel):
    id: int
    name: str
    #: Facts the team recorded against it lately — the busiest is the default.
    recorded: int


class TeamHomeRead(BaseModel):
    team_id: int
    team_name: str
    metrics: list[MetricChoice]
    metric_id: int | None
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None
    direction: str
    period_type: str
    period_label: str
    members: list[MemberRead]
    nudges: list[NoteRead]
    shout_outs: list[NoteRead]


@router.get("/team", response_model=TeamHomeRead | None)
def read_team(
    metric_id: int | None = None,
    period_type: str = "month",
    previous: bool = False,
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> TeamHomeRead | None:
    """A manager's own team: the board, the goals, who needs a word (6.13).

    Null for anybody with no team to manage — an agent, or an admin who sits
    on none — rather than a 404: the home page asks on everybody's behalf and
    "nothing to show" is not an error.
    """
    from app import team_home

    if period_type not in team_home.TEAM_PERIODS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"period_type must be one of: {', '.join(team_home.TEAM_PERIODS)}",
        )
    team = team_home.team_of(db, actor)
    if team is None:
        return None
    org = db.get(Organization, actor.organization_id)
    home = team_home.build(
        db, org, actor, team, metric_id=metric_id, period_type=period_type, previous=previous
    )
    return TeamHomeRead(
        **{k: v for k, v in vars(home).items() if k not in ("members", "nudges", "shout_outs")},
        members=[
            MemberRead(**{**vars(m), "goal": TeamGoalRead(**vars(m.goal)) if m.goal else None})
            for m in home.members
        ],
        nudges=[NoteRead(**vars(n)) for n in home.nudges],
        shout_outs=[NoteRead(**vars(n)) for n in home.shout_outs],
    )
