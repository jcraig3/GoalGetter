"""Connector OAuth: the sign-in button, and keeping the token alive.

**Different job from `app/oidc.py`.** That one answers "who is this person",
returns an id token, and ends in a session. This one answers "may we read your
spreadsheets on your behalf", returns a *refresh* token, and ends in a stored
credential that has to keep working at three in the morning six months later. They
share the authorization-code dance and nothing else, so the pieces that genuinely
overlap — PKCE, the sealed flow cookie, the code exchange — are imported rather
than rewritten.

**A connector declares what it needs and this arranges it.** One `OAuthSpec` on the
connector names the provider, the two endpoints and the scopes; three behaviours
follow, the same way `endpoint_credential` works:

* setup shows *Sign in with Google* instead of a credentials form;
* the callback fills the credential in, so nobody types a token;
* the sync refreshes it before use, without asking anybody anything.

**The refresh merges.** `credentials.put` replaces, for reasons argued in its own
docstring — but a refresh response usually contains an access token and no refresh
token, so replacing would throw away the only thing that can renew the next one and
the integration would die at the first expiry. Merging keeps it, and still picks up
a rotated one when the provider sends it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import credentials as credential_store
from app import oidc
from app.crypto import decrypt, encrypt
from app.models import DataSource, OauthClient

logger = logging.getLogger(__name__)

#: How long before expiry to renew.
#:
#: A token that expires while a sync is halfway through it is a sync that fails
#: for no reason anybody can act on. Five minutes covers a slow warehouse query
#: that started just inside the window.
REFRESH_MARGIN = timedelta(minutes=5)

#: What to assume when a provider does not say how long its token lasts.
#:
#: Conservative on purpose: guessing too short costs an extra refresh, guessing
#: too long costs a failed sync and a support conversation.
DEFAULT_LIFETIME = timedelta(minutes=30)

HTTP_TIMEOUT = 15.0


@dataclass(frozen=True)
class OAuthSpec:
    """What a connector needs to ask a provider for access.

    Endpoints are stated rather than discovered. OIDC discovery exists for
    identity providers and most data APIs do not publish a document — and for the
    ones that do, a network round trip before showing a button is a round trip
    that can fail in front of somebody who just wants to click it.
    """

    #: Matches `oauth_client.provider`. One registration serves every connector
    #: naming the same provider.
    provider: str
    #: Human name for the button: "Sign in with **Google**".
    provider_name: str
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]

    #: What `{tenant}` becomes when the connection does not say.
    #:
    #: `common` is Microsoft's word for "whichever directory the account belongs
    #: to" and means nothing to anybody else. Salesforce's equivalent is
    #: `login.salesforce.com`, and a sandbox is `test.salesforce.com` — so the
    #: fallback belongs to the spec rather than being one provider's vocabulary
    #: hardcoded into the engine.
    default_tenant: str = "common"

    #: Extra parameters for the authorization request.
    #:
    #: Where the awkward provider-specific requirements live. Google needs
    #: `access_type=offline` to issue a refresh token at all, and
    #: `prompt=consent` to issue a *new* one when the account has approved this
    #: app before — without both, a re-connect silently produces a credential
    #: that cannot be renewed.
    extra_authorize_params: tuple[tuple[str, str], ...] = ()


class OAuthProblem(Exception):
    """Something an admin can act on, phrased for them rather than for a log."""


def client_for(db: DbSession, org_id: int, provider: str) -> OauthClient:
    """This organization's registration for a provider, or a refusal that says so.

    A missing registration is by far the most likely reason an OAuth connector
    does not work, and it has a specific fix — so it gets its own message naming
    the provider rather than surfacing as a generic authorization failure.
    """
    row = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == org_id,
            OauthClient.provider == provider,
        )
    )
    if row is None:
        raise OAuthProblem(
            f"No {provider} application is registered yet. Register it on the "
            "Integrations page — the connect flow offers that step in place the "
            "first time it is needed."
        )
    return row


def secret_of(client: OauthClient) -> str:
    """The decrypted client secret. The only place it is in plaintext."""
    return decrypt(client.client_secret_encrypted)


def store_client(
    db: DbSession,
    *,
    org_id: int,
    provider: str,
    client_id: str,
    client_secret: str | None,
    actor_id: int | None,
    tenant_id: str | None = None,
    issuer: str | None = None,
) -> OauthClient:
    """Save a connection, creating or updating it.

    `client_secret=None` means "leave the stored one alone", so an admin fixing a
    typo in the client ID does not have to go and find the secret again. Empty
    string is not the same thing and is rejected upstream — see the router.

    `tenant_id` and `issuer` follow the same rule for the same reason: `None` is
    "unchanged", `""` clears. They are the two fields that turned this row from a
    connector registration into the deployment's one connection to a provider —
    Microsoft needs a tenant to build both its sign-in issuer and its own
    single-tenant endpoints, and a provider we ship no connector for needs its
    issuer typed.
    """
    row = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == org_id, OauthClient.provider == provider
        )
    )
    if row is None:
        if not client_secret:
            raise OAuthProblem("A client secret is needed the first time.")
        row = OauthClient(
            organization_id=org_id,
            provider=provider,
            client_id=client_id,
            client_secret_encrypted=encrypt(client_secret),
            created_by_user_id=actor_id,
            tenant_id=(tenant_id or None),
            issuer=(issuer or None),
        )
        db.add(row)
    else:
        row.client_id = client_id
        if client_secret:
            row.client_secret_encrypted = encrypt(client_secret)
        if tenant_id is not None:
            row.tenant_id = tenant_id or None
        if issuer is not None:
            row.issuer = issuer or None
    db.flush()
    return row


def endpoints_for(spec: OAuthSpec, client: OauthClient) -> tuple[str, str]:
    """The authorize and token URLs to use for one connection.

    **Microsoft's endpoints depend on which kind of app registration was made**, and
    the spec cannot know: `/common/` serves a multi-tenant app and returns an error
    for a single-tenant one, which is the more common kind and the one an admin
    following the setup steps here will produce. So a spec may hold `{tenant}` and
    it is filled from the connection.

    **Salesforce varies for a different reason and lands in the same place.** Its
    login host says *which Salesforce* — production, a sandbox, or a company's own
    My Domain — and that is a per-deployment fact exactly like a Microsoft tenant.
    The fallback comes from the spec rather than the engine, because `common` is
    Microsoft's word and means nothing to Salesforce.

    Left exactly as written for every provider whose URLs do not vary.
    """
    tenant = (client.tenant_id or "").strip() or spec.default_tenant
    return (
        spec.authorize_url.format(tenant=tenant),
        spec.token_url.format(tenant=tenant),
    )


def authorization_url(
    spec: OAuthSpec, client: OauthClient, *, redirect_uri: str, flow: oidc.FlowState
) -> str:
    """Where to send the browser.

    PKCE even though this is a confidential client with a secret. It costs one
    hash and removes a whole class of interception, and the code that generates
    the challenge is already written and tested for sign-in.
    """
    params = {
        "response_type": "code",
        "client_id": client.client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(spec.scopes),
        "state": flow.state,
        "code_challenge": oidc._code_challenge(flow.code_verifier),
        "code_challenge_method": "S256",
    }
    params.update(dict(spec.extra_authorize_params))
    authorize, _ = endpoints_for(spec, client)
    return f"{authorize}?{urlencode(params)}"


def exchange(
    spec: OAuthSpec,
    client: OauthClient,
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    """Turn the code into tokens. Reuses the sign-in flow's exchange verbatim."""
    _, token_url = endpoints_for(spec, client)
    return oidc.exchange_code(
        {"token_endpoint": token_url},
        code=code,
        redirect_uri=redirect_uri,
        client_id=client.client_id,
        client_secret=secret_of(client),
        code_verifier=code_verifier,
    )


