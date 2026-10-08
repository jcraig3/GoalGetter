"""Connecting a source, describing what it means, and watching it work.

Admin only, because a source writes into `metric_fact` and every leaderboard, goal
and competition reads that. The two things to be most suspicious about are whether
a secret can ever come back out, and whether a source that has recorded real
measurements can be deleted.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app import credentials as credential_store
from app.models import (
    AuditLog,
    ConnectorCredential,
    DataSource,
    MetricFact,
    SourceMapping,
    UserIdentity,
)


@pytest.fixture
def admin(make_user):
    return make_user("admin", name="Admin")


@pytest.fixture
def metric(make_metric):
    return make_metric("revenue", unit="currency", decimal_places=2)


@pytest.fixture
def signed_in(client, db, admin, sign_in):
    sign_in(admin)
    db.commit()
    return client


def make_source(client, **overrides):
    body = {"name": "Inbound", "connector": "webhook"}
    body.update(overrides)
    return client.post("/api/data-sources", json=body)


def mapping_body(metric, **overrides):
    body = {
        "metric_id": metric.id,
        "value_field": "amount",
        "occurred_at_field": "closed_at",
        "subject_field": "owner",
    }
    body.update(overrides)
    return body


# ── Connectors ───────────────────────────────────────────────────────────────


def test_the_wizard_lists_exactly_what_this_build_registered(signed_in):
    """Matched against the registry rather than a hand-written set, so shipping a
    connector does not mean editing this test — but a connector that registers
    itself *without* being shipped deliberately still shows up here."""
    from app import connectors as registry

    found = signed_in.get("/api/connectors").json()

    assert {c["key"] for c in found} == set(registry.keys())
    by_key = {c["key"]: c["display_name"] for c in found}
    assert by_key["webhook"] == "Webhook"


def test_only_an_admin_may_look(client, db, make_user, sign_in):
    """A source decides what every leaderboard in the building reads. Not a
    manager-level decision."""
    sign_in(make_user("manager", None, name="Manager"))
    db.commit()

    assert client.get("/api/data-sources").status_code == 403
    assert client.get("/api/connectors").status_code == 403


# ── Creating ─────────────────────────────────────────────────────────────────


def test_creating_a_source(signed_in):
    response = make_source(signed_in)

    assert response.status_code == 201
    body = response.json()
    assert body["connector_name"] == "Webhook"
    assert body["enabled"] is True
    assert body["mappings"] == []
    assert body["facts_written"] == 0


def test_a_webhook_gets_a_generated_token(signed_in, db):
    """Generated, never chosen — a token somebody picked is a token somebody can
    guess, and the endpoint is the whole credential."""
    body = make_source(signed_in).json()

    assert body["credentials_set"] is True
    source = db.get(DataSource, body["id"])
    token = credential_store.get(db, source)["token"]
    assert len(token) > 30


def test_a_new_source_is_due_immediately(signed_in, db):
    """`next_run_at` left NULL, which the scheduler reads as due — so connecting
    something does not appear to sit idle for an hour."""
    body = make_source(signed_in).json()
    assert body["next_run_at"] is None


def test_an_unknown_connector_is_refused_by_name(signed_in):
    """The name here was `salesforce` until Salesforce shipped, which is a neat
    argument for picking something nobody will ever build."""
    response = make_source(signed_in, connector="carrier_pigeon")

    assert response.status_code == 422
    assert "webhook" in json.dumps(response.json())


def test_creating_is_audited(signed_in, db):
    make_source(signed_in)

    entry = db.scalars(select(AuditLog).order_by(AuditLog.id.desc())).first()
    assert entry.action == "data_source.created"
    assert entry.details["connector"] == "webhook"


# ── The endpoint: the one credential that comes back ─────────────────────────


def test_the_endpoint_url_is_shown_so_it_can_be_pasted_somewhere(signed_in, db):
    """A webhook token is an address, not a key a provider already holds. Hiding it
    would make the connector unusable — there is nowhere else to get it."""
    source_id = make_source(signed_in).json()["id"]
    token = credential_store.get(db, db.get(DataSource, source_id))["token"]

    body = signed_in.get(f"/api/data-sources/{source_id}").json()

    assert body["endpoint_url"].endswith(f"/api/hooks/{token}")
    assert body["endpoint_url"].startswith("http")


def test_the_endpoint_is_the_same_one_a_fortnight_later(signed_in):
    """Read, not re-issued. Somebody sets the CRM up long after connecting the
    source, and a URL that changed on every visit would break every sender."""
    source_id = make_source(signed_in).json()["id"]

    first = signed_in.get(f"/api/data-sources/{source_id}").json()["endpoint_url"]
    second = signed_in.get(f"/api/data-sources/{source_id}").json()["endpoint_url"]

    assert first == second


def test_the_endpoint_is_not_on_the_index(signed_in, db, metric, admin):
    """The list is every source an organization has. Putting a live endpoint on each
    row spreads the credential across a page nobody came to for it."""
    with_a_fact(signed_in, db, metric, admin)

    listed = signed_in.get("/api/data-sources").json()

    assert "endpoint_url" not in listed[0]


def test_rotating_replaces_the_endpoint_and_keeps_the_signing_secret(signed_in, db):
    """Rotating an address is not changing the shared key. Doing both would mean
    reconfiguring the sender twice for one problem."""
    source_id = make_source(signed_in).json()["id"]
    signed_in.put(
        f"/api/data-sources/{source_id}/credentials",
        json={"secrets": {"signing_secret": "unchanged"}},
    )
    before = signed_in.get(f"/api/data-sources/{source_id}").json()["endpoint_url"]

    after = signed_in.post(
        f"/api/data-sources/{source_id}/endpoint/rotate"
    ).json()["endpoint_url"]

    assert after != before
    db.expire_all()
    assert (
        credential_store.get(db, db.get(DataSource, source_id))["signing_secret"]
        == "unchanged"
    )


def test_the_old_endpoint_stops_working_after_a_rotation(signed_in, db):
    """The whole point, and the reason it is a deliberate action."""
    source_id = make_source(signed_in).json()["id"]
    old_token = credential_store.get(db, db.get(DataSource, source_id))["token"]

    signed_in.post(f"/api/data-sources/{source_id}/endpoint/rotate")

    assert signed_in.post(f"/api/hooks/{old_token}", json={"a": 1}).status_code == 404


def test_a_fetching_connector_has_no_endpoint_to_show_or_rotate(
    signed_in, db, registry_slot
):
    """`endpoint_url` is None rather than absent, so the UI can decide by asking one
    question instead of knowing which connectors are which."""
    from app import connectors as connector_registry

    class Nothing(BaseModel):
        pass

    class PullerSecrets(BaseModel):
        #: Named `token` on purpose. Most REST connectors have a secret by exactly
        #: this name, and the endpoint URL must be decided by what the connector
        #: *is*, never by what its credentials are called — otherwise connecting a
        #: CRM would publish its API token as a URL.
        token: str = ""

    class Puller:
        """A connector that goes and gets its data, like every one after this."""

        key = "puller"
        display_name = "Puller"
        config_schema = Nothing
        credential_schema = PullerSecrets

        def test_connection(self, config, credentials):
            return connector_registry.ConnectionResult(ok=True, detail="fine")

        def discover(self, config, credentials, *, local=None):
            return []

        def fetch(self, config, credentials, since=None, *, local=None):
            return iter(())

    connector_registry._REGISTRY["puller"] = Puller()
    source_id = make_source(signed_in, connector="puller").json()["id"]
    # Its own API token, which an admin supplies and which is a real secret.
    signed_in.put(
        f"/api/data-sources/{source_id}/credentials",
        json={"secrets": {"token": "its-private-api-key"}},
    )

    body = signed_in.get(f"/api/data-sources/{source_id}").json()
    rotated = signed_in.post(f"/api/data-sources/{source_id}/endpoint/rotate")

    assert body["endpoint_url"] is None
    assert "its-private-api-key" not in json.dumps(body)
    assert rotated.status_code == 409
    assert "no endpoint" in rotated.json()["detail"]


def test_a_fetching_connector_generates_nothing_on_creation(
    signed_in, db, registry_slot
):
    """Only a receiving connector mints its own credential. Everything else waits
    for the admin to supply one, so `credentials_set` stays honest."""
    from app import connectors as connector_registry

    class Nothing(BaseModel):
        pass

    class Puller:
        key = "puller2"
        display_name = "Puller 2"
        config_schema = Nothing
        credential_schema = Nothing

        def test_connection(self, config, credentials):
            return connector_registry.ConnectionResult(ok=True, detail="fine")

        def discover(self, config, credentials, *, local=None):
            return []

        def fetch(self, config, credentials, since=None, *, local=None):
            return iter(())

    connector_registry._REGISTRY["puller2"] = Puller()

    body = make_source(signed_in, connector="puller2").json()

    assert body["credentials_set"] is False


# ── Secrets go in and never come back ────────────────────────────────────────


def test_a_secret_is_never_returned(signed_in, db):
    """**The property to be most suspicious about.** There is no legitimate reason
    for a browser to receive a signing secret, and any mechanism that offers to show
    one can be made to.

    The endpoint token is the documented exception and has its own tests — this is
    about everything else."""
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.put(
        f"/api/data-sources/{source_id}/credentials",
        json={"secrets": {"signing_secret": "also-secret"}},
    )

    assert response.status_code == 200
    assert "also-secret" not in json.dumps(response.json())
    assert response.json()["credentials_set"] is True

    # Nor on any other read.
    assert "also-secret" not in json.dumps(
        signed_in.get(f"/api/data-sources/{source_id}").json()
    )
    assert "also-secret" not in json.dumps(signed_in.get("/api/data-sources").json())


def test_the_endpoint_token_cannot_be_chosen(signed_in, db):
    """Generated, never typed. An admin picking a memorable one picks a guessable
    one, and for a webhook the address is the entire credential."""
    source_id = make_source(signed_in).json()["id"]
    generated = credential_store.get(db, db.get(DataSource, source_id))["token"]

    response = signed_in.put(
        f"/api/data-sources/{source_id}/credentials",
        json={"secrets": {"token": "letmein"}},
    )

    assert response.status_code == 422
    assert "rotate" in response.json()["detail"]
    db.expire_all()
    assert credential_store.get(db, db.get(DataSource, source_id))["token"] == generated


def test_a_typod_credential_key_is_refused_by_name(signed_in, db):
    """Pydantic ignores unknown keys, so without an explicit check this validated,
    stored nothing under the name meant, and — because `put` replaces — blanked the
    generated endpoint token while reporting success."""
    source_id = make_source(signed_in).json()["id"]
    before = credential_store.get(db, db.get(DataSource, source_id))["token"]

    response = signed_in.put(
        f"/api/data-sources/{source_id}/credentials",
        json={"secrets": {"tokn": "typo"}},
    )

    assert response.status_code == 422
    assert "'tokn'" in response.json()["detail"]
    assert "signing_secret" in response.json()["detail"]  # names the valid ones
    assert "token," not in response.json()["detail"]  # and not the generated one
    db.expire_all()
    assert credential_store.get(db, db.get(DataSource, source_id))["token"] == before


def test_setting_one_secret_keeps_the_others(signed_in, db):
    """Turning on signatures must not destroy the endpoint token. `put` replaces, so
    the merge has to happen before it."""
    source_id = make_source(signed_in).json()["id"]
    generated = credential_store.get(db, db.get(DataSource, source_id))["token"]

    signed_in.put(
        f"/api/data-sources/{source_id}/credentials",
        json={"secrets": {"signing_secret": "shared-with-the-sender"}},
    )

    db.expire_all()
    stored = credential_store.get(db, db.get(DataSource, source_id))
    assert stored["token"] == generated
    assert stored["signing_secret"] == "shared-with-the-sender"


def test_a_secret_can_be_cleared_by_sending_it_empty(signed_in, db):
    """The merge must not make a field impossible to unset — otherwise the only way
    off a signing secret is to disconnect and re-issue the endpoint."""
    source_id = make_source(signed_in).json()["id"]
    signed_in.put(
        f"/api/data-sources/{source_id}/credentials",
        json={"secrets": {"signing_secret": "old"}},
    )

    signed_in.put(
        f"/api/data-sources/{source_id}/credentials",
        json={"secrets": {"signing_secret": ""}},
    )

    db.expire_all()
    assert credential_store.get(db, db.get(DataSource, source_id))["signing_secret"] == ""


def test_the_audit_log_records_which_keys_not_which_values(signed_in, db):
    source_id = make_source(signed_in).json()["id"]

    signed_in.put(
        f"/api/data-sources/{source_id}/credentials",
        json={"secrets": {"signing_secret": "hunter2"}},
    )

    entry = db.scalars(
        select(AuditLog).where(AuditLog.action == "data_source.credentials_set")
    ).first()
    assert entry.details["keys"] == ["signing_secret"]
    assert "hunter2" not in json.dumps(entry.details)


def test_disconnecting_forgets_the_secret_and_disables_the_source(signed_in, db):
    """Keeps the source and its history; leaves no usable token behind."""
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.delete(f"/api/data-sources/{source_id}/credentials")

    assert response.json()["credentials_set"] is False
    assert response.json()["enabled"] is False
    assert db.scalars(select(ConnectorCredential)).all() == []


# ── Deleting is refused once it has recorded anything ────────────────────────


def test_an_unused_source_can_be_deleted(signed_in, db):
    source_id = make_source(signed_in).json()["id"]

    assert signed_in.delete(f"/api/data-sources/{source_id}").status_code == 204
    assert db.get(DataSource, source_id) is None


def test_a_source_with_facts_cannot_be_deleted(signed_in, db, metric, admin):
    """Those are real measurements a leaderboard or a settled competition was
    computed from. The message says how many, and points at disabling."""
    source_id = make_source(signed_in).json()["id"]
    db.add(
        MetricFact(
            organization_id=admin.organization_id,
            metric_definition_id=metric.id,
            subject_user_id=admin.id,
            value=Decimal(100),
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
            source_type="connector",
            data_source_id=source_id,
            external_id="keep",
        )
    )
    db.commit()

    response = signed_in.delete(f"/api/data-sources/{source_id}")

    assert response.status_code == 409
    assert "1 measurement" in response.json()["detail"]
    # Names the action that does exist, rather than leaving somebody stuck.
    assert "Remove it instead" in response.json()["detail"]
    # And the page says so before anybody clicks delete.
    assert signed_in.get(f"/api/data-sources/{source_id}").json()["facts_written"] == 1


def test_disabling_is_the_way_to_stop_a_source_that_has_history(signed_in):
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.patch(
        f"/api/data-sources/{source_id}", json={"enabled": False}
    )

    assert response.json()["enabled"] is False


def test_the_connector_cannot_be_changed(signed_in):
    """It would make this a different source whose history of "these numbers came
    from here" now points somewhere else."""
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.patch(
        f"/api/data-sources/{source_id}", json={"connector": "something_else"}
    )

    assert response.status_code == 422


