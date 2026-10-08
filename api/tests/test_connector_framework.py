"""The Phase 3 foundation: the contract, the registry, and the secret store.

No connector exists yet, deliberately — this is the engine, and it is tested with
a stub so that the first real connector proves the *provider*, not the framework.
"""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import BaseModel
from sqlalchemy import select, text

from app import connectors, credentials
from app.models import ConnectorCredential, DataSource, MetricFact


# ── A stub connector, standing in for the real ones ──────────────────────────


class StubConfig(BaseModel):
    sheet: str = "Sheet1"


class StubSecrets(BaseModel):
    token: str = ""


class StubConnector:
    """Implements the protocol structurally and nothing else.

    A plain class rather than a subclass of anything: `Connector` is a Protocol,
    so this is the test that structural typing actually holds — if the protocol
    gained a fifth method, `isinstance` below would start failing.
    """

    key = "stub"
    display_name = "Stub Source"
    config_schema = StubConfig
    credential_schema = StubSecrets

    def test_connection(self, config, credentials):
        return connectors.ConnectionResult(ok=True, detail="Reached the stub.")

    def discover(self, config, credentials, *, local=None):
        return [connectors.SourceField(name="Amount", kind="number")]

    def fetch(self, config, credentials, since=None, *, local=None):
        yield connectors.SourceRow(external_id="1", values={"Amount": 10})


@pytest.fixture
def registry():
    """A clean registry per test, restored afterwards.

    The registry is module-level state, which is right for a process but wrong for
    a test suite — one test registering a connector must not change what the next
    one sees.
    """
    saved = dict(connectors._REGISTRY)
    connectors._REGISTRY.clear()
    yield connectors._REGISTRY
    connectors._REGISTRY.clear()
    connectors._REGISTRY.update(saved)


# ── The contract ─────────────────────────────────────────────────────────────


def test_a_stub_satisfies_the_protocol():
    """Structural typing, so a connector needs no import from the framework and a
    test needs no fake base class."""
    assert isinstance(StubConnector(), connectors.Connector)


def test_a_fetching_connector_need_not_mention_an_endpoint(registry):
    """`endpoint_credential` is an optional capability, asked for through a helper
    rather than declared on the Protocol.

    A member on a `runtime_checkable` Protocol is a member `isinstance` demands, so
    declaring it there would make every fetching connector write
    `endpoint_credential = None` to state the absence of something."""
    assert isinstance(StubConnector(), connectors.Connector)
    assert connectors.endpoint_credential_of(StubConnector()) is None


def test_a_receiving_connector_declares_which_credential_is_its_address(registry):
    class Receiver(StubConnector):
        endpoint_credential = "token"

    assert connectors.endpoint_credential_of(Receiver()) == "token"


def test_something_missing_a_method_does_not(registry):
    class Incomplete:
        key = "incomplete"
        display_name = "Incomplete"
        config_schema = StubConfig
        credential_schema = StubSecrets

        def test_connection(self, config, credentials): ...

    assert not isinstance(Incomplete(), connectors.Connector)


def test_fetch_is_lazy(registry):
    """An iterator, not a list.

    A warehouse query can return a million rows; a connector that materialises
    them has moved the memory problem into the API process, where it is found
    under load rather than in review.
    """
    rows = StubConnector().fetch(StubConfig(), StubSecrets())
    assert not isinstance(rows, list)
    assert next(iter(rows)).external_id == "1"


# ── The registry ─────────────────────────────────────────────────────────────


def test_register_then_get(registry):
    stub = StubConnector()
    connectors.register(stub)

    assert connectors.get("stub") is stub
    assert connectors.keys() == ("stub",)


def test_a_duplicate_key_is_refused(registry):
    """Rather than overwritten. Which of two connectors answering to the same key
    wins would depend on import order — a bug that only appears in the
    environment you cannot attach a debugger to."""
    connectors.register(StubConnector())

    with pytest.raises(ValueError, match="already registered"):
        connectors.register(StubConnector())


def test_an_unknown_key_says_what_is_available(registry):
    """The error a `data_source` row naming a connector this build lacks will
    produce. It has to be distinguishable from a real failure, because the
    scheduler skips it rather than dying."""
    connectors.register(StubConnector())

    with pytest.raises(connectors.UnknownConnector) as caught:
        connectors.get("salesforce")

    assert "salesforce" in str(caught.value)
    assert "stub" in str(caught.value)


def test_an_empty_registry_still_gives_a_usable_error(registry):
    with pytest.raises(connectors.UnknownConnector, match="none"):
        connectors.get("anything")


