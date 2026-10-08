"""A photograph from the directory, and one somebody chose instead.

**Two slots, and that is what makes "revert" mean anything.** With a single one a
sync would overwrite an upload at three the next morning, or the upload would win
for ever and there would be nothing to revert *to*.
"""

import io

import pytest
from PIL import Image

from app import photos
from app.models import StoredAsset


def made(colour=(120, 90, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (600, 600), colour).save(out, format="JPEG")
    return out.getvalue()


TENANT = made((10, 120, 30))
CHOSEN = made((200, 40, 40))


# ── Which one wins ───────────────────────────────────────────────────────────


def test_nobody_starts_with_a_photograph(db, org, make_user):
    """Initials are not a failure case — they are what most people have."""
    user = make_user("agent")

    assert photos.digest_of(db, user) is None
    assert user.photo_digest is None


def test_the_directorys_photograph_is_used_when_it_is_the_only_one(db, org, make_user):
    user = make_user("agent")
    row = photos.set_tenant(db, user, TENANT, etag="W/\"abc\"")

    assert photos.digest_of(db, user) == row.sha256


def test_a_chosen_photograph_beats_the_directorys(db, org, make_user):
    """Somebody picking a photograph of themselves is more recent and more
    deliberate than whatever was uploaded when they joined."""
    user = make_user("agent")
    photos.set_tenant(db, user, TENANT, etag="W/\"abc\"")
    chosen = photos.set_custom(db, user, CHOSEN)

    assert photos.digest_of(db, user) == chosen.sha256


def test_a_sync_does_not_overwrite_what_somebody_chose(db, org, make_user):
    """**The reason there are two columns.** A nightly sync must not quietly
    replace the face somebody picked."""
    user = make_user("agent")
    chosen = photos.set_custom(db, user, CHOSEN)

    photos.set_tenant(db, user, TENANT, etag="W/\"new\"")

    assert photos.digest_of(db, user) == chosen.sha256


def test_reverting_falls_back_to_the_directory(db, org, make_user):
    user = make_user("agent")
    tenant = photos.set_tenant(db, user, TENANT, etag="W/\"abc\"")
    photos.set_custom(db, user, CHOSEN)

    photos.forget_custom(db, user)

    assert photos.digest_of(db, user) == tenant.sha256


def test_reverting_with_no_directory_photograph_falls_back_to_initials(
    db, org, make_user
):
    user = make_user("agent")
    photos.set_custom(db, user, CHOSEN)

    photos.forget_custom(db, user)

    assert photos.digest_of(db, user) is None


def test_reverting_keeps_the_image_itself(db, org, make_user):
    """It is content-addressed and may be somebody else's photograph too."""
    from sqlalchemy import func, select

    user = make_user("agent")
    photos.set_custom(db, user, CHOSEN)
    photos.forget_custom(db, user)

    assert db.scalar(select(func.count()).select_from(StoredAsset)) == 1


# ── What the directory hands over ────────────────────────────────────────────


def test_an_unreadable_directory_photograph_does_not_stop_the_sync(db, org, make_user):
    """One bad photo in a tenant of four hundred must not fail the run — and the
    tag is still recorded, so it is not fetched again every night."""
    user = make_user("agent")

    result = photos.set_tenant(db, user, b"not an image", etag="W/\"bad\"")

    assert result is None
    assert user.tenant_photo_image_id is None
    assert user.tenant_photo_etag == "W/\"bad\""


def test_the_tag_is_recorded_so_it_is_fetched_once(db, org, make_user):
    user = make_user("agent")
    photos.set_tenant(db, user, TENANT, etag="W/\"abc\"")

    assert user.tenant_photo_etag == "W/\"abc\""


# ── Through the API ──────────────────────────────────────────────────────────


def test_somebody_can_set_their_own(client, db, org, make_user, sign_in):
    me = make_user("agent")
    sign_in(me)
    db.commit()

    reply = client.post(f"/api/users/{me.id}/photo", content=CHOSEN)

    assert reply.status_code == 200
    assert reply.json()["photo_digest"]


def test_an_agent_cannot_set_somebody_elses(client, db, org, make_user, sign_in):
    """It is the one piece of profile that is personal rather than
    organizational, and letting a colleague put a picture on your account has
    invented a prank."""
    sign_in(make_user("agent"))
    other = make_user("agent")
    db.commit()

    reply = client.post(f"/api/users/{other.id}/photo", content=CHOSEN)

    assert reply.status_code == 403


def test_a_manager_can(client, db, org, make_user, sign_in):
    """Most people here never sign in — the directory made their account — so
    somebody has to be able to upload a face on their behalf."""
    sign_in(make_user("manager"))
    other = make_user("agent")
    db.commit()

    assert client.post(f"/api/users/{other.id}/photo", content=CHOSEN).status_code == 200


def test_an_admin_can(client, db, org, make_user, sign_in):
    sign_in(make_user("admin"))
    other = make_user("agent")
    db.commit()

    assert client.post(f"/api/users/{other.id}/photo", content=CHOSEN).status_code == 200


def test_a_file_that_is_not_an_image_is_refused_with_a_reason(
    client, db, org, make_user, sign_in
):
    me = make_user("agent")
    sign_in(me)
    db.commit()

    reply = client.post(f"/api/users/{me.id}/photo", content=b"MZ\x90\x00 nope")

    assert reply.status_code == 400
    assert "image" in reply.json()["detail"].lower()


def test_reverting_through_the_api(client, db, org, make_user, sign_in):
    me = make_user("agent")
    sign_in(me)
    photos.set_tenant(db, me, TENANT, etag="W/\"abc\"")
    db.commit()
    client.post(f"/api/users/{me.id}/photo", content=CHOSEN)

    reply = client.delete(f"/api/users/{me.id}/photo")

    assert reply.status_code == 200
    # Back to the directory's, not to nothing.
    assert reply.json()["photo_digest"]
    assert reply.json()["photo_digest"] != _digest(CHOSEN)


def _digest(raw: bytes) -> str:
    import hashlib

    from app import images

    data, _, _ = images.normalise(raw)
    return hashlib.sha256(data).hexdigest()