# ── Drafts: a connect flow nobody finished ───────────────────────────────────


def test_a_half_built_source_is_not_listed(signed_in):
    """The page answers what is feeding my leaderboards, and a draft is not.
    Listing it turns an abandoned click into a chore."""
    make_source(signed_in)

    assert signed_in.get("/api/data-sources").json() == []


def test_a_draft_appears_once_it_is_switched_on(signed_in, metric):
    """Finished means the first time a mapping is enabled — the first moment it can
    import anything."""
    source_id = make_source(signed_in).json()["id"]
    signed_in.post(
        f"/api/data-sources/{source_id}/mappings",
        json=mapping_body(metric, enabled=True),
    )

    listed = signed_in.get("/api/data-sources").json()

    assert [s["id"] for s in listed] == [source_id]
    assert listed[0]["activated"] is True


def test_a_mapping_saved_switched_off_does_not_finish_setup(signed_in, metric):
    """Which is exactly what the connect flow does while somebody is still editing:
    it saves as it goes, disabled, so an abandoned setup imports nothing."""
    source_id = make_source(signed_in).json()["id"]

    body = signed_in.post(
        f"/api/data-sources/{source_id}/mappings",
        json=mapping_body(metric, enabled=False),
    ).json()

    assert body["activated"] is False
    assert signed_in.get("/api/data-sources").json() == []


