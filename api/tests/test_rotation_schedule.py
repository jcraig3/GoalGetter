"""When a slide plays, how often, and a wall's night mode (6.10).

Scheduling is worked out on the server, in the organization's time, so these
check the rules themselves, then the rotation a television is handed, then the
API that sets them.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app import channels as channel_service, schedule
from app.models import Channel, Notification
from tests.test_channels import add, make_board, make_channel, token_for, world  # noqa: F401

NY = ZoneInfo("America/New_York")

#: A Wednesday, in the conftest organization's zone.
WEDNESDAY_NOON = datetime(2026, 9, 30, 12, 0, tzinfo=NY)
assert WEDNESDAY_NOON.weekday() == 2


# ── The rules ────────────────────────────────────────────────────────────────


def test_no_schedule_plays_always():
    assert schedule.plays_now(None, None, None, WEDNESDAY_NOON)


def test_days_choose_the_days():
    assert schedule.plays_now([2], None, None, WEDNESDAY_NOON)
    assert not schedule.plays_now([0, 1, 3, 4], None, None, WEDNESDAY_NOON)


def test_hours_choose_the_hours():
    assert schedule.plays_now(None, time(9), time(17), WEDNESDAY_NOON)
    assert not schedule.plays_now(None, time(13), time(17), WEDNESDAY_NOON)
    # The end is exclusive: until noon is over at noon.
    assert not schedule.plays_now(None, time(9), time(12), WEDNESDAY_NOON)


def test_either_end_can_be_open():
    assert schedule.plays_now(None, time(11), None, WEDNESDAY_NOON)
    assert not schedule.plays_now(None, None, time(11), WEDNESDAY_NOON)


def test_a_window_can_cross_midnight():
    late = WEDNESDAY_NOON.replace(hour=23)
    early = WEDNESDAY_NOON.replace(hour=1)
    assert schedule.plays_now(None, time(22), time(2), late)
    assert schedule.plays_now(None, time(22), time(2), early)
    assert not schedule.plays_now(None, time(22), time(2), WEDNESDAY_NOON)


def test_the_small_hours_belong_to_the_night_before():
    """Fridays 22:00–02:00 is still playing at one on Saturday morning — and
    not at one on Friday morning, which is Thursday night's."""
    saturday_1am = datetime(2026, 10, 3, 1, 0, tzinfo=NY)
    friday_1am = datetime(2026, 10, 2, 1, 0, tzinfo=NY)
    assert schedule.plays_now([4], time(22), time(2), saturday_1am)
    assert not schedule.plays_now([4], time(22), time(2), friday_1am)


def test_weight_spreads_rather_than_stacks():
    """Three times a cycle means spaced out, never three in a row."""
    out = schedule.weighted([("A", 3), ("B", 1), ("C", 1)])
    assert sorted(out) == ["A", "A", "A", "B", "C"]
    assert all(not (x == y == "A") for x, y in zip(out, out[1:]))


def test_weight_of_one_is_the_order_as_written():
    assert schedule.weighted([("A", 1), ("B", 1), ("C", 1)]) == ["A", "B", "C"]


def test_weight_is_clamped():
    assert len(schedule.weighted([("A", 99), ("B", 0)])) == schedule.MAX_WEIGHT + 1


def test_night_mode_off_is_never_quiet():
    assert schedule.quiet_now("off", time(0), time(23), True, WEDNESDAY_NOON) is None


def test_night_mode_in_its_hours():
    evening = WEDNESDAY_NOON.replace(hour=20)
    quiet = schedule.quiet_now("clock", time(19), time(7), False, evening)
    assert quiet is not None and quiet.mode == "clock"
    assert quiet.until == datetime(2026, 10, 1, 7, 0, tzinfo=NY)
    assert schedule.quiet_now("clock", time(19), time(7), False, WEDNESDAY_NOON) is None


def test_night_mode_on_weekends_lasts_until_monday():
    saturday = datetime(2026, 10, 3, 12, 0, tzinfo=NY)
    quiet = schedule.quiet_now("dark", time(19), time(7), True, saturday)
    assert quiet is not None
    # Through Sunday night and the small hours of Monday, until seven.
    assert quiet.until == datetime(2026, 10, 5, 7, 0, tzinfo=NY)


# ── The rotation a television is handed ──────────────────────────────────────


def _channel_with(db, org, *screens):
    from app.models import ChannelScreen

    channel = Channel(organization_id=org.id, name="Wall")
    db.add(channel)
    db.flush()
    for i, fields in enumerate(screens):
        db.add(ChannelScreen(channel_id=channel.id, position=i, kind="message", **fields))
    db.flush()
    return channel


def test_a_slide_out_of_hours_is_left_out(db, org):
    channel = _channel_with(
        db, org,
        {"title": "Always"},
        {"title": "Mornings", "play_from": time(8), "play_until": time(11)},
    )
    slides = channel_service.build(db, org, channel, now=WEDNESDAY_NOON)
    assert [s.title for s in slides] == ["Always"]


def test_a_weighted_slide_comes_round_more(db, org):
    channel = _channel_with(
        db, org, {"title": "Big", "weight": 2}, {"title": "Small"}
    )
    slides = channel_service.build(db, org, channel, now=WEDNESDAY_NOON)
    assert [s.title for s in slides] == ["Big", "Small", "Big"]


def test_nothing_scheduled_shows_the_clock(db, org):
    """Not a black screen that looks broken."""
    channel = _channel_with(
        db, org, {"title": "Mornings", "play_from": time(8), "play_until": time(11)}
    )
    quiet = channel_service.quiet(db, org, channel, now=WEDNESDAY_NOON)
    assert quiet is not None and quiet.mode == "clock"


