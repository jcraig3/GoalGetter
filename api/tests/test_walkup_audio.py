"""Uploading a walk-up clip instead of pasting a link.

**A link was never an answer for most people.** Pasting a YouTube address means
finding the song, copying the URL and knowing which second to start at — which
is most of the reason a floor ends up with three songs between forty people.
What everybody has is a file.
"""

import struct

import pytest

from app import audio, media


def wav(seconds: float = 1.0) -> bytes:
    """A real WAV of silence, built rather than fixtured.

    A binary fixture in the repository is a file nobody can read in a review,
    and this one is eight lines.
    """
    rate = 8000
    frames = b"\x80" * int(rate * seconds)
    header = b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate, 1, 8)
    header += b"data" + struct.pack("<I", len(frames))
    return header + frames


@pytest.fixture
def world(db, org, make_team, make_user):
    enterprise = make_team("Enterprise")
    db.flush()
    return {
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", enterprise, name="Manager"),
        "peter": make_user("agent", enterprise, name="Peter Parker"),
        "clark": make_user("agent", enterprise, name="Clark Kent"),
    }


# -- The file itself ---------------------------------------------------------


def test_a_real_clip_is_accepted_and_measured():
    data, content_type, duration_ms = audio.normalise(wav(2))

    assert content_type == "audio/wav"
    assert 1900 <= duration_ms <= 2100
    assert data


def test_something_that_is_not_audio_says_so():
    with pytest.raises(audio.AudioProblem) as problem:
        audio.normalise(b"this is not a sound")

    assert "audio file" in str(problem.value)


def test_an_empty_file_says_so():
    with pytest.raises(audio.AudioProblem):
        audio.normalise(b"")


def test_a_file_too_large_is_refused_by_size():
    with pytest.raises(audio.AudioProblem) as problem:
        audio.normalise(b"\x00" * (audio.MAX_UPLOAD_BYTES + 1))

    assert "MB" in str(problem.value)


def test_a_long_track_is_cut_rather_than_refused():
    """**Somebody uploading a whole song has not made a mistake.** Playing its
    first fifteen seconds is what they expect; stopping the rotation for three
    minutes is not."""
    assert audio.clip_seconds(200_000) == audio.MAX_SECONDS


def test_a_short_clip_keeps_its_own_length():
    assert audio.clip_seconds(4_000) == 4


def test_a_clip_of_unknown_length_gets_the_cap():
    """Rather than zero, which would hold the screen for no time at all."""
    assert audio.clip_seconds(None) == audio.MAX_SECONDS


# -- Uploading one -----------------------------------------------------------


def upload(client, raw, user_id=None):
    query = f"?user_id={user_id}" if user_id else ""
    return client.post(f"/api/me/walkup/audio{query}", content=raw)


def test_somebody_can_upload_their_own(client, db, world, sign_in):
    sign_in(world["peter"])

    reply = upload(client, wav(3))

    assert reply.status_code == 200, reply.json()
    assert reply.json()["kind"] == "audio"


def test_it_is_stored_by_content_rather_than_by_name(client, db, world, sign_in):
    """**The scheme is the whole design.** Everything downstream carries one
    string for "what to play"; a parallel id column would be a pair that can
    disagree about what a wall is doing."""
    sign_in(world["peter"])

    url = upload(client, wav(3)).json()["url"]

    assert url.startswith(media.ASSET_SCHEME)
    assert media.asset_digest(url)


def test_the_clip_is_trimmed_to_its_own_length(client, db, world, sign_in):
    sign_in(world["peter"])

    body = upload(client, wav(4)).json()

    assert body["start_seconds"] == 0
    assert body["end_seconds"] == 4


def test_a_long_upload_is_trimmed_to_the_cap(client, db, world, sign_in):
    sign_in(world["peter"])

    body = upload(client, wav(40)).json()

    assert body["end_seconds"] == audio.MAX_SECONDS


def test_a_manager_can_upload_for_somebody(client, db, world, sign_in):
    """Plenty of people never open their own settings, and a wall with no music
    is the result."""
    sign_in(world["manager"])

    reply = upload(client, wav(3), user_id=world["peter"].id)

    assert reply.status_code == 200, reply.json()


def test_an_agent_cannot_upload_for_somebody_else(client, db, world, sign_in):
    sign_in(world["clark"])

    assert upload(client, wav(3), user_id=world["peter"].id).status_code == 403


