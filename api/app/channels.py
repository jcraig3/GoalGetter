"""Turning an authored channel into what a wall screen renders.

One place, so the admin preview and the television cannot disagree — the same
reasoning that made `_build_channel` shared in 1f-iv, now with a playlist
behind it instead of a query.

**A screen that cannot render is skipped, never blanked.** A board that was
archived, a goal that was deleted, a message whose text was cleared: the
rotation moves past it. A wall going black in front of an office reads as the
product being broken, and "one of six slides is missing" reads as nothing at
all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session as DbSession

from app import appearance as appearance_service, eligibility, events, goal_tiers, goals as goal_service
from app import periods
from app import photos as photo_service
from app import schedule
from app import streaks as streak_service
from app import leaderboards as board_service
from app import media as media_service
from app import unlocks as unlock_service
from app.models import (
    GameToken,
    CelebrationReplay,
    TvAnnouncement,
    TvAnnouncementSend,
    Channel,
    ChannelScreen,
    ChannelScreenBoard,
    Competition,
    Goal,
    Leaderboard,
    MetricDefinition,
    MetricFact,
    Notification,
    Organization,
    Team,
    UserAccount,
)

#: How many achievements a wall shows at once. Enough to feel like a stream,
#: few enough to read from across a room.
ACHIEVEMENTS_ON_SCREEN = 5

#: How many standings rows a competition slide shows.
#:
#: Fewer than a leaderboard's, because a competition slide also carries a prize
#: and a countdown, and the point of it is the top of the field. `total_entrants`
#: goes with it so the wall can say "of 14".
WALL_ROWS = 8


class _NoActor:
    """Stands in for the signed-in user a wall screen does not have.

    Carries only what the unscoped path reads, so a real endpoint cannot pass
    it by accident and silently skip scoping.
    """

    org_role = "display"
    team_id = None
    id = None

    def __init__(self, organization_id: int) -> None:
        self.organization_id = organization_id


@dataclass
class Slide:
    """One rendered screen. Deliberately flat — a wall must never need a
    second request for anything."""

    id: int
    kind: str
    dwell_seconds: int
    title: str
    subtitle: str | None = None
    #: Leaderboard slides.
    entries: list = field(default_factory=list)
    total_entrants: int = 0
    entity_type: str | None = None
    unit: str | None = None
    decimal_places: int = 0
    unit_label: str | None = None
    direction: str | None = None
    #: Where a race layout draws its finish line. See `app/game_boards.py`.
    finish_line: Decimal | None = None
    #: "23 Sep" when the newest number behind this slide is over a day old
    #: (10.6): a TV showing September under "Last 30 days" gave no hint.
    as_of: str | None = None
    #: Last period's top three, for a calendar board with nothing in it yet
    #: (10.1): `{"label": "September 2026", "entries": [...]}`. A wall that
    #: celebrates September on 1 October beats a blank one.
    previous: dict | None = None
    #: Goal slides.
    current_value: Decimal | None = None
    target_value: Decimal | None = None
    percent: float | None = None
    status: str | None = None
    #: Levels past the target: `{"label", "value", "reached"}`. See
    #: `app/goal_tiers.py`.
    stretch: list = field(default_factory=list)
    #: Competition slides.
    #:
    #: `entries` and `total_entrants` are shared with leaderboard slides on
    #: purpose — a competition table *is* a ranked list, and giving it its own
    #: field would mean the wall rendering the same shape two ways.
    prize: str | None = None
    #: When the countdown runs out. Absent once settled, because "0s left" beside
    #: a final result is noise.
    ends_at: str | None = None
    state: str | None = None
    final: bool = False
    #: Achievements slides — and the "recent wins" strip of a spotlight, which
    #: is the same shape drawn smaller rather than a second one to render.
    achievements: list = field(default_factory=list)
    #: Spotlight slides: who it is about.
    person: dict | None = None
    #: Spotlight slides: their standing, as label/value pairs the wall can draw
    #: without knowing what any of them mean.
    stats: list = field(default_factory=list)
    #: Spotlight slides: consecutive days with a number. None when the screen
    #: names no metric to count one from. See `app/streaks.py`.
    streak_days: int | None = None
    #: Comparison slides: two to four boards, each carrying the fields a
    #: leaderboard slide would. The same shape rather than a new one, so the
    #: wall draws a panel with the component it already has for a board.
    panels: list = field(default_factory=list)
    #: Image, video, and message slides.
    url: str | None = None
    media_kind: str | None = None
    #: Picture and video screens (Phase 26): a stored file's digest, where
    #: the video starts, and how a picture fills the screen.
    media_digest: str | None = None
    media_start_seconds: int | None = None
    fit: str | None = None
    body: str | None = None

    #: How to draw it, already merged.
    #:
    #: **Resolved here rather than on the wall**, because this is the only place
    #: that can see the whole chain — the organization, the thing being shown,
    #: the channel, and the screen. A client given four layers would have to
    #: reimplement the merge, and a second implementation of a merge is a second
    #: set of rules to keep in step.
    appearance: dict = field(default_factory=dict)


def audience(channel: Channel, screen: ChannelScreen) -> dict[str, int | None]:
    """Who this screen is about: the channel's audience, or its own override.

    A screen with no override inherits, which is almost all of them — the point
    of putting the audience on the channel is that a wall is right by default
    and one office's numbers do not turn up on another's by omission.
    """
    source = screen if screen.scope_type is not None else channel
    if source.scope_type == "office":
        return {"office_id": source.scope_office_id, "team_id": None}
    if source.scope_type == "team":
        return {"office_id": None, "team_id": source.scope_team_id}
    return {"office_id": None, "team_id": None}


def build(
    db: DbSession, org: Organization, channel: Channel, *, now: datetime | None = None
) -> list[Slide]:
    """Every screen on the channel that plays now, in order, skipping what
    cannot render — each repeated by its weight, spread through the cycle.

    **Scheduled in the organization's time** (6.10), not the television's or
    the server's: "weekdays from nine" means nine where the office is.
    """
    actor = _NoActor(org.id)
    local = (now or datetime.now(UTC)).astimezone(periods.tz(org))
    screens = [
        screen
        for screen in scheduled_screens(db, channel)
        if schedule.plays_now(screen.days, screen.play_from, screen.play_until, local)
    ]

    rendered: list[tuple[Slide, int]] = []
    for screen in screens:
        slide = slide_for(db, org, channel, screen, actor=actor)
        if slide is not None:
            rendered.append((slide, screen.weight or 1))
    return schedule.weighted(rendered)


def scheduled_screens(db: DbSession, channel: Channel) -> list[ChannelScreen]:
    return list(
        db.scalars(
            select(ChannelScreen)
            .where(ChannelScreen.channel_id == channel.id)
            .order_by(ChannelScreen.position, ChannelScreen.id)
        ).all()
    )


def quiet(
    db: DbSession, org: Organization, channel: Channel, *, now: datetime | None = None
) -> schedule.Quiet | None:
    """What the wall shows instead of its rotation, if anything (6.10).

    Night mode, in its hours. Otherwise a clock when the channel has slides
    but none of them is scheduled right now — a wall of slides that only play
    in the mornings should show the time in the afternoon, not go black and
    look broken. A channel with no slides at all is still being set up, and
    keeps saying so.
    """
    local = (now or datetime.now(UTC)).astimezone(periods.tz(org))
    night = night_mode(org, channel, now=now)
    if night is not None:
        return night
    screens = scheduled_screens(db, channel)
    if screens and not any(
        schedule.plays_now(s.days, s.play_from, s.play_until, local) for s in screens
    ):
        return schedule.Quiet(mode="clock", until=None)
    return None


def night_mode(
    org: Organization, channel: Channel, *, now: datetime | None = None
) -> schedule.Quiet | None:
    """The channel's night mode, if it is in its hours now."""
    local = (now or datetime.now(UTC)).astimezone(periods.tz(org))
    return schedule.quiet_now(
        channel.quiet_mode or "off",
        channel.quiet_from,
        channel.quiet_until,
        bool(channel.quiet_weekends),
        local,
    )


