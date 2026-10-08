"""Authoring what plays on a wall.

A channel is a name and an ordered list of screens. Admin only: a channel is
what an entire office looks at all day, and its contents are not a per-person
preference.
"""

import ipaddress
from datetime import UTC, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session as DbSession

from app import (
    audit,
    channels as channel_service,
    display_previews,
    eligibility,
    events,
    media as media_service,
)
from app.appearance import Appearance
from app.db import get_db
from app.models import (
    CelebrationReplay,
    Channel,
    ChannelScreen,
    ChannelScreenBoard,
    Competition,
    Display,
    Goal,
    Leaderboard,
    MetricDefinition,
    Notification,
    Office,
    Organization,
    Team,
    UserAccount,
)
from app.models.channel import DEFAULT_DWELL_SECONDS, SCOPES, SCREEN_KINDS
from app.sessions import require_role
from app.validation import Name

router = APIRouter(prefix="/channels", tags=["channels"])


class ScreenRead(BaseModel):
    id: int
    position: int
    kind: str
    dwell_seconds: int
    leaderboard_id: int | None
    goal_id: int | None
    competition_id: int | None
    #: For a spotlight. Absent alongside a board means "whoever is leading".
    user_id: int | None
    #: For a comparison: the boards it puts side by side, in order.
    leaderboard_ids: list[int] = []
    #: Only what this one screen chose. The last word in the chain.
    appearance: dict = {}
    url: str | None
    #: A video screen's start, and a picture screen's fit (Phase 26).
    media_start_seconds: int | None = None
    fit: str | None = None
    title: str | None
    body: str | None
    #: NULL means it inherits the channel's audience, which is almost always.
    scope_type: str | None
    scope_office_id: int | None
    scope_team_id: int | None
    #: When it plays (6.10): days of the week, 0 is Monday, null every day;
    #: hours in the organization's time, either end open.
    days: list[int] | None = None
    play_from: time | None = None
    play_until: time | None = None
    #: How many times it comes round in a cycle.
    weight: int = 1
    #: What this screen is, in words, for the editor's list. Resolved here so
    #: the client does not have to hold every board and goal to name a row.
    label: str
    #: True when the board or goal it shows is archived, so it is not playing
    #: (P3-2) — the editor says so, with Restore, instead of "Nothing to show".
    archived: bool = False
    #: Who it ends up being about, inherited or overridden. Shown in the editor
    #: so an admin can see the effect without working it out.
    audience_label: str


class ChannelRead(BaseModel):
    id: int
    name: str
    scope_type: str
    scope_office_id: int | None
    scope_team_id: int | None
    audience_label: str
    #: Empty means anywhere. CIDRs or bare addresses.
    allowed_ips: list[str]
    #: Only what this channel itself chose; absent keys inherit from the
    #: organization. See `app/appearance.py`.
    appearance: dict = {}
    #: Night mode (6.10): `off`, `clock` or `dark`, and when.
    quiet_mode: str = "off"
    quiet_from: time | None = None
    quiet_until: time | None = None
    quiet_weekends: bool = False
    screens: list[ScreenRead]
    #: How many televisions are pointed at this. Editing a channel three
    #: screens are showing is a different act from editing an empty one.
    display_count: int


class ChannelWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name(120)
    scope_type: str = "organization"
    scope_office_id: int | None = None
    scope_team_id: int | None = None
    #: Where this channel may be watched from. Empty means anywhere, which is
    #: the only safe default — a deployment behind a NAT nobody wrote down
    #: would otherwise blank every screen the moment somebody saved a channel.
    allowed_ips: list[str] = []

    #: Night mode (6.10). Out of hours the wall shows a clock that drifts, or
    #: a dark screen, and holds real celebrations back until morning.
    quiet_mode: Literal["off", "clock", "dark"] = "off"
    quiet_from: time | None = None
    quiet_until: time | None = None
    quiet_weekends: bool = False

    #: **Replaces rather than merges**, like every other layer — absence would
    #: otherwise mean "leave it alone", which is the opposite of what a reset
    #: needs.
    appearance: Appearance | None = None


class ScreenWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    #: Up to an hour: a video screen plays for as long as it is told to.
    dwell_seconds: int = Field(DEFAULT_DWELL_SECONDS, ge=5, le=3600)
    leaderboard_id: int | None = None
    goal_id: int | None = None
    competition_id: int | None = None
    user_id: int | None = None
    #: For a comparison. Two to four, in the order they should be drawn.
    leaderboard_ids: list[int] = []
    appearance: Appearance | None = None
    #: A picture screen: a link to a picture or GIF, or `image:<sha256>` from
    #: the library. A video screen: a YouTube link, or `video:<sha256>`.
    url: str | None = None
    #: A video screen starts this many seconds in (Phase 26).
    media_start_seconds: int | None = Field(None, ge=0, le=86_400)
    #: A picture screen: `cover` (fills the screen) or `contain` (all of it).
    fit: Literal["cover", "contain"] | None = None
    title: str | None = None
    body: str | None = None
    #: NULL means inherit the channel's audience.
    scope_type: str | None = None
    scope_office_id: int | None = None
    scope_team_id: int | None = None
    #: When it plays (6.10). Days are 0 (Monday) to 6; empty or null means
    #: every day. Either hour may be left open; from 22:00 until 02:00 crosses
    #: midnight.
    days: list[int] | None = None
    play_from: time | None = None
    play_until: time | None = None
    weight: int = Field(1, ge=1, le=4)


class Reorder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The whole running order, every time.
    #:
    #: Drag-and-drop knows the final arrangement, so sending it wholesale means
    #: there is never a half-applied shuffle to reason about — and two people
    #: reordering at once end with one of the two orders rather than an
    #: interleaving of both.
    screen_ids: list[int]


