"""What a wall interrupts itself for.

The rotation is the steady state; a celebration is the exception that stops it.
So the bar is higher than for the achievements slide: that shows everything
**public**, this shows only what is worth **interrupting** for.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import channels as channel_service, events
from app.models import Channel, ChannelScreen, Display, Notification, Office

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


@pytest.fixture
def world(db, org, make_team, make_user):
    phoenix = Office(organization_id=org.id, name="Phoenix")
    dallas = Office(organization_id=org.id, name="Dallas")
    db.add_all([phoenix, dallas])
    db.flush()

    enterprise = make_team("Enterprise")
    east = make_team("East")
    enterprise.office_id = phoenix.id
    east.office_id = dallas.id
    db.flush()

    return {
        "phoenix": phoenix,
        "dallas": dallas,
        "enterprise": enterprise,
        "east": east,
        "alice": make_user("agent", enterprise, name="Alice"),
        "bob": make_user("agent", enterprise, name="Bob"),
        "dan": make_user("agent", east, name="Dan"),
    }


def make_channel(db, org, *, scope_type="organization", **scope):
    channel = Channel(
        organization_id=org.id, name="Wall", scope_type=scope_type, **scope
    )
    db.add(channel)
    db.flush()
    return channel


def win(
    db,
    org,
    person,
    *,
    event="goal.achieved",
    at=NOW,
    subject_id=1,
    office_id=None,
    team_id=None,
    media=None,
    title="Alice hit her target",
):
    row = Notification(
        organization_id=org.id,
        user_id=person.id,
        event_key=event,
        subject_type="goal",
        subject_id=subject_id,
        title=title,
        about_name=person.full_name,
        about_user_id=person.id,
        about_office_id=office_id,
        about_team_id=team_id,
        created_at=at,
    )
    if media:
        row.media_url, row.media_start_seconds, row.media_end_seconds = media
    db.add(row)
    db.flush()
    return row


# ── What qualifies ───────────────────────────────────────────────────────────


def test_a_win_from_a_moment_ago_takes_over(db, org, world):
    """A moment ago meaning *before its slot has finished*. Since 4k every
    screen on a channel plays a win at the same instant, so a screen asking
    after the slot has ended is not handed it to play late — that would put it
    out of step with every other screen in the room."""
    channel = make_channel(db, org)
    win(db, org, world["alice"], at=NOW - timedelta(seconds=2))

    found = channel_service.celebrations(db, org, channel, now=NOW)

    assert [c.title for c in found] == ["Alice hit her target"]
    assert found[0].about_name == "Alice"


def test_an_old_win_does_not(db, org, world):
    """Past the lifetime it is not "just happened" any more, and the achievements
    slide in the rotation is where it belongs instead."""
    channel = make_channel(db, org)
    win(
        db, org, world["alice"],
        at=NOW - timedelta(seconds=events.CELEBRATION_LIFETIME_SECONDS + 60),
    )

    assert channel_service.celebrations(db, org, channel, now=NOW) == []


def test_a_screen_switched_on_in_the_morning_does_not_replay_the_night(
    db, org, world
):
    """The window is what bounds a reload. Without it, a television coming back
    would fire every celebration it missed, one after another."""
    channel = make_channel(db, org)
    for hour in range(1, 10):
        win(db, org, world["alice"], at=NOW - timedelta(hours=hour), subject_id=hour)

    assert channel_service.celebrations(db, org, channel, now=NOW) == []


def test_only_events_worth_interrupting_for(db, org, world):
    """`celebrate`, not `public`. The achievements slide shows everything public;
    this stops the room."""
    channel = make_channel(db, org)
    win(db, org, world["alice"], event="goal.achieved", subject_id=1)
    win(db, org, world["alice"], event="competition.won", subject_id=2)
    win(db, org, world["alice"], event="recognition", subject_id=3)
    # Public in neither sense, and private ones must not leak onto a wall.
    win(db, org, world["alice"], event="goal.period_ending", subject_id=4)
    win(db, org, world["alice"], event="competition.finished", subject_id=5)
    win(db, org, world["alice"], event="goal.assigned", subject_id=6)

    found = channel_service.celebrations(db, org, channel, now=NOW)

    assert {c.id for c in found} == {
        f"win:{n.id}"
        for n in db.scalars(select(Notification)).all()
        if n.event_key in ("goal.achieved", "competition.won", "recognition")
    }


def test_a_private_celebration_never_reaches_a_wall(db, org, world):
    """The distinction no current event exercises, and the reason the predicate
    is a conjunction.

    `public` is permission — a screen is read by whoever walks past. `celebrate`
    is significance. Today every public event is also a celebration, so swapping
    one for the other changes nothing and a mutation doing so survives the whole
    suite. An event worth interrupting one *person* with but not worth putting on
    a wall is an obvious thing to add later, and it must not land on the wall by
    default.
    """
    private_party = events.EventType("private.party", public=False, celebrate=True)
    events.CATALOGUE[private_party.key] = private_party
    try:
        channel = make_channel(db, org)
        win(db, org, world["alice"], event="private.party")

        assert channel_service.celebrations(db, org, channel, now=NOW) == []
    finally:
        del events.CATALOGUE[private_party.key]


def test_a_public_non_celebration_does_not_interrupt_either(db, org, world):
    """The other half. It belongs on the achievements slide, not over the top of
    whatever the room was reading."""
    quiet_news = events.EventType("quiet.news", public=True, celebrate=False)
    events.CATALOGUE[quiet_news.key] = quiet_news
    try:
        channel = make_channel(db, org)
        win(db, org, world["alice"], event="quiet.news")

        assert channel_service.celebrations(db, org, channel, now=NOW) == []
    finally:
        del events.CATALOGUE[quiet_news.key]


def test_an_unknown_event_key_is_ignored(db, org, world):
    """A newer API's row seen by older code. Skipping keeps the wall running."""
    channel = make_channel(db, org)
    win(db, org, world["alice"], event="something.invented.later")

    assert channel_service.celebrations(db, org, channel, now=NOW) == []


