"""The reporting tab.

**A manager's endpoint, not a second way to read other people's numbers.**
Agents are refused at the edge — not because the figures are secret, but
because every one of these answers is a list of other people to talk to, and
that is a job rather than a view. What a manager sees is still narrowed to
their own team by the same scope rules the goal list obeys, one goal at a
time, so the coarse check here never widens anything.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit, csv_export, report_delivery, reporting as service
from app.db import get_db
from app.models import Competition, Organization, ReportSchedule, UserAccount
from app.sessions import require_role

router = APIRouter(prefix="/reporting", tags=["reporting"])


class GapRead(BaseModel):
    goal_id: int
    goal_name: str
    subject_name: str
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None = None
    current: Decimal
    target: Decimal
    behind_by: float
    days_left: int
    rate_so_far: Decimal | None
    rate_needed: Decimal | None


class OverviewRead(BaseModel):
    total: int
    on_pace: int
    behind: int
    hit: int
    #: Nothing recorded yet, too early to call behind (Q2-10).
    not_started: int = 0
    #: Null when no running goal has anything yet — too early to tell.
    on_pace_percent: float | None
    gaps: list[GapRead]


@router.get("/overview", response_model=OverviewRead)
def overview(
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> OverviewRead:
    """Where every goal this person can see currently stands."""
    org = db.get(Organization, actor.organization_id)
    result = service.overview(db, org, actor)
    return OverviewRead(
        total=result.total,
        on_pace=result.on_pace,
        behind=result.behind,
        hit=result.hit,
        not_started=result.not_started,
        on_pace_percent=result.on_pace_percent,
        gaps=[GapRead(**vars(gap)) for gap in result.gaps],
    )


class RunRead(BaseModel):
    competition_id: int
    name: str
    ended_on: date
    winner_name: str
    value: Decimal


class CompetitionReportRead(BaseModel):
    competition_id: int
    name: str
    state: str
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None = None
    entity_type: str
    leader_name: str | None
    leader_value: Decimal | None
    elapsed_percent: float
    predicted: Decimal | None
    #: Too little of the window gone to forecast (P3-11).
    too_early: bool = False
    runs: list[RunRead]
    all_time_high: Decimal | None
    all_time_high_name: str | None
    first: Decimal | None
    previous: Decimal | None
    #: Computed on the dataclass rather than here, so the rule about which
    #: number a comparison is made from lives in one place and is tested there.
    basis: Decimal | None
    vs_first: Decimal | None
    vs_previous: Decimal | None
    vs_high: Decimal | None


@router.get("/competitions/{competition_id}", response_model=CompetitionReportRead)
def competition_report(
    competition_id: int,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> CompetitionReportRead:
    """One contest, read against the settled contests before it."""
    competition = db.get(Competition, competition_id)
    if competition is None or competition.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found."
        )

    org = db.get(Organization, actor.organization_id)
    result = service.competition_report(db, org, competition)
    return CompetitionReportRead(
        **{k: v for k, v in vars(result).items() if k != "runs"},
        runs=[RunRead(**vars(run)) for run in result.runs],
        basis=result.basis,
        vs_first=result.vs_first,
        vs_previous=result.vs_previous,
        vs_high=result.vs_high,
    )


class SeasonRead(BaseModel):
    label: str
    value: Decimal
    met_target: bool
    #: False before the series began, with nothing recorded (7.6).
    counted: bool = True


class RecordRead(BaseModel):
    goal_id: int
    goal_name: str
    subject_name: str
    metric_name: str
    unit: str
    decimal_places: int
    unit_label: str | None = None
    target: Decimal
    seasons: list[SeasonRead]
    considered: int
    hit: int
    hit_rate: float
    current_streak: int
    best_streak: int


def _record(record: service.Record) -> RecordRead:
    return RecordRead(
        **{k: v for k, v in vars(record).items() if k != "seasons"},
        seasons=[SeasonRead(**vars(season)) for season in record.seasons],
        considered=record.considered,
        hit=record.hit,
        hit_rate=record.hit_rate,
        current_streak=record.current_streak,
        best_streak=record.best_streak,
    )


@router.get("/records", response_model=list[RecordRead])
def records(
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> list[RecordRead]:
    """Every visible goal's track record over the periods before this one."""
    org = db.get(Organization, actor.organization_id)
    return [_record(record) for record in service.records(db, org, actor)]


