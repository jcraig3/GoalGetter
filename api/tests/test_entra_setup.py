"""Creating the Entra application for an admin instead of describing it.

**None of this is verification against a live tenant**, and the same caveat as
every other Microsoft test here is worth as much: it proves the requests are built
and the answers read the way they are written, and only a real directory proves the
endpoints and permissions are the ones Microsoft still serves.

What is worth pinning down is the part that is *not* a happy path. The whole design
turns on two things being true:

* **a permission this admin cannot consent to does not fail the registration** —
  Microsoft reserves consent for its own application permissions to a more senior
  role than the one that can create everything else, so the ordinary ending for a
  Cloud Application Administrator is a working application with two permissions
  outstanding;
* **the application asks for exactly what the panel says it does** — the redirect
  URIs and permissions come from one place, because an automatic registration that
  quietly differed from the documented manual one would be undebuggable.
"""

import base64
import json

import httpx
import pytest

from app import entra, providers
from app.models import OauthClient

BOOTSTRAP = providers.MICROSOFT.bootstrap
assert BOOTSTRAP is not None

#: Graph's permission ids in this fake tenant. Arbitrary, and that is the point:
#: nothing in `entra.py` may recognise them, it must look them up by name.
ROLES = {
    "User.Read.All": "role-user-read",
    "GroupMember.Read.All": "role-group-read",
    "MailboxSettings.Read": "role-mailbox-read",
    "Channel.ReadBasic.All": "role-channel-read",
    "ChannelMember.Read.All": "role-channel-member-read",
    "Mail.Send": "role-mail-send",
}
SCOPES = {
    "openid": "scope-openid",
    "profile": "scope-profile",
    "email": "scope-email",
    "offline_access": "scope-offline",
    "Files.Read.All": "scope-files-read",
    "Team.ReadBasic.All": "scope-team-read",
    "Channel.ReadBasic.All": "scope-channel-read",
    "ChannelMessage.Send": "scope-channel-send",
}


def id_token(tenant="contoso-tenant-id"):
    """A token shaped like Microsoft's, carrying the one claim that is read."""
    payload = base64.urlsafe_b64encode(json.dumps({"tid": tenant}).encode()).decode()
    return f"header.{payload.rstrip('=')}.signature"


