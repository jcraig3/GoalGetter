"""Signing in to a provider, and staying signed in.

**Driven by a fake provider**, for the same reason the pipeline was driven by a
stub connector: the framework should be proven before a real provider's quirks are
in the way. Google's actual endpoints arrive with the Sheets connector; what is
under test here is the dance, the storage, and the renewal.

The two properties worth being most suspicious about: that a client secret can
never come back out, and that a refresh does not throw away the refresh token —
because that failure works for an hour and then stops for good.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app import connectors, credentials as credential_store, oauth
from app.models import AuditLog, DataSource, OauthClient
from app.oauth import OAuthProblem, OAuthSpec

SPEC = OAuthSpec(
    provider="fakeprov",
    provider_name="FakeProv",
    authorize_url="https://fakeprov.test/authorize",
    token_url="https://fakeprov.test/token",
    scopes=("read.rows", "read.metadata"),
    extra_authorize_params=(("access_type", "offline"), ("prompt", "consent")),
)

NOW = datetime(2026, 8, 21, 12, tzinfo=UTC)


@pytest.fixture
def admin(make_user):
    return make_user("admin", name="Admin")


@pytest.fixture
def signed_in(client, db, admin, sign_in):
    sign_in(admin)
    db.commit()
    return client


@pytest.fixture
def fake_connector(registry_slot):
    """A connector that signs in, registered for one test."""
    from pydantic import BaseModel

    class Nothing(BaseModel):
        pass

    class Tokens(BaseModel):
        access_token: str = ""
        refresh_token: str = ""

    class FakeConnector:
        key = "fakeprov_rows"
        display_name = "FakeProv Rows"
        config_schema = Nothing
        credential_schema = Tokens
        oauth = SPEC

        def test_connection(self, config, credentials):
            return connectors.ConnectionResult(
                ok=bool(credentials.access_token), detail="checked"
            )

        def discover(self, config, credentials, *, local=None):
            return []

        def fetch(self, config, credentials, since=None, *, local=None):
            return iter(())

    connectors._REGISTRY["fakeprov_rows"] = FakeConnector()
    return FakeConnector


@pytest.fixture
def registered(db, org, admin):
    """A stored client registration for the fake provider."""
    return oauth.store_client(
        db,
        org_id=org.id,
        provider="fakeprov",
        client_id="client-123",
        client_secret="shhh-secret",
        actor_id=admin.id,
    )


def make_source(db, org, connector="fakeprov_rows") -> DataSource:
    row = DataSource(organization_id=org.id, name="Rows", connector=connector)
    db.add(row)
    db.flush()
    return row


# ── Registering the application ──────────────────────────────────────────────


def test_a_providers_registration_appears_because_a_connector_needs_it(
    signed_in, fake_connector
):
    """Derived from the connectors, not from a list. A settings page offering a
    registration nothing can use invites somebody to do pointless work."""
    listed = {p["provider"]: p for p in signed_in.get("/api/integrations/oauth-clients").json()}

    assert listed["fakeprov"]["used_by"] == ["FakeProv Rows"]
    assert listed["fakeprov"]["scopes"] == ["read.rows", "read.metadata"]


def test_every_provider_a_connector_signs_in_to_is_offered(signed_in):
    """The property, rather than a census that has to be edited every time a
    connector ships. Google is on this list because Google Sheets is in the build;
    if Sheets were removed, so would Google be.

    **A superset now, not an equality.** This asserted `==` until connections
    stopped being connector registrations: an identity provider we ship no
    connector for still needs somewhere to put its client id, so the list is the
    catalogue *plus* whatever the connectors name. The direction that matters is
    unchanged — a connector must never declare a provider nobody can register.
    """
    from app import connectors
    from app.oauth import OAuthSpec

    expected = set()
    for connector in connectors.available():
        spec = connectors.oauth_of(connector)
        if isinstance(spec, OAuthSpec):
            expected.add(spec.provider)

    listed = {p["provider"] for p in signed_in.get("/api/integrations/oauth-clients").json()}

    assert expected <= listed


def test_a_provider_with_no_connector_is_still_offered_for_signing_in(signed_in):
    """The other half, and the reason the equality above had to go.

    Sign-on has always been provider-agnostic — Okta, Auth0, Keycloak. Folding the
    credential onto `oauth_client` must not quietly narrow that to "Microsoft or
    Google", so a generic OIDC connection is offered even though no connector will
    ever name it.
    """
    listed = {p["provider"]: p for p in signed_in.get("/api/integrations/oauth-clients").json()}

    assert "oidc" in listed
    assert listed["oidc"]["used_by"] == []
    assert [c["key"] for c in listed["oidc"]["capabilities"]] == ["sso"]
    # It cannot derive an issuer, so it has to ask for one.
    assert listed["oidc"]["issuer_required"] is True


def test_microsoft_offers_signing_in_and_data_on_one_credential(signed_in):
    """**The whole point of 3e, asserted.** One connection, several capabilities —
    rather than one client id and secret for SSO and a second copy of the same two
    values for Excel."""
    listed = {p["provider"]: p for p in signed_in.get("/api/integrations/oauth-clients").json()}
    microsoft = listed["microsoft"]

    offered = {c["key"] for c in microsoft["capabilities"]}

    assert {"sso", "data"} <= offered
    # And the setup panel asks for both callbacks, because one registration holds
    # several and pasting only one is the failure that looks like a broken login.
    assert any(u.endswith("/api/auth/sso/callback") for u in microsoft["redirect_uris"])
    assert any(
        u.endswith("/api/integrations/oauth/callback") for u in microsoft["redirect_uris"]
    )


def test_a_capability_that_is_not_built_says_so_rather_than_hiding(signed_in):
    """Designed but not built is shown greyed, not omitted. An admin asking "can
    this send our invitations?" should find the answer even when it is "not yet" —
    the same rule the SMTP card already follows.

    **Repointed twice now, both times for the best possible reason.** It asserted
    on Microsoft's `directory` until 3d shipped, then on Microsoft's `email` until
    that shipped too. Google's directory sync is the unfinished one — and the rule
    being protected was never about which feature is unbuilt, only that an unbuilt
    one is shown greyed rather than hidden.
    """
    listed = {p["provider"]: p for p in signed_in.get("/api/integrations/oauth-clients").json()}
    unbuilt = next(c for c in listed["google"]["capabilities"] if c["key"] == "directory")

    assert unbuilt["built"] is False
    assert unbuilt["active"] is False


def test_every_microsoft_capability_ships_now(signed_in):
    """The counterpart, and worth an assertion of its own: an unbuilt capability is
    left out of the permissions an application is told to ask for, so the flag
    lying costs a registration that cannot do the thing it was made for."""
    listed = {p["provider"]: p for p in signed_in.get("/api/integrations/oauth-clients").json()}

    assert all(c["built"] for c in listed["microsoft"]["capabilities"])


def test_directory_sync_is_offered_now_that_it_is_built(signed_in):
    """The other half of the flag, and the reason it is worth a test of its own.

    **An unbuilt capability is left out of the permissions to grant**, so while
    this said False the app registration came out without `User.Read.All` and
    every sync would have failed with a 403 pointing at nothing in particular.
    The greying is cosmetic; this is not.
    """
    listed = {p["provider"]: p for p in signed_in.get("/api/integrations/oauth-clients").json()}
    directory = next(
        c for c in listed["microsoft"]["capabilities"] if c["key"] == "directory"
    )

    assert directory["built"] is True
    assert "User.Read.All" in listed["microsoft"]["scopes"]
    assert "GroupMember.Read.All" in listed["microsoft"]["scopes"]


def test_google_is_offered_because_sheets_ships(signed_in):
    """A concrete anchor for the rule above: the first real provider in the build.
    If this ever fails, either Sheets stopped declaring its sign-in or the
    derivation broke — and both are worth knowing about."""
    listed = {p["provider"]: p for p in signed_in.get("/api/integrations/oauth-clients").json()}

    assert "google" in listed
    assert listed["google"]["used_by"] == ["Google Sheets"]


def test_the_redirect_uris_are_shown_because_a_mismatch_is_unreadable(
    signed_in, fake_connector
):
    """They have to be pasted into the provider's console character for character,
    and the error a provider returns for a mismatch does not say what it expected.

    Plural since one registration can serve several flows — the panel lists the
    ones this connection actually needs rather than every callback that exists.
    """
    from app.config import get_settings

    listed = {p["provider"]: p for p in signed_in.get("/api/integrations/oauth-clients").json()}
    uris = listed["fakeprov"]["redirect_uris"]
    origin = get_settings().app_url.rstrip("/")

    assert uris == [f"{origin}/api/integrations/oauth/callback"]
    assert all(u.startswith("http") for u in uris)


def test_saving_a_registration(signed_in, fake_connector):
    response = signed_in.put(
        "/api/integrations/oauth-clients/fakeprov",
        json={"client_id": "client-123", "client_secret": "shhh"},
    )

    assert response.status_code == 200
    assert response.json()["client_id"] == "client-123"
    assert response.json()["client_secret_set"] is True


def test_the_client_secret_never_comes_back(signed_in, fake_connector):
    """**The property to be most suspicious about.** There is no legitimate reason
    for a browser to receive it, and any mechanism that shows one can be made to."""
    signed_in.put(
        "/api/integrations/oauth-clients/fakeprov",
        json={"client_id": "client-123", "client_secret": "shhh-do-not-leak"},
    )

    for path in ("/api/integrations/oauth-clients",):
        assert "shhh-do-not-leak" not in signed_in.get(path).text


def test_the_secret_is_kept_when_only_the_client_id_changes(
    signed_in, db, fake_connector, org
):
    """Somebody fixing a typo in the client ID should not have to go and find the
    secret again."""
    signed_in.put(
        "/api/integrations/oauth-clients/fakeprov",
        json={"client_id": "wrong", "client_secret": "shhh"},
    )

    signed_in.put(
        "/api/integrations/oauth-clients/fakeprov", json={"client_id": "right"}
    )

    db.expire_all()
    row = db.scalar(select(OauthClient).where(OauthClient.provider == "fakeprov"))
    assert row.client_id == "right"
    assert oauth.secret_of(row) == "shhh"


def test_an_empty_secret_is_refused_rather_than_meaning_keep(signed_in, fake_connector):
    """An empty box that silently means "no change" is a box somebody will use to
    try to clear the value. Omitting the field is how "keep it" is said."""
    response = signed_in.put(
        "/api/integrations/oauth-clients/fakeprov",
        json={"client_id": "client-123", "client_secret": ""},
    )

    assert response.status_code == 422


def test_the_first_save_needs_a_secret(signed_in, fake_connector):
    response = signed_in.put(
        "/api/integrations/oauth-clients/fakeprov", json={"client_id": "client-123"}
    )

    assert response.status_code == 422
    assert "first time" in response.json()["detail"]


def test_a_provider_nothing_signs_in_to_is_refused_by_name(signed_in, fake_connector):
    response = signed_in.put(
        "/api/integrations/oauth-clients/dropbox",
        json={"client_id": "x", "client_secret": "y"},
    )

    assert response.status_code == 404
    assert "fakeprov" in response.json()["detail"]


def test_saving_is_audited_without_the_secret(signed_in, db, fake_connector):
    signed_in.put(
        "/api/integrations/oauth-clients/fakeprov",
        json={"client_id": "client-123", "client_secret": "shhh"},
    )

    entry = db.scalars(
        select(AuditLog).where(AuditLog.action == "oauth_client.saved")
    ).first()
    assert entry.details["provider"] == "fakeprov"
    assert entry.details["secret_changed"] is True
    assert "shhh" not in str(entry.details)


def test_the_audit_entry_says_when_the_secret_was_left_alone(
    signed_in, db, fake_connector
):
    """Otherwise the log claims every edit touched the secret, and "when did this
    secret last change" becomes unanswerable."""
    signed_in.put(
        "/api/integrations/oauth-clients/fakeprov",
        json={"client_id": "one", "client_secret": "shhh"},
    )
    signed_in.put("/api/integrations/oauth-clients/fakeprov", json={"client_id": "two"})

    entries = db.scalars(
        select(AuditLog)
        .where(AuditLog.action == "oauth_client.saved")
        .order_by(AuditLog.id)
    ).all()
    assert [e.details["secret_changed"] for e in entries] == [True, False]


