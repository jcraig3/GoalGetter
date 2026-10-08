import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app import audit, derived, units
from app.db import get_db
from app.metrics_seed import seed_default_metrics
from app.models import MetricDefinition, MetricFact, UserAccount
# Imported rather than redeclared, so the API and the database CHECK
# constraints can never disagree about what a valid value is.
from app.models.metric_definition import AGGREGATIONS, DIRECTIONS, UNITS
from app.sessions import current_user, require_role
from app.validation import Name

router = APIRouter(prefix="/metrics", tags=["metrics"])

# Lowercase, digits, underscores. Matches how connectors and CSV headers will
# address a metric, and rules out anything needing quoting or escaping.
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class MetricRead(BaseModel):
    id: int
    key: str
    name: str
    description: str | None
    unit: str
    aggregation: str
    direction: str
    decimal_places: int
    #: What a count is a count of: "deals". See `app/units.py`.
    unit_label: str | None = None
    archived: bool
    #: For a derived metric (`aggregation = ratio`): what is divided by what.
    numerator_metric_id: int | None = None
    denominator_metric_id: int | None = None
    #: Admins only, both of these — the list is readable by everyone, and what
    #: an organization has plugged in is not everyone's business.
    #:
    #: The sources feeding it, by name.
    sources: list[str] = []
    #: A count whose numbers look like money (QA-39): "Closed Deals" was
    #: summing deal amounts, because its mapping read the amount column.
    looks_like_amounts: bool = False


#: A count's typical value above which it probably is not counting anything.
AMOUNT_HINT = 500


class MetricCreate(BaseModel):
    key: str = Field(min_length=2, max_length=64)
    name: Name(120)
    description: str | None = Field(default=None, max_length=500)
    unit: str = "count"
    aggregation: str = "sum"
    direction: str = "higher_is_better"
    decimal_places: int = Field(default=0, ge=0, le=4)
    unit_label: str | None = Field(default=None, max_length=units.MAX_LABEL)
    #: For `aggregation = ratio`: what is divided by what.
    numerator_metric_id: int | None = None
    denominator_metric_id: int | None = None

    @field_validator("key")
    @classmethod
    def _valid_key(cls, value: str) -> str:
        # Normalised before validation so "Calls Made" fails loudly rather than
        # becoming a second metric that only differs by case.
        if not KEY_PATTERN.match(value):
            raise ValueError(
                "Key must be lowercase letters, digits, and underscores, "
                "starting with a letter — for example: calls_made"
            )
        return value

    @field_validator("unit")
    @classmethod
    def _valid_unit(cls, value: str) -> str:
        return _one_of(value, UNITS, "unit")

    @field_validator("unit_label")
    @classmethod
    def _clean_label(cls, value: str | None) -> str | None:
        return units.clean(value)

    @field_validator("aggregation")
    @classmethod
    def _valid_aggregation(cls, value: str) -> str:
        return _one_of(value, AGGREGATIONS, "aggregation")

    @field_validator("direction")
    @classmethod
    def _valid_direction(cls, value: str) -> str:
        return _one_of(value, DIRECTIONS, "direction")


