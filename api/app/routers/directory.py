"""Managing directory sync: the switch, the rules, and the decisions.

Under `/api/admin/directory` because every one of these is an admin's job, and
because it sits beside `/api/admin/sso` — both are settings for a connection rather
than things an ordinary user touches.

**The credential is not here.** It lives on the provider connection and is edited on
the Integrations page; this router turns the sync *on* for a connection that already
exists, and refuses when one does not, with a message saying where to go.
"""

from __future__ import annotations

from datetime import UTC, datetime

import json
import logging
import time
from html import escape as html_escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app import audit, mail_graph, oidc, providers, public_url, tenant_account
from app.directory import apply as apply_module
from app.crypto import decrypt, encrypt
from app.db import get_db
from app.directory import sync as directory_sync
from app.directory.apply import differences
from app.directory.rules import Rule, conflicts
from app.models import DirectoryPerson, DirectoryRule, DirectoryRun, OauthClient, UserAccount
from app.models.directory import DIRECTORY_STATUSES
from app.models.user import ORG_ROLES
from app.oidc import new_flow_state
from app.sessions import require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/directory", tags=["admin"])

#: What an admin may set a person to by hand.
#:
#: `archived` is absent on purpose: it is something the *directory* decides, by
#: no longer returning somebody. An admin archiving a person who is still employed
#: would be undone on the next pass, which is a button that lies.
DECIDABLE = ("pending", "approved", "hidden", "declined")


# ── What the page reads ──────────────────────────────────────────────────────


class RunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    people_seen: int
    created: int
    archived: int
    needs_review: int
    pending: int
    applied: int
    error: str | None


class StatusRead(BaseModel):
    """Whether this can run at all, and what happened last time."""

    #: Which provider connections could sync a directory, whether or not they do.
    #: Empty when nothing in this build reads one.
    available: list[str]
    provider: str | None
    enabled: bool
    #: False when there is no connection to enable it on — the page then points at
    #: Integrations rather than showing a switch that cannot be flipped.
    connected: bool
    last_run: RunRead | None
    #: How many people are waiting on a decision. Drives the badge, so it counts
    #: work outstanding rather than work done.
    pending: int
    #: Hours between reads. Sits with the switch because it is the same decision
    #: asked twice — whether to read this directory, and how often.
    sync_hours: int
    #: Whether the sync skips accounts holding no licence. Sits with the switch
    #: because it is part of the same question: what should this read.
    ignore_unlicensed: bool

    #: How this connection signs in, and — in delegated mode — as whom.
    auth_mode: str
    connected_as: str
    #: Whether an account is signed in. Always false in application mode, where
    #: none is needed: `account_required` says which of those two it is.
    account_connected: bool
    account_required: bool

    #: Whether outgoing mail goes through this connection, and as which mailbox.
    #: On the connection rather than the SMTP settings because it is the same
    #: application registration that sends it.
    mail_enabled: bool
    mail_from: str


class SwitchWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    enabled: bool
    #: Omitted leaves the stored value alone, for the same reason the frequency
    #: does: flicking the switch must not quietly undo a filter somebody set.
    ignore_unlicensed: bool | None = None
    #: Omitted leaves the stored frequency alone, so turning the switch off and on
    #: again does not silently reset it to daily.
    sync_hours: int | None = Field(
        default=None,
        ge=directory_sync.MIN_SYNC_HOURS,
        le=directory_sync.MAX_SYNC_HOURS,
    )


class RuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    department: str
    job_title: str
    office: str
    group: str
    role: str
    team_id: int | None


class RuleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department: str = Field(default="", max_length=200)
    job_title: str = Field(default="", max_length=200)
    office: str = Field(default="", max_length=200)
    group: str = Field(default="", max_length=200)
    role: str = Field(default="agent", max_length=20)
    team_id: int | None = None


