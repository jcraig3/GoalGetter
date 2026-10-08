"""Sending mail as a mailbox in the customer's own tenant.

**Nothing signs in for this**, which is the whole point: the application
registration and its admin consent are the entire setup, so every Microsoft
feature works the moment that is done. Same client credentials grant the directory
sync uses, and the same reasoning — an account would have added an expiry date and
somebody to offboard.

**The cost is real and is not hidden.** `Mail.Send` as an application permission
lets this send as *any* mailbox in the tenant. There is no narrower application
permission; the narrower one is delegated and needs an account. So the narrowing
happens in Exchange, where it belongs: an **Application Access Policy** — or RBAC
for Applications, its replacement — scopes the app to one mailbox, and the panel
generates the command. Until that is applied the permission is as broad as it
sounds.

**Why not SMTP.** Microsoft disables SMTP AUTH by default now, so "point it at
smtp.office365.com" has stopped working for a lot of tenants. SMTP stays as the
path for everyone else, and as the fallback when a Graph send fails.

**Reports rather than raises**, like `app/mail.py`: the caller is part-way through
creating an invitation, and the link it produces has to work whatever mail does.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import tenant_account
from app.crypto import decrypt
from app.models import OauthClient

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"

#: Somebody is usually waiting on the request that triggered this.
HTTP_TIMEOUT = 15.0

#: `.default` means "every application permission already granted", which is what
#: admin consent decided — the client credentials grant accepts nothing else.
SCOPE = "https://graph.microsoft.com/.default"


@dataclass(frozen=True)
class Sent:
    """Mirrors `mail.Sent`, so `mail.send` can return either without caring."""

    ok: bool
    detail: str
    attempted: bool = True


def configured(db: DbSession, organization_id: int) -> OauthClient | None:
    """The connection to send through, or None when nothing is set up for it.

    Three things have to be true, and they are separate decisions: an application
    is registered, a mailbox is nominated, and somebody switched sending on. A
    connection existing says nothing about whether a company wants its invitations
    going out through Microsoft.

    **A nominated mailbox is required, not defaulted.** An application has no
    mailbox of its own, so there is nothing sensible to fall back to — and guessing
    would mean a first invitation failing on an address nobody chose.
    """
    connection = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == organization_id,
            OauthClient.mail_enabled.is_(True),
        )
    )
    # A mailbox to send as. Nominated in application mode, where the application
    # has none of its own; the signed-in account in delegated mode, where it is
    # the only address possible.
    if connection is None or not sender_for(connection):
        return None
    return connection


def sender_for(connection: OauthClient) -> str:
    """Which mailbox a message goes out as.

    **In delegated mode it is the signed-in account, and nothing else is
    possible.** Plain `Mail.Send` delegated sends as the account that signed in;
    sending as another mailbox would need `Mail.Send.Shared` plus Send As rights
    in Exchange. So a nominated address is ignored rather than attempted — and
    that limitation is the same thing that makes delegated mode the safer one for
    mail, since it cannot send as anybody else either.
    """
    if connection.directory_auth_mode == "delegated":
        return connection.tenant_connected_as
    return (connection.mail_from or "").strip()


def token_for(db: DbSession, connection: OauthClient) -> str:
    """A token to send with, however this connection signs in.

    Reports through `RuntimeError` rather than raising a domain error, because
    every caller here has to turn a failure into a `Sent` — mail is an
    enhancement and must never stop an invitation being created.
    """
    if connection.directory_auth_mode == "delegated":
        try:
            return tenant_account.access_token(
                db, connection, scopes=["https://graph.microsoft.com/Mail.Send"]
            )
        except (tenant_account.NotConnected, tenant_account.Refused) as problem:
            raise RuntimeError(str(problem)) from None

    response = httpx.post(
        f"https://login.microsoftonline.com/{(connection.tenant_id or '').strip()}"
        "/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": connection.client_id,
            "client_secret": decrypt(connection.client_secret_encrypted),
            "scope": SCOPE,
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        try:
            said = response.json().get("error_description") or ""
        except ValueError:
            said = ""
        raise RuntimeError(f"Microsoft refused the credential. {str(said)[:300]}")
    token = str(response.json().get("access_token") or "")
    if not token:
        raise RuntimeError("Microsoft returned no access token.")
    return token


def send(
    db: DbSession,
    connection: OauthClient,
    *,
    to: str,
    subject: str,
    body: str,
) -> Sent:
    """One message, through Graph, as the nominated mailbox.

    Plain text rather than HTML. Every message this product sends is a sentence
    and a link, an HTML version would be a second thing to keep in step, and a
    plain-text invitation renders in everything.
    """
    sender = sender_for(connection)
    if not sender:
        return Sent(
            ok=False,
            attempted=False,
            detail=(
                "No mailbox is set to send from. Name one under Integrations → "
                "Microsoft 365 → Email."
            ),
        )

    try:
        token = token_for(db, connection)
    except (RuntimeError, httpx.RequestError) as problem:
        return Sent(ok=False, detail=str(problem))

    try:
        response = httpx.post(
            # The mailbox is in the path. With an application permission Exchange
            # allows any of them unless an Application Access Policy says
            # otherwise — which is exactly why the panel pushes that policy.
            f"{GRAPH}/users/{sender}/sendMail",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to}}],
                },
                # Nothing reads this mailbox, so a copy in Sent Items is a folder
                # nobody empties. The run history is where a send is recorded.
                "saveToSentItems": False,
            },
            timeout=HTTP_TIMEOUT,
        )
    except httpx.RequestError as problem:
        logger.warning("mail_graph: could not reach Graph", exc_info=problem)
        return Sent(ok=False, detail=f"Could not reach Microsoft ({type(problem).__name__}).")

    # 202 Accepted is the success case; sendMail returns no body.
    if response.status_code in (200, 202):
        return Sent(ok=True, detail=f"Sent to {to} as {sender}.")

    if response.status_code == 403:
        # The predictable failure once the app is scoped, and worth its own
        # message: Graph's own "ErrorAccessDenied" names neither the mailbox nor
        # the policy that is refusing it.
        return Sent(
            ok=False,
            detail=(
                f"Microsoft refused to send as {sender}. Either the mailbox does "
                "not exist, or an Application Access Policy is scoping this "
                "application to a different one."
            ),
        )

    return Sent(ok=False, detail=f"Microsoft returned HTTP {response.status_code}.")
