"""The webhook: data anybody can post at us.

Two halves. The **connector**, which reads an inbox and is pure enough to test
without HTTP, and the **endpoint**, which is the only unauthenticated write in the
product and therefore the part to be suspicious about.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import credentials as credential_store
from app import identity, sync
from app.connectors import webhook as hook
from app.models import (
    DataSource,
    MetricFact,
    SourceMapping,
    SyncRun,
    WebhookEvent,
)

TOKEN = "tok-webhook-test"
SECRET = "shh-signing-secret"


@pytest.fixture
def source(db, org):
    row = DataSource(
        organization_id=org.id, name="Inbound", connector="webhook", backfill_days=30
    )
    db.add(row)
    db.flush()
    credential_store.put(db, row, {"token": TOKEN, "signing_secret": SECRET})
    db.commit()
    return row


@pytest.fixture
def mapped(db, org, source, make_metric):
    metric = make_metric("revenue", unit="currency", decimal_places=2)
    row = SourceMapping(
        organization_id=org.id,
        data_source_id=source.id,
        metric_definition_id=metric.id,
        value_field="amount",
        occurred_at_field="closed_at",
        subject_field="owner",
    )
    db.add(row)
    db.commit()
    return row


def facts(db):
    return list(db.scalars(select(MetricFact).order_by(MetricFact.id)).all())


def post(client, body, *, token=TOKEN, headers=None):
    raw = body if isinstance(body, (bytes, str)) else json.dumps(body)
    return client.post(
        f"/api/hooks/{token}",
        content=raw,
        headers={"content-type": "application/json", **(headers or {})},
    )


# ── Reading a payload's shape ────────────────────────────────────────────────


def test_a_single_event_is_one_row():
    assert hook.rows_in({"owner": "a@b.c", "amount": 1}) == [
        {"owner": "a@b.c", "amount": 1}
    ]


@pytest.mark.parametrize("key", hook.BATCH_KEYS)
def test_a_batch_under_any_common_key(key):
    """Asking an admin which wrapper their system uses is a question they should not
    have to answer."""
    assert hook.rows_in({key: [{"a": 1}, {"a": 2}]}) == [{"a": 1}, {"a": 2}]


def test_a_bare_list_is_a_batch():
    """Plenty of senders post `[{…}, {…}]` with no wrapper at all."""
    assert hook.rows_in([{"a": 1}, {"a": 2}]) == [{"a": 1}, {"a": 2}]


def test_non_objects_in_a_wrapped_batch_are_dropped():
    assert hook.rows_in({"events": [{"a": 1}, "nonsense", None, 42]}) == [{"a": 1}]


def test_non_objects_in_a_bare_list_are_dropped():
    """A separate branch from the wrapped case, and it was untested — a mutation
    keeping junk survived. A stray string reaching the mapper is not a row and
    would fail on every field lookup."""
    assert hook.rows_in([{"a": 1}, "nonsense", None, 42]) == [{"a": 1}]


def test_nothing_usable_is_no_rows():
    assert hook.rows_in("a string") == []
    assert hook.rows_in(None) == []
    assert hook.rows_in({"events": []}) == []


# ── Signatures ───────────────────────────────────────────────────────────────


def test_a_correct_signature_matches():
    body = b'{"owner":"a@b.c"}'
    assert hook.signature_ok(SECRET, body, hook.signature_for(SECRET, body))


def test_a_prefixed_signature_matches():
    """Some senders write `sha256=…`, GitHub-style."""
    body = b'{"a":1}'
    signed = "sha256=" + hook.signature_for(SECRET, body)
    assert hook.signature_ok(SECRET, body, signed)


def test_a_signature_over_different_bytes_fails():
    """Signed over the **raw** body, not re-serialised JSON — two encoders disagree
    about key order and whitespace, and a signature that fails for that reason is
    unresolvable from the outside."""
    signed = hook.signature_for(SECRET, b'{"a":1}')
    assert not hook.signature_ok(SECRET, b'{"a": 1}', signed)


def test_a_missing_or_wrong_signature_fails():
    body = b'{"a":1}'
    assert not hook.signature_ok(SECRET, body, None)
    assert not hook.signature_ok(SECRET, body, "")
    assert not hook.signature_ok(SECRET, body, "deadbeef")
    assert not hook.signature_ok("other-secret", body, hook.signature_for(SECRET, body))


# ── The connector reads its inbox ────────────────────────────────────────────


def park(db, source, payload, *, event_id=None, at=None):
    row = WebhookEvent(
        organization_id=source.organization_id,
        data_source_id=source.id,
        event_id=event_id,
        payload=payload,
        received_at=at or datetime.now(UTC),
    )
    db.add(row)
    db.commit()
    return row


def test_fetch_returns_parked_events(db, source):
    park(db, source, {"owner": "a@b.c", "amount": 5}, event_id="e1")

    rows = list(
        hook.WebhookConnector().fetch(
            hook.WebhookConfig(), hook.WebhookSecrets(), None,
            local=hook.LocalContext(db=db, source_id=source.id),
        )
    )

    assert [r.external_id for r in rows] == ["e1"]
    assert rows[0].values["amount"] == 5


def test_fetch_without_a_context_returns_nothing(db, source):
    """The pipeline always passes one. A connector asked for rows with no session and
    no idea whose inbox to read must not guess."""
    park(db, source, {"owner": "a@b.c"}, event_id="e1")

    rows = list(
        hook.WebhookConnector().fetch(
            hook.WebhookConfig(), hook.WebhookSecrets(), None
        )
    )

    assert rows == []


def test_fetch_reads_only_its_own_inbox(db, org, source):
    """Two sources, and each `fetch` sees only its own events.

    Every other test here has a single source, so a mutation dropping the source
    filter changed nothing — the same single-fixture blindness that hid a cross-
    organization leak earlier in this project. With two inboxes it bites.
    """
    other = DataSource(
        organization_id=org.id, name="Other inbound", connector="webhook"
    )
    db.add(other)
    db.flush()
    park(db, source, {"owner": "mine@b.c"}, event_id="mine")
    park(db, other, {"owner": "theirs@b.c"}, event_id="theirs")

    mine = list(
        hook.WebhookConnector().fetch(
            hook.WebhookConfig(), hook.WebhookSecrets(), None,
            local=hook.LocalContext(db=db, source_id=source.id),
        )
    )
    theirs = list(
        hook.WebhookConnector().fetch(
            hook.WebhookConfig(), hook.WebhookSecrets(), None,
            local=hook.LocalContext(db=db, source_id=other.id),
        )
    )

    assert [r.external_id for r in mine] == ["mine"]
    assert [r.external_id for r in theirs] == ["theirs"]


def test_discover_reads_only_its_own_inbox(db, org, source):
    other = DataSource(
        organization_id=org.id, name="Other inbound", connector="webhook"
    )
    db.add(other)
    db.flush()
    park(db, source, {"mine_field": 1})
    park(db, other, {"their_field": 1})

    fields = hook.WebhookConnector().discover(
        hook.WebhookConfig(),
        hook.WebhookSecrets(),
        local=hook.LocalContext(db=db, source_id=source.id),
    )

    assert [f.name for f in fields] == ["mine_field"]


def test_fetch_honours_the_window(db, source):
    old = datetime.now(UTC) - timedelta(days=10)
    park(db, source, {"owner": "old@b.c"}, event_id="old", at=old)
    park(db, source, {"owner": "new@b.c"}, event_id="new")

    rows = list(
        hook.WebhookConnector().fetch(
            hook.WebhookConfig(),
            hook.WebhookSecrets(),
            datetime.now(UTC) - timedelta(days=1),
            local=hook.LocalContext(db=db, source_id=source.id),
        )
    )

    assert [r.external_id for r in rows] == ["new"]


def test_a_batch_gets_one_id_per_row(db, source):
    """**The bug this prevents.** Ten rows in one delivery all claiming the same id
    would collapse into a single fact, because the id is what makes a sync
    idempotent."""
    park(db, source, {"events": [{"a": 1}, {"a": 2}, {"a": 3}]}, event_id="batch-1")

    rows = list(
        hook.WebhookConnector().fetch(
            hook.WebhookConfig(), hook.WebhookSecrets(), None,
            local=hook.LocalContext(db=db, source_id=source.id),
        )
    )

    assert [r.external_id for r in rows] == ["batch-1#0", "batch-1#1", "batch-1#2"]


def test_a_single_row_keeps_the_plain_event_id(db, source):
    """No `#0` suffix when there is nothing to disambiguate — the id a sender can
    recognise is worth more than a uniform shape."""
    park(db, source, {"a": 1}, event_id="e1")

    rows = list(
        hook.WebhookConnector().fetch(
            hook.WebhookConfig(), hook.WebhookSecrets(), None,
            local=hook.LocalContext(db=db, source_id=source.id),
        )
    )

    assert rows[0].external_id == "e1"


def test_without_a_sender_id_the_row_id_falls_back_to_the_inbox_row(db, source):
    """Worse — a re-delivery makes a second fact — but better than refusing the
    delivery."""
    event = park(db, source, {"a": 1})

    rows = list(
        hook.WebhookConnector().fetch(
            hook.WebhookConfig(), hook.WebhookSecrets(), None,
            local=hook.LocalContext(db=db, source_id=source.id),
        )
    )

    assert rows[0].external_id == f"evt-{event.id}"


def test_discover_reads_the_most_recent_delivery(db, source):
    """A webhook has no schema to ask for, so the last delivery *is* the schema."""
    park(db, source, {"old_field": 1}, at=datetime.now(UTC) - timedelta(hours=1))
    park(db, source, {"owner": "a@b.c", "amount": 100, "closed_at": "2026-08-07"})

    fields = hook.WebhookConnector().discover(
        hook.WebhookConfig(),
        hook.WebhookSecrets(),
        local=hook.LocalContext(db=db, source_id=source.id),
    )

    by_name = {f.name: f.kind for f in fields}
    assert by_name == {"amount": "number", "closed_at": "date", "owner": "email"}


def test_a_formatted_money_column_is_suggested_as_a_number(db, source):
    """JSON has `"$1,250.00"` as a string, and it is the very column somebody
    connected the source to import. Suggesting `string` for it means the wizard
    declines to offer the one field that matters.

    Uses the same `_number` the sync does, so a field the wizard calls a number is
    a field the sync can read as one."""
    park(db, source, {"amount": "$1,250.00", "note": "closed by phone"})

    fields = hook.WebhookConnector().discover(
        hook.WebhookConfig(),
        hook.WebhookSecrets(),
        local=hook.LocalContext(db=db, source_id=source.id),
    )

    assert {f.name: f.kind for f in fields} == {"amount": "number", "note": "string"}


def test_discover_with_nothing_delivered_yet(db, source):
    assert hook.WebhookConnector().discover(
        hook.WebhookConfig(),
        hook.WebhookSecrets(),
        local=hook.LocalContext(db=db, source_id=source.id),
    ) == []


# ── test_connection reports readiness, not a connection ──────────────────────


def test_readiness_needs_a_token():
    got = hook.WebhookConnector().test_connection(
        hook.WebhookConfig(), hook.WebhookSecrets(token="")
    )
    assert got.ok is False
    assert "endpoint" in got.detail


def test_requiring_signatures_without_a_secret_is_refused():
    """Otherwise every delivery is rejected and the reason is invisible."""
    got = hook.WebhookConnector().test_connection(
        hook.WebhookConfig(require_signature=True),
        hook.WebhookSecrets(token=TOKEN, signing_secret=""),
    )
    assert got.ok is False
    assert "signing secret" in got.detail


def test_a_configured_webhook_reports_ready():
    got = hook.WebhookConnector().test_connection(
        hook.WebhookConfig(), hook.WebhookSecrets(token=TOKEN)
    )
    assert got.ok is True


# ── The endpoint ─────────────────────────────────────────────────────────────


def test_a_posted_event_becomes_a_fact(client, db, source, mapped, make_user):
    """End to end, and the point of the whole slice: an HTTP request from anywhere
    turns into a number on a leaderboard, through the same pipeline a warehouse
    query goes through."""
    alice = make_user("agent", None, name="Alice")
    db.commit()

    response = post(
        client,
        {
            "id": "deal-1",
            "owner": alice.email,
            "amount": "1,200.50",
            "closed_at": "2026-08-07",
        },
    )

    assert response.status_code == 202
    assert response.json()["stored"] == 1
    written = facts(db)
    assert len(written) == 1
    assert written[0].value == Decimal("1200.50")
    assert written[0].subject_user_id == alice.id
    assert written[0].external_id == "deal-1"


def test_processing_happens_immediately(client, db, source, mapped, make_user):
    """Not at the next hourly tick. A deal closing should light up the wall while
    somebody is still looking at it."""
    alice = make_user("agent", None, name="Alice")
    db.commit()

    response = post(
        client, {"id": "d1", "owner": alice.email, "amount": 10, "closed_at": "2026-08-07"}
    )

    assert "1 recorded" in response.json()["detail"]
    runs = db.scalars(select(SyncRun)).all()
    assert [r.trigger for r in runs] == ["webhook"]


def test_re_delivery_writes_one_fact(client, db, source, mapped, make_user):
    """A sender that does not get a prompt 2xx will try again. Re-delivery has to be
    harmless, which is what the event id is for."""
    alice = make_user("agent", None, name="Alice")
    db.commit()
    body = {"id": "d1", "owner": alice.email, "amount": 10, "closed_at": "2026-08-07"}

    post(client, body)
    post(client, body)

    assert len(facts(db)) == 1


def test_an_unknown_token_is_404(client, db, source):
    """Never 401 or 403: a wrong token must not learn the difference between "no
    such endpoint" and "right endpoint, wrong key"."""
    assert post(client, {"a": 1}, token="not-a-real-token").status_code == 404


