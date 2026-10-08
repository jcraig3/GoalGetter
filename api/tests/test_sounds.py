"""Sounds for celebrations (6.17): the starter pack, choosing one, rules and
the organization's defaults."""

import io
import wave
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app import channels as channel_service, events, notifications, sound_pack
from app.models import Channel, StoredAsset, WalkupMedia


@pytest.fixture
def world(db, org, make_team, make_user, make_metric):
    team = make_team("Sales")
    return {
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", team, name="Manager"),
        "ann": make_user("agent", team, name="Ann"),
        "metric": make_metric("deals"),
    }


def test_every_pack_sound_is_a_short_real_wav():
    for sound in sound_pack.PACK:
        with wave.open(io.BytesIO(sound_pack.wav(sound.key))) as file:
            seconds = file.getnframes() / file.getframerate()
            assert file.getnchannels() == 1 and file.getsampwidth() == 2
        assert 0.5 < seconds <= 4.0, sound.key


def test_the_pack_is_the_same_every_time():
    sound_pack.wav.cache_clear()
    first = sound_pack.wav("applause")
    sound_pack.wav.cache_clear()
    assert sound_pack.wav("applause") == first


def test_the_picker_lists_the_pack_and_the_organizations_own(client, db, org, world, sign_in):
    sign_in(world["admin"])
    body = client.get("/api/sounds").json()
    assert [s["key"] for s in body["pack"]][:3] == ["fanfare", "chime", "gong"]
    assert body["library"] == []
    assert {k["key"] for k in body["kinds"]} == {"goal", "competition", "recognition", "occasion"}

    played = client.get("/api/sounds/pack/gong")
    assert played.status_code == 200
    assert played.headers["content-type"] == "audio/wav"


def test_an_agent_has_no_picker(client, world, sign_in):
    sign_in(world["ann"])
    assert client.get("/api/sounds").status_code == 403


def test_choosing_a_pack_sound_keeps_one_copy(client, db, org, world, sign_in):
    sign_in(world["admin"])
    kept = client.post("/api/sounds/pack/fanfare/keep").json()
    again = client.post("/api/sounds/pack/fanfare/keep").json()
    assert kept == again
    assert kept["url"].startswith("asset:") and kept["name"] == "Fanfare"
    rows = db.scalars(select(StoredAsset).where(StoredAsset.organization_id == org.id)).all()
    assert len(rows) == 1 and rows[0].content_type.startswith("audio/")
    # Now one of the organization's own.
    assert [s["name"] for s in client.get("/api/sounds").json()["library"]] == ["Fanfare"]


def test_somebodys_walk_up_is_not_offered(client, db, org, world, sign_in):
    sign_in(world["admin"])
    kept = client.post("/api/sounds/pack/chime/keep").json()
    db.add(WalkupMedia(user_id=world["ann"].id, url=kept["url"], start_seconds=0, end_seconds=3))
    db.flush()
    assert client.get("/api/sounds").json()["library"] == []


def test_a_rule_can_play_a_stored_sound(client, db, org, world, sign_in):
    sign_in(world["admin"])
    kept = client.post("/api/sounds/pack/ka-ching/keep").json()
    response = client.post(
        "/api/achievement-rules",
        json={
            "name": "Big deal", "metric_id": world["metric"].id, "comparator": "gte",
            "threshold": "5", "scope": "everyone", "message": "{name} closed a big one",
            "media_url": kept["url"],
        },
    )
    assert response.status_code in (200, 201), response.json()
    assert response.json()["media_url"] == kept["url"]
    assert response.json()["media_kind"] == "audio"

    # And Assets knows where it is used.
    listed = next(a for a in client.get("/api/assets").json() if a["digest"] == kept["url"][6:])
    assert listed["used_in"][0]["label"] == "Celebration “Big deal”"


def test_a_rule_cannot_name_another_organizations_sound(client, db, world, sign_in):
    sign_in(world["admin"])
    response = client.post(
        "/api/achievement-rules",
        json={
            "name": "Big deal", "metric_id": world["metric"].id, "comparator": "gte",
            "threshold": "5", "scope": "everyone", "message": "{name} closed one",
            "media_url": "asset:" + "a" * 64,
        },
    )
    assert response.status_code == 422


def test_a_default_plays_when_the_person_has_none(client, db, org, world, sign_in):
    sign_in(world["admin"])
    gong = client.post("/api/sounds/pack/gong/keep").json()["url"]
    saved = client.put("/api/sounds/defaults", json={"goal": gong, "recognition": None})
    assert saved.status_code == 200 and saved.json() == {"goal": gong}

    channel = Channel(organization_id=org.id, name="Wall")
    db.add(channel)
    notifications.emit(
        db, org_id=org.id, user_id=world["ann"].id, event=events.GOAL_ACHIEVED,
        subject_type="goal", subject_id=1, title="Ann hit her target",
        about_name="Ann", about_user_id=world["ann"].id,
    )
    db.flush()
    db.refresh(org)

    wins = channel_service.celebrations(db, org, channel, now=datetime.now(UTC))
    assert wins[0].media_url == gong
    assert wins[0].media_kind == "audio"
    assert wins[0].media_digest == gong[6:]


def test_the_persons_own_walk_up_still_wins(client, db, org, world, sign_in):
    sign_in(world["admin"])
    gong = client.post("/api/sounds/pack/gong/keep").json()["url"]
    client.put("/api/sounds/defaults", json={"goal": gong})
    channel = Channel(organization_id=org.id, name="Wall")
    db.add(channel)
    notifications.emit(
        db, org_id=org.id, user_id=world["ann"].id, event=events.GOAL_ACHIEVED,
        subject_type="goal", subject_id=2, title="Ann hit her target",
        about_name="Ann", about_user_id=world["ann"].id,
        media_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", media_start_seconds=0,
        media_end_seconds=10,
    )
    db.flush()
    db.refresh(org)
    wins = channel_service.celebrations(db, org, channel, now=datetime.now(UTC))
    assert wins[0].media_kind == "youtube"


def test_defaults_are_an_admins_and_must_be_sounds(client, db, world, sign_in):
    sign_in(world["manager"])
    assert client.put("/api/sounds/defaults", json={}).status_code == 403
    sign_in(world["admin"])
    assert client.put("/api/sounds/defaults", json={"birthday": None}).status_code == 422
    assert client.put("/api/sounds/defaults", json={"goal": "asset:" + "b" * 64}).status_code == 422
