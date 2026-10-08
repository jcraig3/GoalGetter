"""Admin correction — a narrow tool for fixing bad rows.

Not a workflow. **Production metric data comes from integrations, not from
people typing**: hand-keyed numbers are slow, error-prone, and gameable, and a
leaderboard nobody believes is worthless.

This exists because synced data is sometimes wrong, and a number pulled from a
source system that nobody can fix is worse than no number at all — the only
other remedy is fixing the source and waiting for the next sync, which is
impossible if the period is closed.

Four things keep it from becoming a back door:

  * Agents have no write path here at all. It is not a permission toggle; the
    endpoints reject them.
  * A manager may only touch people they can already see.
  * Every write records an audit row in the same transaction.
  * Rows written or edited here are marked, so a hand-keyed number is never
    mistaken for a synced one.
"""

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit, jobs, periods
from app.db import SessionFactory, get_db, get_session_factory
from app.models import MetricDefinition, MetricFact, Organization, Team, UserAccount
from app.scope import EVERYONE, can_see_user, visible_user_ids
from app.sessions import require_role

router = APIRouter(prefix="/metric-facts", tags=["metric-facts"])

# How far ahead of now a fact may be dated.
#
# Not zero: a fact recorded in Sydney is "tomorrow" for a server in UTC, and
# refusing it would make the tool unusable for half the world. Not unbounded
# either — a typo'd year lands far in the future, appears in no period anyone
# looks at, and quietly inflates a yearly total nobody has opened yet.
MAX_FUTURE = timedelta(days=2)

# The oldest a fact may be. Generous, because backfilling a year of history
# before switching on a connector is a legitimate first-day task.
MAX_BACKDATE = timedelta(days=366 * 5)


class MetricFactRead(BaseModel):
    id: int
    metric_definition_id: int
    metric_name: str
    metric_key: str
    unit: str
    decimal_places: int
    unit_label: str | None = None
    subject_user_id: int
    subject_name: str
    team_id: int | None
    team_name: str | None
    # A string, like every other metric value on the wire — see the note in
    # metrics_query.py about IEEE doubles.
    value: Decimal
    occurred_at: datetime
    source_type: str
    # True when a person wrote or edited this row. The UI marks these wherever
    # they appear, so a hand-keyed number is never mistaken for a synced one.
    corrected: bool
    corrected_at: datetime | None


class MetricFactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: int
    subject_user_id: int
    value: Decimal
    occurred_at: datetime

    # `source_type` is deliberately absent. Letting a client set it would allow
    # a hand-typed number to arrive labelled "connector", which defeats the
    # whole point of marking manual entries.


class MetricFactUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Decimal | None = None
    occurred_at: datetime | None = None

    # Neither the metric nor the subject can be changed. Moving a fact to a
    # different person or metric is not a correction — it is a delete and a
    # create, and doing it in one step would leave an audit row that reads
    # "value changed" while something else entirely happened.


def _to_read(fact: MetricFact, metric: MetricDefinition, user: UserAccount, team_name: str | None) -> MetricFactRead:
    return MetricFactRead(
        id=fact.id,
        metric_definition_id=metric.id,
        metric_name=metric.name,
        metric_key=metric.key,
        unit=metric.unit,
        decimal_places=metric.decimal_places,
        unit_label=metric.unit_label,
        subject_user_id=user.id,
        subject_name=user.full_name,
        team_id=fact.subject_team_id,
        team_name=team_name,
        value=fact.value,
        occurred_at=fact.occurred_at,
        source_type=fact.source_type,
        corrected=fact.corrected_at is not None,
        corrected_at=fact.corrected_at,
    )


def _check_when(occurred_at: datetime) -> datetime:
    """Reject dates that cannot be real, and normalise to UTC.

    A naive datetime is treated as UTC rather than rejected: the client sends
    ISO 8601 with an offset, but a hand-built request without one should not
    500 deep inside a comparison.
    """
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)

    now = datetime.now(UTC)
    if occurred_at > now + MAX_FUTURE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That date is in the future. Check the year.",
        )
    if occurred_at < now - MAX_BACKDATE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That date is more than five years ago. Check the year.",
        )
    return occurred_at


