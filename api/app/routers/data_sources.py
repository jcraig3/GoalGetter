"""Connecting a source, describing what it means, and watching it work.

Admin only. A source writes into `metric_fact`, which every leaderboard, goal and
competition reads — so this is the most consequential configuration surface in the
product, and it is not a manager-level decision.

**Secrets go in and never come back.** The API reports *whether* a credential is
set, the same way `sso_config` reports `client_secret_set`. There is no legitimate
reason for a browser to receive a token, and every mechanism that offers to show one
is a mechanism that can be made to.

**One exception, and it is deliberate: a receiving connector's endpoint URL.** A
webhook token is not something a provider already holds — it is an address we
generate that somebody has to paste into another system, so a token that cannot be
read is a feature that cannot be used. `display.url` makes the same trade for the
same reason. It is confined to the detail response, and `POST …/endpoint/rotate`
exists so a leaked one can be replaced without deleting the source and its history.
"""

from __future__ import annotations

import secrets as secrets_module
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import audit, connectors, credentials as credential_store, identity, oauth, public_url
from app import jobs
from app import sync as sync_service
from app.db import SessionFactory, get_db, get_session_factory
from app.models import (
    DataSource,
    MetricDefinition,
    MetricFact,
    Organization,
    SourceMapping,
    SyncRun,
    UserAccount,
    UserIdentity,
)
from app.models.data_source import (
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
)
from app.mapping import FILTER_OPS
from app.scope import can_see_user
from app.sessions import require_role
from app.validation import Name

router = APIRouter(tags=["integrations"])

#: How many recent runs a detail page shows.
#:
#: Enough to see a pattern — "it has failed the last four times" — without turning
#: the page into a log viewer. `sync_run` keeps everything; this is what is worth
#: reading at a glance.
RECENT_RUNS = 10


# ── Reading ──────────────────────────────────────────────────────────────────


class ConnectorRead(BaseModel):
    """One card in the wizard's first step, and the form for its second.

    The schemas are carried as JSON Schema rather than as a hand-written field
    list, because that is what makes a new connector cheap: it arrives with its own
    labels, hints and examples, and the wizard renders them without knowing what a
    warehouse role is. See `SqlConfig` for the wording that ends up on screen.
    """

    key: str
    display_name: str

    #: Non-secret settings — host, query, which sheet.
    config_schema: dict
    #: Secrets. The same shape, rendered as password fields and never read back.
    credential_schema: dict

    #: True when this connector is **posted to** rather than polled, so setup shows
    #: an endpoint to copy instead of a form to fill in. Stated rather than inferred
    #: from `endpoint_url` being null, which is also true of a source whose token
    #: has not been generated yet.
    receives: bool

    #: Which provider this connector signs in to, when it does. Enough for the
    #: wizard to label a button — "Sign in with Google" — and nothing more: the
    #: endpoints and scopes are the server's business.
    oauth: dict | None = None

    #: How to get the credentials, in numbered steps. Empty for a connector with
    #: nothing to explain. Shown above the form, where the field hints beside each
    #: box cannot go: a route through somebody else's product spread across four
    #: hint texts is a route nobody follows.
    setup_steps: list[str] = []


class MappingRead(BaseModel):
    id: int
    metric_id: int
    metric_name: str
    enabled: bool
    value_field: str | None
    occurred_at_field: str | None
    subject_field: str
    external_id_field: str | None
    snapshot_daily: bool
    filters: list
    multiplier: Decimal


class RunRead(BaseModel):
    id: int
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    rows_read: int
    rows_written: int
    rows_quarantined: int
    rows_skipped: int
    conflicts: int
    error: str | None


class SourceRead(BaseModel):
    id: int
    name: str
    connector: str
    connector_name: str
    enabled: bool
    config: dict
    interval_minutes: int
    backfill_days: int
    timezone: str | None
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_status: str | None
    failure_count: int

    #: Whether secrets are stored, never what they are.
    credentials_set: bool
    #: True when this build has no connector by that key — a source configured on a
    #: newer version, or one deliberately removed. The scheduler skips it, and the
    #: UI needs to say so rather than showing a source that will never run.
    connector_missing: bool

    #: Removed from the list, but its facts keep pointing here for provenance.
    #: A removed source has no credential and does not run.
    archived: bool

    #: False means setup was never finished — a draft. Distinct from a source that
    #: was finished and later paused, which looks identical from outside and must
    #: not be swept away.
    activated: bool

    mappings: list[MappingRead]
    #: Identifiers waiting on a decision. The number that belongs on a badge.
    pending_identities: int
    #: Facts this source has written, which is what makes it undeletable.
    facts_written: int
    #: When the newest number it wrote happened (7.3).
    newest_row_at: datetime | None = None
    #: Working days with nothing new, when that is long enough to say so —
    #: a source can sync cleanly and still be stuck. See `app/staleness.py`.
    stale_working_days: int | None = None


class SourceDetail(SourceRead):
    recent_runs: list[RunRead]

    #: The URL a sender posts to. Only for connectors that receive rather than
    #: fetch; None for everything else.
    #:
    #: **This is the one credential that is returned**, and the exception is the
    #: same one `display.url` already makes: a token whose only purpose is to be
    #: pasted somewhere else is useless if it cannot be read, and re-issuing it on
    #: every visit would break every sender configured with the old one. Setting a
    #: CRM up a fortnight after connecting the source must not need a new endpoint.
    #:
    #: On the detail response only. The index lists every source an organization
    #: has, and putting a live endpoint on each row would spread the credential
    #: across a page nobody came to for it.
    endpoint_url: str | None = None


