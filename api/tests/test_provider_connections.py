"""One connection per provider, and single sign-on reading its credential from it.

**These are new because there were none.** `/api/admin/sso` had no test of any kind
before this change, which is how it came to hold a second copy of the same client id
and secret that `oauth_client` already held, with nothing noticing. The endpoint has
just been rewritten to stop doing that, so the behaviour is written down here.

The rule being protected: **an admin registers one application with a provider and
enters it once.** Signing in, reading a spreadsheet, and later syncing people all
come off that one credential, because one app registration can hold several redirect
URIs and delegated scopes are asked for per request.
"""

import pytest

from app.models import (
    DataSource,
    OauthClient,
    Organization,
    SsoConfig,
    UserAccount,
)


@pytest.fixture
def admin(make_user):
    return make_user("admin")


@pytest.fixture
def signed_in(client, db, admin, sign_in):
    sign_in(admin)
    db.commit()
    return client


@pytest.fixture
def connect(db, org):
    """Register an application with a provider, the way the page would."""

    def _connect(provider="microsoft", *, tenant_id=None, issuer=None, secret="shh"):
        row = OauthClient(
            organization_id=org.id,
            provider=provider,
            client_id=f"{provider}-client",
            client_secret_encrypted=secret,
            tenant_id=tenant_id,
            issuer=issuer,
        )
        db.add(row)
        db.flush()
        db.commit()
        return row

    return _connect


def settings_of(client):
    return client.get("/api/admin/sso").json()


def save(client, **changes):
    payload = {
        "enabled": False,
        "provider": None,
        "scopes": "openid profile email",
        "button_label": "Sign in with SSO",
        "auto_provision": False,
        "require_sso": False,
    }
    payload.update(changes)
    return client.put("/api/admin/sso", json=payload)


# ── The credential is not here any more ──────────────────────────────────────


def test_the_sso_settings_hold_no_credential_at_all(signed_in):
    """Not masked — absent, and now absent from the *model* rather than merely from
    the response. There is nowhere left for a second copy of the client secret to
    live, which is the only way two copies cannot drift apart."""
    body = settings_of(signed_in)

    assert "client_id" not in body
    assert "client_secret" not in body
    assert "client_secret_set" not in body


def test_the_issuer_is_reported_but_never_submitted(signed_in, connect):
    """Derived from the tenant id rather than typed. An issuer is a URL with a GUID
    in the middle, and asking somebody to retype one they have already entered as a
    tenant is asking for a support conversation."""
    connect("microsoft", tenant_id="contoso.onmicrosoft.com")

    assert save(signed_in, provider="microsoft").status_code == 200
    assert settings_of(signed_in)["issuer"] == (
        "https://login.microsoftonline.com/contoso.onmicrosoft.com/v2.0"
    )


def test_a_generic_provider_keeps_the_issuer_it_was_given(signed_in, connect):
    """Sign-on has always been provider-agnostic — Okta, Auth0, Keycloak. Moving the
    credential onto the connection must not narrow that to the two providers we ship
    connectors for, so an issuer that cannot be derived is stored and used."""
    connect("oidc", issuer="https://acme.okta.com")

    save(signed_in, provider="oidc")

    assert settings_of(signed_in)["issuer"] == "https://acme.okta.com"


# ── Refusing to enable something that cannot work ────────────────────────────


def test_sso_cannot_be_enabled_with_no_connection(signed_in):
    """The difference between an error the admin sees now and one every user hits at
    their next sign-in. The message has to name the *other page*, because that is
    where the fix is and "not configured" would not say so."""
    response = save(signed_in, enabled=True, provider="microsoft")

    assert response.status_code == 400
    # Asserting on what makes *this* refusal different from the no-issuer one
    # below. Both used to say "on the Integrations page", so either message
    # satisfied both tests and neither guard was really under test.
    assert "Connect this provider first" in response.json()["detail"]


def test_sso_cannot_be_enabled_when_the_connection_has_no_issuer(signed_in, connect):
    """A Microsoft connection with a client id and secret but no tenant is a
    connection that can read a spreadsheet and cannot sign anybody in — because the
    issuer a token is validated against is built from the tenant."""
    connect("microsoft", tenant_id=None)

    response = save(signed_in, enabled=True, provider="microsoft")

    assert response.status_code == 400
    assert "no issuer yet" in response.json()["detail"]
    # And specifically *not* the other refusal — the connection does exist.
    assert "Connect this provider first" not in response.json()["detail"]