def draw_unsaved(db: DbSession, org: Organization, actor, **screen_fields) -> dict | None:
    """A slide for something not saved yet, as an organization-wide wall would
    draw it — for the board and goal forms' "Real numbers" (8.7).

    **The caller owns the savepoint** and rolls it back: the thing being
    previewed is added inside it first, then a throwaway channel and screen
    here, so the same renderer as the TVs draws it and nothing survives.
    """
    from app.routers.display_feed import SlideRead

    channel = Channel(organization_id=org.id, name="Preview", scope_type="organization")
    db.add(channel)
    db.flush()
    screen = ChannelScreen(channel_id=channel.id, position=0, dwell_seconds=20, **screen_fields)
    db.add(screen)
    db.flush()
    slide = slide_for(db, org, channel, screen, actor=actor)
    return SlideRead(**vars(slide)).model_dump(mode="json") if slide else None


def slide_for(
    db: DbSession,
    org: Organization,
    channel: Channel,
    screen: ChannelScreen,
    *,
    actor=None,
) -> Slide | None:
    """One screen, finished exactly as `build` finishes every screen.

    Public for the slide editor's preview, which renders a screen that has not
    been saved: one path from screen to slide, so the preview cannot draw
    something the wall would not.
    """
    slide = _render(
        db, org, actor or _NoActor(org.id), screen, audience(channel, screen)
    )
    if slide is None:
        return None
    slide.appearance = _appearance(db, org, channel, screen)
    _write_names(db, slide)
    _dress(db, slide)
    _place_on_track(slide)
    return slide


def _write_names(db: DbSession, slide: Slide) -> None:
    """Rewrite every name on a slide the way the organization asked for.

    **Applied here, on the server, and not in the renderer.** `first_initial`
    exists so a wall can hang where customers walk past, which makes it a
    privacy setting rather than a typographic one — and a privacy setting that
    works by trimming the string in a browser has still sent every surname to a
    television whose address bar is visible in the room.

    One place, for the same reason: a screen careful about surnames on the
    leaderboard and careless about them in the celebration over the top of it
    is not careful at all.
    """
    style = slide.appearance.get("name_display", "full")
    if style == "full":
        return

    # **Looked up only for the one style that needs them.** Every other style
    # is a transformation of the name already in hand, so nothing is queried
    # for a wall that is not asking for nicknames.
    nicknames = _nicknames(db, slide) if style == "nickname" else {}

    def written(name: str | None, person_id: int | None = None) -> str | None:
        if name is None:
            return None
        return appearance_service.display_name(
            name, nicknames.get(person_id) if person_id else None, style
        )

    # Only boards of people. A team's name is not a person's, and "Enterprise"
    # becoming "E." would be a bug wearing a privacy setting's clothes.
    if slide.entity_type == "user":
        for entry in slide.entries:
            entry["entity_name"] = written(entry["entity_name"], entry["entity_id"])
        # Last period's top three (10.1) are the same people, under the same
        # setting — a full name there would undo it.
        for entry in (slide.previous or {}).get("entries", []):
            entry["entity_name"] = written(entry["entity_name"], entry["entity_id"])

    for panel in slide.panels:
        if panel.get("entity_type") == "user":
            for entry in panel["entries"]:
                entry["entity_name"] = written(
                    entry["entity_name"], entry["entity_id"]
                )

    if slide.person is not None:
        was = slide.person["name"]
        slide.person["name"] = written(was, slide.person["id"])
        # **Only when the heading *is* the name.** A spotlight with no title of
        # its own is headed by the person, and leaving that at the full name
        # while the caption reads "Peter P." would publish exactly what the
        # setting exists to withhold. A title somebody typed is their words and
        # is left alone — "Rep of the month" must not become "Rep".
        if slide.title == was:
            slide.title = slide.person["name"]

    for achievement in slide.achievements:
        if achievement.get("about_person"):
            achievement["about_name"] = written(
                achievement["about_name"], achievement.get("about_user_id")
            )


def _place_on_track(slide: Slide) -> None:
    """How far along a race each entrant is, worked out here rather than on
    the wall, so the rule has one home and one set of tests.

    Done for every ranked slide whatever its layout — it is arithmetic on rows
    already in hand, and a preview switching a screen to the race layout should
    not need a different payload to draw it.
    """
    from app import game_boards

    if not slide.entries:
        return
    # The leader is the first row whichever way round the metric runs — the
    # board is already ranked — so "against the leader" needs no second sort.
    leader = slide.entries[0]["value"]
    for entry in slide.entries:
        standing = game_boards.progress(
            entry["value"],
            finish_line=slide.finish_line,
            leader=leader,
            lower_is_better=slide.direction == "lower_is_better",
        )
        entry["progress"] = standing.fraction
        entry["finished"] = standing.finished


def _dress(db: DbSession, slide: Slide) -> None:
    """Put on what the people on this slide have bought.

    **The wall is where a cosmetic earns its price.** A ring somebody paid for
    that only shows in their own browser is a receipt; the same ring round
    their face on the board by the lifts is the thing they bought. So every
    face a slide draws — board rows, comparison panels, the spotlight, the
    champion — carries its ring, and the spotlight carries a title as well,
    because it is the one layout with room under a name for a second line.

    One query for the whole slide, like `_nicknames`, and for the same reason:
    one lookup per row is ten per board, on every poll, on every television.
    """
    _team_identity(db, slide)

    boards: list[list[dict]] = []
    if slide.entity_type == "user":
        boards.append(slide.entries)
    for panel in slide.panels:
        if panel.get("entity_type") == "user":
            boards.append(panel["entries"])

    ids = {entry["entity_id"] for entries in boards for entry in entries}
    if slide.person is not None:
        ids.add(slide.person["id"])
    if not ids:
        return

    from app import game_boards

    worn = unlock_service.worn_by(db, ids)
    # The pieces for this board's own family: a car on a race track, a boat
    # on a regatta (6.8). Any other layout sends the race's, which nothing draws.
    layout = (slide.appearance or {}).get("ranked_layout")
    pieces = _pieces(db, ids, layout if layout in game_boards.FAMILIES else "race")
    for entries in boards:
        for entry in entries:
            on = worn.get(entry["entity_id"])
            entry["ring"] = on.ring if on else None
            # The piece they move on a race board — see `game_boards`. Sent
            # whatever the layout, for the same reason progress is.
            entry["token"] = pieces.get(entry["entity_id"])
    if slide.person is not None:
        on = worn.get(slide.person["id"])
        slide.person["ring"] = on.ring if on else None
        slide.person["title"] = on.title if on else None