class Tenant:
    """A directory that answers, so the shape of every request is visible."""

    def __init__(self, *, pending=(), applications=(), grants=(), approve=True):
        #: Permission names whose consent is refused, the way a tenant refuses a
        #: Cloud Application Administrator asking for a Graph app role.
        self.pending = set(pending)
        #: Applications that already exist, by display name.
        self.applications = {name: {"id": "app-object", "appId": "app-client"} for name in applications}
        #: Existing delegated grants, so a re-run can be seen to update rather
        #: than duplicate.
        self.grants = list(grants)
        #: False makes the token endpoint say the admin has not finished yet.
        self.approve = approve
        #: Answers one endpoint differently for a single test. Returning None
        #: falls through to the ordinary directory below.
        #:
        #: **A hook rather than patching the class**, which is what the first
        #: version did — and restoring it afterwards restored the patch onto
        #: itself, so every test that ran later inherited a broken tenant.
        self.override = None
        self.asked: list[httpx.Request] = []
        self.created: list[dict] = []
        self.patched: list[dict] = []
        self.assigned: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        if self.override is not None:
            answered = self.override(request)
            if answered is not None:
                return answered
        path = request.url.path
        # Form-encoded at the token endpoints, JSON at Graph. Parsing
        # unconditionally is how the first version of this fake fell over.
        body = {}
        if request.content and request.headers.get("content-type", "").startswith(
            "application/json"
        ):
            body = json.loads(request.content)

        if path.endswith("/devicecode"):
            return httpx.Response(
                200,
                json={
                    "device_code": "the-device-code",
                    "user_code": "ABCD-EFGH",
                    "verification_uri": "https://microsoft.com/devicelogin",
                    "interval": 1,
                    "expires_in": 900,
                },
            )

        if path.endswith("/oauth2/v2.0/token"):
            if not self.approve:
                return httpx.Response(400, json={"error": "authorization_pending"})
            return httpx.Response(
                200, json={"access_token": "admin-token", "id_token": id_token()}
            )

        if path.endswith("/v1.0/servicePrincipals") and request.method == "GET":
            wanted = request.url.params.get("$filter", "")
            if entra.GRAPH_APP_ID in wanted:
                return httpx.Response(
                    200,
                    json={
                        "value": [
                            {
                                "id": "graph-sp",
                                "appRoles": [
                                    {"value": name, "id": value}
                                    for name, value in ROLES.items()
                                ],
                                "oauth2PermissionScopes": [
                                    {"value": name, "id": value}
                                    for name, value in SCOPES.items()
                                ],
                            }
                        ]
                    },
                )
            # The application's own principal. Absent until it is created.
            return httpx.Response(200, json={"value": []})

        if path.endswith("/v1.0/servicePrincipals") and request.method == "POST":
            self.created.append(body)
            return httpx.Response(201, json={"id": "our-sp", "appId": body["appId"]})

        if path.endswith("/appRoleAssignedTo"):
            name = next(
                (n for n, value in ROLES.items() if value == body.get("appRoleId")), ""
            )
            if name in self.pending:
                # Microsoft's own words for this, near enough: the role that can
                # create all of the above cannot consent to a Graph app role.
                return httpx.Response(
                    403,
                    json={"error": {"message": "Insufficient privileges to complete."}},
                )
            self.assigned.append(body)
            return httpx.Response(201, json={"id": "assignment"})

        if path.endswith("/v1.0/applications") and request.method == "GET":
            wanted = request.url.params.get("$filter", "")
            found = [
                app
                for name, app in self.applications.items()
                if f"'{name}'" in wanted
            ]
            return httpx.Response(200, json={"value": found})

        if path.endswith("/v1.0/applications") and request.method == "POST":
            self.created.append(body)
            self.applications[body["displayName"]] = {
                "id": "app-object",
                "appId": "app-client",
            }
            return httpx.Response(201, json={"id": "app-object", "appId": "app-client"})

        if path.endswith("/addPassword"):
            return httpx.Response(200, json={"secretText": "the-new-secret"})

        if "/applications/" in path and request.method == "PATCH":
            self.patched.append(body)
            return httpx.Response(204)

        if path.endswith("/oauth2PermissionGrants") and request.method == "GET":
            return httpx.Response(200, json={"value": self.grants})

        if path.endswith("/oauth2PermissionGrants") and request.method == "POST":
            if "delegated" in self.pending:
                return httpx.Response(
                    403, json={"error": {"message": "Insufficient privileges."}}
                )
            self.assigned.append(body)
            return httpx.Response(201, json={"id": "grant"})

        if "/oauth2PermissionGrants/" in path and request.method == "PATCH":
            self.patched.append(body)
            return httpx.Response(204)

        return httpx.Response(404, json={"error": {"message": f"no route for {path}"}})


@pytest.fixture
def tenant(monkeypatch):
    """A directory that answers, wired into `entra` and nowhere else.

    **The name inside `entra` is replaced, not `httpx.Client` itself.** Patching
    the module globally would also replace the class `TestClient` is built on,
    which is how the endpoint tests below reach the API in the first place.
    """

    def _install(**kwargs):
        directory = Tenant(**kwargs)
        transport = httpx.MockTransport(directory)

        class Shim:
            Response = httpx.Response

            @staticmethod
            def Client(*args, **kw):
                kw["transport"] = transport
                return httpx.Client(*args, **kw)

            @staticmethod
            def post(url, **kw):
                with httpx.Client(transport=transport) as talker:
                    return talker.post(url, **kw)

        monkeypatch.setattr(entra, "httpx", Shim)
        return directory

    return _install


def approval():
    return entra.Approval(access_token="admin-token", tenant_id="contoso-tenant-id")


def permission(name, kind="delegated"):
    return providers.Permission(name=name, kind=kind)


# ── Getting the code, and waiting for it ─────────────────────────────────────


