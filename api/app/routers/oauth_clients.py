"""Registering an OAuth application, and the two-step sign-in that uses it.

Two audiences in one file, which is why it is one file: the settings half is what
an admin does once per deployment, and the connect half is what they do per source.
Splitting them would put the redirect URI they have to paste into the provider in a
different module from the callback that receives it, and those two must agree
exactly or nothing works.

**The redirect URI is fixed and contains no source id.** A provider validates it
against a registered list, so it cannot vary per source — which means the callback
has to learn which source it is for some other way. It comes from the sealed cookie
the authorize step set, which was already carrying the PKCE verifier.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from html import escape as html_escape

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit, connectors, entra, oauth, public_url
from app import providers as providers_catalogue
from app.crypto import decrypt, encrypt
from app.db import get_db
from app.models import DataSource, OauthClient, SsoConfig, UserAccount
from app.oauth import OAuthProblem, OAuthSpec
from app.oidc import new_flow_state
from app.routers import excel as excel_router
from app.routers import sheets as sheets_router
from app.sessions import require_role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["integrations"])

#: Where a provider sends the browser back to. Must match what is registered.
CALLBACK_PATH = "/api/integrations/oauth/callback"

#: The cookie carrying the in-flight authorization.
FLOW_COOKIE = "gg_connect_flow"

#: How long an admin has to finish approving.
#:
#: Long enough to read a consent screen and pick the right account, short enough
#: that a cookie left in a browser overnight cannot be replayed.
FLOW_TTL_SECONDS = 600


# ── Registering the application ──────────────────────────────────────────────


class CapabilityRead(BaseModel):
    """One thing a connection powers, and whether it currently does.

    **Nothing here is stored.** `active` is read off the feature itself — single
    sign-on is on because the SSO settings say so, data is on because a source
    actually uses a connector for this provider. A saved list of ticked boxes would
    be a third place that could disagree with the other two.
    """

    key: str
    name: str
    detail: str
    #: False for a capability that is designed but not built. Shown greyed rather
    #: than hidden, so "can this sync my people?" has a findable answer.
    built: bool
    active: bool


class PermissionRead(BaseModel):
    """One permission to add in the provider's console, described so it can be
    acted on without reading the provider's documentation."""

    name: str
    #: `delegated`, `application`, or empty for a provider with no such split.
    kind: str
    #: Whether a tenant admin has to press *Grant admin consent* as well as add it.
    admin_consent: bool
    #: Which capability wants it. "Why am I granting this?" is the question an
    #: admin asks exactly when being told to hand over directory-wide read access.
    needed_for: str
    #: Whether the capability works without it, in reduced form. Shown, because
    #: an admin weighing a broad permission deserves to know which ones they can
    #: decline and still have a working sync.
    optional: bool


class BootstrapRead(BaseModel):
    """What the panel needs to offer creating the application automatically.

    Present only for a provider that supports it. Everything here is describing
    the offer *before* anybody presses anything — what will be created, who is
    allowed to, and whose name appears on the consent screen. All three are things
    an admin should know in advance rather than discover from a refusal.
    """

    #: What the created application is called in their directory.
    app_name: str
    #: The lowest role that can finish this, in the provider's own vocabulary.
    minimum_role: str
    #: Whose name the consent screen shows, which is not ours — see
    #: `providers.Bootstrap`.
    consent_name: str
    #: What the admin is consenting to for the setup itself. Distinct from the
    #: connection's own permissions, held only for the length of the flow.
    scopes: list[str]
    #: The sign-in modes this provider offers, and which one is in force.
    #:
    #: **Chosen before provisioning, not after.** The two permission sets cannot
    #: share a registration — consent is all-or-nothing, and an admin who can grant
    #: every delegated permission can grant no app role — so the choice decides
    #: what gets written, and changing it means provisioning again.
    modes: list[str]

    #: Where to grant the one-time tenant-wide consent for the bootstrap client.
    #:
    #: **Shown up front, not saved for an error path.** Until this consent exists
    #: in a tenant, the sign-in ends on the provider's ordinary *user* prompt —
    #: "ask an admin to grant permission" — which offers an admin no way to grant
    #: it even though their role allows it. Worse, nothing is refused: the device
    #: code simply never completes, so a panel that waited for a failure would
    #: wait the full fifteen minutes and then say the code expired.
    consent_url: str