@router.get("", response_model=list[ChannelRead])
def list_channels(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[ChannelRead]:
    rows = db.scalars(
        select(Channel)
        .where(Channel.organization_id == actor.organization_id)
        .order_by(Channel.name)
    ).all()
    return [_to_read(db, channel) for channel in rows]


@router.post("", response_model=ChannelRead, status_code=status.HTTP_201_CREATED)
def create_channel(
    payload: ChannelWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ChannelRead:
    channel = Channel(organization_id=actor.organization_id)
    _apply_scope(db, actor, channel, payload)
    db.add(channel)
    audit.record(
        db, actor=actor, action="channel.created", request=request, name=payload.name
    )
    db.commit()
    return _to_read(db, channel)


@router.patch("/{channel_id}", response_model=ChannelRead)
def rename_channel(
    channel_id: int,
    payload: ChannelWrite,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ChannelRead:
    channel = _owned(db, actor, channel_id)
    _apply_scope(db, actor, channel, payload)
    db.commit()
    return _to_read(db, channel)


@router.delete("/{channel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel(
    channel_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> None:
    """Gone, with its screens.

    There is no archive for channels — see the note on the model. Deleting is
    the only retirement, so it is guarded rather than merely confirmed:
    **refused while a television still points at it**, because the foreign key
    cascades and this would take the *display rows* with it. A link somebody
    already opened on a TV would stop working and leave no record it had ever
    existed. A dialog is not enough for something whose consequences are three
    rooms away from the person clicking.
    """
    channel = _owned(db, actor, channel_id)

    attached = db.scalar(
        select(func.count())
        .select_from(Display)
        .where(Display.channel_id == channel.id, Display.revoked_at.is_(None))
    )
    if attached:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"{attached} TV{'s' if attached > 1 else ''} still "
                f"{'play' if attached > 1 else 'plays'} this channel. Point "
                f"{'them' if attached > 1 else 'it'} somewhere else first."
            ),
        )

    audit.record(
        db, actor=actor, action="channel.deleted", request=request, name=channel.name
    )
    db.delete(channel)
    db.commit()


#: A contest's state as the picker says it (review §9): "running", not "active".
CONTEST_STATE_WORDS = {"scheduled": "not started", "active": "running", "ended": "ended", "closed": "closed"}


class EligibleItem(BaseModel):
    id: int
    name: str
    #: Where it belongs, in words, so the picker can say why something is on
    #: the list — "Everyone" or "Phoenix" beside a board is the difference
    #: between a filtered list and one that looks arbitrary.
    belongs_to: str
    #: A competition's state, as data — the starter templates (6.4) take the
    #: running ones, and parsing it back out of `name` would be reading prose.
    state: str | None = None


class Eligible(BaseModel):
    leaderboards: list[EligibleItem]
    goals: list[EligibleItem]
    competitions: list[EligibleItem]
    #: Who this wall may spotlight. Same rule as everything else here: a
    #: Phoenix agent does not belong on Dallas's screen.
    people: list[EligibleItem]


class Using(BaseModel):
    channel_id: int
    channel_name: str
    #: Slides on that channel that would go: its own, plus comparisons it
    #: is a panel of.
    slides: int


@router.get("/using", response_model=list[Using])
def channels_using(
    kind: Literal["leaderboard", "goal", "competition"],
    id: int,
    actor: UserAccount = Depends(require_role("admin", "manager")),
    db: DbSession = Depends(get_db),
) -> list[Using]:
    """Which channels a board, goal or contest is on, for its delete confirm (8.6).

    Deleting one takes its slides with it — the foreign keys cascade — and the
    TVs simply stop showing it. Said before the confirm instead: "Removes 1
    slide from Sales floor".
    """
    column = {
        "leaderboard": ChannelScreen.leaderboard_id,
        "goal": ChannelScreen.goal_id,
        "competition": ChannelScreen.competition_id,
    }[kind]
    screen_ids = set(
        db.scalars(
            select(ChannelScreen.id)
            .join(Channel, Channel.id == ChannelScreen.channel_id)
            .where(Channel.organization_id == actor.organization_id, column == id)
        ).all()
    )
    if kind == "leaderboard":
        # A comparison loses a panel rather than going; still worth saying.
        screen_ids |= set(
            db.scalars(
                select(ChannelScreenBoard.channel_screen_id).where(
                    ChannelScreenBoard.leaderboard_id == id
                )
            ).all()
        )
    if not screen_ids:
        return []
    counts: dict[int, int] = {}
    for channel_id in db.scalars(
        select(ChannelScreen.channel_id).where(ChannelScreen.id.in_(screen_ids))
    ).all():
        counts[channel_id] = counts.get(channel_id, 0) + 1
    channels = db.scalars(
        select(Channel)
        .where(Channel.id.in_(counts), Channel.organization_id == actor.organization_id)
        .order_by(Channel.name)
    ).all()
    return [Using(channel_id=c.id, channel_name=c.name, slides=counts[c.id]) for c in channels]


@router.get("/{channel_id}/eligible", response_model=Eligible)
def list_eligible(
    channel_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> Eligible:
    """What may go on this channel.

    Served rather than filtered in the client so that the picker and the
    validation are the same rule. Two copies would drift, and the version of
    that nobody notices is the quiet one: a picker that omits something the
    server would have accepted.
    """
    channel = _owned(db, actor, channel_id)
    return _eligible(db, actor, eligibility.channel_where(channel))


@router.get("/eligible", response_model=Eligible)
def list_eligible_anywhere(
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> Eligible:
    """What a new channel for everyone may show — before it exists.

    For a template's confirm step (7.9): it says which slides it will add
    before anything is made, so choosing a template twice no longer leaves two
    "Sales floor"s behind.
    """
    return _eligible(db, actor, eligibility.EVERYWHERE)


def _eligible(db: DbSession, actor: UserAccount, wall: eligibility.Where) -> Eligible:
    boards = [
        EligibleItem(
            id=b.id,
            name=b.name,
            belongs_to=_where_label(db, eligibility.board_where(b)),
        )
        for b in db.scalars(
            select(Leaderboard).where(
                Leaderboard.organization_id == actor.organization_id,
                Leaderboard.archived_at.is_(None),
                # Only a board published to everyone can go on a wall at all.
                Leaderboard.visibility == "org",
            ).order_by(Leaderboard.name)
        ).all()
        if eligibility.fits(wall, eligibility.board_where(b))
    ]

    goals = []
    for goal in db.scalars(
        select(Goal).where(
            Goal.organization_id == actor.organization_id,
            Goal.archived_at.is_(None),
        ).order_by(Goal.id.desc())
    ).all():
        where = eligibility.goal_where(db, goal)
        if not eligibility.fits(wall, where):
            continue
        metric = db.get(MetricDefinition, goal.metric_definition_id)
        title = goal.name or (metric.name if metric else "Goal")
        goals.append(
            EligibleItem(
                id=goal.id,
                # Whose, always. Three people with a "Calls Made" goal are
                # three identical options otherwise.
                name=f"{title} — {_goal_subject(db, goal)}",
                belongs_to=_where_label(db, where),
            )
        )

    contests = []
    for competition in db.scalars(
        select(Competition).where(
            Competition.organization_id == actor.organization_id,
            # Same set the renderer will show. A draft nobody has published and a
            # cancelled contest with no result are both a slide saying nothing, so
            # offering them would be offering a blank.
            Competition.state.in_(channel_service.WALL_STATES),
        ).order_by(Competition.starts_at.desc())
    ).all():
        if not eligibility.competition_fits(db, wall, competition):
            continue
        contests.append(
            EligibleItem(
                id=competition.id,
                # The state matters here in a way it does not for a board: a
                # scheduled contest shows a table of zeros until it starts, and an
                # admin choosing between three sprints needs to know which is
                # which.
                name=f"{competition.name} · {CONTEST_STATE_WORDS.get(competition.state, competition.state)}",
                # Names the offices involved rather than "Everyone": for a
                # contest, "Phoenix + Dallas" is the actual answer and the thing
                # that explains why it is on this list and not another's.
                belongs_to=eligibility.competition_places(db, competition),
                state=competition.state,
            )
        )

    people = []
    for person in db.scalars(
        select(UserAccount).where(
            UserAccount.organization_id == actor.organization_id,
            UserAccount.hidden_at.is_(None),
        ).order_by(UserAccount.full_name)
    ).all():
        where = eligibility.person_where(db, person)
        if not eligibility.fits(wall, where):
            continue
        people.append(
            EligibleItem(
                id=person.id,
                name=person.full_name,
                belongs_to=_where_label(db, where),
            )
        )

    return Eligible(
        leaderboards=boards, goals=goals, competitions=contests, people=people
    )


def _where_label(db: DbSession, where: eligibility.Where) -> str:
    if where.office_id is not None:
        office = db.get(Office, where.office_id)
        return office.name if office else "Deleted office"
    if where.team_id is not None:
        team = db.get(Team, where.team_id)
        return team.name if team else "Deleted team"
    return "Everyone"


@router.post(
    "/{channel_id}/screens",
    response_model=ChannelRead,
    status_code=status.HTTP_201_CREATED,
)
def add_screen(
    channel_id: int,
    payload: ScreenWrite,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ChannelRead:
    channel = _owned(db, actor, channel_id)

    last = db.scalar(
        select(func.max(ChannelScreen.position)).where(
            ChannelScreen.channel_id == channel.id
        )
    )
    screen = ChannelScreen(
        channel_id=channel.id, position=(last + 1) if last is not None else 0
    )
    _apply(db, actor, screen, payload)
    db.add(screen)
    db.commit()
    return _to_read(db, channel)


@router.post("/{channel_id}/screens/preview")
def preview_screen(
    channel_id: int,
    payload: ScreenWrite,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> dict:
    """A slide as this channel's walls would draw it, before it is saved (5j).

    **Added for real, inside a savepoint that is always rolled back.** The
    screen goes through `_apply` (every check saving makes, with the same
    refusals) and through `channels.slide_for` (the same renderer the TVs
    use), so the preview has real numbers and cannot disagree with the wall.
    A comparison writes its panels as rows, which is why this is a savepoint
    rather than an object kept out of the session.

    Nothing survives the request: the savepoint is rolled back whatever
    happens, and nothing here commits.
    """
    shown = _preview_slide(db, actor, _owned(db, actor, channel_id), payload)
    if shown is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nothing to show for this slide yet.",
        )
    return shown


@router.post("/{channel_id}/screens/preview/tv/{display_id}", status_code=status.HTTP_202_ACCEPTED)
def preview_screen_on_tv(
    channel_id: int,
    display_id: int,
    payload: ScreenWrite,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> dict:
    """The same unsaved slide, sent to one television for thirty seconds.

    See `app/display_previews.py`. Built here, by the wall's own renderer, and
    stored built: the screen shows exactly what the editor's preview showed.
    """
    display = display_previews.target(db, actor, display_id)
    shown = _preview_slide(db, actor, _owned(db, actor, channel_id), payload)
    if shown is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nothing to show for this slide yet.",
        )
    return display_previews.send(
        db, actor, display, request, slide=shown,
        hold_seconds=display_previews.SLIDE_SECONDS,
    )


@router.get("/{channel_id}/slides")
def rendered_slides(
    channel_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> list[dict]:
    """Every slide on this channel, drawn as its TVs draw it (8.5).

    For the editor's thumbnails and its "Play rotation". The same renderer the
    walls use, so a thumbnail cannot disagree with the screen; a slide with
    nothing to show yet comes back as null, as it would be skipped on a TV.
    """
    from app.routers.display_feed import SlideRead

    channel = _owned(db, actor, channel_id)
    org = db.get(Organization, actor.organization_id)
    out = []
    for screen in db.scalars(
        select(ChannelScreen)
        .where(ChannelScreen.channel_id == channel.id)
        .order_by(ChannelScreen.position)
    ).all():
        slide = channel_service.slide_for(db, org, channel, screen)
        out.append(
            {
                "screen_id": screen.id,
                "slide": SlideRead(**vars(slide)).model_dump(mode="json") if slide else None,
            }
        )
    return out


def _preview_slide(
    db: DbSession, actor: UserAccount, channel: Channel, payload: ScreenWrite
) -> dict | None:
    """An unsaved screen, rendered as the wall would and then rolled back."""
    from app.routers.display_feed import SlideRead

    org = db.get(Organization, actor.organization_id)
    savepoint = db.begin_nested()
    try:
        last = db.scalar(
            select(func.max(ChannelScreen.position)).where(
                ChannelScreen.channel_id == channel.id
            )
        )
        screen = ChannelScreen(
            channel_id=channel.id, position=(last + 1) if last is not None else 0
        )
        _apply(db, actor, screen, payload)
        db.add(screen)
        db.flush()
        slide = channel_service.slide_for(db, org, channel, screen)
        shown = SlideRead(**vars(slide)).model_dump(mode="json") if slide else None
        if shown is not None:
            # **What it would look like with nothing of its own, and where the
            # background comes from** (Phase 26) — so the editor shows "From
            # the leaderboard Sales floor" instead of an empty field.
            look, source = channel_service.inherited_look(db, org, channel, screen)
            shown["inherited"] = look
            shown["background_from"] = source
    finally:
        savepoint.rollback()
    return shown


@router.patch("/{channel_id}/screens/{screen_id}", response_model=ChannelRead)
def edit_screen(
    channel_id: int,
    screen_id: int,
    payload: ScreenWrite,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ChannelRead:
    channel = _owned(db, actor, channel_id)
    screen = _owned_screen(db, channel, screen_id)
    _apply(db, actor, screen, payload)
    db.commit()
    return _to_read(db, channel)


@router.delete("/{channel_id}/screens/{screen_id}", response_model=ChannelRead)
def remove_screen(
    channel_id: int,
    screen_id: int,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ChannelRead:
    channel = _owned(db, actor, channel_id)
    db.delete(_owned_screen(db, channel, screen_id))
    db.commit()
    return _to_read(db, channel)


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Which win to play again.
    notification_id: int


@router.post("/{channel_id}/replay", status_code=status.HTTP_202_ACCEPTED)
def replay(
    channel_id: int,
    payload: ReplayRequest,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> dict[str, str]:
    """Put a celebration back on this channel's screens.

    **202, not 201.** Nothing is guaranteed to have happened: a television that
    is switched off misses it, and the honest answer is "asked for", not
    "done".

    For the manager whose team's best moment of the week happened while the
    room was in a meeting, and whose only record of it is a line in a feed
    somebody has to be told to go and read.
    """
    channel = _owned(db, actor, channel_id)

    win = db.get(Notification, payload.notification_id)
    if win is None or win.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Win not found."
        )
    # The same rule the feed itself obeys. A wall is read by whoever walks
    # past, so "you are behind on your goal" must not reach one — least of all
    # because somebody pressed a button next to it.
    if not events.is_public(win.event_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "That one is private. Only wins that already appear on a wall "
                "can be played on one."
            ),
        )

    # Swept here rather than by a job: the table is only ever read for the last
    # two minutes, so anything older is dead weight and this is the one moment
    # somebody is already writing to it.
    db.execute(
        delete(CelebrationReplay).where(
            CelebrationReplay.organization_id == actor.organization_id,
            CelebrationReplay.created_at
            < datetime.now(UTC) - timedelta(seconds=events.REPLAY_WINDOW_SECONDS),
        )
    )

    db.add(
        CelebrationReplay(
            organization_id=actor.organization_id,
            channel_id=channel.id,
            notification_id=payload.notification_id,
            requested_by_user_id=actor.id,
            created_at=datetime.now(UTC),
        )
    )
    audit.record(
        db,
        actor=actor,
        action="channel.replayed",
        request=request,
        name=channel.name,
    )
    db.commit()
    return {"status": "queued"}


@router.post(
    "/{channel_id}/duplicate",
    response_model=ChannelRead,
    status_code=status.HTTP_201_CREATED,
)
def duplicate_channel(
    channel_id: int,
    request: Request,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ChannelRead:
    """Copy a channel and everything on it.

    **The second wall is almost the first one.** A floor with two televisions
    wants the same rotation with one board swapped, and building it screen by
    screen is a dozen forms to reach a difference of one.

    **The copy is a draft of its own, not a link.** Nothing about it tracks the
    original: editing one afterwards leaves the other alone, which is the whole
    reason somebody duplicated rather than pointed a second display at the same
    channel.

    **No displays come with it.** A television plays one channel, and a copy
    that arrived already on a wall would put an untouched duplicate in front of
    an office before anybody had changed the thing they copied it to change.
    """
    original = _owned(db, actor, channel_id)

    copy = Channel(
        organization_id=actor.organization_id,
        name=_copy_name(db, actor.organization_id, original.name),
        scope_type=original.scope_type,
        scope_office_id=original.scope_office_id,
        scope_team_id=original.scope_team_id,
        allowed_ips=list(original.allowed_ips or []),
        appearance=dict(original.appearance or {}),
        quiet_mode=original.quiet_mode,
        quiet_from=original.quiet_from,
        quiet_until=original.quiet_until,
        quiet_weekends=original.quiet_weekends,
    )
    db.add(copy)
    db.flush()

    screens = db.scalars(
        select(ChannelScreen)
        .where(ChannelScreen.channel_id == original.id)
        .order_by(ChannelScreen.position, ChannelScreen.id)
    ).all()

    for screen in screens:
        made = ChannelScreen(
            channel_id=copy.id,
            position=screen.position,
            kind=screen.kind,
            dwell_seconds=screen.dwell_seconds,
            appearance=dict(screen.appearance or {}),
            leaderboard_id=screen.leaderboard_id,
            goal_id=screen.goal_id,
            competition_id=screen.competition_id,
            user_id=screen.user_id,
            url=screen.url,
            media_start_seconds=screen.media_start_seconds,
            fit=screen.fit,
            title=screen.title,
            body=screen.body,
            scope_type=screen.scope_type,
            scope_office_id=screen.scope_office_id,
            scope_team_id=screen.scope_team_id,
            days=list(screen.days) if screen.days is not None else None,
            play_from=screen.play_from,
            play_until=screen.play_until,
            weight=screen.weight,
        )
        db.add(made)
        db.flush()

        # A comparison keeps its panels, in order. They live in their own table,
        # so nothing above would have carried them.
        for panel in db.scalars(
            select(ChannelScreenBoard)
            .where(ChannelScreenBoard.channel_screen_id == screen.id)
            .order_by(ChannelScreenBoard.position, ChannelScreenBoard.id)
        ).all():
            db.add(
                ChannelScreenBoard(
                    channel_screen_id=made.id,
                    leaderboard_id=panel.leaderboard_id,
                    position=panel.position,
                )
            )

    audit.record(
        db,
        actor=actor,
        action="channel.duplicated",
        request=request,
        name=copy.name,
        copied_from=original.name,
    )
    db.commit()
    return _to_read(db, copy)


def _copy_name(db: DbSession, organization_id: int, name: str) -> str:
    """"Phoenix wall (copy)", and then "(copy 2)".

    Named rather than numbered from the start, because the first copy is
    usually the only one and "Phoenix wall (copy 1)" reads like there are
    others. Truncated to the column width, since the suffix can push a
    long name past it.
    """
    taken = set(
        db.scalars(
            select(Channel.name).where(Channel.organization_id == organization_id)
        ).all()
    )
    stem = name[:100]
    for attempt in range(1, 50):
        suffix = " (copy)" if attempt == 1 else f" (copy {attempt})"
        candidate = f"{stem}{suffix}"
        if candidate not in taken:
            return candidate
    return f"{stem} (copy)"


@router.post("/{channel_id}/order", response_model=ChannelRead)
def reorder(
    channel_id: int,
    payload: Reorder,
    actor: UserAccount = Depends(require_role("admin")),
    db: DbSession = Depends(get_db),
) -> ChannelRead:
    """Rewrite the running order wholesale.

    Ids that are not on this channel are ignored rather than rejected, and any
    screen the client did not mention keeps its place at the end — a stale
    editor tab must not be able to delete a screen by omitting it.
    """
    channel = _owned(db, actor, channel_id)
    screens = {
        screen.id: screen
        for screen in db.scalars(
            select(ChannelScreen).where(ChannelScreen.channel_id == channel.id)
        ).all()
    }

    position = 0
    for screen_id in payload.screen_ids:
        screen = screens.pop(screen_id, None)
        if screen is not None:
            screen.position = position
            position += 1
    for screen in sorted(screens.values(), key=lambda s: s.position):
        screen.position = position
        position += 1

    db.commit()
    return _to_read(db, channel)


def _resolve_scope(
    db: DbSession, actor: UserAccount, scope_type: str | None, office_id, team_id
) -> tuple[str | None, int | None, int | None]:
    """Validate an audience, or raise. `None` means inherit."""
    if scope_type is None:
        return None, None, None
    if scope_type not in SCOPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown audience."
        )

    if scope_type == "office":
        office = db.get(Office, office_id or 0)
        if office is None or office.organization_id != actor.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Office not found."
            )
        return "office", office.id, None

    if scope_type == "team":
        team = db.get(Team, team_id or 0)
        if team is None or team.organization_id != actor.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
            )
        return "team", None, team.id

    return "organization", None, None


def _apply_scope(
    db: DbSession, actor: UserAccount, channel: Channel, payload: ChannelWrite
) -> None:
    kind, office_id, team_id = _resolve_scope(
        db, actor, payload.scope_type, payload.scope_office_id, payload.scope_team_id
    )
    channel.name = payload.name
    channel.scope_type = kind or "organization"
    channel.scope_office_id = office_id
    channel.scope_team_id = team_id
    channel.allowed_ips = _clean_allowlist(payload.allowed_ips)
    _apply_quiet(channel, payload)
    # `exclude_none` keeps the row sparse: a field nobody set stays absent,
    # which is what "inherit" looks like on disk.
    channel.appearance = (payload.appearance or Appearance()).model_dump(
        exclude_none=True
    )


def _apply_quiet(channel: Channel, payload: ChannelWrite) -> None:
    """Night mode, refused when it could never come on or never go off."""
    start, end = payload.quiet_from, payload.quiet_until
    if payload.quiet_mode != "off":
        if (start is None) != (end is None):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Night mode needs both a start and an end time.",
            )
        if start is None and not payload.quiet_weekends:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Night mode needs hours, or weekends, to come on.",
            )
        if start is not None and start == end:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Night mode cannot start and end at the same time.",
            )
    channel.quiet_mode = payload.quiet_mode
    channel.quiet_from = start
    channel.quiet_until = end
    channel.quiet_weekends = payload.quiet_weekends


def _apply_schedule(screen: ChannelScreen, payload: ScreenWrite) -> None:
    """When a slide plays. Every day is stored as NULL, so "all seven
    ticked" and "never touched" are the same row."""
    days = sorted(set(payload.days or []))
    if any(d < 0 or d > 6 for d in days):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Days run from 0 (Monday) to 6 (Sunday).",
        )
    if payload.days is not None and not days:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Choose at least one day for this slide to play.",
        )
    if (
        payload.play_from is not None
        and payload.play_from == payload.play_until
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A slide cannot start and stop playing at the same time.",
        )
    screen.days = None if len(days) in (0, 7) else days
    screen.play_from = payload.play_from
    screen.play_until = payload.play_until
    screen.weight = payload.weight