class RulesRead(BaseModel):
    rules: list[RuleRead]
    #: Pairs of rule positions with identical conditions. Not an error — the second
    #: is simply unreachable — but always a mistake, and one an admin cannot see by
    #: looking at the list.
    clashes: list[list[int]]


class DifferenceRead(BaseModel):
    field: str
    ours: str
    theirs: str


class PersonRead(BaseModel):
    id: int
    external_id: str
    email: str
    display_name: str
    job_title: str
    department: str
    office_location: str
    groups: list[str]
    enabled: bool
    status: str
    pending_reason: str
    user_account_id: int | None
    last_seen_at: datetime | None
    #: What the rules would do with them, so an admin approving somebody can see
    #: where they will land before pressing the button rather than afterwards.
    would_be_role: str
    would_be_team_id: int | None
    #: Where the account and the directory disagree. Empty for almost everybody.
    differences: list[DifferenceRead]


class DecideWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[int] = Field(min_length=1, max_length=500)
    status: str


# ── Status and the switch ────────────────────────────────────────────────────


def _connections(db: DbSession, org_id: int) -> list[OauthClient]:
    return [
        row
        for row in db.scalars(
            select(OauthClient).where(OauthClient.organization_id == org_id)
        ).all()
        if row.provider in directory_sync.READERS
    ]


@router.get("", response_model=StatusRead)
def get_status(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> StatusRead:
    connections = _connections(db, actor.organization_id)
    live = next((c for c in connections if c.directory_sync_enabled), None)
    chosen = live or (connections[0] if connections else None)

    last = db.scalar(
        select(DirectoryRun)
        .where(DirectoryRun.organization_id == actor.organization_id)
        .order_by(DirectoryRun.started_at.desc())
        .limit(1)
    )

    return StatusRead(
        # Every provider this build could read, whether or not one is connected —
        # so the page can say "connect Microsoft to sync your people" rather than
        # showing nothing and explaining nothing.
        available=sorted(directory_sync.READERS),
        provider=chosen.provider if chosen else None,
        enabled=bool(live),
        connected=bool(chosen and chosen.client_secret_encrypted),
        last_run=RunRead.model_validate(last) if last else None,
        pending=_count_pending(db, actor.organization_id),
        # The chosen connection's own frequency, or the default for a deployment
        # with nothing connected yet — so the page shows what would happen rather
        # than a zero it would then have to explain.
        sync_hours=(
            chosen.directory_sync_hours
            if chosen
            else int(directory_sync.INTERVAL.total_seconds() // 3600)
        ),
        ignore_unlicensed=bool(chosen and chosen.directory_ignore_unlicensed),
        auth_mode=(
            chosen.directory_auth_mode if chosen else providers.DEFAULT_AUTH_MODE
        ),
        connected_as=(chosen.tenant_connected_as if chosen else ""),
        account_connected=tenant_account.is_connected(chosen),
        account_required=tenant_account.needed_by(chosen),
        mail_enabled=bool(chosen and chosen.mail_enabled),
        mail_from=(chosen.mail_from if chosen else ""),
    )


def _count_pending(db: DbSession, org_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(DirectoryPerson)
            .where(
                DirectoryPerson.organization_id == org_id,
                DirectoryPerson.status == "pending",
            )
        )
        or 0
    )


@router.put("", response_model=StatusRead)
def set_switch(
    payload: SwitchWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> StatusRead:
    """Turn directory sync on or off for one connection.

    **Refuses to turn it on without a connection**, naming the page where one is
    made. Enabling a switch that cannot do anything is how somebody concludes the
    feature is broken rather than unconfigured.
    """
    if payload.provider not in directory_sync.READERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"This build cannot read a {payload.provider!r} directory.",
        )

    connection = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == actor.organization_id,
            OauthClient.provider == payload.provider,
        )
    )
    if payload.enabled and (connection is None or not connection.client_secret_encrypted):
        name = providers.get(payload.provider)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Connect {name.name if name else payload.provider} on the "
                "Integrations page first — syncing your people uses the same "
                "application registration as everything else."
            ),
        )

    if connection is not None:
        connection.directory_sync_enabled = payload.enabled
        if payload.sync_hours is not None:
            connection.directory_sync_hours = payload.sync_hours
        if payload.ignore_unlicensed is not None:
            connection.directory_ignore_unlicensed = payload.ignore_unlicensed

    audit.record(
        db,
        actor=actor,
        action="directory.switch",
        request=request,
        provider=payload.provider,
        enabled=payload.enabled,
        sync_hours=payload.sync_hours,
        ignore_unlicensed=payload.ignore_unlicensed,
    )
    db.commit()
    return get_status(actor=actor, db=db)


