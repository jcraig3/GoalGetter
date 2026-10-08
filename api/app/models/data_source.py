from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

#: How often a source may be polled, in minutes.
#:
#: An hour by default, matching the job loop it rides on. A warehouse can be
#: nightly and a CRM every fifteen minutes; both are just numbers here rather
#: than cron expressions, because "every so often" is the only schedule any of
#: this needs and a cron parser is a language to maintain — the same argument
#: `main.py` makes for not using APScheduler.
DEFAULT_INTERVAL_MINUTES = 60
MIN_INTERVAL_MINUTES = 5

#: `interval_minutes` for a source that reads once and stops.
#:
#: **What a first test wants.** Creating a source otherwise starts a schedule
#: immediately, whether or not anybody has confirmed the numbers are right —
#: free against a spreadsheet, billed by the second against a warehouse.
#:
#: Distinct from pausing, which says something different: paused is a state
#: somebody chose to stop, and a one-off that has finished is not stopped, it is
#: done. See `sync.due`, which is where the difference is enforced.
READ_ONCE = 0

#: How far back a first sync reaches.
#:
#: Ninety days covers a quarter, which is the longest period a goal can span
#: short of a year. Asked rather than assumed in the wizard, because on a
#: warehouse it is the difference between a cheap query and an expensive one.
DEFAULT_BACKFILL_DAYS = 90

#: What a sync did, on the source itself, so a list of sources can show it
#: without joining every `sync_run`.
LAST_STATUSES = ("ok", "partial", "failed")


class DataSource(Base, TimestampMixin):
    """One connected place data comes from.

    A source is *where* the numbers come from; a `SourceMapping` says which of
    its columns become which metric. Separated because one connected account
    routinely feeds several metrics — a closed deal is both "deals won" and
    "revenue" — and re-authenticating should not mean re-describing the mapping.

    See documentation/15-data-integrations.md.
    """

    __tablename__ = "data_source"
    __table_args__ = (
        CheckConstraint(
            f"interval_minutes = 0 OR interval_minutes >= {MIN_INTERVAL_MINUTES}",
            name="interval_sane",
        ),
        CheckConstraint("backfill_days BETWEEN 0 AND 3650", name="backfill_sane"),
        CheckConstraint(
            "last_status IS NULL OR last_status IN ('ok', 'partial', 'failed')",
            name="last_status_valid",
        ),
        # The scheduler's access path: "which enabled sources are due?"
        Index("ix_data_source_due", "enabled", "next_run_at"),
        Index("ix_data_source_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )

    #: What an admin called it — "Salesforce – Production". Their words, because
    #: two connections to the same provider are otherwise indistinguishable.
    name: Mapped[str] = mapped_column(String(120))

    #: Which connector drives it, matching a key in the registry.
    #:
    #: A string rather than an enum: connectors are added by shipping code, and
    #: a database enum would mean a migration to release one. An unknown key is
    #: handled the way an unknown screen kind is — skipped, loudly, rather than
    #: crashing the scheduler.
    connector: Mapped[str] = mapped_column(String(40))

    #: Off is not the same as gone. A source is disabled while credentials are
    #: being fixed, and deleting one is refused once it has written facts — the
    #: same rule as a metric that has been measured.
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")

    #: Connector-specific, non-secret settings: which sheet, which object, which
    #: filters. JSONB because every connector needs a different shape and the
    #: alternative is thirty nullable columns that only one connector each uses.
    #: Secrets never live here — see `ConnectorCredential`.
    config: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    interval_minutes: Mapped[int] = mapped_column(
        Integer, server_default=str(DEFAULT_INTERVAL_MINUTES)
    )
    backfill_days: Mapped[int] = mapped_column(
        Integer, server_default=str(DEFAULT_BACKFILL_DAYS)
    )

    #: Which timezone a bare date from this source means.
    #:
    #: NULL means the organization's own. It matters because period boundaries
    #: are resolved in the organization's timezone, so a spreadsheet exported in
    #: Sydney and read in Phoenix would land a deal in the wrong day — and for a
    #: daily goal, the wrong period entirely.
    timezone: Mapped[str | None] = mapped_column(String(64))

    #: When the scheduler should next look. NULL means "as soon as possible",
    #: which is the state a newly created source is in.
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))

    #: Consecutive failures, for backoff.
    #:
    #: Reset to zero by any success. A source whose credentials expired should
    #: not be retried every minute forever — see `app/sync.py` for the curve.
    failure_count: Mapped[int] = mapped_column(Integer, server_default="0")

    #: When setup was finished — the moment somebody switched it on.
    #:
    #: **NULL means a draft: the connect flow was started and never completed.**
    #: A draft is hidden from the list and swept away after a day, because a
    #: half-built source nobody came back to is clutter rather than information.
    #:
    #: An explicit column rather than an inference, and the inference is the
    #: reason why. "No credentials and no enabled mapping" describes a draft — and
    #: describes a *restored* source equally well, which is a real source somebody
    #: wants back and must not be swept. The two states look identical from
    #: outside and behave completely differently, so they get told apart by a fact
    #: rather than by a guess.
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Removed, but not gone.
    #:
    #: **The state that lets an integration be taken away without taking its
    #: numbers away.** Facts point at this row through `data_source_id`, and a
    #: leaderboard for last quarter must still be able to answer "where did this
    #: come from" — so the row survives, hidden, rather than being deleted. The
    #: same trade a measured metric makes when it is archived.
    #:
    #: Archiving forgets the credential and disables the source, so a removed
    #: integration genuinely stops working: a webhook endpoint that still
    #: accepted deliveries after being removed would be a removal in name only.
    #: Restoring brings back the row and its history, not its credential.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="SET NULL")
    )

    def __repr__(self) -> str:
        return f"<DataSource {self.name!r} {self.connector}>"