def _clean_allowlist(entries: list[str]) -> list[str]:
    """Validate every entry, or refuse the lot.

    Refusing rather than dropping the bad ones, unlike the trusted-proxy
    setting: that is configuration read at boot where a typo must not stop the
    application, and this is somebody typing into a form where a silently
    ignored entry means a screen they think is protected is not.
    """
    cleaned = []
    for raw in entries:
        entry = raw.strip()
        if not entry:
            continue
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"“{entry}” is not an address or range. Use something "
                    "like 203.0.113.4 or 203.0.113.0/24."
                ),
            ) from None
        cleaned.append(entry)
    return cleaned


def _audience_label(db: DbSession, scope_type: str | None, office_id, team_id) -> str:
    if scope_type == "office":
        office = db.get(Office, office_id) if office_id else None
        return office.name if office else "Deleted office"
    if scope_type == "team":
        team = db.get(Team, team_id) if team_id else None
        return team.name if team else "Deleted team"
    return "Everyone"


def _must_competition_fit(
    db: DbSession,
    screen: ChannelScreen,
    override_kind: str | None,
    override_office: int | None,
    override_team: int | None,
    competition: Competition,
) -> None:
    """The competition version of `_must_fit`.

    Its own function because a competition belongs to a *set* of offices and
    `_must_fit` compares one place against one place. Same job, same moment, same
    reason — say it while the screen is being authored rather than leaving an
    admin to wonder why the rotation skips it.
    """
    if override_kind is not None:
        wall = eligibility.Where(office_id=override_office, team_id=override_team)
    else:
        channel = db.get(Channel, screen.channel_id)
        wall = eligibility.channel_where(channel) if channel else eligibility.EVERYWHERE

    if eligibility.competition_fits(db, wall, competition):
        return

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "This competition's entrants are in "
            f"{eligibility.competition_places(db, competition, picker=False)}. "
            "A wall can only show a contest one of its own people is in."
        ),
    )