@router.post("/sync", response_model=RunRead)
def sync_now(
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RunRead:
    """Read the directory now, rather than waiting for the daily pass.

    The one button an admin presses while watching, so it reports the outcome
    directly rather than leaving them to refresh and guess.
    """
    connection = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == actor.organization_id,
            OauthClient.directory_sync_enabled.is_(True),
        )
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Directory sync is not switched on for any connection.",
        )

    run = directory_sync.run(
        db, connection, now=datetime.now(UTC), trigger="manual"
    )
    audit.record(
        db, actor=actor, action="directory.sync", request=request, provider=connection.provider
    )
    db.commit()
    return RunRead.model_validate(run)


# ── Rules ────────────────────────────────────────────────────────────────────


def _as_rule(row: DirectoryRule) -> Rule:
    return Rule(
        department=row.department,
        job_title=row.job_title,
        office=row.office,
        group=row.group,
        role=row.role,
        team_id=row.team_id,
    )


def _rules_response(db: DbSession, org_id: int) -> RulesRead:
    rows = db.scalars(
        select(DirectoryRule)
        .where(DirectoryRule.organization_id == org_id)
        .order_by(DirectoryRule.id)
    ).all()
    return RulesRead(
        rules=[RuleRead.model_validate(row) for row in rows],
        clashes=[list(pair) for pair in conflicts([_as_rule(row) for row in rows])],
    )


class ValueRead(BaseModel):
    """One value a rule could match on, and how many people carry it."""

    value: str
    #: How many staged people have it. **The half that makes this worth having**:
    #: "Sales" and "sales " look identical in a list and one of them matches nobody,
    #: and a count of 0 next to a value is the only way that shows up before a rule
    #: is saved and quietly matches nothing.
    people: int


class ValuesRead(BaseModel):
    """What the directory actually contains, per field a rule can match on.

    **Read off the staged people rather than asked of the provider.** These are the
    values that will be compared against, so they are the only ones worth offering
    — a department that exists in Entra but on nobody we read is a rule that matches
    nobody, and asking Graph for its own list would produce exactly that.

    Empty until a sync has run, which the form handles by staying typeable.
    """

    department: list[ValueRead]
    job_title: list[ValueRead]
    office: list[ValueRead]
    group: list[ValueRead]


def _counted(rows: list[tuple[str, int]]) -> list[ValueRead]:
    """Non-empty values, commonest first, then alphabetical.

    Frequency before alphabet because the useful answer is near the top: a company
    reading two thousand people has four departments that matter and forty that are
    one person each. Alphabetical within a count keeps it stable between calls, so
    the list does not reshuffle under somebody's cursor.
    """
    return [
        ValueRead(value=value, people=count)
        for value, count in sorted(rows, key=lambda row: (-row[1], row[0].lower()))
        if value and value.strip()
    ]


def _column_values(db: DbSession, org_id: int, column) -> list[ValueRead]:
    rows = db.execute(
        select(column, func.count())
        .where(DirectoryPerson.organization_id == org_id)
        .group_by(column)
    ).all()
    return _counted([(str(value or ""), int(count)) for value, count in rows])


