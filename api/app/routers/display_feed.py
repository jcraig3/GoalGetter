"""What a wall screen plays.

The only endpoint in this product that serves data without a session, so it is
worth being explicit about the boundaries:

  * The token is the *entire* credential. It grants one channel, read-only.
  * It returns board names, ranks, and scores. No email addresses, no user
    ids that address any other endpoint, no goals, no raw facts.
  * Only boards published to the whole organization can appear, enforced by a
    CHECK constraint on `leaderboard` as well as by this query — so a screen
    can never show something its audience could not see by signing in.
  * A revoked token stops working on the next poll, with no cache in between.
"""

from datetime import UTC, datetime, timedelta

from fastapi import Response, APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession, object_session

from app import assets, channels as channel_service, display_previews, events
from app.config import get_settings
from app.net import hidden_by_docker, in_any, proxy_hops, real_client_ip
from app.db import get_db
from app.models import StoredAsset, Channel as ChannelModel
from app.models import Display, Organization
from app.routers.leaderboards import EntryRead

router = APIRouter(prefix="/display", tags=["display"])

# How often a screen may update `last_seen_at`. The column exists so an admin
# can tell a live display from one unplugged months ago; writing on every poll
# would mean a database write every few seconds per screen, forever, to answer
# a question nobody asks more than daily.
SEEN_THROTTLE = timedelta(minutes=5)


class SlideRead(BaseModel):
    """One screen, ready to render.

    A single shape for every kind rather than a union: a wall client should be
    able to loop over slides and switch on `kind`, not learn six response
    shapes. The unused fields cost a few bytes of JSON and save a decoder.
    """

    id: int
    kind: str
    dwell_seconds: int
    title: str
    subtitle: str | None = None

    #: How to draw it, already merged from organization, item, channel and
    #: screen. Sent per slide rather than per channel because two screens in one
    #: rotation can legitimately differ.
    appearance: dict = {}

    entries: list[EntryRead] = []
    total_entrants: int = 0
    entity_type: str | None = None
    unit: str | None = None
    decimal_places: int = 0
    unit_label: str | None = None
    direction: str | None = None
    #: Where a race layout draws the finish line.
    finish_line: Decimal | None = None
    #: "Wed 23 Sep" when the newest number is over a day old (10.6).
    as_of: str | None = None
    #: Last period's top three, for a calendar board with nothing yet (10.1).
    previous: dict | None = None

    current_value: Decimal | None = None
    target_value: Decimal | None = None
    percent: float | None = None
    status: str | None = None
    #: Levels past the target, each with whether it is reached.
    stretch: list[dict] = []

    #: Competition slides. `entries` above carries the standings — a competition
    #: table is a ranked list, and a second field for the same shape would mean
    #: the wall rendering it two ways.
    prize: str | None = None
    ends_at: str | None = None
    state: str | None = None
    final: bool = False

    #: Achievements slides, and the "recent wins" strip under a spotlight.
    achievements: list[dict] = []

    #: Spotlight slides: who, what they have done, and how long they have kept
    #: doing it. See `channels._spotlight`.
    person: dict | None = None
    stats: list[dict] = []
    streak_days: int | None = None

    #: Comparison slides: two to four boards, each shaped like a leaderboard
    #: slide so the wall draws a panel with the component it already has.
    panels: list[dict] = []

    url: str | None = None
    media_kind: str | None = None
    media_digest: str | None = None
    media_start_seconds: int | None = None
    fit: str | None = None
    body: str | None = None


class Channel(BaseModel):
    channel_name: str
    organization_name: str
    slides: list[SlideRead]
    #: When somebody last asked this screen to reload itself.
    #:
    #: The screen remembers the value it started with and reloads when it
    #: changes — see `models/display.py`. Null means nobody ever has, which is
    #: the ordinary case and is why the screen stores whatever it first sees
    #: rather than treating null as "no".
    reload_at: str | None = None
    #: **Night mode, or nothing scheduled** (6.10): show a clock or a dark
    #: screen instead of the slides. `{"mode": "clock" | "dark", "until":
    #: ISO time or null}`. Null is the ordinary case.
    quiet: dict | None = None
    #: The organization's zone, so a clock on the wall tells the office's time
    #: rather than whatever the television was set to.
    time_zone: str = "UTC"
    #: When the screen should come back. Sent by the server so the rotation
    #: rate is an operational setting rather than something baked into a
    #: browser nobody can reach to update.
    refresh_seconds: int = 60
    #: The server's clock, in milliseconds since the epoch.
    #:
    #: **What keeps every screen on a channel in step.** Rotation is worked out
    #: from the time rather than counted from when a screen loaded, so two
    #: screens agree on what should be showing only if they agree on the time
    #: — and a television's own clock is routinely seconds or minutes out. Each
    #: screen sets its clock by this instead.
    server_time: int = 0