def _must_fit(
    db: DbSession,
    screen: ChannelScreen,
    override_kind: str | None,
    override_office: int | None,
    override_team: int | None,
    thing: eligibility.Where,
    noun: str,
) -> None:
    """Refuse a screen whose subject belongs to a different office or team.

    Said when the screen is authored rather than when it renders, because
    "nothing shows up and I do not know why" is the worst possible way to
    learn this — and for a goal the failure is worse than nothing: it shows
    the wrong office's numbers.
    """
    if override_kind is not None:
        wall = eligibility.Where(office_id=override_office, team_id=override_team)
    else:
        channel = db.get(Channel, screen.channel_id)
        wall = eligibility.channel_where(channel) if channel else eligibility.EVERYWHERE

    if eligibility.fits(wall, thing):
        return

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            f"That {noun} belongs to a different office or team from this "
            "channel, so it does not belong on this wall. Change the channel's "
            "audience, or give this screen its own."
        ),
    )


def _channel_office(db: DbSession, screen: ChannelScreen) -> int | None:
    """The office a screen inherits, when it has no override of its own."""
    channel = db.get(Channel, screen.channel_id)
    return channel.scope_office_id if channel else None


def _owned(db: DbSession, actor: UserAccount, channel_id: int) -> Channel:
    channel = db.get(Channel, channel_id)
    if channel is None or channel.organization_id != actor.organization_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found."
        )
    return channel