def test_available_is_ordered_by_display_name(registry):
    """A stable order for the wizard's grid of cards, rather than whichever
    module imported first.

    The names are chosen so a **case-sensitive** sort gets a different answer.
    An earlier version used "Alpha", "Middle", "zeta", which sort identically
    either way — uppercase precedes lowercase in ASCII — so a mutation dropping
    the `.lower()` survived. "apple" before "Banana" only holds if case is
    folded, and real connector names are things like "HubSpot" and "webhook".
    """

    def make(key, name):
        stub = StubConnector()
        stub.key = key
        stub.display_name = name
        return stub

    for key, name in [("b", "Banana"), ("a", "apple"), ("c", "Cherry")]:
        connectors.register(make(key, name))

    assert [c.display_name for c in connectors.available()] == [
        "apple",
        "Banana",
        "Cherry",
    ]


# ── Secrets ──────────────────────────────────────────────────────────────────


@pytest.fixture
def source(db, org):
    row = DataSource(
        organization_id=org.id, name="Stub source", connector="stub"
    )
    db.add(row)
    db.flush()
    return row


def test_secrets_round_trip(db, source):
    credentials.put(db, source, {"token": "abc", "refresh": "def"})

    assert credentials.get(db, source) == {"token": "abc", "refresh": "def"}


def test_secrets_are_encrypted_at_rest(db, source):
    """The point of the module. A token readable with `SELECT` is a token in every
    backup, every log shipper, and every screenshot of a database client."""
    credentials.put(db, source, {"token": "sensitive-value"})

    stored = db.scalar(
        select(ConnectorCredential.secrets_encrypted).where(
            ConnectorCredential.data_source_id == source.id
        )
    )
    assert "sensitive-value" not in stored
    assert stored.startswith("gAAAAA")  # Fernet's version prefix


def test_putting_again_replaces_rather_than_merges(db, source):
    """A merge would leave a stale `refresh` behind when a provider rotates it —
    and that breaks days later, when the access token expires and cannot be
    renewed, with nothing in the logs from the day it actually broke."""
    credentials.put(db, source, {"token": "old", "refresh": "old-refresh"})
    credentials.put(db, source, {"token": "new"})

    assert credentials.get(db, source) == {"token": "new"}


def test_only_one_credential_row_per_source(db, source):
    credentials.put(db, source, {"token": "one"})
    credentials.put(db, source, {"token": "two"})

    rows = db.scalars(
        select(ConnectorCredential).where(
            ConnectorCredential.data_source_id == source.id
        )
    ).all()
    assert len(rows) == 1


def test_no_secrets_reads_as_an_empty_dict(db, source):
    """So a connector needing none — a public sheet, an inbound webhook — reads
    the same as one whose secrets are absent."""
    assert credentials.get(db, source) == {}
    assert credentials.has_secrets(db, source) is False


def test_has_secrets_does_not_decrypt(db, source):
    credentials.put(db, source, {"token": "abc"})
    assert credentials.has_secrets(db, source) is True


def test_expiry_is_stored_in_the_clear(db, source):
    """The scheduler asks "does this need refreshing?" every pass. Decrypting
    every credential to answer that would be slow and needless exposure."""
    when = datetime.now(UTC) + timedelta(hours=1)
    credentials.put(db, source, {"token": "abc"}, expires_at=when)

    stored = db.scalar(
        select(ConnectorCredential.expires_at).where(
            ConnectorCredential.data_source_id == source.id
        )
    )
    assert stored == when


def test_forget_removes_them(db, source):
    credentials.put(db, source, {"token": "abc"})

    assert credentials.forget(db, source) is True
    assert credentials.get(db, source) == {}
    assert credentials.forget(db, source) is False


def test_an_unreadable_secret_raises_rather_than_reading_as_absent(db, source):
    """A mis-keyed deployment must not present itself as a misconfigured
    integration — somebody would spend an afternoon re-entering credentials that
    were fine all along."""
    credentials.put(db, source, {"token": "abc"})
    db.execute(
        text(
            "UPDATE connector_credential SET secrets_encrypted = 'gAAAAAB-not-valid' "
            "WHERE data_source_id = :sid"
        ),
        {"sid": source.id},
    )
    db.flush()

    with pytest.raises(ValueError, match="ENCRYPTION_KEY"):
        credentials.get(db, source)


def test_deleting_a_source_takes_its_secrets(db, source):
    """CASCADE on the credential, so a removed source cannot leave a usable token
    behind in the database."""
    credentials.put(db, source, {"token": "abc"})
    db.delete(source)
    db.flush()

    assert db.scalars(select(ConnectorCredential)).all() == []


# ── The idempotency key ──────────────────────────────────────────────────────