def test_one_celebration_per_win_not_per_recipient(db, org, world):
    """A team goal reaching eight people is eight rows and one thing that
    happened. Without this the wall celebrates it eight times in a row."""
    channel = make_channel(db, org)
    for person in (world["alice"], world["bob"], world["dan"]):
        win(db, org, person, subject_id=7, title="Enterprise hit its target")

    assert len(channel_service.celebrations(db, org, channel, now=NOW)) == 1


# ── Whose wall ───────────────────────────────────────────────────────────────


def test_a_phoenix_win_does_not_interrupt_a_dallas_wall(db, org, world):
    dallas_wall = make_channel(
        db, org, scope_type="office", scope_office_id=world["dallas"].id
    )
    win(db, org, world["alice"], office_id=world["phoenix"].id)

    assert channel_service.celebrations(db, org, dallas_wall, now=NOW) == []


def test_a_phoenix_win_interrupts_the_phoenix_wall(db, org, world):
    phoenix_wall = make_channel(
        db, org, scope_type="office", scope_office_id=world["phoenix"].id
    )
    win(db, org, world["alice"], office_id=world["phoenix"].id)

    assert len(channel_service.celebrations(db, org, phoenix_wall, now=NOW)) == 1


def test_the_snapshot_decides_not_current_membership(db, org, world):
    """A win belongs to the wall of the office somebody was in when they earned
    it. Transferring must not move last week's news to a different floor."""
    phoenix_wall = make_channel(
        db, org, scope_type="office", scope_office_id=world["phoenix"].id
    )
    win(db, org, world["alice"], office_id=world["phoenix"].id)

    # Alice moves to Dallas afterwards.
    world["alice"].team_id = world["east"].id
    db.flush()

    assert len(channel_service.celebrations(db, org, phoenix_wall, now=NOW)) == 1


def test_an_organization_wide_wall_takes_everything(db, org, world):
    channel = make_channel(db, org)
    win(db, org, world["alice"], office_id=world["phoenix"].id, subject_id=1)
    win(db, org, world["dan"], office_id=world["dallas"].id, subject_id=2)

    assert len(channel_service.celebrations(db, org, channel, now=NOW)) == 2


