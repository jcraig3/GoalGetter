from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import aggregate, periods
from app.db import get_db
from app.models import MetricDefinition, Organization, Team, UserAccount
from app.sessions import current_user

router = APIRouter(prefix="/metrics", tags=["metrics"])


class PeriodRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "month"
    # Any date inside the wanted period — "the month containing the 15th", not
    # "the month starting on the 15th". Defaults to today in the org timezone.
    anchor: date | None = None
    start: date | None = None
    end: date | None = None

    @field_validator("type")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in periods.PERIOD_TYPES:
            raise ValueError(
                f"Unknown period type. Expected one of: {', '.join(periods.PERIOD_TYPES)}"
            )
        return value


class MetricQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: int
    group_by: str = "user"
    period: PeriodRequest = Field(default_factory=PeriodRequest)
    team_id: int | None = None
    dense_rank: bool = False
    # Capped in the schema so "?limit=1000000" is not a way to make the API
    # materialise every row it holds.
    limit: int | None = Field(default=None, ge=1, le=500)

    @field_validator("group_by")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in aggregate.GROUP_BY:
            raise ValueError(f"group_by must be one of: {', '.join(aggregate.GROUP_BY)}")
        return value


class PeriodRead(BaseModel):
    type: str
    label: str
    start: datetime
    end: datetime


class MetricSummary(BaseModel):
    id: int
    key: str
    name: str
    unit: str
    aggregation: str
    direction: str
    decimal_places: int
    unit_label: str | None = None


class ResultRow(BaseModel):
    rank: int
    subject_id: int
    subject_name: str
    team_id: int | None
    team_name: str | None
    # Serialised as a JSON string, not a number. JavaScript numbers are IEEE
    # doubles, so a large currency total loses precision the moment it is
    # parsed — the exactness NUMERIC(18,4) was chosen for would be thrown away
    # in the last step. The client formats the string.
    value: Decimal


class MetricQueryResult(BaseModel):
    metric: MetricSummary
    period: PeriodRead
    group_by: str
    rows: list[ResultRow]
    total: Decimal


@router.post("/query", response_model=MetricQueryResult)
def query_metrics(
    payload: MetricQuery,
    # Every role may call this. Scope decides what comes back, not whether the
    # call is allowed: an agent gets their own numbers, a manager their team's.
    actor: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> MetricQueryResult:
    """The single aggregation endpoint.

    Leaderboards, dashboard tiles, goal progress, and competition standings are
    all this call with different arguments. One well-tested path instead of
    four that drift apart.
    """
    metric = db.get(MetricDefinition, payload.metric_id)
    if metric is None or metric.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found."
        )

    if payload.team_id is not None:
        team = db.get(Team, payload.team_id)
        if team is None or team.organization_id != actor.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
            )

    org = db.get(Organization, actor.organization_id)

    try:
        period = periods.resolve(
            org,
            payload.period.type,
            payload.period.anchor,
            custom_start=payload.period.start,
            custom_end=payload.period.end,
        )
    except ValueError as exc:
        # The message is ours — "a custom period needs both a start and an end"
        # — not an internal traceback. Safe to surface.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None

    rows = aggregate.run(
        db,
        actor.organization_id,
        actor,
        metric,
        period,
        group_by=payload.group_by,
        team_id=payload.team_id,
        dense_rank=payload.dense_rank,
        limit=payload.limit,
    )

    return MetricQueryResult(
        metric=MetricSummary(
            id=metric.id,
            key=metric.key,
            name=metric.name,
            unit=metric.unit,
            aggregation=metric.aggregation,
            direction=metric.direction,
            decimal_places=metric.decimal_places,
            unit_label=metric.unit_label,
        ),
        period=PeriodRead(
            type=period.type, label=period.label, start=period.start, end=period.end
        ),
        group_by=payload.group_by,
        rows=[
            ResultRow(
                rank=row.rank,
                subject_id=row.subject_id,
                subject_name=row.subject_name,
                team_id=row.team_id,
                team_name=row.team_name,
                value=row.value,
            )
            for row in rows
        ],
        # Deliberately NOT the sum of `rows`: `limit` truncates the rows, and
        # for avg/max/min the two are different questions anyway.
        total=aggregate.total(
            db,
            actor.organization_id,
            actor,
            metric,
            period,
            group_by=payload.group_by,
            team_id=payload.team_id,
        ),
    )