class MetricUpdate(BaseModel):
    """Everything editable except `key`.

    `key` is absent on purpose. Connectors, saved import mappings, and goals all
    reference it; renaming it would break each of them silently, and the visible
    label is `name`, which is freely editable.
    """

    # Rejects unknown fields instead of ignoring them. Pydantic's default would
    # accept {"key": "renamed"} and quietly drop it, so a client would believe
    # it had renamed the key and get a 200 saying so. A loud 422 is the honest
    # answer to "you cannot change that".
    model_config = ConfigDict(extra="forbid")

    name: Name(120) | None = None
    description: str | None = Field(default=None, max_length=500)
    unit: str | None = None
    aggregation: str | None = None
    direction: str | None = None
    decimal_places: int | None = Field(default=None, ge=0, le=4)
    unit_label: str | None = Field(default=None, max_length=units.MAX_LABEL)
    numerator_metric_id: int | None = None
    denominator_metric_id: int | None = None

    @field_validator("unit")
    @classmethod
    def _valid_unit(cls, value: str | None) -> str | None:
        return value if value is None else _one_of(value, UNITS, "unit")

    @field_validator("unit_label")
    @classmethod
    def _clean_label(cls, value: str | None) -> str | None:
        return units.clean(value)

    @field_validator("aggregation")
    @classmethod
    def _valid_aggregation(cls, value: str | None) -> str | None:
        return value if value is None else _one_of(value, AGGREGATIONS, "aggregation")

    @field_validator("direction")
    @classmethod
    def _valid_direction(cls, value: str | None) -> str | None:
        return value if value is None else _one_of(value, DIRECTIONS, "direction")


def _one_of(value: str, allowed: tuple[str, ...], label: str) -> str:
    if value not in allowed:
        raise ValueError(f"Unknown {label}. Expected one of: {', '.join(allowed)}")
    return value


def _to_read(metric: MetricDefinition) -> MetricRead:
    return MetricRead(
        id=metric.id,
        key=metric.key,
        name=metric.name,
        description=metric.description,
        unit=metric.unit,
        aggregation=metric.aggregation,
        direction=metric.direction,
        decimal_places=metric.decimal_places,
        unit_label=metric.unit_label,
        archived=metric.archived_at is not None,
        numerator_metric_id=metric.numerator_metric_id,
        denominator_metric_id=metric.denominator_metric_id,
    )


def _check_parts(
    db: DbSession,
    organization_id: int,
    aggregation: str,
    numerator_id: int | None,
    denominator_id: int | None,
    *,
    itself: int | None = None,
) -> tuple[int | None, int | None]:
    """The two metrics a ratio divides, checked — or (None, None) for anything
    that is not a ratio. Refusals say what to fix, in words."""
    if aggregation != "ratio":
        return None, None
    if numerator_id is None or denominator_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A ratio needs two metrics: what is divided, and what it is divided by.",
        )
    if numerator_id == denominator_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A metric divided by itself is always 1. Choose two different metrics.",
        )
    for part_id in (numerator_id, denominator_id):
        part = db.get(MetricDefinition, part_id)
        if part is None or part.organization_id != organization_id or part.id == itself:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found.")
        if part.aggregation == "ratio":
            # One level only: a ratio of ratios is a number nobody can check
            # by looking at the two things it came from.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{part.name}' is itself worked out from two metrics. Build the ratio from recorded metrics.",
            )
    return numerator_id, denominator_id


@router.get("", response_model=list[MetricRead])
def list_metrics(
    include_archived: bool = Query(default=False),
    # Readable by everyone: an agent's own dashboard needs to know that "Calls
    # Made" is a count and "Revenue Closed" is currency with 2 decimals. This
    # returns what is measured, never anyone's numbers.
    user: UserAccount = Depends(current_user),
    db: DbSession = Depends(get_db),
) -> list[MetricRead]:
    query = select(MetricDefinition).where(
        MetricDefinition.organization_id == user.organization_id
    )
    if not include_archived:
        query = query.where(MetricDefinition.archived_at.is_(None))

    rows = db.scalars(query.order_by(func.lower(MetricDefinition.name))).all()
    out = [_to_read(metric) for metric in rows]
    if user.org_role != "admin" or not rows:
        return out

    from app.models import DataSource, SourceMapping

    feeding: dict[int, list[str]] = {}
    for metric_id, name, connector in db.execute(
        select(SourceMapping.metric_definition_id, DataSource.name, DataSource.connector)
        .join(DataSource, DataSource.id == SourceMapping.data_source_id)
        .where(
            SourceMapping.organization_id == user.organization_id,
            DataSource.archived_at.is_(None),
        )
    ).all():
        # A source still called by its connector's key says so rather than
        # showing the key (review #10).
        label = name if name != connector else connector.replace("_", " ").title()
        feeding.setdefault(metric_id, []).append(label)

    counts = [m.id for m in rows if m.unit == "count" and m.aggregation == "sum"]
    typical = dict(
        db.execute(
            select(MetricFact.metric_definition_id, func.avg(func.abs(MetricFact.value)))
            .where(MetricFact.metric_definition_id.in_(counts))
            .group_by(MetricFact.metric_definition_id)
        ).all()
    ) if counts else {}

    for read in out:
        read.sources = sorted(set(feeding.get(read.id, [])))
        read.looks_like_amounts = (typical.get(read.id) or 0) > AMOUNT_HINT
    return out