def _team_identity(db: DbSession, slide: Slide) -> None:
    """A team's colour, short name and logo on every team row (6.7).

    A team board drew every team alike — a name, and nothing to know it by
    from across a room. The logo goes where a person's face would; the colour
    and short name are what a podium block, a race piece or a head-to-head
    banner draw when there is no logo, or no room for the whole name.
    """
    boards: list[list[dict]] = []
    if slide.entity_type == "team":
        boards.append(slide.entries)
    for panel in slide.panels:
        if panel.get("entity_type") == "team":
            boards.append(panel["entries"])
    ids = {entry["entity_id"] for entries in boards for entry in entries}
    if not ids:
        return
    teams = {
        team.id: team
        for team in db.scalars(select(Team).where(Team.id.in_(ids))).all()
    }
    for entries in boards:
        for entry in entries:
            entry["is_team"] = True
            team = teams.get(entry["entity_id"])
            if team is None:
                continue
            entry["colour"] = team.color
            entry["short_name"] = team.short_name
            if team.logo and not entry.get("photo_digest"):
                entry["photo_digest"] = team.logo


def _pieces(db: DbSession, ids: set[int], family: str) -> dict[int, str]:
    """Who has chosen which piece, in one query for the whole slide."""
    rows = db.execute(
        select(GameToken.user_id, GameToken.token).where(
            GameToken.user_id.in_(ids), GameToken.family == family
        )
    ).all()
    return {user_id: token for user_id, token in rows}


def _nicknames(db: DbSession, slide: Slide) -> dict[int, str]:
    """What the people on this slide are called, by id.

    One query for the whole slide rather than one per row: a board of ten is
    ten lookups otherwise, on every poll, on every television.
    """
    ids: set[int] = set()
    if slide.entity_type == "user":
        ids.update(entry["entity_id"] for entry in slide.entries)
        ids.update(entry["entity_id"] for entry in (slide.previous or {}).get("entries", []))
    for panel in slide.panels:
        if panel.get("entity_type") == "user":
            ids.update(entry["entity_id"] for entry in panel["entries"])
    if slide.person is not None:
        ids.add(slide.person["id"])
    ids.update(
        a["about_user_id"] for a in slide.achievements if a.get("about_user_id")
    )
    if not ids:
        return {}

    rows = db.execute(
        select(UserAccount.id, UserAccount.nickname).where(
            UserAccount.id.in_(ids), UserAccount.nickname != ""
        )
    ).all()
    return {user_id: nickname for user_id, nickname in rows}


def _appearance(
    db: DbSession, org: Organization, channel: Channel, screen: ChannelScreen
) -> dict:
    """The look for one screen, merged from every layer that has a say.

        organization -> item -> channel -> screen

    (For everything but the background — see below.)

    **The item sits before the channel, deliberately.** A venue's concerns beat
    a thing's own identity: "this TV is in a lobby, show initials only" has to
    win over "this contest is themed red", because the legibility and privacy
    decisions belong to the room the screen is in and not to the contest being
    shown in it.
    """
    item = None
    if screen.kind == "leaderboard" and screen.leaderboard_id:
        item = db.get(Leaderboard, screen.leaderboard_id)
    elif screen.kind == "goal" and screen.goal_id:
        item = db.get(Goal, screen.goal_id)
    elif screen.kind == "competition" and screen.competition_id:
        item = db.get(Competition, screen.competition_id)
    elif screen.kind == "spotlight" and screen.leaderboard_id:
        # A spotlight drawn from a board inherits that board's look, so
        # "Shark Week is blue" covers the person on the Shark Week board too
        # rather than stopping at the table.
        item = db.get(Leaderboard, screen.leaderboard_id)

    own = getattr(item, "appearance", None)
    look = appearance_service.resolve(
        org.appearance, own, channel.appearance, screen.appearance
    )
    # **Except the background, where the item beats the channel.** The rule
    # above is about the room — names, privacy, legibility — and the room's
    # say should win. A background is the other kind of thing: it is the
    # item's own identity, the reason a leaderboard was given one. So for the
    # background alone the order is organization -> channel -> item -> screen:
    # a channel's background is the default for everything on it that has not
    # chosen its own, and a screen can still override both explicitly.
    look.background = appearance_service.resolve(
        org.appearance, channel.appearance, own, screen.appearance
    ).background
    return look.model_dump()


def inherited_look(db: DbSession, org: Organization, channel: Channel, screen: ChannelScreen) -> tuple[dict, str]:
    """What a screen looks like with nothing set on it, and where its
    background comes from, in words: "the leaderboard “Sales floor”", "the
    channel", "your Appearance settings" — or "" for none (Phase 26)."""
    from types import SimpleNamespace

    bare = SimpleNamespace(**{c.key: getattr(screen, c.key) for c in ChannelScreen.__table__.columns})
    bare.appearance = {}
    look = _appearance(db, org, channel, bare)
    item = _item_of(db, screen)
    words = {"leaderboard": "leaderboard", "goal": "goal", "competition": "competition", "spotlight": "leaderboard"}
    if item is not None and (getattr(item, "appearance", None) or {}).get("background"):
        name = getattr(item, "name", None)
        source = f"the {words[screen.kind]} “{name}”" if name else f"the {words[screen.kind]}"
    elif (channel.appearance or {}).get("background"):
        source = "the channel"
    elif (org.appearance or {}).get("background"):
        source = "your Appearance settings"
    else:
        source = ""
    return look, source


def _item_of(db: DbSession, screen) -> object | None:
    """The leaderboard, goal or competition a screen shows, if it shows one."""
    if screen.kind in ("leaderboard", "spotlight") and screen.leaderboard_id:
        return db.get(Leaderboard, screen.leaderboard_id)
    if screen.kind == "goal" and screen.goal_id:
        return db.get(Goal, screen.goal_id)
    if screen.kind == "competition" and screen.competition_id:
        return db.get(Competition, screen.competition_id)
    return None


def _render(db, org, actor, screen: ChannelScreen, narrow) -> Slide | None:
    if screen.kind == "leaderboard":
        return _leaderboard(db, org, actor, screen, narrow)
    if screen.kind == "goal":
        # A goal names its own subject, so there is nothing to *narrow* — but
        # that is exactly why it has to be checked instead. Without this, a
        # Dallas agent's goal on a Phoenix channel renders Dallas numbers on a
        # Phoenix wall: the audience filter has nothing to bite on.
        #
        # Authoring refuses this now; the guard stays for rows written before
        # it did.
        return _goal(db, org, actor, screen, narrow)
    if screen.kind == "competition":
        return _competition(db, org, screen, narrow)
    if screen.kind == "achievements":
        return _achievements(db, org, screen, narrow)
    if screen.kind == "spotlight":
        return _spotlight(db, org, actor, screen, narrow)
    if screen.kind == "comparison":
        return _comparison(db, org, actor, screen, narrow)
    if screen.kind in ("image", "video"):
        return Slide(
            id=screen.id,
            kind=screen.kind,
            dwell_seconds=screen.dwell_seconds,
            title=screen.title or "",
            url=screen.url,
            media_kind=media_service.kind_of(screen.url) if screen.url else None,
            # A stored file, by digest, so the wall fetches it through its own
            # link; a link is drawn as it is (Phase 26).
            media_digest=media_service.asset_digest(screen.url) if screen.url else None,
            media_start_seconds=screen.media_start_seconds,
            fit=screen.fit or "cover",
        )
    if screen.kind == "message":
        return Slide(
            id=screen.id,
            kind="message",
            dwell_seconds=screen.dwell_seconds,
            title=screen.title or "",
            body=screen.body,
        )
    # An unknown kind is a newer API's row seen by older code. Skipping keeps
    # the rest of the rotation running.
    return None