class ConnectorCredential(Base, TimestampMixin):
    """The secrets for one source, encrypted.

    Its own table rather than columns on `data_source` for two reasons. A list
    of sources is read constantly — every scheduler pass, every page load — and
    none of those reads want the ciphertext anywhere near them. And a token
    refresh writes here on its own schedule, so keeping it separate means a
    refresh does not touch the row the scheduler is reading.

    **Encrypted with the same Fernet key as the SSO client secret** — see
    `app/crypto.py`. Fernet because it is authenticated: a tampered ciphertext
    fails to decrypt rather than silently producing garbage that gets sent to a
    provider as a bearer token.
    """

    __tablename__ = "connector_credential"
    __table_args__ = (
        # One set of secrets per source. A refresh replaces the row's contents
        # rather than appending, so there is never a question of which token is
        # current.
        Index("uq_connector_credential_source", "data_source_id", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    data_source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("data_source.id", ondelete="CASCADE")
    )

    #: The whole secret bundle as one encrypted blob.
    #:
    #: One column rather than `access_token_encrypted`, `refresh_token_encrypted`
    #: and so on: every connector needs a different set — a webhook has a shared
    #: secret, OAuth has two tokens and an expiry, a database has a password —
    #: and a column per possibility is a schema that grows with the connector
    #: list. Decrypts to a dict.
    secrets_encrypted: Mapped[str] = mapped_column(String(8000))

    #: When the access token expires, in the clear.
    #:
    #: Deliberately not inside the blob: the scheduler has to ask "does this
    #: need refreshing before I use it?" and decrypting every credential on
    #: every pass to answer that would be both slow and needless exposure.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<ConnectorCredential source={self.data_source_id}>"


#: What set a sync going.
TRIGGERS = ("schedule", "manual", "webhook")

#: How it ended. `partial` is its own outcome on purpose — rows written *and*
#: rows quarantined is the normal first-sync result, and calling that "failed"
#: would train people to ignore the word.
SYNC_STATUSES = ("running", "ok", "partial", "failed")


class SyncRun(Base):
    """One execution of one source, and what it did.

    The record that answers "why is this leaderboard stale?", which is the
    question this table exists for. Counts rather than row-level detail: a sync
    reading forty thousand rows should not write forty thousand log rows to
    describe it.
    """

    __tablename__ = "sync_run"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'ok', 'partial', 'failed')", name="status_valid"
        ),
        CheckConstraint(
            "trigger IN ('schedule', 'manual', 'webhook')", name="trigger_valid"
        ),
        # "The last few runs of this source", which is every read this table has.
        Index("ix_sync_run_source_time", "data_source_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    data_source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("data_source.id", ondelete="CASCADE")
    )

    trigger: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="running")

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rows_read: Mapped[int] = mapped_column(Integer, server_default="0")
    rows_written: Mapped[int] = mapped_column(Integer, server_default="0")
    #: Held back because nobody matched the row's person. Not an error — see
    #: `UserIdentity`.
    rows_quarantined: Mapped[int] = mapped_column(Integer, server_default="0")
    #: Filtered out by the mapping, or belonging to an ignored identifier.
    rows_skipped: Mapped[int] = mapped_column(Integer, server_default="0")

    #: Rows this sync declined to overwrite because a person had corrected them.
    #:
    #: Counted and surfaced rather than silently skipped. **A human correction
    #: wins over a sync** — otherwise the corrections tool is theatre — but a
    #: correction that permanently contradicts the source is something somebody
    #: should get to see.
    conflicts: Mapped[int] = mapped_column(Integer, server_default="0")

    #: Facts withdrawn because the source no longer contains their row.
    #:
    #: Only ever non-zero for a connector that re-reads everything — see
    #: `Connector.reads_everything`. Its own counter rather than folded into
    #: `rows_written`, because a deletion is not a write and a number going down
    #: is the thing somebody wants to see rather than infer.
    rows_removed: Mapped[int] = mapped_column(Integer, server_default="0")

    #: Why it failed, in words an admin can act on. NULL when it did not.
    error: Mapped[str | None] = mapped_column(String(2000))

    def __repr__(self) -> str:
        return f"<SyncRun source={self.data_source_id} {self.status}>"