def _group_values(db: DbSession, org_id: int) -> list[ValueRead]:
    """Group names, counted across the JSONB array each person carries.

    Counted in Python rather than with a lateral unnest. The set is one row per
    person holding a handful of names, the alternative is Postgres-specific SQL in
    a router, and this is read when somebody opens a form rather than in a loop.
    """
    tally: dict[str, int] = {}
    for (groups,) in db.execute(
        select(DirectoryPerson.groups).where(
            DirectoryPerson.organization_id == org_id
        )
    ).all():
        for name in groups or []:
            if isinstance(name, str) and name.strip():
                tally[name] = tally.get(name, 0) + 1
    return _counted(list(tally.items()))


@router.get("/values", response_model=ValuesRead)
def get_values(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ValuesRead:
    """Every value a rule could match on, as the directory actually reported it.

    **This exists because the rule form was four free-text boxes.** A rule is a
    string comparison against what a provider sent, so `Sales` when the tenant says
    `Sales Team` matches nobody — and there is nothing on the screen to say so. The
    rule saves, the sync runs, and an admin concludes the feature is broken.

    Offered rather than enforced: the boxes stay typeable, because before the first
    sync there is nothing here, and a rule written for a department that is about to
    exist is a legitimate thing to want.
    """
    org = actor.organization_id
    return ValuesRead(
        department=_column_values(db, org, DirectoryPerson.department),
        job_title=_column_values(db, org, DirectoryPerson.job_title),
        office=_column_values(db, org, DirectoryPerson.office_location),
        group=_group_values(db, org),
    )


class PlaceValue(BaseModel):
    value: str
    people: int
    office_id: int | None = None
    team_id: int | None = None


class PlacesRead(BaseModel):
    offices: list[PlaceValue]
    departments: list[PlaceValue]


class PlaceLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(min_length=1, max_length=200)
    #: An existing office or team; null makes one named after the value; 0
    #: unlinks it.
    target_id: int | None = None


@router.get("/places", response_model=PlacesRead)
def get_places(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> PlacesRead:
    """Offices and Departments (Phase 28): each value synced people have,
    how many, and the office or team it sorts them into."""
    from app.directory import places

    return PlacesRead(**places.values(db, actor.organization_id))


@router.put("/places/office", response_model=PlacesRead)
def link_office(
    payload: PlaceLink,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> PlacesRead:
    from app.directory import places

    places.link_office(db, actor.organization_id, payload.value, payload.target_id)
    audit.record(db, actor=actor, action="directory.office_linked", value=payload.value,
                 target_id=payload.target_id)
    db.commit()
    return PlacesRead(**places.values(db, actor.organization_id))


@router.put("/places/department", response_model=PlacesRead)
def link_department(
    payload: PlaceLink,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> PlacesRead:
    from app.directory import places

    places.link_department(db, actor.organization_id, payload.value, payload.target_id)
    audit.record(db, actor=actor, action="directory.department_linked", value=payload.value,
                 target_id=payload.target_id)
    db.commit()
    return PlacesRead(**places.values(db, actor.organization_id))


class MailWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    enabled: bool
    #: Which mailbox to send as. Empty means the connected account itself, which
    #: is the only address needing no extra Exchange rights.
    mail_from: str = Field(default="", max_length=320)


@router.put("/mail", response_model=StatusRead)
def set_mail(
    payload: MailWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> StatusRead:
    """Turn Microsoft sending on or off, and say which mailbox as.

    **Refuses to turn it on without an account**, naming what is missing. The
    token that sends is the connected account's, so switching this on without one
    produces a setting that looks configured and fails on the first invitation.
    """
    connection = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == actor.organization_id,
            OauthClient.provider == payload.provider,
        )
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nothing connected."
        )
    if (
        payload.enabled
        and connection.directory_auth_mode != "delegated"
        and not payload.mail_from.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Name the mailbox to send as. There is no default: the "
                "application has no mailbox of its own."
            ),
        )

    if (
        payload.enabled
        and connection.directory_auth_mode == "delegated"
        and not tenant_account.is_connected(connection)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Sign in the account this sends as first — in this mode mail goes "
                "out as that account and nothing else."
            ),
        )

    connection.mail_enabled = payload.enabled
    connection.mail_from = payload.mail_from.strip().lower()
    audit.record(
        db,
        actor=actor,
        action="directory.mail",
        request=request,
        provider=payload.provider,
        enabled=payload.enabled,
        mail_from=connection.mail_from,
    )
    db.commit()
    return get_status(actor=actor, db=db)


# ── The account, in delegated mode ───────────────────────────────────────────
#
# Only reached by a connection whose `directory_auth_mode` is `delegated`. In
# application mode nothing signs in and none of this runs.


ACCOUNT_COOKIE = "gg_tenant_flow"
ACCOUNT_PATH = "/api/admin/directory"
ACCOUNT_TTL_SECONDS = 600


class AccountStart(BaseModel):
    """Where to send the browser to choose the account."""

    url: str


def _redirect_uri(db: DbSession) -> str:
    base = public_url.get(db)
    return f"{base}{providers.TENANT_REDIRECT_PATH}"


#: Scopes that are not Graph resources and must not be prefixed as one.
_BARE = ("offline_access", "openid", "profile", "email")


def _account_scopes() -> list[str]:
    """What to ask the account for: the delegated set, in one consent.

    Read from the catalogue rather than listed here, so the sign-in asks for
    exactly what the registration was provisioned with — two lists would drift,
    and the symptom would be a token missing a scope nobody noticed was absent.
    """
    wanted = list(_BARE)
    for capability in providers.MICROSOFT.capabilities:
        if capability.key not in ("directory", "email") or not capability.built:
            continue
        for permission in capability.permissions:
            if permission.mode != "delegated" or permission.name in _BARE:
                continue
            scope = f"https://graph.microsoft.com/{permission.name}"
            if scope not in wanted:
                wanted.append(scope)
    return wanted


def _connection_for(db: DbSession, org_id: int, provider: str) -> OauthClient:
    row = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == org_id, OauthClient.provider == provider
        )
    )
    if row is None or not row.client_secret_encrypted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Connect this provider on the Integrations page first — choosing "
                "an account uses the same application registration."
            ),
        )
    return row