def test_sso_cannot_be_enabled_when_the_connection_has_no_secret(signed_in, connect):
    """A row with a client id and no secret is a connection somebody started and
    abandoned. It can neither sign anybody in nor read anything."""
    connect("microsoft", tenant_id="contoso.onmicrosoft.com", secret="")

    response = save(signed_in, enabled=True, provider="microsoft")

    assert response.status_code == 400
    assert "Connect this provider first" in response.json()["detail"]


def test_a_connection_with_no_secret_does_not_report_itself_connected(
    signed_in, connect
):
    """`connected` has to check the secret, not merely that a row exists.

    Pointing sign-on at the connection is the part that makes this discriminate:
    without it there is no connection to look at, and every wrong rule agrees that
    nothing is connected.
    """
    connect("microsoft", tenant_id="contoso.onmicrosoft.com", secret="")
    save(signed_in, provider="microsoft")

    assert connection_named(signed_in, "microsoft")["client_secret_set"] is False
    assert settings_of(signed_in)["connected"] is False


def test_sso_enables_once_the_connection_can_actually_do_it(signed_in, connect):
    connect("microsoft", tenant_id="contoso.onmicrosoft.com")

    response = save(signed_in, enabled=True, provider="microsoft")

    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["connected"] is True


def test_a_provider_that_cannot_sign_people_in_is_refused_by_name(signed_in):
    """Pointing sign-on at something that cannot do it would produce a button that
    fails at the provider, so it is refused where the mistake is made.

    **This used Google as its example, and Google now signs people in** — which is
    the trap in naming a specific provider rather than the property. It asks about
    a provider that genuinely cannot instead.
    """
    response = save(signed_in, provider="not-a-provider")

    assert response.status_code == 400
    assert "not-a-provider" in response.json()["detail"]


def test_a_connector_only_provider_offers_no_sign_on():
    """The property behind the test above. A provider that exists solely because
    some connector named it gets one data capability built from its own spec, and
    nothing else — we know nothing about whether it speaks OIDC."""
    from app.providers import derive

    made = derive("acme", "Acme", ("read.things",))

    assert [c.key for c in made.capabilities] == ["data"]


def test_turning_sso_off_needs_no_working_connection(signed_in):
    """Otherwise a deployment whose identity provider has been deleted could not
    switch off the sign-in button that no longer works."""
    assert save(signed_in, enabled=False, provider=None).status_code == 200


# ── What the connection powers, derived rather than stored ───────────────────


def connection_named(client, provider):
    listed = client.get("/api/integrations/oauth-clients").json()
    return next(p for p in listed if p["provider"] == provider)


def capability(client, provider, key):
    return next(
        c for c in connection_named(client, provider)["capabilities"] if c["key"] == key
    )


def test_signing_in_shows_as_active_because_sso_says_so(signed_in, connect):
    """**Nothing stores this.** A ticked box would be a third place that could
    disagree with the SSO settings and the sources; asking the feature itself cannot
    drift."""
    connect("microsoft", tenant_id="contoso.onmicrosoft.com")

    assert capability(signed_in, "microsoft", "sso")["active"] is False

    save(signed_in, enabled=True, provider="microsoft")

    assert capability(signed_in, "microsoft", "sso")["active"] is True


def test_a_connection_chosen_but_switched_off_is_not_active(signed_in, connect):
    """**The case the test above could not see.** It only ever compared "no config
    at all" with "enabled", and every wrong rule agrees about those two. A config
    that names this provider and is switched off is the one that tells `enabled`
    apart from `provider ==`.
    """
    connect("microsoft", tenant_id="contoso.onmicrosoft.com")

    save(signed_in, enabled=False, provider="microsoft")

    assert capability(signed_in, "microsoft", "sso")["active"] is False


def test_signing_in_is_credited_to_the_connection_doing_it_and_no_other(
    signed_in, connect
):
    """Two providers can sign people in, and only one of them is. Without this the
    rule could ignore which provider was chosen entirely."""
    connect("microsoft", tenant_id="contoso.onmicrosoft.com")
    connect("oidc", issuer="https://acme.okta.com")

    save(signed_in, enabled=True, provider="oidc")

    assert capability(signed_in, "oidc", "sso")["active"] is True
    assert capability(signed_in, "microsoft", "sso")["active"] is False