def _owned_screen(db: DbSession, channel: Channel, screen_id: int) -> ChannelScreen:
    screen = db.get(ChannelScreen, screen_id)
    if screen is None or screen.channel_id != channel.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Screen not found."
        )
    return screen


def _apply(
    db: DbSession, actor: UserAccount, screen: ChannelScreen, payload: ScreenWrite
) -> None:
    if payload.kind not in SCREEN_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown screen kind.",
        )

    # **Before anything on the row is touched.** This statement autoflushes,
    # and a half-edited screen — the new kind set, its payload not yet — fails
    # the CHECK on the way out. Clearing while the row is still consistent
    # costs nothing and removes the ordering trap entirely.
    if screen.id is not None:
        db.execute(
            delete(ChannelScreenBoard).where(
                ChannelScreenBoard.channel_screen_id == screen.id
            )
        )

    # **Nothing is written out while this row is half-edited.**
    #
    # The clearing below leaves the screen briefly in a state its own CHECK
    # forbids — a leaderboard screen with no board — and every `db.get` in the
    # branches that follow is an autoflush waiting to write it. That was
    # latent for as long as a no-op edit left the row clean; adding a field
    # that is always assigned made every edit dirty and turned it into a 500.
    #
    # Suppressing the flush is the fix rather than reordering the assignments,
    # because the next person to add a lookup here should not have to know
    # about it.
    with db.no_autoflush:
        _apply_payload(db, actor, screen, payload)


