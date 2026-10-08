"""Walk-up music as an uploaded video, and what each announcement is for.

**Why a walk-up can be a video file.** The announcement people want is the
music video filling the screen with the words over it, and no adverts. A
YouTube embed cannot be that: its uploader decides whether it shows ads,
nothing on this side may skip or hide them, and YouTube's embed rules forbid
anything in front of its player. An uploaded clip has none of those limits.

The checks are the ones background videos already pass, so they are not
repeated here beyond one — the HEVC refusal, because an iPhone video is the
single most likely thing somebody will upload as their walk-up.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app import channels as channel_service, media, notifications
from app.models import Channel, Notification
from tests.test_background_video import mp4


@pytest.fixture
def world(db, org, make_team, make_user):
    team = make_team("Enterprise")
    # On a team of his own: a manager also sees agents on no team at all, so
    # an unassigned Clark would be one of the manager's people.
    other = make_team("SMB")
    db.flush()
    return {
        "admin": make_user("admin", name="Admin"),
        "manager": make_user("manager", team, name="Manager"),
        "peter": make_user("agent", team, name="Peter Parker"),
        "clark": make_user("agent", other, name="Clark Kent"),
    }


def upload(client, data, user_id=None):
    query = f"?user_id={user_id}" if user_id else ""
    return client.post(
        f"/api/me/walkup/video{query}", content=data,
        headers={"Content-Type": "video/mp4"},
    )


# -- The scheme --------------------------------------------------------------


def test_an_uploaded_video_says_it_is_a_video():
    """Read off the one string that says what to play, like everything else."""
    assert media.kind_of("video:" + "a" * 64) == media.KIND_VIDEO


def test_an_uploaded_audio_clip_still_means_audio():
    """`asset:` predates video and keeps meaning audio, so nothing already
    stored changes meaning."""
    assert media.kind_of("asset:" + "a" * 64) == media.KIND_AUDIO


def test_the_wall_fetches_either_by_its_digest():
    assert media.asset_digest("video:" + "b" * 64) == "b" * 64


def test_a_malformed_digest_is_not_trusted():
    assert media.asset_digest("video:../../etc/passwd") is None


# -- Uploading one -----------------------------------------------------------


def test_somebody_uploads_their_own_walkup_video(client, db, world, sign_in):
    sign_in(world["peter"])

    reply = upload(client, mp4(seconds=12))

    assert reply.status_code == 200, reply.json()
    assert reply.json()["kind"] == "video"
    assert reply.json()["url"].startswith("video:")


def test_a_whole_music_video_plays_its_first_fifteen_seconds(
    client, db, world, sign_in
):
    """Cut to the cap, not refused: uploading a whole video is not a mistake."""
    sign_in(world["peter"])

    reply = upload(client, mp4(seconds=45))

    assert reply.json()["end_seconds"] == 15


def test_an_iphone_video_is_refused_with_how_to_fix_it(client, db, world, sign_in):
    """The most likely walk-up upload there is, and one a Chrome-based
    television often cannot play."""
    sign_in(world["peter"])

    reply = upload(client, mp4(codec=b"hvc1"))

    assert reply.status_code == 400
    assert "Most Compatible" in reply.json()["detail"]


def test_a_manager_uploads_one_for_their_own_person(client, db, world, sign_in):
    sign_in(world["manager"])

    assert upload(client, mp4(), user_id=world["peter"].id).status_code == 200


def test_a_manager_cannot_for_somebody_outside_their_team(
    client, db, world, sign_in
):
    sign_in(world["manager"])

    assert upload(client, mp4(), user_id=world["clark"].id).status_code in (403, 404)


def test_it_reaches_the_wall_as_a_video(client, db, org, world, sign_in):
    """Frozen onto the win when it happens, and offered to the wall with its
    kind, so the screen knows to fill itself with it."""
    sign_in(world["peter"])
    upload(client, mp4())

    clip = notifications.walkup_for(db, world["peter"].id)

    assert media.kind_of(clip["media_url"]) == media.KIND_VIDEO


# -- What each announcement is for -------------------------------------------


NOW = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def announce(db, org, person, event_key, title="Title"):
    db.add(
        Notification(
            organization_id=org.id, user_id=person.id, event_key=event_key,
            subject_type="goal", subject_id=1, title=title,
            about_name=person.full_name, about_user_id=person.id,
            created_at=NOW - timedelta(seconds=1),
        )
    )
    db.flush()


@pytest.mark.parametrize(
    ("event_key", "title", "expected"),
    [
        ("goal.achieved", "Calls this month achieved", "Goal hit"),
        ("recognition", "Great call!", "Recognition"),
        ("competition.won", "Peter won August sprint", "Competition won"),
        ("achievement:7", "Big deal", "Big deal"),
    ],
)
def test_every_announcement_says_what_it_is_for(
    db, org, world, event_key, title, expected
):
    """**The first thing anybody across the room reads**: why the music started,
    before whose name it is. An achievement's own name is its occasion."""
    channel = Channel(organization_id=org.id, name="Floor")
    db.add(channel)
    db.flush()
    announce(db, org, world["peter"], event_key, title)

    found = channel_service.celebrations(db, org, channel, now=NOW)

    assert [c.occasion for c in found] == [expected]