def test_data_shows_as_active_only_once_a_source_actually_uses_it(
    signed_in, connect, db, org
):
    from datetime import UTC, datetime

    connect("google")
    assert capability(signed_in, "google", "data")["active"] is False

    db.add(
        DataSource(
            organization_id=org.id,
            name="Sheet",
            connector="google_sheets",
            activated_at=datetime.now(UTC),
        )
    )
    db.commit()

    assert capability(signed_in, "google", "data")["active"] is True


def test_a_removed_source_does_not_count_as_using_the_connection(
    signed_in, connect, db, org
):
    """Its facts still say where they came from, but it is finished business — and
    a connection reporting itself in use because of a source somebody deleted is a
    connection nobody dares remove."""
    from datetime import UTC, datetime

    connect("google")
    db.add(
        DataSource(
            organization_id=org.id,
            name="Gone",
            connector="google_sheets",
            activated_at=datetime.now(UTC),
            archived_at=datetime.now(UTC),
        )
    )
    db.commit()

    assert capability(signed_in, "google", "data")["active"] is False


def test_a_draft_source_does_not_count_as_using_the_connection(signed_in, connect, db, org):
    """A connect flow nobody finished imports nothing, so it is not something this
    connection powers — the same rule that keeps drafts out of the sources list."""
    connect("google")
    db.add(
        DataSource(
            organization_id=org.id, name="Half-built", connector="google_sheets"
        )
    )
    db.commit()

    assert capability(signed_in, "google", "data")["active"] is False


# ── Saving the connection ────────────────────────────────────────────────────


def test_the_tenant_is_saved_and_the_secret_is_left_alone(signed_in, connect, db, org):
    """Same rule the client secret already had, applied to the two new fields: an
    admin fixing a tenant id should not have to go and find their secret again."""
    connect("microsoft", tenant_id="old-tenant", secret="original")

    response = signed_in.put(
        "/api/integrations/oauth-clients/microsoft",
        json={"client_id": "microsoft-client", "tenant_id": "new-tenant"},
    )

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "new-tenant"
    assert response.json()["client_secret_set"] is True

    db.expire_all()
    row = db.query(OauthClient).filter_by(organization_id=org.id, provider="microsoft").one()
    assert row.client_secret_encrypted == "original"


def test_a_brand_new_connection_keeps_the_tenant_it_was_created_with(
    signed_in, db, org
):
    """**Creating and updating are separate branches**, and the fixture above only
    exercised updating — it built its rows directly. A tenant dropped on creation
    would leave a Microsoft connection that can read a spreadsheet and cannot sign
    anybody in, which is a confusing thing to debug."""
    response = signed_in.put(
        "/api/integrations/oauth-clients/microsoft",
        json={
            "client_id": "new-client",
            "client_secret": "brand-new",
            "tenant_id": "fresh.onmicrosoft.com",
        },
    )

    assert response.status_code == 200
    row = db.query(OauthClient).filter_by(organization_id=org.id, provider="microsoft").one()
    assert row.tenant_id == "fresh.onmicrosoft.com"


def test_a_brand_new_connection_keeps_the_issuer_it_was_created_with(
    signed_in, db, org
):
    response = signed_in.put(
        "/api/integrations/oauth-clients/oidc",
        json={
            "client_id": "new-client",
            "client_secret": "brand-new",
            "issuer": "https://acme.okta.com/",
        },
    )

    assert response.status_code == 200
    row = db.query(OauthClient).filter_by(organization_id=org.id, provider="oidc").one()
    # And the trailing slash is gone: an issuer is concatenated with
    # `/.well-known/openid-configuration`, so a stray slash produces a double one
    # and a 404 from the provider.
    assert row.issuer == "https://acme.okta.com"


def test_only_the_callbacks_the_connection_actually_needs_are_listed(
    signed_in, connect
):
    """Once something is switched on the list narrows to it. A panel that always
    listed every callback would have an admin registering a sign-in URI for a
    connection used only to read spreadsheets."""
    connect("microsoft", tenant_id="contoso.onmicrosoft.com")
    save(signed_in, enabled=True, provider="microsoft")

    uris = connection_named(signed_in, "microsoft")["redirect_uris"]

    assert [u.rsplit("/api", 1)[1] for u in uris] == ["/auth/sso/callback"]


