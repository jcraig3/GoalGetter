"""What has this subject actually done, before you pick a target.

A target set with no reference to history is a guess, and a guess is either
trivially met or plainly impossible — both of which stop anyone taking the
number seriously. This answers "what has been normal here?" so the person
setting the goal is adjusting a real figure rather than inventing one.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session as DbSession

from app import aggregate, periods, scope
from app.db import get_db
from app.models import MetricDefinition, Organization, Team, UserAccount
from app.models.goal import SUBJECT_TYPES
from app.scope import can_see_user
from app.sessions import require_role

router = APIRouter(prefix="/goals", tags=["goals"])

# How far back to look. Enough to show a trend and average out one bad month,
# short enough that a reorganisation last year does not drag the figure.
LOOKBACK = 6

# Periods a preview can be built for. `custom` is absent because there is no
# "previous custom range" to walk back through.
PREVIEWABLE = tuple(p for p in periods.PERIOD_TYPES if p != "custom")


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: int
    subject_type: str
    #: Absent for an organization goal, which is about everyone.
    subject_id: int | None = None
    period_type: str = "month"

    @field_validator("subject_type")
    @classmethod
    def _subject(cls, value: str) -> str:
        if value not in SUBJECT_TYPES:
            raise ValueError(f"subject_type must be one of: {', '.join(SUBJECT_TYPES)}")
        return value

    @field_validator("period_type")
    @classmethod
    def _period(cls, value: str) -> str:
        if value not in PREVIEWABLE:
            raise ValueError(
                "A custom date range has no history to compare against. "
                f"Expected one of: {', '.join(PREVIEWABLE)}"
            )
        return value


class PastPeriod(BaseModel):
    label: str
    value: Decimal
    start: date


class Preview(BaseModel):
    subject_name: str
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None = None
    direction: str

    #: Oldest first, so a chart reads left to right without reversing it.
    history: list[PastPeriod] = Field(default_factory=list)
    average: Decimal | None = None
    best: Decimal | None = None
    #: A starting point, not a recommendation — see `_suggest`.
    suggested_target: Decimal | None = None


def _round_step(value: Decimal) -> Decimal:
    """How coarsely to round a suggestion of roughly this size.

    Scaled by magnitude rather than by unit. An earlier version kept full
    precision for currency, on the reasoning that money is exact — which
    produced a suggested revenue target of $216,026.54. That is precisely the
    "reads as a calculation" problem the rounding exists to avoid; the unit was
    never what mattered.
    """
    absolute = abs(value)
    if absolute < 10:
        return Decimal("0.5")
    if absolute < 200:
        return Decimal(10)
    if absolute < 2_000:
        return Decimal(50)
    if absolute < 20_000:
        return Decimal(500)
    if absolute < 200_000:
        return Decimal(5_000)
    return Decimal(10_000)


def _suggest(average: Decimal, direction: str, decimals: int) -> Decimal:
    """A target a little beyond the recent average.

    Ten percent, which is a convention rather than a finding — a nudge past
    "what already happens", which is the failure mode of a target set to the
    average itself. The person setting the goal sees the history it came from
    and is expected to overrule it.

    Rounded, because "231.4" reads as a calculation and "240" reads as a
    decision. Nobody rallies around 231.4, and a target is a thing people say
    out loud to each other.
    """
    factor = Decimal("0.9") if direction == "lower_is_better" else Decimal("1.1")
    raw = average * factor

    step = _round_step(raw)
    rounded = (raw / step).to_integral_value(rounding="ROUND_HALF_UP") * step

    # Never zero, and never below the smallest step — a suggestion of 0 would
    # be rejected by the target > 0 constraint the moment it was accepted.
    rounded = max(rounded, step)
    return rounded.quantize(Decimal(1).scaleb(-decimals)) if decimals else rounded


@router.post("/preview", response_model=Preview)
def preview(
    payload: PreviewRequest,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> Preview:
    """Recent complete periods for one subject and metric."""
    metric = db.get(MetricDefinition, payload.metric_id)
    if metric is None or metric.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found.")

    org = db.get(Organization, actor.organization_id)

    if payload.subject_type == "organization":
        # **Admins only, matching the goal it previews.** Showing a manager the
        # company's history for a goal they cannot then set would be an answer
        # to a question they are not allowed to ask.
        if actor.org_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an admin can set a goal for the whole organization.",
            )
        subject_name = org.name

    elif payload.subject_type == "user":
        subject = db.get(UserAccount, payload.subject_id)
        if (
            subject is None
            or subject.organization_id != actor.organization_id
            or not can_see_user(db, actor, subject.id)
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        subject_name = subject.full_name
    else:
        team = db.get(Team, payload.subject_id)
        if team is None or team.organization_id != actor.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
        if actor.org_role != "admin" and team.id != actor.team_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
        subject_name = team.name

    result = Preview(
        subject_name=subject_name,
        metric_name=metric.name,
        unit=metric.unit,
        decimal_places=metric.decimal_places,
        unit_label=metric.unit_label,
        direction=metric.direction,
    )

    # Start from the period BEFORE the current one.
    #
    # The current period is partway through, so including it would drag the
    # average down by however much of it is left — and suggest a target below
    # what the person actually achieves. A part-finished month is not a data
    # point about monthly performance.
    # The organization's today — see `periods.today`.
    period = periods.resolve(org, payload.period_type, periods.today(org))

    history: list[PastPeriod] = []
    for _ in range(LOOKBACK):
        period = periods.previous(org, period)
        if payload.subject_type == "organization":
            # One figure across everyone, the same way the goal itself is
            # computed — a history that did not match would argue for a target
            # the goal could never report against.
            value = aggregate.total(
                db, org.id, actor, metric, period, visible=scope.EVERYONE
            )
        else:
            rows = aggregate.run(
                db,
                org.id,
                actor,
                metric,
                period,
                group_by=payload.subject_type,
                team_id=payload.subject_id if payload.subject_type == "team" else None,
            )
            if payload.subject_type == "user":
                rows = [row for row in rows if row.subject_id == payload.subject_id]
            value = rows[0].value if rows else Decimal(0)

        history.append(
            PastPeriod(
                label=period.label,
                value=value,
                start=period.start.date(),
            )
        )

    # Oldest first for display.
    result.history = list(reversed(history))

    # Periods with nothing recorded are excluded from the average rather than
    # counted as zero. Someone who joined three months ago has three empty
    # periods before that, and averaging those in halves their target for a
    # reason that has nothing to do with their performance.
    measured = [entry.value for entry in history if entry.value != 0]
    if measured:
        result.average = sum(measured) / len(measured)
        result.best = (
            min(measured) if metric.direction == "lower_is_better" else max(measured)
        )
        result.suggested_target = _suggest(
            result.average, metric.direction, metric.decimal_places
        )

    return result