@router.post("/account", response_model=AccountStart)
def start_account(
    provider: str,
    response: Response,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> AccountStart:
    """Begin choosing the account this connection acts as.

    Returns the URL rather than redirecting: the caller is `fetch` from a
    single-page app, and a 303 would be followed inside the XHR so the consent
    screen would arrive as a JSON parse error.
    """
    connection = _connection_for(db, actor.organization_id, provider)
    if connection.directory_auth_mode != "delegated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This connection acts as the application, so there is no account "
                "to sign in. Switch it to the service-account mode first."
            ),
        )

    flow = new_flow_state()
    url = tenant_account.authorize_url(
        connection,
        redirect_uri=_redirect_uri(db),
        scopes=_account_scopes(),
        state=flow.state,
        challenge=oidc._code_challenge(flow.code_verifier),
    )

    # Encrypted rather than signed, because it holds the PKCE verifier: anybody
    # who could read it and intercept the code could complete the exchange.
    response.set_cookie(
        ACCOUNT_COOKIE,
        encrypt(
            json.dumps(
                {
                    "state": flow.state,
                    "verifier": flow.code_verifier,
                    "provider": provider,
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


@router.get("/callback")
def account_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: DbSession = Depends(get_db),
) -> HTMLResponse:
    """Where Microsoft sends the browser back.

    **Unauthenticated by necessity** — a provider redirect carries no session
    cookie on a cross-site navigation in any modern browser. The sealed flow
    cookie is what makes it safe: encrypted, short-lived, scoped to this path, and
    carrying the `state` that must match what came back.
    """
    sealed = request.cookies.get(ACCOUNT_COOKIE)
    if not sealed:
        return _finished(db, "That took too long. Please try again.")
    try:
        held = json.loads(decrypt(sealed))
    except ValueError:
        return _finished(db, "That could not be verified. Please try again.")
    if held.get("exp", 0) < time.time():
        return _finished(db, "That took too long. Please try again.")

    if error:
        return _finished(db, 
            "Sign-in was cancelled."
            if error == "access_denied"
            else f"{error.replace('_', ' ').capitalize()}."
        )
    if not code or not state or state != held.get("state"):
        # A mismatched state means the response did not come from our request.
        return _finished(db, "That sign-in did not match. Please try again.")

    connection = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == held.get("org"),
            OauthClient.provider == held.get("provider"),
        )
    )
    if connection is None:
        return _finished(db, "That connection no longer exists.")

    try:
        refresh, who = tenant_account.exchange(
            connection,
            code=code,
            redirect_uri=_redirect_uri(db),
            verifier=held["verifier"],
        )
        tenant_account.store(db, connection, refresh_token=refresh, connected_as=who)
        db.commit()
    except tenant_account.Refused as problem:
        return _finished(db, str(problem))
    except Exception as problem:  # noqa: BLE001 — reported to a person, and logged
        logger.warning("tenant account exchange failed", exc_info=problem)
        return _finished(db, "Could not complete that sign-in. Please try again.")

    done = _finished(db, None)
    done.delete_cookie(ACCOUNT_COOKIE, path=ACCOUNT_PATH)
    return done


#: What the popup posts back to the page that opened it. Same shape the connector
#: callback uses, and for the same reasons: a popup closes itself, and a lost
#: opener still lands somewhere sensible.
_DONE_PAGE = """<!doctype html>
<meta charset="utf-8">
<title>Connecting…</title>
<body style="font:14px system-ui;padding:2rem;color:#444">
<p id="m">Finishing up…</p>
<script>
(function () {
  var result = JSON.parse(document.currentScript.dataset.result);
  if (window.opener && !window.opener.closed) {
    window.opener.postMessage({ source: "goalgetter-tenant", result: result }, %(origin)s);
    window.close();
    return;
  }
  document.getElementById("m").textContent = result.error || "Connected.";
  var to = "/integrations";
  if (result.error) to += "?error=" + encodeURIComponent(result.error);
  window.location.replace(to);
})();
</script>
</body>"""


def _finished(db: DbSession, message: str | None) -> HTMLResponse:
    payload = json.dumps({"error": message})
    origin = public_url.get(db)
    page = _DONE_PAGE % {"origin": json.dumps(origin)}
    # In a data attribute rather than the script body, so the payload is parsed as
    # data and can never be parsed as code.
    page = page.replace(
        "<script>", f'<script data-result="{html_escape(payload, quote=True)}">', 1
    )
    return HTMLResponse(page)


class MailTestWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    #: Where to send it. **A typed address rather than the admin's own**, unlike
    #: the SMTP test beside it — the question here is usually "does mail from this
    #: mailbox reach people outside the tenant", and an admin's own address is the
    #: one delivery path most likely to work regardless.
    to: EmailStr


class MailTestResult(BaseModel):
    ok: bool
    detail: str


@router.post("/mail/test", response_model=MailTestResult)
def test_mail(
    payload: MailTestWrite,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> MailTestResult:
    """Send one real message through Microsoft, and say what happened.

    **Deliberately not `mail.send`.** That one tries Microsoft and falls back to
    SMTP, which is right for an invitation and wrong for a test: a green result
    that came from the fallback would say this setting works when it does not.
    This exercises the path being configured, and nothing else.

    Works whether or not sending is switched on, because "does this work?" is the
    question somebody asks *before* switching it on.
    """
    connection = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == actor.organization_id,
            OauthClient.provider == payload.provider,
        )
    )
    if connection is None or not connection.client_secret_encrypted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect this provider on the Integrations page first.",
        )
    if not mail_graph.sender_for(connection):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Name the mailbox to send as first — the application has none of "
                "its own."
            ),
        )

    sent = mail_graph.send(
        db,
        connection,
        to=str(payload.to),
        subject="GoalGetter test message",
        body=(
            "This is a test from GoalGetter. If you are reading it, "
            "invitations and password reset links will reach people from "
            f"{mail_graph.sender_for(connection)}."
        ),
    )
    # Committed because a send renews the token, and a rotated refresh token
    # thrown away here is a send that works once and never again.
    db.commit()
    return MailTestResult(ok=sent.ok, detail=sent.detail)