def _office_of(db: DbSession, team_id: int | None) -> int | None:
    """The office a team belongs to right now, snapshotted onto the fact.

    Resolved at write time rather than joined at read time — see the comment on
    `MetricFact.subject_office_id`.
    """
    if team_id is None:
        return None
    team = db.get(Team, team_id)
    return team.office_id if team else None


def _metric(db: DbSession, metric_id: int, organization_id: int) -> MetricDefinition:
    metric = db.get(MetricDefinition, metric_id)
    if metric is None or metric.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found.")
    if metric.archived_at is not None:
        # Editing existing history for an archived metric is fine; recording
        # NEW data against one an admin has retired is a mistake worth
        # catching, since it will not appear in any picker afterwards.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{metric.name}' is archived. Restore it before recording new data.",
        )
    if metric.aggregation == "ratio":
        # Worked out from two other metrics, so it has no facts to record.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{metric.name}' is worked out from two other metrics, so it has "
                "no data of its own. Record the metrics it is built from instead."
            ),
        )
    return metric


def _subject(db: DbSession, actor: UserAccount, user_id: int) -> UserAccount:
    user = db.get(UserAccount, user_id)
    if user is None or user.organization_id != actor.organization_id or user.hidden_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    # 404 rather than 403, as everywhere else: for someone outside the actor's
    # scope, confirming the account exists is itself information.
    if not can_see_user(db, actor, user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


def _owned_fact(db: DbSession, actor: UserAccount, fact_id: int) -> MetricFact:
    fact = db.get(MetricFact, fact_id)
    if fact is None or fact.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
    if not can_see_user(db, actor, fact.subject_user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entry not found.")
    return fact


@router.get("", response_model=list[MetricFactRead])
def list_facts(
    metric_id: int | None = None,
    subject_user_id: int | None = None,
    source_type: str | None = None,
    since: date | None = Query(default=None, description="From this day, inclusive"),
    until: date | None = Query(default=None, description="To this day, inclusive"),
    limit: int = Query(default=100, ge=1, le=500),
    # The next page: the newest hundred was all there was to see (review §7).
    offset: int = Query(default=0, ge=0),
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> list[MetricFactRead]:
    """Individual rows, newest first — how you find the one to fix.

    This is the only place raw facts are readable one at a time. Everything
    else aggregates, which is why scope matters just as much here: a single row
    IS one person's number.
    """
    query = (
        select(MetricFact, MetricDefinition, UserAccount, Team.name)
        .join(MetricDefinition, MetricDefinition.id == MetricFact.metric_definition_id)
        .join(UserAccount, UserAccount.id == MetricFact.subject_user_id)
        .outerjoin(Team, Team.id == MetricFact.subject_team_id)
        .where(MetricFact.organization_id == actor.organization_id)
    )

    visible = visible_user_ids(db, actor)
    if visible is not EVERYONE:
        query = query.where(MetricFact.subject_user_id.in_(visible))

    if metric_id is not None:
        query = query.where(MetricFact.metric_definition_id == metric_id)
    if subject_user_id is not None:
        query = query.where(MetricFact.subject_user_id == subject_user_id)
    if source_type is not None:
        query = query.where(MetricFact.source_type == source_type)
    # Days in the organization's zone, like every other boundary here.
    if since is not None or until is not None:
        org = db.get(Organization, actor.organization_id)
        zone = periods.tz(org)
        if since is not None:
            query = query.where(
                MetricFact.occurred_at >= datetime.combine(since, time(0), tzinfo=zone)
            )
        if until is not None:
            query = query.where(
                MetricFact.occurred_at
                < datetime.combine(until + timedelta(days=1), time(0), tzinfo=zone)
            )

    # id as the tiebreaker: a bulk import gives thousands of rows the same
    # occurred_at, and without it their order flips between requests.
    rows = db.execute(
        query.order_by(MetricFact.occurred_at.desc(), MetricFact.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [_to_read(fact, metric, user, team_name) for fact, metric, user, team_name in rows]


@router.post("", response_model=MetricFactRead, status_code=status.HTTP_201_CREATED)
def create_fact(
    payload: MetricFactCreate,
    request: Request,
    background: BackgroundTasks,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
    sessions: SessionFactory = Depends(get_session_factory),
) -> MetricFactRead:
    metric = _metric(db, payload.metric_id, actor.organization_id)
    subject = _subject(db, actor, payload.subject_user_id)
    occurred_at = _check_when(payload.occurred_at)

    fact = MetricFact(
        organization_id=actor.organization_id,
        metric_definition_id=metric.id,
        subject_user_id=subject.id,
        # The team they are on NOW, because the event is being recorded now.
        # Backdating does not reach back for the team they were on then: this
        # tool is for correcting today's data, and guessing at historical
        # membership would invent a fact nobody asserted.
        subject_team_id=subject.team_id,
        subject_office_id=_office_of(db, subject.team_id),
        value=payload.value,
        occurred_at=occurred_at,
        source_type="manual",
        created_by_user_id=actor.id,
        # Marked from the moment it exists. A hand-keyed row is a correction
        # even when it replaces nothing.
        corrected_at=datetime.now(UTC),
        corrected_by_user_id=actor.id,
    )
    db.add(fact)
    audit.record(
        db,
        actor=actor,
        action="metric_fact.created",
        request=request,
        target=subject,
        metric=metric.key,
        value=str(payload.value),
        occurred_at=occurred_at.isoformat(),
    )
    db.commit()
    # A correction can finish a goal or cross a rule's bar, and the wall should
    # say so now rather than at the next hourly pass.
    background.add_task(jobs.announce_now, sessions)

    team = db.get(Team, fact.subject_team_id) if fact.subject_team_id else None
    return _to_read(fact, metric, subject, team.name if team else None)


@router.patch("/{fact_id}", response_model=MetricFactRead)
def update_fact(
    fact_id: int,
    payload: MetricFactUpdate,
    request: Request,
    background: BackgroundTasks,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
    sessions: SessionFactory = Depends(get_session_factory),
) -> MetricFactRead:
    fact = _owned_fact(db, actor, fact_id)
    fields = payload.model_dump(exclude_unset=True)

    changes: dict[str, object] = {}

    if "value" in fields and fields["value"] != fact.value:
        changes["value"] = audit.changed(str(fact.value), str(fields["value"]))
        fact.value = fields["value"]

    if "occurred_at" in fields:
        occurred_at = _check_when(fields["occurred_at"])
        if occurred_at != fact.occurred_at:
            changes["occurred_at"] = audit.changed(
                fact.occurred_at.isoformat(), occurred_at.isoformat()
            )
            fact.occurred_at = occurred_at

    metric = db.get(MetricDefinition, fact.metric_definition_id)
    subject = db.get(UserAccount, fact.subject_user_id)

    if changes:
        # Only on a real change. Marking an unchanged row as corrected would
        # tell the sync path to preserve something nobody edited.
        fact.corrected_at = datetime.now(UTC)
        fact.corrected_by_user_id = actor.id
        audit.record(
            db,
            actor=actor,
            action="metric_fact.edited",
            request=request,
            target=subject,
            metric=metric.key,
            source_type=fact.source_type,
            **changes,
        )

    db.commit()
    background.add_task(jobs.announce_now, sessions)
    team = db.get(Team, fact.subject_team_id) if fact.subject_team_id else None
    return _to_read(fact, metric, subject, team.name if team else None)


@router.delete("/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fact(
    fact_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> None:
    """Remove a row that should not exist — a duplicate, or a mis-sync.

    A hard delete, not a soft one. `metric_fact` is the hot table and every
    aggregation query would otherwise need a `WHERE deleted_at IS NULL` that
    somebody eventually forgets, silently resurrecting deleted numbers.

    Nothing is lost: the audit row records the metric, the person, the value,
    and the date, so the deletion is fully reconstructable.
    """
    fact = _owned_fact(db, actor, fact_id)
    metric = db.get(MetricDefinition, fact.metric_definition_id)
    subject = db.get(UserAccount, fact.subject_user_id)

    audit.record(
        db,
        actor=actor,
        action="metric_fact.deleted",
        request=request,
        target=subject,
        metric=metric.key if metric else None,
        value=str(fact.value),
        occurred_at=fact.occurred_at.isoformat(),
        source_type=fact.source_type,
    )
    # A rule's win announced for this number is about a number that no
    # longer exists (Q2-6).
    from app import cleanup

    cleanup.forget(db, actor.organization_id, *cleanup.about("metric_fact", fact.id))
    db.delete(fact)
    db.commit()
