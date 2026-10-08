"""Previewing somebody's walk-up announcement from their profile.

**Nothing is sent anywhere**, and the first test says so: a preview writes no
notification, so no wall is interrupted. That is the difference from the
"send a test to the wall" button removed in 4f, which interrupted every screen
in the building and would not go away.

The rest is that the preview is the real thing: the same parser as Save, the
same hold as the wall, the same fields a wall receives.
"""

import pytest
from sqlalchemy import select

from app import events, media
from app.models import Notification
from tests.test_background_video import mp4

YOUTUBE = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture
def world(db, org, make_team, make_user):
    team = make_team("Enterprise")
    other = make_team("SMB")
    db.flush()
    return {
        "manager": make_user("manager", team, name="Manager"),
        "peter": make_user("agent", team, name="Peter Parker"),
        "clark": make_user("agent", other, name="Clark Kent"),
    }


def preview(client, user_id=None, **body):
    query = f"?user_id={user_id}" if user_id else ""
    return client.post(f"/api/me/walkup/preview{query}", json=body)


def test_a_preview_reaches_no_wall(client, db, world, sign_in):
    """**The property the button rests on.**"""
    sign_in(world["peter"])

    preview(client, url=YOUTUBE)

    assert db.scalars(select(Notification)).all() == []


def test_it_previews_the_link_as_typed_before_saving(client, db, world, sign_in):
    sign_in(world["peter"])

    body = preview(client, url=YOUTUBE, start_seconds=42).json()

    assert (body["media_kind"], body["media_id"], body["media_start_seconds"]) == (
        "youtube", "dQw4w9WgXcQ", 42,
    )


def test_it_holds_the_screen_as_long_as_the_wall_would(client, db, world, sign_in):
    """A preview that ran a different length would be previewing something
    else."""
    sign_in(world["peter"])

    body = preview(client, url=YOUTUBE, start_seconds=10).json()

    assert body["hold_seconds"] == media.MAX_CLIP_SECONDS


def test_it_is_the_announcement_a_wall_would_show(client, db, world, sign_in):
    sign_in(world["peter"])

    body = preview(client, url=YOUTUBE).json()

    assert (body["occasion"], body["about_name"]) == ("Recognition", "Peter Parker")


def test_a_bad_link_is_refused_with_the_same_words_save_uses(
    client, db, world, sign_in
):
    """So a link the preview accepts is one Save will accept."""
    sign_in(world["peter"])

    previewed = preview(client, url="https://example.com/song")
    saved = client.put("/api/me/walkup", json={"url": "https://example.com/song"})

    assert previewed.status_code == 422
    assert previewed.json()["detail"] == saved.json()["detail"]


def test_with_nothing_typed_it_previews_what_is_saved(client, db, world, sign_in):
    """Which is how an uploaded clip is previewed — an upload saves at once."""
    sign_in(world["peter"])
    client.post(
        "/api/me/walkup/video", content=mp4(seconds=8),
        headers={"Content-Type": "video/mp4"},
    )

    body = preview(client).json()

    assert body["media_kind"] == "video"
    assert body["media_digest"]
    assert body["hold_seconds"] == 8


def test_with_nothing_at_all_it_is_a_plain_announcement(client, db, world, sign_in):
    sign_in(world["peter"])

    body = preview(client).json()

    assert body["media_url"] is None
    assert body["hold_seconds"] == events.CELEBRATION_HOLD_SECONDS


def test_a_manager_previews_their_own_persons(client, db, world, sign_in):
    sign_in(world["manager"])

    reply = preview(client, user_id=world["peter"].id, url=YOUTUBE)

    assert reply.status_code == 200
    assert reply.json()["about_name"] == "Peter Parker"


def test_a_manager_cannot_preview_somebody_elses(client, db, world, sign_in):
    sign_in(world["manager"])

    assert preview(client, user_id=world["clark"].id).status_code == 404