def test_the_code_and_where_to_enter_it_come_from_microsoft(tenant):
    """**Nothing about the sign-in page is hardcoded here.** The verification URI
    differs by cloud — a government or sovereign tenant sends its admins somewhere
    else entirely — and Microsoft's own documentation says to display what comes
    back rather than a constant."""
    directory = tenant()

    code = entra.start(BOOTSTRAP)

    assert code.user_code == "ABCD-EFGH"
    assert code.verification_uri == "https://microsoft.com/devicelogin"
    assert code.device_code == "the-device-code"

    asked = dict(httpx.QueryParams(directory.asked[0].content.decode()))
    assert asked["client_id"] == providers.GRAPH_CLI_CLIENT_ID
    # Every scope, in one request. The admin consents once.
    assert set(asked["scope"].split()) == set(BOOTSTRAP.scopes)


def test_an_unusable_interval_falls_back_rather_than_polling_flat_out(tenant):
    """Zero is as dangerous as missing: an interval of nothing is a client asking a
    token endpoint as fast as it can, which earns a rate limit and then a block."""
    directory = tenant()
    directory.override = lambda request: (
        httpx.Response(
            200,
            json={
                "device_code": "the-device-code",
                "user_code": "ABCD-EFGH",
                "verification_uri": "https://microsoft.com/devicelogin",
                "interval": 0,
                "expires_in": None,
            },
        )
        if request.url.path.endswith("/devicecode")
        else None
    )

    code = entra.start(BOOTSTRAP)

    assert code.interval > 0
    assert code.expires_in > 0


def test_still_signing_in_is_not_an_error(tenant):
    """The expected answer for most of this flow's life. Somebody reading a consent
    screen is not a failure, so it is a return value rather than an exception."""
    tenant(approve=False)

    assert entra.poll(BOOTSTRAP, "the-device-code") is None


def test_the_tenant_is_read_from_the_token_microsoft_issued_us(tenant):
    """Which saves asking for `Organization.Read.All` on the consent screen purely
    to look up a value Microsoft has already put in our own id token."""
    tenant()

    result = entra.poll(BOOTSTRAP, "the-device-code")

    assert result is not None
    assert result.tenant_id == "contoso-tenant-id"
    assert result.access_token == "admin-token"


def test_a_personal_account_is_refused_with_a_reason(tenant, monkeypatch):
    """A Microsoft account with no directory has nothing to register anything in.
    Without this it would fail several steps later, on a Graph call, with a message
    about permissions rather than about the account."""
    tenant()
    monkeypatch.setattr(
        entra, "_tenant_of", lambda token: (_ for _ in ()).throw(
            entra.SetupProblem("no directory")
        )
    )

    with pytest.raises(entra.SetupProblem):
        entra.poll(BOOTSTRAP, "the-device-code")


@pytest.mark.parametrize(
    "error", ["authorization_declined", "expired_token", "bad_verification_code"]
)
def test_terminal_refusals_stop_rather_than_polling_on(tenant, error):
    """Declined, expired, and unrecognised all mean "stop". Treating any of them as
    "not finished yet" would poll a dead code for the full fifteen minutes."""
    directory = tenant()
    directory.override = lambda request: httpx.Response(400, json={"error": error})

    with pytest.raises(entra.SetupProblem):
        entra.poll(BOOTSTRAP, "the-device-code")


# ── Creating the application ─────────────────────────────────────────────────


def test_permissions_are_looked_up_by_name_not_hardcoded(tenant):
    """**The reason there is no table of GUIDs in `entra.py`.** Entra works in ids
    and admins read names, and keeping the mapping in the code would be a second
    copy of Microsoft's own list, free to drift out of step with it."""
    directory = tenant()

    entra.provision(
        approval(),
        app_name="GoalGetter",
        redirect_uris=["https://goal.example.com/api/auth/sso/callback"],
        permissions=[
            permission("Files.Read.All"),
            permission("User.Read.All", kind="application"),
        ],
    )

    access = directory.patched[0]["requiredResourceAccess"][0]
    assert access["resourceAppId"] == entra.GRAPH_APP_ID
    assert {(item["id"], item["type"]) for item in access["resourceAccess"]} == {
        ("scope-files-read", "Scope"),
        ("role-user-read", "Role"),
    }