class ProviderRead(BaseModel):
    """One provider this deployment can hold a single credential for."""

    provider: str
    provider_name: str
    #: Which connectors use it, so the page can say what connecting unlocks
    #: rather than listing bare provider names. Empty for a provider that only
    #: signs people in.
    used_by: list[str]
    #: The raw strings, kept because the connect flow and anything scripting this
    #: want them without the console vocabulary around them.
    scopes: list[str]
    #: The same list, described for somebody standing in the admin console.
    permissions: list[PermissionRead]

    client_id: str | None
    #: Whether a secret is stored. Never the secret — same rule as everywhere.
    client_secret_set: bool
    last_used_at: datetime | None

    #: How the directory sync and outgoing mail authenticate — see
    #: `oauth_client.directory_auth_mode`. Reported so the panel can show which
    #: was chosen, and what the consequences are.
    auth_mode: str

    #: Microsoft's directory id, and the label to ask for it under. An empty
    #: label means this provider has no such concept and the field is not shown.
    tenant_id: str | None
    tenant_label: str
    tenant_hint: str

    #: Where sign-in discovers the provider's endpoints. Derived from the tenant
    #: where it can be, which is why it is reported rather than always asked for.
    issuer: str | None
    #: True when the issuer cannot be derived and has to be typed — an identity
    #: provider we ship no connector for.
    issuer_required: bool

    #: What this one credential powers.
    capabilities: list[CapabilityRead]

    #: Every callback the switched-on capabilities need registered. Shown because
    #: a mismatch here is the single most common setup failure, and the error a
    #: provider returns for it does not say what it expected.
    redirect_uris: list[str]
    where_to_get_it: str
    setup_steps: list[str]

    #: How to skip all of the above. None for a provider that can only be
    #: registered by hand, which is every one except Microsoft today.
    bootstrap: BootstrapRead | None


class ProviderWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_id: str = Field(min_length=1, max_length=500)
    #: Omit entirely to keep the stored secret. Sending `""` is refused rather
    #: than treated as "keep": an empty box that silently means "no change" is a
    #: box somebody will use to try to clear the value.
    client_secret: str | None = Field(default=None, min_length=1, max_length=2000)
    #: `None` leaves these alone; `""` clears them. Same rule as the secret, so
    #: there is one convention on this endpoint rather than two.
    tenant_id: str | None = Field(default=None, max_length=200)
    issuer: str | None = Field(default=None, max_length=500)


def _specs() -> dict[str, tuple[OAuthSpec, list[str]]]:
    """Every provider the registered connectors need, and who needs it.

    Derived from the connectors rather than from a list, so a provider appears in
    Settings the moment a connector for it ships and disappears when it is
    removed. A settings page offering a registration nothing can use is a page
    that invites somebody to do pointless work.
    """
    found: dict[str, tuple[OAuthSpec, list[str]]] = {}
    for connector in connectors.available():
        spec = connectors.oauth_of(connector)
        if spec is None:
            continue
        assert isinstance(spec, OAuthSpec)
        if spec.provider in found:
            found[spec.provider][1].append(connector.display_name)
        else:
            found[spec.provider] = (spec, [connector.display_name])
    return found


def _definitions(
    specs: dict[str, tuple[OAuthSpec, list[str]]],
) -> list[providers_catalogue.Provider]:
    """Every provider a connection can be made to: the catalogue, plus the
    connectors.

    **A union, and both halves matter.** The catalogue carries providers with no
    connector — an identity provider used only for signing in still needs somewhere
    to put its client id. The connectors carry providers with no catalogue entry,
    which is what keeps shipping a connector a self-contained job: name a provider
    in a spec and it appears here, with no central list to remember to edit.

    Catalogue order first, because those are the ones with setup steps written for
    them, then anything else alphabetically.
    """
    described = list(providers_catalogue.catalogue())
    known = {p.key for p in described}
    extra = [
        providers_catalogue.derive(key, spec.provider_name, tuple(spec.scopes))
        for key, (spec, _) in sorted(specs.items())
        if key not in known
    ]
    return described + extra


def _redirect_uri(db: DbSession) -> str:
    """Assembled from the address in Settings, like every other externally visible URL here."""
    return f"{public_url.get(db)}{CALLBACK_PATH}"


