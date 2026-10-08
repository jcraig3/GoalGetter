"""Announcement destinations: what to announce, and where.

Admin only. A destination posts to a channel a whole team reads, which is the
same decision as publishing a board to the organization.

**Two ways to reach a channel.** Picked from the Teams a signed-in account is
in (`via = graph`), which is what most people expect; or through a Workflows
link made inside the channel (`via = workflow`), which needs no account at all.

**A Workflows link is write-only.** It carries its own signature, so anybody
holding it can post into the channel as the Workflow. It is stored encrypted,
never sent back in full, and shown only as a hint to recognise it by; changing
it means pasting a new one.
"""

import json
import logging
import time
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app import announcements as service, audit, crypto, oidc, public_url, teams_account
from app.db import get_db
from app.models import (
    AnnouncementDestination,
    OauthClient,
    Office,
    Organization,
    Team,
    UserAccount,
)
from app.oidc import new_flow_state
from app.sessions import require_role
from app.validation import Name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/announcements", tags=["announcements"])


class ChoiceRead(BaseModel):
    key: str
    label: str


class DestinationRead(BaseModel):
    id: int
    kind: str
    name: str
    via: str = "workflow"
    #: Enough of a Workflows link to recognise it by. Never the link.
    link_hint: str
    #: For a picked channel: "Metropolis Sales Team › Closers".
    channel_label: str | None = None
    team_external_id: str | None = None
    channel_external_id: str | None = None
    events: list[str]
    office_id: int | None
    team_id: int | None
    enabled: bool
    last_sent_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    #: True when the most recent thing that happened was a failure — the one
    #: fact the settings page leads with.
    failing: bool


class ListRead(BaseModel):
    #: The master switch. Off, nothing is posted to any channel.
    enabled: bool = True
    choices: list[ChoiceRead]
    destinations: list[DestinationRead]


def _read(row: AnnouncementDestination) -> DestinationRead:
    failing = row.last_error_at is not None and (
        row.last_sent_at is None or row.last_error_at > row.last_sent_at
    )
    return DestinationRead(
        id=row.id, kind=row.kind, name=row.name, via=row.via,
        link_hint=service.hint_of(row.webhook_url) if row.via == "workflow" else "",
        channel_label=row.channel_label,
        team_external_id=row.team_external_id,
        channel_external_id=row.channel_external_id,
        events=list(row.events or []),
        office_id=row.office_id, team_id=row.team_id, enabled=row.enabled,
        last_sent_at=row.last_sent_at, last_error=row.last_error,
        last_error_at=row.last_error_at, failing=failing,
    )


