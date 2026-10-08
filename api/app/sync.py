"""Running one source, and writing what it found.

The orchestration: ask the connector for rows, put each through `mapping`, resolve
its person through `identity`, and upsert a `metric_fact`. One path, so seven
connectors cannot each get the awkward parts subtly wrong.

Two rules decided before any of this was written:

**A human correction wins over a sync.** If somebody hand-fixed a number, the sync
declines to overwrite it and counts a conflict. Anything else makes the corrections
tool theatre — but a correction that permanently contradicts its source is
something an admin should get to see, which is what the count is for.

**A row whose person is unknown waits.** Never auto-created, never dropped. See
`app/identity.py`.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, true as sa_true
from sqlalchemy.orm import Session as DbSession

from app import (
    connectors,
    credentials,
    events,
    identity,
    mapping,
    notifications,
    oauth,
)
from app.models import (
    DataSource,
    MetricDefinition,
    MetricFact,
    Organization,
    SourceMapping,
    SyncRun,
    UserAccount,
)
from app.mapping import MappingError
from app.models.data_source import READ_ONCE
from app.models.metric_fact import VALUE_SCALE

logger = logging.getLogger(__name__)

#: How many consecutive failures back off to what delay.
#:
#: A source whose credentials expired must not be retried every minute forever —
#: that is a log nobody reads and an API somebody rate-limits. Doubling, capped at
#: six hours, so a transient network blip recovers quickly and a genuinely broken
#: source stops shouting.
BACKOFF_MINUTES = (5, 15, 60, 180, 360)

#: How many mapping errors to report before giving up on describing them.
#:
#: A mapping pointed at the wrong column fails on every row, and an error field
#: containing forty thousand identical sentences is not more useful than one
#: containing the first three.
MAX_REPORTED_ERRORS = 3


def due(db: DbSession, *, now: datetime | None = None) -> list[DataSource]:
    """Enabled sources whose next run has arrived.

    `next_run_at IS NULL` counts as due: that is the state a freshly created source
    is in, so connecting one syncs it promptly rather than after an hour of
    apparently doing nothing.

    **A source set to read once is due exactly until it has.** Its schedule is
    not "never" — that would never run at all — it is "once", and the difference
    is whether anything has run yet.

    Archived sources are excluded here as well as being disabled by the act of
    archiving. Belt and braces on purpose: "a removed integration does not run" is
    the property, and leaving it to depend on a second column staying in step is
    how a removed webhook quietly starts importing again.
    """
    now = now or datetime.now(UTC)
    return list(
        db.scalars(
            select(DataSource)
            .where(
                DataSource.enabled.is_(True),
                DataSource.archived_at.is_(None),
                (DataSource.next_run_at.is_(None)) | (DataSource.next_run_at <= now),
                # **A one-off that has run is not due.** This has to be said
                # here rather than by leaving `next_run_at` empty, because an
                # empty next-run means "due now" a line above — that is how a
                # freshly created source syncs promptly instead of idling for an
                # hour. Without this clause, "read once" would read every tick.
                (DataSource.interval_minutes != READ_ONCE)
                | (DataSource.last_run_at.is_(None)),
            )
            .order_by(DataSource.next_run_at.nulls_first(), DataSource.id)
        ).all()
    )


def since_for(db: DbSession, source: DataSource, *, now: datetime) -> datetime:
    """How far back this run should ask for.

    The last **fully clean** run's start, minus nothing — a source that reports a
    deal a minute after it closed would otherwise be missed by a window that
    started when the previous sync did. Overlap is free because the upsert is
    idempotent, which is the whole reason `external_id` exists.

    **`ok` only, deliberately not `partial`.** A `partial` run read rows it did not
    resolve — held for a quarantine question, or skipped on a mapping error — and
    moving the window past them makes those rows unreachable forever. That turns
    quarantine from a safety net into a data-loss mechanism: an admin answers "this
    identifier is Sam", the next sync no longer covers the rows that raised the
    question, and the numbers never appear. Same for the middle of the wizard, where
    a test event arrives before any mapping exists — that run is `partial` too, and
    advancing past it means the event can never become a fact.

    The cost is that an unanswered quarantine pins the window until it is answered
    or ignored, so the read keeps starting from the same point and gets no cheaper.
    That is the right way round: the condition is visible — `partial` on the source,
    a count of waiting identifiers on the page — and re-reading rows we already have
    costs a query, while advancing past them costs the data. There is deliberately
    no silent expiry, because silently giving up on unresolved rows is the bug this
    paragraph exists to describe.

    With no clean run yet, the backfill window. Ninety days by default, asked in the
    wizard rather than assumed, because on a warehouse it is the difference between
    a cheap query and an expensive one.
    """
    last_clean = db.scalar(
        select(func.max(SyncRun.started_at)).where(
            SyncRun.data_source_id == source.id,
            SyncRun.status == "ok",
        )
    )
    if last_clean is not None:
        return last_clean
    return now - timedelta(days=source.backfill_days)


def run(
    db: DbSession,
    org: Organization,
    source: DataSource,
    *,
    trigger: str = "schedule",
    now: datetime | None = None,
) -> SyncRun:
    """Sync one source. Always returns a `SyncRun`, even when it failed.

    Never raises for anything a source can do to us — a bad credential, an
    unreachable host, a mapping pointed at a column that no longer exists. All of
    those are recorded on the run and reported, because a scheduler that dies on
    one bad source stops syncing the good ones too.
    """
    now = now or datetime.now(UTC)
    run_row = SyncRun(
        organization_id=org.id,
        data_source_id=source.id,
        trigger=trigger,
        status="running",
        started_at=now,
    )
    db.add(run_row)
    db.flush()

    try:
        _execute(db, org, source, run_row, now=now)
    except Exception as error:  # noqa: BLE001 — recorded, not propagated
        run_row.status = "failed"
        run_row.error = _describe(error)
        source.failure_count += 1
        _warn_admins(db, org, source, run_row, now=now)
    else:
        # `partial` is its own outcome: rows written *and* rows held back is the
        # normal first-sync result, and calling that "failed" trains people to
        # ignore the word.
        run_row.status = (
            "partial"
            if (run_row.rows_quarantined or run_row.conflicts or run_row.error)
            else "ok"
        )
        source.failure_count = 0

    run_row.finished_at = datetime.now(UTC)
    source.last_run_at = run_row.started_at
    source.last_status = run_row.status
    source.next_run_at = _next_run(source, now=now)
    db.flush()
    return run_row


#: Consecutive failures before anybody is told.
#:
#: **Not the first one.** A warehouse that was mid-resume, a token a second from
#: refresh, a network that blinked — all of them fail once and fix themselves
#: before anybody could have read the message. An alert per blip is an alert
#: nobody reads, and then the real outage arrives in a mailbox people have
#: learned to skim. Three in a row is a thing that is actually broken.
FAILURES_BEFORE_WARNING = 3


def _warn_admins(
    db: DbSession,
    org: Organization,
    source: DataSource,
    run_row: SyncRun,
    *,
    now: datetime,
) -> None:
    """Tell the admins a source has stopped working.

    **Because nothing else did.** A source that starts failing at three in the
    morning showed a red pill on a page nobody had open, and the first anybody
    knew was a leaderboard that had quietly stopped moving — which reads as "the
    team had a slow week", not as "the integration is down". That is the worst
    shape a failure can take: invisible, and easy to explain away.

    Once a day at most, per source, by the notification's own unique index on
    `period_anchor`. A broken thing is worth one reminder a day and no more; the
    alert exists to be noticed, and one per hour is how it stops being.
    """
    if source.failure_count < FAILURES_BEFORE_WARNING:
        return

    admins = list(
        db.scalars(
            select(UserAccount.id).where(
                UserAccount.organization_id == org.id,
                UserAccount.org_role == "admin",
                UserAccount.status == "active",
                UserAccount.hidden_at.is_(None),
            )
        )
    )
    for user_id in admins:
        notifications.emit(
            db,
            org_id=org.id,
            user_id=user_id,
            event=events.SOURCE_FAILING,
            subject_type="data_source",
            subject_id=source.id,
            # One per source per day: the same source failing hourly is one
            # problem, not twenty-four.
            period_anchor=now.date(),
            title=f"{source.name} has stopped importing",
            body=(
                f"{source.failure_count} runs in a row have failed. "
                f"{run_row.error or 'No detail was recorded.'}"
            ),
            link_url=f"/integrations/sources/{source.id}",
        )


def _next_run(source: DataSource, *, now: datetime) -> datetime | None:
    """When to look again — sooner on success, later after repeated failure.

    **Never, for a one-off that has run.** `due()` would read a null as "due
    now", but it already excludes a one-off with a run behind it, so the null
    is only ever read by the things that judge lateness. A date there — which
    used to be "now plus zero minutes" — was already in the past the moment it
    was written, and every one of them called the source overdue (QA-12).
    """
    if source.interval_minutes == READ_ONCE:
        return None
    if source.failure_count == 0:
        return now + timedelta(minutes=source.interval_minutes)
    step = min(source.failure_count, len(BACKOFF_MINUTES)) - 1
    return now + timedelta(minutes=max(BACKOFF_MINUTES[step], source.interval_minutes))


def _describe(error: Exception) -> str:
    """An error an admin can act on.

    `UnknownConnector` gets its own wording because it is not a failure of the
    source at all — it is a row naming a connector this build does not ship, which
    is a deployment question rather than a credential one.
    """
    if isinstance(error, connectors.UnknownConnector):
        return str(error)
    return f"{type(error).__name__}: {error}"[:2000]


def _execute(
    db: DbSession,
    org: Organization,
    source: DataSource,
    run_row: SyncRun,
    *,
    now: datetime,
) -> None:
    connector = connectors.get(source.connector)
    config = connector.config_schema(**oauth.config_for(db, source))
    secrets = connector.credential_schema(
        **oauth.ensure_fresh(db, source, connectors.oauth_of(connector))
    )

    mappings = list(
        db.scalars(
            select(SourceMapping).where(
                SourceMapping.data_source_id == source.id,
                SourceMapping.enabled.is_(True),
            )
        ).all()
    )
    if not mappings:
        # Not an error. A source can legitimately exist for a while with no
        # mapping — that is the middle of the wizard — and a red failure for it
        # would be crying wolf.
        run_row.error = "No mappings are configured, so nothing was imported."
        return

    since = since_for(db, source, now=now)
    problems: list[str] = []

    # Fetched once and reused across mappings. A closed deal is both a "deals won"
    # count and a "revenue" amount, and asking the provider twice for the same rows
    # doubles the rate-limit cost to produce identical data.
    local = connectors.LocalContext(db=db, source_id=source.id)

    # Collected one at a time rather than with `list()`, so a connector that stops
    # early keeps everything it did read. `Truncated` is raised *after* the last
    # row, and `list()` would discard the whole generator's output along with it.
    rows: list[connectors.SourceRow] = []
    try:
        for row in connector.fetch(config, secrets, since, local=local):
            rows.append(row)
    except connectors.Truncated as limit:
        # Recorded, which makes the run `partial` — and a partial run does not
        # advance the watermark, so the rows this stopped short of are read again
        # next time rather than skipped forever.
        problems.append(str(limit))
    run_row.rows_read = len(rows)

    # **Whether absence means deleted.** Only for a connector that hands back the
    # whole source every time, and only when nothing has already gone wrong: a
    # truncated read is exactly the case where "missing" must not mean "gone".
    whole = connectors.reads_everything(connector, config) and not problems

    for source_mapping in mappings:
        metric = db.get(MetricDefinition, source_mapping.metric_definition_id)
        if metric is None or metric.archived_at is not None:
            # A metric archived after the mapping was made. Skipped rather than
            # failed: the admin retired the metric deliberately, and the sync
            # should not start failing because of a decision they made on purpose.
            continue

        # Which rows this pass actually stood behind. Per mapping, because the
        # filters are per mapping: one sheet can feed a won-only metric and an
        # everything metric, and a row belongs to one and not the other.
        kept: set[str] = set()
        before = len(problems)

        for row in rows:
            try:
                _apply(
                    db, org, source, source_mapping, metric, row, run_row,
                    now=now, kept=kept if whole else None,
                )
            except MappingError as error:
                run_row.rows_skipped += 1
                if len(problems) < MAX_REPORTED_ERRORS:
                    problems.append(str(error))

        # **Only when this mapping had a clean pass.** A row that raised a
        # MappingError was read and not accounted for, so treating its absence
        # from `kept` as a deletion would withdraw a real fact over a typo.
        if whole and len(problems) == before:
            _withdraw_missing(db, org, source, metric, kept, run_row)

    if problems:
        run_row.error = " ".join(problems)


def _apply(
    db: DbSession,
    org: Organization,
    source: DataSource,
    source_mapping: SourceMapping,
    metric: MetricDefinition,
    row: connectors.SourceRow,
    run_row: SyncRun,
    *,
    now: datetime,
    kept: set[str] | None = None,
) -> None:
    """Turn one row into a fact, and note that this pass stood behind it.

    `kept` collects the external ids this mapping wrote or confirmed, for
    `_withdraw_missing`. `None` switches that off — which is every connector
    reading a window rather than a whole source, and every run that already hit
    a problem.

    **A row filtered out is deliberately not kept.** That is what takes a deal
    moving from *Closed Won* back to *Negotiation* off the board: the sheet still
    has the row, this metric no longer claims it.
    """
    values = row.values

    if not mapping.matches(values, source_mapping.filters or []):
        run_row.rows_skipped += 1
        return

    who = identity.resolve(db, source, values.get(source_mapping.subject_field), now=now)
    if who.outcome == identity.IGNORED:
        run_row.rows_skipped += 1
        return
    if who.outcome == identity.QUARANTINED:
        run_row.rows_quarantined += 1
        return

    value = mapping.value_of(
        values, source_mapping.value_field, source_mapping.multiplier
    )
    when = mapping.occurred_at(
        values,
        source_mapping.occurred_at_field,
        source_timezone=source.timezone,
        org_timezone=org.timezone,
    )
    external_id = _identify(row, values, source_mapping, on=now.date())

    # Noted before the write, so a row confirmed unchanged — which `_upsert`
    # returns early on, deliberately, rather than counting as a write — still
    # counts as one this pass stood behind.
    if kept is not None:
        kept.add(external_id)

    _upsert(
        db,
        org,
        source,
        metric,
        now=now,
        user_id=who.user_id,
        value=value,
        occurred_at=when,
        external_id=external_id,
        run_row=run_row,
    )


def _identify(
    row: connectors.SourceRow,
    values: dict,
    source_mapping: SourceMapping,
    *,
    on: date | None = None,
) -> str:
    """The id that makes re-reading this row harmless, or a refusal.

    The mapping's column first, then whatever the connector supplied — a webhook
    knows its own delivery id, a database row does not.

    **Nothing is written without one, and that is a change of policy worth the
    words.** `_upsert` can only recognise a row it has seen before by its
    `external_id`; without one it inserts, so every re-read appends a second copy
    of the same measurement.

    That was documented as a known cost and it is much worse than it looked, because
    of how it combines with the window. A `partial` run does not advance the
    watermark — deliberately, so rows held for a quarantine question can be
    re-read — which means one unanswered question makes the source re-read the same
    window on *every* pass. With no external id, every pass then appends the good
    rows again: an hourly source quietly adds twenty-four phantom measurements a day
    to a leaderboard, and both halves of the cause are individually correct.

    So a row with no id is a configuration error, reported per row like any other,
    with a message naming the fix. Loud and stopped beats silent and wrong — and it
    is what a warehouse tool does too: Fivetran and Airbyte both require a primary
    key for anything but append-only loading.
    """
    #: **Snapshotting makes the day part of the row's identity.** Without it a
    #: totals view overwrites yesterday on every read and no history survives;
    #: with it each day is its own fact and a week is the sum of seven. See
    #: `SourceMapping.snapshot_daily`, which is opt-in for the reason set out
    #: there.
    suffix = f"@{on.isoformat()}" if source_mapping.snapshot_daily and on else ""

    named = mapping.external_id_of(values, source_mapping.external_id_field)
    if named:
        return named + suffix
    if row.external_id:
        return row.external_id + suffix

    if source_mapping.external_id_field:
        raise MappingError(
            f"{source_mapping.external_id_field!r} was empty on this row, so there "
            "is nothing to recognise it by next time. Every column named as the "
            "row's id has to have a value."
        )
    raise MappingError(
        "This mapping does not say which column is the row's own id, and this "
        "source does not provide one. Without it the same row is imported again "
        "every time it is read. Pick the column holding the record's id — a "
        "primary key, a ticket number, a deal id."
    )


def _upsert(
    db: DbSession,
    org: Organization,
    source: DataSource,
    metric: MetricDefinition,
    *,
    user_id: int,
    value,
    occurred_at: datetime | None,
    now: datetime,
    external_id: str | None,
    run_row: SyncRun,
) -> None:
    """Write the fact, or leave a corrected one alone.

    **`occurred_at=None` means the source has no date**, and the fact is dated by
    when its number last changed. This is the only place that can decide it,
    because it is the only place that can see the previous value.

    Looked up rather than `ON CONFLICT DO UPDATE`, and that is a deliberate cost.
    The decision here depends on a column of the *existing* row — has a human
    touched it — and expressing "update unless corrected_at is set" as a conflict
    clause would work but would give up the conflict *count*, which is the thing
    that makes the rule visible instead of silent.

    A row with no external id cannot be matched, so it is inserted. That is the
    honest behaviour and it is why a source without a stable row id is a worse
    position to be in: every sync appends rather than updates, and re-reading the
    same window duplicates it.
    """
    if metric.aggregation == "ratio":
        # A derived metric has no facts of its own; a mapping to one predates
        # the refusal that now stops it being made. Nothing is written.
        return None

    existing = None
    if external_id is not None:
        existing = db.scalar(
            select(MetricFact).where(
                MetricFact.organization_id == org.id,
                MetricFact.data_source_id == source.id,
                MetricFact.metric_definition_id == metric.id,
                MetricFact.external_id == external_id,
            )
        )

    # **Dated by when the number last changed.** First import counts as a change;
    # a row that stops moving keeps the date it last moved on.
    #
    # One rule, two shapes. A deal row is written once and never touched again, so
    # it keeps the day it first arrived — which is within a sync interval of when
    # it really happened, and is the best anybody can do from a source that does
    # not say. A running total like `sales_today` moves to today the moment it goes
    # from 1 to 2, and stays on today however many times it is read after that.
    #
    # Deliberately *not* "the time of the last read": that would drag every fact
    # forward on every sync, so nothing would ever age out of a period and a person
    # who stopped selling in March would still be on April's leaderboard.
    if occurred_at is None:
        if existing is None:
            occurred_at = now
        elif existing.value != value or existing.subject_user_id != user_id:
            occurred_at = now
        else:
            occurred_at = existing.occurred_at

    if existing is None:
        db.add(
            MetricFact(
                organization_id=org.id,
                metric_definition_id=metric.id,
                subject_user_id=user_id,
                subject_team_id=_team_of(db, user_id),
                subject_office_id=_office_of(db, user_id),
                value=value,
                occurred_at=occurred_at,
                source_type="connector",
                data_source_id=source.id,
                external_id=external_id,
            )
        )
        run_row.rows_written += 1
        db.flush()
        return

    if existing.corrected_at is not None:
        # **A human correction wins.** Counted so somebody can see that this
        # source and this person disagree, permanently, about one number.
        run_row.conflicts += 1
        return

    unchanged = (
        existing.value == value
        and existing.occurred_at == occurred_at
        and existing.subject_user_id == user_id
    )
    if unchanged:
        # Re-reading the same window is the normal case, not a write. Counting it
        # as one would make every sync look busy and hide the runs that did
        # something.
        return

    existing.value = value
    existing.occurred_at = occurred_at
    existing.subject_user_id = user_id
    existing.subject_team_id = _team_of(db, user_id)
    existing.subject_office_id = _office_of(db, user_id)
    run_row.rows_written += 1
    db.flush()


def _team_of(db: DbSession, user_id: int) -> int | None:
    """The team to stamp on the fact.

    A snapshot, not a lookup at read time — the same reasoning as everywhere else
    in this product. A win belongs to the team somebody was on when they earned it,
    and a transfer must not move last month's numbers to a different leaderboard.
    """
    return db.scalar(select(UserAccount.team_id).where(UserAccount.id == user_id))


def _office_of(db: DbSession, user_id: int) -> int | None:
    from app.models import Team

    team_id = _team_of(db, user_id)
    if team_id is None:
        return None
    return db.scalar(select(Team.office_id).where(Team.id == team_id))


#: How many rows a preview shows.
#:
#: Ten is enough to recognise whether a mapping is right and few enough that the
#: wizard answers in a moment. A mapping error surfaces in three seconds instead of
#: after a sync has written forty thousand wrong rows.
PREVIEW_ROWS = 10


@dataclass
class PreviewRow:
    """One source row, as the fact it would become.

    Carries the outcome rather than only the happy path, because the useful part of
    a preview is the rows that *would not* work: the person nobody recognises, the
    column that is not a number, the filter excluding more than the admin expected.
    """

    #: `written`, `quarantined`, `skipped`, or `error`.
    outcome: str
    #: What the source sent, so the admin can see which row this was.
    source_values: dict
    subject_name: str | None = None
    value: Decimal | None = None
    occurred_at: datetime | None = None
    external_id: str | None = None
    detail: str | None = None


def preview(
    db: DbSession,
    org: Organization,
    source: DataSource,
    source_mapping: SourceMapping,
    *,
    limit: int = PREVIEW_ROWS,
    now: datetime | None = None,
) -> list[PreviewRow]:
    """What this mapping would do, without doing any of it.

    **Nothing is written and nothing is recorded** — not a fact, not a quarantine
    question, not a `sync_run`. A preview that created a queue as a side effect of
    being looked at would be a nasty surprise, which is why `identity.resolve` grew
    a `record=False`.

    Goes through the same `mapping` calls the real sync does, so what an admin sees
    here is what they will get. A separate "preview formatter" would be a second
    implementation of the interesting logic, and the two would agree right up until
    somebody fixed a bug in one of them.

    **Deliberately not the sync's window.** `since_for` answers "what have I not
    dealt with yet", which for a healthy source is a few minutes and for a freshly
    synced one is nothing at all — so a preview built on it shows an empty table
    exactly when somebody is trying to work out why their mapping is wrong. This
    asks over the source's own backfill window instead, and it never consults run
    history, so previewing gives the same answer before and after a sync.

    **The newest rows, not the oldest.** `fetch` yields oldest-first, so taking the
    first ten of ninety days would show an admin the beginning of their history when
    what they want is the test event they sent thirty seconds ago. Keeping a tail
    means draining the window; that is a deliberate button press rather than
    anything on a timer, and if a connector ever needs this to be cheap the fix is a
    "latest N" hint in the protocol rather than a second code path here.
    """
    now = now or datetime.now(UTC)
    connector = connectors.get(source.connector)
    config = connector.config_schema(**oauth.config_for(db, source))
    secrets = connector.credential_schema(
        **oauth.ensure_fresh(db, source, connectors.oauth_of(connector))
    )
    local = connectors.LocalContext(db=db, source_id=source.id)

    window = now - timedelta(days=source.backfill_days)
    latest = deque(
        connector.fetch(config, secrets, window, local=local), maxlen=limit
    )

    out: list[PreviewRow] = []
    for row in latest:
        values = row.values
        if not mapping.matches(values, source_mapping.filters or []):
            out.append(
                PreviewRow(
                    outcome="skipped",
                    source_values=values,
                    detail="Excluded by the filters.",
                )
            )
            continue

        who = identity.resolve(
            db, source, values.get(source_mapping.subject_field), now=now, record=False
        )
        if who.outcome == identity.IGNORED:
            out.append(
                PreviewRow(
                    outcome="skipped",
                    source_values=values,
                    detail="This identifier is set to be ignored.",
                )
            )
            continue

        try:
            value = _as_stored(
                mapping.value_of(
                    values, source_mapping.value_field, source_mapping.multiplier
                )
            )
            when = mapping.occurred_at(
                values,
                source_mapping.occurred_at_field,
                source_timezone=source.timezone,
                org_timezone=org.timezone,
            )
            # With no date column the real date is decided against the stored
            # fact, which a preview has not written. `now` is what a row imported
            # this moment would get, and showing a blank instead would read as a
            # mapping that is not finished.
            if when is None:
                when = now
        except MappingError as error:
            out.append(
                PreviewRow(outcome="error", source_values=values, detail=str(error))
            )
            continue

        # Through the same check the real sync uses, so the preview cannot promise
        # an import that would then be refused — which is the whole reason preview
        # goes through the `mapping` calls rather than reimplementing them.
        try:
            external_id = _identify(row, values, source_mapping)
        except MappingError as error:
            out.append(
                PreviewRow(outcome="error", source_values=values, detail=str(error))
            )
            continue

        if who.outcome == identity.QUARANTINED:
            out.append(
                PreviewRow(
                    outcome="quarantined",
                    source_values=values,
                    value=value,
                    occurred_at=when,
                    external_id=external_id,
                    detail=(
                        f"Nobody matches "
                        f"{values.get(source_mapping.subject_field)!r} yet."
                    ),
                )
            )
            continue

        person = db.get(UserAccount, who.user_id)
        out.append(
            PreviewRow(
                outcome="written",
                source_values=values,
                subject_name=person.full_name if person else None,
                value=value,
                occurred_at=when,
                external_id=external_id,
            )
        )
    return out


def _as_stored(value: Decimal) -> Decimal:
    """The value as the column will actually hold it.

    A six-decimal-place multiplier against a four-decimal-place column produces
    `1250.00000000` in Python and `1250.0000` in the database. Preview exists to be
    believed, so it shows the second one.
    """
    return value.quantize(Decimal(1).scaleb(-VALUE_SCALE), rounding=ROUND_HALF_UP)


#: How long a half-built source is kept before it is swept away.
#:
#: Long enough that somebody who was interrupted can come back tomorrow and pick up
#: where they left off; short enough that abandoned clicks do not accumulate. A
#: draft has no credentials worth keeping and has imported nothing, so there is
#: nothing here to lose.
DRAFT_TTL = timedelta(hours=24)


def sweep_drafts(db: DbSession, *, now: datetime | None = None) -> int:
    """Delete connect flows nobody finished. Returns how many went.

    A draft is a source with `activated_at IS NULL` — setup was started and never
    switched on. **Never touches a source that was once activated**, whatever state
    it is in now: a paused source, a restored one and one whose only mapping was
    deleted all look like a draft from outside, and all three are somebody's real
    source. That distinction is the entire reason `activated_at` is a column
    rather than a guess.

    Facts are checked as well as the flag, and belt-and-braces on purpose — a
    delete that hit anything with history would be refused by the foreign key
    anyway, but discovering that through an integrity error at three in the morning
    is worse than not attempting it.
    """
    now = now or datetime.now(UTC)
    stale = db.scalars(
        select(DataSource).where(
            DataSource.activated_at.is_(None),
            DataSource.created_at < now - DRAFT_TTL,
        )
    ).all()

    gone = 0
    for source in stale:
        written = db.scalar(
            select(func.count())
            .select_from(MetricFact)
            .where(MetricFact.data_source_id == source.id)
        )
        if written:
            continue
        db.delete(source)
        gone += 1
    db.flush()
    return gone


def run_due(db: DbSession, *, now: datetime | None = None) -> dict[str, int]:
    """Sync every source that is due, and tidy away abandoned drafts.

    One source failing does not stop the others: each `run` records its own outcome
    and returns rather than raising.
    """
    now = now or datetime.now(UTC)
    orgs = {o.id: o for o in db.scalars(select(Organization)).all()}
    tally = {"sources": 0, "written": 0, "quarantined": 0, "conflicts": 0, "failed": 0}

    for source in due(db, now=now):
        org = orgs.get(source.organization_id)
        if org is None:
            continue
        outcome = run(db, org, source, trigger="schedule", now=now)
        tally["sources"] += 1
        tally["written"] += outcome.rows_written
        tally["quarantined"] += outcome.rows_quarantined
        tally["conflicts"] += outcome.conflicts
        if outcome.status == "failed":
            tally["failed"] += 1

    # After the syncs, not before: a draft finished in the last minute should be
    # synced on this pass rather than swept on it.
    tally["drafts_swept"] = sweep_drafts(db, now=now)
    return tally


def _withdraw_missing(
    db: DbSession,
    org: Organization,
    source: DataSource,
    metric: MetricDefinition,
    kept: set[str],
    run_row: SyncRun,
) -> None:
    """Remove facts whose row is no longer in the source.

    **One rule: for a source read whole every time, the source is the truth.**
    The alternative was "the source is the truth, except deletions, and except
    rows that stop matching a filter" — two exceptions, each of them a number on
    a leaderboard permanently disagreeing with the spreadsheet it came from. A
    deal deleted in Excel kept counting; a deal moved back out of *Closed Won*
    kept counting.

    Three guards, and every one of them is load-bearing:

    **The connector must say it reads everything.** Absence only means deleted
    when presence was guaranteed. See `connectors.reads_everything`.

    **The run must be clean.** A truncated read or a mapping error means rows
    were not accounted for, and withdrawing on that basis deletes real data over
    a typo. Checked by the caller before this is reached.

    **A corrected fact is never touched.** A human who edited a number already
    beats the source in `_upsert`; the same person should not lose their edit
    because somebody tidied a spreadsheet. Manual facts are excluded for the same
    reason — they were never this source's to withdraw, and the
    `data_source_id` filter already keeps out every other source's.

    Deleted rather than flagged. A flag would need honouring in `aggregate`,
    `dashboard`, `competitions`, `notifications` and `csv_export`, and a filter
    applied in four places out of five is the bug this codebase keeps finding.
    """
    stale = db.scalars(
        select(MetricFact).where(
            MetricFact.organization_id == org.id,
            MetricFact.data_source_id == source.id,
            MetricFact.metric_definition_id == metric.id,
            MetricFact.corrected_at.is_(None),
            MetricFact.external_id.is_not(None),
            MetricFact.external_id.not_in(kept) if kept else sa_true(),
        )
    ).all()

    for fact in stale:
        db.delete(fact)
    if stale:
        run_row.rows_removed += len(stale)
        db.flush()
        logger.info(
            "sync: withdrew %d fact(s) for source %s metric %s",
            len(stale),
            source.id,
            metric.id,
        )