def _active_capabilities(db: DbSession, org_id: int, provider: str) -> set[str]:
    """Which capabilities this connection is actually powering, right now.

    Asked of the features themselves rather than of a stored list, so the card
    cannot claim something the rest of the product disagrees with.
    """
    active: set[str] = set()

    config = db.scalar(select(SsoConfig).where(SsoConfig.organization_id == org_id))
    if config is not None and config.enabled and config.provider == provider:
        active.add("sso")

    # **Stored rather than derived, and the exception is on purpose.** There is
    # nothing else to read it off: a connection existing says nothing about
    # whether a company wants two hundred accounts proposed from it, so the switch
    # is a column — see `oauth_client.directory_sync_enabled`. Leaving it out of
    # here is what made the card say "○ Sync people from your directory" to
    # somebody who had just switched it on.
    connection = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == org_id, OauthClient.provider == provider
        )
    )
    if connection is not None and connection.directory_sync_enabled:
        active.add("directory")
    # Switched on in the Microsoft 365 box, and configured in their own cards.
    if connection is not None and connection.mail_enabled:
        active.add("email")
    if provider == "microsoft":
        from app.models import Organization

        org = db.get(Organization, org_id)
        if org is not None and org.teams_enabled:
            active.add("teams")

    keys = [
        connector.key
        for connector in connectors.available()
        if getattr(connectors.oauth_of(connector), "provider", None) == provider
    ]
    if keys:
        using = db.scalar(
            select(DataSource.id)
            .where(
                DataSource.organization_id == org_id,
                DataSource.connector.in_(keys),
                DataSource.archived_at.is_(None),
                # A draft nobody finished is not a thing this connection powers.
                DataSource.activated_at.is_not(None),
            )
            .limit(1)
        )
        if using is not None:
            active.add("data")

    return active


def _wanted(
    definition: providers_catalogue.Provider,
    *,
    used_by: list[str],
    active: set[str],
) -> set[str]:
    """Which capabilities the registration is for.

    What is switched on, falling back to everything available when nothing is yet —
    on a fresh connection the admin needs the full list, because they are about to
    turn things on.

    **Built capabilities only, and this was wrong first time.** A fresh Microsoft
    connection asked an admin to grant `User.Read.All`, `GroupMember.Read.All` and
    `Mail.Send` — permissions for directory sync and email, neither of which exists
    yet. Two of those need admin consent, so the panel was asking somebody to hand
    over tenant-wide read access for a feature that does nothing. Found by looking
    at the real page rather than by a test.

    **Its own function because two things now depend on it.** The panel describes
    what to grant and `bootstrap_poll` goes and grants it, and those two answering
    differently would produce an application whose permissions do not match the
    ones the admin was shown.
    """
    available = providers_catalogue.offered(definition, has_connector=bool(used_by))
    buildable = {
        cap.key for cap in definition.capabilities if cap.built and cap.key in available
    }
    return active or buildable