def _apply_payload(
    db: DbSession, actor: UserAccount, screen: ChannelScreen, payload: ScreenWrite
) -> None:
    """Everything that mutates the row, with no flush able to interrupt it."""
    # Cleared first, then set. Editing a leaderboard screen into a message must
    # not leave the board id behind — the CHECK would allow it and the label
    # would go on naming a board nobody is showing.
    kind, office_id, team_id = _resolve_scope(
        db, actor, payload.scope_type, payload.scope_office_id, payload.scope_team_id
    )
    screen.scope_type = kind
    screen.scope_office_id = office_id
    screen.scope_team_id = team_id

    screen.kind = payload.kind
    screen.dwell_seconds = payload.dwell_seconds
    _apply_schedule(screen, payload)
    screen.appearance = (payload.appearance or Appearance()).model_dump(
        exclude_none=True
    )
    screen.leaderboard_id = None
    screen.goal_id = None
    screen.competition_id = None
    screen.user_id = None
    screen.url = None
    screen.media_start_seconds = None
    screen.fit = None
    screen.title = payload.title
    screen.body = None

    if payload.kind == "leaderboard":
        board = db.get(Leaderboard, payload.leaderboard_id or 0)
        if board is None or board.organization_id != actor.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Board not found."
            )
        # The safety property from Phase 1, enforced where it is authored so an
        # admin is told now rather than finding a blank slide on a wall later.
        # The renderer checks again: two guards cost nothing, and a wall has no
        # audience control at all.
        if board.visibility != "org":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Only a board published to everyone can go on a wall — "
                    "anyone walking past can read it."
                ),
            )
        _must_fit(
            db, screen, kind, office_id, team_id,
            eligibility.board_where(board), "board",
        )
        screen.leaderboard_id = board.id

    elif payload.kind == "goal":
        goal = db.get(Goal, payload.goal_id or 0)
        if goal is None or goal.organization_id != actor.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found."
            )
        # The hole this closes: a goal names its own subject, so the
        # audience filter has nothing to narrow — a Dallas agent's goal on
        # a Phoenix channel would render Dallas numbers on a Phoenix wall.
        _must_fit(
            db, screen, kind, office_id, team_id,
            eligibility.goal_where(db, goal), "goal",
        )
        screen.goal_id = goal.id

    elif payload.kind == "competition":
        competition = db.get(Competition, payload.competition_id or 0)
        if (
            competition is None
            or competition.organization_id != actor.organization_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Competition not found."
            )
        if competition.state not in channel_service.WALL_STATES:
            # A draft is a plan nobody has published; a cancelled contest has no
            # result and no future. Both would be a slide saying nothing, and
            # refusing here is how an admin hears about it rather than watching a
            # rotation skip past.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"A {competition.state} competition has nothing to show. "
                    "Publish it first."
                    if competition.state == "draft"
                    else "A cancelled competition has no result to show."
                ),
            )
        # Same hole as a goal: a competition names its own entrants, so the
        # audience filter has nothing to narrow. A Phoenix-only contest on
        # Dallas's wall is Phoenix's numbers in front of Dallas.
        _must_competition_fit(db, screen, kind, office_id, team_id, competition)
        screen.competition_id = competition.id

    elif payload.kind in ("image", "video"):
        screen.url = _screen_media(db, actor, payload.kind, payload.url or "")
        if payload.kind == "video":
            screen.media_start_seconds = payload.media_start_seconds or None
        else:
            screen.fit = payload.fit

    elif payload.kind == "spotlight":
        _apply_spotlight(db, actor, screen, payload, kind, office_id, team_id)

    elif payload.kind == "comparison":
        _apply_comparison(db, actor, screen, payload, kind, office_id, team_id)

    elif payload.kind == "message":
        if not payload.title:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A message needs something to say.",
            )
        screen.body = payload.body