@router.get("/records.csv")
def records_csv(
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> StreamingResponse:
    """The same track records as a spreadsheet.

    **One row per goal, with a column per period**, rather than a row per
    period. The question this file gets opened to answer is "who keeps
    missing", and that is a sort on one column — a long-format export would
    make somebody build a pivot table before they could see it.

    Same scope as the page: a different rendering of what they can already
    read, never a way around who may see it.
    """
    org = db.get(Organization, actor.organization_id)
    rows = service.records(db, org, actor)

    # Every goal on the same metric and period shape shares its labels, but
    # two metrics need not — so the widest row decides the header, and a goal
    # with fewer periods leaves the trailing columns empty.
    width = max((len(record.seasons) for record in rows), default=0)
    labels: list[str] = []
    for record in rows:
        if len(record.seasons) == width:
            labels = [season.label for season in record.seasons]
            break

    header = [
        "Goal",
        "Who",
        "Metric",
        "Unit",
        "Target",
        "Periods",
        "Hit",
        "Hit rate %",
        "Current streak",
        "Best streak",
        *labels,
    ]

    def body():
        for record in rows:
            # Blank where a period does not count (7.6): before the goal,
            # with nothing recorded — not a zero, which would read as a miss.
            values = [season.value if season.counted else "" for season in record.seasons]
            yield [
                record.goal_name,
                record.subject_name,
                record.metric_name,
                record.unit,
                record.target,
                record.considered,
                record.hit,
                record.hit_rate,
                record.current_streak,
                record.best_streak,
                *values,
                *[""] * (width - len(values)),
            ]

    name = csv_export.filename(org.name, "track-record")
    return StreamingResponse(
        csv_export.rows_to_csv(header, body()),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ── Scheduled delivery ──────────────────────────────────────────────────────


class Recipient(BaseModel):
    id: int
    name: str
    email: str


class ScheduleRead(BaseModel):
    id: int
    name: str
    cadence: str
    weekday: int | None
    hour: int
    recipients: list[Recipient]
    enabled: bool
    last_sent_at: datetime | None
    last_error: str | None


class ScheduleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="Coaching digest", min_length=1, max_length=80)
    cadence: Literal["weekdays", "weekly", "monthly"] = "weekly"
    #: For weekly: 0 is Monday.
    weekday: int | None = Field(default=0, ge=0, le=6)
    hour: int = Field(default=8, ge=0, le=23)
    recipient_ids: list[int] = Field(default_factory=list, max_length=50)
    enabled: bool = True


def _schedule_read(db: DbSession, row: ReportSchedule) -> ScheduleRead:
    people = (
        db.scalars(select(UserAccount).where(UserAccount.id.in_(row.recipient_ids or []))).all()
        if row.recipient_ids
        else []
    )
    return ScheduleRead(
        id=row.id, name=row.name, cadence=row.cadence,
        weekday=row.weekday if row.cadence == "weekly" else None, hour=row.hour,
        recipients=[Recipient(id=p.id, name=p.full_name, email=p.email) for p in people],
        enabled=row.enabled, last_sent_at=row.last_sent_at, last_error=row.last_error,
    )


def _check_recipients(db: DbSession, actor: UserAccount, ids: list[int]) -> list[int]:
    """Admins and managers of this organization, and for a manager only
    themselves. The digest is worked out in each recipient's own scope, but
    who receives one is an admin's decision."""
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choose who receives it.")
    if actor.org_role != "admin" and ids != [actor.id]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A manager can schedule the digest for themselves. Ask an admin to add others.",
        )
    people = db.scalars(select(UserAccount).where(UserAccount.id.in_(ids))).all()
    fine = {
        p.id for p in people
        if p.organization_id == actor.organization_id
        and p.org_role in report_delivery.RECIPIENT_ROLES
        and p.hidden_at is None
    }
    if set(ids) - fine:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Only admins and managers can receive the coaching digest. "
                "It is a list of people to talk to."
            ),
        )
    return ids