def test_a_bad_file_is_refused_with_a_message(client, db, world, sign_in):
    sign_in(world["peter"])

    reply = upload(client, b"not audio")

    assert reply.status_code == 400
    assert "audio" in reply.json()["detail"].lower()


def test_the_same_clip_twice_is_one_row(client, db, org, world, sign_in):
    """Content-addressed, like every other asset."""
    from sqlalchemy import func, select

    from app.models import StoredAsset

    sign_in(world["peter"])
    raw = wav(3)
    upload(client, raw)
    before = db.scalar(select(func.count()).select_from(StoredAsset))

    sign_in(world["clark"])
    upload(client, raw)

    assert db.scalar(select(func.count()).select_from(StoredAsset)) == before


def test_uploading_replaces_a_link(client, db, world, sign_in):
    """One clip per person — the person is the key."""
    sign_in(world["peter"])
    client.put(
        "/api/me/walkup", json={"url": "https://youtu.be/dQw4w9WgXcQ"}
    )

    body = upload(client, wav(3)).json()

    assert body["kind"] == "audio"


# -- Reaching a wall ---------------------------------------------------------


def test_a_wall_is_given_the_digest_rather_than_a_path(
    client, db, org, world, sign_in
):
    """**The wall builds its own URL from a digest**, exactly as it does for a
    face — so nothing on a screen has to learn what the `asset:` scheme is, and
    the clip is fetched through the token that already scopes that display."""
    from app import notifications
    from app.models import Notification

    sign_in(world["peter"])
    upload(client, wav(3))
    db.commit()

    sign_in(world["admin"])
    db.add(
        Notification(
            organization_id=org.id,
            user_id=world["peter"].id,
            event_key="goal.achieved",
            subject_type="goal",
            subject_id=1,
            title="Calls achieved",
            about_name="Peter Parker",
            about_user_id=world["peter"].id,
            **notifications.walkup_for(db, world["peter"].id),
        )
    )
    db.commit()

    channel = client.post("/api/channels", json={"name": "Floor"}).json()
    created = client.post(
        "/api/displays", json={"name": "TV", "channel_id": channel["id"]}
    ).json()
    token = created["url"].rsplit("/", 1)[-1]
    client.cookies.clear()
    card = client.get(f"/api/display/{token}/celebrations").json()["celebrations"][0]

    assert card["media_kind"] == "audio"
    assert len(card["media_digest"]) == 64
    # And the screen can actually fetch it with the token it already has.
    assert (
        client.get(f"/api/display/{token}/assets/{card['media_digest']}").status_code
        == 200
    )


def test_it_is_served_as_audio(client, db, org, world, sign_in):
    """A browser given `application/octet-stream` will not play it."""
    from sqlalchemy import select

    from app.models import StoredAsset

    sign_in(world["peter"])
    upload(client, wav(3))
    db.commit()
    digest = db.scalars(select(StoredAsset.sha256)).first()

    reply = client.get(f"/api/images/{digest}")

    assert reply.headers["content-type"] == "audio/wav"


# -- Chosen from Assets (8.1) --------------------------------------------------


def test_a_sound_already_in_assets_can_be_chosen(client, db, org, world, sign_in):
    """The review found a bare file input as the only way in; the library's
    sounds are the other half of it."""
    from app import assets

    data, content_type, duration_ms = audio.normalise(wav(3))
    stored = assets.keep(db, org.id, data, content_type=content_type, duration_ms=duration_ms)
    db.commit()
    sign_in(world["admin"])

    response = client.put(
        f"/api/me/walkup/asset?user_id={world['peter'].id}", json={"digest": stored.sha256}
    )

    assert response.status_code == 200, response.json()
    assert response.json()["kind"] == "audio"
    from app.models import WalkupMedia

    row = db.get(WalkupMedia, world["peter"].id)
    db.refresh(row)
    assert row.url == f"{media.ASSET_SCHEME}{stored.sha256}"
    assert 2 <= row.end_seconds <= 4


def test_only_a_file_that_plays_and_is_ours(client, db, org, world, sign_in):
    sign_in(world["admin"])

    response = client.put("/api/me/walkup/asset", json={"digest": "0" * 64})

    assert response.status_code == 404
    assert "sound or a video" in response.json()["detail"]
