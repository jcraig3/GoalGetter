"""What a deployment can be connected to, and what each connection powers.

**One connection per provider, several capabilities on it.** An admin registers one
application with Microsoft and that single credential signs people in, reads their
Excel workbooks and — once 3d lands — syncs their people. Before this module there
were two credentials for the same Entra app registration, in two tables, behind two
forms on the same page, neither aware of the other.

**Capabilities are derived, never stored.** There is no list of ticked boxes
anywhere: single sign-on is on because `sso_config` says so, and data is on because a
data source actually uses a connector for that provider. A stored flag would be a
third thing that could disagree with the other two, and the whole point of this
module is having fewer of those.

**The catalogue is data, not code.** Adding a provider is an entry below plus,
usually, a connector — not a branch in a router.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Where each capability sends the browser back to.
#:
#: Separate paths because they are separate flows with separate handlers, and an
#: app registration is perfectly happy holding both. The setup panel lists whichever
#: ones a deployment actually needs, so nobody pastes a URI for a feature they are
#: not using.
SSO_REDIRECT_PATH = "/api/auth/sso/callback"
DATA_REDIRECT_PATH = "/api/integrations/oauth/callback"

#: Where the tenant account signs in, in delegated mode.
#:
#: **A third callback rather than reusing the data one**, which carries a source
#: id in its sealed cookie and would have nothing to put there. One registration
#: holds as many redirect URIs as it needs.
TENANT_REDIRECT_PATH = "/api/admin/directory/callback"



@dataclass(frozen=True)
class Permission:
    """One permission an admin has to grant, described the way the console does.

    **The scope string on its own is not enough to act on.** In Entra, `Files.Read.All`
    exists twice — once as a *delegated* permission and once as an *application*
    one — on different tabs, meaning different things, and picking the wrong one
    produces a connection that authorises cleanly and then returns 403 on every
    read. Some also need a tenant admin to press *Grant admin consent*, which is a
    separate button an admin will not think to press unless told.

    So the panel says which kind and whether consent is needed, rather than leaving
    an admin to work it out from the provider's documentation.
    """

    #: What to type into the console's permission search box. Also the scope sent
    #: in the authorization request — for Graph and for Google they are the same
    #: string, which is why there is one field rather than two that can disagree.
    name: str
    #: `delegated` — acts as the signed-in person. `application` — acts as itself,
    #: with no user, which is what a background sync needs. Empty for a provider
    #: that does not make the distinction, and then it is not shown.
    kind: str = "delegated"
    #: Whether a tenant admin has to approve it before it will work at all.
    admin_consent: bool = False

    #: Which sign-in mode this permission belongs to, or empty for both.
    #:
    #: **The two sets must never appear on one registration.** A Cloud Application
    #: Administrator can consent to every delegated permission and to none of
    #: Microsoft Graph's app roles — and consent is all-or-nothing, so a
    #: registration holding both greys the button out and neither half gets
    #: granted. Which is exactly the trap this field exists to make impossible.
    mode: str = ""

    #: Whether the capability works without it, in reduced form.
    #:
    #: **Not decoration — it decides whether a missing grant is fatal.** A
    #: consent screen is all-or-nothing to the admin looking at it, but a
    #: *tenant* can end up with a partial set: an optional permission removed
    #: later, or a policy that never allowed it. Marking one optional is a promise
    #: the code has to keep, so each of these has a matching degrade path in the
    #: provider.
    optional: bool = False


@dataclass(frozen=True)
class Capability:
    """One thing a provider connection can power."""

    key: str
    #: What the admin sees on the connection card.
    name: str
    #: One line: what switching this on actually gets them.
    detail: str
    #: What to grant, in the provider's own vocabulary. Shown in the setup panel so
    #: an admin knows exactly what to add, rather than working it out from
    #: documentation.
    permissions: tuple[Permission, ...] = ()
    redirect_path: str = ""
    #: False for a capability that is designed but not built. Shown greyed rather
    #: than hidden — an admin looking for "can this sync my people?" should find
    #: the answer even when the answer is "not yet".
    built: bool = True

    @property
    def scopes(self) -> tuple[str, ...]:
        """Just the names, which is what goes in the authorization request."""
        return tuple(p.name for p in self.permissions)


@dataclass(frozen=True)
class Bootstrap:
    """Creating the application *for* an admin, rather than describing it to them.

    **The chicken-and-egg, and why there is not one.** Signing in to a provider
    needs a client id, and a deployment that has not registered anything yet has
    none — which is what makes automatic registration look impossible for software
    somebody pulls onto their own server. Microsoft's way out is that its own
    command-line tooling is a *public client that already exists in every tenant*:
    `Connect-MgGraph` signs in as it, asks for whatever delegated scopes it needs at
    consent time, and the admin approves them on screen. Nothing is registered in
    advance by anybody, so there is nothing for this project to own, host or ship a
    secret for.

    So the flow is: sign in as that client, use the admin's own token to create
    *their* application through the provider's API, and then never use the
    bootstrap client again. What ends up stored is a registration belonging
    entirely to them.

    **This is a convenience, never a requirement.** Every provider described here
    can still be registered by hand, and some tenants will have to — see
    `app/entra.py` for the three ways this can be refused.
    """

    #: The public client the *bootstrap* sign-in runs as — not the application
    #: being created. Overridable per deployment: a tenant that restricts
    #: Microsoft's tooling can point this at a registration of its own.
    client_id: str
    #: Where the code comes from, and where it is exchanged. `{tenant}` is filled
    #: with `organizations`, since which tenant is decided by who signs in.
    devicecode_url: str
    token_url: str
    #: What to ask the admin to consent to. Enough to create an application,
    #: give it permissions, and consent to them on the organization's behalf.
    scopes: tuple[str, ...]
    #: What the created application is called in their directory.
    app_name: str
    #: The lowest directory role that can complete this, named the way the
    #: provider's own console names it. Shown before the button, because being
    #: told this afterwards by an error message is the worst place to learn it.
    minimum_role: str
    #: How the consent screen identifies the client. Said in advance because it is
    #: the provider's name for its own tooling rather than ours, and an admin who
    #: was not warned reasonably reads that as the wrong app.
    consent_name: str

    #: Where an admin grants the one-time, tenant-wide consent for the bootstrap
    #: client, with `{client_id}` filled from whichever client is actually in use.
    #:
    #: **The step that is invisible until it bites.** The role above really is
    #: enough to *grant* this — Microsoft reserves only its own application
    #: permissions for a more senior role, and everything asked for here is
    #: delegated. But granting tenant-wide consent is a different endpoint from
    #: signing in, and the sign-in screen offers an admin no way to do it: what
    #: they get is the ordinary user prompt, which says to go and ask an admin.
    #: They are the admin, and the screen cannot tell them so.
    #:
    #: So the link is shown *before* that happens rather than being the thing
    #: somebody works out afterwards. Once granted, it is granted for the whole
    #: tenant and nobody sees a consent prompt here again.
    consent_url_template: str = ""

    def consent_url(self, client_id: str) -> str:
        """Where to grant tenant-wide consent for the client actually in use.

        Built from the resolved client id rather than the declared one, so a
        deployment that points `entra_bootstrap_client_id` at a registration of
        its own gets a link for *that* app instead of a link that would consent
        to something it is not using.
        """
        if not self.consent_url_template:
            return ""
        return self.consent_url_template.format(client_id=client_id)


@dataclass(frozen=True)
class Provider:
    """A provider a deployment can hold one credential for."""

    key: str
    name: str
    capabilities: tuple[Capability, ...]

    #: How to create the application automatically, when the provider allows it.
    #: None means the only path is the console steps below.
    bootstrap: Bootstrap | None = None

    #: What to call the directory id, when the provider has one. Empty means it
    #: does not, and the field is not shown.
    tenant_label: str = ""
    tenant_hint: str = ""

    #: How to build the OIDC issuer from the tenant id. Empty means the issuer
    #: cannot be derived and has to be typed — see `issuer_for`.
    issuer_template: str = ""

    #: Where the admin goes to create the application. The single most useful
    #: thing on the setup panel, and the thing they otherwise have to search for.
    console_url: str = ""
    console_steps: tuple[str, ...] = ()


#: The three OIDC scopes every identity provider understands. Delegated by
#: definition — they describe the person signing in — and no provider requires
#: admin consent for them.
SSO = Capability(
    key="sso",
    name="Single sign-on",
    detail="People sign in with their work account instead of a password here.",
    permissions=(
        Permission("openid"),
        Permission("profile"),
        Permission("email"),
    ),
    redirect_path=SSO_REDIRECT_PATH,
)

#: Microsoft's own command-line client, and the reason the Microsoft connection can
#: register itself.
#:
#: `Connect-MgGraph` signs in as this, and it is present in essentially every
#: tenant — Microsoft creates it on first use where it is not. A *public* client,
#: so there is no secret anywhere in this, and a delegated one, so it can do
#: nothing except on behalf of the admin who consented in front of it.
GRAPH_CLI_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"

MICROSOFT = Provider(
    key="microsoft",
    name="Microsoft 365",
    bootstrap=Bootstrap(
        client_id=GRAPH_CLI_CLIENT_ID,
        # `organizations` rather than `common`: a personal Microsoft account has no
        # directory to register anything in, and letting one sign in here produces
        # a confusing failure several steps later instead of a clear one now.
        devicecode_url="https://login.microsoftonline.com/organizations/oauth2/v2.0/devicecode",
        token_url="https://login.microsoftonline.com/organizations/oauth2/v2.0/token",
        scopes=(
            # Reading `tid` off the id token is how the tenant is learned, which
            # saves asking for `Organization.Read.All` purely to look up a value
            # Microsoft already put in our own token.
            "openid",
            "profile",
            # Create the application and its service principal.
            "Application.ReadWrite.All",
            # Consent to it: the first for application permissions, the second
            # for delegated ones. Both are what "Grant admin consent" presses.
            #
            # `AppRoleAssignment.ReadWrite.All` is the uncomfortable one — it is
            # what lets an application grant privileges to itself, and it is here
            # because without it directory sync cannot be switched on by the same
            # admin who set it up. That was the whole point: everything working
            # when the registration finishes. A tenant unwilling to grant it can
            # still register by hand and press consent in the portal.
            "AppRoleAssignment.ReadWrite.All",
            "DelegatedPermissionGrant.ReadWrite.All",
        ),
        app_name="GoalGetter",
        minimum_role="Cloud Application Administrator",
        consent_name="Microsoft Graph Command Line Tools",
        # `organizations` rather than a tenant id: which directory this lands in
        # is decided by who signs in, which is the same reason the device code
        # request uses it. It means the link works before we know the tenant —
        # and we do not know it until the sign-in this link unblocks.
        consent_url_template=(
            "https://login.microsoftonline.com/organizations/adminconsent"
            "?client_id={client_id}"
        ),
    ),
    tenant_label="Directory (tenant) ID",
    tenant_hint=(
        "Entra admin centre → Overview. A GUID, or your domain — acme.onmicrosoft.com."
    ),
    # Single-tenant app registrations are the common case and `/common/` does not
    # serve them. Deriving every endpoint from the tenant makes both kinds work
    # without asking the admin which they made.
    issuer_template="https://login.microsoftonline.com/{tenant}/v2.0",
    console_url="https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
    console_steps=(
        "Entra admin centre → App registrations → New registration.",
        "Add the redirect URIs below as a Web platform.",
        "Certificates & secrets → New client secret. Copy it now; it is shown once.",
        "API permissions → add the permissions below, then Grant admin consent.",
    ),
    capabilities=(
        SSO,
        Capability(
            key="data",
            name="Excel spreadsheets",
            detail="Read a workbook on OneDrive or SharePoint as a data source.",
            permissions=(
                # `.All` rather than `Files.Read`: a team's workbook usually lives
                # in somebody else's OneDrive or a SharePoint site, and the
                # narrower one reaches only files the signed-in account owns.
                Permission("Files.Read.All", admin_consent=True),
                # Not a permission anybody would guess at. Without it Microsoft
                # issues no refresh token, and the source works for exactly one
                # hour before stopping with an authorization error.
                Permission("offline_access"),
            ),
            redirect_path=DATA_REDIRECT_PATH,
        ),
        Capability(
            key="directory",
            name="Sync people from your directory",
            detail="Create GoalGetter accounts from your tenant, with roles by job title.",
            #: **Two sets, and a deployment picks one** — see `Permission.mode`
            #: and `oauth_client.directory_auth_mode`. They cannot coexist on a
            #: registration: consent is all-or-nothing, and a Cloud Application
            #: Administrator can grant every delegated permission and no app role,
            #: so a mixed set greys the consent button and nothing is granted.
            #:
            #: *Application* is the better shape and the harder one to switch on:
            #: no account, nothing to expire, nobody to offboard — and one consent
            #: press that needs a Privileged Role Administrator.
            #:
            #: *Delegated* is what a Cloud Application Administrator can set up
            #: alone, start to finish. It costs an account: the sync acts as one
            #: person, so it stops if that account is disabled or its password is
            #: reset.
            permissions=(
                # ── Acting as the application ──────────────────────────────
                Permission(
                    "User.Read.All",
                    kind="application",
                    admin_consent=True,
                    mode="application",
                ),
                Permission(
                    "GroupMember.Read.All",
                    kind="application",
                    admin_consent=True,
                    mode="application",
                    optional=True,
                ),
                # Channels, for using a private or shared channel as a team.
                # Optional: without them the Teams themselves still work, and
                # the Teams panel says what to grant.
                Permission(
                    "Channel.ReadBasic.All",
                    kind="application",
                    admin_consent=True,
                    mode="application",
                    optional=True,
                ),
                Permission(
                    "ChannelMember.Read.All",
                    kind="application",
                    admin_consent=True,
                    mode="application",
                    optional=True,
                ),
                # Tells a person from a conference room. **Application only** —
                # the delegated version reads the signed-in user's own mailbox,
                # not everybody's, so it would be a permission that consents
                # cleanly and answers 403 on every account but one.
                Permission(
                    "MailboxSettings.Read",
                    kind="application",
                    admin_consent=True,
                    mode="application",
                    optional=True,
                ),
                # ── Acting as one account ──────────────────────────────────
                Permission(
                    "User.Read.All", admin_consent=True, mode="delegated"
                ),
                Permission(
                    "GroupMember.Read.All",
                    admin_consent=True,
                    mode="delegated",
                    optional=True,
                ),
                Permission(
                    "Channel.ReadBasic.All",
                    admin_consent=True,
                    mode="delegated",
                    optional=True,
                ),
                Permission(
                    "ChannelMember.Read.All",
                    admin_consent=True,
                    mode="delegated",
                    optional=True,
                ),
                # Without this there is no refresh token, and the sync works
                # until the first access token expires and then stops for good.
                Permission("offline_access", mode="delegated"),
            ),
            # Only reached in delegated mode; harmless on a registration that
            # never uses it, and absent it the sign-in has nowhere to return to.
            redirect_path=TENANT_REDIRECT_PATH,
        ),
        Capability(
            key="email",
            name="Send email",
            detail="Invitations and password resets through Microsoft, instead of SMTP.",
            #: **Delegated is the narrower one here, and by a long way.**
            #:
            #: `Mail.Send` as an application permission is described by Entra as
            #: "Send mail as any user", which is exactly what it does — every
            #: mailbox in the tenant, the finance director's included. Narrowing it
            #: is an Exchange Application Access Policy, which the panel generates.
            #:
            #: The delegated version sends as the signed-in account and nothing
            #: else. So a deployment running in delegated mode gets the safer mail
            #: permission for free, with no Exchange work at all.
            permissions=(
                Permission(
                    "Mail.Send",
                    kind="application",
                    admin_consent=True,
                    mode="application",
                ),
                Permission("Mail.Send", mode="delegated"),
                Permission("offline_access", mode="delegated"),
            ),
            # Only reached in delegated mode; harmless on a registration that
            # never uses it, and absent it the sign-in has nowhere to return to.
            redirect_path=TENANT_REDIRECT_PATH,
        ),
        Capability(
            key="teams",
            name="Microsoft Teams",
            detail="Post wins into channels, and use Teams and channels as teams and offices.",
            #: **Delegated, and only delegated exists.** Microsoft lets an
            #: application post to a channel only while migrating messages in, so
            #: posting is always *as somebody* — ideally an account made for it,
            #: such as "GoalGetter". None of these needs admin consent, and the
            #: account can only see and post in Teams it is a member of, which
            #: is also exactly what the picker lists.
            permissions=(
                Permission("Team.ReadBasic.All"),
                Permission("Channel.ReadBasic.All"),
                Permission("ChannelMessage.Send"),
                Permission("offline_access"),
            ),
            # The Excel sign-in's callback, so no new address is needed on the
            # registration.
            redirect_path=DATA_REDIRECT_PATH,
        ),
    ),
)

GOOGLE = Provider(
    key="google",
    name="Google",
    # Fixed rather than templated: Google is one issuer for everybody, and a
    # Workspace domain is not part of it. `issuer_for` uses a template with no
    # `{tenant}` in it as-is.
    issuer_template="https://accounts.google.com",
    console_url="https://console.cloud.google.com/apis/credentials",
    console_steps=(
        "Google Cloud console → APIs & Services → Credentials.",
        "Create credentials → OAuth client ID → Web application.",
        "Add the redirect URIs below under Authorised redirect URIs.",
        "On the OAuth consent screen, choose Internal if this is a Workspace "
        "account — that skips Google's review process entirely.",
        "Enable the APIs the permissions below belong to, for the same project.",
    ),
    capabilities=(
        # Google Workspace signs people in perfectly well, and it is the same
        # credential Sheets already uses — so a Workspace company gets sign-on for
        # no extra setup beyond ticking it. This is the answer to "is the Google
        # connection only for Sheets?": no, and it never was architecturally.
        SSO,
        Capability(
            key="data",
            name="Google Sheets",
            detail="Read a spreadsheet as a data source.",
            # Google has no delegated/application split on the consent screen, so
            # `kind` is empty and the panel does not show a column that would
            # always say the same thing.
            permissions=(
                Permission(
                    "https://www.googleapis.com/auth/spreadsheets.readonly", kind=""
                ),
                # **What makes a picker possible at all.** The Sheets API can read
                # a spreadsheet somebody names but cannot list the ones an account
                # has; only Drive can. The narrower of the two Drive scopes
                # deliberately: metadata lists names and ids and cannot read a
                # single cell, so the grant says exactly what the picker does.
                Permission(
                    "https://www.googleapis.com/auth/drive.metadata.readonly", kind=""
                ),
            ),
            redirect_path=DATA_REDIRECT_PATH,
        ),
        Capability(
            key="directory",
            name="Sync people from your directory",
            detail="Create GoalGetter accounts from Workspace, with roles by job title.",
            permissions=(
                Permission(
                    "https://www.googleapis.com/auth/admin.directory.user.readonly",
                    kind="",
                ),
            ),
            built=False,
        ),
    ),
)

SALESFORCE = Provider(
    key="salesforce",
    name="Salesforce",
    tenant_label="Login host",
    tenant_hint=(
        "login.salesforce.com for production, test.salesforce.com for a sandbox, "
        "or your own My Domain host."
    ),
    console_url="https://help.salesforce.com/s/articleView?id=sf.connected_app_create.htm",
    console_steps=(
        "In Salesforce: Setup → Apps → App Manager → New Connected App.",
        "Tick Enable OAuth Settings and paste the callback URL below.",
        "Add the OAuth scopes listed below, and save. Salesforce takes a few "
        "minutes to activate a new connected app.",
        "Open Manage Consumer Details to copy the consumer key and secret.",
    ),
    capabilities=(
        Capability(
            key="data",
            name="Salesforce records",
            detail="Read opportunities, or anything else a SOQL query returns.",
            permissions=(
                # Salesforce's own names, which are what the console's picker
                # lists — not the OAuth scope strings an admin never sees.
                Permission("api", kind=""),
                # **The one that is not obvious and is not optional.** Without it
                # Salesforce issues no refresh token, and the source works for a
                # couple of hours and then stops — which is precisely the failure
                # this connector had before it signed in properly.
                Permission("refresh_token", kind=""),
            ),
            redirect_path=DATA_REDIRECT_PATH,
        ),
    ),
)

#: Anything else that speaks OIDC.
#:
#: **Not a fallback — the reason SSO stays honest.** Sign-on here has always been
#: provider-agnostic: Okta, Auth0, Keycloak, anything with a discovery document.
#: Folding the credential into this table must not quietly turn that into
#: "Microsoft or Google", so a deployment with its own identity provider gets a
#: connection of its own, typed issuer and all.
OIDC = Provider(
    key="oidc",
    name="Other identity provider",
    issuer_template="",
    console_steps=(
        "In your identity provider, create an OpenID Connect web application.",
        "Add the redirect URI below.",
        "Copy its client ID, client secret, and issuer URL.",
    ),
    capabilities=(SSO,),
)

_CATALOGUE: tuple[Provider, ...] = (MICROSOFT, GOOGLE, SALESFORCE, OIDC)


def catalogue() -> tuple[Provider, ...]:
    """The providers described here, in the order shown.

    Not the whole list — see `derive`. A connector can introduce a provider this
    module has never heard of, and that has to keep working: it is the property
    that makes shipping a connector a self-contained job.
    """
    return _CATALOGUE


def derive(key: str, name: str, scopes: tuple[str, ...]) -> Provider:
    """A minimal definition for a provider only a connector knows about.

    **The extensibility this module must not break.** A provider used to appear
    for registration the moment some connector named it, with no central list to
    edit. Making the catalogue authoritative would have quietly ended that, so
    anything not described above gets a definition built from its own spec: one
    data capability, its own scopes, no tenant and no sign-in.

    Adding it to the catalogue later is then an enrichment — console steps, a
    tenant field, more capabilities — rather than the thing that makes it work.
    """
    return Provider(
        key=key,
        name=name,
        capabilities=(
            Capability(
                key="data",
                name="Data sources",
                detail=f"Read data from {name} on a schedule.",
                # No kind and no consent flag: a connector's spec says what to ask
                # for and nothing about how that provider's console presents it,
                # and inventing an answer would be worse than omitting one.
                permissions=tuple(Permission(scope, kind="") for scope in scopes),
                redirect_path=DATA_REDIRECT_PATH,
            ),
        ),
    )


def get(key: str) -> Provider | None:
    return next((p for p in _CATALOGUE if p.key == key), None)


def capability(provider_key: str, capability_key: str) -> Capability | None:
    provider = get(provider_key)
    if provider is None:
        return None
    return next((c for c in provider.capabilities if c.key == capability_key), None)


def issuer_for(provider_key: str, *, tenant_id: str = "", stored: str = "") -> str:
    """The OIDC discovery base for a connection.

    **Derived wherever it can be**, because an issuer is a URL with a GUID in the
    middle of it and asking somebody to type one correctly is asking for a support
    conversation. Microsoft's is a template around the tenant id, which is a value
    the admin can see on one screen and copy.

    Falls back to what was stored, which is the whole of the answer for a provider
    we ship no template for.
    """
    provider = get(provider_key)
    if provider is None:
        return (stored or "").rstrip("/")
    template = provider.issuer_template
    tenant = (tenant_id or "").strip()
    # A template with no `{tenant}` in it is a fixed issuer — Google is one issuer
    # for every customer — so it needs nothing filled in and must not be skipped
    # for want of a tenant id that will never exist.
    if template and "{tenant}" not in template:
        return template
    if template and tenant:
        return template.format(tenant=tenant)
    return (stored or "").rstrip("/")


def offered(provider: Provider, *, has_connector: bool) -> set[str]:
    """Which of a provider's capabilities this build can actually offer.

    Only one rule, and it earns its own function because inline it was untestable:
    **a data capability with no connector shipping for it is not offered.** A
    checkbox that unlocks nothing is a checkbox that costs somebody an afternoon in
    an admin console. It matters for a catalogue provider whose connector is later
    removed — the entry stays, the capability should not.
    """
    return {
        cap.key
        for cap in provider.capabilities
        if cap.key != "data" or has_connector
    }


def needs_typed_issuer(provider: Provider) -> bool:
    """Whether the admin has to supply an issuer rather than it being known.

    False for a provider whose issuer is fixed *or* derivable from a tenant id.
    True only for one we ship nothing for, which is the whole of what the generic
    OIDC entry exists to serve.
    """
    return not provider.issuer_template


# These two take the `Provider` rather than its key on purpose. Looking the key up
# here would silently return nothing for a provider that only a connector knows
# about — which is exactly what happened, and what a test caught: a derived
# provider was listed with an empty scope list, so its setup panel would have told
# an admin to grant no permissions at all.
#: How the sync and outgoing mail authenticate. See the directory capability.
AUTH_MODES = ("application", "delegated")
DEFAULT_AUTH_MODE = "application"


def permissions_for(
    provider: Provider, capability_keys: set[str], mode: str = DEFAULT_AUTH_MODE
) -> list[tuple[Permission, str]]:
    """Every permission the switched-on capabilities need, with what each is for.

    The point of the whole capability model: an admin does not work out which
    permissions a feature wants, the setup panel tells them — and it tells them
    about exactly the features they turned on, not every feature that exists.

    Paired with the capability's name, because "why am I granting this?" is the
    question an admin asks at precisely the moment they are being asked to hand
    over read access to their whole directory. Deduplicated by name, keeping the
    first reason — a permission two capabilities need is granted once.
    """
    found: list[tuple[Permission, str]] = []
    seen: set[tuple[str, str]] = set()
    for cap in provider.capabilities:
        if cap.key not in capability_keys:
            continue
        for permission in cap.permissions:
            # A permission belonging to the other mode is not merely unused — put
            # on the registration it would break consent for everything else.
            if permission.mode and permission.mode != mode:
                continue
            # By name *and kind*: `Channel.ReadBasic.All` is wanted twice on an
            # application-mode registration — as an app role for reading every
            # Team's channels, and delegated for the account that posts — and
            # they are two different permissions in Entra that share a label.
            if (permission.name, permission.kind) in seen:
                continue
            seen.add((permission.name, permission.kind))
            found.append((permission, cap.name))
    return found


def scopes_for(
    provider: Provider, capability_keys: set[str], mode: str = DEFAULT_AUTH_MODE
) -> list[str]:
    """Just the names, which is what goes in the authorization request."""
    return [p.name for p, _ in permissions_for(provider, capability_keys, mode)]


def redirect_paths_for(provider: Provider, capability_keys: set[str]) -> list[str]:
    """The callbacks the switched-on capabilities send the browser back to."""
    found: list[str] = []
    for cap in provider.capabilities:
        if cap.key in capability_keys and cap.redirect_path:
            if cap.redirect_path not in found:
                found.append(cap.redirect_path)
    return found