@router.get("/destinations", response_model=ListRead)
def list_destinations(
    kind: Literal["teams", "slack"] | None = None,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ListRead:
    """Every channel — or one kind's, for the Teams and Slack cards."""
    query = select(AnnouncementDestination).where(
        AnnouncementDestination.organization_id == actor.organization_id
    )
    if kind is not None:
        query = query.where(AnnouncementDestination.kind == kind)
    rows = db.scalars(query.order_by(AnnouncementDestination.name)).all()
    org = db.get(Organization, actor.organization_id)
    return ListRead(
        enabled=org.teams_enabled,
        choices=[ChoiceRead(key=k, label=v) for k, v in service.CHOICES.items()],
        destinations=[_read(row) for row in rows],
    )


class DestinationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = "teams"
    name: Name(80)
    via: Literal["workflow", "graph"] = "workflow"
    #: For `workflow`. Required when creating; on an update, absent keeps the
    #: stored one.
    webhook_url: str | None = None
    #: For `graph`: the picked Team and channel, by Microsoft's ids.
    team_external_id: str | None = Field(default=None, max_length=200)
    channel_external_id: str | None = Field(default=None, max_length=200)
    events: list[str] = Field(default_factory=lambda: list(service.DEFAULT_CHOICES))
    office_id: int | None = None
    team_id: int | None = None
    enabled: bool = True


def _apply(
    db: DbSession, actor: UserAccount, row: AnnouncementDestination, payload: DestinationWrite
) -> None:
    if payload.kind not in ("teams", "slack"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A channel is a Microsoft Teams or a Slack one.",
        )
    if payload.kind == "slack" and payload.via != "workflow":
        # Slack is reached through its incoming webhook link, always.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A Slack channel is added with its incoming webhook link.",
        )
    if row.id is not None and row.kind != payload.kind:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A channel cannot change from Teams to Slack. Add a new one.",
        )
    unknown = set(payload.events) - set(service.CHOICES)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Not something that can be announced: {sorted(unknown)[0]}.",
        )
    if not payload.events:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose at least one kind of win to announce.",
        )
    if payload.office_id is not None and payload.team_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose one office or one team, not both.",
        )
    if payload.office_id is not None:
        office = db.get(Office, payload.office_id)
        if office is None or office.organization_id != actor.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Office not found.")
    if payload.team_id is not None:
        team = db.get(Team, payload.team_id)
        if team is None or team.organization_id != actor.organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")

    if payload.via == "graph":
        _pick(db, actor, row, payload)
    elif payload.webhook_url is not None:
        try:
            url = service.check_link(payload.kind, payload.webhook_url)
        except service.LinkProblem as problem:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(problem)
            ) from None
        row.webhook_url = crypto.encrypt(url)
        # A new link is a fresh start: the last one's failure is not this one's.
        row.last_error = None
        row.last_error_at = None

    if payload.via == "workflow" and not (payload.webhook_url or row.webhook_url):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Paste the channel's incoming webhook link."
                if payload.kind == "slack"
                else "Paste the channel's Workflows link."
            ),
        )
    row.via = payload.via
    if payload.via == "workflow":
        row.team_external_id = row.channel_external_id = row.channel_label = None

    row.kind = payload.kind
    row.name = payload.name.strip()
    row.events = list(dict.fromkeys(payload.events))
    row.office_id = payload.office_id
    row.team_id = payload.team_id
    row.enabled = payload.enabled