def test_two_sources_may_use_the_same_external_id(db, org, source, make_metric, make_user):
    """The reason `data_source_id` is in `uq_metric_fact_external`.

    A Salesforce opportunity and a spreadsheet row are both plausibly "1042".
    Without the source in the key the second connector's rows would silently
    update the first's instead of adding their own — the worst kind of data bug,
    because the totals stay plausible.
    """
    other = DataSource(organization_id=org.id, name="Other", connector="stub")
    db.add(other)
    db.flush()

    metric = make_metric("revenue")
    person = make_user("agent", None, name="Alice")
    when = datetime(2026, 8, 1, tzinfo=UTC)

    for src in (source, other):
        db.add(
            MetricFact(
                organization_id=org.id,
                metric_definition_id=metric.id,
                subject_user_id=person.id,
                value=100,
                occurred_at=when,
                source_type="connector",
                data_source_id=src.id,
                external_id="1042",
            )
        )
    db.flush()

    rows = db.scalars(
        select(MetricFact).where(MetricFact.external_id == "1042")
    ).all()
    assert len(rows) == 2


def test_one_source_cannot_write_the_same_id_twice(db, org, source, make_metric, make_user):
    """What makes a sync idempotent: re-reading yesterday's deals writes nothing
    new."""
    from sqlalchemy.exc import IntegrityError

    metric = make_metric("revenue")
    person = make_user("agent", None, name="Alice")
    when = datetime(2026, 8, 1, tzinfo=UTC)

    def fact():
        return MetricFact(
            organization_id=org.id,
            metric_definition_id=metric.id,
            subject_user_id=person.id,
            value=100,
            occurred_at=when,
            source_type="connector",
            data_source_id=source.id,
            external_id="dup",
        )

    db.add(fact())
    db.flush()
    db.add(fact())
    with pytest.raises(IntegrityError):
        db.flush()


def test_one_source_row_may_feed_two_metrics(db, org, source, make_metric, make_user):
    """A closed deal is both a "deals won" count and a "revenue" amount — two
    facts sharing one external id, which is why the metric stays in the key."""
    revenue = make_metric("revenue")
    deals = make_metric("deals_won")
    person = make_user("agent", None, name="Alice")
    when = datetime(2026, 8, 1, tzinfo=UTC)

    for metric, value in ((revenue, 5000), (deals, 1)):
        db.add(
            MetricFact(
                organization_id=org.id,
                metric_definition_id=metric.id,
                subject_user_id=person.id,
                value=value,
                occurred_at=when,
                source_type="connector",
                data_source_id=source.id,
                external_id="deal-77",
            )
        )
    db.flush()

    assert len(db.scalars(select(MetricFact).where(MetricFact.external_id == "deal-77")).all()) == 2


def test_a_source_with_facts_cannot_be_deleted(db, org, source, make_metric, make_user):
    """RESTRICT, not CASCADE or SET NULL.

    Deleting a source must not delete the measurements it collected — a settled
    competition was computed from them — and nulling the column would break the
    idempotency key, so re-connecting the same source would import everything a
    second time.
    """
    from sqlalchemy.exc import IntegrityError

    metric = make_metric("revenue")
    person = make_user("agent", None, name="Alice")
    db.add(
        MetricFact(
            organization_id=org.id,
            metric_definition_id=metric.id,
            subject_user_id=person.id,
            value=100,
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
            source_type="connector",
            data_source_id=source.id,
            external_id="keep-me",
        )
    )
    db.flush()

    db.delete(source)
    with pytest.raises(IntegrityError):
        db.flush()


def test_every_connector_that_asks_for_a_credential_says_where_to_get_it():
    """**A property, so a new connector cannot quietly ship without it.**

    The credential fields carry a sentence each, and that is the right place for
    "which of the two boxes on this screen goes here". It is the wrong place for
    the route through somebody else's product — Settings, then Integrations, then
    Private apps — because a journey told one sentence at a time, each next to the
    field it ends at, is a journey nobody follows.

    A connector that generates its own credential is exempt, and there is exactly
    one: a webhook hands out an address rather than asking for one.
    """
    from app import connectors

    for connector in connectors.available():
        if connectors.endpoint_credential_of(connector) is not None:
            continue
        if not connector.credential_schema.model_json_schema().get("properties"):
            continue
        assert connectors.setup_steps_of(connector), (
            f"{connector.key} asks for a credential and does not say where to find it"
        )


def test_a_connector_that_generates_its_own_credential_needs_no_steps():
    """The other half, stated so the exemption above is a rule rather than a hole
    somebody can widen."""
    from app import connectors

    webhook = connectors.get("webhook")

    assert connectors.endpoint_credential_of(webhook) is not None
    assert connectors.setup_steps_of(webhook) == ()


def test_setup_steps_default_to_nothing_for_a_connector_that_declares_none():
    """Read through a helper with a default, like every other optional capability
    — so a stub in a test, or a connector written before this existed, is not a
    crash."""
    from app import connectors

    class Bare:
        key = "bare"
        display_name = "Bare"

    assert connectors.setup_steps_of(Bare()) == ()
