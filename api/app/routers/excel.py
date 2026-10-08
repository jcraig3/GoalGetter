"""Browsing somebody's spreadsheets, so nobody has to paste a link.

**Why this exists at all.** Connecting a workbook used to mean opening OneDrive,
finding the file, *Share → Copy link*, coming back, pasting it, and then typing the
worksheet name from memory. Every one of those is a step where a person can be
right and the software still fails: a link to the folder instead of the file, a
link with a `?web=1` on the end, a tab renamed last week. The information was
always available over the same API we were already using — we were asking a human
to be the lookup.

So: one sign-in, then pick the file from a list and the worksheet from a dropdown.

**Everything here is a GET.** Not a convention — a property. The account's token
carries `Files.Read.All` and nothing else, a scope that cannot create, modify or
delete a file. There is no code path in this module that writes to Microsoft, and
the permission would refuse one if there were.
"""

from __future__ import annotations

import json
import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit, excel_account, oidc, providers, public_url
from app.connectors.excel import share_token
from app.connectors.rest import RestProblem, request_json
from app.crypto import decrypt, encrypt
from app.db import get_db
from app.models import DataSource, OauthClient, UserAccount
from app.oidc import new_flow_state
from app.sessions import require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/excel", tags=["excel"])

GRAPH = "https://graph.microsoft.com/v1.0"
HTTP_TIMEOUT = 20.0

#: How many files one browse returns. A picker is for choosing, not for reading a
#: whole drive — anybody with more than this many workbooks searches instead.
MAX_FILES = 50

#: Set at the data callback's path, so this reuses the redirect URI the
#: registration already has. **That is the point**: a new redirect path would mean
#: editing the app registration, and the whole premise of this work is that the
#: registration is already correct and must not be touched.
ACCOUNT_COOKIE = "gg_connect_flow"
ACCOUNT_PATH = providers.DATA_REDIRECT_PATH
ACCOUNT_TTL_SECONDS = 600


def _redirect_uri(db: DbSession) -> str:
    return f"{public_url.get(db)}{providers.DATA_REDIRECT_PATH}"


def _connection(db: DbSession, org_id: int) -> OauthClient | None:
    return db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == org_id, OauthClient.provider == "microsoft"
        )
    )


def _registered(db: DbSession, org_id: int) -> OauthClient:
    """The connection, or a refusal naming the step that is missing."""
    connection = _connection(db, org_id)
    if connection is None or not connection.client_secret_encrypted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Connect Microsoft 365 on the Integrations page first — reading "
                "spreadsheets uses the same application registration."
            ),
        )
    return connection


def _token(db: DbSession, org_id: int) -> tuple[OauthClient, str]:
    connection = _registered(db, org_id)
    try:
        return connection, excel_account.access_token(db, connection)
    except excel_account.NotConnected as problem:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(problem)
        ) from None
    except excel_account.Refused as problem:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(problem)
        ) from None


# ── What is connected ────────────────────────────────────────────────────────


class Workbook(BaseModel):
    """One spreadsheet this deployment reads."""

    source_id: int
    name: str
    worksheet: str
    enabled: bool
    last_status: str | None = None

    #: Which file and tab, so the picker can grey out what is already connected.
    #:
    #: **Shown rather than refused.** The API rejects a duplicate either way, but
    #: a 409 at the end of a wizard is a wasted trip: the answer was knowable
    #: before the click, so the list says "already connected" on the row instead.
    drive_id: str = ""
    item_id: str = ""


class ExcelStatus(BaseModel):
    """Everything the Excel panel draws itself from."""

    #: Whether the provider is registered at all. False means every other field
    #: is moot and the panel says so rather than offering a sign-in that 409s.
    registered: bool
    connected: bool
    #: Whose files these are. Empty when nobody is signed in.
    connected_as: str
    #: The workbooks currently being read, so "what are we pulling from?" is
    #: answered on the panel rather than by going to look at the source list.
    workbooks: list[Workbook]


def _workbooks(db: DbSession, org_id: int) -> list[Workbook]:
    rows = db.scalars(
        select(DataSource)
        .where(
            DataSource.organization_id == org_id,
            DataSource.connector == "microsoft_excel",
            DataSource.archived_at.is_(None),
        )
        .order_by(DataSource.name)
    ).all()
    return [
        Workbook(
            source_id=row.id,
            name=row.name,
            worksheet=str((row.config or {}).get("worksheet") or ""),
            enabled=row.enabled,
            last_status=row.last_status,
            drive_id=str((row.config or {}).get("drive_id") or ""),
            item_id=str((row.config or {}).get("item_id") or ""),
        )
        for row in rows
    ]