class FieldRead(BaseModel):
    name: str
    kind: str
    samples: list[str]
    #: Every distinct value, when there are few enough to be a choice. Empty
    #: otherwise — which is how the wizard tells a category apart from a name.
    values: list[str] = Field(default_factory=list)


class PreviewRowRead(BaseModel):
    outcome: str
    source_values: dict
    subject_name: str | None
    value: Decimal | None
    occurred_at: datetime | None
    external_id: str | None
    detail: str | None


class IdentityRead(BaseModel):
    id: int
    external_identifier: str
    pending_rows: int
    last_seen_at: datetime | None


# ── Writing ──────────────────────────────────────────────────────────────────


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(120)
    connector: str
    config: dict = Field(default_factory=dict)
    #: `0` means read once and stop — see `models.data_source.READ_ONCE`. The
    #: floor is otherwise five minutes, and the ceiling a month.
    interval_minutes: int = Field(default=DEFAULT_INTERVAL_MINUTES, ge=0, le=43200)

    @field_validator("interval_minutes")
    @classmethod
    def _sane_interval(cls, value: int) -> int:
        # Mirrors the database constraint, so the refusal is a sentence rather
        # than an integrity error somebody has to decode.
        if value != 0 and value < MIN_INTERVAL_MINUTES:
            raise ValueError(
                f"An interval is either 0 (read once) or at least "
                f"{MIN_INTERVAL_MINUTES} minutes."
            )
        return value
    backfill_days: int = Field(default=DEFAULT_BACKFILL_DAYS, ge=0, le=3650)
    timezone: str | None = None

    @field_validator("connector")
    @classmethod
    def _known(cls, value: str) -> str:
        # Validated against the registry rather than a stored list: connectors
        # arrive by shipping code, and a database enum would need a migration to
        # release one.
        if value not in connectors.keys():
            raise ValueError(
                f"Unknown connector. This build has: {', '.join(connectors.keys())}."
            )
        return value


class SourceUpdate(BaseModel):
    """Everything except which connector it is.

    Changing that would make it a different source whose history of "this is where
    those numbers came from" now points somewhere else. Delete and reconnect, which
    is honest about what happened.
    """

    model_config = ConfigDict(extra="forbid")

    name: Name(120) | None = None
    enabled: bool | None = None
    config: dict | None = None
    #: `0` means read once and stop. Same bounds as the create payload — two
    #: models validating the same field differently is how a value gets in one
    #: way and is refused the other.
    interval_minutes: int | None = Field(default=None, ge=0, le=43200)

    @field_validator("interval_minutes")
    @classmethod
    def _sane_interval(cls, value: int | None) -> int | None:
        if value is not None and value != 0 and value < MIN_INTERVAL_MINUTES:
            raise ValueError(
                f"An interval is either 0 (read once) or at least "
                f"{MIN_INTERVAL_MINUTES} minutes."
            )
        return value
    backfill_days: int | None = Field(default=None, ge=0, le=3650)
    timezone: str | None = None


class CredentialWrite(BaseModel):
    """Secrets, in only.

    A free-form dict rather than a per-connector model, because each connector
    declares its own `credential_schema` and validation happens against that — see
    `set_credentials`.
    """

    model_config = ConfigDict(extra="forbid")

    secrets: dict


class MappingWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_id: int
    #: Empty means the source has no date: the fact is dated by when its
    #: number last changed. See `models/data_source.py`.
    occurred_at_field: str | None = Field(default=None, max_length=200)
    subject_field: str = Field(min_length=1, max_length=200)
    #: None means count each row as one — how a "deals won" metric works.
    value_field: str | None = Field(default=None, max_length=200)
    external_id_field: str | None = Field(default=None, max_length=200)

    #: One fact per row per day, instead of one fact per row. See
    #: `models/data_source.py` — opt-in, because for a row-per-event source it
    #: turns one sale into one a day.
    snapshot_daily: bool = False
    filters: list[dict] = Field(default_factory=list)
    multiplier: Decimal = Decimal(1)
    enabled: bool = True

    @model_validator(mode="after")
    def _identifiable(self):
        """A mapping with no date column must say which column identifies a row.

        **Not a style rule — the dating depends on it.** With no date, a fact is
        dated by when its number last changed, which means finding the fact
        written last time and comparing. Without a row id there is nothing to find
        it by, so every read inserts a new fact: the totals multiply, and the date
        is always the day of the read. Failing here is the difference between a
        refused mapping and a leaderboard that is quietly wrong.
        """
        if not self.occurred_at_field and not self.external_id_field:
            raise ValueError(
                "With no date column, pick the column that identifies each row — "
                "without it the same row is imported again on every read instead "
                "of being updated."
            )
        return self

    @field_validator("multiplier")
    @classmethod
    def _not_zero(cls, value: Decimal) -> Decimal:
        # Zero would silently turn every measurement into nothing, which looks
        # exactly like a broken integration.
        if value == 0:
            raise ValueError("A multiplier of zero would make every value nothing.")
        return value

    @field_validator("filters")
    @classmethod
    def _filters(cls, value: list[dict]) -> list[dict]:
        for rule in value:
            if not rule.get("field"):
                raise ValueError("Every filter needs a field.")
            if rule.get("op", "eq") not in FILTER_OPS:
                raise ValueError(
                    f"Unknown filter operator {rule.get('op')!r}. "
                    f"Use one of: {', '.join(FILTER_OPS)}."
                )
        return value


class MapIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int


# ── Helpers ──────────────────────────────────────────────────────────────────


def _org(db: DbSession, actor: UserAccount) -> Organization:
    return db.get(Organization, actor.organization_id)


def _owned(db: DbSession, actor: UserAccount, source_id: int) -> DataSource:
    source = db.get(DataSource, source_id)
    if source is None or source.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source not found."
        )
    return source


def _mark_activated(source: DataSource, *, enabling: bool) -> None:
    """Stamp the moment setup was finished, once.

    "Finished" is the first time a mapping is switched on, because that is the
    first moment the source can import anything — everything before it is a draft
    somebody may abandon. Stamped once and never cleared: pausing a source later
    does not make it unfinished again, which is the distinction the column exists
    to hold.
    """
    if enabling and source.activated_at is None:
        source.activated_at = datetime.now(UTC)


def _newness(db: DbSession, source: DataSource) -> dict:
    """The newest row, and whether its age is worth saying (7.3)."""
    from app import staleness

    newest = staleness.newest_row(db, source.id)
    days = None
    if newest is not None and staleness.is_watched(source):
        org = db.get(Organization, source.organization_id)
        quiet = staleness.quiet_days(org, newest, datetime.now(UTC))
        days = quiet if quiet is not None and quiet >= staleness.STALE_WORKING_DAYS else None
    return {"newest_row_at": newest, "stale_working_days": days}


def _facts_written(db: DbSession, source: DataSource) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(MetricFact)
            .where(MetricFact.data_source_id == source.id)
        )
        or 0
    )


def _to_read(db: DbSession, source: DataSource, *, detail: bool = False):
    try:
        connector = connectors.get(source.connector)
        connector_name = connector.display_name
        missing = False
    except connectors.UnknownConnector:
        connector_name = source.connector
        missing = True

    mappings = [
        MappingRead(
            id=m.id,
            metric_id=m.metric_definition_id,
            metric_name=(
                (metric := db.get(MetricDefinition, m.metric_definition_id))
                and metric.name
            )
            or "Deleted metric",
            enabled=m.enabled,
            value_field=m.value_field,
            occurred_at_field=m.occurred_at_field,
            subject_field=m.subject_field,
            external_id_field=m.external_id_field,
            snapshot_daily=m.snapshot_daily,
            filters=m.filters or [],
            multiplier=m.multiplier,
        )
        for m in db.scalars(
            select(SourceMapping)
            .where(SourceMapping.data_source_id == source.id)
            .order_by(SourceMapping.id)
        ).all()
    ]

    pending = (
        db.scalar(
            select(func.count())
            .select_from(UserIdentity)
            .where(
                UserIdentity.data_source_id == source.id,
                UserIdentity.user_id.is_(None),
                UserIdentity.ignored.is_(False),
            )
        )
        or 0
    )

    fields = dict(
        id=source.id,
        name=source.name,
        connector=source.connector,
        connector_name=connector_name,
        enabled=source.enabled,
        config=source.config or {},
        interval_minutes=source.interval_minutes,
        backfill_days=source.backfill_days,
        timezone=source.timezone,
        next_run_at=source.next_run_at,
        last_run_at=source.last_run_at,
        last_status=source.last_status,
        failure_count=source.failure_count,
        # **"Can it authenticate", not "does it store a secret".** Those were
        # the same question until the Excel account moved to the organization,
        # and leaving this asserting the old one made every working Excel source
        # report *Setup unfinished* and offer to resume a wizard it had finished.
        credentials_set=(
            credential_store.has_secrets(db, source)
            or oauth.has_shared_credential(db, source)
        ),
        archived=source.archived_at is not None,
        activated=source.activated_at is not None,
        connector_missing=missing,
        mappings=mappings,
        pending_identities=pending,
        facts_written=_facts_written(db, source),
        **_newness(db, source),
    )

    if not detail:
        return SourceRead(**fields)

    runs = [
        RunRead(
            id=r.id,
            trigger=r.trigger,
            status=r.status,
            started_at=r.started_at,
            finished_at=r.finished_at,
            rows_read=r.rows_read,
            rows_written=r.rows_written,
            rows_quarantined=r.rows_quarantined,
            rows_skipped=r.rows_skipped,
            conflicts=r.conflicts,
            error=r.error,
        )
        for r in db.scalars(
            select(SyncRun)
            .where(SyncRun.data_source_id == source.id)
            .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
            .limit(RECENT_RUNS)
        ).all()
    ]
    return SourceDetail(
        **fields, recent_runs=runs, endpoint_url=_endpoint_url(db, source)
    )


#: Where a receiving connector's endpoint lives, matching `hooks.router`.
HOOK_PATH = "/api/hooks"