def test_an_empty_channel_is_not_quiet(db, org):
    """Still being set up, and the wall keeps saying so."""
    channel = _channel_with(db, org)
    assert channel_service.quiet(db, org, channel, now=WEDNESDAY_NOON) is None


def test_night_mode_wins_over_the_rotation(db, org):
    channel = _channel_with(db, org, {"title": "Always"})
    channel.quiet_mode = "dark"
    channel.quiet_from, channel.quiet_until = time(19), time(7)
    night = WEDNESDAY_NOON.replace(hour=22)
    assert channel_service.quiet(db, org, channel, now=night).mode == "dark"
    assert channel_service.quiet(db, org, channel, now=WEDNESDAY_NOON) is None


# ── Setting it ───────────────────────────────────────────────────────────────


def test_a_slides_schedule_round_trips(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    body = add(
        client, channel["id"], kind="message", title="Hello",
        days=[4, 0, 0], play_from="09:00", play_until="17:30", weight=3,
    ).json()
    screen = body["screens"][0]
    assert screen["days"] == [0, 4]
    assert screen["play_from"] == "09:00:00"
    assert screen["play_until"] == "17:30:00"
    assert screen["weight"] == 3


def test_every_day_is_stored_as_every_day(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    body = add(client, channel["id"], kind="message", title="Hi", days=list(range(7))).json()
    assert body["screens"][0]["days"] is None


def test_no_days_at_all_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    response = add(client, channel["id"], kind="message", title="Hi", days=[])
    assert response.status_code == 422


def test_weight_past_four_is_refused(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    assert add(client, channel["id"], kind="message", title="Hi", weight=5).status_code == 422


def test_night_mode_needs_hours_or_weekends(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.post("/api/channels", json={"name": "W", "quiet_mode": "clock"})
    assert response.status_code == 422
    response = client.post(
        "/api/channels",
        json={"name": "W", "quiet_mode": "clock", "quiet_weekends": True},
    )
    assert response.status_code == 201


def test_night_mode_round_trips_and_is_copied(client, db, world, sign_in):
    sign_in(world["admin"])
    channel = client.post(
        "/api/channels",
        json={"name": "W", "quiet_mode": "dark", "quiet_from": "19:00", "quiet_until": "07:00"},
    ).json()
    assert channel["quiet_mode"] == "dark"
    assert channel["quiet_from"] == "19:00:00"
    add(client, channel["id"], kind="message", title="Hi", weight=2, play_from="09:00")

    copy = client.post(f"/api/channels/{channel['id']}/duplicate").json()
    assert copy["quiet_mode"] == "dark"
    assert copy["quiet_until"] == "07:00:00"
    assert copy["screens"][0]["weight"] == 2
    assert copy["screens"][0]["play_from"] == "09:00:00"


# ── On the television ────────────────────────────────────────────────────────


def _around_now(org_tz: str) -> tuple[str, str]:
    """A night-mode window that contains this moment, wherever the clock is."""
    now = datetime.now(ZoneInfo(org_tz))
    start = (now - timedelta(hours=1)).strftime("%H:%M")
    end = (now + timedelta(hours=1)).strftime("%H:%M")
    return start, end


def test_a_quiet_wall_is_told_so_and_sent_no_slides(client, db, org, world, sign_in):
    sign_in(world["admin"])
    start, end = _around_now(org.timezone)
    channel = client.post(
        "/api/channels",
        json={"name": "W", "quiet_mode": "clock", "quiet_from": start, "quiet_until": end},
    ).json()
    add(client, channel["id"], kind="message", title="Hello")
    token = token_for(client, channel["id"])
    client.cookies.clear()

    body = client.get(f"/api/display/{token}").json()
    assert body["quiet"]["mode"] == "clock"
    assert body["quiet"]["until"] is not None
    assert body["slides"] == []
    assert body["time_zone"] == org.timezone


def test_an_ordinary_wall_is_not_quiet(client, db, org, world, sign_in):
    sign_in(world["admin"])
    channel = make_channel(client)
    add(client, channel["id"], kind="message", title="Hello")
    token = token_for(client, channel["id"])
    client.cookies.clear()

    body = client.get(f"/api/display/{token}").json()
    assert body["quiet"] is None
    assert [s["title"] for s in body["slides"]] == ["Hello"]


def test_night_mode_holds_celebrations_back(client, db, org, world, sign_in):
    """A win at two in the morning lighting up an empty office helps nobody."""
    sign_in(world["admin"])
    start, end = _around_now(org.timezone)
    channel = client.post(
        "/api/channels",
        json={"name": "W", "quiet_mode": "dark", "quiet_from": start, "quiet_until": end},
    ).json()
    token = token_for(client, channel["id"])
    db.add(
        Notification(
            organization_id=org.id,
            user_id=world["alice"].id,
            event_key="goal.achieved",
            subject_type="goal",
            subject_id=1,
            title="Alice hit her target",
            about_user_id=world["alice"].id,
            created_at=datetime.now(UTC),
        )
    )
    db.flush()
    client.cookies.clear()
    assert client.get(f"/api/display/{token}/celebrations").json()["celebrations"] == []

    # The same win, the moment night mode is off, takes over.
    db.get(Channel, channel["id"]).quiet_mode = "off"
    db.flush()
    found = client.get(f"/api/display/{token}/celebrations").json()["celebrations"]
    assert [c["title"] for c in found] == ["Alice hit her target"]