def _screen_media(db: DbSession, actor: UserAccount, kind: str, url: str) -> str:
    """What a picture or video screen shows (Phase 26): from the library or a
    link, and the right sort for the screen — a picture or GIF for a picture
    screen, an uploaded video or YouTube for a video screen."""
    url = url.strip()
    wanted = media_service.KIND_IMAGE if kind == "image" else media_service.KIND_VIDEO
    try:
        if media_service.asset_digest(url) is not None:
            return media_service.stored_ref(db, actor.organization_id, url, (wanted,))
        clip = media_service.parse(url)
    except media_service.MediaError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
    if kind == "image" and clip.kind != media_service.KIND_IMAGE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That's a video: choose the Video kind for it.",
        )
    if kind == "video" and clip.kind != media_service.KIND_YOUTUBE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That's a picture: choose the Picture kind for it.",
        )
    return clip.url


def _apply_spotlight(
    db: DbSession,
    actor: UserAccount,
    screen: ChannelScreen,
    payload: ScreenWrite,
    kind: str | None,
    office_id: int | None,
    team_id: int | None,
) -> None:
    """Validate a spotlight: a person, a board, or both.

    Its own function because it is the only screen with two optional payloads
    and a rule about the pair. Folding it into `_apply` would put a second
    shape of validation inside a chain of single-payload ones.
    """
    if payload.user_id is None and payload.leaderboard_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "A spotlight needs somebody to be about — either a person, or "
                "a board to take the leader of."
            ),
        )

    if payload.leaderboard_id is not None:
        board = db.get(Leaderboard, payload.leaderboard_id)
        if board is None or board.organization_id != actor.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Board not found."
            )
        if board.visibility != "org":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Only a board published to everyone can go on a wall — "
                    "anyone walking past can read it."
                ),
            )
        if board.entity_type != "user":
            # A team board has no face and no person to put on the screen.
            # Said here rather than leaving the rotation to skip it silently.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "That board ranks teams, so there is no one person to "
                    "spotlight. Choose a board of people."
                ),
            )
        _must_fit(
            db, screen, kind, office_id, team_id,
            eligibility.board_where(board), "board",
        )
        screen.leaderboard_id = board.id

    if payload.user_id is not None:
        person = db.get(UserAccount, payload.user_id)
        if (
            person is None
            or person.organization_id != actor.organization_id
            or person.hidden_at is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Person not found."
            )
        # The same hole as a goal: a spotlight names its own subject, so the
        # audience filter has nothing to narrow. A Dallas agent's face on a
        # Phoenix wall is the failure this prevents.
        _must_fit(
            db, screen, kind, office_id, team_id,
            eligibility.person_where(db, person), "person",
        )
        screen.user_id = person.id


#: How many boards fit side by side on a television.
#:
#: Two is the point of the screen; five 384-pixel columns on a 1920-wide wall
#: is a spreadsheet nobody reads from across a room.
MIN_PANELS = 2
MAX_PANELS = 4


def _panel_ids(db: DbSession, screen: ChannelScreen) -> list[int]:
    """The boards on a comparison, in the order they are drawn."""
    if screen.kind != "comparison":
        return []
    return list(
        db.scalars(
            select(ChannelScreenBoard.leaderboard_id)
            .where(ChannelScreenBoard.channel_screen_id == screen.id)
            .order_by(ChannelScreenBoard.position, ChannelScreenBoard.id)
        ).all()
    )


def _apply_comparison(
    db: DbSession,
    actor: UserAccount,
    screen: ChannelScreen,
    payload: ScreenWrite,
    kind: str | None,
    office_id: int | None,
    team_id: int | None,
) -> None:
    """Validate and attach the panels of a comparison.

    Every board goes through the same checks a leaderboard screen does, because
    a panel *is* a board on a wall — putting it in a column does not make a
    private board public or a Dallas board acceptable in Phoenix.
    """
    ids = payload.leaderboard_ids
    if len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The same board twice is two identical columns.",
        )
    if not MIN_PANELS <= len(ids) <= MAX_PANELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"A comparison puts {MIN_PANELS} to {MAX_PANELS} boards side "
                "by side. One board on its own is a leaderboard screen."
            ),
        )

    # Flushed before the panels are inserted, because a screen being created
    # has no id yet and the rows point at it.
    db.add(screen)
    db.flush()

    for position, board_id in enumerate(ids):
        board = db.get(Leaderboard, board_id)
        if board is None or board.organization_id != actor.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Board not found."
            )
        if board.visibility != "org":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"“{board.name}” is not published to everyone, so it "
                    "cannot go on a wall — anyone walking past can read it."
                ),
            )
        _must_fit(
            db, screen, kind, office_id, team_id,
            eligibility.board_where(board), "board",
        )
        db.add(
            ChannelScreenBoard(
                channel_screen_id=screen.id,
                leaderboard_id=board.id,
                position=position,
            )
        )