def test_the_redirect_uris_given_are_the_ones_registered(tenant):
    """A mismatched redirect URI is the single most common way this whole area
    fails, and the provider's error does not say what it expected. The automatic
    path takes the same list the manual panel renders for copying."""
    directory = tenant()
    uris = [
        "https://goal.example.com/api/auth/sso/callback",
        "https://goal.example.com/api/integrations/oauth/callback",
    ]

    entra.provision(
        approval(), app_name="GoalGetter", redirect_uris=uris, permissions=[]
    )

    assert directory.patched[0]["web"]["redirectUris"] == uris


def test_the_application_is_single_tenant(tenant):
    """A multi-tenant registration would let accounts from any directory reach this
    deployment's sign-in, which is emphatically not what somebody connecting their
    own company's Microsoft is asking for."""
    directory = tenant()

    entra.provision(
        approval(), app_name="GoalGetter", redirect_uris=[], permissions=[]
    )

    created = next(item for item in directory.created if "displayName" in item)
    assert created["signInAudience"] == "AzureADMyOrg"


def test_running_it_again_updates_rather_than_duplicating(tenant):
    """Re-running is the intended way to rotate the secret. The alternative is a
    directory slowly filling with identical registrations nobody can tell apart."""
    directory = tenant(
        applications=["GoalGetter"],
        grants=[{"id": "existing-grant", "scope": "openid"}],
    )

    result = entra.provision(
        approval(),
        app_name="GoalGetter",
        redirect_uris=[],
        permissions=[permission("Files.Read.All")],
    )

    assert result.client_id == "app-client"
    # No second application. `signInAudience` is the tell — only creating one
    # sends it, where the service principal alongside it also carries a name.
    assert not any("signInAudience" in item for item in directory.created)
    # And the existing consent was updated in place rather than joined by a
    # second grant, which would leave Entra to decide which of them counts.
    assert {"scope": "Files.Read.All"} in directory.patched


def test_a_permission_this_admin_cannot_consent_to_does_not_lose_the_rest(tenant):
    """**The ordinary ending for a Cloud Application Administrator**, and the reason
    consent is reported rather than insisted on. Microsoft reserves consent for its
    own application permissions to Privileged Role Administrator — refusing to
    create anything because the last of six steps needs a more senior admin would
    throw away the five that worked."""
    tenant(pending=["User.Read.All", "GroupMember.Read.All"])

    result = entra.provision(
        approval(),
        app_name="GoalGetter",
        redirect_uris=[],
        permissions=[
            permission("Files.Read.All"),
            permission("offline_access"),
            permission("User.Read.All", kind="application"),
            permission("GroupMember.Read.All", kind="application"),
        ],
    )

    assert result.client_secret == "the-new-secret"
    assert set(result.granted) == {"Files.Read.All", "offline_access"}
    assert set(result.pending) == {"User.Read.All", "GroupMember.Read.All"}


def test_a_permission_microsoft_no_longer_offers_is_named_not_fatal(tenant):
    """Over the life of a self-hosted install, a permission this build asks for can
    be renamed or withdrawn. A working registration missing one, with that one
    named, beats no registration at all."""
    tenant()

    result = entra.provision(
        approval(),
        app_name="GoalGetter",
        redirect_uris=[],
        permissions=[permission("Files.Read.All"), permission("Invented.Scope")],
    )

    assert result.granted == ("Files.Read.All",)
    assert result.pending == ("Invented.Scope",)


def test_consent_is_granted_for_everybody_not_just_the_admin(tenant):
    """`AllPrincipals` is what tenant-wide consent means. The alternative consents
    for one person, leaving everyone else facing a prompt they are probably not
    allowed to answer."""
    directory = tenant()

    entra.provision(
        approval(),
        app_name="GoalGetter",
        redirect_uris=[],
        permissions=[permission("openid"), permission("Files.Read.All")],
    )

    grant = next(item for item in directory.assigned if "consentType" in item)
    assert grant["consentType"] == "AllPrincipals"
    assert set(grant["scope"].split()) == {"openid", "Files.Read.All"}


