"""Announcements for the TVs: designed, saved, sent and sent again (Phase 25)."""

import pytest
from sqlalchemy import select

from app import assets
from app import channels as channel_service
from app.models import AuditLog, Channel, TvAnnouncement, TvAnnouncementSend

YOUTUBE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin"))


def make_channel(db, org, name="Wall"):
    channel = Channel(organization_id=org.id, name=name, scope_type="organization")
    db.add(channel)
    db.flush()
    return channel


def stored(db, org, content_type, data):
    return assets.keep(db, org.id, data, content_type=content_type).sha256


def create(client, **fields):
    body = {"title": "Lunch is here", **fields}
    reply = client.post("/api/tv-announcements", json=body)
    assert reply.status_code == 201, reply.text
    return reply.json()


def test_an_announcement_is_saved_with_its_look(client, admin, org):
    made = create(
        client,
        body="In the kitchen",
        hold_seconds=20,
        background={"kind": "youtube", "asset": "dQw4w9WgXcQ"},
        media_url=YOUTUBE,
        media_start_seconds=30,
    )
    assert made["background"] == {"kind": "youtube", "asset": "dQw4w9WgXcQ"}
    assert made["media_kind"] == "youtube"
    assert made["times_sent"] == 0
    assert [row["title"] for row in client.get("/api/tv-announcements").json()] == ["Lunch is here"]


def test_a_manager_makes_them_too(client, make_user, sign_in, org):
    sign_in(make_user("manager"))
    assert client.post("/api/tv-announcements", json={"title": "Huddle"}).status_code == 201


def test_an_agent_does_not(client, make_user, sign_in, org):
    sign_in(make_user("agent"))
    assert client.post("/api/tv-announcements", json={"title": "Nope"}).status_code == 403
    assert client.get("/api/tv-announcements").status_code == 403


def test_library_files_are_checked(client, admin, db, org):
    picture = stored(db, org, "image/png", b"png-bytes")
    sound = stored(db, org, "audio/mpeg", b"mp3-bytes")
    db.commit()
    made = create(client, media_url=f"image:{picture}", sound_url=f"asset:{sound}")
    assert made["media_kind"] == "image"
    # A sound where a picture goes, a picture where the sound goes, a file
    # that isn't there.
    for fields in (
        {"media_url": f"image:{sound}"},
        {"sound_url": f"asset:{picture}"},
        {"media_url": "video:" + "0" * 64},
    ):
        reply = client.post("/api/tv-announcements", json={"title": "x", **fields})
        assert reply.status_code == 400, fields


def test_a_link_must_be_youtube_or_a_picture(client, admin):
    reply = client.post("/api/tv-announcements", json={"title": "x", "media_url": "https://example.com/page"})
    assert reply.status_code == 400


def test_sending_puts_it_on_every_wall(client, admin, db, org):
    wall = make_channel(db, org)
    sound = stored(db, org, "audio/mpeg", b"mp3-bytes")
    db.commit()
    made = create(client, background={"kind": "solid", "color": "#112233"}, sound_url=f"asset:{sound}")
    reply = client.post(f"/api/tv-announcements/{made['id']}/send", json={})
    assert reply.json() == {"channels": 0, "everywhere": True}

    shown = [c for c in channel_service.celebrations(db, org, wall) if c.event_key == "announcement"]
    assert len(shown) == 1
    assert shown[0].title == "Lunch is here"
    assert shown[0].background == {"kind": "solid", "color": "#112233"}
    assert shown[0].sound_digest == sound
    assert shown[0].occasion == ""
    assert client.get("/api/tv-announcements").json()[0]["times_sent"] == 1


def test_sending_to_chosen_channels_only(client, admin, db, org):
    lobby, floor = make_channel(db, org, "Lobby"), make_channel(db, org, "Floor")
    db.commit()
    made = create(client)
    reply = client.post(f"/api/tv-announcements/{made['id']}/send", json={"channel_ids": [floor.id]})
    assert reply.json() == {"channels": 1, "everywhere": False}
    assert any(c.event_key == "announcement" for c in channel_service.celebrations(db, org, floor))
    assert not any(c.event_key == "announcement" for c in channel_service.celebrations(db, org, lobby))


def test_sent_again_it_plays_again(client, admin, db, org):
    wall = make_channel(db, org)
    db.commit()
    made = create(client)
    client.post(f"/api/tv-announcements/{made['id']}/send", json={})
    client.post(f"/api/tv-announcements/{made['id']}/send", json={})
    shown = [c for c in channel_service.celebrations(db, org, wall) if c.event_key == "announcement"]
    assert len({c.id for c in shown}) == 2


def test_another_organizations_channel_is_refused(client, admin, db, org):
    from app.models import Organization

    other = Organization(name="Elsewhere")
    db.add(other)
    db.flush()
    elsewhere = make_channel(db, other, "Theirs")
    db.commit()
    made = create(client)
    reply = client.post(f"/api/tv-announcements/{made['id']}/send", json={"channel_ids": [elsewhere.id]})
    assert reply.status_code == 400


def test_editing_and_deleting(client, admin, db, org):
    made = create(client)
    reply = client.patch(f"/api/tv-announcements/{made['id']}", json={"title": "Pizza is here", "hold_seconds": 30})
    assert reply.json()["title"] == "Pizza is here"
    client.post(f"/api/tv-announcements/{made['id']}/send", json={})
    assert client.delete(f"/api/tv-announcements/{made['id']}").status_code == 204
    assert db.scalar(select(TvAnnouncementSend)) is None
    actions = db.scalars(select(AuditLog.action).where(AuditLog.action.like("announcement.%"))).all()
    assert set(actions) == {"announcement.created", "announcement.updated", "announcement.sent", "announcement.deleted"}


def test_the_preview_is_what_a_wall_would_show_and_saves_nothing(client, admin, db):
    reply = client.post(
        "/api/tv-announcements/preview",
        json={"title": "All-hands at 3", "background": {"kind": "solid", "color": "#000000"}, "media_url": YOUTUBE},
    )
    shown = reply.json()
    assert shown["event_key"] == "announcement"
    assert shown["media_kind"] == "youtube"
    assert shown["media_id"] == "dQw4w9WgXcQ"
    assert shown["background"] == {"kind": "solid", "color": "#000000"}
    assert db.scalar(select(TvAnnouncement)) is None


def test_channels_to_choose_from(client, make_user, sign_in, db, org):
    make_channel(db, org, "Lobby")
    db.commit()
    sign_in(make_user("manager"))
    assert [c["name"] for c in client.get("/api/tv-announcements/channels").json()] == ["Lobby"]