def expires_from(response: dict[str, Any], *, now: datetime | None = None) -> datetime:
    """When the access token in this response stops working.

    Stored in the clear on `connector_credential` so the scheduler can ask "does
    this need renewing?" without decrypting every credential on every pass.
    """
    now = now or datetime.now(UTC)
    seconds = response.get("expires_in")
    try:
        lifetime = timedelta(seconds=int(seconds))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        lifetime = DEFAULT_LIFETIME
    return now + lifetime


def save_tokens(
    db: DbSession,
    source: DataSource,
    client: OauthClient,
    response: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Store what the provider returned, keeping what it did not send.

    **The merge that matters.** A refresh response is usually just an access
    token; replacing would discard the refresh token and the source would work
    for an hour and then stop for good. Merging keeps it, and a provider that
    rotates its refresh token still overwrites the old one because the new one is
    in the response.
    """
    now = now or datetime.now(UTC)
    merged = {**credential_store.get(db, source), **response}
    credential_store.put(db, source, merged, expires_at=expires_from(response, now=now))
    client.last_used_at = now
    db.flush()
    return merged


def needs_refresh(
    expires_at: datetime | None, *, now: datetime | None = None
) -> bool:
    """Whether the stored token is close enough to expiry to renew.

    No expiry recorded means "we do not know", and the honest answer there is to
    leave it alone: a provider that issues non-expiring tokens would otherwise be
    refreshed on every single sync.
    """
    if expires_at is None:
        return False
    now = now or datetime.now(UTC)
    return expires_at - REFRESH_MARGIN <= now


def refresh(
    db: DbSession,
    source: DataSource,
    spec: OAuthSpec,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Renew the access token using the stored refresh token.

    Raises rather than returning quietly on failure: a revoked or expired refresh
    token means the source genuinely cannot sync, and the sync's own error
    handling turns that into a visible failure with this message on it. Papering
    over it would produce a source that reports success and imports nothing.
    """
    secrets = credential_store.get(db, source)
    token = str(secrets.get("refresh_token") or "")
    if not token:
        raise OAuthProblem(
            "This source has no refresh token, so its access cannot be renewed. "
            "Reconnect it to sign in again."
        )

    client = client_for(db, source.organization_id, spec.provider)
    # The same endpoint the token was obtained from. A refresh sent to `/common/`
    # for a single-tenant registration fails, and it fails hours later on a
    # scheduled sync rather than in front of whoever set it up.
    _, token_url = endpoints_for(spec, client)
    response = httpx.post(
        token_url,
        data={
            "grant_type": "refresh_token",
            "refresh_token": token,
            "client_id": client.client_id,
            "client_secret": secret_of(client),
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        # The status only. A provider's error body can echo back what was sent,
        # and what was sent includes the client secret.
        raise OAuthProblem(
            f"{spec.provider_name} refused to renew this source's access "
            f"(HTTP {response.status_code}). Reconnect it to sign in again."
        )

    return save_tokens(db, source, client, response.json(), now=now)


def ensure_fresh(
    db: DbSession,
    source: DataSource,
    spec: OAuthSpec | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The credentials to use right now, renewed first if they are about to lapse.

    Every path that talks to a provider goes through here — sync, test, discover —
    so "is the token still good?" is asked in one place. A connector that needs no
    OAuth passes `spec=None` and gets its stored secrets back untouched, which is
    what keeps the callers free of `if connector is oauth` branching.

    **A spreadsheet token is not its source own**, and the branch lives here
    for the same reason the rest of the function does: there are four call
    sites, and a token rule applied at three of them is a bug that only shows
    up on the fourth. See `app/excel_account.py` and `app/sheets_account.py` —
    one account is signed in for the whole deployment and every spreadsheet
    reads as it, so a per-source credential would be a second, staler answer
    to a question already settled.

    The source's own credentials are still honoured when no account is signed in,
    which is what keeps a workbook connected before this existed working after it.
    """
    if source.connector in SHARED_CREDENTIAL_CONNECTORS:
        shared = _shared_token(db, source)
        if shared is not None:
            return shared

    # A warehouse credential is not a token — it is a username and a key, and it
    # never expires or refreshes. Returned straight through rather than dressed
    # up as one.
    warehouse = WAREHOUSE_CONNECTORS.get(source.connector)
    if warehouse is not None:
        from app import warehouse_account

        if warehouse_account.is_connected(db, source.organization_id, warehouse):
            return warehouse_account.credentials_for(
                db, source.organization_id, warehouse
            )

    secrets = credential_store.get(db, source)
    if spec is None:
        return secrets

    if needs_refresh(credential_store.expires_at(db, source), now=now):
        logger.info("Refreshing %s access for source %s", spec.provider, source.id)
        return refresh(db, source, spec, now=now)
    return secrets


#: Connectors whose credential is held once per organization, not per source.
#:
#: Maps the connector to the provider registration its account hangs off. A
#: spreadsheet is the shape that wants this: connecting four of them should not
#: mean four sign-ins and four credentials expiring independently. See
#: `app/excel_account.py` and `app/sheets_account.py`.
#:
#: **A table rather than a check at each call site**, because three things have to
#: agree about it: the token substituted below, whether a source counts as having
#: credentials at all, and what the setup screen offers. When the first two
#: disagreed, every working Excel source reported "Setup unfinished" and offered
#: to resume a wizard it had already completed.
SHARED_CREDENTIAL_CONNECTORS = {
    "microsoft_excel": "microsoft",
    "google_sheets": "google",
}


def _connection_for(db: DbSession, source: DataSource) -> OauthClient | None:
    provider = SHARED_CREDENTIAL_CONNECTORS.get(source.connector)
    if provider is None:
        return None
    return db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == source.organization_id,
            OauthClient.provider == provider,
        )
    )


def _account_module(connector: str):
    """The module holding this connector organization-wide account.

    Imported inside rather than at module scope: both of them import `oauth` for
    `secret_of`, and naming them at the top would close the cycle.
    """
    if connector == "microsoft_excel":
        from app import excel_account

        return excel_account
    if connector == "google_sheets":
        from app import sheets_account

        return sheets_account
    return None


#: Connectors whose credential lives on a `warehouse_connection` rather than an
#: OAuth registration. Same idea as the table above, different table.
WAREHOUSE_CONNECTORS = {"snowflake": "snowflake"}


def config_for(db: DbSession, source: DataSource) -> dict:
    """The source config a connector should be handed.

    Its own stored config, plus whatever the shared connection owns. For a
    warehouse that is the account, warehouse, role and database — answered once
    when it was connected, and needed by every call.

    **Here rather than in the connector**, because `test_connection` is handed no
    database session and so cannot look anything up; and here rather than at the
    four call sites, for the same reason `ensure_fresh` is one function: a rule
    applied at three of four places is a bug that only shows on the fourth.
    """
    config = dict(source.config or {})

    warehouse = WAREHOUSE_CONNECTORS.get(source.connector)
    if warehouse is not None:
        from app import warehouse_account

        row = warehouse_account.get(db, source.organization_id, warehouse)
        if row is not None:
            # The connection wins over anything stale in the source row: it is
            # the one place these are edited, so a source holding an old
            # warehouse name must not quietly keep using it.
            config.update(warehouse_account.config_defaults(row))

    return config


def has_shared_credential(db: DbSession, source: DataSource) -> bool:
    """Whether this source authenticates with an organization-wide account.

    Read by the status endpoint so `credentials_set` keeps meaning "this source
    can authenticate" rather than "this source stores a secret". Those were the
    same question until the Excel account moved up a level, and the health check
    was left asserting the old one.
    """
    warehouse = WAREHOUSE_CONNECTORS.get(source.connector)
    if warehouse is not None:
        from app import warehouse_account

        return warehouse_account.is_connected(db, source.organization_id, warehouse)

    account = _account_module(source.connector)
    if account is None:
        return False
    return account.is_connected(_connection_for(db, source))


def _shared_token(db: DbSession, source: DataSource) -> dict[str, Any] | None:
    """The organization-wide account access token, or `None` to fall back.

    `None` for every reason that is not "it worked": no registration, nobody
    signed in, or a refusal from the provider. A refusal deliberately falls
    through to whatever the source itself holds rather than raising — if that
    still works the sync should not fail, and if it does not, the error the
    connector raises names the spreadsheet, which is what somebody can act on.
    """
    account = _account_module(source.connector)
    if account is None:
        return None

    connection = _connection_for(db, source)
    if not account.is_connected(connection):
        return None
    assert connection is not None
    try:
        return {"access_token": account.access_token(db, connection)}
    except Exception:  # noqa: BLE001 — fall back to whatever the source holds
        logger.warning(
            "Shared %s account could not be renewed; falling back to source %s",
            source.connector,
            source.id,
        )
        return None
