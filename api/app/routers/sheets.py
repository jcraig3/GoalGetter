"""Browsing somebody's Google spreadsheets, so nobody has to paste a URL.

The Sheets half of what `app/routers/excel.py` does for Excel, and deliberately
the same shape: one account for the deployment, then pick the file from a list and
the tab from a dropdown.

**Why a second Drive scope was unavoidable.** The Sheets API can read a
spreadsheet somebody names but cannot list the ones an account has — only Drive
can. Without `drive.metadata.readonly` the question "which spreadsheet?" stays a
box to paste a URL into. The narrower of the two Drive scopes on purpose: metadata
lists names and ids and cannot read a single cell of anything, so the grant says
exactly what the picker does and nothing more.

**Everything here is a GET.** Both scopes are `readonly` by name, and there is no
code path in this module that writes to Google.
"""

from __future__ import annotations

import json
import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import audit, oidc, providers, public_url, sheets_account
from app.connectors.rest import RestProblem, request_json
from app.connectors.sheets import spreadsheet_id_of
from app.crypto import encrypt
from app.db import get_db
from app.models import DataSource, OauthClient, UserAccount
from app.oidc import new_flow_state
from app.sessions import require_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/sheets", tags=["sheets"])

DRIVE = "https://www.googleapis.com/drive/v3"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
HTTP_TIMEOUT = 20.0

#: How many files one browse returns. A picker is for choosing, not for reading a
#: whole Drive — anybody with more than this many spreadsheets searches instead.
MAX_FILES = 50

#: Set at the data callback path, so this reuses a redirect URI the registration
#: already has rather than needing a new one added to it.
ACCOUNT_COOKIE = "gg_connect_flow"
ACCOUNT_PATH = providers.DATA_REDIRECT_PATH
ACCOUNT_TTL_SECONDS = 600


def _redirect_uri(db: DbSession) -> str:
    return f"{public_url.get(db)}{providers.DATA_REDIRECT_PATH}"


def _connection(db: DbSession, org_id: int) -> OauthClient | None:
    return db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == org_id, OauthClient.provider == "google"
        )
    )


def _registered(db: DbSession, org_id: int) -> OauthClient:
    connection = _connection(db, org_id)
    if connection is None or not connection.client_secret_encrypted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Connect Google on the Integrations page first — reading "
                "spreadsheets uses the same application registration."
            ),
        )
    return connection


def _token(db: DbSession, org_id: int) -> tuple[OauthClient, str]:
    connection = _registered(db, org_id)
    try:
        return connection, sheets_account.access_token(db, connection)
    except sheets_account.NotConnected as problem:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(problem)
        ) from None
    except sheets_account.Refused as problem:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(problem)
        ) from None


# ── What is connected ────────────────────────────────────────────────────────


class Spreadsheet(BaseModel):
    """One spreadsheet this deployment reads."""

    source_id: int
    name: str
    tab: str
    enabled: bool
    last_status: str | None = None
    #: Which file and tab, so the picker can say what is already connected.
    spreadsheet_id: str = ""


class SheetsStatus(BaseModel):
    """Everything the Google Sheets panel draws itself from."""

    registered: bool
    connected: bool
    connected_as: str
    #: Whether the credential is a service account rather than a person.
    #:
    #: Shown because it changes the next step: a service account reads nothing
    #: until the spreadsheet has been *shared* with its address, and that is not a
    #: thing anybody guesses.
    service_account: bool
    spreadsheets: list[Spreadsheet]


def _sheets(db: DbSession, org_id: int) -> list[Spreadsheet]:
    rows = db.scalars(
        select(DataSource)
        .where(
            DataSource.organization_id == org_id,
            DataSource.connector == "google_sheets",
            DataSource.archived_at.is_(None),
        )
        .order_by(DataSource.name)
    ).all()
    return [
        Spreadsheet(
            source_id=row.id,
            name=row.name,
            tab=str((row.config or {}).get("tab") or ""),
            enabled=row.enabled,
            last_status=row.last_status,
            spreadsheet_id=str((row.config or {}).get("spreadsheet_id") or ""),
        )
        for row in rows
    ]