def _schedule_owned(db: DbSession, actor: UserAccount, schedule_id: int) -> ReportSchedule:
    row = db.get(ReportSchedule, schedule_id)
    if (
        row is None
        or row.organization_id != actor.organization_id
        or (actor.org_role != "admin" and row.created_by_user_id != actor.id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return row


def _apply(db: DbSession, actor: UserAccount, row: ReportSchedule, payload: ScheduleWrite) -> None:
    row.recipient_ids = _check_recipients(db, actor, payload.recipient_ids)
    row.name = payload.name.strip()
    row.cadence = payload.cadence
    row.weekday = payload.weekday if payload.cadence == "weekly" else None
    row.hour = payload.hour
    row.enabled = payload.enabled
    # **From the next slot**, not the one that just passed: a schedule saved
    # at 10am for 8am must not fire the moment it is saved. "Send a test" is
    # how to see it now.
    org = db.get(Organization, actor.organization_id)
    row.last_slot_at = report_delivery.due_slot(org, row, datetime.now(UTC))


@router.get("/schedules", response_model=list[ScheduleRead])
def list_schedules(
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> list[ScheduleRead]:
    query = select(ReportSchedule).where(ReportSchedule.organization_id == actor.organization_id)
    if actor.org_role != "admin":
        query = query.where(ReportSchedule.created_by_user_id == actor.id)
    return [_schedule_read(db, row) for row in db.scalars(query.order_by(ReportSchedule.id)).all()]


class MailReady(BaseModel):
    #: Whether a digest could go out now, and as whom.
    ready: bool
    sending_from: str | None = None


@router.get("/mail", response_model=MailReady)
def mail_ready(
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> MailReady:
    """Whether email is set up, for the Email tab to say so (8.3).

    In the order `mail.send` tries them: the Microsoft 365 connection, then
    SMTP. The tab used to say "It needs email set up" whether it was or not.
    """
    from app import mail, mail_graph

    connection = mail_graph.configured(db, actor.organization_id)
    if connection is not None:
        return MailReady(ready=True, sending_from=mail_graph.sender_for(connection) or None)
    config = mail.config_for(db, actor.organization_id)
    if mail.usable(config):
        return MailReady(ready=True, sending_from=config.from_address)
    return MailReady(ready=False)


@router.get("/recipients", response_model=list[Recipient])
def list_recipients(
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> list[Recipient]:
    """Who a schedule can go to: admins and managers, or a manager themselves."""
    if actor.org_role != "admin":
        return [Recipient(id=actor.id, name=actor.full_name, email=actor.email)]
    people = db.scalars(
        select(UserAccount)
        .where(
            UserAccount.organization_id == actor.organization_id,
            UserAccount.org_role.in_(report_delivery.RECIPIENT_ROLES),
            UserAccount.hidden_at.is_(None),
        )
        .order_by(UserAccount.full_name)
    ).all()
    return [Recipient(id=p.id, name=p.full_name, email=p.email) for p in people]


@router.post("/schedules", response_model=ScheduleRead, status_code=status.HTTP_201_CREATED)
def create_schedule(
    payload: ScheduleWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> ScheduleRead:
    """Email the coaching digest on a schedule, starting from the next slot."""
    row = ReportSchedule(organization_id=actor.organization_id, created_by_user_id=actor.id)
    _apply(db, actor, row, payload)
    db.add(row)
    audit.record(db, actor=actor, action="report_schedule.created", request=request, name=row.name)
    db.commit()
    return _schedule_read(db, row)


@router.patch("/schedules/{schedule_id}", response_model=ScheduleRead)
def update_schedule(
    schedule_id: int,
    payload: ScheduleWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> ScheduleRead:
    row = _schedule_owned(db, actor, schedule_id)
    _apply(db, actor, row, payload)
    audit.record(db, actor=actor, action="report_schedule.updated", request=request, name=row.name)
    db.commit()
    return _schedule_read(db, row)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> None:
    row = _schedule_owned(db, actor, schedule_id)
    audit.record(db, actor=actor, action="report_schedule.deleted", request=request, name=row.name)
    db.delete(row)
    db.commit()


class SendRead(BaseModel):
    ok: bool
    error: str | None = None


@router.post("/schedules/{schedule_id}/send", response_model=SendRead)
def send_schedule_now(
    schedule_id: int,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> SendRead:
    """Send the digest to yourself now, as you would receive it. Changes
    nothing about when it next sends."""
    row = _schedule_owned(db, actor, schedule_id)
    org = db.get(Organization, actor.organization_id)
    error = report_delivery.send_now(db, org, row, actor)
    return SendRead(ok=error is None, error=error)