def test_forgetting_a_registration_leaves_existing_sources_alone(
    signed_in, db, org, fake_connector, registered
):
    """Revoking live sources as a side effect of tidying up Settings would be a
    much worse surprise than a sync that stops and says why."""
    source = make_source(db, org)
    credential_store.put(db, source, {"access_token": "at", "refresh_token": "rt"})
    db.commit()

    assert signed_in.delete("/api/integrations/oauth-clients/fakeprov").status_code == 204

    db.expire_all()
    assert credential_store.get(db, source)["access_token"] == "at"


def test_only_an_admin_may_register(client, db, make_user, sign_in):
    sign_in(make_user("manager", None, name="Manager"))
    db.commit()

    assert client.get("/api/integrations/oauth-clients").status_code == 403


def test_another_organizations_registration_is_not_visible(
    signed_in, db, fake_connector
):
    from app.models import Organization

    other = Organization(name="Rival", timezone="UTC")
    db.add(other)
    db.flush()
    oauth.store_client(
        db, org_id=other.id, provider="fakeprov", client_id="theirs",
        client_secret="theirs", actor_id=None,
    )
    db.commit()

    listed = signed_in.get("/api/integrations/oauth-clients").json()

    assert listed[0]["client_id"] is None
    assert listed[0]["client_secret_set"] is False