def test_turning_the_mapping_on_at_the_end_finishes_setup(signed_in, metric):
    """The connect flow's last step, and the moment data starts flowing."""
    source_id = make_source(signed_in).json()["id"]
    created = signed_in.post(
        f"/api/data-sources/{source_id}/mappings",
        json=mapping_body(metric, enabled=False),
    ).json()
    mapping_id = created["mappings"][0]["id"]

    body = signed_in.patch(
        f"/api/data-sources/{source_id}/mappings/{mapping_id}",
        json=mapping_body(metric, enabled=True),
    ).json()

    assert body["activated"] is True


def test_pausing_a_finished_source_does_not_make_it_a_draft_again(signed_in, metric):
    """**The distinction the column exists for.** A paused source with its mapping
    switched off looks exactly like a draft from outside, and must keep being listed
    — and must never be swept."""
    source_id = make_source(signed_in).json()["id"]
    created = signed_in.post(
        f"/api/data-sources/{source_id}/mappings",
        json=mapping_body(metric, enabled=True),
    ).json()
    mapping_id = created["mappings"][0]["id"]

    signed_in.patch(
        f"/api/data-sources/{source_id}/mappings/{mapping_id}",
        json=mapping_body(metric, enabled=False),
    )
    signed_in.patch(f"/api/data-sources/{source_id}", json={"enabled": False})

    listed = signed_in.get("/api/data-sources").json()
    assert [s["id"] for s in listed] == [source_id]
    assert listed[0]["activated"] is True