def test_the_setup_panel_asks_for_both_callbacks_on_a_fresh_connection(signed_in):
    """Before anything is switched on there is nothing to derive from, so the panel
    lists everything the connection could need — the admin is about to turn those
    things on, and a second trip to the Entra console to add one more redirect URI
    is the trip this is meant to prevent."""
    uris = connection_named(signed_in, "microsoft")["redirect_uris"]

    assert any(u.endswith("/api/auth/sso/callback") for u in uris)
    assert any(u.endswith("/api/integrations/oauth/callback") for u in uris)


def test_an_unbuilt_capability_asks_for_no_permissions(signed_in):
    """**Found by looking at the real page, not by a test.**

    A fresh Microsoft connection listed permissions for directory sync and email
    while neither was built — all needing tenant-wide admin consent, so the panel
    was asking an admin to hand over read access to every user in the company for
    features that did nothing yet.

    **Both of those ship now, so Google's directory sync is the example.** The
    rule was never about which feature happens to be unfinished: an unbuilt one is
    shown greyed on the card and left out of the list of things to go and grant.
    Repointing it is the third time, each for the best possible reason.
    """
    connection = connection_named(signed_in, "google")

    assert not any("admin.directory" in scope for scope in connection["scopes"])
    # ...while still being visible as something that is coming.
    assert any(c["key"] == "directory" for c in connection["capabilities"])


def test_everything_microsoft_ships_is_asked_for(signed_in):
    """The half with teeth. An unbuilt capability is excluded from the permissions
    an application is told to request, so a stale flag costs a registration that
    cannot do the thing it was made for — which is exactly what shipped once."""
    scopes = connection_named(signed_in, "microsoft")["scopes"]

    for wanted in ("User.Read.All", "GroupMember.Read.All", "MailboxSettings.Read", "Mail.Send"):
        assert wanted in scopes

def test_the_permissions_listed_are_the_ones_the_admin_has_to_grant(signed_in):
    """The point of the capability model: nobody works out which Entra permissions a
    feature needs by reading documentation, the panel says so."""
    scopes = connection_named(signed_in, "microsoft")["scopes"]

    assert "openid" in scopes
    assert "Files.Read.All" in scopes
    # `offline_access` is what makes a refresh token appear at all — leaving it out
    # produces a source that works for an hour.
    assert "offline_access" in scopes


# ── The sign-in flow itself ──────────────────────────────────────────────────


def test_starting_a_sign_in_uses_the_connections_credential(
    client, db, org, connect, monkeypatch
):
    """End to end through the part that matters: the authorize URL must carry the
    client id from `oauth_client`, because there is nowhere else for it to come
    from now."""
    from app import oidc

    connect("oidc", issuer="https://acme.okta.com")
    db.add(SsoConfig(organization_id=org.id, enabled=True, provider="oidc"))
    db.commit()

    monkeypatch.setattr(
        oidc,
        "discover",
        lambda issuer: {
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "jwks_uri": f"{issuer}/keys",
        },
    )

    response = client.get("/api/auth/sso/start", follow_redirects=False)

    assert response.status_code == 303
    assert "client_id=oidc-client" in response.headers["location"]
    assert response.headers["location"].startswith("https://acme.okta.com/authorize")


def test_signing_in_with_microsoft_derives_the_issuer_from_the_tenant(
    client, db, org, connect, monkeypatch
):
    """**The other half of the sign-in test, and the one that was missing.** The
    existing one used a connection with a stored issuer, so a rule that ignored the
    tenant entirely still passed it. Microsoft stores no issuer at all."""
    from app import oidc

    connect("microsoft", tenant_id="contoso.onmicrosoft.com")
    db.add(SsoConfig(organization_id=org.id, enabled=True, provider="microsoft"))
    db.commit()

    seen = {}

    def fake_discover(issuer):
        seen["issuer"] = issuer
        return {
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "jwks_uri": f"{issuer}/keys",
        }

    monkeypatch.setattr(oidc, "discover", fake_discover)

    response = client.get("/api/auth/sso/start", follow_redirects=False)

    assert response.status_code == 303
    assert seen["issuer"] == (
        "https://login.microsoftonline.com/contoso.onmicrosoft.com/v2.0"
    )


def test_a_sign_in_with_no_connection_fails_readably(client, db, org):
    """Enabled but pointed at nothing — which a database restored from a partial
    backup can be. It must land on the login page with a message rather than a
    stack trace."""
    db.add(SsoConfig(organization_id=org.id, enabled=True, provider="microsoft"))
    db.commit()

    response = client.get("/api/auth/sso/start", follow_redirects=False)

    assert response.status_code == 303
    # The specific message, not merely *some* error. Without a connection check
    # this still redirected to /login — via a failed discovery of an empty issuer
    # — so "there is an error" could not tell the two apart.
    assert "not%20configured" in response.headers["location"]