# ── Starting the sign-in ─────────────────────────────────────────────────────


def test_authorize_returns_the_url_rather_than_redirecting(
    signed_in, db, org, fake_connector, registered
):
    """The caller is `fetch` from a single-page app. A 303 would be followed inside
    the XHR and the consent screen would arrive as a JSON parse error."""
    source = make_source(db, org)
    db.commit()

    response = signed_in.post(f"/api/data-sources/{source.id}/authorize")

    assert response.status_code == 200
    assert response.json()["url"].startswith("https://fakeprov.test/authorize?")


def test_the_authorization_url_carries_what_the_provider_needs(
    signed_in, db, org, fake_connector, registered
):
    from urllib.parse import parse_qs, urlparse

    source = make_source(db, org)
    db.commit()

    url = signed_in.post(f"/api/data-sources/{source.id}/authorize").json()["url"]
    params = parse_qs(urlparse(url).query)

    assert params["client_id"] == ["client-123"]
    assert params["scope"] == ["read.rows read.metadata"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["response_type"] == ["code"]
    # Without these two the provider issues no refresh token, and the source works
    # until the first expiry and then stops for good.
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]


def held_flow(response) -> dict:
    """What the flow cookie is carrying, opened the way the callback opens it."""
    import json as json_module

    from app.crypto import decrypt

    from app.routers.oauth_clients import FLOW_COOKIE

    return json_module.loads(decrypt(response.cookies[FLOW_COOKIE]))


