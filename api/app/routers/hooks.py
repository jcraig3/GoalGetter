"""The inbound endpoint. Public, and the only unauthenticated write in the product.

`POST /api/hooks/{token}` — the token in the path is the credential, the same shape
as a wall screen's display link. Optionally an HMAC signature on top, for a sender
that can manage one.

**Its whole job is to accept a payload and write it down.** No mapping, no identity
resolution, no facts. Those happen in the sync pipeline, which this triggers
immediately afterwards — so a closed deal reaches the wall in seconds rather than
at the next hourly tick, while still being durable and retryable if processing
fails.

**A sender is never punished for our configuration.** If a mapping points at the
wrong column, that is a `partial` sync run and a message on the Integrations page —
not a 500 for whoever posted the data. They get 202 for anything we managed to
store, because the alternative teaches senders to retry payloads we already have.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import credentials as credential_store
from app import jobs
from app import sync as sync_service
from app.connectors import webhook as webhook_connector
from app.db import SessionFactory, get_db, get_session_factory
from app.models import DataSource, Organization, WebhookEvent

router = APIRouter(prefix="/hooks", tags=["hooks"])

#: The largest payload we will store.
#:
#: A webhook is meant to describe an event, not carry a database export. A cap
#: keeps one misconfigured sender from filling the disk, and it fails loudly enough
#: that they will notice and batch properly instead.
MAX_BODY_BYTES = 512 * 1024

#: Headers senders use for a signature, in the order we look.
SIGNATURE_HEADERS = ("x-goalgetter-signature", "x-hub-signature-256", "x-signature")


class Accepted(BaseModel):
    """What a sender gets back.

    Deliberately thin. `stored` is the useful part — a sender comparing it against
    what they sent can tell a batch was truncated. Nothing about mapping outcomes:
    those are our business, and reporting them here would invite a sender to retry
    on something they cannot fix.
    """

    accepted: bool
    stored: int
    detail: str


def _source_for(db: DbSession, token: str) -> tuple[DataSource, dict]:
    """The source this token belongs to, and its decrypted secrets.

    Scans webhook sources and compares tokens with a constant-time check. A lookup
    column would be faster, but it would mean storing the token in a form that can
    be searched — which is storing a credential in the clear, and the whole reason
    `connector_credential` exists is not to.

    404 for a bad token, never 401 or 403: a wrong token must not be able to tell
    the difference between "no such endpoint" and "endpoint exists, wrong key".
    """
    for source in db.scalars(
        select(DataSource).where(DataSource.connector == "webhook")
    ).all():
        secrets = credential_store.get(db, source)
        stored = str(secrets.get("token") or "")
        if stored and _same(stored, token):
            return source, secrets
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown endpoint.")


def _same(left: str, right: str) -> bool:
    """Constant-time, for the same reason as the signature check.

    Also untestable by behaviour — see the note on `webhook.signature_ok`. A mutant
    swapping in `==` survives the suite, and that is a property of timing rather
    than of the answer.
    """
    import hmac

    return hmac.compare_digest(left, right)


@router.post("/{token}", response_model=Accepted, status_code=status.HTTP_202_ACCEPTED)
async def receive(
    token: str,
    request: Request,
    background: BackgroundTasks,
    db: DbSession = Depends(get_db),
    sessions: SessionFactory = Depends(get_session_factory),
    content_type: str | None = Header(default=None, alias="content-type"),
) -> Accepted:
    """Accept a payload, park it, and start processing.

    202 rather than 200, and it is the honest code: we have accepted the data and
    not yet acted on it. A sender reading status codes properly will not treat this
    as "the numbers are live", because they are not — they are stored.
    """
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Payloads are limited to {MAX_BODY_BYTES // 1024} KB. "
                "Send events in smaller batches."
            ),
        )

    source, secrets = _source_for(db, token)

    if not source.enabled:
        # 409, not 404: the endpoint is real and the sender's request is fine — an
        # admin turned this source off, and saying so is what stops them debugging
        # their own integration for an afternoon.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This source is disabled. Enable it to start accepting events.",
        )

    config = webhook_connector.WebhookConfig(**(source.config or {}))
    if config.require_signature:
        provided = next(
            (request.headers.get(name) for name in SIGNATURE_HEADERS
             if request.headers.get(name)),
            None,
        )
        if not webhook_connector.signature_ok(
            str(secrets.get("signing_secret") or ""), body, provided
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Signature missing or does not match.",
            )

    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The body is not valid JSON.",
        ) from None

    rows = webhook_connector.rows_in(payload)
    if not rows:
        # Accepted and stored nothing. Not an error — a sender's keep-alive ping or
        # an empty batch is a normal thing to receive — but worth saying, because
        # "it returned 202 and nothing happened" is otherwise a mystery.
        return Accepted(
            accepted=True, stored=0, detail="Nothing in the payload looked like a row."
        )

    event = WebhookEvent(
        organization_id=source.organization_id,
        data_source_id=source.id,
        event_id=_event_id(payload, request),
        payload=payload,
    )
    db.add(event)
    db.commit()

    # Processed now rather than at the next tick. The payload is already stored, so
    # a failure here costs nothing — the scheduled run picks it up — but the common
    # case is that a deal closed and the wall lights up while somebody is still
    # looking at it.
    org = db.get(Organization, source.organization_id)
    detail = "Stored."
    if org is not None:
        outcome = sync_service.run(db, org, source, trigger="webhook")
        db.commit()
        # And announced now too: processing it straight away was only half of
        # "the wall lights up" while the wins were still found hourly.
        background.add_task(jobs.announce_now, sessions)
        detail = f"Stored and processed: {outcome.rows_written} recorded."

    return Accepted(accepted=True, stored=len(rows), detail=detail)


def _event_id(payload: object, request: Request) -> str | None:
    """The sender's own id for this delivery, if it offered one.

    Checked in the payload first, then the headers a few providers use. Worth
    hunting for: it becomes the fact's `external_id`, which is what makes a
    re-delivery harmless — and re-delivery is normal, because a sender that does not
    get a prompt 2xx will try again.
    """
    for header in ("x-goalgetter-event-id", "x-event-id", "x-request-id"):
        value = request.headers.get(header)
        if value:
            return value[:255]

    if isinstance(payload, dict):
        for key in ("event_id", "id", "eventId", "uuid"):
            value = payload.get(key)
            if isinstance(value, (str, int)):
                return str(value)[:255]
    return None