def test_only_an_admin_can_read_or_change_any_of_this(client, db, make_user, sign_in):
    agent = make_user("agent")
    sign_in(agent)
    db.commit()

    assert client.get("/api/admin/sso").status_code == 403
    assert client.get("/api/integrations/oauth-clients").status_code == 403
    assert isinstance(agent, UserAccount)


# ── The catalogue's own rules ────────────────────────────────────────────────
#
# Tested directly rather than through the API, because the shipping catalogue
# cannot produce some of these situations — no provider currently has two
# capabilities sharing a scope, so a dedup bug would be invisible through any
# endpoint. A synthetic provider can produce them, and the rules are what a future
# catalogue entry will rely on.


def synthetic(**kwargs):
    from app.providers import Capability, Permission, Provider

    defaults = dict(
        key="acme",
        name="Acme",
        capabilities=(
            Capability(
                key="sso",
                name="Sign in",
                detail="",
                permissions=(Permission("openid"), Permission("shared")),
                redirect_path="/sso",
            ),
            Capability(
                key="data",
                name="Data",
                detail="",
                permissions=(
                    Permission("shared"),
                    Permission("read", kind="application", admin_consent=True),
                ),
                redirect_path="/data",
            ),
        ),
    )
    defaults.update(kwargs)
    return Provider(**defaults)


def test_a_scope_two_capabilities_both_need_is_asked_for_once():
    """An admin pasting a permission list should not see the same entry twice, and
    some providers reject a duplicated scope outright."""
    from app.providers import scopes_for

    assert scopes_for(synthetic(), {"sso", "data"}) == [
        "openid",
        "shared",
        "read",
    ]


def test_only_the_chosen_capabilities_contribute_scopes():
    from app.providers import scopes_for

    assert scopes_for(synthetic(), {"sso"}) == ["openid", "shared"]


def test_only_the_chosen_capabilities_contribute_redirect_uris():
    """The API cannot reach this for a provider whose capabilities all share one
    callback, which is most of them."""
    from app.providers import redirect_paths_for

    assert redirect_paths_for(synthetic(), {"data"}) == ["/data"]
    assert redirect_paths_for(synthetic(), set()) == []


def test_a_data_capability_with_no_connector_is_not_offered():
    """It matters for a catalogue provider whose connector is later removed: the
    entry stays and the capability must not, because a checkbox that unlocks
    nothing costs somebody an afternoon in an admin console."""
    from app.providers import offered

    assert offered(synthetic(), has_connector=True) == {"sso", "data"}
    assert offered(synthetic(), has_connector=False) == {"sso"}


def test_a_typed_issuer_is_stripped_of_its_trailing_slash():
    """It is concatenated with `/.well-known/openid-configuration`, so a stray
    slash produces a double one and a 404 that says nothing useful."""
    from app.providers import issuer_for

    assert issuer_for("oidc", stored="https://acme.okta.com/") == "https://acme.okta.com"


def test_a_derived_issuer_wins_over_anything_stored():
    """Microsoft's is built from the tenant. If a stale issuer were also stored,
    the URL a sign-in starts at and the one a token is validated against could
    disagree — which fails at the last step of a flow that looked fine."""
    from app.providers import issuer_for

    assert issuer_for(
        "microsoft", tenant_id="abc", stored="https://stale.example"
    ) == "https://login.microsoftonline.com/abc/v2.0"


# ── What an admin is told to grant ───────────────────────────────────────────


def test_a_permission_says_which_kind_it_is():
    """**A scope string on its own is not actionable.** In Entra `Files.Read.All`
    exists twice — delegated and application — on different tabs, meaning different
    things, and the wrong one authorises cleanly then returns 403 on every read."""
    from app.providers import permissions_for

    kinds = {p.name: p.kind for p, _ in permissions_for(synthetic(), {"sso", "data"})}

    assert kinds["openid"] == "delegated"
    assert kinds["read"] == "application"


def test_a_permission_says_whether_admin_consent_is_needed():
    """A separate button in the console, which nobody presses unless told — and
    until it is pressed the permission does nothing at all."""
    from app.providers import permissions_for

    consent = {
        p.name: p.admin_consent for p, _ in permissions_for(synthetic(), {"sso", "data"})
    }

    assert consent["read"] is True
    assert consent["openid"] is False