def test_the_provider_is_sent_the_hash_and_never_the_verifier(
    signed_in, db, org, fake_connector, registered
):
    """**The whole point of PKCE**, and the assertion has to be this specific: an
    earlier version of this test looked for the string `code_verifier` in the URL,
    which is the *parameter name* and is absent whether the value sent is the hash
    or the secret itself.
    """
    import base64
    import hashlib
    from urllib.parse import parse_qs, urlparse

    source = make_source(db, org)
    db.commit()

    response = signed_in.post(f"/api/data-sources/{source.id}/authorize")
    params = parse_qs(urlparse(response.json()["url"]).query)
    verifier = held_flow(response)["verifier"]

    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    assert params["code_challenge"] == [expected]
    assert verifier not in response.json()["url"]


def test_the_state_sent_is_the_state_the_cookie_will_be_checked_against(
    signed_in, db, org, fake_connector, registered
):
    """Sending no state at all leaves nothing to match the response against, and
    the callback's check then compares two empty strings and passes."""
    from urllib.parse import parse_qs, urlparse

    source = make_source(db, org)
    db.commit()

    response = signed_in.post(f"/api/data-sources/{source.id}/authorize")
    params = parse_qs(urlparse(response.json()["url"]).query)

    assert params["state"] == [held_flow(response)["state"]]
    assert params["state"][0]


def test_the_flow_cookie_is_not_readable_by_scripts(
    signed_in, db, org, fake_connector, registered
):
    """It holds the PKCE verifier. Anything that can read it and see the code can
    complete the exchange."""
    source = make_source(db, org)
    db.commit()

    response = signed_in.post(f"/api/data-sources/{source.id}/authorize")

    header = response.headers["set-cookie"]
    assert "HttpOnly" in header
    # Scoped to the one path that consumes it, so it is not attached to every
    # request the browser makes.
    assert "Path=/api/integrations/oauth/callback" in header


def test_authorizing_without_a_registration_says_what_to_do(
    signed_in, db, org, fake_connector
):
    """By far the most likely reason an OAuth connector does not work, and it has a
    specific fix — so it gets its own message rather than a generic failure."""
    source = make_source(db, org)
    db.commit()

    response = signed_in.post(f"/api/data-sources/{source.id}/authorize")

    assert response.status_code == 409
    assert "No fakeprov application is registered" in response.json()["detail"]
    # And says where to do it, since that is the whole fix.
    assert "Integrations page" in response.json()["detail"]


def test_a_connector_that_signs_in_to_nothing_cannot_be_authorized(
    signed_in, db, org
):
    source = make_source(db, org, connector="webhook")
    db.commit()

    response = signed_in.post(f"/api/data-sources/{source.id}/authorize")

    assert response.status_code == 409
    assert "does not sign in" in response.json()["detail"]


def test_one_organizations_registration_does_not_authorize_anothers_source(
    signed_in, db, org, fake_connector
):
    """A cross-tenant hole with no test on it: another organization having
    registered the same provider must not let this one sign in with it."""
    from app.models import Organization

    other = Organization(name="Rival", timezone="UTC")
    db.add(other)
    db.flush()
    oauth.store_client(
        db, org_id=other.id, provider="fakeprov", client_id="theirs",
        client_secret="theirs", actor_id=None,
    )
    source = make_source(db, org)
    db.commit()

    response = signed_in.post(f"/api/data-sources/{source.id}/authorize")

    assert response.status_code == 409
    assert "No fakeprov application is registered" in response.json()["detail"]


def test_another_organizations_source_cannot_be_authorized(
    signed_in, db, fake_connector, registered
):
    from app.models import Organization

    other = Organization(name="Rival", timezone="UTC")
    db.add(other)
    db.flush()
    theirs = make_source(db, other)
    db.commit()

    assert signed_in.post(f"/api/data-sources/{theirs.id}/authorize").status_code == 404


# ── Storing what came back ───────────────────────────────────────────────────