def test_a_disabled_source_says_so(client, db, source, mapped):
    """409, not 404 — the endpoint is real and the sender's request is fine. Saying
    so is what stops them debugging their own integration for an afternoon."""
    source.enabled = False
    db.commit()

    response = post(client, {"a": 1})

    assert response.status_code == 409
    assert "disabled" in response.json()["detail"]


def test_malformed_json_is_a_400(client, db, source, mapped):
    response = post(client, b"{not json")
    assert response.status_code == 400
    assert "valid JSON" in response.json()["detail"]


def test_an_oversized_payload_is_refused(client, db, source, mapped):
    """A webhook describes an event; it is not a database export. One misconfigured
    sender should not fill the disk."""
    response = post(client, {"blob": "x" * (hook_max() + 1024)})
    assert response.status_code == 413


def hook_max():
    from app.routers.hooks import MAX_BODY_BYTES

    return MAX_BODY_BYTES


def test_an_empty_payload_is_accepted_and_says_nothing_happened(
    client, db, source, mapped
):
    """A keep-alive ping is a normal thing to receive. Accepting it silently would
    make "it returned 202 and nothing happened" a mystery."""
    response = post(client, {"events": []})

    assert response.status_code == 202
    assert response.json()["stored"] == 0
    assert "Nothing in the payload" in response.json()["detail"]
    assert db.scalars(select(WebhookEvent)).all() == []


