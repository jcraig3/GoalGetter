"""Organization → Assets (6.3).

What has to be true: a picture, a video and a sound can each be added, and
what each is comes from its bytes; art keeps its transparency and a photo is
fitted to a television; every file says where it is used; one in use cannot
be removed and the refusal says where; people's photographs stay out of it;
and only an admin can see or change any of it.
"""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.models import StoredAsset
from tests.test_background_video import mp4
from tests.test_walkup_audio import wav


@pytest.fixture
def admin(make_user, sign_in):
    return sign_in(make_user("admin", name="Admin"))


def png(width=600, height=600, alpha=True) -> bytes:
    out = io.BytesIO()
    if alpha:
        Image.new("RGBA", (width, height), (255, 0, 0, 0)).save(out, format="PNG")
    else:
        Image.new("RGB", (width, height), (255, 0, 0)).save(out, format="PNG")
    return out.getvalue()


def upload(client, data: bytes, name: str, content_type: str):
    return client.post(
        "/api/assets",
        content=data,
        headers={"content-type": content_type, "x-file-name": name},
    )


def test_a_picture_a_video_and_a_sound_can_each_be_added(client, admin):
    art = upload(client, png(), "Gold star.png", "image/png")
    clip = upload(client, mp4(seconds=5), "Loop.mp4", "video/mp4")
    sound = upload(client, wav(), "Airhorn.wav", "audio/wav")

    for reply, kind, name in ((art, "image", "Gold star"), (clip, "video", "Loop"),
                              (sound, "audio", "Airhorn")):
        assert reply.status_code == 201, reply.json()
        assert (reply.json()["kind"], reply.json()["name"]) == (kind, name)
        assert reply.json()["used_in"] == []

    listed = client.get("/api/assets").json()
    assert {a["name"] for a in listed} == {"Gold star", "Loop", "Airhorn"}


def test_what_a_file_is_comes_from_its_bytes_not_its_claim(client, admin):
    reply = upload(client, png(), "really-a-picture.mp3", "audio/mpeg")
    assert reply.status_code == 201, reply.json()
    assert reply.json()["kind"] == "image"


def test_art_keeps_its_transparency_and_a_photo_is_fitted_to_a_tv(client, admin):
    art = upload(client, png(2000, 2000, alpha=True), "badge.png", "image/png").json()
    photo = upload(client, png(4000, 3000, alpha=False), "office.png", "image/png").json()

    assert (art["content_type"], art["width"]) == ("image/png", 1024)
    assert photo["content_type"] == "image/jpeg"
    assert photo["width"] <= 1920 and photo["height"] <= 1080


def test_a_file_that_is_none_of_the_three_is_refused(client, admin):
    reply = upload(client, b"just some text", "notes.txt", "text/plain")
    assert reply.status_code == 400


def test_a_file_in_use_says_where_and_cannot_be_removed(client, db, org, admin):
    art = upload(client, png(alpha=False), "Backdrop.png", "image/png").json()
    org.appearance = {**(org.appearance or {}), "background": {"kind": "image", "asset": art["digest"]}}
    db.commit()

    listed = next(a for a in client.get("/api/assets").json() if a["digest"] == art["digest"])
    assert listed["used_in"] == [{"label": "The organization's background", "link": "/appearance"}]

    refused = client.delete(f"/api/assets/{art['digest']}")
    assert refused.status_code == 409
    assert "organization's background" in refused.json()["detail"]

    org.appearance = {}
    db.commit()
    assert client.delete(f"/api/assets/{art['digest']}").status_code == 204
    assert db.scalar(select(StoredAsset).where(StoredAsset.sha256 == art["digest"])) is None


def test_a_file_can_be_renamed(client, admin):
    art = upload(client, png(), "IMG_2041.png", "image/png").json()
    renamed = client.patch(f"/api/assets/{art['digest']}", json={"name": "  Trophy   art "})
    assert renamed.json()["name"] == "Trophy art"


def test_peoples_photos_are_labelled_with_whose_they_are(client, db, org, admin, make_user):
    """Phase 27: the Profile pics shelf — every person's photo, uploaded or
    synced, with their name. Removing one stays on their page."""
    from app import images

    alice = make_user("agent", name="Alice")
    alice.custom_photo_image_id = images.store(db, org.id, png(400, 400, alpha=False)).id
    bob = make_user("agent", name="Bob")
    blue = io.BytesIO()
    Image.new("RGB", (300, 300), (0, 0, 255)).save(blue, format="PNG")
    bob.tenant_photo_image_id = images.store(db, org.id, blue.getvalue()).id
    db.commit()

    assert client.get("/api/assets").json() == []
    listed = {a["photo_of"]: a["photo_source"] for a in client.get("/api/assets?photos=true").json()}
    assert listed == {"Alice": "uploaded", "Bob": "synced"}
    digest = next(a["digest"] for a in client.get("/api/assets?photos=true").json() if a["photo_of"] == "Alice")
    assert client.delete(f"/api/assets/{digest}").status_code == 409


def test_a_photo_can_come_from_the_library(client, db, org, admin, make_user):
    alice = make_user("agent", name="Alice")
    digest = upload(client, png(400, 400, alpha=False), "a.png", "image/png").json()["digest"]

    response = client.post(f"/api/users/{alice.id}/photo/from-library", json={"digest": digest})
    assert response.status_code == 200, response.text
    db.refresh(alice)
    assert alice.custom_photo_image_id is not None
    missing = client.post(f"/api/users/{alice.id}/photo/from-library", json={"digest": "0" * 64})
    assert missing.status_code == 404


def test_a_file_a_past_win_played_is_in_use(client, db, org, admin):
    from app.models import Notification

    digest = upload(client, png(), "cheer.png", "image/png").json()["digest"]
    db.add(Notification(organization_id=org.id, user_id=admin.id, event_key="t", subject_type="user", subject_id=1,
                        title="A win", media_url=f"image:{digest}"))
    db.commit()

    used = next(a for a in client.get("/api/assets").json() if a["digest"] == digest)["used_in"]
    assert [u["label"] for u in used] == ["Played for a past win"]


def test_managers_pick_and_add_but_only_an_admin_renames_or_removes(client, make_user, sign_in):
    """Phase 25: a manager making an announcement picks from the library and
    adds to it; looking after it stays an admin's."""
    sign_in(make_user("manager"))
    assert client.get("/api/assets").status_code == 200
    added = upload(client, png(), "x.png", "image/png")
    assert added.status_code == 201
    digest = added.json()["digest"]
    assert client.patch(f"/api/assets/{digest}", json={"name": "y"}).status_code == 403
    assert client.delete(f"/api/assets/{digest}").status_code == 403


def test_not_an_agent(client, make_user, sign_in):
    sign_in(make_user("agent"))
    assert client.get("/api/assets").status_code == 403
    assert upload(client, png(), "x.png", "image/png").status_code == 403