@router.get("/status", response_model=ExcelStatus)
def excel_status(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ExcelStatus:
    connection = _connection(db, actor.organization_id)
    registered = bool(connection and connection.client_secret_encrypted)
    return ExcelStatus(
        registered=registered,
        connected=excel_account.is_connected(connection),
        connected_as=excel_account.connected_as(connection),
        workbooks=_workbooks(db, actor.organization_id) if registered else [],
    )


# ── Signing the account in ───────────────────────────────────────────────────


class AccountStart(BaseModel):
    url: str


@router.post("/account", response_model=AccountStart)
def start_account(
    response: Response,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> AccountStart:
    """Begin signing in the account whose files GoalGetter reads.

    Returns the URL rather than redirecting: the caller is `fetch` from a
    single-page app, and a 303 would be followed inside the XHR, so the consent
    screen would arrive as a JSON parse error.
    """
    connection = _registered(db, actor.organization_id)

    flow = new_flow_state()
    url = _authorize_url(
        connection,
        state=flow.state,
        challenge=oidc._code_challenge(flow.code_verifier),
        redirect_uri=_redirect_uri(db),
    )

    # Encrypted rather than signed, because it holds the PKCE verifier: anybody
    # who could read it and intercept the code could complete the exchange.
    #
    # `account` rather than `source_id` is what tells the shared callback which
    # flow this is — see `oauth_clients.callback`.
    response.set_cookie(
        ACCOUNT_COOKIE,
        encrypt(
            json.dumps(
                {
                    "state": flow.state,
                    "verifier": flow.code_verifier,
                    "account": "excel",
                    "org": actor.organization_id,
                    "exp": time.time() + ACCOUNT_TTL_SECONDS,
                }
            )
        ),
        max_age=ACCOUNT_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=public_url.is_https(db),
        path=ACCOUNT_PATH,
    )
    return AccountStart(url=url)


def _authorize_url(
    connection: OauthClient, *, state: str, challenge: str, redirect_uri: str
) -> str:
    from urllib.parse import urlencode

    tenant = (connection.tenant_id or "").strip() or "organizations"
    query = urlencode(
        {
            "client_id": connection.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": " ".join(excel_account.SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Always ask, rather than silently reusing whoever is signed into the
            # browser. Choosing *whose* files these are is the entire decision
            # being made here, and a silent sign-in makes it for them.
            "prompt": "select_account",
        }
    )
    return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{query}"


def complete_account(
    db: DbSession, held: dict, *, code: str, verifier: str
) -> str | None:
    """Finish the sign-in. Returns a message on failure, `None` on success.

    Called by the shared data callback rather than routed here, because the
    redirect URI is the one already on the registration and there is exactly one
    of those.
    """
    connection = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == held.get("org"),
            OauthClient.provider == "microsoft",
        )
    )
    if connection is None:
        return "That connection no longer exists."

    from app.tenant_account import exchange

    try:
        refresh, who = exchange(
            connection, code=code, redirect_uri=_redirect_uri(db), verifier=verifier
        )
    except Exception as problem:  # noqa: BLE001 — shown to whoever pressed the button
        return str(problem)[:400]

    excel_account.store(db, connection, refresh_token=refresh, connected_as=who)
    db.commit()
    logger.info("Excel account connected as %s", who or "an unnamed account")
    return None


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def forget_account(
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> Response:
    """Stop reading files as that account.

    **The workbooks stay.** Their configuration is still correct and still worth
    keeping — what has gone is the ability to read them, and the next sync says
    exactly that. Removing them here would make a mis-click cost somebody their
    column mappings.
    """
    connection = _registered(db, actor.organization_id)
    who = excel_account.connected_as(connection)
    excel_account.forget(db, connection)
    audit.record(
        db,
        actor=actor,
        action="excel.account.forgotten",
        request=request,
        was=who,
        workbooks_kept=len(_workbooks(db, actor.organization_id)),
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Browsing ─────────────────────────────────────────────────────────────────


class FileHit(BaseModel):
    """One workbook somebody could choose."""

    drive_id: str
    item_id: str
    name: str
    #: Where it lives, in words — "My files", or the site or folder it is under.
    location: str = ""
    modified: str = ""
    #: The sharing link, kept so a source configured by the picker is still
    #: readable by the pasted-link path if it ever has to fall back to it.
    web_url: str = ""


def _hit(item: dict) -> FileHit | None:
    """One Graph driveItem as a choice, or `None` if it is not a workbook.

    Filtered by name rather than by mime type: Graph reports several types for
    `.xlsx` depending on where it came from, and the extension is what the person
    choosing is looking at anyway.
    """
    name = str(item.get("name") or "")
    if not name.lower().endswith((".xlsx", ".xlsm")):
        return None
    parent = item.get("parentReference") or {}
    drive_id = str(parent.get("driveId") or "")
    item_id = str(item.get("id") or "")
    if not drive_id or not item_id:
        return None
    path = str(parent.get("path") or "")
    # Graph's path is `/drive/root:/Folder/Sub`; the readable half is after the colon.
    folder = path.split(":", 1)[1].strip("/") if ":" in path else ""
    return FileHit(
        drive_id=drive_id,
        item_id=item_id,
        name=name,
        location=folder or "My files",
        modified=str(item.get("lastModifiedDateTime") or ""),
        web_url=str(item.get("webUrl") or ""),
    )


@router.get("/files", response_model=list[FileHit])
def browse(
    q: str = Query("", max_length=200),
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[FileHit]:
    """Workbooks the connected account can open.

    **Empty query means recent, not everything.** A drive listing would be a wall
    of folders to click through; what somebody connecting a spreadsheet almost
    always wants is one they touched this week. Typing switches to a search across
    everything they can reach, OneDrive and SharePoint alike.
    """
    _, token = _token(db, actor.organization_id)

    term = q.strip()
    if term:
        # `search(q=)` on the drive covers the account's own files and everything
        # shared with them. Quotes are escaped because the term goes inside a
        # single-quoted OData string.
        safe = term.replace("'", "''")
        url = f"{GRAPH}/me/drive/search(q='{safe}')"
    else:
        url = f"{GRAPH}/me/drive/recent"

    with httpx.Client(
        timeout=HTTP_TIMEOUT,
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=True,
    ) as client:
        try:
            body = request_json(client, url, {"$top": str(MAX_FILES * 4)}, "Microsoft")
        except RestProblem as problem:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(problem)
            ) from None

    found = body.get("value") if isinstance(body, dict) else None
    items = found if isinstance(found, list) else []
    hits = [hit for hit in (_hit(item) for item in items if isinstance(item, dict)) if hit]
    return hits[:MAX_FILES]


@router.get("/resolve", response_model=FileHit)
def resolve(
    url: str = Query(..., max_length=2000),
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> FileHit:
    """One sharing link, as a chosen workbook.

    **The path that reaches SharePoint.** Browsing runs on `/me/drive`, which is
    one person's OneDrive plus what has been shared *to* them; a workbook living
    in a site's document library — which is where a team's spreadsheets usually
    live — is not in either. A link is, and the link is the thing somebody already
    has in their clipboard.

    Resolving it here rather than storing the URL and resolving it on every read
    is the same trade the picker makes everywhere else: the ids are what Graph
    actually addresses a file by, so this is one request now instead of one
    request per sync, and it fails in front of the person who pasted it rather
    than at three in the morning.
    """
    _, token = _token(db, actor.organization_id)

    with httpx.Client(
        timeout=HTTP_TIMEOUT,
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=True,
    ) as client:
        try:
            item = request_json(
                client,
                f"{GRAPH}/shares/{share_token(url)}/driveItem",
                {"$select": "id,name,webUrl,lastModifiedDateTime,parentReference"},
                "Microsoft",
            )
        except RestProblem as problem:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(problem)
            ) from None

    hit = _hit(item) if isinstance(item, dict) else None
    if hit is None:
        # Two different mistakes, and the message names both because the link
        # looks identical either way once it is pasted.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "That link does not point at a workbook. Check it is a link to "
                "the .xlsx file itself rather than to the folder or site it sits "
                "in, and that the signed-in account can open it."
            ),
        )
    return hit


class Worksheet(BaseModel):
    name: str


@router.get("/worksheets", response_model=list[Worksheet])
def worksheets(
    drive_id: str = Query(..., max_length=300),
    item_id: str = Query(..., max_length=300),
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[Worksheet]:
    """The tabs in one workbook, so nobody types a name from memory.

    A typo here used to produce "that worksheet is empty", which is true and
    useless — the sheet was not empty, it did not exist.
    """
    _, token = _token(db, actor.organization_id)

    with httpx.Client(
        timeout=HTTP_TIMEOUT,
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=True,
    ) as client:
        try:
            body = request_json(
                client,
                f"{GRAPH}/drives/{drive_id}/items/{item_id}/workbook/worksheets",
                {"$select": "name"},
                "Microsoft",
            )
        except RestProblem as problem:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(problem)
            ) from None

    found = body.get("value") if isinstance(body, dict) else None
    sheets = found if isinstance(found, list) else []
    return [
        Worksheet(name=str(sheet.get("name") or ""))
        for sheet in sheets
        if isinstance(sheet, dict) and sheet.get("name")
    ]