def _to_read(db: DbSession, channel: Channel) -> ChannelRead:
    screens = db.scalars(
        select(ChannelScreen)
        .where(ChannelScreen.channel_id == channel.id)
        .order_by(ChannelScreen.position, ChannelScreen.id)
    ).all()
    displays = db.scalar(
        select(func.count())
        .select_from(Display)
        .where(Display.channel_id == channel.id, Display.revoked_at.is_(None))
    )
    return ChannelRead(
        id=channel.id,
        name=channel.name,
        scope_type=channel.scope_type,
        scope_office_id=channel.scope_office_id,
        scope_team_id=channel.scope_team_id,
        audience_label=_audience_label(
            db, channel.scope_type, channel.scope_office_id, channel.scope_team_id
        ),
        allowed_ips=list(channel.allowed_ips or []),
        appearance=channel.appearance or {},
        quiet_mode=channel.quiet_mode or "off",
        quiet_from=channel.quiet_from,
        quiet_until=channel.quiet_until,
        quiet_weekends=bool(channel.quiet_weekends),
        display_count=int(displays or 0),
        screens=[
            ScreenRead(
                id=s.id,
                position=s.position,
                kind=s.kind,
                dwell_seconds=s.dwell_seconds,
                leaderboard_id=s.leaderboard_id,
                goal_id=s.goal_id,
                competition_id=s.competition_id,
                user_id=s.user_id,
                leaderboard_ids=_panel_ids(db, s),
                appearance=s.appearance or {},
                url=s.url,
                media_start_seconds=s.media_start_seconds,
                fit=s.fit,
                title=s.title,
                body=s.body,
                scope_type=s.scope_type,
                scope_office_id=s.scope_office_id,
                scope_team_id=s.scope_team_id,
                days=s.days,
                play_from=s.play_from,
                play_until=s.play_until,
                weight=s.weight or 1,
                label=_label(db, s),
                archived=_target_archived(db, s),
                audience_label=_audience_label(
                    db,
                    s.scope_type if s.scope_type is not None else channel.scope_type,
                    s.scope_office_id
                    if s.scope_type is not None
                    else channel.scope_office_id,
                    s.scope_team_id
                    if s.scope_type is not None
                    else channel.scope_team_id,
                ),
            )
            for s in screens
        ],
    )


def _goal_subject(db: DbSession, goal: Goal) -> str:
    """Who a goal is about, for labelling a screen."""
    if goal.subject_type == "organization":
        org = db.get(Organization, goal.organization_id)
        # The company's own name. Without this branch the lookup below runs
        # with a null id, which SQLAlchemy warns about and which renders
        # "Deleted user" under a target nobody deleted.
        return org.name if org else "Everyone"
    if goal.subject_type == "team":
        team = db.get(Team, goal.subject_team_id)
        return team.name if team else "Deleted team"
    person = db.get(UserAccount, goal.subject_user_id)
    return person.full_name if person else "Deleted user"


def _target_archived(db: DbSession, screen: ChannelScreen) -> bool:
    """Whether the board or goal this slide shows is archived (P3-2)."""
    if screen.leaderboard_id is not None:
        board = db.get(Leaderboard, screen.leaderboard_id)
        return board is not None and board.archived_at is not None
    if screen.goal_id is not None:
        goal = db.get(Goal, screen.goal_id)
        return goal is not None and goal.archived_at is not None
    return False


def _label(db: DbSession, screen: ChannelScreen) -> str:
    """What the editor calls this row.

    Resolved server-side so the client does not have to hold every board and
    goal in memory to name a list, and so a deleted target reads as something
    explicable rather than as a blank line.
    """
    if screen.kind == "leaderboard":
        board = db.get(Leaderboard, screen.leaderboard_id)
        return board.name if board else "Deleted board"
    if screen.kind == "goal":
        goal = db.get(Goal, screen.goal_id)
        if goal is None:
            return "Deleted goal"
        # Named after the metric when the goal has no name of its own — which
        # most do not. The previous version fell through to "Deleted goal" for
        # any unnamed goal, so a perfectly live screen read as broken.
        metric = db.get(MetricDefinition, goal.metric_definition_id)
        title = goal.name or (metric.name if metric else "Goal")
        # And whose it is. Three people with a "Calls Made" goal are three
        # identical rows otherwise, and the editor is where you pick between
        # them.
        return f"{title} — {_goal_subject(db, goal)}"
    if screen.kind == "spotlight":
        if screen.user_id is not None:
            person = db.get(UserAccount, screen.user_id)
            who = person.full_name if person else "Deleted person"
            board = db.get(Leaderboard, screen.leaderboard_id) if screen.leaderboard_id else None
            return f"{who} — {board.name}" if board else who
        board = db.get(Leaderboard, screen.leaderboard_id)
        # Named for what it *does*, not for the board. "Whoever leads Revenue"
        # is the difference between this row and the board screen above it.
        return f"Whoever leads {board.name}" if board else "Deleted board"
    if screen.kind == "comparison":
        if screen.title:
            return screen.title
        names = [
            board.name
            for board in (
                db.get(Leaderboard, board_id) for board_id in _panel_ids(db, screen)
            )
            if board is not None
        ]
        # Named by its boards, because "Comparison" in a running order of six
        # tells an admin nothing about which one this is.
        return " vs ".join(names) if names else "Comparison"
    if screen.kind == "competition":
        # By name, like a board or a goal. It fell through to the catch-all
        # below and read as the bare word "competition" (QA-11).
        if screen.title:
            return screen.title
        contest = db.get(Competition, screen.competition_id) if screen.competition_id else None
        return contest.name if contest else "Deleted competition"
    if screen.kind == "achievements":
        return screen.title or "Recent wins"
    if screen.kind == "message":
        return screen.title or "Message"
    return screen.title or (screen.url or "").rsplit("/", 1)[-1] or screen.kind