def test_a_deployment_can_use_its_own_public_client(tenant, monkeypatch):
    """Some tenants restrict Microsoft's command-line client outright, which would
    otherwise leave an admin with an error they cannot act on."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ENTRA_BOOTSTRAP_CLIENT_ID", "our-own-public-client")
    try:
        directory = tenant()
        entra.start(BOOTSTRAP)
        asked = dict(httpx.QueryParams(directory.asked[0].content.decode()))
        assert asked["client_id"] == "our-own-public-client"
    finally:
        get_settings.cache_clear()


# ── Through the API ──────────────────────────────────────────────────────────


@pytest.fixture
def admin(make_user):
    return make_user("admin")


@pytest.fixture
def signed_in(client, db, admin, sign_in):
    sign_in(admin)
    db.commit()
    return client


def test_only_microsoft_offers_to_register_itself(signed_in):
    """The offer is described by the catalogue, not by a branch in the page — so a
    provider that gains this later needs no frontend change."""
    listed = {p["provider"]: p for p in signed_in.get("/api/integrations/oauth-clients").json()}

    assert listed["microsoft"]["bootstrap"] is not None
    assert listed["microsoft"]["bootstrap"]["minimum_role"] == "Cloud Application Administrator"
    assert listed["google"]["bootstrap"] is None
    assert listed["oidc"]["bootstrap"] is None


def test_the_setup_scopes_are_shown_before_anything_is_pressed(signed_in):
    """An admin should know what they are about to consent to while they can still
    decide not to, rather than reading it on Microsoft's screen mid-flow."""
    listed = {p["provider"]: p for p in signed_in.get("/api/integrations/oauth-clients").json()}

    scopes = listed["microsoft"]["bootstrap"]["scopes"]
    assert "Application.ReadWrite.All" in scopes
    # The two that only describe the sign-in are left out: padding the list makes
    # the permissions that actually matter harder to read.
    assert "openid" not in scopes


def test_the_admin_consent_link_is_offered_before_anything_fails(signed_in):
    """**The failure that does not look like one.** Until a directory has granted
    this consent, an admin entering the code lands on Microsoft's ordinary user
    prompt telling them to ask an admin — which they are — and nothing is refused,
    so the code is simply never approved. There is no error to react to, which is
    why the link is part of the offer rather than part of an error path."""
    listed = {
        p["provider"]: p
        for p in signed_in.get("/api/integrations/oauth-clients").json()
    }

    url = listed["microsoft"]["bootstrap"]["consent_url"]
    assert url.startswith("https://login.microsoftonline.com/organizations/adminconsent")
    # The client actually being signed in as, so the consent matches the flow.
    assert providers.GRAPH_CLI_CLIENT_ID in url


