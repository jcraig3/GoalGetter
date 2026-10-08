"""The Google account GoalGetter reads spreadsheets as.

**One sign-in for the whole deployment, not one per spreadsheet** — the same move
`app/excel_account.py` makes, for the same reason. Before it, every Sheets source
ran its own authorization dance and stored its own credential, so connecting three
spreadsheets meant three sign-ins and three tokens expiring independently; when
one died the error named a source rather than the account.

**Two honest ways to be a robot, and the connector already supported both.**

A *signed-in account* is two clicks and right for a Workspace company, whose
consent screen is Internal — no verification review, no seven-day token expiry.
Its one weakness is that it belongs to a person: when they leave, the sync stops.

A *service account* is a key plus sharing the spreadsheet with its address, the
ordinary Share button exactly as with a colleague. The access belongs to the
organization rather than to anybody, and it sidesteps Google's review process
that a plain Gmail account runs into.

**Neither is a mode anybody chooses.** Whichever credential is present is the one
used — a stored key means service account, a stored token means the signed-in
one. That is what `SheetsConnector._token` has always done per source, lifted up a
level unchanged. One less question, and no way for a setting and a credential to
disagree.

**Read-only, and structurally so.** Both scopes are `readonly` by name, every
Google call made with this token is a GET, and nothing here can create, modify or
delete a spreadsheet even if something tried.
"""

from __future__ import annotations

import json
import logging

import httpx
from sqlalchemy.orm import Session as DbSession

from app.crypto import decrypt, encrypt
from app.models import OauthClient
from app.oauth import secret_of
from app.tenant_account import NotConnected, Refused, _describe

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 15.0
TOKEN_URL = "https://oauth2.googleapis.com/token"

__all__ = [
    "NotConnected",
    "Refused",
    "SCOPES",
    "access_token",
    "connected_as",
    "forget",
    "is_connected",
    "store",
    "store_service_account",
    "uses_service_account",
]

#: What the sign-in asks for.
#:
#: `spreadsheets.readonly` reads the cells and is the whole of what syncing needs.
#:
#: **`drive.metadata.readonly` is what makes a picker possible at all**, and it is
#: new. The Sheets API can read a spreadsheet somebody names but cannot list the
#: ones an account has — only Drive can, and without it "which spreadsheet?" stays
#: a box to paste a URL into. The narrower of the two Drive scopes deliberately:
#: metadata lists names and ids and cannot read a single cell of anything, so the
#: grant says exactly what the picker does.
#:
#: Adding it means the next sign-in asks for one more thing. On an Internal
#: Workspace consent screen that is a click; on an External one it is a scope
#: Google treats as sensitive, which is one more reason the service account is the
#: better path for a plain Gmail account.
SCOPES: list[str] = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]


def store(
    db: DbSession, connection: OauthClient, *, refresh_token: str, connected_as: str
) -> None:
    """Keep a signed-in account, and drop any service key it replaces.

    Both cleared together because `access_token` picks whichever is present: two
    stored at once would make "which one is this reading as?" a question the
    screen could not answer from the data.
    """
    connection.sheets_refresh_token_encrypted = encrypt(refresh_token)
    connection.sheets_service_account_encrypted = None
    connection.sheets_connected_as = connected_as
    db.flush()


def store_service_account(db: DbSession, connection: OauthClient, *, key: str) -> str:
    """Keep a service-account key, and return the address to share sheets with.

    **The address is the point of the return value.** A key on its own reads
    nothing: Google grants a service account access to exactly the files somebody
    has shared with it, so the next step is always "share the spreadsheet with
    this address" and the screen cannot say it without knowing the address.
    """
    try:
        parsed = json.loads(key)
        email = str(parsed.get("client_email") or "")
    except ValueError:
        raise Refused(
            "That does not look like a service account key. Paste the whole JSON "
            "file downloaded when the account was created."
        ) from None
    if not email:
        raise Refused(
            "That key has no client_email in it, so there is no address to share "
            "spreadsheets with. Check it is a service account key rather than an "
            "OAuth client secret."
        )

    connection.sheets_service_account_encrypted = encrypt(key)
    connection.sheets_refresh_token_encrypted = None
    connection.sheets_connected_as = email
    db.flush()
    return email


def forget(db: DbSession, connection: OauthClient) -> None:
    """Drop whichever credential is held.

    **Sources are left alone on purpose**, matching `excel_account.forget`. Their
    configuration — which spreadsheet, which tab, how the columns map — is still
    correct and still worth keeping; what has gone is the ability to read, and the
    next sync says exactly that.
    """
    connection.sheets_refresh_token_encrypted = None
    connection.sheets_service_account_encrypted = None
    connection.sheets_connected_as = ""
    db.flush()


def is_connected(connection: OauthClient | None) -> bool:
    return bool(
        connection
        and (
            connection.sheets_refresh_token_encrypted
            or connection.sheets_service_account_encrypted
        )
    )


def uses_service_account(connection: OauthClient | None) -> bool:
    return bool(connection and connection.sheets_service_account_encrypted)


def connected_as(connection: OauthClient | None) -> str:
    return (connection.sheets_connected_as or "") if connection else ""


def access_token(db: DbSession, connection: OauthClient) -> str:
    """A bearer token for whichever credential is held.

    Inferred rather than configured, exactly as the per-source version was: a
    stored key means service account, a stored token means the signed-in account.
    """
    if connection.sheets_service_account_encrypted:
        # Minted per use rather than cached — see `sheets._service_token`, which
        # this borrows rather than reimplements so the assertion is built once.
        from app.connectors.sheets import _service_token

        try:
            return _service_token(decrypt(connection.sheets_service_account_encrypted))
        except Exception as problem:  # noqa: BLE001 — shown to an admin
            raise Refused(
                "Google would not accept that service account key. "
                f"{type(problem).__name__}: {problem}"[:400]
            ) from None

    if not connection.sheets_refresh_token_encrypted:
        raise NotConnected(
            "No Google account is signed in for spreadsheets yet. Sign one in "
            "under Integrations → Google → Google Sheets, or paste a service "
            "account key there."
        )

    response = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": connection.client_id,
            "client_secret": secret_of(connection),
            "refresh_token": decrypt(connection.sheets_refresh_token_encrypted),
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        raise Refused(
            "Google would not renew access for "
            f"{connection.sheets_connected_as or 'the connected account'}. "
            f"{_describe(response)} Sign it in again under Integrations → Google."
        )

    body = response.json()
    token = str(body.get("access_token") or "")
    if not token:
        raise Refused("Google returned no access token.")

    # **A rotated refresh token is written back.** Google usually returns none on
    # a refresh, and *usually* is the problem: the run that receives a new one and
    # discards it succeeds, and every run after it fails with an invalid grant.
    rotated = str(body.get("refresh_token") or "")
    if rotated:
        connection.sheets_refresh_token_encrypted = encrypt(rotated)
        db.flush()

    return token