class UserIdentity(Base, TimestampMixin):
    """Who a source's name for a person refers to.

    A CRM row says the owner is `pparker@acme.com`, or `0051x000ABCdef`. A fact
    needs a `subject_user_id`. This is the mapping between the two.

    **Unmatched rows are quarantined, never auto-created.** A CRM is full of
    things that are not your salespeople: service accounts, ex-employees who
    still own old records, contractors, duplicates from a migration.
    Auto-creating an account for each would put people who never signed in onto
    leaderboards, with no team and no office, and into every goal and competition
    picker. Quarantining loses nothing and asks once — mapping an identifier
    releases the rows already held *and* matches every future row automatically.

    Dropping unmatched rows silently was the third option and the worst: real
    numbers disappear and somebody notices months later that their deals never
    counted.
    """

    __tablename__ = "user_identity"
    __table_args__ = (
        # One decision per identifier per source. Provider ids are only unique
        # within the system that issued them, so the source has to be part of
        # the key.
        Index(
            "uq_user_identity_source_external",
            "data_source_id",
            "external_identifier",
            unique=True,
        ),
        # Exactly one outcome: mapped to somebody, or deliberately ignored.
        # Neither means it is still waiting, which is what the quarantine list
        # reads. Both would be a contradiction.
        CheckConstraint(
            "NOT (user_id IS NOT NULL AND ignored)", name="mapped_or_ignored"
        ),
        Index("ix_user_identity_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    data_source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("data_source.id", ondelete="CASCADE")
    )

    #: What the source calls them — an email, a provider user id, a login.
    #: Stored exactly as it arrived, and compared case-insensitively for emails
    #: by `app/identity.py`.
    external_identifier: Mapped[str] = mapped_column(String(320))

    #: Who that is. NULL and not ignored means "still waiting to be told".
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("user_account.id", ondelete="CASCADE")
    )

    #: "Never mind this one." For the `Integration User` a CRM owns half its
    #: records with — without this, the quarantine list asks about it forever.
    ignored: Mapped[bool] = mapped_column(Boolean, server_default="false")

    #: How many rows are waiting on this decision, so the list can lead with the
    #: one that matters. Maintained by the sync rather than counted, because the
    #: rows themselves are not stored — quarantined rows are re-read next sync.
    pending_rows: Mapped[int] = mapped_column(Integer, server_default="0")

    #: When a row last arrived under this identifier. An identifier nothing has
    #: referenced for months is probably an ex-employee, which is useful context
    #: when deciding.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        state = "ignored" if self.ignored else (self.user_id or "unmapped")
        return f"<UserIdentity {self.external_identifier!r} {state}>"