def test_a_draft_can_be_deleted_outright(signed_in, db):
    """What Cancel does. It has imported nothing, so there is nothing to keep."""
    source_id = make_source(signed_in).json()["id"]

    assert signed_in.delete(f"/api/data-sources/{source_id}").status_code == 204
    assert db.get(DataSource, source_id) is None


def test_drafts_are_listed_when_asked_for(signed_in):
    """Hidden, not unreachable: the connect flow resumes one by id, and this is how
    anything else finds them."""
    source_id = make_source(signed_in).json()["id"]

    listed = signed_in.get("/api/data-sources?include_drafts=true").json()

    assert [s["id"] for s in listed] == [source_id]
    assert listed[0]["activated"] is False


def test_a_removed_source_stays_out_of_the_list_even_with_drafts_shown(
    signed_in, db, metric, admin
):
    """Two independent reasons to be left out, so asking for one back must not let
    the other in."""
    source_id = with_a_fact(signed_in, db, metric, admin)
    signed_in.post(f"/api/data-sources/{source_id}/archive")

    assert signed_in.get("/api/data-sources?include_drafts=true").json() == []


# ── Removing an integration without removing its numbers ─────────────────────


def with_a_fact(client, db, metric, admin, **overrides):
    """A source that has imported something, which is what makes it unremovable
    by deletion and is therefore the case every test here needs."""
    source_id = make_source(client, **overrides).json()["id"]
    db.add(
        MetricFact(
            organization_id=admin.organization_id,
            metric_definition_id=metric.id,
            subject_user_id=admin.id,
            value=Decimal(100),
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
            source_type="connector",
            data_source_id=source_id,
            external_id="keep",
        )
    )
    # A source that has imported something plainly finished setup, so it is not a
    # draft — and drafts are hidden from the list.
    db.get(DataSource, source_id).activated_at = datetime(2026, 8, 1, tzinfo=UTC)
    db.commit()
    return source_id


def test_removing_takes_it_out_of_the_list_and_keeps_the_facts(
    signed_in, db, metric, admin
):
    """**The action a test webhook needs.** Deleting is refused once anything was
    imported, so without this the list grew forever."""
    source_id = with_a_fact(signed_in, db, metric, admin)

    body = signed_in.post(f"/api/data-sources/{source_id}/archive").json()

    assert body["archived"] is True
    assert signed_in.get("/api/data-sources").json() == []
    assert len(db.scalars(select(MetricFact)).all()) == 1


def test_removing_forgets_the_credential(signed_in, db, metric, admin):
    """A webhook endpoint that still accepted deliveries after being removed would
    be a removal in name only."""
    source_id = with_a_fact(signed_in, db, metric, admin)
    token = credential_store.get(db, db.get(DataSource, source_id))["token"]

    signed_in.post(f"/api/data-sources/{source_id}/archive")

    assert signed_in.post(f"/api/hooks/{token}", json={"a": 1}).status_code == 404
    assert db.scalars(select(ConnectorCredential)).all() == []


def test_removing_stops_it_being_scheduled(signed_in, db, metric, admin):
    from app import sync as sync_service

    source_id = with_a_fact(signed_in, db, metric, admin)

    signed_in.post(f"/api/data-sources/{source_id}/archive")

    db.expire_all()
    assert db.get(DataSource, source_id).enabled is False
    assert sync_service.due(db) == []


def test_a_removed_source_is_not_scheduled_even_if_something_re_enables_it(
    signed_in, db, metric, admin
):
    """`due()` filters on archived as well as enabled. Belt and braces: "a removed
    integration does not run" must not depend on a second column staying in step."""
    from app import sync as sync_service

    source_id = with_a_fact(signed_in, db, metric, admin)
    signed_in.post(f"/api/data-sources/{source_id}/archive")

    db.get(DataSource, source_id).enabled = True
    db.commit()

    assert sync_service.due(db) == []


def test_a_removed_source_cannot_be_switched_back_on_without_restoring(
    signed_in, db, metric, admin
):
    """Otherwise it would run again, with no credential, from a page that does not
    show it."""
    source_id = with_a_fact(signed_in, db, metric, admin)
    signed_in.post(f"/api/data-sources/{source_id}/archive")

    response = signed_in.patch(
        f"/api/data-sources/{source_id}", json={"enabled": True}
    )

    assert response.status_code == 409
    assert "Restore it first" in response.json()["detail"]


