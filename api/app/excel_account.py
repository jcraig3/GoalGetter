"""The Microsoft account GoalGetter reads workbooks as.

**One sign-in for the whole deployment, not one per spreadsheet.** That is the
entire point of this module. Before it, every Excel source ran its own
authorization dance and stored its own refresh token, so connecting three
workbooks meant signing in three times and produced three credentials that expired
independently — and when one of them died, the error named a source rather than
the account, so the fix was three clicks away from the message.

**A sign-in is not a design choice here.** `Files.Read.All` is on the registration
as a *delegated* permission (see `providers.MICROSOFT`), and a delegated permission
only ever appears in a token issued for a signed-in user. There is no app-only
token that carries it, so there is nothing to fall back to and nothing to be clever
about: somebody signs in once, and everything reads as them.

**Which is also the access boundary, and it is a good one.** GoalGetter can open
exactly the files that person can open — their OneDrive, and the SharePoint sites
they already have access to. Nothing is granted tenant-wide, nobody's private files
become readable, and revoking it is one *Sign out* rather than an admin unpicking
an app role.

**Read-only, and structurally so.** Every Graph call made with this token is a GET
(see `app/routers/excel.py` and `app/connectors/excel.py`), and the scope itself
grants no write — `Files.Read.All` cannot create, modify or delete a file even if
something here tried to.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.orm import Session as DbSession

from app.crypto import decrypt, encrypt
from app.models import OauthClient
from app.oauth import secret_of
from app.tenant_account import (
    HTTP_TIMEOUT,
    NotConnected,
    Refused,
    _describe,
    _tenant_of,
)

logger = logging.getLogger(__name__)

__all__ = [
    "NotConnected",
    "Refused",
    "SCOPES",
    "access_token",
    "connected_as",
    "forget",
    "is_connected",
    "store",
]

#: What the sign-in asks for.
#:
#: Deliberately the *minimum* that makes a workbook readable and keeps working:
#: one Graph scope, plus the three bare ones that are not Graph resources and must
#: not be prefixed as such.
#:
#: `offline_access` is the one nobody would guess at. Without it Microsoft issues
#: no refresh token and every source stops after an hour, with an authorization
#: error that says nothing about a missing permission.
SCOPES: list[str] = [
    "offline_access",
    "openid",
    "profile",
    "email",
    "https://graph.microsoft.com/Files.Read.All",
]


def store(
    db: DbSession, connection: OauthClient, *, refresh_token: str, connected_as: str
) -> None:
    connection.files_refresh_token_encrypted = encrypt(refresh_token)
    connection.files_connected_as = connected_as
    db.flush()


def forget(db: DbSession, connection: OauthClient) -> None:
    """Drop the account.

    **Sources are left alone on purpose**, matching what removing a provider
    registration does. Their configuration — which workbook, which worksheet, how
    the columns map — is still correct and still worth keeping; what has gone is
    the ability to read, and the next sync says exactly that. Deleting them here
    would mean re-doing the mapping to recover from a mis-click.
    """
    connection.files_refresh_token_encrypted = None
    connection.files_connected_as = ""
    db.flush()


def is_connected(connection: OauthClient | None) -> bool:
    return bool(connection and connection.files_refresh_token_encrypted)


def connected_as(connection: OauthClient | None) -> str:
    return (connection.files_connected_as or "") if connection else ""


def access_token(db: DbSession, connection: OauthClient) -> str:
    """A fresh access token for the connected account.

    **A rotated refresh token is written back**, which is the one thing here that
    must not be got wrong. Microsoft usually returns the same one, and *usually* is
    the problem: the run that receives a new one and discards it succeeds, and
    every run after it fails with an invalid grant — days later, with nothing in
    the log from the day it actually broke.
    """
    if not connection.files_refresh_token_encrypted:
        raise NotConnected(
            "No Microsoft account is signed in for spreadsheets yet. Sign one in "
            "under Integrations → Microsoft 365 → Excel spreadsheets."
        )

    response = httpx.post(
        f"https://login.microsoftonline.com/{_tenant_of(connection)}/oauth2/v2.0/token",
        data={
            "grant_type": "refresh_token",
            "client_id": connection.client_id,
            "client_secret": secret_of(connection),
            "refresh_token": decrypt(connection.files_refresh_token_encrypted),
            "scope": " ".join(SCOPES),
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        raise Refused(
            "Microsoft would not renew access for "
            f"{connection.files_connected_as or 'the connected account'}. "
            f"{_describe(response)} Sign it in again under Integrations → "
            "Microsoft 365 → Excel spreadsheets."
        )

    body = response.json()
    token = str(body.get("access_token") or "")
    if not token:
        raise Refused("Microsoft returned no access token.")

    rotated = str(body.get("refresh_token") or "")
    if rotated:
        connection.files_refresh_token_encrypted = encrypt(rotated)
        db.flush()

    return token