class SourceMapping(Base, TimestampMixin):
    """Which of a source's columns become which metric.

    Separate from `data_source` because one connected account routinely feeds
    several metrics: a closed deal is both a "deals won" count and a "revenue"
    amount. Two mappings over the same source, and re-authenticating the account
    does not disturb either.

    **Direct mapping plus filters, and a multiplier — not an expression
    language.** An expression field (`Amount * 0.7`) is a parser, a safe
    evaluator, error messages for typos, and a small language to document and
    maintain forever. The real cases are money stored in cents, a commission
    percentage, and unit conversion — all of which one number covers. If
    something genuinely needs more, we will know its exact shape instead of
    guessing at it now.
    """

    __tablename__ = "source_mapping"
    __table_args__ = (
        CheckConstraint("multiplier <> 0", name="multiplier_not_zero"),
        # One mapping per source per metric. Two would be two ways to compute the
        # same number from the same place, and the external ids would collide in
        # `metric_fact` anyway.
        Index(
            "uq_source_mapping_source_metric",
            "data_source_id",
            "metric_definition_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    data_source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("data_source.id", ondelete="CASCADE")
    )
    metric_definition_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("metric_definition.id", ondelete="CASCADE")
    )

    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")

    #: The column holding the number.
    #:
    #: NULL means **count the row as one**, which is how a "deals won" metric
    #: works — the fact that a row exists *is* the measurement. Without this,
    #: every count metric would need a column of literal 1s in the source.
    value_field: Mapped[str | None] = mapped_column(String(200))

    #: The column holding when it happened. **Optional**, and empty is a real
    #: answer rather than an omission.
    #:
    #: **Plenty of sources have no date to give.** A pre-aggregated view — one row
    #: per person, a number that moves — is the shape every leaderboard tool that
    #: came before this one asks for, so it is the shape a lot of warehouses
    #: already hold. Refusing it meant telling somebody to go and write SQL that
    #: invents a date, which they would get wrong in a way nothing here could see.
    #:
    #: Empty means **the fact is dated by when its number last changed** — first
    #: import counts as a change, and a row that stops moving keeps the date it
    #: last moved on. That single rule covers both shapes: a deal row, written once
    #: and never touched again, keeps the day it first arrived; a running total
    #: like `sales_today` moves to today the moment it goes from 1 to 2, and stays
    #: on today for the rest of the day. See `sync._upsert`, which is where the
    #: decision actually lives, because it is the only place that can see the
    #: previous value.
    occurred_at_field: Mapped[str | None] = mapped_column(String(200))

    #: Required: a fact with no subject cannot be put on a leaderboard.
    subject_field: Mapped[str] = mapped_column(String(200))

    #: The column holding the source's own stable id for the row.
    #:
    #: This is what makes a sync idempotent: re-reading yesterday's deals writes
    #: nothing new because the ids already exist. A source with no such column
    #: can still be mapped — see `app/sync.py` for the synthesised fallback and
    #: why it is a worse position to be in.
    external_id_field: Mapped[str | None] = mapped_column(String(200))

    #: `[{"field": "Stage", "op": "eq", "value": "Closed Won"}, …]`
    #:
    #: Valid operators are `mapping.FILTER_OPS` — kept there rather than here,
    #: beside the code that enforces them, so the list and the implementation
    #: cannot drift.
    #:
    #: All must pass. AND rather than a boolean tree, because "closed won deals
    #: in the enterprise pipeline" is every real filter anyone has described, and
    #: OR groups are the first step towards the language this deliberately is not.
    filters: Mapped[list] = mapped_column(JSONB, server_default="[]")

    #: Keep one fact per row **per day**, instead of one fact per row.
    #:
    #: **The only way to get history out of a source that has none.** A
    #: pre-aggregated view holds one row per person and a number that moves —
    #: `sales_today` is 3 this afternoon and 1 tomorrow morning. Keyed by the
    #: person alone, tomorrow's read overwrites today's and the week is
    #: unrecoverable; every leaderboard can then only ever show the current
    #: figure, which is precisely the limitation of the tools this data came
    #: from.
    #:
    #: With this on, the row's id carries the date, so each day becomes its own
    #: fact and a week is the sum of seven. One metric then serves every period —
    #: today, this week, this month — from a single column, and the separate
    #: `_week` and `_month` columns such a view carries stop being needed.
    #:
    #: **Off by default, and opt-in rather than inferred.** For a source with one
    #: row per *event* this would be actively wrong: a deal row keyed by deal id
    #: plus the date becomes a new deal every day, and one sale turns into thirty.
    #: Nothing in the data distinguishes the two shapes reliably, and the cost of
    #: guessing wrong is a leaderboard inflated by a factor of the days elapsed.
    snapshot_daily: Mapped[bool] = mapped_column(Boolean, server_default="false")

    #: Scale the value by this. `0.01` for money stored in cents, `0.7` for a
    #: commission share. One, meaning unchanged, by default.
    multiplier: Mapped[Decimal] = mapped_column(
        Numeric(12, 6), server_default="1"
    )

    def __repr__(self) -> str:
        return f"<SourceMapping source={self.data_source_id} metric={self.metric_definition_id}>"