def test_another_organizations_win_never_appears(db, org, world, make_user):
    from app.models import Organization

    channel = make_channel(db, org)
    other = Organization(name="Rival", timezone="UTC")
    db.add(other)
    db.flush()
    db.add(
        Notification(
            organization_id=other.id,
            user_id=world["alice"].id,
            event_key="goal.achieved",
            subject_type="goal",
            subject_id=99,
            title="Their win",
            created_at=NOW,
        )
    )
    db.flush()

    assert channel_service.celebrations(db, org, channel, now=NOW) == []


# ── How long it holds ────────────────────────────────────────────────────────


def test_without_media_it_holds_the_fixed_duration(db, org, world):
    channel = make_channel(db, org)
    win(db, org, world["alice"])

    found = channel_service.celebrations(db, org, channel, now=NOW)

    assert found[0].hold_seconds == events.CELEBRATION_HOLD_SECONDS
    assert found[0].media_url is None


def test_with_a_clip_it_holds_for_the_clip(db, org, world):
    """Cutting a walk-up off halfway is worse than the extra few seconds."""
    channel = make_channel(db, org)
    win(
        db, org, world["alice"],
        media=("https://www.youtube.com/watch?v=abcdefghijk", 30, 42),
    )

    found = channel_service.celebrations(db, org, channel, now=NOW)

    assert found[0].hold_seconds == 12
    assert found[0].media_kind == "youtube"


def test_a_clip_cannot_hold_the_screen_indefinitely(db, org, world):
    """The cap `media.MAX_CLIP_SECONDS` exists for exactly this — it is why a
    walk-up is fifteen seconds and not a whole song."""
    from app import media as media_service

    channel = make_channel(db, org)
    win(
        db, org, world["alice"],
        media=("https://www.youtube.com/watch?v=abcdefghijk", 0, 600),
    )

    found = channel_service.celebrations(db, org, channel, now=NOW)

    assert found[0].hold_seconds == media_service.MAX_CLIP_SECONDS


def test_a_clip_with_no_end_falls_back_to_the_cap(db, org, world):
    from app import media as media_service

    channel = make_channel(db, org)
    win(
        db, org, world["alice"],
        media=("https://media.giphy.com/x.gif", None, None),
    )

    assert (
        channel_service.celebrations(db, org, channel, now=NOW)[0].hold_seconds
        == media_service.MAX_CLIP_SECONDS
    )


def test_they_arrive_oldest_first(db, org, world):
    """So the room sees them in the order they happened. Newest-first would
    celebrate the second win before the first."""
    channel = make_channel(db, org)
    win(db, org, world["alice"], at=NOW - timedelta(seconds=3), subject_id=1,
        title="First")
    win(db, org, world["bob"], at=NOW - timedelta(seconds=1), subject_id=2,
        title="Second")

    assert [c.title for c in channel_service.celebrations(db, org, channel, now=NOW)] == [
        "First",
        "Second",
    ]


# ── Over HTTP ────────────────────────────────────────────────────────────────


def test_the_endpoint_serves_a_wall(client, db, org, world):
    channel = make_channel(db, org)
    display = Display(
        organization_id=org.id, channel_id=channel.id, name="TV", token="tok-celebrate"
    )
    db.add(display)
    db.flush()
    win(db, org, world["alice"], at=datetime.now(UTC))
    db.commit()

    response = client.get("/api/display/tok-celebrate/celebrations")

    assert response.status_code == 200
    data = response.json()
    assert [c["title"] for c in data["celebrations"]] == ["Alice hit her target"]
    assert data["cooldown_seconds"] == events.CELEBRATION_COOLDOWN_SECONDS


def test_a_revoked_token_gets_nothing(client, db, org):
    assert client.get("/api/display/not-a-token/celebrations").status_code == 404


def test_nothing_recent_is_an_empty_list_not_an_error(client, db, org, world):
    """A quiet hour is the normal case, and a wall must not treat it as a
    failure."""
    channel = make_channel(db, org)
    db.add(
        Display(
            organization_id=org.id, channel_id=channel.id, name="TV", token="tok-quiet"
        )
    )
    db.flush()
    db.commit()

    response = client.get("/api/display/tok-quiet/celebrations")

    assert response.status_code == 200
    assert response.json()["celebrations"] == []


# ── One timetable for every screen ───────────────────────────────────────────