def test_a_required_signature_is_enforced(client, db, source, mapped, make_user):
    alice = make_user("agent", None, name="Alice")
    source.config = {"require_signature": True}
    db.commit()
    body = json.dumps({"owner": alice.email, "amount": 1, "closed_at": "2026-08-07"})

    unsigned = post(client, body)
    signed = post(
        client,
        body,
        headers={"x-goalgetter-signature": hook.signature_for(SECRET, body.encode())},
    )

    assert unsigned.status_code == 401
    assert signed.status_code == 202


def test_a_signature_is_ignored_when_not_required(client, db, source, mapped, make_user):
    """Off by default, because a Zapier step cannot compute an HMAC and the token is
    already a credential."""
    alice = make_user("agent", None, name="Alice")
    db.commit()

    response = post(
        client, {"owner": alice.email, "amount": 1, "closed_at": "2026-08-07"}
    )

    assert response.status_code == 202


def test_an_unknown_person_is_quarantined_not_rejected(client, db, source, mapped):
    """The sender did nothing wrong. They get a 202, and an admin gets a question."""
    response = post(
        client, {"owner": "stranger@nowhere.test", "amount": 5, "closed_at": "2026-08-07"}
    )

    assert response.status_code == 202
    assert facts(db) == []
    assert [i.external_identifier for i in identity.pending(db, source)] == [
        "stranger@nowhere.test"
    ]