def test_tokens_are_stored_with_an_expiry_readable_without_decrypting(
    db, org, admin, registered
):
    """`expires_at` in the clear is what lets the scheduler ask "does this need
    renewing?" on every pass without decrypting every credential."""
    source = make_source(db, org)

    oauth.save_tokens(
        db, source, registered,
        {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600},
        now=NOW,
    )

    assert credential_store.get(db, source)["access_token"] == "at-1"
    assert credential_store.expires_at(db, source) == NOW + timedelta(hours=1)


def test_a_provider_that_gives_no_lifetime_gets_a_conservative_one(
    db, org, registered
):
    """Guessing too short costs an extra refresh; too long costs a failed sync."""
    source = make_source(db, org)

    oauth.save_tokens(db, source, registered, {"access_token": "at"}, now=NOW)

    assert credential_store.expires_at(db, source) == NOW + oauth.DEFAULT_LIFETIME


def test_a_nonsense_lifetime_is_treated_as_absent(db, org, registered):
    """`expires_in: "soon"` is a real thing providers send."""
    source = make_source(db, org)

    oauth.save_tokens(
        db, source, registered, {"access_token": "at", "expires_in": "soon"}, now=NOW
    )

    assert credential_store.expires_at(db, source) == NOW + oauth.DEFAULT_LIFETIME


def test_saving_records_that_the_registration_works(db, org, registered):
    """"We pasted these in three months ago and nothing has ever worked" and "these
    worked until Tuesday" are different problems."""
    source = make_source(db, org)

    oauth.save_tokens(db, source, registered, {"access_token": "at"}, now=NOW)

    assert registered.last_used_at == NOW


# ── Renewing ─────────────────────────────────────────────────────────────────


def test_a_refresh_keeps_the_refresh_token_the_provider_did_not_resend(
    db, org, registered, monkeypatch
):
    """**The bug that works for an hour and then stops for good.** A refresh
    response is usually just an access token; replacing the stored credential
    would discard the only thing that can renew the next one."""
    source = make_source(db, org)
    oauth.save_tokens(
        db, source, registered,
        {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600},
        now=NOW,
    )

    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: httpx.Response(
            200, json={"access_token": "at-2", "expires_in": 3600}
        ),
    )

    oauth.refresh(db, source, SPEC, now=NOW + timedelta(hours=1))

    stored = credential_store.get(db, source)
    assert stored["access_token"] == "at-2"
    assert stored["refresh_token"] == "rt-1"


def test_a_rotated_refresh_token_replaces_the_old_one(db, org, registered, monkeypatch):
    """The other half: a provider that rotates sends a new one, and merging must
    not pin the stale value."""
    source = make_source(db, org)
    oauth.save_tokens(
        db, source, registered, {"access_token": "at-1", "refresh_token": "rt-1"},
        now=NOW,
    )

    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: httpx.Response(
            200, json={"access_token": "at-2", "refresh_token": "rt-2"}
        ),
    )

    oauth.refresh(db, source, SPEC, now=NOW)

    assert credential_store.get(db, source)["refresh_token"] == "rt-2"


def test_a_refresh_without_a_stored_refresh_token_says_to_reconnect(db, org, registered):
    source = make_source(db, org)
    credential_store.put(db, source, {"access_token": "at"})

    with pytest.raises(OAuthProblem, match="Reconnect"):
        oauth.refresh(db, source, SPEC)


def test_a_refused_refresh_does_not_leak_what_was_sent(db, org, registered, monkeypatch):
    """A provider's error body can echo the request back, and the request included
    the client secret."""
    source = make_source(db, org)
    oauth.save_tokens(db, source, registered, {"refresh_token": "rt-1"}, now=NOW)

    monkeypatch.setattr(
        oauth.httpx,
        "post",
        lambda *a, **k: httpx.Response(
            400, json={"error": "invalid_grant", "sent": "shhh-secret"}
        ),
    )

    with pytest.raises(OAuthProblem) as raised:
        oauth.refresh(db, source, SPEC)

    assert "shhh-secret" not in str(raised.value)
    assert "400" in str(raised.value)
    assert "FakeProv" in str(raised.value)


def test_a_missing_registration_is_reported_when_renewing(db, org, monkeypatch):
    """The registration can be removed after a source is connected. The source then
    fails with a message naming what is missing rather than going quiet."""
    source = make_source(db, org)
    credential_store.put(db, source, {"refresh_token": "rt-1"})

    with pytest.raises(OAuthProblem, match="No fakeprov application"):
        oauth.refresh(db, source, SPEC)


# ── When to renew ────────────────────────────────────────────────────────────


def test_a_token_inside_the_margin_is_renewed(db, org, registered, monkeypatch):
    """A token that expires halfway through a sync is a sync that fails for no
    reason anybody can act on."""
    source = make_source(db, org)
    oauth.save_tokens(
        db, source, registered,
        {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 60},
        now=NOW,
    )
    calls: list[str] = []

    def fake_post(*args, **kwargs):
        calls.append("refreshed")
        return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3600})

    monkeypatch.setattr(oauth.httpx, "post", fake_post)

    secrets = oauth.ensure_fresh(db, source, SPEC, now=NOW)

    assert calls == ["refreshed"]
    assert secrets["access_token"] == "at-2"