@router.delete("/account", response_model=StatusRead)
def forget_account(
    provider: str,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> StatusRead:
    """Stop acting as that account.

    Switches off what cannot run without it, rather than leaving switches with
    nothing behind them. Signing in and reading spreadsheets are untouched: they
    never went through this token.
    """
    connection = db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == actor.organization_id,
            OauthClient.provider == provider,
        )
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nothing connected."
        )

    tenant_account.forget(db, connection)
    audit.record(
        db, actor=actor, action="directory.account_forgotten", request=request,
        provider=provider,
    )
    db.commit()
    return get_status(actor=actor, db=db)


@router.get("/rules", response_model=RulesRead)
def list_rules(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RulesRead:
    return _rules_response(db, actor.organization_id)


@router.post("/rules", response_model=RulesRead, status_code=status.HTTP_201_CREATED)
def add_rule(
    payload: RuleWrite,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RulesRead:
    _check_role(payload.role)
    db.add(
        DirectoryRule(organization_id=actor.organization_id, **payload.model_dump())
    )
    db.commit()
    return _rules_response(db, actor.organization_id)


@router.put("/rules/{rule_id}", response_model=RulesRead)
def edit_rule(
    rule_id: int,
    payload: RuleWrite,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RulesRead:
    _check_role(payload.role)
    row = _rule_of(db, actor.organization_id, rule_id)
    for key, value in payload.model_dump().items():
        setattr(row, key, value)
    db.commit()
    return _rules_response(db, actor.organization_id)


@router.delete("/rules/{rule_id}", response_model=RulesRead)
def remove_rule(
    rule_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> RulesRead:
    """Delete a rule.

    **Nobody is reassigned by this.** People the rule placed keep the team and role
    they have — the rules only ever propose, and a deletion that silently moved
    fifty people would be the loudest possible version of the thing this design
    exists to prevent.
    """
    db.delete(_rule_of(db, actor.organization_id, rule_id))
    db.commit()
    return _rules_response(db, actor.organization_id)


def _rule_of(db: DbSession, org_id: int, rule_id: int) -> DirectoryRule:
    row = db.scalar(
        select(DirectoryRule).where(
            DirectoryRule.id == rule_id, DirectoryRule.organization_id == org_id
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such rule.")
    return row


def _check_role(role: str) -> None:
    if role not in ORG_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{role!r} is not a role. Known: {', '.join(ORG_ROLES)}.",
        )


# ── People, and deciding about them ──────────────────────────────────────────


@router.get("/people", response_model=list[PersonRead])
def list_people(
    person_status: str = Query(default="pending", alias="status"),
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[PersonRead]:
    if person_status not in DIRECTORY_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{person_status!r} is not a status. "
            f"Known: {', '.join(DIRECTORY_STATUSES)}.",
        )

    rules = directory_sync.rules_for(db, actor.organization_id)
    rows = db.scalars(
        select(DirectoryPerson)
        .where(
            DirectoryPerson.organization_id == actor.organization_id,
            DirectoryPerson.status == person_status,
        )
        .order_by(DirectoryPerson.display_name)
    ).all()

    from app.directory.rules import Person, place

    found = []
    for row in rows:
        placement = place(
            rules,
            Person(
                external_id=row.external_id,
                email=row.email,
                display_name=row.display_name,
                job_title=row.job_title,
                department=row.department,
                office_location=row.office_location,
                groups=tuple(row.groups or ()),
                enabled=row.enabled,
            ),
        )
        found.append(
            PersonRead(
                id=row.id,
                external_id=row.external_id,
                email=row.email,
                display_name=row.display_name,
                job_title=row.job_title,
                department=row.department,
                office_location=row.office_location,
                groups=list(row.groups or ()),
                enabled=row.enabled,
                status=row.status,
                pending_reason=row.pending_reason,
                user_account_id=row.user_account_id,
                last_seen_at=row.last_seen_at,
                would_be_role=placement.role,
                would_be_team_id=placement.team_id,
                differences=[
                    DifferenceRead(field=d.field, ours=d.ours, theirs=d.theirs)
                    for d in differences(row)
                ],
            )
        )
    return found


@router.post("/people/decide", response_model=list[PersonRead])
def decide(
    payload: DecideWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[PersonRead]:
    """Add people, hide them, decline them, or put them back — in bulk.

    **Adding hidden is an addition, not a refusal**, and it is what most of a
    directory wants. A company of four hundred has contractors, service
    accounts and whole departments that do not sell: none belong on a
    leaderboard, all belong in the roster. Declining them creates nothing, so
    they exist nowhere and cannot be found, photographed or moved onto a team
    later.

    **Bulk because the first use is two hundred people at once.** Approving a
    company one row at a time is the kind of chore that makes somebody give up and
    keep typing names in by hand instead.

    **Approving creates the accounts, immediately.** It used to only mark them and
    leave the next sync pass to do it — one path from approved to account, with
    the per-person error handling on it, which was the right instinct. What it
    missed is that a daily sync makes "approved" and "has an account" up to
    twenty-four hours apart: an admin approves four hundred people, the queue
    empties, the People list is unchanged, and the only available reading is that
    they vanished.

    The instinct is kept by calling the *same* function the sync calls, rather
    than a second implementation of it — so there is still exactly one path, and
    the sync still sweeps up anybody this missed.
    """
    if payload.status not in DECIDABLE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{payload.status!r} is not something to decide. "
                f"Choose one of: {', '.join(DECIDABLE)}."
            ),
        )

    rows = db.scalars(
        select(DirectoryPerson).where(
            DirectoryPerson.organization_id == actor.organization_id,
            DirectoryPerson.id.in_(payload.ids),
        )
    ).all()

    for row in rows:
        # Somebody the directory has stopped returning is not a decision to make —
        # they are gone, and marking them approved would create an account for a
        # person who no longer works there.
        if row.status == "archived":
            continue
        row.status = payload.status
        if payload.status != "pending":
            row.pending_reason = ""

    # **The same function the sync pass calls**, not a second copy of it — so
    # there is still one path from approved to account, and the sync still sweeps
    # up anybody this could not place.
    created = 0
    problems: list[str] = []
    if payload.status in apply_module.ADDS_AN_ACCOUNT:
        created, problems = directory_sync.apply_approved(
            db,
            actor.organization_id,
            # Read here rather than passed in: the rules decide role and team, and
            # an approval that ignored them would place everybody as an unassigned
            # agent and quietly disagree with what the panel previewed.
            rules=directory_sync.rules_for(db, actor.organization_id),
            now=datetime.now(UTC),
        )

    audit.record(
        db,
        actor=actor,
        action="directory.decide",
        request=request,
        decided=payload.status,
        count=len(rows),
        accounts_created=created,
        # Named, not counted. "3 could not be created" is not something anybody
        # can act on; "Sam Rivera has no email address" is.
        problems=problems or None,
    )
    db.commit()
    return list_people(person_status="pending", actor=actor, db=db)