def _allowed_here(request: Request, channel: ChannelModel) -> None:
    """Refuse a screen outside the network this channel is restricted to.

    **403 with a reason, not the 404 the token uses.** Everywhere else here a
    refusal is deliberately indistinguishable — missing, revoked and malformed
    tokens all 404, so probing tells you nothing. This one is different on
    purpose: the token is valid and the *location* is wrong, and the person who
    hits it is overwhelmingly an admin who has just plugged a television into
    the wrong network. A silent 404 sends them hunting a broken link that is
    not broken.

    What it concedes is small. Somebody outside with a photographed URL learns
    the link is real — and still cannot use it, which is the entire point of
    the allowlist. Trading that for an error a person can act on is worth it.
    """
    if not channel.allowed_ips:
        return

    settings = get_settings()
    # The channel's own session: the proxy setting lives in the database.
    seen = real_client_ip(request, settings.trusted_proxy_ips, proxy_hops(object_session(channel)))
    if in_any(seen, ",".join(channel.allowed_ips)):
        return

    # **Docker hid the screen's address** (P6-1): every screen arrives as
    # Docker's gateway on Docker Desktop, so the allowlist cannot be checked.
    # Still refused — a list that cannot be checked must not let everybody
    # in — but said so, rather than naming an address nobody recognises.
    if hidden_by_docker(seen):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This channel only allows screens on certain networks, but this server "
                "cannot see screens' addresses, so it cannot check. An administrator can "
                "remove the network list from the channel."
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"This screen is outside the network allowed for this channel. "
            f"It is connecting from {seen or 'an unknown address'}."
        ),
    )


@router.get("/{token}/assets/{digest}")
def display_asset(
    token: str, digest: str, request: Request, db: DbSession = Depends(get_db)
) -> Response:
    """A face, a logo, a background or a walk-up clip, for a screen with no
    session.

    One route for every kind, because a content-addressed store has one way to
    hand bytes back and the content type comes off the row.

    **Through the display's own token, not a second credential.** The token
    already decides which organization a screen may see, and it is already the
    thing a revoked display loses — so a photograph reached this way is revoked
    at the same moment the board is. Minting a separate image token would be one
    more thing to remember to turn off.

    Scoped to that organization like the signed-in route, so a token from one
    tenant cannot confirm what another holds.
    """
    display = _display_for(db, token)
    row = db.scalar(
        select(StoredAsset).where(
            StoredAsset.organization_id == display.organization_id,
            StoredAsset.sha256 == digest,
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    # Range-aware: a television playing a background video asks for one, and
    # Safari refuses to play an MP4 from a server that ignores it. Safe to keep
    # forever either way — the URL is the hash of what it returns.
    return assets.respond(row, request.headers.get("range"))


def _display_for(db: DbSession, token: str) -> Display:
    """Resolve the token, or 404.

    404 for missing, revoked, and malformed alike. A screen cannot act on the
    difference, and distinguishing them would tell whoever is probing whether a
    token was ever real.
    """
    unknown = HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="This display link is not valid."
    )
    if not token:
        raise unknown

    display = db.scalar(select(Display).where(Display.token == token))
    if display is None or display.revoked_at is not None:
        raise unknown
    return display


def _build_channel(
    db: DbSession, display: Display, request: Request | None = None
) -> Channel:
    """Everything a screen should show, in one response."""
    org = db.get(Organization, display.organization_id)
    channel = db.get(ChannelModel, display.channel_id)
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="This display link is not valid."
        )

    if request is not None:
        _allowed_here(request, channel)

    now = datetime.now(UTC)
    quiet = channel_service.quiet(db, org, channel, now=now)
    # Nothing to render while the wall is quiet — the slides would only be
    # thrown away, and the next poll fetches them when it ends.
    slides = [] if quiet is not None else channel_service.build(db, org, channel, now=now)

    # Note that an admin opening the link from their desk counts as the screen
    # being seen — there is no way to tell the two apart, because it is the
    # same URL. "Last seen" therefore means "this link was fetched", which is
    # the honest reading of it.
    now = datetime.now(UTC)
    if display.last_seen_at is None or now - display.last_seen_at > SEEN_THROTTLE:
        display.last_seen_at = now
        db.commit()

    return Channel(
        channel_name=channel.name,
        organization_name=org.name,
        slides=[SlideRead(**vars(slide)) for slide in slides],
        reload_at=display.reload_at.isoformat() if display.reload_at else None,
        quiet=(
            {
                "mode": quiet.mode,
                "until": quiet.until.isoformat() if quiet.until else None,
            }
            if quiet is not None
            else None
        ),
        time_zone=org.timezone,
        # Taken last, as close as possible to the response leaving: the screen
        # assumes it was read halfway through the round trip.
        server_time=int(datetime.now(UTC).timestamp() * 1000),
    )


class SoundReport(BaseModel):
    #: True: the browser held a celebration's sound back and it played muted.
    #: False: something just played with sound.
    blocked: bool