def test_the_consent_link_follows_the_client_actually_in_use(signed_in, monkeypatch):
    """A deployment pointing at its own public client must not be handed a link
    that consents to Microsoft's instead — it would appear to succeed and change
    nothing about the flow that is actually failing."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ENTRA_BOOTSTRAP_CLIENT_ID", "our-own-public-client")
    try:
        listed = {
            p["provider"]: p
            for p in signed_in.get("/api/integrations/oauth-clients").json()
        }
        url = listed["microsoft"]["bootstrap"]["consent_url"]
        assert "client_id=our-own-public-client" in url
        assert providers.GRAPH_CLI_CLIENT_ID not in url
    finally:
        get_settings.cache_clear()


def test_a_provider_without_a_bootstrap_has_no_consent_link(signed_in):
    """Nothing to consent to, so nothing offered — rather than an empty string a
    page might render as a dead link."""
    listed = {
        p["provider"]: p
        for p in signed_in.get("/api/integrations/oauth-clients").json()
    }

    assert listed["google"]["bootstrap"] is None


def test_polling_without_having_started_is_refused(signed_in, tenant):
    """The device code lives in a sealed cookie, so a poll without one has nothing
    to poll and nothing to guess from."""
    tenant()

    response = signed_in.post(
        "/api/integrations/oauth-clients/microsoft/bootstrap/poll"
    )

    assert response.status_code == 409


def test_a_provider_that_cannot_register_itself_says_so(signed_in, tenant):
    tenant()

    response = signed_in.post("/api/integrations/oauth-clients/google/bootstrap")

    assert response.status_code == 404


def test_the_whole_flow_stores_a_working_connection(signed_in, tenant, db, org):
    """**The point of all of it**: what ends up on the row is indistinguishable from
    an admin having done the console work by hand, which is what keeps every other
    part of the product — sign-in, Excel, directory sync — unchanged."""
    tenant()

    started = signed_in.post("/api/integrations/oauth-clients/microsoft/bootstrap")
    assert started.status_code == 200
    assert started.json()["user_code"] == "ABCD-EFGH"

    finished = signed_in.post(
        "/api/integrations/oauth-clients/microsoft/bootstrap/poll"
    )

    assert finished.status_code == 200
    assert finished.json()["status"] == "done"
    assert finished.json()["provider"]["client_secret_set"] is True

    db.expire_all()
    row = db.query(OauthClient).filter_by(
        organization_id=org.id, provider="microsoft"
    ).one()
    assert row.client_id == "app-client"
    assert row.tenant_id == "contoso-tenant-id"
    # Encrypted at rest, like every other stored secret.
    assert row.client_secret_encrypted != "the-new-secret"


def test_the_application_asks_for_what_the_panel_says_it_does(signed_in, tenant):
    """**The property that makes the two paths safe to offer side by side.** The
    panel tells an admin which permissions and redirect URIs to add; this creates
    them. Both come from `providers.py` through one function, so a registration made
    here cannot quietly differ from the documented manual one."""
    directory = tenant()
    described = next(
        p
        for p in signed_in.get("/api/integrations/oauth-clients").json()
        if p["provider"] == "microsoft"
    )

    signed_in.post("/api/integrations/oauth-clients/microsoft/bootstrap")
    signed_in.post("/api/integrations/oauth-clients/microsoft/bootstrap/poll")

    written = directory.patched[0]
    assert written["web"]["redirectUris"] == described["redirect_uris"]

    # **Resolved by kind, not by name alone.** `Files.Read.All` exists in Entra as
    # both a delegated scope and an app role, with different ids — merging the two
    # maps and looking up by name would let this pass while the application asked
    # for the wrong one, which is the exact mistake the panel's `kind` column
    # exists to prevent.
    written_access = {
        (item["id"], item["type"])
        for item in written["requiredResourceAccess"][0]["resourceAccess"]
    }
    expected = {
        (ROLES[p["name"]], "Role")
        if p["kind"] == "application"
        else (SCOPES[p["name"]], "Scope")
        for p in described["permissions"]
    }
    assert written_access == expected


def test_an_agent_cannot_register_anything(client, db, make_user, sign_in):
    """Same gate as saving a credential by hand. This one creates an application in
    the company's directory, so if anything it matters more."""
    sign_in(make_user("agent"))
    db.commit()

    assert (
        client.post("/api/integrations/oauth-clients/microsoft/bootstrap").status_code
        == 403
    )


def test_the_registration_asks_for_everything_the_build_can_do(signed_in, tenant):
    """**Not only what is switched on.** Admin consent is the expensive step — a
    senior role and a separate trip — so a registration built for today's switches
    means every later toggle costs another re-run and another consent.

    Asked for once, so turning mail on months later is a toggle. This is the
    opposite choice from the panel's own list, which narrows to what is active
    because it is telling somebody what to grant *now*.
    """
    directory = tenant()

    signed_in.post("/api/integrations/oauth-clients/microsoft/bootstrap")
    signed_in.post("/api/integrations/oauth-clients/microsoft/bootstrap/poll")

    ids = {
        item["id"]
        for item in directory.patched[0]["requiredResourceAccess"][0]["resourceAccess"]
    }
    # Sync and mail both, though neither is switched on in this test.
    assert ROLES["User.Read.All"] in ids
    assert ROLES["MailboxSettings.Read"] in ids
    assert ROLES["Mail.Send"] in ids
    # And the delegated ones the other capabilities need.
    assert SCOPES["Files.Read.All"] in ids
    assert SCOPES["offline_access"] in ids