def test_a_permission_says_what_it_is_for():
    """"Why am I granting this?" is the question an admin asks at exactly the
    moment they are told to hand over directory-wide read access."""
    from app.providers import permissions_for

    reasons = {p.name: why for p, why in permissions_for(synthetic(), {"sso", "data"})}

    assert reasons["openid"] == "Sign in"
    assert reasons["read"] == "Data"


def test_a_permission_two_capabilities_need_is_listed_once_with_the_first_reason():
    """Granted once in the console, so listed once here — and attributed to the
    first thing that wants it rather than repeated."""
    from app.providers import permissions_for

    listed = [(p.name, why) for p, why in permissions_for(synthetic(), {"sso", "data"})]

    assert [name for name, _ in listed].count("shared") == 1
    assert dict(listed)["shared"] == "Sign in"


def test_excel_asks_for_offline_access_and_says_it_is_for_excel(signed_in):
    """The permission nobody would guess at: without it Microsoft issues no refresh
    token and the source works for exactly one hour. Naming what it is for is what
    stops an admin pruning it as noise."""
    listed = connection_named(signed_in, "microsoft")["permissions"]
    offline = next(p for p in listed if p["name"] == "offline_access")

    assert offline["needed_for"] == "Excel spreadsheets"


def test_the_permission_list_and_the_scope_list_cannot_disagree(signed_in):
    """One is what the admin is told to grant, the other is what is actually
    requested. Two lists that could differ would produce a connection that
    authorises and then fails, with the page insisting it was set up correctly."""
    connection = connection_named(signed_in, "microsoft")

    assert [p["name"] for p in connection["permissions"]] == connection["scopes"]


def test_google_signs_people_in_as_well_as_reading_sheets(signed_in):
    """**The Google connection was never only for Sheets.** It is one credential
    with several capabilities, exactly like Microsoft — so a Workspace company gets
    sign-on for no setup beyond ticking it."""
    offered = {c["key"] for c in connection_named(signed_in, "google")["capabilities"]}

    assert {"sso", "data"} <= offered


def test_googles_issuer_is_fixed_rather_than_derived_from_a_tenant():
    """Google is one issuer for everybody and a Workspace domain is not part of it,
    so a template with no `{tenant}` in it is used as-is. Requiring a tenant here
    would have left Google unable to sign anyone in."""
    from app.providers import issuer_for, needs_typed_issuer, get

    assert issuer_for("google") == "https://accounts.google.com"
    assert issuer_for("google", tenant_id="ignored") == "https://accounts.google.com"
    assert needs_typed_issuer(get("google")) is False


def test_signing_in_with_google_needs_no_tenant(signed_in, connect):
    """The refusal for a Microsoft connection with no tenant must not fire here —
    Google has no such concept and never will."""
    connect("google")

    assert save(signed_in, enabled=True, provider="google").status_code == 200


def test_the_card_says_directory_sync_is_on_once_it_is(signed_in, connect, db, org):
    """**The one capability that is stored rather than derived**, and it was the one
    left out of the derivation — so somebody who had just switched tenant sync on
    was shown a card claiming it was off, on the same screen as the switch."""
    row = connect("microsoft")
    row.directory_sync_enabled = True
    db.commit()

    connection = connection_named(signed_in, "microsoft")
    directory = next(c for c in connection["capabilities"] if c["key"] == "directory")

    assert directory["active"] is True


def test_the_card_says_it_is_off_when_it_is(signed_in, connect):
    connect("microsoft")

    connection = connection_named(signed_in, "microsoft")
    directory = next(c for c in connection["capabilities"] if c["key"] == "directory")

    assert directory["active"] is False


def test_another_organizations_switch_does_not_light_up_this_card(
    signed_in, connect, db, org
):
    """Every capability here is derived per organization, and this one reads a row
    that has an `organization_id` on it — so the filter is worth an assertion
    rather than a glance."""
    connect("microsoft")
    other = Organization(name="Other", timezone="UTC")
    db.add(other)
    db.flush()
    db.add(
        OauthClient(
            organization_id=other.id,
            provider="microsoft",
            client_id="theirs",
            client_secret_encrypted="x",
            directory_sync_enabled=True,
        )
    )
    db.commit()

    connection = connection_named(signed_in, "microsoft")
    directory = next(c for c in connection["capabilities"] if c["key"] == "directory")

    assert directory["active"] is False
