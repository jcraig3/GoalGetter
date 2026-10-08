"""The webhook connector: data anybody can post at us.

**The first real connector, and deliberately the one with no OAuth.** If the
framework only holds up once a provider's authentication is doing half the work,
it does not hold up. This one has a token in a URL and a shared secret, so what is
left is entirely the abstraction.

It is also the one that unblocks technical customers immediately. Anything that can
make an HTTP request — a Zapier step, a CRM's own outbound message, six lines of
script on a cron — can feed GoalGetter without waiting for us to write a connector
for their system.

**It pushes, and the protocol pulls.** Payloads arrive at `POST /api/hooks/{token}`
and are parked in `webhook_event`; `fetch` reads that inbox. So a webhook goes
through exactly the same mapping, identity resolution and correction rules as a
warehouse query, rather than having its own private path into `metric_fact`.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterator
from datetime import datetime

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.connectors import (
    ConnectionResult,
    LocalContext,
    SourceField,
    SourceRow,
    register,
)
from app.models import WebhookEvent

#: Where in a payload to look for a list of rows.
#:
#: A sender posts either one event (`{"owner": …, "amount": …}`) or a batch
#: (`{"events": [ … ]}`). Both are normal, and asking an admin to configure which
#: one their system does is a question they should not have to answer — so the
#: connector looks for a list under any of these and treats the payload as a single
#: row if it finds none.
BATCH_KEYS = ("events", "records", "rows", "data", "items")


class WebhookConfig(BaseModel):
    """Non-secret settings.

    Almost nothing, which is the point of this connector. The path token is a
    credential and lives with the secrets.
    """

    #: Require a signature header, and refuse anything unsigned.
    #:
    #: Off by default because the token in the URL is already a credential and
    #: turning this on means the sender has to implement HMAC — which a Zapier step
    #: cannot. On for anything sending real money figures over the open internet.
    require_signature: bool = False


class WebhookSecrets(BaseModel):
    """The token in the URL, and the key payloads are signed with."""

    #: The whole credential for an unsigned webhook. Generated, never chosen — a
    #: token somebody picked is a token somebody can guess.
    token: str = ""
    #: Shared with the sender, used for HMAC-SHA256 over the raw body.
    signing_secret: str = Field(default="", repr=False)


def signature_for(secret: str, body: bytes) -> str:
    """The expected signature for this body.

    HMAC-SHA256, hex, of the **raw bytes** — not of re-serialised JSON. Two JSON
    encoders disagree about key order and whitespace, so signing a parsed-then-
    re-dumped payload produces a signature that fails for reasons nobody can see.
    """
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def signature_ok(secret: str, body: bytes, provided: str | None) -> bool:
    """Whether a provided signature matches.

    `compare_digest`, not `==`: string comparison returns early on the first
    differing byte, and the timing of that leaks how much of a guess was right.

    **No test can catch this one.** Constant-time comparison is a property of *how
    long* the function takes, not of what it returns, so a mutation swapping in `==`
    passes every assertion — and a test that measured timing would be flaky enough
    to get deleted within a month. Verified by reading, and noted here so the next
    person to see the surviving mutant knows it is deliberate rather than missed.
    """
    if not provided:
        return False
    expected = signature_for(secret, body)
    # Some senders prefix the algorithm, GitHub-style.
    candidate = provided.split("=", 1)[-1].strip()
    return hmac.compare_digest(expected, candidate)


def rows_in(payload: object) -> list[dict]:
    """The rows a payload contains.

    One event or a batch, without asking the admin which their system sends. A
    bare list is a batch too — plenty of senders post `[{…}, {…}]` with no wrapper.
    """
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in BATCH_KEYS:
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [row for row in candidate if isinstance(row, dict)]
    return [payload]


class WebhookConnector:
    """Reads the inbox that `POST /api/hooks/{token}` fills."""

    key = "webhook"
    display_name = "Webhook"
    config_schema = WebhookConfig
    credential_schema = WebhookSecrets

    #: The token in the URL is this connector's address. Generated on creation,
    #: refused on a credential write, and returned as part of the endpoint — see the
    #: protocol for why all three follow from this one line.
    endpoint_credential = "token"

    def test_connection(
        self, config: WebhookConfig, credentials: WebhookSecrets
    ) -> ConnectionResult:
        """There is nothing to reach out to, so this reports readiness instead.

        Saying "connected" for a webhook would be a lie — nothing has been
        contacted. What an admin actually needs to know at this point is whether
        anything has arrived yet, because "I set it up and nothing happened" is the
        only failure this connector has.
        """
        if not credentials.token:
            return ConnectionResult(
                ok=False,
                detail="No endpoint has been generated for this source yet.",
            )
        if config.require_signature and not credentials.signing_secret:
            return ConnectionResult(
                ok=False,
                detail=(
                    "Signatures are required but no signing secret is set, so every "
                    "delivery would be rejected."
                ),
            )
        return ConnectionResult(
            ok=True,
            detail="Ready. Post events to the endpoint and they will appear here.",
        )

    def discover(
        self,
        config: WebhookConfig,
        credentials: WebhookSecrets,
        *,
        local: LocalContext | None = None,
    ) -> list[SourceField]:
        """The fields of whatever has arrived most recently.

        A webhook has no schema to ask for, so the last delivery *is* the schema.
        This is why the setup flow asks for one test event before the mapping step:
        without a real payload, the mapper would have nothing to suggest from and
        the admin would be back to typing field names blind.
        """
        if local is None:
            return []

        latest = local.db.scalar(
            select(WebhookEvent)
            .where(WebhookEvent.data_source_id == local.source_id)
            .order_by(WebhookEvent.received_at.desc())
            .limit(1)
        )
        if latest is None:
            return []
        return _fields_of(rows_in(latest.payload))

    def fetch(
        self,
        config: WebhookConfig,
        credentials: WebhookSecrets,
        since: datetime | None = None,
        *,
        local: LocalContext | None = None,
    ) -> Iterator[SourceRow]:
        """Everything parked for this source since the window opened.

        Uses the sync's own session, from `local`. Opening its own would read the
        inbox on a different connection from the one writing the facts — not one
        transaction — and would see nothing at all under test, where the suite runs
        inside a transaction that is never committed.

        Re-reading is free: the fact's `external_id` is the event id, so a delivery
        seen twice writes nothing the second time. That is also why there is no
        `processed` flag to get half-set.
        """
        if local is None:
            return

        query = select(WebhookEvent).where(
            WebhookEvent.data_source_id == local.source_id
        )
        if since is not None:
            query = query.where(WebhookEvent.received_at >= since)

        for event in local.db.scalars(
            query.order_by(WebhookEvent.received_at, WebhookEvent.id)
        ).all():
            rows = rows_in(event.payload)
            for index, row in enumerate(rows):
                yield SourceRow(
                    external_id=_row_id(event, index, len(rows)),
                    values=row,
                )


def _row_id(event: WebhookEvent, index: int, total: int) -> str:
    """A stable id for one row of one delivery.

    The event id alone is not enough for a batch: ten rows in one delivery would
    all claim the same id and collapse into one fact. The index makes them
    distinct, and it is stable because the order within a payload does not change
    between reads of the same stored payload.

    Falls back to the row's primary key when the sender supplied no id of its own.
    Less good — a re-delivery of the same event creates a second inbox row and
    therefore a second fact — but better than refusing the delivery, and the
    endpoint says so when it happens.
    """
    base = event.event_id or f"evt-{event.id}"
    return base if total == 1 else f"{base}#{index}"


def _fields_of(rows: list[dict]) -> list[SourceField]:
    """Guess each field's kind from the first row that has a value for it.

    A guess, and labelled as one — it drives the auto-suggested mapping, and the
    admin confirms. Guessing wrong costs a click; not guessing costs every admin
    typing every field name.
    """
    fields: dict[str, SourceField] = {}
    for row in rows:
        for name, value in row.items():
            if name in fields or not isinstance(name, str):
                continue
            fields[name] = SourceField(
                name=name, kind=_kind_of(value), samples=(str(value)[:60],)
            )
    return sorted(fields.values(), key=lambda f: f.name.lower())


def _kind_of(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        if "@" in value:
            return "email"
        # Cheap and good enough for a suggestion: anything the real parsers accept.
        # Both are imported from `mapping` rather than re-implemented here, so a
        # field the wizard calls a number is a field the sync can read as one.
        from app.mapping import _number, _parse_datetime

        if _parse_datetime(value) is not None:
            return "date"
        # `"$1,250.00"` is a number an admin means as one. JSON has it as a string,
        # so without this the wizard declines to suggest the very column somebody
        # connected the source to import.
        if _number(value) is not None:
            return "number"
    return "string"


register(WebhookConnector())
