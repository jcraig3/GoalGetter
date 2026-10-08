"""The account a connection acts as, in delegated mode.

**One of two modes, not the design.** See `oauth_client.directory_auth_mode`. In
application mode nothing here is used: the sync and outgoing mail act as the
software itself and there is no account at all. This is the other option, and it
exists for one reason — a Cloud Application Administrator can consent to every
delegated Microsoft Graph permission and to none of its app roles, so the
application mode needs somebody more senior to press consent once. Delegated
needs nobody.

What it costs is an account. The sync acts as one person, so it stops if that
account is disabled, has its password reset, or is caught by a Conditional Access
policy on non-interactive refresh. Connect a service account, not a person — the
panel says so in as many words.

`offline_access` is what makes it run unattended: the refresh token outlives the
session, and using it daily keeps it alive. Same mechanism every data source here
already runs on — see `app/oauth.py`.
"""

from __future__ import annotations

import base64
import json
import logging
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session as DbSession

from app.crypto import decrypt, encrypt
from app.models import OauthClient
from app.oauth import secret_of

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 15.0


class NotConnected(Exception):
    """No account has been signed in yet, phrased for the admin who has to."""


class Refused(Exception):
    """The provider would not renew, phrased for somebody who can act on it."""


def _tenant_of(connection: OauthClient) -> str:
    """The connection's own tenant, never `/common/`.

    A single-tenant registration is what the setup here produces, and `/common/`
    returns an error for one.
    """
    return (connection.tenant_id or "").strip() or "organizations"


def authorize_url(
    connection: OauthClient,
    *,
    redirect_uri: str,
    scopes: list[str],
    state: str,
    challenge: str,
) -> str:
    """Where to send the admin to choose the account.

    `prompt=select_account` on purpose. The overwhelmingly likely mistake is
    connecting as yourself when you meant a service account, and a silent
    single-sign-on through the current session is what makes that invisible — the
    page would say "connected" as the wrong person.
    """
    params = {
        "client_id": connection.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return (
        f"https://login.microsoftonline.com/{_tenant_of(connection)}"
        f"/oauth2/v2.0/authorize?{urlencode(params)}"
    )


def exchange(
    connection: OauthClient, *, code: str, redirect_uri: str, verifier: str
) -> tuple[str, str]:
    """The authorization code, for a refresh token and the account's address.

    Both, because the address is the only way a screen can name *whose* account
    this is — and "connected" without saying to what is the state this flow exists
    to avoid.
    """
    response = httpx.post(
        f"https://login.microsoftonline.com/{_tenant_of(connection)}/oauth2/v2.0/token",
        data={
            "grant_type": "authorization_code",
            "client_id": connection.client_id,
            "client_secret": secret_of(connection),
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        raise Refused(_describe(response))

    body = response.json()
    refresh = str(body.get("refresh_token") or "")
    if not refresh:
        # Almost always a missing `offline_access`. Its own message, because
        # without one this appears to work and stops within the hour.
        raise Refused(
            "Microsoft returned no refresh token, so this could not keep working "
            "unattended. The application is missing the offline_access permission."
        )
    return refresh, _who(str(body.get("id_token") or ""))


def store(
    db: DbSession, connection: OauthClient, *, refresh_token: str, connected_as: str
) -> None:
    connection.tenant_refresh_token_encrypted = encrypt(refresh_token)
    connection.tenant_connected_as = connected_as
    db.flush()


def forget(db: DbSession, connection: OauthClient) -> None:
    """Drop the account, and switch off what cannot run without it.

    In delegated mode that is both features. **Application mode is untouched by
    this** — it has no account to drop, so a deployment in that mode never reaches
    here and its switches are not this function's business.
    """
    connection.tenant_refresh_token_encrypted = None
    connection.tenant_connected_as = ""
    if connection.directory_auth_mode == "delegated":
        connection.directory_sync_enabled = False
        connection.mail_enabled = False
    db.flush()


def is_connected(connection: OauthClient | None) -> bool:
    return bool(connection and connection.tenant_refresh_token_encrypted)


def needed_by(connection: OauthClient | None) -> bool:
    """Whether this connection's mode requires an account at all."""
    return bool(connection) and connection.directory_auth_mode == "delegated"


def access_token(db: DbSession, connection: OauthClient, *, scopes: list[str]) -> str:
    """A fresh access token for the connected account.

    **A rotated refresh token is written back**, and that is the one thing here
    that must not be got wrong. Microsoft usually returns the same one, and
    *usually* is the problem: the run that receives a new one and discards it
    succeeds, and every run after it fails with an invalid grant — days later,
    with nothing in the log from the day it broke.
    """
    if not connection.tenant_refresh_token_encrypted:
        raise NotConnected(
            "No Microsoft account is signed in for this connection yet. Sign one "
            "in on the Integrations page — it is the account this acts as."
        )

    response = httpx.post(
        f"https://login.microsoftonline.com/{_tenant_of(connection)}/oauth2/v2.0/token",
        data={
            "grant_type": "refresh_token",
            "client_id": connection.client_id,
            "client_secret": secret_of(connection),
            "refresh_token": decrypt(connection.tenant_refresh_token_encrypted),
            "scope": " ".join(scopes),
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        raise Refused(
            "Microsoft would not renew access for "
            f"{connection.tenant_connected_as or 'the connected account'}. "
            f"{_describe(response)} Sign it in again on the Integrations page."
        )

    body = response.json()
    token = str(body.get("access_token") or "")
    if not token:
        raise Refused("Microsoft returned no access token.")

    rotated = str(body.get("refresh_token") or "")
    if rotated:
        connection.tenant_refresh_token_encrypted = encrypt(rotated)
        db.flush()

    return token


def _describe(response: httpx.Response) -> str:
    """Microsoft's own words, which are specific enough to act on.

    `AADSTS50173` is "the password changed, sign in again"; `AADSTS700082` is
    "this sat unused too long". No wording of ours separates those, and they need
    different responses.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    detail = body.get("error_description") or body.get("error") or ""
    return str(detail)[:400]


def _who(id_token: str) -> str:
    """Which account signed in, from the token issued to us.

    The exception Microsoft documents: an id token is issued *to* this client, for
    this client. An empty answer is not fatal — the connection works, the screen
    just cannot name it.
    """
    parts = id_token.split(".")
    if len(parts) != 3:
        return ""
    try:
        raw = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        claims = json.loads(raw)
    except Exception:  # noqa: BLE001 — cosmetic, never worth failing a connect
        return ""
    if not isinstance(claims, dict):
        return ""
    return str(
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("upn")
        or ""
    )