@router.post("", response_model=MetricRead, status_code=status.HTTP_201_CREATED)
def create_metric(
    payload: MetricCreate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MetricRead:
    numerator, denominator = _check_parts(
        db, actor.organization_id, payload.aggregation,
        payload.numerator_metric_id, payload.denominator_metric_id,
    )
    _name_free(db, actor.organization_id, payload.name)
    metric = MetricDefinition(
        organization_id=actor.organization_id,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        unit=payload.unit,
        aggregation=payload.aggregation,
        direction=payload.direction,
        decimal_places=payload.decimal_places,
        unit_label=payload.unit_label,
        numerator_metric_id=numerator,
        denominator_metric_id=denominator,
    )
    db.add(metric)
    audit.record(
        db, actor=actor, action="metric.created", request=request, key=payload.key
    )

    try:
        db.commit()
    except IntegrityError:
        # Caught rather than pre-checked with a SELECT: two simultaneous
        # requests can both find the key free and both insert. The unique
        # constraint is the only thing that actually decides, so the error it
        # raises is what gets translated.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A metric with the key '{payload.key}' already exists.",
        ) from None

    return _to_read(metric)


@router.patch("/{metric_id}", response_model=MetricRead)
def update_metric(
    metric_id: int,
    payload: MetricUpdate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MetricRead:
    metric = _owned(db, metric_id, actor.organization_id, allow_archived=True)

    # exclude_unset so an omitted field means "leave alone", not "set to null".
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("name") and metric.archived_at is None:
        _name_free(db, actor.organization_id, fields["name"], metric.id)

    aggregation = fields.get("aggregation", metric.aggregation)
    if (aggregation == "ratio") != (metric.aggregation == "ratio"):
        # Switching in or out of derived changes where every number comes from:
        # facts recorded against it would be ignored, or it would suddenly
        # need facts it has never had.
        has_facts = db.scalar(
            select(MetricFact.id).where(MetricFact.metric_definition_id == metric.id).limit(1)
        )
        if has_facts is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"'{metric.name}' already has data recorded against it, so it "
                    "cannot become a metric worked out from two others. Make a new "
                    "metric for the ratio instead."
                ),
            )
    if aggregation == "ratio" or {"numerator_metric_id", "denominator_metric_id"} & fields.keys():
        fields["numerator_metric_id"], fields["denominator_metric_id"] = _check_parts(
            db, actor.organization_id, aggregation,
            fields.get("numerator_metric_id", metric.numerator_metric_id),
            fields.get("denominator_metric_id", metric.denominator_metric_id),
            itself=metric.id,
        )
    elif metric.aggregation == "ratio":
        fields["numerator_metric_id"] = fields["denominator_metric_id"] = None

    # Changing aggregation or direction silently reinterprets every existing
    # fact — a `sum` metric switched to `last` reports a completely different
    # number for the same data. Recorded so the change is findable when someone
    # asks why last month moved.
    reinterpreting = {
        field: audit.changed(getattr(metric, field), value)
        for field, value in fields.items()
        if field in ("aggregation", "direction", "unit")
        and getattr(metric, field) != value
    }
    if reinterpreting:
        audit.record(
            db,
            actor=actor,
            action="metric.redefined",
            request=request,
            key=metric.key,
            **reinterpreting,
        )

    for field, value in fields.items():
        setattr(metric, field, value)

    db.commit()
    return _to_read(metric)