def test_a_removed_source_can_still_be_renamed(signed_in, db, metric, admin):
    """Only resuming is refused. Tidying the name of something in the removed list
    is harmless, and refusing it would be a rule with no reason behind it."""
    source_id = with_a_fact(signed_in, db, metric, admin)
    signed_in.post(f"/api/data-sources/{source_id}/archive")

    response = signed_in.patch(
        f"/api/data-sources/{source_id}", json={"name": "Old Salesforce test"}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Old Salesforce test"


def test_removed_sources_are_listed_when_asked_for(signed_in, db, metric, admin):
    """Out of the way, not out of existence — this page is the one place somebody
    might want to see it again."""
    source_id = with_a_fact(signed_in, db, metric, admin)
    signed_in.post(f"/api/data-sources/{source_id}/archive")

    listed = signed_in.get("/api/data-sources?include_archived=true").json()

    assert [s["id"] for s in listed] == [source_id]
    assert listed[0]["archived"] is True


def test_restoring_brings_back_the_source_but_not_its_credential(
    signed_in, db, metric, admin
):
    """Archiving forgot the credential, so a restored source has nothing to connect
    with. Enabling it here would produce a source that fails on its next run and
    reports it as a failure rather than as the unfinished setup it is."""
    source_id = with_a_fact(signed_in, db, metric, admin)
    signed_in.post(f"/api/data-sources/{source_id}/archive")

    body = signed_in.post(f"/api/data-sources/{source_id}/restore").json()

    assert body["archived"] is False
    assert body["credentials_set"] is False
    assert body["enabled"] is False
    assert body["facts_written"] == 1
    assert len(signed_in.get("/api/data-sources").json()) == 1


def test_restoring_keeps_the_mappings(signed_in, db, metric, admin):
    """The part that would be painful to redo. Removing an integration is not a
    statement about what it was importing into."""
    source_id = with_a_fact(signed_in, db, metric, admin)
    signed_in.post(f"/api/data-sources/{source_id}/mappings", json=mapping_body(metric))
    signed_in.post(f"/api/data-sources/{source_id}/archive")

    body = signed_in.post(f"/api/data-sources/{source_id}/restore").json()

    assert [m["metric_name"] for m in body["mappings"]] == [metric.name]


def test_removing_is_audited_with_what_was_kept(signed_in, db, metric, admin):
    source_id = with_a_fact(signed_in, db, metric, admin)

    signed_in.post(f"/api/data-sources/{source_id}/archive")

    entry = db.scalars(
        select(AuditLog).where(AuditLog.action == "data_source.archived")
    ).first()
    assert entry.details["facts_kept"] == 1


def test_a_source_that_imported_nothing_is_still_deleted_outright(signed_in, db):
    """Nothing to keep provenance for, so there is no reason to leave a row behind
    — which is the common case for a webhook somebody set up and abandoned."""
    source_id = make_source(signed_in).json()["id"]

    assert signed_in.delete(f"/api/data-sources/{source_id}").status_code == 204
    assert db.get(DataSource, source_id) is None


# ── Test, discover, sync ─────────────────────────────────────────────────────


def test_a_failed_connection_test_is_a_200(signed_in, db):
    """A failed connection test is a successful *test*. A 4xx would make a browser
    treat a working feature as a broken request."""
    source_id = make_source(signed_in).json()["id"]
    signed_in.delete(f"/api/data-sources/{source_id}/credentials")

    response = signed_in.post(f"/api/data-sources/{source_id}/test")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "endpoint" in response.json()["detail"]


def test_a_configured_webhook_reports_ready(signed_in):
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.post(f"/api/data-sources/{source_id}/test")

    assert response.json()["ok"] is True


def test_an_unreadable_config_is_reported_rather_than_raised(signed_in, db):
    """The broad `except` earns its keep here. Stored config that its own schema now
    rejects — a hand-edited row, or a connector whose fields changed between builds
    — must come back as a failed test, not a 500. The Test button is the one place
    an admin goes to find out what is wrong; it cannot be the thing that breaks."""
    source_id = make_source(signed_in).json()["id"]
    db.get(DataSource, source_id).config = {"require_signature": "sometimes"}
    db.commit()

    response = signed_in.post(f"/api/data-sources/{source_id}/test")

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "ValidationError" in response.json()["detail"]


def test_discover_with_nothing_received_is_an_empty_list_not_an_error(signed_in):
    """A webhook that has not been posted to has no schema to report. That is why
    the setup flow asks for a test event before the mapping step."""
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.get(f"/api/data-sources/{source_id}/fields")

    assert response.status_code == 200
    assert response.json() == []


def test_discover_reads_the_last_delivery(signed_in, db, admin):
    from app.models import WebhookEvent

    source_id = make_source(signed_in).json()["id"]
    db.add(
        WebhookEvent(
            organization_id=admin.organization_id,
            data_source_id=source_id,
            payload={"owner": "a@b.c", "amount": 100},
        )
    )
    db.commit()

    fields = signed_in.get(f"/api/data-sources/{source_id}/fields").json()

    assert {f["name"]: f["kind"] for f in fields} == {
        "amount": "number",
        "owner": "email",
    }


def test_a_failed_sync_is_still_a_200_with_the_reason(signed_in, db):
    """A 500 would hide the very detail somebody clicked the button to see."""
    source_id = make_source(signed_in).json()["id"]
    source = db.get(DataSource, source_id)
    source.connector = "gone_away"
    db.commit()

    response = signed_in.post(f"/api/data-sources/{source_id}/sync")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "gone_away" in response.json()["error"]


def test_a_source_naming_a_missing_connector_says_so(signed_in, db):
    """A source configured on a newer build, or a connector deliberately removed.
    The UI has to say so rather than showing something that will never run."""
    source_id = make_source(signed_in).json()["id"]
    db.get(DataSource, source_id).connector = "gone_away"
    db.commit()

    body = signed_in.get(f"/api/data-sources/{source_id}").json()

    assert body["connector_missing"] is True


def test_sync_now_records_a_manual_run(signed_in, db):
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.post(f"/api/data-sources/{source_id}/sync")

    assert response.json()["trigger"] == "manual"
    assert signed_in.get(f"/api/data-sources/{source_id}").json()["recent_runs"]


# ── Mappings ─────────────────────────────────────────────────────────────────


def test_adding_a_mapping(signed_in, metric):
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.post(
        f"/api/data-sources/{source_id}/mappings", json=mapping_body(metric)
    )

    assert response.status_code == 201
    assert [m["metric_name"] for m in response.json()["mappings"]] == [metric.name]


def test_a_count_mapping_needs_no_value_column(signed_in, metric):
    """How a "deals won" metric works: the fact that a row exists is the
    measurement."""
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.post(
        f"/api/data-sources/{source_id}/mappings",
        json=mapping_body(metric, value_field=None),
    )

    assert response.status_code == 201
    assert response.json()["mappings"][0]["value_field"] is None


def test_two_mappings_for_one_metric_are_refused(signed_in, metric):
    """Two ways to compute the same number from the same place — and their external
    ids would collide in `metric_fact` anyway."""
    source_id = make_source(signed_in).json()["id"]
    signed_in.post(f"/api/data-sources/{source_id}/mappings", json=mapping_body(metric))

    response = signed_in.post(
        f"/api/data-sources/{source_id}/mappings", json=mapping_body(metric)
    )

    assert response.status_code == 409
    assert metric.name in response.json()["detail"]


def test_a_zero_multiplier_is_refused(signed_in, metric):
    """It would silently turn every measurement into nothing, which looks exactly
    like a broken integration."""
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.post(
        f"/api/data-sources/{source_id}/mappings",
        json=mapping_body(metric, multiplier="0"),
    )

    assert response.status_code == 422


def test_an_unknown_filter_operator_is_refused_with_the_valid_ones(signed_in, metric):
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.post(
        f"/api/data-sources/{source_id}/mappings",
        json=mapping_body(
            metric, filters=[{"field": "Stage", "op": "roughly", "value": "Won"}]
        ),
    )

    assert response.status_code == 422
    assert "contains" in json.dumps(response.json())


def test_a_filter_without_a_field_is_refused(signed_in, metric):
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.post(
        f"/api/data-sources/{source_id}/mappings",
        json=mapping_body(metric, filters=[{"op": "eq", "value": "Won"}]),
    )

    assert response.status_code == 422


def test_an_archived_metric_cannot_be_imported_into(signed_in, db, metric):
    source_id = make_source(signed_in).json()["id"]
    metric.archived_at = datetime.now(UTC)
    db.commit()

    response = signed_in.post(
        f"/api/data-sources/{source_id}/mappings", json=mapping_body(metric)
    )

    assert response.status_code == 409
    assert "archived" in response.json()["detail"]


def test_a_mapping_cannot_change_which_metric_it_feeds(signed_in, metric, make_metric):
    """Its imported facts belong to the old one."""
    other = make_metric("deals_won")
    source_id = make_source(signed_in).json()["id"]
    created = signed_in.post(
        f"/api/data-sources/{source_id}/mappings", json=mapping_body(metric)
    ).json()
    mapping_id = created["mappings"][0]["id"]

    response = signed_in.patch(
        f"/api/data-sources/{source_id}/mappings/{mapping_id}",
        json=mapping_body(other),
    )

    assert response.status_code == 400
    assert "cannot change which metric" in response.json()["detail"]


def test_editing_a_mapping_changes_future_syncs_only(signed_in, db, metric, admin):
    """A leaderboard for last month should not move because somebody fixed a mapping
    today."""
    source_id = make_source(signed_in).json()["id"]
    created = signed_in.post(
        f"/api/data-sources/{source_id}/mappings", json=mapping_body(metric)
    ).json()
    mapping_id = created["mappings"][0]["id"]
    db.add(
        MetricFact(
            organization_id=admin.organization_id,
            metric_definition_id=metric.id,
            subject_user_id=admin.id,
            value=Decimal(100),
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
            source_type="connector",
            data_source_id=source_id,
            external_id="old",
        )
    )
    db.commit()

    signed_in.patch(
        f"/api/data-sources/{source_id}/mappings/{mapping_id}",
        json=mapping_body(metric, multiplier="0.01"),
    )

    kept = db.scalars(select(MetricFact)).all()
    assert [f.value for f in kept] == [Decimal(100)]


def test_deleting_a_mapping_keeps_what_it_imported(signed_in, db, metric, admin):
    """Removing a mapping says "stop adding more", not "that never happened" — and a
    settled competition may have been decided on those numbers."""
    source_id = make_source(signed_in).json()["id"]
    created = signed_in.post(
        f"/api/data-sources/{source_id}/mappings", json=mapping_body(metric)
    ).json()
    mapping_id = created["mappings"][0]["id"]
    db.add(
        MetricFact(
            organization_id=admin.organization_id,
            metric_definition_id=metric.id,
            subject_user_id=admin.id,
            value=Decimal(100),
            occurred_at=datetime(2026, 8, 1, tzinfo=UTC),
            source_type="connector",
            data_source_id=source_id,
            external_id="old",
        )
    )
    db.commit()

    response = signed_in.delete(
        f"/api/data-sources/{source_id}/mappings/{mapping_id}"
    )

    assert response.json()["mappings"] == []
    assert len(db.scalars(select(MetricFact)).all()) == 1


def test_another_organizations_metric_is_not_found(signed_in, db):
    """A source cannot be pointed at a metric belonging to somebody else's
    deployment — it would write facts into their leaderboards."""
    from app.models import MetricDefinition, Organization

    other = Organization(name="Rival", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = MetricDefinition(
        organization_id=other.id,
        key="their_revenue",
        name="Their Revenue",
        aggregation="sum",
        direction="higher_is_better",
    )
    db.add(theirs)
    db.commit()
    source_id = make_source(signed_in).json()["id"]

    response = signed_in.post(
        f"/api/data-sources/{source_id}/mappings",
        json=mapping_body(theirs),
    )

    assert response.status_code == 404


def test_another_sources_mapping_is_not_found(signed_in, metric):
    """The path names two things; checking only the second would let one source edit
    another's mapping."""
    mine = make_source(signed_in, name="Mine").json()["id"]
    theirs = make_source(signed_in, name="Theirs").json()["id"]
    created = signed_in.post(
        f"/api/data-sources/{theirs}/mappings", json=mapping_body(metric)
    ).json()
    mapping_id = created["mappings"][0]["id"]

    response = signed_in.delete(f"/api/data-sources/{mine}/mappings/{mapping_id}")

    assert response.status_code == 404


# ── Preview ──────────────────────────────────────────────────────────────────


def test_preview_shows_rows_as_the_facts_they_would_become(
    signed_in, db, metric, admin, make_user
):
    """The most useful thing on the page: a mapping error in three seconds rather
    than after forty thousand wrong rows."""
    from app.models import WebhookEvent

    alice = make_user("agent", None, name="Alice")
    source_id = make_source(signed_in).json()["id"]
    created = signed_in.post(
        f"/api/data-sources/{source_id}/mappings", json=mapping_body(metric)
    ).json()
    mapping_id = created["mappings"][0]["id"]
    db.add(
        WebhookEvent(
            organization_id=admin.organization_id,
            data_source_id=source_id,
            event_id="e1",
            payload={"owner": alice.email, "amount": "1,200.50", "closed_at": "2026-08-07"},
        )
    )
    db.commit()

    rows = signed_in.post(
        f"/api/data-sources/{source_id}/mappings/{mapping_id}/preview"
    ).json()

    assert len(rows) == 1
    assert rows[0]["outcome"] == "written"
    assert rows[0]["subject_name"] == "Alice"
    assert Decimal(rows[0]["value"]) == Decimal("1200.50")


def test_preview_writes_nothing(signed_in, db, metric, admin):
    """A preview that created a quarantine queue as a side effect of being looked at
    would be a nasty surprise."""
    from app.models import WebhookEvent

    source_id = make_source(signed_in).json()["id"]
    created = signed_in.post(
        f"/api/data-sources/{source_id}/mappings", json=mapping_body(metric)
    ).json()
    mapping_id = created["mappings"][0]["id"]
    db.add(
        WebhookEvent(
            organization_id=admin.organization_id,
            data_source_id=source_id,
            payload={"owner": "stranger@nowhere.test", "amount": 1, "closed_at": "2026-08-07"},
        )
    )
    db.commit()

    signed_in.post(f"/api/data-sources/{source_id}/mappings/{mapping_id}/preview")

    assert db.scalars(select(MetricFact)).all() == []
    assert db.scalars(select(UserIdentity)).all() == []


# ── Quarantine ───────────────────────────────────────────────────────────────


def test_the_quarantine_list_is_busiest_first(signed_in, db, admin):
    source_id = make_source(signed_in).json()["id"]
    for identifier, rows in (("quiet@x.test", 1), ("busy@x.test", 9)):
        db.add(
            UserIdentity(
                organization_id=admin.organization_id,
                data_source_id=source_id,
                external_identifier=identifier,
                pending_rows=rows,
            )
        )
    db.commit()

    found = signed_in.get(f"/api/data-sources/{source_id}/identities").json()

    assert [i["external_identifier"] for i in found] == ["busy@x.test", "quiet@x.test"]


def test_mapping_an_identifier_removes_it_from_the_list(
    signed_in, db, admin, make_user
):
    alice = make_user("agent", None, name="Alice")
    source_id = make_source(signed_in).json()["id"]
    db.add(
        UserIdentity(
            organization_id=admin.organization_id,
            data_source_id=source_id,
            external_identifier="0051x",
            pending_rows=4,
        )
    )
    db.commit()
    waiting = signed_in.get(f"/api/data-sources/{source_id}/identities").json()[0]

    response = signed_in.post(
        f"/api/data-sources/{source_id}/identities/{waiting['id']}/map",
        json={"user_id": alice.id},
    )

    assert response.json() == []


def test_ignoring_an_identifier_removes_it_from_the_list(signed_in, db, admin):
    source_id = make_source(signed_in).json()["id"]
    db.add(
        UserIdentity(
            organization_id=admin.organization_id,
            data_source_id=source_id,
            external_identifier="integration@x.test",
            pending_rows=200,
        )
    )
    db.commit()
    waiting = signed_in.get(f"/api/data-sources/{source_id}/identities").json()[0]

    response = signed_in.post(
        f"/api/data-sources/{source_id}/identities/{waiting['id']}/ignore"
    )

    assert response.json() == []


def test_ignoring_the_rest_clears_the_whole_tail(signed_in, db, admin):
    """**What a warehouse with history always produces.**

    A view of sales going back years names everybody who ever worked here, and
    the ones who left will never match. They are not questions anybody can
    answer, but they arrive looking exactly like questions — and three hundred of
    them is not a list somebody works through one row at a time.
    """
    source_id = make_source(signed_in).json()["id"]
    for n in range(5):
        db.add(
            UserIdentity(
                organization_id=admin.organization_id,
                data_source_id=source_id,
                external_identifier=f"gone{n}@x.test",
                pending_rows=10,
            )
        )
    db.commit()
    assert len(signed_in.get(f"/api/data-sources/{source_id}/identities").json()) == 5

    response = signed_in.post(f"/api/data-sources/{source_id}/identities/ignore-rest")

    assert response.status_code == 200
    assert response.json() == []


def test_ignoring_the_rest_leaves_answered_ones_alone(signed_in, db, admin):
    """It clears the *questions*, not the decisions already taken."""
    source_id = make_source(signed_in).json()["id"]
    db.add(
        UserIdentity(
            organization_id=admin.organization_id,
            data_source_id=source_id,
            external_identifier="known@x.test",
            user_id=admin.id,
        )
    )
    db.add(
        UserIdentity(
            organization_id=admin.organization_id,
            data_source_id=source_id,
            external_identifier="gone@x.test",
            pending_rows=4,
        )
    )
    db.commit()

    signed_in.post(f"/api/data-sources/{source_id}/identities/ignore-rest")

    from sqlalchemy import select

    kept = db.scalar(
        select(UserIdentity).where(UserIdentity.external_identifier == "known@x.test")
    )
    db.refresh(kept)
    assert kept.user_id == admin.id
    assert kept.ignored is False


def test_only_an_admin_may_ignore_the_rest(client, db, make_user, sign_in, signed_in):
    """Silencing a source's questions is not a manager-level decision."""
    source_id = make_source(signed_in).json()["id"]
    db.commit()
    sign_in(make_user("manager"))

    reply = client.post(f"/api/data-sources/{source_id}/identities/ignore-rest")

    assert reply.status_code == 403


def test_mapping_to_somebody_outside_the_organization_is_refused(
    signed_in, db, admin
):
    from app.models import Organization, UserAccount

    other = Organization(name="Rival", timezone="UTC")
    db.add(other)
    db.flush()
    stranger = UserAccount(
        organization_id=other.id,
        email="them@rival.test",
        full_name="Them",
        org_role="agent",
        status="active",
    )
    db.add(stranger)
    source_id = make_source(signed_in).json()["id"]
    db.add(
        UserIdentity(
            organization_id=admin.organization_id,
            data_source_id=source_id,
            external_identifier="x",
            pending_rows=1,
        )
    )
    db.commit()
    waiting = signed_in.get(f"/api/data-sources/{source_id}/identities").json()[0]

    response = signed_in.post(
        f"/api/data-sources/{source_id}/identities/{waiting['id']}/map",
        json={"user_id": stranger.id},
    )

    assert response.status_code == 404


def test_the_badge_count_matches_the_list(signed_in, db, admin, make_user):
    """Three waiting, one already answered, one ignored — the badge must count only
    the questions still open, or it nags about work that is done."""
    alice = make_user("agent", None, name="Alice")
    source_id = make_source(signed_in).json()["id"]
    for i in range(3):
        db.add(
            UserIdentity(
                organization_id=admin.organization_id,
                data_source_id=source_id,
                external_identifier=f"p{i}@x.test",
                pending_rows=1,
            )
        )
    db.add(
        UserIdentity(
            organization_id=admin.organization_id,
            data_source_id=source_id,
            external_identifier="known@x.test",
            user_id=alice.id,
        )
    )
    db.add(
        UserIdentity(
            organization_id=admin.organization_id,
            data_source_id=source_id,
            external_identifier="robot@x.test",
            ignored=True,
        )
    )
    db.commit()

    body = signed_in.get(f"/api/data-sources/{source_id}").json()

    assert body["pending_identities"] == 3
    assert len(body["mappings"]) == 0  # unrelated, and the counts must not cross


def test_ignoring_an_identifier_clears_the_badge_too(signed_in, db, admin):
    """The list and the badge are two queries. Two places computing the same thing
    is two places that drift."""
    source_id = make_source(signed_in).json()["id"]
    db.add(
        UserIdentity(
            organization_id=admin.organization_id,
            data_source_id=source_id,
            external_identifier="robot@x.test",
            pending_rows=40,
        )
    )
    db.commit()
    waiting = signed_in.get(f"/api/data-sources/{source_id}/identities").json()[0]

    signed_in.post(
        f"/api/data-sources/{source_id}/identities/{waiting['id']}/ignore"
    )

    assert signed_in.get(f"/api/data-sources/{source_id}").json()[
        "pending_identities"
    ] == 0


def test_another_sources_identity_is_not_found(signed_in, db, admin, make_user):
    """The path names a source and an identifier. Checking only the second would let
    one source answer another's question — and the answer is stored per source,
    because the same person is a different identifier in each system."""
    alice = make_user("agent", None, name="Alice")
    mine = make_source(signed_in, name="Mine").json()["id"]
    theirs = make_source(signed_in, name="Theirs").json()["id"]
    db.add(
        UserIdentity(
            organization_id=admin.organization_id,
            data_source_id=theirs,
            external_identifier="0051x",
            pending_rows=4,
        )
    )
    db.commit()
    waiting = signed_in.get(f"/api/data-sources/{theirs}/identities").json()[0]

    mapped = signed_in.post(
        f"/api/data-sources/{mine}/identities/{waiting['id']}/map",
        json={"user_id": alice.id},
    )
    ignored = signed_in.post(
        f"/api/data-sources/{mine}/identities/{waiting['id']}/ignore"
    )

    assert mapped.status_code == 404
    assert ignored.status_code == 404


def test_another_organizations_source_is_not_found(signed_in, db):
    from app.models import Organization

    other = Organization(name="Rival", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = DataSource(
        organization_id=other.id, name="Theirs", connector="webhook"
    )
    db.add(theirs)
    db.commit()

    assert signed_in.get(f"/api/data-sources/{theirs.id}").status_code == 404
    assert signed_in.get("/api/data-sources").json() == []