@router.get("/status", response_model=SheetsStatus)
def sheets_status(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> SheetsStatus:
    connection = _connection(db, actor.organization_id)
    registered = bool(connection and connection.client_secret_encrypted)
    return SheetsStatus(
        registered=registered,
        connected=sheets_account.is_connected(connection),
        connected_as=sheets_account.connected_as(connection),
        service_account=sheets_account.uses_service_account(connection),
        spreadsheets=_sheets(db, actor.organization_id) if registered else [],
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
    """Begin signing in the account whose spreadsheets GoalGetter reads."""
    connection = _registered(db, actor.organization_id)

    flow = new_flow_state()
    url = _authorize_url(
        connection,
        state=flow.state,
        challenge=oidc._code_challenge(flow.code_verifier),
        redirect_uri=_redirect_uri(db),
    )

    response.set_cookie(
        ACCOUNT_COOKIE,
        encrypt(
            json.dumps(
                {
                    "state": flow.state,
                    "verifier": flow.code_verifier,
                    "account": "sheets",
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

    query = urlencode(
        {
            "client_id": connection.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(sheets_account.SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Both required, for different reasons. Without `access_type=offline`
            # Google issues no refresh token at all, so this works for an hour.
            # Without `prompt=consent` it issues none on a *re-connect*, because
            # the account already approved this app — the more confusing failure,
            # since the first connection worked.
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def complete_account(
    db: DbSession, held: dict, *, code: str, verifier: str
) -> str | None:
    """Finish the sign-in. Returns a message on failure, `None` on success.

    Called by the shared data callback rather than routed here, because the
    redirect URI is the one already on the registration and there is one of those.
    """
    connection = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == held.get("org"),
            OauthClient.provider == "google",
        )
    )
    if connection is None:
        return "That connection no longer exists."

    from app.oauth import secret_of

    response = httpx.post(
        sheets_account.TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": connection.client_id,
            "client_secret": secret_of(connection),
            "redirect_uri": _redirect_uri(db),
            "code_verifier": verifier,
        },
        headers={"Accept": "application/json"},
        timeout=HTTP_TIMEOUT,
    )
    if response.status_code != 200:
        return f"Google refused that sign-in. {response.text[:300]}"

    body = response.json()
    refresh = str(body.get("refresh_token") or "")
    if not refresh:
        return (
            "Google returned no refresh token, so this could not keep working "
            "unattended. Try again — a re-connect only issues one when the consent "
            "screen is shown."
        )

    sheets_account.store(
        db,
        connection,
        refresh_token=refresh,
        connected_as=_who(str(body.get("id_token") or ""), str(body.get("access_token") or "")),
    )
    db.commit()
    return None


def _who(id_token: str, access_token: str) -> str:
    """Which account signed in. Cosmetic — an empty answer is not fatal."""
    import base64

    parts = id_token.split(".")
    if len(parts) == 3:
        try:
            raw = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
            claims = json.loads(raw)
            if isinstance(claims, dict) and claims.get("email"):
                return str(claims["email"])[:320]
        except Exception:  # noqa: BLE001 — cosmetic, never worth failing a connect
            pass

    # No id token when `openid` was not among the scopes, which is the normal case
    # here: this asks for spreadsheet access, not identity. One cheap call rather
    # than widening the grant just to put a name on a screen.
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            body = client.get(
                "https://www.googleapis.com/drive/v3/about",
                params={"fields": "user(emailAddress)"},
                headers={"Authorization": f"Bearer {access_token}"},
            ).json()
        return str((body.get("user") or {}).get("emailAddress") or "")[:320]
    except Exception:  # noqa: BLE001
        return ""


class ServiceKey(BaseModel):
    key: str = Field(min_length=1, max_length=20000)


class ServiceKeyResult(BaseModel):
    #: The address to share spreadsheets with. Without it the key reads nothing.
    share_with: str


@router.post("/service-account", response_model=ServiceKeyResult)
def save_service_account(
    payload: ServiceKey,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ServiceKeyResult:
    """Store a service-account key, and hand back the address to share with.

    **The address is the whole second half of this setup.** A key alone reads
    nothing: Google grants a service account exactly the files somebody has shared
    with it, so a screen that took the key and said "connected" would be lying
    until a human went and pressed Share.
    """
    connection = _registered(db, actor.organization_id)
    try:
        email = sheets_account.store_service_account(db, connection, key=payload.key)
    except sheets_account.Refused as problem:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(problem)
        ) from None

    audit.record(
        db,
        actor=actor,
        action="sheets.service_account.saved",
        request=request,
        share_with=email,
    )
    db.commit()
    return ServiceKeyResult(share_with=email)


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def forget_account(
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> Response:
    """Stop reading spreadsheets as that account. The sources stay."""
    connection = _registered(db, actor.organization_id)
    who = sheets_account.connected_as(connection)
    sheets_account.forget(db, connection)
    audit.record(
        db,
        actor=actor,
        action="sheets.account.forgotten",
        request=request,
        was=who,
        spreadsheets_kept=len(_sheets(db, actor.organization_id)),
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Browsing ─────────────────────────────────────────────────────────────────


class FileHit(BaseModel):
    """One spreadsheet somebody could choose."""

    spreadsheet_id: str
    name: str
    location: str = ""
    modified: str = ""
    web_url: str = ""


def _hit(item: dict) -> FileHit | None:
    """One Drive file as a choice, or `None` if it is not a spreadsheet.

    Filtered by mime type rather than by extension, the opposite of the Excel
    picker — and for a good reason either way. A Google Sheet has no extension in
    its name, so the type is the only signal; a file in OneDrive has a type that
    varies by where it came from, so the name is the better one.
    """
    if item.get("mimeType") != "application/vnd.google-apps.spreadsheet":
        return None
    file_id = str(item.get("id") or "")
    if not file_id:
        return None
    return FileHit(
        spreadsheet_id=file_id,
        name=str(item.get("name") or ""),
        location="Shared with me" if item.get("shared") else "My Drive",
        modified=str(item.get("modifiedTime") or ""),
        web_url=str(item.get("webViewLink") or ""),
    )


@router.get("/files", response_model=list[FileHit])
def browse(
    q: str = Query("", max_length=200),
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[FileHit]:
    """Spreadsheets the connected account can open.

    **Empty query means most-recently-modified, not everything.** What somebody
    connecting a spreadsheet almost always wants is one they touched this week.

    With a service account this lists exactly the files that have been shared with
    it — which is the right answer, and a useful check on whether the sharing step
    was actually done.
    """
    _, token = _token(db, actor.organization_id)

    term = q.strip()
    clauses = ["mimeType = 'application/vnd.google-apps.spreadsheet'", "trashed = false"]
    if term:
        # Escaped because the term goes inside a single-quoted Drive query string.
        clauses.append(f"name contains '{term.replace(chr(39), chr(92) + chr(39))}'")

    with httpx.Client(
        timeout=HTTP_TIMEOUT,
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=True,
    ) as client:
        try:
            body = request_json(
                client,
                f"{DRIVE}/files",
                {
                    "q": " and ".join(clauses),
                    "orderBy": "modifiedTime desc",
                    "pageSize": str(MAX_FILES),
                    "fields": "files(id,name,mimeType,modifiedTime,webViewLink,shared)",
                    # So a Workspace company sees shared drives, not only the
                    # account own files.
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                },
                "Google",
            )
        except RestProblem as problem:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(problem)
            ) from None

    found = body.get("files") if isinstance(body, dict) else None
    items = found if isinstance(found, list) else []
    hits = [hit for hit in (_hit(item) for item in items if isinstance(item, dict)) if hit]
    return hits[:MAX_FILES]


@router.get("/resolve", response_model=FileHit)
def resolve(
    url: str = Query(..., max_length=2000),
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> FileHit:
    """One pasted spreadsheet address, as a chosen file.

    The way in for a sheet the picker cannot reach — one on a shared drive the
    account can open but Drive does not list, or one somebody has the link to and
    nothing else.
    """
    _, token = _token(db, actor.organization_id)
    file_id = spreadsheet_id_of(url)
    if not file_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "That does not look like a spreadsheet address. Paste the whole "
                "URL from the browser, or just the long code between /d/ and /edit."
            ),
        )

    with httpx.Client(
        timeout=HTTP_TIMEOUT,
        headers={"Authorization": f"Bearer {token}"},
        follow_redirects=True,
    ) as client:
        try:
            item = request_json(
                client,
                f"{DRIVE}/files/{file_id}",
                {
                    "fields": "id,name,mimeType,modifiedTime,webViewLink,shared",
                    "supportsAllDrives": "true",
                },
                "Google",
            )
        except RestProblem as problem:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(problem)
            ) from None

    hit = _hit(item) if isinstance(item, dict) else None
    if hit is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "That address does not point at a Google Sheet, or the connected "
                "account cannot open it. If you are using a service account, share "
                "the spreadsheet with its address first."
            ),
        )
    return hit


class Tab(BaseModel):
    name: str


@router.get("/tabs", response_model=list[Tab])
def tabs(
    spreadsheet_id: str = Query(..., max_length=300),
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[Tab]:
    """The tabs in one spreadsheet, so nobody types a name from memory.

    A typo there used to produce "that tab is empty", which is true and useless —
    the tab was not empty, it did not exist.
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
                f"{SHEETS}/{spreadsheet_id_of(spreadsheet_id)}",
                {"fields": "sheets(properties(title))"},
                "Google",
            )
        except RestProblem as problem:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(problem)
            ) from None

    found = body.get("sheets") if isinstance(body, dict) else None
    sheets = found if isinstance(found, list) else []
    return [
        Tab(name=str((s.get("properties") or {}).get("title") or ""))
        for s in sheets
        if isinstance(s, dict) and (s.get("properties") or {}).get("title")
    ]