def board_slide(db, org, actor, board: Leaderboard, *, anchor=None) -> Slide | None:
    """One board as the wall would draw it, outside any channel.

    For the board's own page, which showed a plain table whatever layout the
    board was set to — so a podium or a race was only ever seen on a TV
    (QA-37). The board's own look over the organization's: there is no
    channel or screen to add theirs. Run as the viewer, who the results
    endpoint has already let see this board.
    """
    metric = db.get(MetricDefinition, board.metric_definition_id)
    if metric is None:
        return None
    result = board_service.run(db, org, actor, board, anchor=anchor)
    slide = Slide(
        id=board.id,
        kind="leaderboard",
        dwell_seconds=20,
        title=board.name,
        subtitle=f"{metric.name} · {result.period.label}",
        entries=[vars(entry) for entry in result.entries],
        total_entrants=result.total_entrants,
        entity_type=board.entity_type,
        unit=metric.unit,
        decimal_places=metric.decimal_places,
        unit_label=metric.unit_label,
        direction=metric.direction,
        finish_line=board.finish_line,
    )
    slide.appearance = appearance_service.resolve(org.appearance, board.appearance).model_dump()
    _write_names(db, slide)
    _dress(db, slide)
    _place_on_track(slide)
    return slide


def _leaderboard(db, org, actor, screen, narrow) -> Slide | None:
    board = db.get(Leaderboard, screen.leaderboard_id)
    if board is None or board.archived_at is not None:
        return None

    # The safety property that survived from Phase 1: only a board published to
    # the whole organization can appear on a wall, because a wall has no
    # audience control at all. Checked here as well as by the CHECK constraint
    # on `leaderboard`, so relaxing one cannot silently open the screens.
    if board.visibility != "org":
        return None

    metric = db.get(MetricDefinition, board.metric_definition_id)
    if metric is None:
        return None

    result = board_service.run(db, org, actor, board, narrow=narrow)
    return Slide(
        as_of=_as_of(db, org, metric),
        previous=_last_period(db, org, actor, board, metric, result, narrow),
        id=screen.id,
        kind="leaderboard",
        dwell_seconds=screen.dwell_seconds,
        title=board.name,
        subtitle=f"{metric.name} · {result.period.label}",
        entries=[vars(entry) for entry in result.entries],
        total_entrants=result.total_entrants,
        entity_type=board.entity_type,
        unit=metric.unit,
        decimal_places=metric.decimal_places,
        unit_label=metric.unit_label,
        direction=metric.direction,
        finish_line=board.finish_line,
    )


#: How old the newest number may be before a slide says when it is from.
STALE_AFTER = timedelta(days=1)


def _as_of(db, org, metric) -> str | None:
    """"23 Sep" when the newest number this metric has is over a day old.

    Any source and corrections included — what the figures on screen are made
    of. Nothing at all says nothing: an empty board says so in its own words.
    """
    from app import derived, staleness

    newest = db.scalar(
        select(func.max(MetricFact.occurred_at)).where(
            MetricFact.organization_id == org.id,
            MetricFact.metric_definition_id.in_(derived.fact_metric_ids(db, metric)),
        )
    )
    if newest is None or datetime.now(UTC) - newest <= STALE_AFTER:
        return None
    return staleness.say_date(org, newest)


#: How many of last period's places an empty board shows.
LAST_PERIOD_SHOWN = 3


def _last_period(db, org, actor, board, metric, result, narrow) -> dict | None:
    """Last period's top three, when this one has nothing in it yet.

    Only for a calendar period — a rolling one ("last 30 days") is never empty
    because a month turned over. Nothing when last period was empty too.
    """
    # Nothing yet: no rows, or every row at zero where higher is better (a
    # zero can be a real best where lower is).
    lower = metric.direction == "lower_is_better"
    if result.entries and (lower or any(entry.value for entry in result.entries)):
        return None
    if result.period.type in periods.ROLLING_DAYS or result.period.type == "custom":
        return None
    before = periods.previous(org, result.period)
    anchor = before.start.astimezone(periods.tz(org)).date()
    last = board_service.run(db, org, actor, board, anchor=anchor, narrow=narrow)
    shown = [vars(entry) for entry in last.entries if entry.value][:LAST_PERIOD_SHOWN]
    return {"label": before.label, "entries": shown} if shown else None


def _goal_subject(db, goal: Goal) -> str:
    """Who the goal is about — the same answer the channel editor shows."""
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


def _goal(db, org, actor, screen, narrow) -> Slide | None:
    """A goal on the wall.

    The most useful screen there is: a target with a pace marker is the thing a
    room can act on before the period closes, where a ranking only says where
    you already are.
    """
    goal = db.get(Goal, screen.goal_id)
    if goal is None or goal.archived_at is not None:
        return None

    wall = eligibility.Where(
        office_id=narrow.get("office_id"), team_id=narrow.get("team_id")
    )
    if not eligibility.fits(wall, eligibility.goal_where(db, goal)):
        return None

    metric = db.get(MetricDefinition, goal.metric_definition_id)
    if metric is None:
        return None

    # Evaluated as the organization, not as a viewer — a wall has none, and
    # scoping to nobody would show a team goal as zero.
    from app.notifications import _System

    current, has_data = goal_service.current_value(
        db, org, _System(org.id), goal, metric
    )
    progress = goal_service.progress(
        current, goal.target_value, metric.direction, has_data=has_data
    )
    period = goal_service.resolve_period(org, goal)

    # Whose, and when. A room looking at "Calls Made · August" cannot tell
    # which of three people it is about — so an unnamed goal leads with who it
    # belongs to, "Clark — Calls Made", rather than a metric's name in the
    # biggest type on the screen with the person underneath it in the smallest.
    subject = _goal_subject(db, goal)
    return Slide(
        as_of=_as_of(db, org, metric) if period.end > datetime.now(UTC) else None,
        id=screen.id,
        kind="goal",
        dwell_seconds=screen.dwell_seconds,
        title=goal.name or f"{subject} — {metric.name}",
        subtitle=f"{subject} · {period.label}" if goal.name else period.label,
        current_value=progress.current,
        target_value=goal.target_value,
        percent=progress.percent,
        status="hit" if progress.attained else "open",
        stretch=[
            {
                "label": level.label,
                "value": str(level.value),
                "reached": goal_service.progress(
                    current, level.value, metric.direction, has_data=has_data
                ).attained,
            }
            for level in goal_tiers.levels_of(goal.stretch_targets)
        ],
        unit=metric.unit,
        decimal_places=metric.decimal_places,
        unit_label=metric.unit_label,
        direction=metric.direction,
    )