def _endpoint_url(db: DbSession, source: DataSource) -> str | None:
    """The URL to paste into the sending system, or None if it fetches instead.

    Assembled from the address in Settings rather than the incoming request, the same as a display
    link: an admin might be on `localhost` behind a proxy, and the endpoint has to be
    the address the *sender* can reach.
    """
    try:
        key = connectors.endpoint_credential_of(connectors.get(source.connector))
    except connectors.UnknownConnector:
        return None
    if key is None:
        return None
    token = credential_store.get(db, source).get(key)
    if not token:
        return None
    return f"{public_url.get(db)}{HOOK_PATH}/{token}"


# ── Connectors ───────────────────────────────────────────────────────────────


def _oauth_summary(connector) -> dict | None:
    """What the wizard needs to know about a connector's sign-in, and no more.

    The provider's name for a button label. Not the endpoints or the scopes: those
    decide what access is requested, and a browser has no business being able to
    read — let alone influence — either.
    """
    spec = connectors.oauth_of(connector)
    if spec is None:
        return None
    return {"provider": spec.provider, "provider_name": spec.provider_name}


@router.get("/connectors", response_model=list[ConnectorRead])
def list_connectors(
    actor: UserAccount = Depends(require_role("admin")),
) -> list[ConnectorRead]:
    """What this build can connect to — the wizard's first step."""
    return [
        ConnectorRead(
            key=c.key,
            display_name=c.display_name,
            config_schema=c.config_schema.model_json_schema(),
            credential_schema=c.credential_schema.model_json_schema(),
            receives=connectors.endpoint_credential_of(c) is not None,
            oauth=_oauth_summary(c),
            setup_steps=list(connectors.setup_steps_of(c)),
        )
        for c in connectors.available()
    ]


# ── Sources ──────────────────────────────────────────────────────────────────


#: Config keys that together say "this is the same spreadsheet and the same tab".
#:
#: Per connector, because the two name a file differently — Microsoft addresses it
#: by drive and item, Google by one id — while meaning exactly the same thing. The
#: tab is part of the identity in both: one file with a tab per team is the normal
#: shape, and those tabs are genuinely different sources.
_SHEET_IDENTITY = {
    "microsoft_excel": ("drive_id", "item_id", "worksheet"),
    "google_sheets": ("spreadsheet_id", "tab"),
}

#: The keys that must be filled for a config to identify anything at all.
#:
#: Everything but the tab: an empty tab means "the first one", which is a real
#: answer, while an empty file id means the source is half-built. Two drafts with
#: nothing set are not duplicates of each other.
_SHEET_REQUIRED = {
    "microsoft_excel": ("drive_id", "item_id"),
    "google_sheets": ("spreadsheet_id",),
}


def _same_sheet(db: DbSession, source: DataSource) -> DataSource | None:
    """Another live source already reading this exact workbook and tab.

    **Because five of them is what happens otherwise.** Every trip through the
    wizard makes a new source, so re-running it to fix a mapping leaves the
    previous attempt behind — enabled, on its own schedule, writing the same facts
    from the same file. The duplicates all sync, all succeed, and nothing on any
    screen says they are the same sheet.

    Archived sources are ignored: one deliberately removed is not in the way, and
    treating it as a clash would make removing-and-re-adding impossible.

    Sources with no ids are ignored too — a half-built draft, or one configured
    before the picker existed — because "both have nothing set" is not sameness.
    """
    keys = _SHEET_IDENTITY.get(source.connector)
    if keys is None:
        return None

    identity = {key: str(source.config.get(key) or "").strip() for key in keys}
    if any(not identity[key] for key in _SHEET_REQUIRED[source.connector]):
        return None

    others = db.scalars(
        select(DataSource).where(
            DataSource.organization_id == source.organization_id,
            DataSource.connector == source.connector,
            DataSource.id != source.id,
            DataSource.archived_at.is_(None),
        )
    ).all()

    for other in others:
        if all(
            str(other.config.get(key) or "").strip() == identity[key] for key in keys
        ):
            return other
    return None


def _refuse_duplicate(db: DbSession, source: DataSource) -> None:
    """Stop a second source reading the same sheet, naming the first one."""
    clash = _same_sheet(db, source)
    if clash is None:
        return
    sheet = str(
        source.config.get("worksheet") or source.config.get("tab") or ""
    ).strip()
    where = f" “{sheet}”" if sheet else ""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"{clash.name} already reads that spreadsheet{where}. Two sources on one "
            "sheet would import every row twice — open that one instead, or choose a "
            "different tab."
        ),
    )