def test_a_bad_mapping_still_returns_202(client, db, source, mapped, make_user):
    """**A sender is never punished for our configuration.** A 500 here teaches them
    to retry a payload we already stored."""
    alice = make_user("agent", None, name="Alice")
    mapped.value_field = "amont"
    db.commit()

    response = post(
        client, {"owner": alice.email, "amount": 1, "closed_at": "2026-08-07"}
    )

    assert response.status_code == 202
    stored = db.scalars(select(WebhookEvent)).all()
    assert len(stored) == 1  # kept, so a fixed mapping can re-read it
    run = db.scalars(select(SyncRun)).all()[0]
    assert run.status == "partial"
    assert "amont" in run.error


def test_a_batch_becomes_several_facts(client, db, source, mapped, make_user):
    alice = make_user("agent", None, name="Alice")
    bob = make_user("agent", None, name="Bob")
    db.commit()

    response = post(
        client,
        {
            "id": "batch-7",
            "events": [
                {"owner": alice.email, "amount": 100, "closed_at": "2026-08-07"},
                {"owner": bob.email, "amount": 200, "closed_at": "2026-08-07"},
            ],
        },
    )

    assert response.json()["stored"] == 2
    assert sorted(f.value for f in facts(db)) == [Decimal(100), Decimal(200)]
    assert sorted(f.external_id for f in facts(db)) == ["batch-7#0", "batch-7#1"]


def test_an_event_id_from_a_header_is_used(client, db, source, mapped, make_user):
    """Several providers put it there rather than in the body."""
    alice = make_user("agent", None, name="Alice")
    db.commit()

    post(
        client,
        {"owner": alice.email, "amount": 1, "closed_at": "2026-08-07"},
        headers={"x-goalgetter-event-id": "from-header"},
    )

    assert facts(db)[0].external_id == "from-header"