def test_a_token_with_plenty_of_life_is_left_alone(db, org, registered, monkeypatch):
    source = make_source(db, org)
    oauth.save_tokens(
        db, source, registered,
        {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600},
        now=NOW,
    )

    def explode(*args, **kwargs):
        raise AssertionError("should not have refreshed")

    monkeypatch.setattr(oauth.httpx, "post", explode)

    assert oauth.ensure_fresh(db, source, SPEC, now=NOW)["access_token"] == "at-1"


def test_a_credential_with_no_expiry_is_never_renewed(db, org, registered, monkeypatch):
    """A provider that issues non-expiring tokens would otherwise be refreshed on
    every single sync."""
    source = make_source(db, org)
    credential_store.put(db, source, {"access_token": "at", "refresh_token": "rt"})

    def explode(*args, **kwargs):
        raise AssertionError("should not have refreshed")

    monkeypatch.setattr(oauth.httpx, "post", explode)

    assert oauth.ensure_fresh(db, source, SPEC, now=NOW)["access_token"] == "at"


def test_the_margin_is_the_boundary(db, org, registered):
    assert oauth.needs_refresh(NOW + oauth.REFRESH_MARGIN, now=NOW) is True
    assert (
        oauth.needs_refresh(NOW + oauth.REFRESH_MARGIN + timedelta(seconds=1), now=NOW)
        is False
    )


def test_an_expired_token_is_renewed(db, org, registered):
    assert oauth.needs_refresh(NOW - timedelta(days=1), now=NOW) is True


def test_a_connector_that_needs_no_oauth_is_handed_its_secrets_untouched(
    db, org, monkeypatch
):
    """What keeps every caller free of `if connector is oauth` branching."""
    source = make_source(db, org, connector="webhook")
    credential_store.put(db, source, {"token": "abc"})

    def explode(*args, **kwargs):
        raise AssertionError("should not have refreshed")

    monkeypatch.setattr(oauth.httpx, "post", explode)

    assert oauth.ensure_fresh(db, source, None, now=NOW) == {"token": "abc"}


def test_a_non_oauth_source_with_an_expiry_recorded_is_still_not_refreshed(
    db, org, monkeypatch
):
    """Defensive, and the only input that separates the `spec is None` guard from
    the expiry check below it: a webhook credential does not normally carry an
    expiry, so without one either path returns the same thing. Reaching the
    refresh with no spec would be an AttributeError rather than a failed sync."""
    source = make_source(db, org, connector="webhook")
    credential_store.put(
        db, source, {"token": "abc"}, expires_at=NOW - timedelta(days=1)
    )

    def explode(*args, **kwargs):
        raise AssertionError("should not have refreshed")

    monkeypatch.setattr(oauth.httpx, "post", explode)

    assert oauth.ensure_fresh(db, source, None, now=NOW) == {"token": "abc"}


# ── Coming back from the provider ────────────────────────────────────────────
#
# The unauthenticated half, and therefore the half where a bug is a security bug.
# A provider redirect carries no session cookie in any modern browser, so the
# sealed flow cookie *is* the credential — which makes what it must refuse the
# interesting part.


def sealed(**overrides) -> str:
    """A flow cookie, valid unless a test breaks it on purpose."""
    import json as json_module
    import time as time_module

    from app.crypto import encrypt

    body = {
        "state": "state-abc",
        "verifier": "verifier-xyz",
        "source_id": 1,
        "exp": time_module.time() + 600,
    }
    body.update(overrides)
    return encrypt(json_module.dumps(body))


def hand_back(client, cookie: str | None, **params):
    """Follow the provider's redirect back, as a browser would."""
    from app.routers.oauth_clients import CALLBACK_PATH, FLOW_COOKIE

    client.cookies.clear()
    if cookie is not None:
        client.cookies.set(FLOW_COOKIE, cookie, path=CALLBACK_PATH)
    return client.get(CALLBACK_PATH, params=params, follow_redirects=False)


def outcome_of(response) -> dict:
    """What the callback page is carrying back to whoever opened it.

    The callback returns a page rather than a redirect now, because the browser is
    in a popup the connect flow opened. The outcome rides in a data attribute, which
    is also how it stays data rather than becoming code.
    """
    import html as html_module
    import json as json_module
    import re

    found = re.search(r'data-result="([^"]*)"', response.text)
    assert found, response.text
    return json_module.loads(html_module.unescape(found.group(1)))


def message_of(response) -> str:
    """The readable error, so assertions read as the sentence somebody sees."""
    return outcome_of(response).get("error") or ""