#: States a competition is worth putting on a wall in.
#:
#: A draft is a plan nobody has published, and a cancelled contest has no result
#: and no future — both would be a slide saying nothing. `ended` stays because the
#: provisional table is still the most interesting thing in the room.
WALL_STATES = ("scheduled", "active", "ended", "closed")


def _competition(db, org, screen, narrow) -> Slide | None:
    """A contest on the wall: the table, the prize, and how long is left.

    Standings come from `competitions.standings`, which is the same call the app
    makes — so a settled contest shows its frozen result here too, and the wall
    cannot disagree with the trophy.
    """
    from app import competitions as competition_service

    competition = db.get(Competition, screen.competition_id)
    if competition is None or competition.state not in WALL_STATES:
        return None

    wall = eligibility.Where(
        office_id=narrow.get("office_id"), team_id=narrow.get("team_id")
    )
    # Set-based, unlike every other screen kind: a contest can be on in two
    # offices at once, and only those two.
    if not eligibility.competition_fits(db, wall, competition):
        return None

    metric = db.get(MetricDefinition, competition.metric_definition_id)
    if metric is None:
        return None

    rows = competition_service.standings(db, org, competition)
    if not rows:
        # Nothing to rank. An empty table on a wall is worse than one fewer
        # slide, the same as an achievements panel with no wins in it.
        return None

    settled = competition.state == "closed"
    shown = rows[:WALL_ROWS]
    as_of = None if settled else _as_of(db, org, metric)
    # **Faces, as a board has them** (8.5). A contest's rows never carried a
    # photo, so every contest layout drew initials — the head-to-head most
    # visibly, two big circles of letters. One query, as a board does it.
    faces = {}
    if competition.entity_type == "user" and shown:
        from app.leaderboards import _faces

        faces = _faces(db, [row.entity_id for row in shown])
    return Slide(
        id=screen.id,
        kind="competition",
        dwell_seconds=screen.dwell_seconds,
        title=screen.title or competition.name,
        subtitle=metric.name,
        prize=competition.prize,
        # Nothing to count down to once it is settled.
        ends_at=None if settled else competition.ends_at.isoformat(),
        state=competition.state,
        final=settled,
        as_of=as_of,
        finish_line=competition.finish_line,
        # The same keys a leaderboard entry uses, so the wall renders one shape.
        # `movement` is null rather than 0: a competition has no previous period to
        # have moved from, and 0 would claim it held its place.
        entries=[
            {
                "rank": row.rank,
                "entity_id": row.entity_id,
                "entity_name": row.entity_name,
                "team_name": None,
                "value": row.value,
                "movement": None,
                "photo_digest": faces.get(row.entity_id),
            }
            for row in shown
        ],
        total_entrants=len(rows),
        entity_type=competition.entity_type,
        unit=metric.unit,
        decimal_places=metric.decimal_places,
        unit_label=metric.unit_label,
        direction=metric.direction,
    )


@dataclass
class Celebration:
    """One win, ready to take over a wall."""

    #: What a screen remembers having played.
    #:
    #: **A string, not the notification id**, because the same win can arrive
    #: twice: once because it just happened and again because somebody pressed
    #: replay. A numeric id would make the second one look like the first and
    #: a wall would skip the very thing it was asked to show.
    id: str
    title: str
    body: str | None
    about_name: str | None
    media_url: str | None
    media_kind: str | None
    #: The YouTube id, already extracted. Sent so the wall does not carry a
    #: second copy of the URL parsing — `media.youtube_id` is the one that knows
    #: which shapes are accepted, and it is already tested.
    media_id: str | None
    #: The stored file to play, for an uploaded clip. Extracted here for the
    #: same reason as `media_id`: the wall builds a URL from a digest and never
    #: learns what the `asset:` scheme is.
    media_digest: str | None
    media_start_seconds: int | None
    media_end_seconds: int | None
    #: How long this one should hold the screen, decided here rather than in the
    #: browser so the pacing is an operational setting.
    hold_seconds: int
    created_at: str
    #: When it takes over every screen on the channel, and when it lets go, in
    #: milliseconds since the epoch. See `_schedule`.
    starts_at: int = 0
    ends_at: int = 0
    #: When it became due: the win, or the moment somebody pressed replay.
    #: What the timetable is worked out from; not sent.
    due: datetime | None = None
    #: What the announcement is *for*, in a word or two a room reads at a
    #: glance — "Recognition", "Goal hit", or an achievement's own name. See
    #: `_occasion`.
    occasion: str = ""
    #: Which event it is, so a screen can draw the one that has a drawing of
    #: its own — the prize wheel spins before it says what it landed on.
    event_key: str = ""
    #: The number it was for, "$500" — the largest thing on the takeover
    #: (7.9). None for a win that is not about a number, a shout-out.
    figure: str | None = None
    #: Their photograph, inside the glow: a face is the most motivating thing
    #: a wall shows (7.9). The same picture a spotlight slide shows.
    photo_digest: str | None = None
    #: An announcement's own screen behind its words (Phase 25): an
    #: `appearance.Background` — a colour, a picture, a video, or a YouTube
    #: video filling the screen with the words over it.
    background: dict | None = None
    #: Its sound effect, a stored clip, played first; the video's own sound
    #: comes in when it ends.
    sound_digest: str | None = None


def announcement_celebration(item, id: str, created_at: str) -> Celebration:
    """An announcement as a wall takes it over with (Phase 25). Public so its
    preview, in the browser and on one TV, draws exactly what a wall will."""
    url = item.media_url or None
    return Celebration(
        id=id,
        title=item.title,
        body=item.body or None,
        about_name=None,
        media_url=url,
        media_kind=media_service.kind_of(url) if url else None,
        media_id=media_service.youtube_id(url) if url else None,
        media_digest=media_service.asset_digest(url) if url else None,
        media_start_seconds=item.media_start_seconds,
        media_end_seconds=None,
        hold_seconds=item.hold_seconds,
        created_at=created_at,
        # About nothing in particular: no "Goal hit" above the words.
        occasion="",
        event_key="announcement",
        background=item.background or None,
        sound_digest=media_service.asset_digest(item.sound_url) if item.sound_url else None,
    )


def _announcements(db: DbSession, org: Organization, channel: Channel, now: datetime) -> list[Celebration]:
    """Announcements sent to this wall in the last few minutes (Phase 25).

    Like a replay: somebody decided this is worth interrupting the room for,
    so it isn't filtered by `milestones`, and it takes its turn in the
    timetable from the moment it was sent.
    """
    since = now - timedelta(seconds=events.REPLAY_WINDOW_SECONDS)
    rows = db.execute(
        select(TvAnnouncementSend, TvAnnouncement)
        .join(TvAnnouncement, TvAnnouncement.id == TvAnnouncementSend.announcement_id)
        .where(
            TvAnnouncementSend.organization_id == org.id,
            TvAnnouncementSend.created_at >= since,
            or_(TvAnnouncementSend.channel_id.is_(None), TvAnnouncementSend.channel_id == channel.id),
        )
        .order_by(TvAnnouncementSend.created_at, TvAnnouncementSend.id)
    ).all()
    out = []
    for send, item in rows:
        shown = announcement_celebration(item, f"announcement:{send.id}", send.created_at.isoformat())
        shown.due = send.created_at
        out.append(shown)
    return out