def _describe(
    definition: providers_catalogue.Provider,
    row: OauthClient | None,
    *,
    used_by: list[str],
    active: set[str],
    base: str,
) -> ProviderRead:
    available = providers_catalogue.offered(definition, has_connector=bool(used_by))
    issuer = providers_catalogue.issuer_for(
        definition.key,
        tenant_id=(row.tenant_id if row else "") or "",
        stored=(row.issuer if row else "") or "",
    )
    wanted = _wanted(definition, used_by=used_by, active=active)
    mode = row.directory_auth_mode if row else providers_catalogue.DEFAULT_AUTH_MODE
    return ProviderRead(
        provider=definition.key,
        provider_name=definition.name,
        used_by=sorted(used_by),
        scopes=providers_catalogue.scopes_for(definition, wanted, mode),
        permissions=[
            PermissionRead(
                name=permission.name,
                kind=permission.kind,
                admin_consent=permission.admin_consent,
                needed_for=why,
                optional=permission.optional,
            )
            for permission, why in providers_catalogue.permissions_for(
                definition, wanted, mode
            )
        ],
        auth_mode=(
            row.directory_auth_mode if row else providers_catalogue.DEFAULT_AUTH_MODE
        ),
        client_id=row.client_id if row else None,
        client_secret_set=bool(row and row.client_secret_encrypted),
        last_used_at=row.last_used_at if row else None,
        tenant_id=(row.tenant_id if row else None),
        tenant_label=definition.tenant_label,
        tenant_hint=definition.tenant_hint,
        issuer=issuer or None,
        issuer_required=providers_catalogue.needs_typed_issuer(definition),
        capabilities=[
            CapabilityRead(
                key=cap.key,
                name=cap.name,
                detail=cap.detail,
                built=cap.built,
                active=cap.key in active,
            )
            for cap in definition.capabilities
            if cap.key in available
        ],
        redirect_uris=[
            f"{base}{path}"
            for path in providers_catalogue.redirect_paths_for(definition, wanted)
        ],
        where_to_get_it=definition.console_url,
        setup_steps=list(definition.console_steps),
        bootstrap=(
            BootstrapRead(
                app_name=definition.bootstrap.app_name,
                minimum_role=definition.bootstrap.minimum_role,
                consent_name=definition.bootstrap.consent_name,
                modes=list(providers_catalogue.AUTH_MODES),
                consent_url=definition.bootstrap.consent_url(
                    entra.client_id_for(definition.bootstrap)
                ),
                scopes=[
                    scope
                    for scope in definition.bootstrap.scopes
                    # The two that describe the sign-in rather than granting
                    # anything. Listing them next to `Application.ReadWrite.All`
                    # pads the one list an admin should actually read closely.
                    if scope not in ("openid", "profile")
                ],
            )
            if definition.bootstrap
            else None
        ),
    )


@router.get("/integrations/oauth-clients", response_model=list[ProviderRead])
def list_providers(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[ProviderRead]:
    """Every provider a connection can be made to, and what each one powers.

    **Driven by the catalogue, not only by the connectors.** A provider used to
    appear here solely because a connector named it, which was right when this was
    a list of connector registrations and wrong now that it is the list of a
    deployment's connections: an identity provider we ship no connector for still
    needs somewhere to put its client id.
    """
    stored = {
        row.provider: row
        for row in db.scalars(
            select(OauthClient).where(
                OauthClient.organization_id == actor.organization_id
            )
        ).all()
    }
    specs = _specs()

    return [
        _describe(
            definition,
            stored.get(definition.key),
            used_by=specs[definition.key][1] if definition.key in specs else [],
            active=_active_capabilities(db, actor.organization_id, definition.key),
            base=public_url.get(db),
        )
        for definition in _definitions(specs)
    ]


@router.put("/integrations/oauth-clients/{provider}", response_model=ProviderRead)
def save_provider(
    provider: str,
    payload: ProviderWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ProviderRead:
    """Store the credential for one provider connection."""
    known = {d.key for d in _definitions(_specs())}
    if provider not in known:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"{provider!r} is not a provider this build connects to. "
                f"It knows: {', '.join(sorted(known))}."
            ),
        )

    try:
        oauth.store_client(
            db,
            org_id=actor.organization_id,
            provider=provider,
            client_id=payload.client_id.strip(),
            client_secret=payload.client_secret,
            actor_id=actor.id,
            tenant_id=(payload.tenant_id.strip() if payload.tenant_id is not None else None),
            issuer=(
                payload.issuer.strip().rstrip("/") if payload.issuer is not None else None
            ),
        )
    except OAuthProblem as problem:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(problem)
        ) from None

    audit.record(
        db,
        actor=actor,
        action="oauth_client.saved",
        request=request,
        provider=provider,
        # Whether the secret was touched, never the secret.
        secret_changed=payload.client_secret is not None,
    )
    db.commit()
    return next(p for p in list_providers(actor=actor, db=db) if p.provider == provider)


# ── Registering it automatically ─────────────────────────────────────────────
#
# The same outcome as the form above — a client id, a secret and a tenant on the
# same row — reached without anybody visiting an admin console. `app/entra.py`
# explains why this is possible at all for software nobody hosts.


#: The cookie carrying an in-flight setup.
SETUP_COOKIE = "gg_setup_flow"

#: Scoped to the endpoints below, like the connect flow's own cookie.
SETUP_PATH = "/api/integrations/oauth-clients"

#: How long the whole thing may take.
#:
#: Microsoft expires the code itself at fifteen minutes; this is the same window
#: with a minute of slack, so the expiry somebody is told about is Microsoft's
#: rather than a shorter one of ours that would look like a bug.
SETUP_TTL_SECONDS = 960