def token_reply(monkeypatch, **body):
    monkeypatch.setattr(
        oauth.httpx, "post", lambda *a, **k: httpx.Response(200, json=body)
    )


def test_a_successful_callback_stores_the_tokens(
    client, db, org, fake_connector, registered, monkeypatch
):
    source = make_source(db, org)
    db.commit()
    token_reply(monkeypatch, access_token="at-1", refresh_token="rt-1", expires_in=3600)

    response = hand_back(
        client, sealed(source_id=source.id), code="the-code", state="state-abc"
    )

    assert response.status_code == 200
    assert outcome_of(response) == {"source_id": source.id, "error": None}
    assert credential_store.get(db, source)["refresh_token"] == "rt-1"


def test_the_code_is_redeemed_with_the_verifier_that_never_left_the_server(
    client, db, org, fake_connector, registered, monkeypatch
):
    """PKCE only works if the verifier held in the cookie is the one sent back."""
    source = make_source(db, org)
    db.commit()
    sent: list[dict] = []

    def capture(url, data=None, **kwargs):
        sent.append(data or {})
        return httpx.Response(200, json={"access_token": "at"})

    monkeypatch.setattr(oauth.httpx, "post", capture)

    hand_back(client, sealed(source_id=source.id), code="the-code", state="state-abc")

    assert sent[0]["code_verifier"] == "verifier-xyz"
    assert sent[0]["code"] == "the-code"


def test_a_mismatched_state_is_refused(
    client, db, org, fake_connector, registered, monkeypatch
):
    """The one case worth being blunt about: the response did not come from the
    request we made."""
    source = make_source(db, org)
    db.commit()
    token_reply(monkeypatch, access_token="at")

    response = hand_back(
        client, sealed(source_id=source.id), code="the-code", state="not-ours"
    )

    assert "did not match" in message_of(response)
    assert credential_store.get(db, source) == {}


def test_a_callback_with_a_matching_state_but_no_code_is_refused(
    client, db, org, fake_connector, registered, monkeypatch
):
    """The provider redirecting back with neither a code nor an error. Without the
    code check it goes on to redeem `None`, and what comes back from that is the
    provider's problem rather than a message anybody can act on."""
    source = make_source(db, org)
    db.commit()
    token_reply(monkeypatch, access_token="at")

    response = hand_back(client, sealed(source_id=source.id), state="state-abc")

    assert "did not match" in message_of(response)
    assert credential_store.get(db, source) == {}


def test_a_callback_with_no_cookie_is_refused(client, db, org, fake_connector):
    """Somebody opening the callback URL directly, or a stale bookmark.

    The exact message matters here: without the guard the code falls through to
    decrypting `None`, which fails too — so asserting merely that *something* came
    back cannot tell the guard from its absence.
    """
    response = hand_back(client, None, code="the-code", state="state-abc")

    assert response.status_code == 200
    assert message_of(response) == "That sign-in took too long. Please try again."
    assert outcome_of(response)["source_id"] is None


def test_a_tampered_cookie_is_refused_rather_than_half_read(
    client, db, org, fake_connector, registered
):
    """Fernet is authenticated, so this fails to open rather than quietly changing
    which source gets the tokens — which would be a way to point somebody's account
    at a source they did not choose."""
    source = make_source(db, org)
    db.commit()

    response = hand_back(
        client, sealed(source_id=source.id)[:-4] + "AAAA",
        code="the-code", state="state-abc",
    )

    assert "could not be verified" in message_of(response)
    assert credential_store.get(db, source) == {}


def test_an_expired_flow_is_refused(
    client, db, org, fake_connector, registered, monkeypatch
):
    """A cookie left in a browser overnight cannot be replayed."""
    import time as time_module

    source = make_source(db, org)
    db.commit()
    token_reply(monkeypatch, access_token="at")

    response = hand_back(
        client,
        sealed(source_id=source.id, exp=time_module.time() - 1),
        code="the-code",
        state="state-abc",
    )

    assert "too long" in message_of(response)
    assert credential_store.get(db, source) == {}


def test_a_cancelled_sign_in_is_not_alarming(client, db, org, fake_connector):
    """Somebody pressed cancel. That is not an error worth a red banner about."""
    source = make_source(db, org)
    db.commit()

    response = hand_back(client, sealed(source_id=source.id), error="access_denied")

    assert message_of(response) == "Sign-in was cancelled."


def test_another_provider_error_is_passed_on_readably(client, db, org, fake_connector):
    source = make_source(db, org)
    db.commit()

    response = hand_back(client, sealed(source_id=source.id), error="invalid_scope")

    assert message_of(response) == "Invalid scope."


def test_a_callback_for_a_source_that_is_gone_says_so(
    client, db, org, fake_connector, registered
):
    response = hand_back(client, sealed(source_id=999_999), code="c", state="state-abc")

    assert response.status_code == 200
    assert "no longer exists" in message_of(response)