@router.post("/{token}/sound", status_code=status.HTTP_204_NO_CONTENT)
def report_sound(
    token: str, payload: SoundReport, request: Request, db: DbSession = Depends(get_db)
) -> Response:
    """A screen saying whether its browser lets it play sound (Phase 24).

    Written only when it changes, so a wall reporting on every celebration
    costs nothing; the screen's token is the whole credential, as for its feed."""
    display = _display_for(db, token)
    blocked = display.sound_blocked_at is not None
    if payload.blocked != blocked:
        display.sound_blocked_at = datetime.now(UTC) if payload.blocked else None
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{token}", response_model=Channel)
def channel(
    token: str, request: Request, db: DbSession = Depends(get_db)
) -> Channel:
    """The public feed. The token in the path is the entire credential —
    unless the channel narrows *where* it may be used from."""
    display = _display_for(db, token)
    return _build_channel(db, display, request)


class CelebrationRead(BaseModel):
    #: `win:42` or `replay:7`. A screen remembers these, and the same win
    #: arriving twice — once because it happened, again because somebody
    #: pressed replay — has to look like two things or the second is skipped.
    id: str
    title: str
    body: str | None = None
    about_name: str | None = None
    media_url: str | None = None
    media_kind: str | None = None
    media_id: str | None = None
    #: An uploaded clip, by digest. The wall fetches it through its own token.
    media_digest: str | None = None
    media_start_seconds: int | None = None
    media_end_seconds: int | None = None
    hold_seconds: int
    created_at: str
    #: When it takes over every screen on this channel and when it lets go, in
    #: milliseconds since the epoch — the same for all of them.
    starts_at: int
    ends_at: int
    #: What it is for: "Recognition", "Goal hit", an achievement's name.
    occasion: str = ""
    event_key: str = ""
    #: The number it was for, "$500", and their photograph (7.9).
    figure: str | None = None
    photo_digest: str | None = None
    #: Sent to this one screen from an editor (`app/display_previews.py`),
    #: and marked so on the screen: the room should not take it for news.
    preview: bool = False
    #: A previewed slide, drawn full-screen instead of an announcement.
    slide: SlideRead | None = None
    #: An announcement's own screen behind its words, and its sound effect
    #: (Phase 25). See `channels.Celebration`.
    background: dict | None = None
    sound_digest: str | None = None


class Celebrations(BaseModel):
    celebrations: list[CelebrationRead]
    #: The quiet gap between two takeovers, sent by the server for the same
    #: reason `refresh_seconds` is: pacing a wall is an operational setting, not
    #: something baked into a browser nobody can reach to update.
    cooldown_seconds: int
    #: The server's clock — see `Channel.server_time`.
    server_time: int = 0


@router.get("/{token}/celebrations", response_model=Celebrations)
def celebrations(
    token: str, request: Request, db: DbSession = Depends(get_db)
) -> Celebrations:
    """Wins from the last few minutes, for the screen to interrupt itself with.

    Separate from the channel feed on purpose. The rotation is heavy — every
    board, goal and competition on the channel — and a wall has to notice a win
    within seconds of it landing, not within a refresh cycle. Two endpoints means
    this one can be polled often and cheaply.

    Same credential and the same allowlist as the feed itself.
    """
    display = _display_for(db, token)
    channel = db.get(ChannelModel, display.channel_id)
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Display not found."
        )
    _allowed_here(request, channel)

    org = db.get(Organization, channel.organization_id)
    # Previews first: one was sent to this screen on purpose, by somebody
    # standing in front of it, and should win over whatever else is on.
    previews = [
        CelebrationRead(**item)
        for item in display_previews.pending(db, display, datetime.now(UTC))
    ]
    # **Night mode holds real celebrations back** (6.10): a win at two in the
    # morning lighting up an empty office helps nobody, and the window they
    # are offered in has closed by the morning. Previews still show, so
    # somebody setting up after hours sees their work.
    night = channel_service.night_mode(org, channel)
    wins = [] if night is not None else channel_service.celebrations(db, org, channel)
    return Celebrations(
        celebrations=previews + [
            CelebrationRead(
                **{k: v for k, v in vars(item).items() if k != "due"}
            )
            for item in wins
        ],
        cooldown_seconds=events.CELEBRATION_COOLDOWN_SECONDS,
        server_time=int(datetime.now(UTC).timestamp() * 1000),
    )


class _NoActor:
    """Stands in for the signed-in user a wall screen does not have.

    `aggregate` takes an actor to resolve scope from, and a display has none.
    Rather than making `actor` optional everywhere — which would let a real
    endpoint pass None by accident and silently skip scoping — this object
    carries only what the unscoped path reads, and would fail loudly on
    anything else.
    """

    org_role = "display"
    team_id = None
    id = None

    def __init__(self, organization_id: int) -> None:
        self.organization_id = organization_id