def _name_free(db: DbSession, org_id: int, name: str, itself: int | None = None) -> None:
    """Refuse a name another metric in use already has, ignoring case (QA-9).

    The name is what every goal, rule and board picker shows, so two alike
    make all of them a guess. Checked first for the message; the unique
    index is what actually decides.
    """
    clash = db.scalar(
        select(MetricDefinition.id).where(
            MetricDefinition.organization_id == org_id,
            MetricDefinition.archived_at.is_(None),
            func.lower(MetricDefinition.name) == name.lower(),
            MetricDefinition.id != (itself or 0),
        )
    )
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"There is already a metric called “{name}”. Pickers would show two alike.",
        )


@router.post("/{metric_id}/archive", response_model=MetricRead)
def archive_metric(
    metric_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MetricRead:
    """Hide a metric without losing what it measured.

    Facts reference the definition, and a leaderboard for last quarter must
    still be able to name the metric it ranked. Archiving removes it from
    pickers and new goals; the history stays readable.
    """
    metric = _owned(db, metric_id, actor.organization_id, allow_archived=True)
    metric.archived_at = datetime.now(UTC)
    db.commit()
    return _to_read(metric)


@router.post("/{metric_id}/restore", response_model=MetricRead)
def restore_metric(
    metric_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MetricRead:
    metric = _owned(db, metric_id, actor.organization_id, allow_archived=True)
    _name_free(db, actor.organization_id, metric.name, metric.id)
    metric.archived_at = None
    db.commit()
    return _to_read(metric)


@router.delete("/{metric_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_metric(
    metric_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Permanently remove a metric.

    Allowed only while nothing has ever been measured with it, so it exists for
    one case: a metric created by mistake. Once facts reference it, archive is
    the correct action — a leaderboard for last quarter must still be able to
    name the metric it ranked.
    """
    metric = _owned(db, metric_id, actor.organization_id, allow_archived=True)

    users = derived.used_by(db, metric)
    if users:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{', '.join(m.name for m in users)} "
                f"{'is' if len(users) == 1 else 'are'} worked out from this metric. "
                "Change or remove that first."
            ),
        )

    facts = int(
        db.scalar(
            select(func.count())
            .select_from(MetricFact)
            .where(MetricFact.metric_definition_id == metric.id)
        )
        or 0
    )
    if facts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{facts:,} {'measurement has' if facts == 1 else 'measurements have'} "
                "been recorded for this metric. Archive it instead — that hides it "
                "from pickers while keeping its history readable."
            ),
        )

    db.delete(metric)
    db.commit()


@router.post("/seed-defaults", response_model=list[MetricRead])
def seed_defaults(
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[MetricRead]:
    """Add back any of the shipped defaults that are missing.

    New organizations get these at setup. This is the recovery path for one that
    cleared them out and wants a starting point again — and the way an existing
    deployment picks up defaults added in a later release.

    Idempotent: existing keys are left exactly as they are, including renames.
    """
    created = seed_default_metrics(db, actor.organization_id)
    # Only when it actually did something. A no-op re-seed writing a row every
    # time someone clicks the button would bury the entries that matter.
    if created:
        audit.record(
            db,
            actor=actor,
            action="metric.defaults_seeded",
            request=request,
            created=created,
        )
    db.commit()
    return list_metrics(include_archived=True, user=actor, db=db)


def _owned(
    db: DbSession,
    metric_id: int,
    organization_id: int,
    *,
    allow_archived: bool = False,
) -> MetricDefinition:
    metric = db.get(MetricDefinition, metric_id)
    # 404 rather than 403 for another organization's metric: confirming it
    # exists would itself leak information.
    if metric is None or metric.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found."
        )
    if metric.archived_at is not None and not allow_archived:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found."
        )
    return metric