def test_a_failed_exchange_reports_rather_than_raising(
    client, db, org, fake_connector, registered, monkeypatch
):
    """The person reading this is looking at a browser window they were sent to,
    not at a response body."""
    source = make_source(db, org)
    db.commit()
    monkeypatch.setattr(
        oauth.httpx, "post", lambda *a, **k: httpx.Response(400, json={"error": "nope"})
    )

    response = hand_back(
        client, sealed(source_id=source.id), code="the-code", state="state-abc"
    )

    assert response.status_code == 200
    assert message_of(response)
    assert credential_store.get(db, source) == {}


def test_the_flow_cookie_is_cleared_once_it_has_been_used(
    client, db, org, fake_connector, registered, monkeypatch
):
    """It holds the PKCE verifier. Leaving it in the browser after the exchange is
    leaving a spent credential lying around."""
    source = make_source(db, org)
    db.commit()
    token_reply(monkeypatch, access_token="at")

    response = hand_back(
        client, sealed(source_id=source.id), code="the-code", state="state-abc"
    )

    assert 'gg_connect_flow=""' in response.headers.get("set-cookie", "")


# -- The popup, and the page that closes it -----------------------------------


def test_the_callback_page_posts_only_to_our_own_origin(
    client, db, org, fake_connector, registered, monkeypatch
):
    """**Never `"*"`.** This message is the signal that a credential was stored, so
    any page able to receive it could act on it."""
    from app.config import get_settings

    source = make_source(db, org)
    db.commit()
    token_reply(monkeypatch, access_token="at")

    response = hand_back(
        client, sealed(source_id=source.id), code="the-code", state="state-abc"
    )

    origin = get_settings().app_url.rstrip("/")
    # The call itself, not the whole page: the comment above it in the served
    # script mentions the wildcard in order to rule it out, which a naive
    # "the page must not contain a star" assertion trips over.
    assert f'result: result }}, "{origin}")' in response.text
    assert 'result: result }, "*")' not in response.text


def test_the_page_closes_the_popup_and_falls_back_to_navigating(
    client, db, org, fake_connector, registered, monkeypatch
):
    """One response for both cases. A blocked popup, a pasted callback URL and a
    provider that lost the window all land here in an ordinary tab, and two
    responses that handled them separately could disagree."""
    source = make_source(db, org)
    db.commit()
    token_reply(monkeypatch, access_token="at")

    text = hand_back(
        client, sealed(source_id=source.id), code="the-code", state="state-abc"
    ).text

    assert "window.close()" in text
    assert "window.location.replace" in text
    # The guard itself, not merely that both branches exist: without it the page
    # always tries to message an opener, and a blocked popup — which is common —
    # would sit there having done nothing. This is the limit of what a Python test
    # can assert about a script it cannot run.
    assert "window.opener && !window.opener.closed" in text


def test_a_provider_error_cannot_close_the_script_tag(
    client, db, org, fake_connector
):
    """**The payload carries a provider's own words.** Without escaping, a provider
    could end the tag and run whatever it liked on our origin — and the callback is
    the one endpoint here with no session behind it."""
    source = make_source(db, org)
    db.commit()

    response = hand_back(
        client,
        sealed(source_id=source.id),
        error="</script><script>alert(1)</script>",
    )

    # The property is that the tag cannot be closed early, so count the tags: one
    # opening and one closing, both ours. `alert(1)` surviving as *text* inside a
    # quoted attribute is fine and expected — it is escaped, and parsed as data.
    assert response.text.count("<script") == 1
    assert response.text.count("</script") == 1
    # The payload's own tag, defused into attribute-safe text.
    assert "&lt;/script&gt;" in response.text

    # And it still round-trips, so the provider's message is not silently lost.
    assert "alert(1)" in message_of(response)


def test_the_outcome_is_data_rather_than_interpolated_code(
    client, db, org, fake_connector, registered, monkeypatch
):
    """In a `data-` attribute and parsed with `JSON.parse`, so it can never be read
    as code however strange it gets."""
    source = make_source(db, org)
    db.commit()
    token_reply(monkeypatch, access_token="at")

    text = hand_back(
        client, sealed(source_id=source.id), code="the-code", state="state-abc"
    ).text

    assert "JSON.parse(document.currentScript.dataset.result)" in text


def test_the_page_needs_nothing_from_the_network(
    client, db, org, fake_connector, registered, monkeypatch
):
    """It runs in a popup that is about to close, possibly on a deployment with no
    internet access at all. A stylesheet or a script from elsewhere would be a
    spinner that never resolves."""
    source = make_source(db, org)
    db.commit()
    token_reply(monkeypatch, access_token="at")

    text = hand_back(
        client, sealed(source_id=source.id), code="the-code", state="state-abc"
    ).text

    assert "src=" not in text
    assert "href=" not in text