def celebrations(
    db: DbSession,
    org: Organization,
    channel: Channel,
    *,
    now: datetime | None = None,
) -> list[Celebration]:
    """Wins from the last few minutes that this wall should interrupt itself for.

    **Nothing is marked as celebrated here.** `notification.celebrated_at` is
    per-person, for the overlay in the app; a wall has no person, and two
    televisions on the same channel should both show a win rather than racing to
    claim it. So the server offers a *window* — everything from the last
    `CELEBRATION_LIFETIME_SECONDS` — and each screen remembers what it has already
    played.

    That window is also what stops a television switched on in the morning firing
    a night's worth of celebrations back to back.

    Scoped by the same snapshot columns the achievements slide uses: a win belongs
    to the wall of the office somebody was in when they earned it, not the one
    they transferred to afterwards.
    """
    now = now or datetime.now(UTC)
    # The lookback the *timetable* is built from, which is longer than the
    # window a win is offered for — see `CELEBRATION_SYNC_LEAD_SECONDS`.
    since = now - timedelta(seconds=2 * events.CELEBRATION_LIFETIME_SECONDS)
    where = eligibility.channel_where(channel)
    # **The same name rule the rotation underneath obeys.** A lobby wall
    # careful about surnames on the leaderboard and careless about them in the
    # celebration that takes over the screen is not careful at all. There is no
    # screen or item here — a celebration belongs to the channel — so the chain
    # is two layers rather than four.
    look = appearance_service.resolve(org.appearance, channel.appearance)
    style = look.name_display
    # Only for the one style that needs them — see `_nicknames`. A wall not
    # asking for nicknames queries nothing.
    nicknames = (
        _celebration_nicknames(db, org) if style == "nickname" else {}
    )
    # How much this wall interrupts itself, which is a question about the room
    # rather than about the event — see `Appearance.milestones`.
    level = look.milestones or "all"

    conditions = [
        Notification.organization_id == org.id,
        Notification.created_at >= since,
        # Recorded, not announced (7.2) — a goal set already met.
        Notification.quiet.is_(False),
    ]
    if where.office_id is not None:
        conditions.append(Notification.about_office_id == where.office_id)
    if where.team_id is not None:
        conditions.append(Notification.about_team_id == where.team_id)

    rows = db.scalars(
        select(Notification)
        .where(*conditions)
        .order_by(Notification.created_at, Notification.id)
    ).all()

    out: list[Celebration] = []
    seen: set[tuple] = set()
    for row in rows:
        if not events.interrupts(row.event_key, level):
            continue
        # One per win, not one per recipient. A team goal reaching eight people
        # is eight rows and one thing that happened.
        key = (
            row.event_key,
            row.subject_type,
            row.subject_id,
            row.period_anchor,
        )
        if key in seen:
            continue
        seen.add(key)
        win = _as_celebration(
            row, f"win:{row.id}", style, nicknames.get(row.about_user_id),
            sounds=org.celebration_sounds,
            db=db,
        )
        win.due = row.created_at
        out.append(win)

    # A replay is due from the moment somebody pressed the button, not from
    # when the win first happened — so it takes its turn in the timetable with
    # everything else, rather than being filed under last Tuesday.
    out.extend(_replays(db, org, channel, now, style, nicknames))
    out.extend(_announcements(db, org, channel, now))

    scheduled = _schedule(out, cooldown=events.CELEBRATION_COOLDOWN_SECONDS)
    # Only what has not finished. A screen switched on in the morning is
    # offered nothing from the night before, because all of it has ended.
    stamp = _ms(now)
    return [item for item in scheduled if item.ends_at > stamp]


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _schedule(items: list[Celebration], *, cooldown: int) -> list[Celebration]:
    """Give every celebration the moment it takes over the screens.

    **One timetable for the whole channel**, worked out here, so that every
    television on it plays each win at the same instant rather than whenever it
    happened to poll. A screen does no scheduling of its own: it reads the
    start and end times and waits for them on a clock it has set by the
    server's.

    Each one starts a few seconds after it became due — long enough for every
    screen to have heard about it — and never before the one ahead of it has
    finished and the gap between them has passed. Starts land on a whole
    second, so screens rounding a few milliseconds differently cannot disagree
    about which second a win began.

    Pure, and in order of when each became due: the same list gives the same
    timetable whenever and wherever it is asked for, which is the whole point.
    """
    ordered = sorted(items, key=lambda item: (item.due or datetime.min.replace(tzinfo=UTC), item.id))
    free_at = 0
    for item in ordered:
        due = _ms(item.due) if item.due else 0
        earliest = due + events.CELEBRATION_SYNC_LEAD_SECONDS * 1000
        start = max(earliest, free_at)
        # Up to the next whole second.
        start = -(-start // 1000) * 1000
        item.starts_at = start
        item.ends_at = start + item.hold_seconds * 1000
        free_at = item.ends_at + cooldown * 1000
    return ordered


def _celebration_nicknames(db: DbSession, org: Organization) -> dict[int, str]:
    """Everybody in the organization who has one.

    The whole roster rather than the people in this window: a celebration feed
    is a handful of rows and the set of people with nicknames is smaller still,
    so one query beats working out which ids are needed first.
    """
    rows = db.execute(
        select(UserAccount.id, UserAccount.nickname).where(
            UserAccount.organization_id == org.id, UserAccount.nickname != ""
        )
    ).all()
    return {user_id: nickname for user_id, nickname in rows}


def _as_celebration(
    row: Notification,
    card_id: str,
    style: str,
    nickname: str | None = None,
    *,
    sounds: dict | None = None,
    db: DbSession | None = None,
) -> Celebration:
    """One notification, shaped for a wall.

    Shared by a fresh win and a replay so the two cannot drift: a replay that
    formatted names differently would be a privacy setting applied in one place
    and not the other.

    **A win with nothing to play gets the organization's sound for its kind**
    (6.17) — the person's own walk-up, frozen on the row, always comes first.
    Chosen here, when the wall asks, so a sound picked this morning plays for
    a win from a minute ago.
    """
    if not row.media_url:
        from app import sounds as sound_service

        fallback = sound_service.default_for(sounds, row.event_key)
        if fallback:
            row = _with_media(row, fallback)
    photo = None
    if db is not None and row.about_user_id is not None:
        person = db.get(UserAccount, row.about_user_id)
        photo = photo_service.digest_of(db, person) if person is not None else None
    return Celebration(
        id=card_id,
        title=row.title,
        body=row.body,
        about_name=(
            appearance_service.display_name(row.about_name, nickname, style)
            # A team's name is not a person's: "Enterprise" becoming "E." is a
            # bug rather than a privacy setting.
            if row.about_name and row.about_user_id is not None
            else row.about_name
        ),
        media_url=row.media_url,
        media_kind=(
            media_service.kind_of(row.media_url) if row.media_url else None
        ),
        media_id=(
            media_service.youtube_id(row.media_url) if row.media_url else None
        ),
        media_digest=(
            media_service.asset_digest(row.media_url) if row.media_url else None
        ),
        media_start_seconds=row.media_start_seconds,
        media_end_seconds=row.media_end_seconds,
        hold_seconds=_hold_for(row),
        created_at=row.created_at.isoformat(),
        occasion=_occasion(row),
        event_key=row.event_key,
        figure=row.figure,
        photo_digest=photo,
    )


#: The label over each kind of win.
_OCCASIONS = {
    events.GOAL_ACHIEVED.key: "Goal hit",
    **{event.key: "Stretch target hit" for event in events.GOAL_STRETCH},
    events.RECOGNITION.key: "Recognition",
    events.COMPETITION_WON.key: "Competition won",
    events.BIRTHDAY.key: "Happy birthday",
    events.WORK_ANNIVERSARY.key: "Work anniversary",
    events.WHEEL_WON.key: "Prize wheel",
}


def occasion_of(row: Notification) -> str:
    """What a win is for — public, because a chat card says it the same way a
    wall does. See `_occasion`."""
    return _occasion(row)


def _occasion(row: Notification) -> str:
    """What an announcement is for, said the way the room would say it.

    **The first thing anybody across the room reads**, so it is the kind of
    win rather than the details: "Recognition" tells a floor why the music
    started before anybody has read whose name it is. An achievement rule is
    named by whoever wrote it — "Big deal", "Five-star review" — and that name
    *is* the occasion, so it is used as it stands.
    """
    if row.event_key in _OCCASIONS:
        return _OCCASIONS[row.event_key]
    if row.event_key.startswith("achievement:"):
        return row.title
    return "Celebration"


def _replays(
    db: DbSession,
    org: Organization,
    channel: Channel,
    now: datetime,
    style: str,
    nicknames: dict[int, str],
) -> list[Celebration]:
    """Wins somebody asked this wall to play again.

    **Not filtered by `milestones`.** That setting is about which wins are
    worth interrupting a room for on their own; a replay is somebody deciding
    this one is, which is a stronger signal than any default. A quiet wall that
    ignored an explicit instruction would read as broken.

    **Nor by the celebration window.** A replay of a win from last Tuesday is
    the whole point of the feature — "the manager who missed it" missed it
    because it was not recent.
    """
    since = now - timedelta(seconds=events.REPLAY_WINDOW_SECONDS)
    rows = db.scalars(
        select(CelebrationReplay)
        .where(
            CelebrationReplay.organization_id == org.id,
            CelebrationReplay.created_at >= since,
            # NULL means every wall in the organization, which is what an admin
            # testing a fresh deployment wants before any channel exists.
            or_(
                CelebrationReplay.channel_id.is_(None),
                CelebrationReplay.channel_id == channel.id,
            ),
        )
        .order_by(CelebrationReplay.created_at, CelebrationReplay.id)
    ).all()

    out: list[Celebration] = []
    for replay in rows:
        row = db.get(Notification, replay.notification_id)
        if row is None:
            # Deleted, or aged out of the feed. Skipped rather than drawn
            # empty, the same as every other screen here.
            continue
        # The **replay's** id, so a wall that already played this win when it
        # happened plays it again rather than skipping what it was asked for.
        again = _as_celebration(
            row,
            f"replay:{replay.id}",
            style,
            nicknames.get(row.about_user_id),
            sounds=org.celebration_sounds,
            db=db,
        )
        again.due = replay.created_at
        out.append(again)
    return out


def _with_media(row: Notification, url: str):
    """The row as the wall should read it, with a sound it did not carry.
    A copy rather than the row itself: nothing here writes to the database."""
    from types import SimpleNamespace

    fields = {c.key: getattr(row, c.key) for c in Notification.__table__.columns}
    return SimpleNamespace(**{**fields, "media_url": url, "media_start_seconds": 0,
                              "media_end_seconds": None})


def _hold_for(row: Notification) -> int:
    """How long this celebration holds the screen. See `hold_for_clip`."""
    return hold_for_clip(row.media_url, row.media_start_seconds, row.media_end_seconds)


def hold_for_clip(url: str | None, start_seconds: int | None, end_seconds: int | None) -> int:
    """How long a celebration with this clip holds the screen.

    A clip plays to its end; anything else gets a fixed read-it-from-across-the-
    room duration. Cutting a walk-up song off halfway is worse than the extra few
    seconds, and the clip is already capped at fifteen by `media.MAX_CLIP_SECONDS`
    — which is the reason that cap exists.

    Public because the walk-up preview uses it too: a preview that held the
    screen for a different length from the wall would be previewing something
    else.
    """
    if not url:
        return events.CELEBRATION_HOLD_SECONDS
    start = start_seconds or 0
    end = end_seconds
    if end is None or end <= start:
        return media_service.MAX_CLIP_SECONDS
    return min(end - start, media_service.MAX_CLIP_SECONDS)


def _achievements(db, org, screen, narrow) -> Slide | None:
    """Recent wins, deduplicated the same way the Achievements page does.

    Public events only, decided by `events.is_public` rather than a list
    repeated here — being behind on a goal is a conversation with a manager,
    not something to put on a wall in front of the floor.
    """
    conditions = [Notification.organization_id == org.id]
    # The snapshot, not current membership: a win belongs to the wall of the
    # office somebody was in when they earned it, and a transfer must not move
    # last month's news to a different floor.
    if narrow.get("office_id") is not None:
        conditions.append(Notification.about_office_id == narrow["office_id"])
    if narrow.get("team_id") is not None:
        conditions.append(Notification.about_team_id == narrow["team_id"])

    rows = db.execute(
        select(Notification)
        .where(*conditions)
        .distinct(
            Notification.event_key,
            Notification.subject_type,
            Notification.subject_id,
            Notification.period_anchor,
        )
        .order_by(
            Notification.event_key,
            Notification.subject_type,
            Notification.subject_id,
            Notification.period_anchor,
            Notification.created_at.desc(),
        )
    ).scalars().all()

    recent = sorted(
        (n for n in rows if events.is_public(n.event_key)),
        key=lambda n: (n.created_at, n.id),
        reverse=True,
    )[:ACHIEVEMENTS_ON_SCREEN]

    if not recent:
        # Nothing to celebrate yet. An empty panel on a wall is worse than one
        # fewer slide in the rotation.
        return None

    # **Not "Recent" when they are not** (7.9): a wall presenting a week-old
    # win as news is how a room learns to stop reading it. A title somebody
    # typed is left alone.
    newest = recent[0].created_at
    stale = (datetime.now(UTC) - newest) > timedelta(hours=WINS_FRESH_HOURS)

    return Slide(
        id=screen.id,
        kind="achievements",
        dwell_seconds=screen.dwell_seconds,
        title=screen.title or ("Latest wins" if stale else "Recent wins"),
        achievements=[
            {
                "id": n.id,
                "about_name": n.about_name,
                #: Whether `about_name` is a person. A team's name must not be
                #: put through `display_name` — "Enterprise" becoming "E." is
                #: not a privacy setting, it is a bug.
                "about_person": n.about_user_id is not None,
                "about_user_id": n.about_user_id,
                "title": n.title,
                "body": n.body,
                "created_at": n.created_at,
                #: "$500" — said beside the name, as the takeover leads with it.
                "figure": n.figure,
            }
            for n in recent
        ],
    )


#: How old the newest win can be and still be called recent.
WINS_FRESH_HOURS = 24


#: How many recent wins a spotlight carries. Fewer than the achievements
#: screen: a spotlight is mostly a face, and a long list underneath turns it
#: back into the list screen it exists to be different from.
SPOTLIGHT_WINS = 3


def _spotlight(db, org, actor, screen, narrow) -> Slide | None:
    """One person, large.

    **The board-sourced form is the reason this exists.** A screen naming a
    person is an uploaded image with extra steps — it goes stale the moment
    somebody else overtakes them. A screen naming a *board* says "whoever is
    leading", and is right every time the wall refreshes.

    Both together mean "this person, on this board", which is how you keep a
    spotlight on the new starter you are trying to encourage rather than on
    whoever happens to be winning.
    """
    board = None
    metric = None
    if screen.leaderboard_id is not None:
        board = db.get(Leaderboard, screen.leaderboard_id)
        if board is None or board.archived_at is not None:
            return None
        # The same safety property as a leaderboard screen: a wall has no
        # audience control, so only an org-wide board may feed one.
        if board.visibility != "org":
            return None
        if board.entity_type != "user":
            # A team board has no face and no person to spotlight. Skipped
            # rather than drawn empty.
            return None
        metric = db.get(MetricDefinition, board.metric_definition_id)
        if metric is None:
            return None

    person = db.get(UserAccount, screen.user_id) if screen.user_id else None
    if person is not None and person.organization_id != org.id:
        return None

    entry = None
    total = 0
    period_label = None
    if board is not None:
        # `apply_limit=False`: a spotlight can be on somebody who is fortieth,
        # which is exactly who a manager wants to encourage. The board's own
        # "top 10" is a drawing decision for the board, not a filter on who
        # exists.
        result = board_service.run(db, org, actor, board, narrow=narrow, apply_limit=False)
        total = result.total_entrants
        period_label = result.period.label
        if person is None:
            entry = result.entries[0] if result.entries else None
            if entry is None:
                # Nobody on the board yet. An empty spotlight is worse than one
                # fewer slide, and the rotation moves past it.
                return None
            person = db.get(UserAccount, entry.entity_id)
        else:
            entry = next(
                (e for e in result.entries if e.entity_id == person.id), None
            )

    if person is None or person.hidden_at is not None:
        return None

    # Authoring refuses a person from a different office or team; this is the
    # second guard, for rows written before it did. See `eligibility`.
    if not eligibility.fits(
        eligibility.Where(
            office_id=narrow.get("office_id"), team_id=narrow.get("team_id")
        ),
        eligibility.person_where(db, person),
    ):
        return None

    team = db.get(Team, person.team_id) if person.team_id else None

    stats: list[dict] = []
    if entry is not None and metric is not None:
        stats = [
            {
                "label": metric.name,
                "value": entry.value,
                "unit": metric.unit,
                "decimal_places": metric.decimal_places,
                "unit_label": metric.unit_label,
                "rank": entry.rank,
                "movement": entry.movement,
                "of": total,
            }
        ]

    streak = None
    if metric is not None:
        streak = streak_service.current(
            db, org, metric_id=metric.id, user_id=person.id
        )

    wins = _wins_for(db, org, person)

    return Slide(
        id=screen.id,
        kind="spotlight",
        dwell_seconds=screen.dwell_seconds,
        title=screen.title or person.full_name,
        subtitle=(
            f"{board.name} · {period_label}"
            if board is not None
            else (person.job_title or None)
        ),
        person={
            "id": person.id,
            "name": person.full_name,
            "photo_digest": photo_service.digest_of(db, person),
            "job_title": person.job_title or None,
            "team_name": team.name if team else None,
        },
        stats=stats,
        streak_days=streak,
        achievements=wins,
    )


def _wins_for(db, org, person) -> list[dict]:
    """What this person has recently done that the floor may see.

    `events.is_public` decides, not a list repeated here — being behind on a
    goal is a conversation with a manager, not a line under somebody's
    photograph on a wall.
    """
    rows = db.scalars(
        select(Notification)
        .where(
            Notification.organization_id == org.id,
            Notification.about_user_id == person.id,
        )
        .distinct(
            Notification.event_key,
            Notification.subject_type,
            Notification.subject_id,
            Notification.period_anchor,
        )
        .order_by(
            Notification.event_key,
            Notification.subject_type,
            Notification.subject_id,
            Notification.period_anchor,
            Notification.created_at.desc(),
        )
    ).all()

    recent = sorted(
        (n for n in rows if events.is_public(n.event_key)),
        key=lambda n: (n.created_at, n.id),
        reverse=True,
    )[:SPOTLIGHT_WINS]

    return [
        {
            "id": n.id,
            "about_name": n.about_name,
            "about_person": n.about_user_id is not None,
            "about_user_id": n.about_user_id,
            "title": n.title,
            "body": n.body,
            "created_at": n.created_at,
        }
        for n in recent
    ]


#: How many rows each panel of a comparison shows.
#:
#: Fewer than a board's eight, because four panels of eight is thirty-two rows
#: on one television and nobody reads any of them. Five is enough to see the
#: shape of each column and still show somebody near the top of one and not the
#: other, which is the whole reason for putting them side by side.
COMPARISON_ROWS = 5


def _comparison(db, org, actor, screen, narrow) -> Slide | None:
    """Two to four boards on one slide.

    **A question no single board can answer.** "Who is calling and who is
    closing" is two boards, and a rotation showing them ninety seconds apart
    asks the room to hold one in their head while they wait for the other. Side
    by side, the person who is top of one and bottom of the other is visible in
    a glance.

    **What is left is drawn rather than the whole screen skipped.** A board that
    was archived or deleted takes its panel with it; a comparison of three that
    has become a comparison of two is still the comparison, and blanking it
    would punish the room for an edit made elsewhere.
    """
    panels = []
    for row in db.scalars(
        select(ChannelScreenBoard)
        .where(ChannelScreenBoard.channel_screen_id == screen.id)
        .order_by(ChannelScreenBoard.position, ChannelScreenBoard.id)
    ).all():
        panel = _panel(db, org, actor, row.leaderboard_id, narrow)
        if panel is not None:
            panels.append(panel)

    if not panels:
        return None

    return Slide(
        id=screen.id,
        kind="comparison",
        dwell_seconds=screen.dwell_seconds,
        # Named by the boards when nobody titled it, because "Comparison" on a
        # wall tells the room nothing it cannot already see.
        title=screen.title or " vs ".join(p["title"] for p in panels),
        panels=panels,
    )


def _panel(db, org, actor, leaderboard_id, narrow) -> dict | None:
    """One column of a comparison, shaped like a leaderboard slide.

    The same fields rather than a smaller bespoke set, so the wall draws a
    panel with the component it already has for a board — and a change to how
    a board renders reaches both.
    """
    board = db.get(Leaderboard, leaderboard_id)
    if board is None or board.archived_at is not None:
        return None
    # The safety property from Phase 1 again: a wall has no audience control.
    if board.visibility != "org":
        return None

    metric = db.get(MetricDefinition, board.metric_definition_id)
    if metric is None:
        return None

    result = board_service.run(db, org, actor, board, narrow=narrow)
    return {
        "title": board.name,
        "subtitle": f"{metric.name} · {result.period.label}",
        "entries": [vars(entry) for entry in result.entries[:COMPARISON_ROWS]],
        "total_entrants": result.total_entrants,
        "entity_type": board.entity_type,
        "unit": metric.unit,
        "decimal_places": metric.decimal_places,
        "unit_label": metric.unit_label,
        "direction": metric.direction,
    }