def ms(moment):
    return int(moment.timestamp() * 1000)


def test_a_win_starts_a_few_seconds_after_it_happened_on_a_whole_second(
    db, org, world
):
    """Long enough for every screen to have heard about it, and on a whole
    second so screens rounding differently cannot disagree about which second
    it began."""
    channel = make_channel(db, org)
    happened = NOW - timedelta(seconds=1, milliseconds=300)
    win(db, org, world["alice"], at=happened)

    found = channel_service.celebrations(db, org, channel, now=NOW)[0]

    assert found.starts_at >= ms(happened) + events.CELEBRATION_SYNC_LEAD_SECONDS * 1000
    assert found.starts_at % 1000 == 0
    assert found.ends_at == found.starts_at + found.hold_seconds * 1000


def test_two_screens_asking_at_different_moments_get_the_same_timetable(
    db, org, world
):
    """**The property the whole feature rests on.** A screen that polled a
    second later must be told exactly the same start times, or the room sees
    two screens out of step."""
    channel = make_channel(db, org)
    win(db, org, world["alice"], at=NOW - timedelta(seconds=2), subject_id=1)
    win(db, org, world["bob"], at=NOW - timedelta(seconds=1), subject_id=2)

    early = channel_service.celebrations(db, org, channel, now=NOW)
    later = channel_service.celebrations(db, org, channel, now=NOW + timedelta(seconds=2))

    assert [c.starts_at for c in early] == [c.starts_at for c in later]


def test_the_second_waits_for_the_first_and_the_gap(db, org, world):
    """Without the gap, four wins in the same minute strobe."""
    channel = make_channel(db, org)
    win(db, org, world["alice"], at=NOW - timedelta(seconds=2), subject_id=1)
    win(db, org, world["bob"], at=NOW - timedelta(seconds=1), subject_id=2)

    first, second = channel_service.celebrations(db, org, channel, now=NOW)

    assert second.starts_at >= first.ends_at + events.CELEBRATION_COOLDOWN_SECONDS * 1000


def test_a_finished_one_is_not_offered_to_play_late(db, org, world):
    channel = make_channel(db, org)
    win(db, org, world["alice"], at=NOW - timedelta(seconds=2))
    found = channel_service.celebrations(db, org, channel, now=NOW)[0]
    after = datetime.fromtimestamp(found.ends_at / 1000 + 1, tz=NOW.tzinfo)

    assert channel_service.celebrations(db, org, channel, now=after) == []


def test_one_still_playing_is_offered_so_a_screen_can_join_it(db, org, world):
    """A screen switched on mid-celebration joins it for the time that is left,
    in step with the rest, rather than starting it over."""
    channel = make_channel(db, org)
    win(db, org, world["alice"], at=NOW - timedelta(seconds=2))
    found = channel_service.celebrations(db, org, channel, now=NOW)[0]
    during = datetime.fromtimestamp(found.starts_at / 1000 + 1, tz=NOW.tzinfo)

    assert len(channel_service.celebrations(db, org, channel, now=during)) == 1


# ── The figure and the face (7.9) ────────────────────────────────────────────


def test_a_win_brings_its_figure_and_their_photo(db, org, world):
    """The takeover leads with the number and shows the person: "$500" huge,
    their photo inside the glow."""
    import io

    from PIL import Image

    from app import photos

    buffer = io.BytesIO()
    Image.new("RGB", (256, 256), (255, 0, 0)).save(buffer, format="PNG")
    stored = photos.set_custom(db, world["alice"], buffer.getvalue())
    row = win(db, org, world["alice"], at=NOW - timedelta(seconds=2))
    row.figure = "$500"
    db.flush()

    [found] = channel_service.celebrations(db, org, make_channel(db, org), now=NOW)

    assert found.figure == "$500"
    assert found.photo_digest == stored.sha256


def test_a_team_win_has_no_photo(db, org, world):
    row = win(db, org, world["alice"], at=NOW - timedelta(seconds=2))
    row.about_user_id = None
    row.about_team_id = world["enterprise"].id
    db.flush()

    [found] = channel_service.celebrations(db, org, make_channel(db, org), now=NOW)

    assert found.photo_digest is None
    assert found.figure is None