class SetupStart(BaseModel):
    """The code to enter, and where to enter it."""

    user_code: str
    #: Microsoft's, as given. Not a constant here: it differs by cloud, and a
    #: sovereign tenant sends its admins somewhere else entirely.
    verification_uri: str
    #: Seconds between polls, and seconds until the code dies. Both Microsoft's
    #: numbers, so the page counts down to the same moment the code does.
    interval: int
    expires_in: int


class SetupPoll(BaseModel):
    """Whether the admin has finished, and what exists now that they have."""

    #: `pending` while they are still signing in, `done` once it is created.
    status: str
    #: The connection as it now stands. Exactly what `save_provider` returns, so
    #: the page updates through the same path as the manual form.
    provider: ProviderRead | None = None
    #: Permissions that are granted and working.
    granted: list[str] = []
    #: Permissions the application asks for that this admin could not consent to.
    #: **Not a failure.** The registration is real and everything else works —
    #: Microsoft reserves consent for its own application permissions to a more
    #: senior role than the one that can create all of this.
    pending: list[str] = []


def _bootstrap_for(
    provider: str,
) -> tuple[providers_catalogue.Provider, providers_catalogue.Bootstrap, list[str]]:
    """The provider, its bootstrap, and who uses it — or a refusal saying why."""
    specs = _specs()
    definition = next(
        (d for d in _definitions(specs) if d.key == provider), None
    )
    if definition is None or definition.bootstrap is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"{provider!r} cannot register itself. Use the setup steps to "
                "create the application by hand."
            ),
        )
    used_by = specs[provider][1] if provider in specs else []
    return definition, definition.bootstrap, used_by


@router.post(
    "/integrations/oauth-clients/{provider}/bootstrap", response_model=SetupStart
)
def bootstrap_start(
    provider: str,
    response: Response,
    mode: str = providers_catalogue.DEFAULT_AUTH_MODE,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SetupStart:
    """Ask the provider for a sign-in code.

    Only when somebody presses the button, never on page load: the code lives
    fifteen minutes from the moment it is issued, and one fetched while the panel
    was merely open would spend most of that window being read.
    """
    _, bootstrap, _ = _bootstrap_for(provider)
    if mode not in providers_catalogue.AUTH_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown sign-in mode {mode!r}.",
        )

    try:
        code = entra.start(bootstrap)
    except entra.SetupProblem as problem:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(problem)
        ) from None

    # The device code, encrypted, for the same reason the connect flow seals its
    # verifier: anybody holding it could collect the token the admin is at that
    # moment approving. Never returned to the page — what goes on screen is the
    # short user code, which is useless without it.
    response.set_cookie(
        SETUP_COOKIE,
        encrypt(
            json.dumps(
                {
                    "provider": provider,
                    "mode": mode,
                    "device_code": code.device_code,
                    "exp": time.time() + SETUP_TTL_SECONDS,
                }
            )
        ),
        max_age=SETUP_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=public_url.is_https(db),
        path=SETUP_PATH,
    )
    logger.info("Started %s setup for organization %s", provider, actor.organization_id)
    return SetupStart(
        user_code=code.user_code,
        verification_uri=code.verification_uri,
        interval=code.interval,
        expires_in=code.expires_in,
    )