@router.get("/data-sources", response_model=list[SourceRead])
def list_sources(
    include_archived: bool = Query(default=False),
    include_drafts: bool = Query(default=False),
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[SourceRead]:
    """What is actually running. Everything else has to be asked for.

    Two things are left out by default, for the same reason: the page answers "what
    is feeding my leaderboards", and neither of them is.

    **Drafts** are connect flows nobody finished. They import nothing and are swept
    away after a day, so listing them turns an abandoned click into a chore.

    **Removed** sources stay in the table so their facts can still say where they
    came from, but they are finished business.

    Neither is unreachable — both have a parameter here and their own pages still
    load — because a source whose facts are on a leaderboard has to be inspectable
    even after somebody tidied it away.
    """
    query = select(DataSource).where(
        DataSource.organization_id == actor.organization_id
    )
    if not include_archived:
        query = query.where(DataSource.archived_at.is_(None))
    if not include_drafts:
        query = query.where(DataSource.activated_at.is_not(None))
    return [
        _to_read(db, source)
        for source in db.scalars(query.order_by(DataSource.name)).all()
    ]


@router.post(
    "/data-sources", response_model=SourceDetail, status_code=status.HTTP_201_CREATED
)
def create_source(
    payload: SourceCreate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SourceDetail:
    """Connect a source. It syncs as soon as it has a mapping.

    `next_run_at` is left NULL, which the scheduler reads as due — so a newly
    connected source does something visible promptly rather than appearing to sit
    idle for an hour.
    """
    source = DataSource(
        organization_id=actor.organization_id,
        name=payload.name,
        connector=payload.connector,
        config=payload.config,
        interval_minutes=payload.interval_minutes,
        backfill_days=payload.backfill_days,
        timezone=payload.timezone,
        created_by_user_id=actor.id,
    )
    db.add(source)
    db.flush()

    generated = connectors.endpoint_credential_of(connectors.get(payload.connector))
    if generated is not None:
        # Generated here, not asked for. An address somebody chose is an address
        # somebody can guess, and for a receiving connector it is the whole
        # credential.
        credential_store.put(
            db, source, {generated: secrets_module.token_urlsafe(32)}
        )

    audit.record(
        db,
        actor=actor,
        action="data_source.created",
        request=request,
        name=source.name,
        connector=source.connector,
    )
    db.commit()
    return _to_read(db, source, detail=True)


@router.get("/data-sources/{source_id}", response_model=SourceDetail)
def read_source(
    source_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SourceDetail:
    return _to_read(db, _owned(db, actor, source_id), detail=True)


@router.patch("/data-sources/{source_id}", response_model=SourceDetail)
def update_source(
    source_id: int,
    payload: SourceUpdate,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SourceDetail:
    source = _owned(db, actor, source_id)
    changes = payload.model_dump(exclude_unset=True)

    if source.archived_at is not None and changes.get("enabled"):
        # Otherwise a removed integration could be switched back on without
        # being restored — running again, with no credential, from a page that
        # does not show it.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{source.name} has been removed. Restore it first, then "
                "reconnect it."
            ),
        )

    for field, value in changes.items():
        setattr(source, field, value)

    # **After the assignment, before the commit.** Checked against what the
    # source is about to become rather than what was sent, so it catches a clash
    # introduced by changing only the worksheet as well as one from a fresh
    # config. `db.flush()` is deliberately not called first — nothing is written
    # until this returns.
    if "config" in changes:
        _refuse_duplicate(db, source)

    audit.record(
        db,
        actor=actor,
        action="data_source.updated",
        request=request,
        name=source.name,
        fields=sorted(changes),
    )
    db.commit()
    return _to_read(db, source, detail=True)


@router.post("/data-sources/{source_id}/archive", response_model=SourceDetail)
def archive_source(
    source_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SourceDetail:
    """Remove the integration, keep the numbers.

    **The action a test webhook needs.** Deleting is refused once a source has
    written facts, because `metric_fact.data_source_id` is what answers "where did
    this number come from" — so without this there was no way to tidy one away and
    the list grew forever.

    Three things happen together, and all three are the point:

    * the **credential is forgotten**, so the integration genuinely stops working.
      A webhook endpoint that still accepted deliveries after being removed would
      be a removal in name only;
    * it is **disabled**, so nothing schedules it;
    * it is **hidden**, so it is out of the way rather than out of existence.

    Its facts stay exactly where they are and keep counting on leaderboards. That
    is deliberate: the numbers were real when they arrived, and removing the
    plumbing is not a statement about the measurements.
    """
    source = _owned(db, actor, source_id)
    credential_store.forget(db, source)
    source.enabled = False
    source.archived_at = datetime.now(UTC)
    audit.record(
        db,
        actor=actor,
        action="data_source.archived",
        request=request,
        name=source.name,
        facts_kept=_facts_written(db, source),
    )
    db.commit()
    return _to_read(db, source, detail=True)


@router.post("/data-sources/{source_id}/restore", response_model=SourceDetail)
def restore_source(
    source_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SourceDetail:
    """Bring a removed source back — its history and its mappings, not its
    credential.

    Left disabled on purpose. Archiving forgot the credential, so a restored
    source has nothing to connect with; enabling it here would produce a source
    that fails on its next run and reports it as a failure rather than as the
    unfinished setup it is. The connect flow picks it up from exactly there.
    """
    source = _owned(db, actor, source_id)
    source.archived_at = None
    audit.record(
        db,
        actor=actor,
        action="data_source.restored",
        request=request,
        name=source.name,
    )
    db.commit()
    return _to_read(db, source, detail=True)


@router.delete("/data-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Remove a source that has never written anything.

    Refused once it has, and the message says how many. Those are real
    measurements that leaderboards and settled competitions were computed from —
    the same rule as a metric that has been measured. **Disable it instead**, which
    stops it syncing and keeps its history.
    """
    source = _owned(db, actor, source_id)
    written = _facts_written(db, source)
    if written:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This source has recorded {written:,} "
                f"{'measurement' if written == 1 else 'measurements'}, which "
                "leaderboards and competitions were computed from. Remove it "
                "instead — that disconnects it and takes it out of the list, "
                "keeping the numbers it imported."
            ),
        )

    name = source.name
    db.delete(source)
    audit.record(
        db, actor=actor, action="data_source.deleted", request=request, name=name
    )
    db.commit()


# ── Credentials ──────────────────────────────────────────────────────────────


@router.put("/data-sources/{source_id}/credentials", response_model=SourceDetail)
def set_credentials(
    source_id: int,
    payload: CredentialWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SourceDetail:
    """Store secrets. Validated against the connector's own schema.

    Validated rather than accepted blindly so a typo'd key is caught here rather
    than surfacing as a failed sync at three in the morning. Never read back — the
    response reports `credentials_set` and nothing else.

    **Unnamed keys keep what is already stored.** `credential_store.put` replaces,
    for good reasons of its own, so submitting one field would otherwise blank the
    rest — an admin turning on signatures would save a signing secret and silently
    destroy the webhook's endpoint token, which is the whole credential. Merging
    here keeps `put` honest about replacing while letting a form send only what
    changed. To clear a secret, send it empty, or disconnect.
    """
    source = _owned(db, actor, source_id)
    try:
        connector = connectors.get(source.connector)
    except connectors.UnknownConnector as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from None

    # Checked explicitly rather than by `extra="forbid"` on every connector's
    # schema: pydantic ignores unknown keys by default, so a typo would validate,
    # store nothing under the name meant, and *blank the real secret*. Naming the
    # valid keys is also the more useful answer than "unexpected field".
    generated = connectors.endpoint_credential_of(connector)
    if generated is not None and generated in payload.secrets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{generated!r} is generated, not chosen — one somebody picked is "
                "one somebody can guess. Use the rotate action to replace it."
            ),
        )

    known = [
        name
        for name in connector.credential_schema.model_fields
        if name != generated
    ]
    unknown = sorted(set(payload.secrets) - set(known))
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{connector.display_name} has no credential called "
                f"{unknown[0]!r}. It takes: {', '.join(known)}."
            ),
        )

    try:
        validated = connector.credential_schema(
            **{**credential_store.get(db, source), **payload.secrets}
        )
    except Exception as error:  # noqa: BLE001 — pydantic's message is the useful part
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from None

    credential_store.put(db, source, validated.model_dump())
    audit.record(
        db,
        actor=actor,
        action="data_source.credentials_set",
        request=request,
        name=source.name,
        # The keys, never the values — enough to see *what* was set.
        keys=sorted(payload.secrets),
    )
    db.commit()
    return _to_read(db, source, detail=True)


@router.post("/data-sources/{source_id}/endpoint/rotate", response_model=SourceDetail)
def rotate_endpoint(
    source_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SourceDetail:
    """Issue a new endpoint for a receiving connector, invalidating the old one.

    For a URL that ended up somewhere it should not have. **It breaks every sender
    configured with the old address** — that is the point, and it is why this is a
    deliberate action rather than something that happens on its own.

    Keeps the signing secret. Rotating an address is not the same as changing the
    shared key, and quietly doing both would mean the sender has to be reconfigured
    twice for one problem.
    """
    source = _owned(db, actor, source_id)
    try:
        generated = connectors.endpoint_credential_of(
            connectors.get(source.connector)
        )
    except connectors.UnknownConnector as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from None
    if generated is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{source.name} fetches its data rather than receiving it, so it has "
                "no endpoint to rotate."
            ),
        )

    kept = credential_store.get(db, source)
    kept[generated] = secrets_module.token_urlsafe(32)
    credential_store.put(db, source, kept)
    audit.record(
        db,
        actor=actor,
        action="data_source.endpoint_rotated",
        request=request,
        name=source.name,
    )
    db.commit()
    return _to_read(db, source, detail=True)


@router.delete("/data-sources/{source_id}/credentials", response_model=SourceDetail)
def forget_credentials(
    source_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SourceDetail:
    """Disconnect the account without deleting the source or its history."""
    source = _owned(db, actor, source_id)
    credential_store.forget(db, source)
    source.enabled = False
    audit.record(
        db,
        actor=actor,
        action="data_source.disconnected",
        request=request,
        name=source.name,
    )
    db.commit()
    return _to_read(db, source, detail=True)


# ── Testing, discovering, previewing ─────────────────────────────────────────


class TestResult(BaseModel):
    ok: bool
    detail: str
    info: dict[str, str] = Field(default_factory=dict)


@router.post("/data-sources/{source_id}/test", response_model=TestResult)
def test_source(
    source_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> TestResult:
    """The Test button.

    Returns 200 with `ok: false` rather than an error status. A failed connection
    test is a successful *test* — the client asked a question and got an answer, and
    a 4xx here would make a browser treat a working feature as a broken request.
    """
    source = _owned(db, actor, source_id)
    try:
        connector = connectors.get(source.connector)
        config = connector.config_schema(**oauth.config_for(db, source))
        secrets = connector.credential_schema(
            **oauth.ensure_fresh(db, source, connectors.oauth_of(connector))
        )
        outcome = connector.test_connection(config, secrets)
    except connectors.UnknownConnector as error:
        return TestResult(ok=False, detail=str(error))
    except Exception as error:  # noqa: BLE001 — reported, not raised
        return TestResult(ok=False, detail=f"{type(error).__name__}: {error}")
    return TestResult(ok=outcome.ok, detail=outcome.detail, info=outcome.info)


@router.get("/data-sources/{source_id}/fields", response_model=list[FieldRead])
def discover_fields(
    source_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[FieldRead]:
    """What columns this source has, so the mapper can suggest rather than ask.

    An empty list is a normal answer, not a failure — a webhook that has not yet
    received anything has no schema to report, which is exactly why the setup flow
    asks for one test event before the mapping step.
    """
    source = _owned(db, actor, source_id)
    try:
        connector = connectors.get(source.connector)
        config = connector.config_schema(**oauth.config_for(db, source))
        secrets = connector.credential_schema(
            **oauth.ensure_fresh(db, source, connectors.oauth_of(connector))
        )
        found = connector.discover(
            config,
            secrets,
            local=connectors.LocalContext(db=db, source_id=source.id),
        )
    except connectors.UnknownConnector as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from None
    return [
        FieldRead(
            name=f.name, kind=f.kind, samples=list(f.samples), values=list(f.values)
        )
        for f in found
    ]


@router.post(
    "/data-sources/{source_id}/mappings/{mapping_id}/preview",
    response_model=list[PreviewRowRead],
)
def preview_mapping(
    source_id: int,
    mapping_id: int,
    limit: int = Query(default=sync_service.PREVIEW_ROWS, ge=1, le=50),
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[PreviewRowRead]:
    """Real rows as the facts they would become. Nothing is written.

    The single most useful thing on this page: a mapping error shows up in three
    seconds rather than after a sync has recorded forty thousand wrong numbers.
    """
    source = _owned(db, actor, source_id)
    source_mapping = _owned_mapping(db, source, mapping_id)
    try:
        rows = sync_service.preview(
            db, _org(db, actor), source, source_mapping, limit=limit
        )
    except connectors.UnknownConnector as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from None
    return [
        PreviewRowRead(
            outcome=r.outcome,
            source_values=r.source_values,
            subject_name=r.subject_name,
            value=r.value,
            occurred_at=r.occurred_at,
            external_id=r.external_id,
            detail=r.detail,
        )
        for r in rows
    ]


@router.post("/data-sources/{source_id}/sync", response_model=RunRead)
def sync_now(
    source_id: int,
    request: Request,
    background: BackgroundTasks,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
    sessions: SessionFactory = Depends(get_session_factory),
) -> RunRead:
    """Run it now. Returns the run, whatever its outcome.

    Not an error response for a failed sync: the request to run succeeded, and the
    run's own `status` and `error` are the answer. A 500 here would hide the very
    detail somebody clicked the button to see.
    """
    source = _owned(db, actor, source_id)
    outcome = sync_service.run(db, _org(db, actor), source, trigger="manual")
    audit.record(
        db,
        actor=actor,
        action="data_source.synced",
        request=request,
        name=source.name,
        status=outcome.status,
        written=outcome.rows_written,
    )
    db.commit()
    if outcome.rows_written:
        background.add_task(jobs.announce_now, sessions)
    return RunRead(
        id=outcome.id,
        trigger=outcome.trigger,
        status=outcome.status,
        started_at=outcome.started_at,
        finished_at=outcome.finished_at,
        rows_read=outcome.rows_read,
        rows_written=outcome.rows_written,
        rows_quarantined=outcome.rows_quarantined,
        rows_skipped=outcome.rows_skipped,
        conflicts=outcome.conflicts,
        error=outcome.error,
    )


# ── Mappings ─────────────────────────────────────────────────────────────────


def _owned_mapping(
    db: DbSession, source: DataSource, mapping_id: int
) -> SourceMapping:
    row = db.get(SourceMapping, mapping_id)
    if row is None or row.data_source_id != source.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Mapping not found."
        )
    return row


@router.post(
    "/data-sources/{source_id}/mappings",
    response_model=SourceDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_mapping(
    source_id: int,
    payload: MappingWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SourceDetail:
    source = _owned(db, actor, source_id)
    metric = _metric_for(db, actor, payload.metric_id)

    existing = db.scalar(
        select(SourceMapping).where(
            SourceMapping.data_source_id == source.id,
            SourceMapping.metric_definition_id == metric.id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This source already feeds {metric.name}. Edit that mapping "
                "rather than adding a second one — two would be two ways to "
                "compute the same number from the same place."
            ),
        )

    db.add(
        SourceMapping(
            organization_id=actor.organization_id,
            data_source_id=source.id,
            metric_definition_id=metric.id,
            **payload.model_dump(exclude={"metric_id"}),
        )
    )
    _mark_activated(source, enabling=payload.enabled)
    audit.record(
        db,
        actor=actor,
        action="source_mapping.created",
        request=request,
        name=source.name,
        metric=metric.key,
    )
    db.commit()
    return _to_read(db, source, detail=True)


@router.patch(
    "/data-sources/{source_id}/mappings/{mapping_id}", response_model=SourceDetail
)
def update_mapping(
    source_id: int,
    mapping_id: int,
    payload: MappingWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SourceDetail:
    """Edit a mapping. **Does not rewrite what it already imported.**

    Changing which column is the value changes what future syncs record; the facts
    already written stay as they are, because they are what the source said at the
    time and a leaderboard for last month should not move because somebody fixed a
    mapping today. Re-importing is a deliberate act — delete the facts, or widen the
    backfill window.
    """
    source = _owned(db, actor, source_id)
    row = _owned_mapping(db, source, mapping_id)
    metric = _metric_for(db, actor, payload.metric_id)

    if metric.id != row.metric_definition_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "A mapping cannot change which metric it feeds — its imported facts "
                "belong to the old one. Delete it and add a new mapping."
            ),
        )

    for field, value in payload.model_dump(exclude={"metric_id"}).items():
        setattr(row, field, value)
    _mark_activated(source, enabling=payload.enabled)

    audit.record(
        db,
        actor=actor,
        action="source_mapping.updated",
        request=request,
        name=source.name,
        metric=metric.key,
    )
    db.commit()
    return _to_read(db, source, detail=True)


@router.delete(
    "/data-sources/{source_id}/mappings/{mapping_id}", response_model=SourceDetail
)
def delete_mapping(
    source_id: int,
    mapping_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SourceDetail:
    """Stop feeding this metric. The facts already imported stay.

    They are real measurements. Removing a mapping says "stop adding more", not
    "that never happened" — and a settled competition may have been decided on
    them.
    """
    source = _owned(db, actor, source_id)
    row = _owned_mapping(db, source, mapping_id)
    metric = db.get(MetricDefinition, row.metric_definition_id)

    db.delete(row)
    audit.record(
        db,
        actor=actor,
        action="source_mapping.deleted",
        request=request,
        name=source.name,
        metric=metric.key if metric else None,
    )
    db.commit()
    return _to_read(db, source, detail=True)


def _metric_for(db: DbSession, actor: UserAccount, metric_id: int) -> MetricDefinition:
    metric = db.get(MetricDefinition, metric_id)
    if metric is None or metric.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Metric not found."
        )
    if metric.archived_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"'{metric.name}' is archived. Restore it before importing into it."
            ),
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


# ── Quarantine ───────────────────────────────────────────────────────────────


@router.get("/data-sources/{source_id}/identities", response_model=list[IdentityRead])
def list_identities(
    source_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[IdentityRead]:
    """Who this source mentions that we do not recognise, busiest first."""
    source = _owned(db, actor, source_id)
    return [
        IdentityRead(
            id=i.id,
            external_identifier=i.external_identifier,
            pending_rows=i.pending_rows,
            last_seen_at=i.last_seen_at,
        )
        for i in identity.pending(db, source)
    ]


@router.post(
    "/data-sources/{source_id}/identities/{identity_id}/map",
    response_model=list[IdentityRead],
)
def map_identity(
    source_id: int,
    identity_id: int,
    payload: MapIdentity,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[IdentityRead]:
    """"This identifier is that person." Answered once, applies forever.

    The rows already held are not re-attached here — they were never stored, only
    counted. The next sync re-reads the source and they match, which is why
    quarantining costs nothing.
    """
    source = _owned(db, actor, source_id)
    row = _owned_identity(db, source, identity_id)

    person = db.get(UserAccount, payload.user_id)
    if (
        person is None
        or person.organization_id != actor.organization_id
        or not can_see_user(db, actor, person.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found."
        )

    identity.map_to(db, row, person.id)
    audit.record(
        db,
        actor=actor,
        action="user_identity.mapped",
        request=request,
        target=person,
        name=source.name,
        identifier=row.external_identifier,
    )
    db.commit()
    return list_identities(source_id, actor=actor, db=db)


@router.post(
    "/data-sources/{source_id}/identities/{identity_id}/ignore",
    response_model=list[IdentityRead],
)
def ignore_identity(
    source_id: int,
    identity_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[IdentityRead]:
    """"Never mind this one." For the service account a CRM owns half its records
    with — without this, the list asks about it forever."""
    source = _owned(db, actor, source_id)
    row = _owned_identity(db, source, identity_id)

    identity.ignore(db, row)
    audit.record(
        db,
        actor=actor,
        action="user_identity.ignored",
        request=request,
        name=source.name,
        identifier=row.external_identifier,
    )
    db.commit()
    return list_identities(source_id, actor=actor, db=db)


@router.post(
    "/data-sources/{source_id}/identities/ignore-rest",
    response_model=list[IdentityRead],
)
def ignore_remaining_identities(
    source_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[IdentityRead]:
    """"None of the rest are people here." One click for the whole tail.

    **The case this exists for is a warehouse with history.** A view of sales
    going back years names everybody who ever worked here, and the ones who left
    will never match — they are not questions anybody can answer, but they arrive
    looking exactly like questions. Three hundred of them is not a list somebody
    works through one row at a time, so without this the honest answer is to give
    up on the list entirely, and then a genuine new hire's rows are lost in it.

    Deliberately *not* automatic. An unmatched identifier is a person nobody has
    added yet just as often as it is a person who left, and the two are
    indistinguishable from here — so the decision is a human's, taken once.
    """
    source = _owned(db, actor, source_id)
    rows = identity.pending(db, source)
    for row in rows:
        identity.ignore(db, row)

    audit.record(
        db,
        actor=actor,
        action="user_identity.ignored_rest",
        request=request,
        name=source.name,
        count=str(len(rows)),
    )
    db.commit()
    return list_identities(source_id, actor=actor, db=db)


def _owned_identity(
    db: DbSession, source: DataSource, identity_id: int
) -> UserIdentity:
    row = db.get(UserIdentity, identity_id)
    if row is None or row.data_source_id != source.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Identifier not found."
        )
    return row