class WebhookEvent(Base):
    """One payload somebody posted at us, parked until it is processed.

    **A webhook pushes; the connector protocol pulls.** Reconciled here rather
    than by special-casing the pipeline: the endpoint's whole job is to accept a
    payload and write it down, and the webhook connector's `fetch` reads from this
    table. Everything after that — filters, identity resolution, the correction
    rule — is the same code every other connector goes through, which is the point.
    Processing inline would have let a webhook quietly bypass all of it.

    Parked rather than processed at the door for three reasons. A sender must not
    receive a 500 because *our* mapping points at the wrong column. A slow pipeline
    must not make them time out and retry. And a payload that fails to process is
    still here for the next attempt.

    **No `processed` flag.** The pipeline is already idempotent — `external_id` is
    the event id — so re-reading an event writes nothing new, and `fetch(since)`
    can simply return everything received in the window. A flag would add a state
    machine, and the failure mode of a half-marked batch is worse than the cost of
    a repeated no-op.
    """

    __tablename__ = "webhook_event"
    __table_args__ = (
        # How `fetch` reads: this source's events, in the window, oldest first.
        Index("ix_webhook_event_source_time", "data_source_id", "received_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("organization.id", ondelete="CASCADE")
    )
    data_source_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("data_source.id", ondelete="CASCADE")
    )

    #: The sender's own id for this event, when it supplied one.
    #:
    #: Used as the fact's `external_id`, which is what makes a re-delivered
    #: webhook harmless — and re-delivery is normal, because a sender that does not
    #: get a prompt 2xx will try again.
    event_id: Mapped[str | None] = mapped_column(String(255))

    #: Exactly what arrived. JSONB so a mapping can name any field in it, and so a
    #: payload whose shape nobody anticipated is still stored rather than rejected.
    payload: Mapped[dict] = mapped_column(JSONB)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<WebhookEvent source={self.data_source_id} {self.event_id!r}>"