@router.post(
    "/integrations/oauth-clients/{provider}/bootstrap/poll", response_model=SetupPoll
)
def bootstrap_poll(
    provider: str,
    request: Request,
    response: Response,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SetupPoll:
    """Has the admin finished? If so, create the application and store it.

    **Creating happens here rather than in a third request**, so there is no moment
    where a token capable of writing to somebody's directory is held anywhere
    waiting to be used. It is fetched, spent, and dropped inside one request.
    """
    definition, bootstrap, used_by = _bootstrap_for(provider)

    sealed = request.cookies.get(SETUP_COOKIE)
    if not sealed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That setup took too long. Please start again.",
        )
    try:
        held = json.loads(decrypt(sealed))
    except ValueError:
        # A tampered or re-keyed cookie, and nonsense that decrypts. Both mean the
        # same thing to whoever is reading the screen — see the connect callback,
        # which documents the same pair.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That setup could not be verified. Please start again.",
        ) from None

    if held.get("exp", 0) < time.time() or held.get("provider") != provider:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That setup took too long. Please start again.",
        )

    try:
        approval = entra.poll(bootstrap, str(held.get("device_code") or ""))
    except entra.SetupProblem as problem:
        # Terminal: declined, expired, or refused outright. The cookie is left
        # alone rather than cleared — raising discards anything set on the
        # injected response, and pressing the button again overwrites it with a
        # fresh code anyway. The page stops polling on this, so a dead cookie is
        # never asked about twice.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(problem)
        ) from None

    if approval is None:
        return SetupPoll(status="pending")

    # **Everything this build can do, not only what is switched on today.**
    #
    # `_describe` narrows to the active capabilities, which is right for a panel
    # telling somebody what to grant *now*. Provisioning is the opposite case:
    # admin consent is the expensive step — it needs a senior role and a separate
    # trip — so asking only for what happens to be on means every later toggle
    # costs another re-run and another consent. Asking for the whole buildable set
    # once means switching mail on later is a toggle.
    wanted = _wanted(definition, used_by=used_by, active=set())
    mode = str(held.get("mode") or providers_catalogue.DEFAULT_AUTH_MODE)
    base = public_url.get(db)

    try:
        registration = entra.provision(
            approval,
            app_name=bootstrap.app_name,
            # The same two functions the panel renders from, so an application
            # created here asks for exactly what the manual steps would have told
            # somebody to add. A mismatched redirect URI is the most common way
            # this whole area fails, and this is what makes it unable to happen.
            redirect_uris=[
                f"{base}{path}"
                for path in providers_catalogue.redirect_paths_for(definition, wanted)
            ],
            permissions=[
                permission
                for permission, _ in providers_catalogue.permissions_for(
                    definition, wanted, mode
                )
            ],
        )
        stored = oauth.store_client(
            db,
            org_id=actor.organization_id,
            provider=provider,
            client_id=registration.client_id,
            client_secret=registration.client_secret,
            actor_id=actor.id,
            tenant_id=registration.tenant_id,
        )
        # Recorded on the row, because everything downstream reads it from there:
        # which token to mint, which permissions the panel lists, and whether an
        # account has to be signed in at all.
        stored.directory_auth_mode = mode
        db.flush()
    except (entra.SetupProblem, OAuthProblem) as problem:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(problem)
        ) from None

    audit.record(
        db,
        actor=actor,
        action="oauth_client.provisioned",
        request=request,
        provider=provider,
        tenant_id=registration.tenant_id,
        # What was and was not consented to. The pending list is the one thing
        # somebody will need months later to explain a permission error, and it is
        # nowhere else — the connection row holds a credential, not a history.
        granted=list(registration.granted),
        pending=list(registration.pending),
    )
    db.commit()

    response.delete_cookie(SETUP_COOKIE, path=SETUP_PATH)
    return SetupPoll(
        status="done",
        provider=next(
            p for p in list_providers(actor=actor, db=db) if p.provider == provider
        ),
        granted=list(registration.granted),
        pending=list(registration.pending),
    )