@router.post("/destinations", response_model=DestinationRead, status_code=status.HTTP_201_CREATED)
def create_destination(
    payload: DestinationWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> DestinationRead:
    """Add a channel.

    **Starts from now.** Its reading position is set to the newest win, so a
    channel added this afternoon is not flooded with every win since the
    deployment began.
    """
    row = AnnouncementDestination(organization_id=actor.organization_id)
    _apply(db, actor, row, payload)
    row.last_notification_id = service.newest_notification_id(db, actor.organization_id)
    db.add(row)
    audit.record(db, actor=actor, action="announcement_destination.created", request=request, name=row.name)
    db.commit()
    return _read(row)


def _owned(db: DbSession, actor: UserAccount, destination_id: int) -> AnnouncementDestination:
    row = db.get(AnnouncementDestination, destination_id)
    if row is None or row.organization_id != actor.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    return row


@router.patch("/destinations/{destination_id}", response_model=DestinationRead)
def update_destination(
    destination_id: int,
    payload: DestinationWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> DestinationRead:
    """Change what it announces, whose, or its link.

    Switching one back on does not replay what was missed while it was off — it
    carries on from now, for the same reason a new one starts from now.
    """
    row = _owned(db, actor, destination_id)
    was_enabled = row.enabled
    _apply(db, actor, row, payload)
    if row.enabled and not was_enabled:
        row.last_notification_id = service.newest_notification_id(db, actor.organization_id)
    audit.record(db, actor=actor, action="announcement_destination.updated", request=request, name=row.name)
    db.commit()
    return _read(row)


@router.delete("/destinations/{destination_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_destination(
    destination_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    row = _owned(db, actor, destination_id)
    audit.record(db, actor=actor, action="announcement_destination.deleted", request=request, name=row.name)
    db.delete(row)
    db.commit()


class TestRead(BaseModel):
    ok: bool
    error: str | None = None


@router.post("/destinations/{destination_id}/test", response_model=TestRead)
def test_destination(
    destination_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> TestRead:
    """Post one hello card to the channel, now — the way to know a link works
    before the first win is waiting on it."""
    row = _owned(db, actor, destination_id)
    error = service.send_test(row, db=db)
    db.commit()  # a rotated refresh token, if Microsoft sent one
    return TestRead(ok=error is None, error=error)


class Switch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on: bool


@router.put("/enabled", response_model=ListRead)
def set_enabled(
    payload: Switch,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ListRead:
    """Switch Microsoft Teams on or off as a whole — posting to every channel,
    and the scheduled reads that keep teams in step. Set from the Microsoft 365
    box; configured in the Microsoft Teams card.

    Switching it on carries on from now: a pause does not save wins up to
    arrive in a burst. See `announcements.resume`.
    """
    org = db.get(Organization, actor.organization_id)
    if payload.on and not org.teams_enabled:
        service.resume(db, org.id)
    org.teams_enabled = payload.on
    audit.record(db, actor=actor, action="teams.switched", request=request, on=str(payload.on))
    db.commit()
    return list_destinations(actor=actor, db=db)


@router.put("/destinations/{destination_id}/enabled", response_model=DestinationRead)
def set_destination_enabled(
    destination_id: int,
    payload: Switch,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> DestinationRead:
    """Switch one channel on or off, without opening its settings."""
    row = _owned(db, actor, destination_id)
    if payload.on and not row.enabled:
        row.last_notification_id = service.newest_notification_id(db, actor.organization_id)
    row.enabled = payload.on
    audit.record(
        db, actor=actor, action="announcement_destination.switched", request=request,
        name=row.name, on=str(payload.on),
    )
    db.commit()
    return _read(row)


# ── Picking a channel: the account that posts ────────────────────────────────


def _microsoft(db: DbSession, org_id: int) -> OauthClient | None:
    return db.scalar(
        select(OauthClient).where(
            OauthClient.organization_id == org_id, OauthClient.provider == "microsoft"
        )
    )


def _registered(db: DbSession, org_id: int) -> OauthClient:
    connection = _microsoft(db, org_id)
    if connection is None or not connection.client_secret_encrypted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect Microsoft 365 first — picking a channel signs in through it.",
        )
    return connection


def _token(db: DbSession, org_id: int) -> tuple[OauthClient, str]:
    connection = _registered(db, org_id)
    try:
        return connection, teams_account.access_token(db, connection)
    except teams_account.NotConnected as problem:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(problem)) from None
    except teams_account.Refused as problem:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(problem)) from None


def _pick(
    db: DbSession, actor: UserAccount, row: AnnouncementDestination, payload: DestinationWrite
) -> None:
    """A picked channel, checked with Microsoft as the posting account — so a
    channel is only saved when that account can see it."""
    if not payload.team_external_id or not payload.channel_external_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choose a Team and a channel."
        )
    unchanged = (
        row.via == "graph"
        and row.team_external_id == payload.team_external_id
        and row.channel_external_id == payload.channel_external_id
    )
    if unchanged:
        return
    _, token = _token(db, actor.organization_id)
    try:
        label = teams_account.describe_channel(
            token, payload.team_external_id, payload.channel_external_id
        )
    except teams_account.GraphProblem as problem:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(problem)) from None
    row.team_external_id = payload.team_external_id
    row.channel_external_id = payload.channel_external_id
    row.channel_label = label
    row.webhook_url = None
    # A new channel is a fresh start: the last one's failure is not this one's.
    row.last_error = None
    row.last_error_at = None


class AccountRead(BaseModel):
    #: Whether Microsoft 365 is connected at all — without it only Workflows
    #: links are possible, and the page says so.
    registered: bool
    connected: bool
    connected_as: str


@router.get("/account", response_model=AccountRead)
def read_account(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> AccountRead:
    connection = _microsoft(db, actor.organization_id)
    return AccountRead(
        registered=bool(connection and connection.client_secret_encrypted),
        connected=teams_account.is_connected(connection),
        connected_as=teams_account.connected_as(connection),
    )


class AccountStart(BaseModel):
    url: str


@router.post("/account", response_model=AccountStart)
def start_account(
    response: Response,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> AccountStart:
    """Begin signing in the account announcements post as.

    Through the Excel sign-in's callback and cookie, so the registration needs
    no new address — the cookie's `account` says which sign-in it is.
    """
    from urllib.parse import urlencode

    from app import providers
    from app.routers import excel as excel_router

    connection = _registered(db, actor.organization_id)
    flow = new_flow_state()
    tenant = (connection.tenant_id or "").strip() or "organizations"
    url = (
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?"
        + urlencode(
            {
                "client_id": connection.client_id,
                "response_type": "code",
                "redirect_uri": excel_router._redirect_uri(),
                "response_mode": "query",
                "scope": " ".join(teams_account.SCOPES),
                "state": flow.state,
                "code_challenge": oidc._code_challenge(flow.code_verifier),
                "code_challenge_method": "S256",
                # Always ask: choosing *who* posts is the decision being made.
                "prompt": "select_account",
            }
        )
    )
    response.set_cookie(
        excel_router.ACCOUNT_COOKIE,
        crypto.encrypt(
            json.dumps(
                {
                    "state": flow.state,
                    "verifier": flow.code_verifier,
                    "account": "teams",
                    "org": actor.organization_id,
                    "exp": time.time() + excel_router.ACCOUNT_TTL_SECONDS,
                }
            )
        ),
        max_age=excel_router.ACCOUNT_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=public_url.is_https(db),
        path=providers.DATA_REDIRECT_PATH,
    )
    return AccountStart(url=url)


def complete_account(db: DbSession, held: dict, *, code: str, verifier: str) -> str | None:
    """Finish the sign-in. A message on failure, None on success. Called by
    the shared callback in `oauth_clients`."""
    from app.routers import excel as excel_router
    from app.tenant_account import exchange

    connection = _microsoft(db, held.get("org"))
    if connection is None:
        return "That connection no longer exists."
    try:
        refresh, who = exchange(
            connection, code=code, redirect_uri=excel_router._redirect_uri(), verifier=verifier
        )
    except Exception as problem:  # noqa: BLE001 — shown to whoever pressed the button
        return str(problem)[:400]
    teams_account.store(db, connection, refresh_token=refresh, connected_as=who)
    db.commit()
    logger.info("Teams posting account connected as %s", who or "an unnamed account")
    return None


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def forget_account(
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> Response:
    """Stop posting as that account. Picked channels are kept, and say they
    cannot post until an account is signed in again."""
    connection = _registered(db, actor.organization_id)
    who = teams_account.connected_as(connection)
    teams_account.forget(db, connection)
    audit.record(db, actor=actor, action="announcements.account.forgotten", request=request, was=who)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class TeamChoice(BaseModel):
    id: str
    name: str


class ChannelChoice(BaseModel):
    id: str
    name: str
    membership: str


@router.get("/account/teams", response_model=list[TeamChoice])
def pick_team(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[TeamChoice]:
    """The Teams the posting account is in — asked live, one request, only when
    somebody opens the picker."""
    _, token = _token(db, actor.organization_id)
    db.commit()
    try:
        return [TeamChoice(**t) for t in teams_account.joined_teams(token)]
    except teams_account.GraphProblem as problem:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(problem)) from None


@router.get("/account/teams/{team_id}/channels", response_model=list[ChannelChoice])
def pick_channel(
    team_id: str,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[ChannelChoice]:
    _, token = _token(db, actor.organization_id)
    db.commit()
    try:
        return [ChannelChoice(**c) for c in teams_account.channels(token, team_id)]
    except teams_account.GraphProblem as problem:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(problem)) from None