@router.delete(
    "/integrations/oauth-clients/{provider}", status_code=status.HTTP_204_NO_CONTENT
)
def forget_provider(
    provider: str,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Remove a registration.

    **Leaves existing sources alone**, and that is deliberate: their stored access
    tokens keep working until they expire and then fail with a message naming the
    missing registration. Revoking access to live sources as a side effect of
    tidying up Settings would be a much worse surprise than a sync that stops and
    says why.
    """
    row = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == actor.organization_id,
            OauthClient.provider == provider,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nothing registered."
        )
    db.delete(row)
    audit.record(
        db, actor=actor, action="oauth_client.forgotten", request=request,
        provider=provider,
    )
    db.commit()


# ── Signing in for one source ────────────────────────────────────────────────


def _spec_for(db: DbSession, actor: UserAccount, source_id: int) -> tuple[DataSource, OAuthSpec]:
    """The source and the spec it signs in with, or a refusal."""
    source = db.get(DataSource, source_id)
    if source is None or source.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Source not found."
        )
    try:
        connector = connectors.get(source.connector)
    except connectors.UnknownConnector as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from None

    spec = connectors.oauth_of(connector)
    if not isinstance(spec, OAuthSpec):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{connector.display_name} does not sign in to anything.",
        )
    return source, spec


class Authorization(BaseModel):
    """Where to send the browser next."""

    url: str


@router.post("/data-sources/{source_id}/authorize", response_model=Authorization)
def authorize(
    source_id: int,
    response: Response,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> Authorization:
    """Begin the sign-in for one source.

    Returns the URL rather than a redirect, because the caller is `fetch` from a
    single-page app: a 303 here would be followed by the browser inside the XHR
    and the consent screen would be rendered into a JSON parse error. The page
    navigates to what this returns.
    """
    source, spec = _spec_for(db, actor, source_id)

    try:
        client = oauth.client_for(db, actor.organization_id, spec.provider)
    except OAuthProblem as problem:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(problem)
        ) from None

    flow = new_flow_state()
    url = oauth.authorization_url(
        spec, client, redirect_uri=_redirect_uri(db), flow=flow
    )

    # The verifier and the source id, encrypted into a cookie. Encrypted rather
    # than signed because it holds the PKCE verifier: anyone who could read it and
    # intercept the code could complete the exchange. Fernet is authenticated, so
    # a tampered cookie fails to open rather than quietly changing which source
    # gets the tokens — which would be a way to point somebody's Google account at
    # a source they did not choose.
    response.set_cookie(
        FLOW_COOKIE,
        encrypt(
            json.dumps(
                {
                    "state": flow.state,
                    "verifier": flow.code_verifier,
                    "source_id": source.id,
                    "exp": time.time() + FLOW_TTL_SECONDS,
                }
            )
        ),
        max_age=FLOW_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=public_url.is_https(db),
        path=CALLBACK_PATH,
    )
    return Authorization(url=url)


#: What the popup posts back to the page that opened it.
#:
#: A page rather than a redirect, because the browser is in a popup the connect
#: flow opened and the flow is still sitting there behind it. Redirecting would
#: leave a second copy of the wizard inside a 520-pixel window while the real one
#: waits forever — and closing the popup is what makes this feel like a sign-in
#: button rather than a page you get sent away to.
#:
#: **It still works with no opener.** A provider that lost the popup, a pasted
#: callback URL, a browser that blocked `window.open` — all end up here in a normal
#: tab, and the same page redirects instead. One response that handles both beats
#: two that can disagree.
_COMPLETE_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Connecting…</title>
<body style="font:14px system-ui;padding:2rem;color:#444">
<p id="m">Finishing up…</p>
<script>
(function () {
  var result = JSON.parse(document.currentScript.dataset.result);
  if (window.opener && !window.opener.closed) {
    // Targeted at our own origin, never "*": this message is the signal that a
    // credential was stored, and any page that could receive it could act on it.
    window.opener.postMessage({ source: "goalgetter-oauth", result: result }, %(origin)s);
    window.close();
    return;
  }
  var to = result.source_id
    ? "/integrations/connect/" + result.source_id
    : "/integrations";
  if (result.error) to += "?error=" + encodeURIComponent(result.error);
  document.getElementById("m").textContent = result.error || "Connected.";
  window.location.replace(to);
})();
</script>
</body>"""


def _back(db: DbSession, source_id: int | None, message: str | None = None) -> HTMLResponse:
    """Hand the outcome back to whoever started this.

    The same response whether it is in a popup or a tab — see `_COMPLETE_PAGE`.
    """
    payload = json.dumps({"source_id": source_id, "error": message})
    origin = public_url.get(db)
    page = _COMPLETE_PAGE % {"origin": json.dumps(origin)}
    # In a data attribute rather than interpolated into the script body, so the
    # payload is parsed as data and can never be parsed as code.
    page = page.replace(
        "<script>", f'<script data-result="{html_escape(payload, quote=True)}">', 1
    )
    return HTMLResponse(page)


@router.get("/integrations/oauth/callback")
def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: DbSession = Depends(get_db),
) -> HTMLResponse:
    """Where the provider sends the browser back.

    **Unauthenticated by necessity** — a provider redirect carries no session
    cookie for a cross-site navigation in every browser, and the flow cookie is
    the credential that makes this safe: it is encrypted, short-lived, scoped to
    this path, and carries the `state` that must match what came back.

    Every failure ends in a redirect with a readable message rather than an
    exception, because the person reading it is looking at a browser window they
    were sent to, not at a response body.
    """
    sealed = request.cookies.get(FLOW_COOKIE)
    if not sealed:
        return _back(db, None, "That sign-in took too long. Please try again.")

    try:
        held = json.loads(decrypt(sealed))
    except ValueError:
        # Both failures that can happen here are ValueErrors and both mean the
        # same thing to the person reading the screen: `crypto.decrypt` documents
        # that contract for a tampered or re-keyed value, and `json.loads` raises
        # a subclass for anything that decrypts to nonsense.
        return _back(db, None, "That sign-in could not be verified. Please try again.")

    source_id = held.get("source_id")
    if held.get("exp", 0) < time.time():
        return _back(db, source_id, "That sign-in took too long. Please try again.")

    # **Two flows share one redirect URI, on purpose.** The other is the org-wide
    # Excel account (`routers/excel.py`), which needs a callback and must not need
    # a second address added to the app registration — that registration is
    # already provisioned and correct, and editing it is exactly what this design
    # set out to avoid. The cookie says which flow this is; nothing else overlaps.
    if held.get("account") == "sheets":
        if error:
            return _back(db, 
                None,
                "Sign-in was cancelled."
                if error == "access_denied"
                else f"{error.replace('_', ' ').capitalize()}.",
            )
        if not code or not state or state != held.get("state"):
            return _back(db, None, "That sign-in did not match. Please try again.")
        return _back(db, 
            None,
            sheets_router.complete_account(
                db, held, code=code, verifier=held["verifier"]
            ),
        )

    if held.get("account") == "teams":
        # The account announcements post to picked Teams channels as.
        from app.routers import announcements as announcements_router

        if error:
            return _back(db, 
                None,
                "Sign-in was cancelled."
                if error == "access_denied"
                else f"{error.replace('_', ' ').capitalize()}.",
            )
        if not code or not state or state != held.get("state"):
            return _back(db, None, "That sign-in did not match. Please try again.")
        return _back(db, 
            None,
            announcements_router.complete_account(db, held, code=code, verifier=held["verifier"]),
        )

    if held.get("account") == "excel":
        if error:
            return _back(db, 
                None,
                "Sign-in was cancelled."
                if error == "access_denied"
                else f"{error.replace('_', ' ').capitalize()}.",
            )
        if not code or not state or state != held.get("state"):
            return _back(db, None, "That sign-in did not match. Please try again.")
        return _back(db, 
            None,
            excel_router.complete_account(
                db, held, code=code, verifier=held["verifier"]
            ),
        )

    if error:
        # The provider's own word for what happened — `access_denied` when
        # somebody pressed cancel, which is not an error worth alarming them over.
        readable = (
            "Sign-in was cancelled."
            if error == "access_denied"
            else f"{error.replace('_', ' ').capitalize()}."
        )
        return _back(db, source_id, readable)

    if not code or not state or state != held.get("state"):
        # A mismatched state is the one case worth being blunt about: it means the
        # response did not come from the request we made.
        return _back(db, source_id, "That sign-in did not match. Please try again.")

    source = db.get(DataSource, source_id) if source_id else None
    if source is None:
        return _back(db, None, "That source no longer exists.")

    try:
        connector = connectors.get(source.connector)
        spec = connectors.oauth_of(connector)
        assert isinstance(spec, OAuthSpec)
        client = oauth.client_for(db, source.organization_id, spec.provider)
        tokens = oauth.exchange(
            spec,
            client,
            code=code,
            redirect_uri=_redirect_uri(db),
            code_verifier=held["verifier"],
        )
        if not tokens.get("refresh_token"):
            # Worth its own message: without one the source works until the access
            # token expires and then stops for good. The usual cause is a provider
            # that only issues one on first consent — see `extra_authorize_params`.
            logger.warning("No refresh token for source %s", source.id)
        oauth.save_tokens(db, source, client, tokens)
        db.commit()
    except OAuthProblem as problem:
        return _back(db, source_id, str(problem))
    except Exception as problem:  # noqa: BLE001 — reported to a person, and logged
        logger.warning("Token exchange failed for source %s", source_id, exc_info=problem)
        return _back(db, source_id, "Could not complete that sign-in. Please try again.")

    cleared = _back(db, source_id)
    cleared.delete_cookie(FLOW_COOKIE, path=CALLBACK_PATH)
    return cleared
